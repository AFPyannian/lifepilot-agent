"""验证笔记仓储的增删改查。"""


from app.repositories.note_repository import (
    NoteRepository,
)


def create_repository(tmp_path):
    return NoteRepository(
        tmp_path / "application.db"
    )


def test_add_and_get_note(tmp_path):
    repository = create_repository(tmp_path)

    created = repository.add(
        owner_id="user-1",
        title="LangGraph学习",
        content="学习State、Node和Edge。",
    )

    loaded = repository.get_by_id(
        owner_id="user-1",
        note_id=created.id,
    )

    assert loaded == created


def test_search_notes(tmp_path):
    repository = create_repository(tmp_path)

    repository.add(
        owner_id="user-1",
        title="Python学习",
        content="学习装饰器和类型标注。",
    )
    repository.add(
        owner_id="user-1",
        title="数据库学习",
        content="学习SQLite和SQL。",
    )

    results = repository.search(
        owner_id="user-1",
        query="装饰器",
    )

    assert len(results) == 1
    assert results[0].title == "Python学习"


def test_update_note(tmp_path):
    repository = create_repository(tmp_path)

    created = repository.add(
        owner_id="user-1",
        title="旧标题",
        content="旧内容",
    )

    updated = repository.update(
        owner_id="user-1",
        note_id=created.id,
        title="新标题",
        content="新内容",
    )

    assert updated is not None
    assert updated.title == "新标题"
    assert updated.content == "新内容"
    assert updated.created_at == created.created_at


def test_delete_note(tmp_path):
    repository = create_repository(tmp_path)

    created = repository.add(
        owner_id="user-1",
        title="需要删除",
        content="这条笔记将被删除。",
    )

    was_deleted = repository.delete(
        owner_id="user-1",
        note_id=created.id,
    )

    loaded = repository.get_by_id(
        owner_id="user-1",
        note_id=created.id,
    )

    assert was_deleted is True
    assert loaded is None


def test_notes_are_isolated_by_owner(
    tmp_path,
):
    repository = create_repository(tmp_path)

    repository.add(
        owner_id="user-1",
        title="用户一",
        content="用户一的私有笔记。",
    )

    repository.add(
        owner_id="user-2",
        title="用户二",
        content="用户二的私有笔记。",
    )

    user_one_notes = repository.list_all(
        "user-1"
    )
    user_two_notes = repository.list_all(
        "user-2"
    )

    assert len(user_one_notes) == 1
    assert len(user_two_notes) == 1
    assert (
        user_one_notes[0].title
        == "用户一"
    )
    assert (
        user_two_notes[0].title
        == "用户二"
    )