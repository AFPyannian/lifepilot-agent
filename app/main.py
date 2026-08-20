import logging

from langchain_core.messages import (
    HumanMessage,
    ToolMessage,
)

# LangGraph 状态存档器
from app.checkpointing import (
    open_sqlite_checkpointer,
)
# 读取项目配置
from app.config import (
    apply_runtime_environment,
    get_settings,
)
from app.exceptions import (
    ConfigurationError,
    LifePilotError,
)
from app.graph import build_graph
from app.logging_config import (
    configure_logging,
    shutdown_logging,
)

# 创建main.py的日志记录器
logger = logging.getLogger("lifepilot.main")


def run_chat(graph, thread_id: str) -> None:
    """负责一次持续性的会话"""

    # LangGraph配置: checkpointer 利用 thread_id，查找checkpointer保存的对应会话状态。
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    print(f"\nLifePilot 已启动，输入 exit、quit 或 退出，可以结束程序。当前会话ID：{thread_id}")

    # 日志: 记录会话开始
    logger.info(
        "Conversation started thread_id=%s",
        thread_id,
    )

    while True:
        # 会话的一次输入
        user_input = input("\n你：").strip()
        # 输入检查(退出条件)
        if user_input.lower() in {"exit", "quit", "退出"}:
            print("LifePilot：再见！")

            logger.info(
                "Conversation ended thread_id=%s",
                thread_id,
            )
            break
        # 输入约束(不能为空)
        if not user_input:
            print("LifePilot：请输入有效内容。")
            continue

        print("\nLifePilot 正在思考……")

        try:
            # 传入消息+之前状态，执行执行一次 LangGraph 工作流，保存最新完整状态。
            result = graph.invoke(
                {
                    "messages": [
                        HumanMessage(content=user_input),
                    ],
                },
                # 同步thread_id。因此可以加载本会话之前状态，并将新的HumanMessage添加进去。
                config=config,
            )
        # 可预料的异常
        except LifePilotError as error:
            # 记录真正的异常日志，供开发者参考
            logger.exception(
                "Expected application error "
                "thread_id=%s",
                thread_id,
            )
            # 对用户隐藏内部错误，转而展示友好消息。(防止泄露数据给用户，或输出用户不理解的技术异常)
            print(
                f"\nLifePilot：{error.user_message}"
            )
            continue
        # 未预料的异常
        except Exception:
            logger.exception(
                "Unexpected Agent error "
                "thread_id=%s",
                thread_id,
            )
            print(
                "\nLifePilot：发生了未预期的错误，"
                "请稍后重试。"
            )
            continue

        # 从最新完整状态中取得最后的回答结果
        final_message = result["messages"][-1]

        # 打印最终回答结果
        print("\nLifePilot：")
        print(final_message.content)

        # 统计工具消息数量
        tool_message_count = sum(
            isinstance(message, ToolMessage) for message in result["messages"]
        )

        # 记录单轮对话完成日志
        logger.info(
            "Agent turn completed thread_id=%s messages=%d tools=%d",
            thread_id,
            len(result["messages"]),
            tool_message_count,
        )

        # # 打印会话的全部消息数量
        # print(
        #     f"\n[调试信息] "
        #     f"当前会话共有 {len(result['messages'])} 条消息，"
        #     f"累计执行工具 {tool_message_count} 次。"
        # )


def main() -> None:
    """Start LifePilot with persistent checkpoints."""
    # 读取配置
    try:
        settings = get_settings()
    except ConfigurationError as error:
        print(f"LifePilot 启动失败：{error.user_message}")
        return
    # 应用运行配置
    apply_runtime_environment(settings)
    # 启动日志系统
    configure_logging(settings)

    # 日志: 记录应用启动
    logger.info(
        "Application starting model=%s owner_id=%s",
        settings.deepseek_model,
        settings.owner_id,
    )

    try:
        # 输入自定义会话名称
        thread_id = input(
            f"请输入会话ID（直接回车默认使用 {settings.default_thread_id} 会话）："
        ).strip()
        # 设置无输入直接回车时，默认使用 main 会话
        if not thread_id:
            thread_id = settings.default_thread_id

        # 打开 SQLite checkpointer
        with open_sqlite_checkpointer(
                settings.checkpoint_database_path
        ) as checkpointer:
            # 构建 Graph
            graph = build_graph(
                settings=settings,
                checkpointer=checkpointer,
                owner_id=settings.owner_id,
            )
            # 进入聊天循环
            run_chat(
                graph=graph,
                thread_id=thread_id,
            )
    # 用户终止程序
    except KeyboardInterrupt:
        logger.warning("Application interrupted by user.")
        print("\nLifePilot：程序已由用户终止。")
    # 预期异常
    except LifePilotError as error:
        logger.exception("Application startup failed.")
        print(f"LifePilot 启动失败：{error.user_message}")
    # 非预期异常
    except Exception:
        logger.exception("Unexpected application failure.")
        print("LifePilot 启动失败：发生了未预期的错误。")
    # 程序结束输出(无论如何结束都输出)
    finally:
        logger.info("Application stopped.")
        shutdown_logging()

if __name__ == "__main__":
    main()