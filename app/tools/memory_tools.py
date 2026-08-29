"""创建供 Agent 管理用户长期记忆的工具。"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from app.identity import user_id_from_config
from app.repositories.user_memory_repository import (
    UserMemoryRepository,
)


def create_memory_tools(
    repository: UserMemoryRepository,
) -> list[BaseTool]:
    """创建从可信运行上下文读取用户身份的记忆工具。"""

    @tool
    def update_user_profile(
        config: RunnableConfig,
        display_name: str | None = None,
        occupation: str | None = None,
        current_goal: str | None = None,
        response_style: str | None = None,
    ) -> str:
        """更新姓名、职业、目标或回答风格；仅保存用户明确要求记住的资料。"""
        try:
            profile = repository.update_profile(
                owner_id=user_id_from_config(config),
                display_name=display_name,
                occupation=occupation,
                current_goal=current_goal,
                response_style=response_style,
            )
        except ValueError:
            return "至少需要提供一项有效的用户资料。"

        return (
            "用户资料已更新：\n"
            f"姓名：{profile.display_name or '未设置'}\n"
            f"职业：{profile.occupation or '未设置'}\n"
            f"当前目标：{profile.current_goal or '未设置'}\n"
            f"回答风格：{profile.response_style or '未设置'}"
        )

    @tool
    def get_user_profile(config: RunnableConfig) -> str:
        """读取当前用户的结构化资料。"""
        profile = repository.get_profile(user_id_from_config(config))

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
        config: RunnableConfig,
    ) -> str:
        """保存稳定偏好、重要事实、长期目标或约束；不得保存敏感凭据。"""
        try:
            memory = repository.add_memory(
                owner_id=user_id_from_config(config),
                category=category,
                content=content,
            )
        except ValueError:
            return "长期记忆分类或内容无效，请提供简短、明确的信息。"

        return (
            f"已保存长期记忆，ID={memory.id}，"
            f"分类：{memory.category}，"
            f"内容：{memory.content}"
        )

    @tool
    def list_user_memories(config: RunnableConfig) -> str:
        """列出当前用户最近保存的长期记忆。"""
        memories = repository.list_recent(
            owner_id=user_id_from_config(config),
            limit=50,
        )

        if not memories:
            return "尚未保存长期记忆。"

        return "\n".join(
            (f"ID={memory.id} | 分类：{memory.category} | {memory.content}")
            for memory in memories
        )

    @tool
    def search_user_memories(
        query: str,
        config: RunnableConfig,
    ) -> str:
        """按关键词搜索当前用户的长期记忆。"""
        memories = repository.search(
            owner_id=user_id_from_config(config),
            query=query,
        )

        if not memories:
            return f"没有找到包含“{query.strip()}”的长期记忆。"

        return "\n".join(
            (f"ID={memory.id} | 分类：{memory.category} | {memory.content}")
            for memory in memories
        )

    @tool
    def forget_user_memory(
        memory_id: int,
        config: RunnableConfig,
    ) -> str:
        """请求永久删除一条长期记忆；执行前必须获得用户审批。"""
        was_deleted = repository.delete_memory(
            owner_id=user_id_from_config(config),
            memory_id=memory_id,
        )

        if not was_deleted:
            return f"未找到 ID={memory_id} 的长期记忆，或该记忆不属于当前用户。"

        return f"已遗忘 ID={memory_id} 的长期记忆。"

    return [
        update_user_profile,
        get_user_profile,
        remember_user_fact,
        list_user_memories,
        search_user_memories,
        forget_user_memory,
    ]
