"""验证用户资料和长期记忆仓储。"""


from app.repositories.user_memory_repository import (
    UserMemoryRepository,
)


def create_repository(tmp_path):
    return UserMemoryRepository(
        tmp_path / "application.db"
    )


def test_create_and_update_profile(tmp_path):
    repository = create_repository(tmp_path)

    first = repository.update_profile(
        owner_id="user-1",
        display_name="小李",
        occupation="Python学习者",
    )

    second = repository.update_profile(
        owner_id="user-1",
        current_goal="成为Agent开发工程师",
    )

    assert first.display_name == "小李"
    assert second.display_name == "小李"
    assert second.occupation == "Python学习者"
    assert (
        second.current_goal
        == "成为Agent开发工程师"
    )


def test_add_memory_without_duplicates(
    tmp_path,
):
    repository = create_repository(tmp_path)

    first = repository.add_memory(
        owner_id="user-1",
        category="偏好",
        content="喜欢简洁的回答",
    )

    second = repository.add_memory(
        owner_id="user-1",
        category="偏好",
        content="喜欢简洁的回答",
    )

    memories = repository.list_recent(
        "user-1"
    )

    assert first.id == second.id
    assert len(memories) == 1


def test_search_memory(tmp_path):
    repository = create_repository(tmp_path)

    repository.add_memory(
        owner_id="user-1",
        category="技术栈",
        content="正在学习LangGraph",
    )

    results = repository.search(
        owner_id="user-1",
        query="LangGraph",
    )

    assert len(results) == 1
    assert (
        results[0].content
        == "正在学习LangGraph"
    )


def test_memories_are_isolated(tmp_path):
    repository = create_repository(tmp_path)

    repository.add_memory(
        owner_id="user-1",
        category="偏好",
        content="喜欢中文回答",
    )

    repository.add_memory(
        owner_id="user-2",
        category="偏好",
        content="喜欢英文回答",
    )

    user_one = repository.list_recent("user-1")
    user_two = repository.list_recent("user-2")

    assert len(user_one) == 1
    assert len(user_two) == 1
    assert user_one[0].content == "喜欢中文回答"
    assert user_two[0].content == "喜欢英文回答"


def test_delete_memory(tmp_path):
    repository = create_repository(tmp_path)

    memory = repository.add_memory(
        owner_id="user-1",
        category="临时信息",
        content="需要被遗忘",
    )

    was_deleted = repository.delete_memory(
        owner_id="user-1",
        memory_id=memory.id,
    )

    assert was_deleted is True
    assert repository.list_recent("user-1") == []