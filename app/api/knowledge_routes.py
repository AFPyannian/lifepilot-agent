import logging
import os
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from starlette.concurrency import (
    run_in_threadpool,
)

from app.api.schemas import (
    KnowledgeDeleteResponse,
    KnowledgeDocumentItem,
    KnowledgeDocumentResponse,
    KnowledgeListResponse,
)
from app.knowledge.loaders import (
    SUPPORTED_SUFFIXES,
)


logger = logging.getLogger(
    "lifepilot.api.knowledge"
)

router = APIRouter()

UPLOAD_CHUNK_SIZE = 1024 * 1024

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


@router.post(
    "/knowledge/documents",
    response_model=KnowledgeDocumentResponse,
    summary="上传并导入知识库文档",
)
async def upload_knowledge_document(
    request: Request,
    file: Annotated[
        UploadFile,
        File(
            description=(
                "TXT、Markdown 或 PDF 文档"
            )
        ),
    ],
) -> KnowledgeDocumentResponse:
    service, settings, graph_lock = (
        _get_knowledge_dependencies(request)
    )

    filename = _validate_filename(
        file.filename
    )

    source_path = _safe_source_path(
        source_directory=(
            settings
            .knowledge_source_directory
        ),
        filename=filename,
    )

    try:
        await _save_upload_file(
            upload=file,
            destination=source_path,
            max_file_bytes=(
                settings
                .knowledge_max_file_bytes
            ),
        )

        def ingest_document() -> Any:
            with graph_lock:
                return service.ingest(
                    owner_id=settings.owner_id,
                    filename=filename,
                )

        result = await run_in_threadpool(
            ingest_document
        )

        logger.info(
            "Knowledge document imported "
            "filename=%s chunks=%s",
            result.source_name,
            result.chunk_count,
        )

        return KnowledgeDocumentResponse(
            filename=result.source_name,
            chunk_count=result.chunk_count,
            already_indexed=(
                result.already_indexed
            ),
        )

    except ValueError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=str(error),
        ) from error

    except HTTPException:
        raise

    except Exception as error:
        logger.exception(
            "Knowledge document upload failed "
            "filename=%s",
            filename,
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "文档导入失败，请检查文件"
                "内容后重试。"
            ),
        ) from error

    finally:
        await file.close()


@router.get(
    "/knowledge/documents",
    response_model=KnowledgeListResponse,
    summary="查看知识库文档",
)
async def list_knowledge_documents(
    request: Request,
) -> KnowledgeListResponse:
    service, settings, graph_lock = (
        _get_knowledge_dependencies(request)
    )

    def list_documents() -> Any:
        with graph_lock:
            return service.list_sources(
                settings.owner_id
            )

    try:
        sources = await run_in_threadpool(
            list_documents
        )

    except Exception as error:
        logger.exception(
            "Failed to list knowledge documents"
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="读取知识库文档列表失败。",
        ) from error

    return KnowledgeListResponse(
        documents=[
            KnowledgeDocumentItem(
                filename=source.source_name,
                chunk_count=(
                    source.chunk_count
                ),
            )
            for source in sources
        ]
    )


@router.delete(
    "/knowledge/documents/{filename}",
    response_model=KnowledgeDeleteResponse,
    summary="删除知识库文档",
)
async def delete_knowledge_document(
    filename: str,
    request: Request,
) -> KnowledgeDeleteResponse:
    service, settings, graph_lock = (
        _get_knowledge_dependencies(request)
    )

    safe_filename = _validate_filename(
        filename
    )

    source_path = _safe_source_path(
        source_directory=(
            settings
            .knowledge_source_directory
        ),
        filename=safe_filename,
    )

    def delete_document() -> bool:
        with graph_lock:
            vector_deleted = (
                service.delete_source(
                    owner_id=settings.owner_id,
                    filename=safe_filename,
                )
            )

            file_deleted = False

            if (
                source_path.exists()
                and source_path.is_file()
            ):
                source_path.unlink()
                file_deleted = True

            return (
                vector_deleted
                or file_deleted
            )

    try:
        deleted = await run_in_threadpool(
            delete_document
        )

    except ValueError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Knowledge document deletion failed "
            "filename=%s",
            safe_filename,
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="删除知识库文档失败。",
        ) from error

    return KnowledgeDeleteResponse(
        filename=safe_filename,
        deleted=deleted,
    )


def _get_knowledge_dependencies(
    request: Request,
) -> tuple[Any, Any, Any]:
    service = getattr(
        request.app.state,
        "knowledge_service",
        None,
    )

    settings = getattr(
        request.app.state,
        "settings",
        None,
    )

    graph_lock = getattr(
        request.app.state,
        "graph_lock",
        None,
    )

    if (
        service is None
        or settings is None
        or graph_lock is None
    ):
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail="知识库服务当前不可用。",
        )

    return service, settings, graph_lock


def _validate_filename(
    raw_filename: str | None,
) -> str:
    if raw_filename is None:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail="上传文件缺少文件名。",
        )

    filename = raw_filename.strip()

    if not filename or len(filename) > 255:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail="文件名无效。",
        )

    forbidden_characters = '<>:"/\\|?*'

    if any(
        character in forbidden_characters
        or ord(character) < 32
        for character in filename
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "文件名包含不允许的字符。"
            ),
        )

    if filename.endswith((".", " ")):
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "文件名不能以空格或点结尾。"
            ),
        )

    reserved_name = (
        filename
        .split(".", maxsplit=1)[0]
        .upper()
    )

    if reserved_name in WINDOWS_RESERVED_NAMES:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "该文件名是 Windows 保留名称。"
            ),
        )

    if (
        Path(filename).suffix.lower()
        not in SUPPORTED_SUFFIXES
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "只允许上传 TXT、Markdown "
                "和 PDF 文件。"
            ),
        )

    return filename


def _safe_source_path(
    source_directory: Path,
    filename: str,
) -> Path:
    root = source_directory.resolve()

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_path = (
        root / filename
    ).resolve()

    if source_path.parent != root:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail="文件路径不安全。",
        )

    return source_path


async def _save_upload_file(
    upload: UploadFile,
    destination: Path,
    max_file_bytes: int,
) -> None:
    temporary_path = (
        destination.parent
        / f".upload-{uuid4().hex}.tmp"
    )

    total_bytes = 0

    try:
        with temporary_path.open(
            "xb"
        ) as output_file:
            while chunk := await upload.read(
                UPLOAD_CHUNK_SIZE
            ):
                total_bytes += len(chunk)

                if (
                    total_bytes
                    > max_file_bytes
                ):
                    raise ValueError(
                        "上传文件超过允许的"
                        "大小限制。"
                    )

                output_file.write(chunk)

        if total_bytes == 0:
            raise ValueError(
                "不能上传空文件。"
            )

        # 临时文件完整写入后再替换目标，
        # 避免留下只写了一部分的文件。
        os.replace(
            temporary_path,
            destination,
        )

    finally:
        temporary_path.unlink(
            missing_ok=True
        )