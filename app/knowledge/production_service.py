"""基于对象存储和 pgvector 的生产知识库服务。"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, cast
from uuid import uuid4

from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.config import Settings
from app.database import Database
from app.database_models import KnowledgeChunkRow, KnowledgeDocumentRow
from app.knowledge.loaders import load_source_documents
from app.knowledge.service import IngestionResult, KnowledgeSource
from app.knowledge.vector_store import create_embedding_model
from app.storage import S3ObjectStorage


class ProductionKnowledgeService:
    """协调 S3 源文件、PostgreSQL 元数据和 pgvector 检索。"""

    uses_object_storage = True

    def __init__(
        self,
        database: Database,
        settings: Settings,
        storage: S3ObjectStorage | None = None,
        embedding_factory: Callable[[], HuggingFaceEmbeddings] | None = None,
    ) -> None:
        self._database = database
        self._settings = settings
        self._storage = storage or S3ObjectStorage(settings)
        self._embedding_factory = embedding_factory or (
            lambda: create_embedding_model(settings)
        )
        self._embedding_model: HuggingFaceEmbeddings | None = None
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.knowledge_chunk_size,
            chunk_overlap=settings.knowledge_chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", "。", "！", "？", "；", "，", "、", ""],
        )

    def _embeddings(self) -> HuggingFaceEmbeddings:
        if self._embedding_model is None:
            self._embedding_model = self._embedding_factory()
        return self._embedding_model

    def submit_upload(
        self,
        *,
        owner_id: str,
        filename: str,
        source: BinaryIO,
        content_type: str | None,
    ) -> tuple[IngestionResult, str | None]:
        """上传源文件并在提交事务后投递幂等索引任务。"""
        digest = hashlib.sha256()
        size_bytes = 0
        source.seek(0)
        while chunk := source.read(1024 * 1024):
            size_bytes += len(chunk)
            if size_bytes > self._settings.knowledge_max_file_bytes:
                raise ValueError("上传文件超过允许的大小限制。")
            digest.update(chunk)
        if size_bytes == 0:
            raise ValueError("不能上传空文件。")
        file_hash = digest.hexdigest()

        with self._database.session() as session:
            existing = session.scalar(
                select(KnowledgeDocumentRow).where(
                    KnowledgeDocumentRow.owner_id == owner_id,
                    KnowledgeDocumentRow.filename == filename,
                )
            )
            if existing is not None and existing.sha256 == file_hash:
                count = session.scalar(
                    select(func.count(KnowledgeChunkRow.id)).where(
                        KnowledgeChunkRow.document_id == existing.id
                    )
                )
                if existing.status == "ready":
                    return (
                        IngestionResult(filename, int(count or 0), True, "ready"),
                        None,
                    )

        document_id = existing.id if existing is not None else str(uuid4())
        object_key = f"users/{owner_id}/knowledge/{document_id}/{filename}"
        source.seek(0)
        self._storage.upload(source, object_key, content_type)
        timestamp = datetime.now(UTC)
        statement = insert(KnowledgeDocumentRow).values(
            id=document_id,
            owner_id=owner_id,
            filename=filename,
            object_key=object_key,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=file_hash,
            status="queued",
            error_code=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_knowledge_owner_filename",
            set_={
                "object_key": object_key,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "sha256": file_hash,
                "status": "queued",
                "error_code": None,
                "updated_at": timestamp,
            },
        )
        with self._database.session() as session:
            session.execute(statement)

        from app.tasks.knowledge import ingest_knowledge_document

        task = ingest_knowledge_document.delay(document_id)
        return IngestionResult(filename, 0, False, "queued"), cast(str, task.id)

    def ingest_document(self, document_id: str) -> IngestionResult:
        """由 Celery Worker 幂等解析、切分并重建指定文档向量。"""
        with self._database.session() as session:
            document = session.get(KnowledgeDocumentRow, document_id)
            if document is None:
                raise ValueError("知识文档不存在")
            document.status = "processing"
            document.error_code = None
            document.updated_at = datetime.now(UTC)
            object_key = document.object_key
            filename = document.filename
            owner_id = document.owner_id
            file_hash = document.sha256

        try:
            with TemporaryDirectory(prefix="lifepilot-knowledge-") as temp_dir:
                source_path = Path(temp_dir) / filename
                self._storage.download(object_key, source_path)
                documents = load_source_documents(source_path)
                for item in documents:
                    item.metadata.update(
                        {
                            "owner_id": owner_id,
                            "source_name": filename,
                            "source_type": source_path.suffix.lower(),
                            "file_hash": file_hash,
                        }
                    )
                chunks = self._splitter.split_documents(documents)
                if not chunks:
                    raise ValueError("文档切分后没有可写入的内容")
                vectors = self._embeddings().embed_documents(
                    [chunk.page_content for chunk in chunks]
                )

            timestamp = datetime.now(UTC)
            with self._database.session() as session:
                session.execute(
                    delete(KnowledgeChunkRow).where(
                        KnowledgeChunkRow.document_id == document_id
                    )
                )
                for index, (chunk, vector) in enumerate(
                    zip(chunks, vectors, strict=True)
                ):
                    session.add(
                        KnowledgeChunkRow(
                            id=hashlib.sha256(
                                f"{document_id}:{file_hash}:{index}".encode()
                            ).hexdigest(),
                            document_id=document_id,
                            owner_id=owner_id,
                            chunk_index=index,
                            content=chunk.page_content,
                            chunk_metadata=chunk.metadata,
                            embedding=vector,
                            created_at=timestamp,
                        )
                    )
                row = session.get(KnowledgeDocumentRow, document_id)
                if row is None:
                    raise ValueError("知识文档已被删除")
                row.status = "ready"
                row.error_code = None
                row.updated_at = timestamp
            return IngestionResult(filename, len(chunks), False, "ready")
        except Exception:
            with self._database.session() as session:
                row = session.get(KnowledgeDocumentRow, document_id)
                if row is not None:
                    row.status = "failed"
                    row.error_code = "ingestion_failed"
                    row.updated_at = datetime.now(UTC)
            raise

    def search(self, owner_id: str, query: str) -> list[Document]:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("检索问题不能为空")
        vector = self._embeddings().embed_query(clean_query)
        distance = KnowledgeChunkRow.embedding.cosine_distance(vector)
        with self._database.session() as session:
            rows = session.execute(
                select(KnowledgeChunkRow, KnowledgeDocumentRow.filename, distance)
                .join(
                    KnowledgeDocumentRow,
                    KnowledgeDocumentRow.id == KnowledgeChunkRow.document_id,
                )
                .where(
                    KnowledgeChunkRow.owner_id == owner_id,
                    KnowledgeDocumentRow.status == "ready",
                )
                .order_by(distance)
                .limit(self._settings.knowledge_retrieval_k)
            ).all()
        return [
            Document(
                page_content=row[0].content,
                metadata={**row[0].chunk_metadata, "source_name": row[1]},
            )
            for row in rows
        ]

    def list_sources(self, owner_id: str) -> list[KnowledgeSource]:
        with self._database.session() as session:
            rows = session.execute(
                select(
                    KnowledgeDocumentRow.filename,
                    KnowledgeDocumentRow.sha256,
                    KnowledgeDocumentRow.status,
                    func.count(KnowledgeChunkRow.id),
                )
                .outerjoin(
                    KnowledgeChunkRow,
                    KnowledgeChunkRow.document_id == KnowledgeDocumentRow.id,
                )
                .where(KnowledgeDocumentRow.owner_id == owner_id)
                .group_by(KnowledgeDocumentRow.id)
                .order_by(KnowledgeDocumentRow.filename)
            ).all()
        return [KnowledgeSource(row[0], int(row[3]), row[1], row[2]) for row in rows]

    def delete_source(self, owner_id: str, filename: str) -> bool:
        with self._database.session() as session:
            document = session.scalar(
                select(KnowledgeDocumentRow).where(
                    KnowledgeDocumentRow.owner_id == owner_id,
                    KnowledgeDocumentRow.filename == filename,
                )
            )
            if document is None:
                return False
            object_key = document.object_key
        self._storage.delete(object_key)
        with self._database.session() as session:
            result = session.execute(
                delete(KnowledgeDocumentRow).where(
                    KnowledgeDocumentRow.owner_id == owner_id,
                    KnowledgeDocumentRow.filename == filename,
                )
            )
            return bool(getattr(result, "rowcount", 0))

    def close(self) -> None:
        """对象存储和 SQLAlchemy 连接由应用生命周期统一管理。"""

    def ping(self) -> None:
        """验证对象存储 Bucket 可访问。"""
        self._storage.ping()
