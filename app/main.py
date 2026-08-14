from langchain_core.messages import HumanMessage

from app.graph import build_graph


def main() -> None:
    """Run the LifePilot command-line application."""
    graph = build_graph()

    config = {
        "configurable": {
            "thread_id": "local-user-1",
        }
    }

    print("LifePilot 已启动。")
    print("输入 exit、quit 或 退出，可以结束程序。")

    while True:
        user_input = input("\n你：").strip()

        if user_input.lower() in {
            "exit",
            "quit",
            "退出",
        }:
            print("LifePilot：再见！")
            break

        if not user_input:
            print("LifePilot：请输入有效内容。")
            continue

        print("\nLifePilot 正在思考……")

        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(content=user_input),
                ],
            },
            config=config,
        )

        final_message = result["messages"][-1]

        print("\nLifePilot：")
        print(final_message.content)

        print(
            f"\n[调试信息] "
            f"当前会话共有 {len(result['messages'])} 条消息。"
        )


if __name__ == "__main__":
    main()