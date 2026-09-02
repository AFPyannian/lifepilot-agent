"""运行知识库文档召回评估。"""

import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.config import get_settings
from app.knowledge import (
    create_knowledge_base_service,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FIXTURE_DIRECTORY = PROJECT_ROOT / "evaluations" / "fixtures"

CASES_PATH = PROJECT_ROOT / "evaluations" / "rag_cases.json"

EVALUATION_USER_ID = "rag-evaluation-user"


def load_cases() -> list[dict[str, Any]]:
    """读取 RAG 文档召回评估数据集。"""
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def stage_fixtures(source_directory: Path, owner_id: str) -> list[Path]:
    """按多用户知识库目录约定复制评估夹具。"""
    user_directory = source_directory / owner_id
    user_directory.mkdir(parents=True, exist_ok=True)

    staged_paths: list[Path] = []
    for fixture_path in sorted(FIXTURE_DIRECTORY.glob("*.md")):
        staged_path = user_directory / fixture_path.name
        shutil.copy2(fixture_path, staged_path)
        staged_paths.append(staged_path)

    return staged_paths


def main() -> None:
    """在临时 Chroma 数据库中运行 Hit@1 召回评估。"""
    cases = load_cases()
    results: list[dict[str, Any]] = []

    with TemporaryDirectory(prefix="lifepilot-rag-eval-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        source_directory = temporary_root / "knowledge"
        base_settings = get_settings()

        eval_settings = base_settings.model_copy(
            update={
                "app_environment": "test",
                "knowledge_source_directory": source_directory,
                "chroma_persist_directory": temporary_root / "chroma",
                "knowledge_retrieval_k": 1,
                "embedding_device": "cpu",
            }
        )

        service = create_knowledge_base_service(eval_settings)

        try:
            owner_id = EVALUATION_USER_ID

            for document_path in stage_fixtures(source_directory, owner_id):
                service.ingest(
                    owner_id=owner_id,
                    filename=document_path.name,
                )

            for case in cases:
                documents = service.search(
                    owner_id=owner_id,
                    query=case["query"],
                )

                retrieved_sources = [
                    document.metadata.get("source_name") for document in documents
                ]

                passed = case["expected_source"] in retrieved_sources

                result = {
                    "id": case["id"],
                    "passed": passed,
                    "query": case["query"],
                    "expected_source": (case["expected_source"]),
                    "retrieved_sources": (retrieved_sources),
                }

                results.append(result)

                status = "PASS" if passed else "FAIL"

                print(
                    f"[{status}] {case['id']} | "
                    f"expected="
                    f"{case['expected_source']} | "
                    f"retrieved="
                    f"{retrieved_sources}"
                )

        finally:
            # 删除临时目录前先释放 Chroma 文件句柄。
            service.close()

    passed_count = sum(result["passed"] for result in results)

    hit_at_1 = passed_count / len(results)

    print()
    print(f"RAG Hit@1: {hit_at_1:.1%}")

    if hit_at_1 < 0.75:
        sys.exit(1)


if __name__ == "__main__":
    main()
