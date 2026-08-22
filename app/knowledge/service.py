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
    """文档导入结果"""
    source_name: str
    chunk_count: int
    already_indexed: bool


@dataclass(frozen=True)
class KnowledgeSource:
    """知识库文档摘要"""
    source_name: str
    chunk_count: int
    file_hash: str


class KnowledgeBaseService:
    """
        个人知识库业务服务。

        负责：
        1. 检查文件；
        2. 读取文件；
        3. 切分文本；
        4. 写入Chroma；
        5. 检索文档；
        6. 列出和删除知识库文档。
    """
    def __init__(
        self,
        source_directory: Path,
        vector_store_factory: Callable[[], Any],
        chunk_size: int = 700,
        chunk_overlap: int = 120,
        retrieval_k: int = 4,
        max_file_bytes: int = 20_000_000,
    ) -> None:
        # 将知识库目录转换成绝对路径
        self._source_directory = source_directory.resolve()

        self._source_directory.mkdir(parents=True, exist_ok=True)

        # 使用工厂函数延迟创建Chroma
        self._vector_store_factory = vector_store_factory
        self._vector_store: Any | None = None
        self._retrieval_k = retrieval_k
        self._max_file_bytes = max_file_bytes

        # 防止多个知识库工具同时首次访问时，
        # 重复创建Embedding模型和Chroma客户端。
        self._vector_store_lock = Lock()

        # 中文文本切分器
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
        """
        将knowledge_base目录中的文档导入Chroma。这里只接收文件名，不接收完整路径。
        """
        source_path = self._resolve_source(filename)

        # 根据文件内容计算哈希值
        file_hash = sha256(source_path.read_bytes()).hexdigest()

        store = self._get_store()
        # 查看同一用户是否已经导入过同名文档
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

        # 文件名相同且内容哈希相同，表示无需重复导入
        if existing_ids and all(
            metadata.get("file_hash") == file_hash
            for metadata in existing_metadata
        ):
            return IngestionResult(
                source_name=source_path.name,
                chunk_count=len(existing_ids),
                already_indexed=True,
            )

        # 读取TXT、Markdown或PDF
        documents = load_source_documents(source_path)

        # 给每个Document补充来源信息
        for document in documents:
            document.metadata.update(
                {
                    "owner_id": owner_id,
                    "source_name": source_path.name,
                    "source_type": source_path.suffix.lower(),
                    "file_hash": file_hash,
                }
            )

        # 把完整Document切分成多个Chunk
        chunks = self._text_splitter.split_documents(documents)

        if not chunks:
            raise ValueError("文档切分后没有可写入的内容")

        chunk_ids: list[str] = []

        for index, chunk in enumerate(chunks):
            # 保存Chunk序号
            chunk.metadata["chunk_index"] = index

            # 为每个Chunk生成稳定且唯一的ID
            chunk_id = sha256(
                (
                    f"{owner_id}:"
                    f"{source_path.name}:"
                    f"{file_hash}:"
                    f"{index}"
                ).encode("utf-8")
            ).hexdigest()

            chunk_ids.append(chunk_id)

        # 文件内容改变时，删除原来的旧Chunk
        if existing_ids:
            store.delete(ids=existing_ids)

        # 写入新Chunk
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
        """根据用户问题检索相关文档片段"""
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
        """列出指定用户已经导入的文档"""
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
        """
        删除指定文档在Chroma中的所有Chunk。

            注意：这里删除的是向量索引，不会删除knowledge_base目录里的原始文件。
        """
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

    def _get_store(self) -> Any:
        """
        延迟并且线程安全地创建Chroma。

        ToolNode可能并行执行多个工具，因此必须防止：
        1. 重复加载Embedding模型；
        2. 同时创建多个Chroma客户端；
        3. 多个客户端同时初始化同一个SQLite数据库。
        """
        if self._vector_store is not None:
            return self._vector_store

        with self._vector_store_lock:
            # 获得锁后再次检查，因为等待锁期间，
            # 另一个线程可能已经完成初始化。
            if self._vector_store is None:
                self._vector_store = (
                    self._vector_store_factory()
                )

        return self._vector_store

    def _resolve_source(self, filename: str) -> Path:
        """校验并取得knowledge_base中的文件路径。"""
        safe_filename = self._validate_filename(filename)
        source_path = (
            self._source_directory / safe_filename
        ).resolve()

        # 防止通过../读取目录外的文件
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
        """
        校验文件名。

            允许: agent_learning.md

            不允许: ../secret.txt
                   documents/file.pdf
        """
        clean_filename = filename.strip()

        if not clean_filename:
            raise ValueError("文件名不能为空")

        if Path(clean_filename).name != clean_filename:
            raise ValueError("请只提供文件名，不要提供目录路径")

        return clean_filename