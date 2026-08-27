"""运行 Agent 工具轨迹和回答质量评估。"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.checkpointing import open_sqlite_checkpointer
from app.config import get_settings
from app.graph import build_graph
from app.observability import configure_observability
from app.repositories.note_repository import NoteRepository
from app.repositories.todo_repository import TodoRepository
from app.repositories.user_memory_repository import UserMemoryRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CASES_PATH = PROJECT_ROOT / "evaluations" / "agent_cases.json"

REPORT_DIRECTORY = PROJECT_ROOT / "evaluation_reports"


def load_cases() -> list[dict[str, Any]]:
    """读取 Agent 离线评估数据集。"""
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def extract_tool_names(messages: list[Any]) -> list[str]:
    """从模型消息轨迹中提取工具名称。"""
    tool_names: list[str] = []

    for message in messages:
        if not isinstance(message, AIMessage):
            continue

        for tool_call in message.tool_calls:
            tool_name = tool_call.get("name")

            if isinstance(tool_name, str):
                tool_names.append(tool_name)

    return tool_names


def extract_final_reply(messages: list[Any]) -> str:
    """从消息轨迹中提取最后一条非空模型回复。"""
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue

        if isinstance(message.content, str):
            content = message.content.strip()

            if content:
                return content

    return ""


def evaluate_case(graph: Any, case: dict[str, Any]) -> dict[str, Any]:
    """运行并评价一个 Agent 用例。"""
    thread_id = f"eval-{case['id']}-{uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id,
        },
        "run_name": f"eval_{case['id']}",
        "tags": [
            "lifepilot",
            "offline-evaluation",
        ],
        "metadata": {
            "evaluation_case_id": case["id"],
            "environment": "test",
        },
    }

    started_at = perf_counter()

    try:
        result = graph.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": case["input"],
                    }
                ]
            },
            config=config,
        )

        latency_seconds = perf_counter() - started_at

        messages = result.get("messages", [])
        actual_tools = extract_tool_names(messages)
        final_reply = extract_final_reply(messages)

        required_tools = set(case.get("required_tools", []))

        allowed_tools = set(case.get("allowed_tools", case.get("required_tools", [])))

        actual_tool_set = set(actual_tools)

        required_tools_called = required_tools.issubset(actual_tool_set)

        no_unexpected_tools = actual_tool_set.issubset(allowed_tools)

        required_keywords = case.get("required_answer_keywords", [])

        keyword_pass = all(
            keyword.lower() in final_reply.lower() for keyword in required_keywords
        )

        latency_pass = latency_seconds <= case.get("max_latency_seconds", 60)

        interrupted = bool(result.get("__interrupt__"))

        passed = all(
            [
                required_tools_called,
                no_unexpected_tools,
                keyword_pass,
                latency_pass,
                not interrupted,
                bool(final_reply),
            ]
        )

        return {
            "id": case["id"],
            "passed": passed,
            "input": case["input"],
            "required_tools": sorted(required_tools),
            "allowed_tools": sorted(allowed_tools),
            "actual_tools": actual_tools,
            "required_tools_called": (required_tools_called),
            "no_unexpected_tools": (no_unexpected_tools),
            "keyword_pass": keyword_pass,
            "latency_pass": latency_pass,
            "latency_seconds": round(
                latency_seconds,
                3,
            ),
            "interrupted": interrupted,
            "final_reply": final_reply,
            "error": None,
        }

    except Exception as error:
        return {
            "id": case["id"],
            "passed": False,
            "input": case["input"],
            "actual_tools": [],
            "latency_seconds": round(
                perf_counter() - started_at,
                3,
            ),
            "final_reply": "",
            "error": (f"{type(error).__name__}: {error}"),
        }


def print_result(
    result: dict[str, Any],
) -> None:
    """在控制台输出一个评估用例的摘要。"""
    status = "PASS" if result["passed"] else "FAIL"

    print(
        f"[{status}] {result['id']} | "
        f"tools={result.get('actual_tools', [])} | "
        f"latency={result['latency_seconds']}s"
    )

    if result.get("error"):
        print(f"  error: {result['error']}")


def write_report(results: list[dict[str, Any]]) -> Path:
    """将评估结果写入带时间戳的 JSON 报告。"""
    REPORT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    passed_count = sum(result["passed"] for result in results)

    total_count = len(results)

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "total_cases": total_count,
        "passed_cases": passed_count,
        "failed_cases": total_count - passed_count,
        "pass_rate": (passed_count / total_count if total_count else 0),
        "results": results,
    }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    report_path = REPORT_DIRECTORY / f"agent-eval-{timestamp}.json"

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return report_path


def main() -> None:
    """在隔离数据库中运行 Agent 评估并应用通过率门槛。"""
    parser = argparse.ArgumentParser(
        description="运行LifePilot Agent离线评估",
    )

    parser.add_argument(
        "--case",
        help="只运行指定ID的评估用例",
    )

    parser.add_argument(
        "--minimum-pass-rate",
        type=float,
        default=0.75,
        help="最低通过率，默认0.75",
    )

    args = parser.parse_args()
    cases = load_cases()

    if args.case:
        cases = [case for case in cases if case["id"] == args.case]

        if not cases:
            raise SystemExit(f"没有找到评估用例：{args.case}")

    results: list[dict[str, Any]] = []

    with TemporaryDirectory(prefix="lifepilot-agent-eval-") as temporary_directory:
        temporary_root = Path(temporary_directory)

        base_settings = get_settings()

        eval_settings = base_settings.model_copy(
            update={
                "app_environment": "test",
                "owner_id": "evaluation-user",
                "default_thread_id": "evaluation",
                "app_database_path": temporary_root / "app.db",
                "checkpoint_database_path": temporary_root / "checkpoints.db",
                "knowledge_source_directory": temporary_root / "knowledge",
                "chroma_persist_directory": temporary_root / "chroma",
                "langsmith_project": "lifepilot-evaluation",
            }
        )

        configure_observability(eval_settings)

        todo_repository = TodoRepository(eval_settings.app_database_path)

        note_repository = NoteRepository(eval_settings.app_database_path)

        memory_repository = UserMemoryRepository(eval_settings.app_database_path)

        with open_sqlite_checkpointer(
            eval_settings.checkpoint_database_path
        ) as checkpointer:
            graph = build_graph(
                settings=eval_settings,
                checkpointer=checkpointer,
                todo_repository=(todo_repository),
                note_repository=(note_repository),
                memory_repository=(memory_repository),
                owner_id=(eval_settings.owner_id),
            )

            for case in cases:
                result = evaluate_case(
                    graph,
                    case,
                )

                results.append(result)
                print_result(result)

    report_path = write_report(results)

    pass_rate = sum(result["passed"] for result in results) / len(results)

    print()
    print(f"Pass rate: {pass_rate:.1%}")
    print(f"Report: {report_path}")

    if pass_rate < args.minimum_pass_rate:
        sys.exit(1)


if __name__ == "__main__":
    main()
