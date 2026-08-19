from langchain_core.tools import tool


_TODO_ITEMS: list[str] = []     # 变量名: 类型注解(变量预期是字符串列表) = 初始化一个空列表


@tool
def add_todo(task: str) -> str:
    """
    添加一条新设待办事项：当用户要求记录、添加或创建待办事项时使用。
        Args: task 是需要添加的具体待办内容。
    """
    normalized_task = task.strip()

    if not normalized_task:
        return "待办内容不能为空。"

    _TODO_ITEMS.append(normalized_task)

    return f"已添加待办：{normalized_task}"


@tool
def list_todos() -> str:
    """
    查看当前所有待办事项：当用户要求查看、列出或检查待办事项时使用。
    """
    if not _TODO_ITEMS:
        return "待办列表为空。"

    return "\n".join(
        f"{index}. {task}" for index, task in enumerate(_TODO_ITEMS, start=1)
    )


def clear_todos() -> None:
    """删除所有待办事项：主要用于自动化测试。"""
    _TODO_ITEMS.clear()


TODO_TOOLS = [
    add_todo,
    list_todos,
]