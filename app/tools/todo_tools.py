from langchain_core.tools import BaseTool, tool

from app.repositories.todo_repository import (
    TodoRepository,
)


def create_todo_tools(repository: TodoRepository, owner_id: str) -> list[BaseTool]:
    """Create todo tools for one specific owner."""

    @tool
    def add_todo(task: str) -> str:
        """
        添加一条新设待办事项：当用户要求记录、添加或创建待办事项时使用。
            Args: task 是需要添加的具体待办内容。
        """
        try:
            todo = repository.add(
                owner_id=owner_id,
                task=task,
            )
        except ValueError:
            return "待办内容不能为空。"

        return (
            f"已添加待办，ID={todo.id}，"
            f"内容：{todo.task}"
        )


    @tool
    def list_todos() -> str:
        """
        查看当前所有待办事项：当用户要求查看、列出或检查待办事项时使用。
        """
        todos = repository.list_all(owner_id)

        if not todos:
            return "待办列表为空。"

        lines: list[str] = []

        for todo in todos:
            status = (
                "已完成"
                if todo.is_completed
                else "未完成"
            )

            lines.append(
                f"ID={todo.id} | "
                f"{status} | "
                f"{todo.task}"
            )

        return "\n".join(lines)

    @tool
    def complete_todo(todo_id: int) -> str:
        """把一条待办事项标记为已完成。

        只有用户明确要求完成某条待办时才使用。
        如果用户没有提供任务ID，应先询问或查看待办列表。

        Args:
            todo_id: 需要标记为完成的待办ID。
        """
        was_updated = repository.mark_completed(
            owner_id=owner_id,
            todo_id=todo_id,
        )

        if not was_updated:
            return (
                f"未找到 ID={todo_id} 的待办，"
                "或该待办不属于当前用户。"
            )

        return (
            f"已将 ID={todo_id} 的待办"
            "标记为完成。"
        )

    @tool
    def delete_todo(todo_id: int) -> str:
        """永久删除一条待办事项。

        只有用户明确要求删除某条待办时才使用。
        如果用户没有提供任务ID，应先询问或查看待办列表。

        Args:
            todo_id: 需要删除的待办ID。
        """
        was_deleted = repository.delete(
            owner_id=owner_id,
            todo_id=todo_id,
        )

        if not was_deleted:
            return (
                f"未找到 ID={todo_id} 的待办，"
                "或该待办不属于当前用户。"
            )

        return f"已删除 ID={todo_id} 的待办。"

    return [
        add_todo,
        list_todos,
        complete_todo,
        delete_todo,
    ]