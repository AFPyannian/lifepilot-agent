"""验证 Alice 与 Bob 之间的请求、会话和文件隔离。"""

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.api.server import create_app
from app.auth.models import Principal
from app.repositories.conversation_repository import ConversationRepository


class MappingAuthService:
    """将不同测试 Token 映射到不同用户。"""

    def __init__(self) -> None:
        self.principals = {
            "alice-token": Principal(
                user_id="alice-id",
                username="alice",
                role="user",
                status="active",
                session_id="alice-session",
            ),
            "bob-token": Principal(
                user_id="bob-id",
                username="bob",
                role="user",
                status="active",
                session_id="bob-session",
            ),
        }

    def authenticate(self, access_token: str) -> Principal | None:
        return self.principals.get(access_token)


class RecordingGraph:
    """记录每次 Agent 调用使用的隔离配置。"""

    def __init__(self) -> None:
        self.configs: list[dict[str, Any]] = []

    def get_state(self, config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(next=())

    def invoke(
        self,
        input_data: dict[str, Any] | None,
        config: dict[str, Any],
        context: Any | None = None,
    ) -> dict[str, Any]:
        self.configs.append(config)
        return {"messages": [AIMessage(content="测试回答")]}


class RecordingKnowledgeService:
    """记录知识库操作所属用户。"""

    def __init__(self) -> None:
        self.ingested: list[tuple[str, str]] = []
        self.deleted: list[tuple[str, str]] = []

    def ingest(self, owner_id: str, filename: str) -> SimpleNamespace:
        self.ingested.append((owner_id, filename))
        return SimpleNamespace(
            source_name=filename,
            chunk_count=1,
            already_indexed=False,
        )

    def delete_source(self, owner_id: str, filename: str) -> bool:
        self.deleted.append((owner_id, filename))
        return True

    def list_sources(self, owner_id: str) -> list[Any]:
        return []


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "api_rate_limit_enabled": False,
        "agent_recursion_limit": 25,
        "app_environment": "test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_same_public_thread_id_uses_separate_internal_checkpoints(tmp_path) -> None:
    repository = ConversationRepository(tmp_path / "application.db")
    graph = RecordingGraph()
    app = create_app(
        agent_graph=graph,
        settings=settings(),
        auth_service=MappingAuthService(),
        conversation_repository=repository,
    )

    with TestClient(app) as client:
        for token in ("alice-token", "bob-token"):
            response = client.post(
                "/api/v1/chat",
                headers=headers(token),
                json={"message": "你好", "thread_id": "main"},
            )
            assert response.status_code == 200

    internal_ids = {config["configurable"]["thread_id"] for config in graph.configs}
    assert internal_ids == {
        "user:alice-id:thread:main",
        "user:bob-id:thread:main",
    }
    assert repository.get("alice-id", "main") is not None
    assert repository.get("bob-id", "main") is not None


def test_user_cannot_read_other_users_conversation(tmp_path) -> None:
    repository = ConversationRepository(tmp_path / "application.db")
    repository.record_message("bob-id", "private", "Bob 的消息")
    app = create_app(
        agent_graph=RecordingGraph(),
        settings=settings(),
        auth_service=MappingAuthService(),
        conversation_repository=repository,
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/conversations/private",
            headers=headers("alice-token"),
        )

    assert response.status_code == 404


def test_same_filename_is_stored_and_deleted_per_user(tmp_path) -> None:
    source_root = tmp_path / "knowledge"
    service = RecordingKnowledgeService()
    app = create_app(
        agent_graph=RecordingGraph(),
        knowledge_service=service,
        settings=settings(
            knowledge_source_directory=source_root,
            knowledge_max_file_bytes=1000,
        ),
        auth_service=MappingAuthService(),
    )

    with TestClient(app) as client:
        for token, content in (
            ("alice-token", b"Alice"),
            ("bob-token", b"Bob"),
        ):
            response = client.post(
                "/api/v1/knowledge/documents",
                headers=headers(token),
                files={"file": ("same.md", content, "text/markdown")},
            )
            assert response.status_code == 200

        deleted = client.delete(
            "/api/v1/knowledge/documents/same.md",
            headers=headers("alice-token"),
        )

    assert deleted.status_code == 200
    assert not (source_root / "alice-id" / "same.md").exists()
    assert (source_root / "bob-id" / "same.md").read_bytes() == b"Bob"
    assert service.ingested == [
        ("alice-id", "same.md"),
        ("bob-id", "same.md"),
    ]
    assert service.deleted == [("alice-id", "same.md")]
