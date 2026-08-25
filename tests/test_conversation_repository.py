from pathlib import Path

from app.repositories.conversation_repository import (
    ConversationRepository,
)


def create_repository(
    tmp_path: Path,
) -> ConversationRepository:
    return ConversationRepository(
        tmp_path / "application.db"
    )


def test_record_and_list_conversations(
    tmp_path: Path,
) -> None:
    repository = create_repository(
        tmp_path
    )

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message=(
            "请帮我制定一个学习"
            "LangGraph的计划"
        ),
    )

    conversations = (
        repository.list_conversations(
            owner_id="owner-1"
        )
    )

    assert len(conversations) == 1

    assert (
        conversations[0].thread_id
        == "thread-1"
    )

    assert conversations[0].title.startswith(
        "请帮我制定"
    )


def test_second_message_does_not_replace_title(
    tmp_path: Path,
) -> None:
    repository = create_repository(
        tmp_path
    )

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="第一条消息",
    )

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="第二条消息",
    )

    conversation = repository.get(
        owner_id="owner-1",
        thread_id="thread-1",
    )

    assert conversation is not None

    assert (
        conversation.title
        == "第一条消息"
    )


def test_rename_conversation(
    tmp_path: Path,
) -> None:
    repository = create_repository(
        tmp_path
    )

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="原始标题",
    )

    renamed = repository.rename(
        owner_id="owner-1",
        thread_id="thread-1",
        title="LangGraph学习计划",
    )

    conversation = repository.get(
        owner_id="owner-1",
        thread_id="thread-1",
    )

    assert renamed is True
    assert conversation is not None

    assert (
        conversation.title
        == "LangGraph学习计划"
    )


def test_delete_conversation(
    tmp_path: Path,
) -> None:
    repository = create_repository(
        tmp_path
    )

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="测试对话",
    )

    deleted = repository.delete(
        owner_id="owner-1",
        thread_id="thread-1",
    )

    assert deleted is True

    assert repository.get(
        owner_id="owner-1",
        thread_id="thread-1",
    ) is None


def test_owner_cannot_access_other_owner_thread(
    tmp_path: Path,
) -> None:
    repository = create_repository(
        tmp_path
    )

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="私有对话",
    )

    assert repository.get(
        owner_id="owner-2",
        thread_id="thread-1",
    ) is None