"""提供 LifePilot 命令行交互入口。"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from app.checkpointing import open_sqlite_checkpointer
from app.config import apply_runtime_environment, get_settings
from app.credentials.crypto import CredentialCipher
from app.credentials.service import ProviderCredentialService
from app.exceptions import ConfigurationError, LifePilotError
from app.graph import build_graph
from app.identity import AgentContext, checkpoint_config
from app.logging_config import configure_logging, shutdown_logging
from app.model import DeepSeekCredentialValidator
from app.model_gateway import DeepSeekModelGateway
from app.observability import configure_observability
from app.repositories.provider_credential_repository import (
    ProviderCredentialRepository,
)

logger = logging.getLogger("lifepilot.main")


def display_graph_result(
    result: dict[str, Any],
    thread_id: str,
) -> None:
    """显示最新模型回答并记录本轮工具调用数量。"""

    messages = result.get("messages", [])
    if not messages:
        print("\nLifePilot：本轮执行已经完成，但没有生成可显示的消息。")
        return
    final_message = messages[-1]

    print("\nLifePilot：")
    print(final_message.content)

    tool_message_count = sum(isinstance(message, ToolMessage) for message in messages)

    logger.info(
        "Agent turn completed thread_id=%s messages=%d tools=%d",
        thread_id,
        len(messages),
        tool_message_count,
    )


def has_pending_execution(
    graph: Any,
    config: dict[str, Any],
) -> bool:
    """判断指定会话是否仍有待执行的 LangGraph 节点。"""
    try:
        snapshot = graph.get_state(config)

        return bool(snapshot.next)

    except Exception:
        logger.exception("Failed to inspect pending graph state.")

        return True


def resume_pending_execution(
    graph: Any,
    config: dict[str, Any],
    thread_id: str,
    context: AgentContext,
) -> dict[str, Any] | None:
    """从 Checkpoint 恢复当前会话的未完成执行。"""
    snapshot = graph.get_state(config)

    if not snapshot.next:
        return None

    logger.warning(
        "Pending graph execution detected thread_id=%s next_nodes=%s",
        thread_id,
        snapshot.next,
    )

    print("\n检测到这个会话上一次没有执行完成，正在从保存点继续……")

    return graph.invoke(
        None,
        config=config,
        context=context,
    )


def run_chat(
    graph: Any,
    thread_id: str,
    user_id: str,
) -> None:
    """运行支持中断恢复的命令行多轮会话。"""

    config = checkpoint_config(user_id, thread_id)
    context = AgentContext(user_id=user_id)

    print(
        f"\nLifePilot 已启动，输入 exit、quit 或 退出，可以结束程序。当前会话ID：{thread_id}"
    )

    logger.info(
        "Conversation started thread_id=%s",
        thread_id,
    )

    try:
        recovered_result = resume_pending_execution(
            graph=graph,
            config=config,
            thread_id=thread_id,
            context=context,
        )

        if recovered_result is not None:
            display_graph_result(
                result=recovered_result,
                thread_id=thread_id,
            )
    except LifePilotError as error:
        logger.exception(
            "Pending graph recovery failed thread_id=%s",
            thread_id,
        )

        print(f"\nLifePilot：{error.user_message}")

        print(
            "\n当前会话仍保留在未完成状态。"
            "请先解决模型或工具故障，"
            "然后重新启动并继续使用同一个会话ID。"
        )

        return
    except Exception:
        logger.exception(
            "Unexpected pending graph recovery failure thread_id=%s",
            thread_id,
        )

        print("\nLifePilot：恢复上一次执行时发生了未预期错误。")

        print("为避免损坏会话历史，当前会话暂不接受新消息。")

        return

    while True:
        user_input = input("\n你：").strip()

        if user_input.lower() in {"exit", "quit", "退出"}:
            print("LifePilot：再见！")

            logger.info(
                "Conversation ended thread_id=%s",
                thread_id,
            )
            break

        if not user_input:
            print("LifePilot：请输入有效内容。")
            continue

        print("\nLifePilot 正在思考……")

        try:
            result = graph.invoke(
                {
                    "messages": [
                        HumanMessage(content=user_input),
                    ],
                    "model_mode": "PLATFORM",
                },
                config=config,
                context=context,
            )

        except LifePilotError as error:
            logger.exception(
                "Expected application error thread_id=%s",
                thread_id,
            )

            print(f"\nLifePilot：{error.user_message}")

            if has_pending_execution(
                graph,
                config,
            ):
                print("\n本轮工作流尚未完成，执行状态已经保存在checkpoint中。")

                print(
                    "程序将暂停接收新消息。"
                    "解决模型或工具问题后，"
                    "重新启动并输入相同会话ID，"
                    "程序会自动继续。"
                )

                return

            continue

        except Exception:
            logger.exception(
                "Unexpected Agent error thread_id=%s",
                thread_id,
            )
            print("\nLifePilot：发生了未预期的错误，请稍后重试。")

            if has_pending_execution(
                graph,
                config,
            ):
                print(
                    "当前工作流仍未完成。为避免破坏工具消息顺序，程序将暂停当前会话。"
                )

                return

            continue

        display_graph_result(
            result=result,
            thread_id=thread_id,
        )


def main() -> None:
    """初始化配置、日志和 Checkpointer，并启动命令行会话。"""

    try:
        settings = get_settings()
    except ConfigurationError as error:
        print(f"LifePilot 启动失败：{error.user_message}")
        return

    apply_runtime_environment(settings)

    configure_logging(settings)

    configure_observability(settings)

    logger.info(
        "Application starting model=%s owner_id=%s",
        settings.deepseek_model,
        settings.local_cli_owner_id,
    )

    try:
        thread_id = input(
            f"请输入会话ID（直接回车默认使用 {settings.default_thread_id} 会话）："
        ).strip()

        if not thread_id:
            thread_id = settings.default_thread_id

        with open_sqlite_checkpointer(
            settings.checkpoint_database_path
        ) as checkpointer:
            credential_repository = ProviderCredentialRepository(
                settings.app_database_path
            )
            credential_keyring = settings.provider_credential_keyring()
            credential_service = ProviderCredentialService(
                repository=credential_repository,
                cipher=(
                    CredentialCipher(
                        keyring=credential_keyring,
                        active_key_version=(
                            settings.provider_credential_active_key_version
                        ),
                    )
                    if credential_keyring
                    else None
                ),
                validator=DeepSeekCredentialValidator(settings),
            )
            model_gateway = DeepSeekModelGateway(
                settings=settings,
                credential_service=credential_service,
            )
            graph = build_graph(
                settings=settings,
                checkpointer=checkpointer,
                model_gateway=model_gateway,
            )

            run_chat(
                graph=graph,
                thread_id=thread_id,
                user_id=settings.local_cli_owner_id,
            )

    except KeyboardInterrupt:
        logger.warning("Application interrupted by user.")
        print("\nLifePilot：程序已由用户终止。")

    except LifePilotError as error:
        logger.exception("Application startup failed.")
        print(f"LifePilot 启动失败：{error.user_message}")

    except Exception:
        logger.exception("Unexpected application failure.")
        print("LifePilot 启动失败：发生了未预期的错误。")

    finally:
        logger.info("Application stopped.")
        shutdown_logging()


if __name__ == "__main__":
    main()
