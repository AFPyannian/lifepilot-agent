from app.repositories.note_repository import (
    NoteRepository,
)
from app.tools import create_note_tools


def create_tools(tmp_path):
    repository = NoteRepository(
        tmp_path / "application.db"
    )

    tools = create_note_tools(
        repository=repository,
        owner_id="test-user",
    )

    return {
        current_tool.name: current_tool
        for current_tool in tools
    }


def test_add_and_list_note(tmp_path):
    tools = create_tools(tmp_path)

    add_result = tools["add_note"].invoke(
        {
            "title": "Agent学习",
            "content": "学习工具调用。",
        }
    )

    list_result = tools["list_notes"].invoke({})

    assert (
        add_result
        == "已创建笔记，ID=1，标题：Agent学习"
    )
    assert "ID=1" in list_result
    assert "Agent学习" in list_result


def test_get_note(tmp_path):
    tools = create_tools(tmp_path)

    tools["add_note"].invoke(
        {
            "title": "完整笔记",
            "content": "这是一段完整内容。",
        }
    )

    result = tools["get_note"].invoke(
        {
            "note_id": 1,
        }
    )

    assert "标题：完整笔记" in result
    assert "内容：这是一段完整内容。" in result


def test_search_notes(tmp_path):
    tools = create_tools(tmp_path)

    tools["add_note"].invoke(
        {
            "title": "Python装饰器",
            "content": "装饰器用于包装函数。",
        }
    )

    result = tools["search_notes"].invoke(
        {
            "query": "包装函数",
        }
    )

    assert "Python装饰器" in result


def test_update_and_delete_note(tmp_path):
    tools = create_tools(tmp_path)

    tools["add_note"].invoke(
        {
            "title": "旧标题",
            "content": "旧内容",
        }
    )

    update_result = tools["update_note"].invoke(
        {
            "note_id": 1,
            "title": "新标题",
            "content": "新内容",
        }
    )

    assert "已更新笔记" in update_result
    assert "新标题" in update_result

    delete_result = tools["delete_note"].invoke(
        {
            "note_id": 1,
        }
    )

    assert (
        delete_result
        == "已删除 ID=1 的笔记。"
    )

    assert (
        tools["list_notes"].invoke({})
        == "笔记列表为空。"
    )