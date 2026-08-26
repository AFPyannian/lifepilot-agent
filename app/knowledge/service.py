"""实现知识文档导入、检索、列举和删除服务。"""


from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from threading import Lock

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.knowledge.loaders import SUPPORTED_SUFFIXES, load_source_documents


@dataclass(frozen=True)
class IngestionResult:
    """记录文档索引结果。"""
    source_name: str
    chunk_count: int
    already_indexed: bool


@dataclass(frozen=True)
class KnowledgeSource:
    """记录知识文档摘要。"""
    source_name: str
    chunk_count: int
    file_hash: str


class KnowledgeBaseService:
    """协调文档校验、切分和向量存储操作。"""
    def __init__(
        self,
        source_directory: Path,
        vector_store_factory: Callable[[], Any],
        chunk_size: int = 700,
        chunk_overlap: int = 120,
        retrieval_k: int = 4,
        max_file_bytes: int = 20_000_000,
    ) -> None:

        """保存知识库配置并创建中文文本切分器。"""
        self._source_directory = source_directory.resolve()

        self._source_directory.mkdir(parents=True, exist_ok=True)


        self._vector_store_factory = vector_store_factory
        self._vector_store: Any | None = None
        self._retrieval_k = retrieval_k
        self._max_file_bytes = max_file_bytes


        self._vector_store_lock = Lock()


        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=[
                "\n\n", "\n", " ", "。", "！", "？", "；",
                "，", "、", ".", "!", "?", ";", ",", "",
            ],
        )

    def ingest(self, owner_id: str, filename: str) -> IngestionResult:
        """索引文档，并以内容哈希避免重复处理。"""
        source_path = self._resolve_source(filename)


        file_hash = sha256(source_path.read_bytes()).hexdigest()

        store = self._get_store()

        existing = store.get(
            where={
                "$and": [
                    {"owner_id": owner_id},
                    {"source_name": source_path.name},
                ]
            }
        )

        existing_ids = existing.get("ids", [])
        existing_metadata = existing.get("metadatas", [])


        if existing_ids and all(
            metadata.get("file_hash") == file_hash
            for metadata in existing_metadata
        ):
            return IngestionResult(
                source_name=source_path.name,
                chunk_count=len(existing_ids),
                already_indexed=True,
            )


        documents = load_source_documents(source_path)


        for document in documents:
            document.metadata.update(
                {
                    "owner_id": owner_id,
                    "source_name": source_path.name,
                    "source_type": source_path.suffix.lower(),
                    "file_hash": file_hash,
                }
            )


        chunks = self._text_splitter.split_documents(documents)

        if not chunks:
            raise ValueError("文档切分后没有可写入的内容")

        chunk_ids: list[str] = []

        for index, chunk in enumerate(chunks):

            chunk.metadata["chunk_index"] = index


            chunk_id = sha256(
                (
                    f"{owner_id}:"
                    f"{source_path.name}:"
                    f"{file_hash}:"
                    f"{index}"
                ).encode("utf-8")
            ).hexdigest()

            chunk_ids.append(chunk_id)


        if existing_ids:
            store.delete(ids=existing_ids)


        store.add_documents(
            documents=chunks,
            ids=chunk_ids,
        )

        return IngestionResult(
            source_name=source_path.name,
            chunk_count=len(chunks),
            already_indexed=False,
        )

    def search(self, owner_id: str, query: str) -> list[Document]:
        """检索当前用户最相关的文档片段。"""
        clean_query = query.strip()

        if not clean_query:
            raise ValueError("检索问题不能为空")

        return self._get_store().max_marginal_relevance_search(
            query=clean_query,
            k=self._retrieval_k,
            fetch_k=max(self._retrieval_k * 3, 10),
            lambda_mult=0.7,
            filter={"owner_id": owner_id},
        )

    def list_sources(self, owner_id: str) -> list[KnowledgeSource]:
        """汇总当前用户已经索引的文档。"""
        result = self._get_store().get(
            where={"owner_id": owner_id}
        )

        sources: dict[str, KnowledgeSource] = {}

        for metadata in result.get("metadatas", []):
            source_name = metadata["source_name"]

            if source_name not in sources:
                sources[source_name] = KnowledgeSource(
                    source_name=source_name,
                    chunk_count=0,
                    file_hash=metadata["file_hash"],
                )

            current = sources[source_name]

            sources[source_name] = KnowledgeSource(
                source_name=current.source_name,
                chunk_count=current.chunk_count + 1,
                file_hash=current.file_hash,
            )

        return sorted(
            sources.values(),
            key=lambda source: source.source_name,
        )

    def delete_source(self, owner_id: str, filename: str) -> bool:
        """删除指定文档的全部向量片段。"""
        safe_filename = self._validate_filename(filename)

        result = self._get_store().get(
            where={
                "$and": [
                    {"owner_id": owner_id},
                    {"source_name": safe_filename},
                ]
            }
        )

        document_ids = result.get("ids", [])

        if not document_ids:
            return False

        self._get_store().delete(ids=document_ids)
        return True

    def close(self) -> None:
        """关闭底层向量数据库客户端并释放文件句柄。"""
        with self._vector_store_lock:
            vector_store = self._vector_store
            self._vector_store = None

        if vector_store is None:
            return


        close_vector_store = getattr(
            vector_store,
            "close",
            None,
        )

        if callable(close_vector_store):
            close_vector_store()
            return


        client = getattr(
            vector_store,
            "_client",
            None,
        )

        close_client = getattr(
            client,
            "close",
            None,
        )

        if callable(close_client):
            close_client()

    def _get_store(self) -> Any:
        """线程安全地延迟创建向量存储。"""
        if self._vector_store is not None:
            return self._vector_store

        with self._vector_store_lock:


            # 锁内再次检查，避免并发创建多个存储实例。
            if self._vector_store is None:
                self._vector_store = (
                    self._vector_store_factory()
                )

        return self._vector_store

    def _resolve_source(self, filename: str) -> Path:
        """校验并返回知识库根目录中的源文件。"""
        safe_filename = self._validate_filename(filename)
        source_path = (
            self._source_directory / safe_filename
        ).resolve()


        # 解析后的父目录必须仍是知识库根目录。
        if source_path.parent != self._source_directory:
            raise ValueError("只能读取 knowledge_base 目录中的文件")

        if not source_path.exists():
            raise ValueError(f"文件不存在：{safe_filename}")

        if not source_path.is_file():
            raise ValueError("指定对象不是文件")

        if source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError("只支持 TXT、Markdown 和 PDF 文件")

        if source_path.stat().st_size > self._max_file_bytes:
            raise ValueError("文件大小超过知识库配置限制")

        return source_path

    @staticmethod
    def _validate_filename(filename: str) -> str:
        """拒绝目录路径和不安全文件名。"""
        clean_filename = filename.strip()

        if not clean_filename:
            raise ValueError("文件名不能为空")

        if Path(clean_filename).name != clean_filename:
            raise ValueError("请只提供文件名，不要提供目录路径")

        return clean_filename