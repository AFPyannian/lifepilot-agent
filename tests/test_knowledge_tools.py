"""验证知识库工具及删除审批。"""

from app.tools import (
    create_knowledge_tools,
)


class FakeKnowledgeService:
    """模拟无需 Embedding 和 Chroma 的知识库服务。"""

    def __init__(
        self,
        existing_files: (set[str] | None) = None,
    ) -> None:
        self.existing_files = set(existing_files or set())

        self.delete_calls: list[tuple[str, str]] = []

    def delete_source(
        self,
        owner_id: str,
        filename: str,
    ) -> bool:
        self.delete_calls.append(
            (
                owner_id,
                filename,
            )
        )

        if filename not in self.existing_files:
            return False

        self.existing_files.remove(filename)

        return True


def create_tools(
    service: FakeKnowledgeService,
):
    tools = create_knowledge_tools(
        service=service,
        owner_id="test-user",
    )

    return {current_tool.name: current_tool for current_tool in tools}


def test_delete_knowledge_document_approved(
    monkeypatch,
):

    monkeypatch.setattr(
        ("app.tools.knowledge_tools.interrupt"),
        lambda request: {
            "approved": True,
        },
    )

    service = FakeKnowledgeService(
        existing_files={
            "guide.md",
        }
    )

    tools = create_tools(service)

    result = tools["delete_knowledge_document"].invoke(
        {
            "filename": "guide.md",
        }
    )

    assert result == ("已从知识库删除文档：guide.md")

    assert service.delete_calls == [
        (
            "test-user",
            "guide.md",
        )
    ]

    assert "guide.md" not in service.existing_files


def test_delete_knowledge_document_rejected(
    monkeypatch,
):

    captured_request = {}

    def reject_delete(request):
        captured_request.update(request)

        return {
            "approved": False,
        }

    monkeypatch.setattr(
        ("app.tools.knowledge_tools.interrupt"),
        reject_delete,
    )

    service = FakeKnowledgeService(
        existing_files={
            "guide.md",
        }
    )

    tools = create_tools(service)

    result = tools["delete_knowledge_document"].invoke(
        {
            "filename": "guide.md",
        }
    )

    assert result == ("用户拒绝删除知识库文档，操作已取消。")

    assert service.delete_calls == []

    assert "guide.md" in service.existing_files

    assert captured_request == {
        "kind": "tool_approval",
        "tool_name": ("delete_knowledge_document"),
        "message": ("是否确认从知识库删除这个文档？"),
        "arguments": {
            "filename": "guide.md",
        },
    }


def test_delete_missing_knowledge_document(
    monkeypatch,
):

    monkeypatch.setattr(
        ("app.tools.knowledge_tools.interrupt"),
        lambda request: {
            "approved": True,
        },
    )

    service = FakeKnowledgeService()

    tools = create_tools(service)

    result = tools["delete_knowledge_document"].invoke(
        {
            "filename": "missing.md",
        }
    )

    assert result == ("知识库中不存在文档：missing.md")

    assert service.delete_calls == [
        (
            "test-user",
            "missing.md",
        )
    ]
