from langchain_core.tools import BaseTool, tool

from app.repositories.user_memory_repository import (
    UserMemoryRepository,
)


def create_memory_tools(repository: UserMemoryRepository, owner_id: str) -> list[BaseTool]:
    """为单个用户创建长期记忆工具"""

    @tool
    def update_user_profile(
        display_name: str | None = None,
        occupation: str | None = None,
        current_goal: str | None = None,
        response_style: str | None = None,
    ) -> str:
        """创建或更新用户的结构化个人资料：保存姓名、职业、当前目标和回答风格。

        只有用户明确要求记住或更新这些资料时才使用。

        Args:
            display_name: 用户希望助理使用的名字。
            occupation: 用户的职业或身份。
            current_goal: 用户当前的主要目标。
            response_style: 用户偏好的回答风格。
        """
        try:
            profile = repository.update_profile(
                owner_id=owner_id,
                display_name=display_name,
                occupation=occupation,
                current_goal=current_goal,
                response_style=response_style,
            )
        except ValueError:
            return (
                "至少需要提供一项有效的用户资料。"
            )

        return (
            "用户资料已更新：\n"
            f"姓名：{profile.display_name or '未设置'}\n"
            f"职业：{profile.occupation or '未设置'}\n"
            f"当前目标：{profile.current_goal or '未设置'}\n"
            f"回答风格：{profile.response_style or '未设置'}"
        )

    @tool
    def get_user_profile() -> str:
        """读取当前用户保存的结构化资料。

        当用户询问助理记住了哪些个人资料时使用。
        """
        profile = repository.get_profile(owner_id)

        if profile is None:
            return "尚未保存用户资料。"

        return (
            f"姓名：{profile.display_name or '未设置'}\n"
            f"职业：{profile.occupation or '未设置'}\n"
            f"当前目标：{profile.current_goal or '未设置'}\n"
            f"回答风格：{profile.response_style or '未设置'}"
        )

    @tool
    def remember_user_fact(
        category: str,
        content: str,
    ) -> str:
        """保存一条需要跨会话记住的用户事实：保存稳定偏好、背景、约束或长期目标，不应保存密码、API Key或银行卡等敏感凭据。

        只有用户明确要求记住时才使用。

        Args:
            category: 事实分类，例如偏好、背景、目标或约束。
            content: 需要长期记住的事实。
        """
        try:
            memory = repository.add_memory(
                owner_id=owner_id,
                category=category,
                content=content,
            )
        except ValueError:
            return (
                "长期记忆分类或内容无效，请提供简短、明确的信息。"
            )

        return (
            f"已保存长期记忆，ID={memory.id}，"
            f"分类：{memory.category}，"
            f"内容：{memory.content}"
        )

    @tool
    def list_user_memories() -> str:
        """列出当前用户保存的长期记忆。

        当用户询问助理记住了什么时使用。
        """
        memories = repository.list_recent(
            owner_id=owner_id,
            limit=50,
        )

        if not memories:
            return "尚未保存长期记忆。"

        return "\n".join(
            (
                f"ID={memory.id} | "
                f"分类：{memory.category} | "
                f"{memory.content}"
            )
            for memory in memories
        )

    @tool
    def search_user_memories(
        query: str,
    ) -> str:
        """按照关键词搜索用户长期记忆。

        Args:
            query: 需要搜索的关键词。
        """
        memories = repository.search(
            owner_id=owner_id,
            query=query,
        )

        if not memories:
            return (
                f"没有找到包含“{query.strip()}”的长期记忆。"
            )

        return "\n".join(
            (
                f"ID={memory.id} | "
                f"分类：{memory.category} | "
                f"{memory.content}"
            )
            for memory in memories
        )

    @tool
    def forget_user_memory(
        memory_id: int,
    ) -> str:
        """永久删除一条长期记忆。

        只有用户明确要求遗忘某条记忆时才使用。

        Args:
            memory_id: 需要删除的长期记忆ID。
        """
        was_deleted = repository.delete_memory(
            owner_id=owner_id,
            memory_id=memory_id,
        )

        if not was_deleted:
            return (
                f"未找到 ID={memory_id} 的长期记忆，或该记忆不属于当前用户。"
            )

        return (
            f"已遗忘 ID={memory_id} 的长期记忆。"
        )

    return [
        update_user_profile,
        get_user_profile,
        remember_user_fact,
        list_user_memories,
        search_user_memories,
        forget_user_memory,
    ]