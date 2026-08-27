"""验证笔记工具及删除审批。"""

from app.repositories.note_repository import (
    NoteRepository,
)
from app.tools import create_note_tools


def create_tools(tmp_path):
    repository = NoteRepository(tmp_path / "application.db")

    tools = create_note_tools(
        repository=repository,
        owner_id="test-user",
    )

    return {current_tool.name: current_tool for current_tool in tools}


def test_add_and_list_note(
    tmp_path,
):
    tools = create_tools(tmp_path)

    add_result = tools["add_note"].invoke(
        {
            "title": "Agent学习",
            "content": "学习工具调用。",
        }
    )

    list_result = tools["list_notes"].invoke({})

    assert add_result == ("已创建笔记，ID=1，标题：Agent学习")

    assert "ID=1" in list_result
    assert "Agent学习" in list_result


def test_get_note(
    tmp_path,
):
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


def test_search_notes(
    tmp_path,
):
    tools = create_tools(tmp_path)

    tools["add_note"].invoke(
        {
            "title": "Python装饰器",
            "content": ("装饰器用于包装函数。"),
        }
    )

    result = tools["search_notes"].invoke(
        {
            "query": "包装函数",
        }
    )

    assert "Python装饰器" in result


def test_update_note(
    tmp_path,
):
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

    note_result = tools["get_note"].invoke(
        {
            "note_id": 1,
        }
    )

    assert "标题：新标题" in note_result
    assert "内容：新内容" in note_result


def test_delete_note_approved(
    tmp_path,
    monkeypatch,
):

    monkeypatch.setattr(
        "app.tools.note_tools.interrupt",
        lambda request: {
            "approved": True,
        },
    )

    tools = create_tools(tmp_path)

    tools["add_note"].invoke(
        {
            "title": "即将删除",
            "content": "测试内容",
        }
    )

    delete_result = tools["delete_note"].invoke(
        {
            "note_id": 1,
        }
    )

    assert delete_result == ("已删除 ID=1 的笔记。")

    assert tools["list_notes"].invoke({}) == "笔记列表为空。"


def test_delete_note_rejected(
    tmp_path,
    monkeypatch,
):

    captured_request = {}

    def reject_delete(request):
        captured_request.update(request)

        return {
            "approved": False,
        }

    monkeypatch.setattr(
        "app.tools.note_tools.interrupt",
        reject_delete,
    )

    tools = create_tools(tmp_path)

    tools["add_note"].invoke(
        {
            "title": "必须保留",
            "content": "不能被删除",
        }
    )

    delete_result = tools["delete_note"].invoke(
        {
            "note_id": 1,
        }
    )

    assert delete_result == ("用户拒绝删除该笔记，操作已取消。")

    note_result = tools["get_note"].invoke(
        {
            "note_id": 1,
        }
    )

    assert "标题：必须保留" in note_result
    assert "内容：不能被删除" in note_result

    assert captured_request == {
        "kind": "tool_approval",
        "tool_name": "delete_note",
        "message": ("是否确认删除这条笔记？"),
        "arguments": {
            "note_id": 1,
        },
    }


def test_delete_missing_note_after_approval(
    tmp_path,
    monkeypatch,
):

    monkeypatch.setattr(
        "app.tools.note_tools.interrupt",
        lambda request: {
            "approved": True,
        },
    )

    tools = create_tools(tmp_path)

    result = tools["delete_note"].invoke(
        {
            "note_id": 999,
        }
    )

    assert result == ("未找到 ID=999 的笔记，或该笔记不属于当前用户。")
