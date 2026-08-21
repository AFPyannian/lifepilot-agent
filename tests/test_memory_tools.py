from app.repositories.user_memory_repository import (
    UserMemoryRepository,
)
from app.tools import create_memory_tools


def create_tools(tmp_path):
    repository = UserMemoryRepository(
        tmp_path / "application.db"
    )

    tools = create_memory_tools(
        repository=repository,
        owner_id="test-user",
    )

    return {
        current_tool.name: current_tool
        for current_tool in tools
    }


def test_update_and_get_profile(tmp_path):
    tools = create_tools(tmp_path)

    tools["update_user_profile"].invoke(
        {
            "display_name": "小李",
            "current_goal": "学习Agent开发",
        }
    )

    result = tools[
        "get_user_profile"
    ].invoke({})

    assert "姓名：小李" in result
    assert "学习Agent开发" in result


def test_remember_and_list_fact(tmp_path):
    tools = create_tools(tmp_path)

    tools["remember_user_fact"].invoke(
        {
            "category": "偏好",
            "content": "喜欢简洁回答",
        }
    )

    result = tools[
        "list_user_memories"
    ].invoke({})

    assert "偏好" in result
    assert "喜欢简洁回答" in result


def test_search_memory(tmp_path):
    tools = create_tools(tmp_path)

    tools["remember_user_fact"].invoke(
        {
            "category": "技术栈",
            "content": "正在学习LangGraph",
        }
    )

    result = tools[
        "search_user_memories"
    ].invoke(
        {
            "query": "LangGraph",
        }
    )

    assert "正在学习LangGraph" in result


def test_forget_memory(tmp_path):
    tools = create_tools(tmp_path)

    tools["remember_user_fact"].invoke(
        {
            "category": "临时",
            "content": "需要删除的信息",
        }
    )

    result = tools[
        "forget_user_memory"
    ].invoke(
        {
            "memory_id": 1,
        }
    )

    assert result == "已遗忘 ID=1 的长期记忆。"

    assert (
        tools["list_user_memories"].invoke({})
        == "尚未保存长期记忆。"
    )