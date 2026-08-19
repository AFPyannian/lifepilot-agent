from app.repositories.todo_repository import (
    TodoRepository,
)


def create_repository(tmp_path):
    database_path = tmp_path / "todos.db"

    return TodoRepository(database_path)


def test_add_and_list_todo(tmp_path):
    repository = create_repository(tmp_path)

    created = repository.add(
        owner_id="user-1",
        task="学习 SQLite",
    )

    todos = repository.list_all("user-1")

    assert created.id > 0
    assert created.task == "学习 SQLite"
    assert created.is_completed is False

    assert len(todos) == 1
    assert todos[0] == created


def test_users_are_isolated(tmp_path):
    repository = create_repository(tmp_path)

    repository.add(
        owner_id="user-1",
        task="用户一的任务",
    )
    repository.add(
        owner_id="user-2",
        task="用户二的任务",
    )

    user_one_todos = repository.list_all(
        "user-1"
    )
    user_two_todos = repository.list_all(
        "user-2"
    )

    assert len(user_one_todos) == 1
    assert len(user_two_todos) == 1

    assert (
        user_one_todos[0].task
        == "用户一的任务"
    )
    assert (
        user_two_todos[0].task
        == "用户二的任务"
    )


def test_mark_todo_as_completed(tmp_path):
    repository = create_repository(tmp_path)

    todo = repository.add(
        owner_id="user-1",
        task="完成数据库练习",
    )

    was_updated = repository.mark_completed(
        owner_id="user-1",
        todo_id=todo.id,
    )

    todos = repository.list_all("user-1")

    assert was_updated is True
    assert todos[0].is_completed is True


def test_delete_todo(tmp_path):
    repository = create_repository(tmp_path)

    todo = repository.add(
        owner_id="user-1",
        task="需要删除的任务",
    )

    was_deleted = repository.delete(
        owner_id="user-1",
        todo_id=todo.id,
    )

    todos = repository.list_all("user-1")

    assert was_deleted is True
    assert todos == []