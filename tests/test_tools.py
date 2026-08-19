from app.repositories.todo_repository import (
    TodoRepository,
)
from app.tools import create_todo_tools


def create_tools(
    tmp_path,
    owner_id: str = "test-user",
):
    repository = TodoRepository(
        tmp_path / "todos.db"
    )

    tools = create_todo_tools(
        repository=repository,
        owner_id=owner_id,
    )

    return {
        current_tool.name: current_tool
        for current_tool in tools
    }


def test_empty_todo_list(tmp_path):
    tools = create_tools(tmp_path)

    result = tools["list_todos"].invoke({})

    assert result == "待办列表为空。"


def test_add_and_list_todo(tmp_path):
    tools = create_tools(tmp_path)

    add_result = tools["add_todo"].invoke(
        {
            "task": "学习 SQLite",
        }
    )

    list_result = tools["list_todos"].invoke({})

    assert (
        add_result
        == "已添加待办，ID=1，内容：学习 SQLite"
    )

    assert (
        list_result
        == "ID=1 | 未完成 | 学习 SQLite"
    )


def test_complete_todo(tmp_path):
    tools = create_tools(tmp_path)

    tools["add_todo"].invoke(
        {
            "task": "完成数据库练习",
        }
    )

    complete_result = tools[
        "complete_todo"
    ].invoke(
        {
            "todo_id": 1,
        }
    )

    list_result = tools["list_todos"].invoke({})

    assert (
        complete_result
        == "已将 ID=1 的待办标记为完成。"
    )

    assert (
        list_result
        == "ID=1 | 已完成 | 完成数据库练习"
    )


def test_delete_todo(tmp_path):
    tools = create_tools(tmp_path)

    tools["add_todo"].invoke(
        {
            "task": "即将被删除",
        }
    )

    delete_result = tools[
        "delete_todo"
    ].invoke(
        {
            "todo_id": 1,
        }
    )

    list_result = tools["list_todos"].invoke({})

    assert delete_result == "已删除 ID=1 的待办。"
    assert list_result == "待办列表为空。"


def test_data_survives_repository_recreation(
    tmp_path,
):
    database_path = tmp_path / "persistent.db"

    first_repository = TodoRepository(
        database_path
    )

    first_tools = create_todo_tools(
        repository=first_repository,
        owner_id="test-user",
    )

    first_tools_by_name = {
        current_tool.name: current_tool
        for current_tool in first_tools
    }

    first_tools_by_name["add_todo"].invoke(
        {
            "task": "需要持久保存的任务",
        }
    )

    second_repository = TodoRepository(
        database_path
    )

    second_tools = create_todo_tools(
        repository=second_repository,
        owner_id="test-user",
    )

    second_tools_by_name = {
        current_tool.name: current_tool
        for current_tool in second_tools
    }

    result = second_tools_by_name[
        "list_todos"
    ].invoke({})

    assert (
        result
        == "ID=1 | 未完成 | 需要持久保存的任务"
    )