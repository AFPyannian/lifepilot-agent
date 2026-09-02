"""验证评估入口与当前多用户 Agent 契约保持一致。"""

from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

import evaluations.run_agent_eval as agent_eval
import evaluations.run_rag_eval as rag_eval
from app.config import Settings
from app.identity import AgentContext
from app.repositories.todo_repository import TodoRepository


class RecordingGraph:
    """记录评估传入图的状态、配置和可信上下文。"""

    def __init__(self) -> None:
        self.state = None
        self.config = None
        self.context = None

    def invoke(self, state, *, config, context):
        self.state = state
        self.config = config
        self.context = context
        return {"messages": [AIMessage(content="LifePilot 已就绪")]}


class TodoToolCallingModel:
    """确定性调用待办工具，用于验证完整评估图。"""

    def bind_tools(self, tools):
        assert "add_todo" in {tool.name for tool in tools}
        return self

    def invoke(self, messages):
        if any(isinstance(message, ToolMessage) for message in messages):
            return AIMessage(content="待办已创建")

        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "add_todo",
                    "args": {"task": "学习 LangGraph"},
                    "id": "evaluation-tool-call",
                    "type": "tool_call",
                }
            ],
        )


def test_agent_evaluation_injects_user_context_and_checkpoint_identity():
    graph = RecordingGraph()

    result = agent_eval.evaluate_case(
        graph,
        {
            "id": "greeting",
            "input": "你好",
            "required_tools": [],
            "allowed_tools": [],
            "required_answer_keywords": ["LifePilot"],
            "max_latency_seconds": 30,
        },
    )

    assert result["passed"] is True
    assert isinstance(graph.context, AgentContext)
    assert graph.context.user_id == agent_eval.EVALUATION_USER_ID
    assert graph.context.request_id == "evaluation:greeting"
    assert graph.config["configurable"]["user_id"] == agent_eval.EVALUATION_USER_ID
    assert graph.config["configurable"]["thread_id"].startswith(
        f"user:{agent_eval.EVALUATION_USER_ID}:thread:eval-greeting-"
    )


def test_agent_evaluation_graph_uses_current_model_gateway_contract(
    tmp_path,
    monkeypatch,
):
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        app_environment="test",
        app_database_path=tmp_path / "app.db",
        checkpoint_database_path=tmp_path / "checkpoints.db",
        knowledge_source_directory=tmp_path / "knowledge",
        chroma_persist_directory=tmp_path / "chroma",
    )
    model = object()
    checkpointer = object()
    compiled_graph = object()
    captured = {}

    monkeypatch.setattr(agent_eval, "create_model", lambda active_settings: model)

    def fake_build_graph(**kwargs):
        captured.update(kwargs)
        return compiled_graph

    monkeypatch.setattr(agent_eval, "build_graph", fake_build_graph)

    result = agent_eval.build_evaluation_graph(settings, checkpointer)

    assert result is compiled_graph
    assert captured["settings"] is settings
    assert captured["model"] is model
    assert captured["checkpointer"] is checkpointer
    assert "owner_id" not in captured


def test_agent_evaluation_graph_executes_tools_with_trusted_user(
    tmp_path,
    monkeypatch,
):
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        app_environment="test",
        app_database_path=tmp_path / "app.db",
        checkpoint_database_path=tmp_path / "checkpoints.db",
        knowledge_source_directory=tmp_path / "knowledge",
        chroma_persist_directory=tmp_path / "chroma",
    )
    monkeypatch.setattr(
        agent_eval,
        "create_model",
        lambda active_settings: TodoToolCallingModel(),
    )
    graph = agent_eval.build_evaluation_graph(settings, InMemorySaver())

    result = agent_eval.evaluate_case(
        graph,
        {
            "id": "add_todo",
            "input": "帮我创建一个学习 LangGraph 的待办",
            "required_tools": ["add_todo"],
            "allowed_tools": ["add_todo"],
            "required_answer_keywords": ["待办"],
            "max_latency_seconds": 30,
        },
    )

    assert result["passed"] is True
    todos = TodoRepository(settings.app_database_path).list_all(
        agent_eval.EVALUATION_USER_ID
    )
    assert [todo.task for todo in todos] == ["学习 LangGraph"]


def test_rag_evaluation_stages_fixtures_in_user_directory(
    tmp_path,
    monkeypatch,
    capsys,
):
    fixture_directory = tmp_path / "fixtures"
    fixture_directory.mkdir()
    fixture_path = fixture_directory / "sample.md"
    fixture_path.write_text("LifePilot evaluation fixture", encoding="utf-8")
    monkeypatch.setattr(rag_eval, "FIXTURE_DIRECTORY", fixture_directory)
    monkeypatch.setattr(
        rag_eval,
        "load_cases",
        lambda: [
            {
                "id": "sample",
                "query": "LifePilot 是什么？",
                "expected_source": "sample.md",
            }
        ],
    )
    monkeypatch.setattr(
        rag_eval,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            deepseek_api_key="test-key",
            app_environment="test",
        ),
    )

    class FakeKnowledgeService:
        def __init__(self, settings) -> None:
            self.source_directory = settings.knowledge_source_directory
            self.closed = False

        def ingest(self, owner_id: str, filename: str) -> None:
            staged_path = self.source_directory / owner_id / filename
            assert staged_path.read_text(encoding="utf-8") == (
                "LifePilot evaluation fixture"
            )

        def search(self, owner_id: str, query: str):
            assert owner_id == rag_eval.EVALUATION_USER_ID
            assert query == "LifePilot 是什么？"
            return [SimpleNamespace(metadata={"source_name": "sample.md"})]

        def close(self) -> None:
            self.closed = True

    service_holder = {}

    def create_service(settings):
        service = FakeKnowledgeService(settings)
        service_holder["service"] = service
        return service

    monkeypatch.setattr(rag_eval, "create_knowledge_base_service", create_service)

    rag_eval.main()

    assert service_holder["service"].closed is True
    assert "RAG Hit@1: 100.0%" in capsys.readouterr().out
