from langchain_core.tools import BaseTool, tool

from app.repositories.note_repository import (
    NoteItem,
    NoteRepository,
)


def _format_note_summary(
    note: NoteItem,
) -> str:
    """Create a compact note summary."""
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
    """Create note tools for one owner."""

    @tool
    def add_note(
        title: str,
        content: str,
    ) -> str:
        """创建并保存一条新笔记。

        当用户明确要求记录、保存或创建笔记时使用。

        Args:
            title: 简短、明确的笔记标题。
            content: 需要保存的完整笔记内容。
        """
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
        """列出当前用户保存的所有笔记摘要。

        当用户要求查看笔记列表时使用。
        """
        notes = repository.list_all(owner_id)

        if not notes:
            return "笔记列表为空。"

        return "\n".join(
            _format_note_summary(note)
            for note in notes
        )

    @tool
    def get_note(note_id: int) -> str:
        """根据ID读取一条完整笔记。

        当用户希望查看某条笔记的完整内容时使用。

        Args:
            note_id: 需要读取的笔记ID。
        """
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
        """按照关键词搜索笔记标题和内容。

        当用户记不清笔记ID，或要求查找相关笔记时使用。

        Args:
            query: 用于搜索笔记的关键词。
        """
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
        """修改一条已存在的笔记。

        用户必须提供笔记ID，并至少提供新标题或新内容。

        Args:
            note_id: 需要修改的笔记ID。
            title: 新标题；不修改标题时可以省略。
            content: 新内容；不修改内容时可以省略。
        """
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
        """永久删除一条笔记。

        只有用户明确要求删除某条笔记时才使用。

        Args:
            note_id: 需要永久删除的笔记ID。
        """
        was_deleted = repository.delete(
            owner_id=owner_id,
            note_id=note_id,
        )

        if not was_deleted:
            return (
                f"未找到 ID={note_id} 的笔记，"
                "或该笔记不属于当前用户。"
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