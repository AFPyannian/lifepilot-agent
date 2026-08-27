"""验证知识库文档管理接口。"""

from types import SimpleNamespace
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.api.server import create_app


class FakeKnowledgeService:
    def __init__(self) -> None:
        self.ingested_filename: str | None = None

        self.deleted_filename: str | None = None

    def ingest(
        self,
        owner_id: str,
        filename: str,
    ) -> SimpleNamespace:
        assert owner_id == "test-user"

        self.ingested_filename = filename

        return SimpleNamespace(
            source_name=filename,
            chunk_count=3,
            already_indexed=False,
        )

    def list_sources(
        self,
        owner_id: str,
    ) -> list[SimpleNamespace]:
        assert owner_id == "test-user"

        return [
            SimpleNamespace(
                source_name="学习资料.md",
                chunk_count=3,
            )
        ]

    def delete_source(
        self,
        owner_id: str,
        filename: str,
    ) -> bool:
        assert owner_id == "test-user"

        self.deleted_filename = filename
        return True


def create_test_app(
    tmp_path,
    service: FakeKnowledgeService,
    max_file_bytes: int = 1000,
):
    settings = SimpleNamespace(
        owner_id="test-user",
        knowledge_source_directory=tmp_path,
        knowledge_max_file_bytes=(max_file_bytes),
    )

    return create_app(
        agent_graph=object(),
        knowledge_service=service,
        settings=settings,
    )


def test_upload_knowledge_document(
    tmp_path,
) -> None:
    service = FakeKnowledgeService()

    app = create_test_app(
        tmp_path,
        service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "学习资料.md",
                    b"# Agent\nTest content",
                    "text/markdown",
                )
            },
        )

    assert response.status_code == 200

    assert response.json() == {
        "filename": "学习资料.md",
        "chunk_count": 3,
        "already_indexed": False,
    }

    assert service.ingested_filename == "学习资料.md"

    assert (tmp_path / "学习资料.md").read_bytes() == (b"# Agent\nTest content")


def test_upload_rejects_unsupported_file(
    tmp_path,
) -> None:
    service = FakeKnowledgeService()

    app = create_test_app(
        tmp_path,
        service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "program.exe",
                    b"unsafe",
                    ("application/octet-stream"),
                )
            },
        )

    assert response.status_code == 400
    assert not (tmp_path / "program.exe").exists()


def test_upload_rejects_oversized_file(
    tmp_path,
) -> None:
    service = FakeKnowledgeService()

    app = create_test_app(
        tmp_path,
        service,
        max_file_bytes=4,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "large.md",
                    b"12345",
                    "text/markdown",
                )
            },
        )

    assert response.status_code == 400
    assert not (tmp_path / "large.md").exists()


def test_list_knowledge_documents(
    tmp_path,
) -> None:
    service = FakeKnowledgeService()

    app = create_test_app(
        tmp_path,
        service,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/knowledge/documents")

    assert response.status_code == 200

    assert response.json() == {
        "documents": [
            {
                "filename": "学习资料.md",
                "chunk_count": 3,
            }
        ]
    }


def test_delete_knowledge_document(
    tmp_path,
) -> None:
    filename = "学习资料.md"

    source_path = tmp_path / filename
    source_path.write_text(
        "test",
        encoding="utf-8",
    )

    service = FakeKnowledgeService()

    app = create_test_app(
        tmp_path,
        service,
    )

    encoded_filename = quote(
        filename,
        safe="",
    )

    with TestClient(app) as client:
        response = client.delete(f"/api/v1/knowledge/documents/{encoded_filename}")

    assert response.status_code == 200

    assert response.json() == {
        "filename": filename,
        "deleted": True,
    }

    assert service.deleted_filename == filename

    assert not source_path.exists()
