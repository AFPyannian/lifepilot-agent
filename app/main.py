from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import (
    HumanMessage,
    ToolMessage,
)

from app.checkpointing import (
    open_sqlite_checkpointer,
)
from app.graph import build_graph

# 计算项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 设置检查点数据库路径(拼接得到路径), 数据库用于保存 LangGraph 会话状态.
CHECKPOINT_DATABASE_PATH = (PROJECT_ROOT / "data" / "checkpoints.db")


def run_chat(graph, thread_id: str) -> None:
    """运行一个可以持久化保存的会话线程."""

    # LangGraph配置: checkpointer 读取此时的 thread_id，从而知道当前状态应该保存到哪个会话中。
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    print(f"\nLifePilot 已启动，输入 exit、quit 或 退出，可以结束程序。当前会话ID：{thread_id}")

    while True:
        # 会话的一次输入
        user_input = input("\n你：").strip()
        # 输入检查(退出条件)
        if user_input.lower() in {
            "exit",
            "quit",
            "退出",
        }:
            print("LifePilot：再见！")
            break
        # 输入约束(不能为空)
        if not user_input:
            print("LifePilot：请输入有效内容。")
            continue

        print("\nLifePilot 正在思考……")

        # 传入消息+之前状态，执行执行一次 LangGraph 工作流，保存最新状态。
        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(content=user_input),
                ],
            },
            # 同步thread_id。因此可以加载本会话之前状态，并将新的HumanMessage添加进去。
            config=config,
        )
        # 从完整状态中取得最后的回答结果
        final_message = result["messages"][-1]
        # 打印最终回答结果
        print("\nLifePilot：")
        print(final_message.content)

        # 统计工具消息数量
        tool_message_count = sum(
            isinstance(message, ToolMessage)
            for message in result["messages"]
        )
        # 打印会话的全部消息数量
        print(
            f"\n[调试信息] "
            f"当前会话共有 {len(result['messages'])} 条消息，"
            f"累计执行工具 {tool_message_count} 次。"
        )


def main() -> None:
    """Start LifePilot with persistent checkpoints."""
    load_dotenv()

    thread_id = input(
        "请输入会话ID（直接回车默认使用 ID:main 的会话）："
    ).strip()

    if not thread_id:
        thread_id = "main"

    # 打开 SQLite checkpointer
    with open_sqlite_checkpointer(
        CHECKPOINT_DATABASE_PATH
    ) as checkpointer:
        # 构建 Agent
        graph = build_graph(
            checkpointer=checkpointer,
            owner_id="local-user",
        )
        # 启动聊天循环
        run_chat(
            graph=graph,
            thread_id=thread_id,
        )


if __name__ == "__main__":
    main()