"""创建供 Agent 管理用户待办事项的工具。"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from app.identity import user_id_from_config
from app.repositories.todo_repository import (
    TodoRepository,
)


def create_todo_tools(repository: TodoRepository) -> list[BaseTool]:
    """创建从可信运行上下文读取用户身份的待办工具。"""

    @tool
    def add_todo(task: str, config: RunnableConfig) -> str:
        """创建待办事项；仅在用户明确要求添加或保存待办时调用。"""
        try:
            todo = repository.add(
                owner_id=user_id_from_config(config),
                task=task,
            )
        except ValueError:
            return "待办内容不能为空。"

        return f"已添加待办，ID={todo.id}，内容：{todo.task}"

    @tool
    def list_todos(config: RunnableConfig) -> str:
        """列出当前用户的全部待办及其完成状态。"""
        todos = repository.list_all(user_id_from_config(config))

        if not todos:
            return "待办列表为空。"

        lines: list[str] = []

        for todo in todos:
            status = "已完成" if todo.is_completed else "未完成"

            lines.append(f"ID={todo.id} | {status} | {todo.task}")

        return "\n".join(lines)

    @tool
    def complete_todo(
        todo_id: int,
        config: RunnableConfig,
    ) -> str:
        """将当前用户指定编号的待办标记为完成。"""
        was_updated = repository.mark_completed(
            owner_id=user_id_from_config(config),
            todo_id=todo_id,
        )

        if not was_updated:
            return f"未找到 ID={todo_id} 的待办，或该待办不属于当前用户。"

        return f"已将 ID={todo_id} 的待办标记为完成。"

    @tool
    def delete_todo(
        todo_id: int,
        config: RunnableConfig,
    ) -> str:
        """请求永久删除一条待办；执行前必须获得用户审批。"""
        decision = interrupt(
            {
                "kind": "tool_approval",
                "tool_name": "delete_todo",
                "message": ("是否确认删除这个待办事项？"),
                "arguments": {
                    "todo_id": todo_id,
                },
            }
        )

        if not isinstance(decision, dict) or decision.get("approved") is not True:
            return "用户拒绝删除该待办事项，操作已取消。"

        was_deleted = repository.delete(
            owner_id=user_id_from_config(config),
            todo_id=todo_id,
        )

        if not was_deleted:
            return f"未找到 ID={todo_id} 的待办，或该待办不属于当前用户。"

        return f"已删除 ID={todo_id} 的待办。"

    return [
        add_todo,
        list_todos,
        complete_todo,
        delete_todo,
    ]
