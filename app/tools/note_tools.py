"""创建供 Agent 管理用户笔记的工具。"""


from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from app.repositories.note_repository import (
    NoteItem,
    NoteRepository,
)


def _format_note_summary(
    note: NoteItem,
) -> str:
    """将笔记压缩成适合列表展示的摘要。"""
    preview = " ".join(
        note.content.split()
    )

    if len(preview) > 80:
        preview = f"{preview[:80]}..."

    return (
        f"ID={note.id} | "
        f"标题：{note.title} | "
        f"摘要：{preview}"
    )


def create_note_tools(
    repository: NoteRepository,
    owner_id: str,
) -> list[BaseTool]:
    """为指定用户创建笔记工具。"""

    @tool
    def add_note(
        title: str,
        content: str,
    ) -> str:
        """创建一条笔记；仅在用户明确要求记录或保存时调用。"""
        try:
            note = repository.add(
                owner_id=owner_id,
                title=title,
                content=content,
            )
        except ValueError:
            return "笔记标题和内容都不能为空。"

        return (
            f"已创建笔记，ID={note.id}，"
            f"标题：{note.title}"
        )

    @tool
    def list_notes() -> str:
        """列出当前用户的全部笔记摘要。"""
        notes = repository.list_all(owner_id)

        if not notes:
            return "笔记列表为空。"

        return "\n".join(
            _format_note_summary(note)
            for note in notes
        )

    @tool
    def get_note(note_id: int) -> str:
        """根据编号读取当前用户的一条完整笔记。"""
        note = repository.get_by_id(
            owner_id=owner_id,
            note_id=note_id,
        )

        if note is None:
            return (
                f"未找到 ID={note_id} 的笔记，"
                "或该笔记不属于当前用户。"
            )

        return (
            f"笔记ID：{note.id}\n"
            f"标题：{note.title}\n"
            f"内容：{note.content}\n"
            f"创建时间：{note.created_at}\n"
            f"更新时间：{note.updated_at}"
        )

    @tool
    def search_notes(query: str) -> str:
        """按关键词搜索当前用户的笔记标题和正文。"""
        notes = repository.search(
            owner_id=owner_id,
            query=query,
        )

        if not notes:
            return (
                f"没有找到包含“{query.strip()}”"
                "的笔记。"
            )

        return "\n".join(
            _format_note_summary(note)
            for note in notes
        )

    @tool
    def update_note(
        note_id: int,
        title: str | None = None,
        content: str | None = None,
    ) -> str:
        """修改当前用户已经存在的一条笔记。"""
        if title is None and content is None:
            return "必须提供新标题或新内容。"

        try:
            note = repository.update(
                owner_id=owner_id,
                note_id=note_id,
                title=title,
                content=content,
            )
        except ValueError:
            return "笔记标题和内容都不能为空。"

        if note is None:
            return (
                f"未找到 ID={note_id} 的笔记，"
                "或该笔记不属于当前用户。"
            )

        return (
            f"已更新笔记，ID={note.id}，"
            f"标题：{note.title}"
        )

    @tool
    def delete_note(note_id: int) -> str:
        """请求永久删除一条笔记；执行前必须获得用户审批。"""
        decision = interrupt(
            {
                "kind": "tool_approval",
                "tool_name": "delete_note",
                "message": (
                    "是否确认删除这条笔记？"
                ),
                "arguments": {
                    "note_id": note_id,
                },
            }
        )

        if (
                not isinstance(decision, dict)
                or decision.get("approved")
                is not True
        ):
            return (
                "用户拒绝删除该笔记，"
                "操作已取消。"
            )

        was_deleted = repository.delete(
            owner_id=owner_id,
            note_id=note_id,
        )

        if not was_deleted:
            return (
                f"未找到 ID={note_id} 的笔记，或该笔记不属于当前用户。"
            )

        return f"已删除 ID={note_id} 的笔记。"

    return [
        add_note,
        list_notes,
        get_note,
        search_notes,
        update_note,
        delete_note,
    ]