from langchain_core.messages import HumanMessage

from app.graph import build_graph


def main() -> None:
    """运行 LifePilot 命令行应用程序."""

    graph = build_graph()

    # 用户提示词输入
    user_input = input("你：").strip()    # .strip() 会去掉用户输入内容开头和结尾的空格、换行符等空白字符。
    if not user_input:
        print("请输入有效内容。")
        return

    print("\nLifePilot 正在思考……")

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content=user_input),
            ],
        }
    )

    final_message = result["messages"][-1]

    print("\nLifePilot：")
    print(final_message.content)

    print(
        f"\n[调试信息] "
        f"状态中共有 {len(result['messages'])} 条消息。"
    )


if __name__ == "__main__":
    main()