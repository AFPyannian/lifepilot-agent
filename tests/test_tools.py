from app.tools import (
    add_todo,
    clear_todos,
    list_todos,
)


def setup_function() -> None:
    """Reset todo data before each test."""
    clear_todos()


def test_empty_todo_list():
    result = list_todos.invoke({})

    assert result == "待办列表为空。"


def test_add_and_list_todo():
    add_result = add_todo.invoke(
        {
            "task": "学习 LangGraph",
        }
    )

    list_result = list_todos.invoke({})

    assert add_result == "已添加待办：学习 LangGraph"
    assert list_result == "1. 学习 LangGraph"


def test_rejects_blank_todo():
    result = add_todo.invoke(
        {
            "task": "   ",
        }
    )

    assert result == "待办内容不能为空。"