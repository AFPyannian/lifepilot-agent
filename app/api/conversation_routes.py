from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    Request,
    status,
)
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)

from app.api.interrupts import (
    find_pending_interrupt,
    normalize_approval_request,
)
from app.api.schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessage,
    ConversationSummary,
    DeleteConversationResponse,
    RenameConversationRequest,
)


router = APIRouter()

ThreadIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


@router.get(
    "/conversations",
    response_model=(
        ConversationListResponse
    ),
    summary="查看历史会话",
)
def list_conversations(
    request: Request,
) -> ConversationListResponse:
    (
        repository,
        settings,
        graph,
        graph_lock,
    ) = _get_dependencies(request)

    conversations = (
        repository.list_conversations(
            owner_id=settings.owner_id,
        )
    )

    return ConversationListResponse(
        conversations=[
            ConversationSummary(
                thread_id=(
                    conversation.thread_id
                ),
                title=conversation.title,
                created_at=(
                    conversation.created_at
                ),
                updated_at=(
                    conversation.updated_at
                ),
            )
            for conversation
            in conversations
        ]
    )


@router.get(
    "/conversations/{thread_id}",
    response_model=(
        ConversationDetailResponse
    ),
    summary="加载历史会话",
)
def get_conversation(
    thread_id: ThreadIdPath,
    request: Request,
) -> ConversationDetailResponse:
    (
        repository,
        settings,
        graph,
        graph_lock,
    ) = _get_dependencies(request)

    conversation = repository.get(
        owner_id=settings.owner_id,
        thread_id=thread_id,
    )

    if conversation is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail="会话不存在。",
        )

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    with graph_lock:
        snapshot = graph.get_state(
            config
        )

        pending_interrupt = (
            find_pending_interrupt(
                graph=graph,
                config=config,
            )
        )

    messages = _convert_messages(
        snapshot.values.get(
            "messages",
            [],
        )
    )

    pending_approval = None

    if pending_interrupt is not None:
        pending_approval = (
            normalize_approval_request(
                pending_interrupt
            )
        )

    return ConversationDetailResponse(
        thread_id=conversation.thread_id,
        title=conversation.title,
        created_at=(
            conversation.created_at
        ),
        updated_at=(
            conversation.updated_at
        ),
        messages=messages,
        pending_approval=(
            pending_approval
        ),
    )


@router.patch(
    "/conversations/{thread_id}",
    response_model=ConversationSummary,
    summary="重命名会话",
)
def rename_conversation(
    thread_id: ThreadIdPath,
    payload: RenameConversationRequest,
    request: Request,
) -> ConversationSummary:
    (
        repository,
        settings,
        graph,
        graph_lock,
    ) = _get_dependencies(request)

    renamed = repository.rename(
        owner_id=settings.owner_id,
        thread_id=thread_id,
        title=payload.title,
    )

    if not renamed:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail="会话不存在。",
        )

    conversation = repository.get(
        owner_id=settings.owner_id,
        thread_id=thread_id,
    )

    if conversation is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail="会话不存在。",
        )

    return ConversationSummary(
        thread_id=conversation.thread_id,
        title=conversation.title,
        created_at=(
            conversation.created_at
        ),
        updated_at=(
            conversation.updated_at
        ),
    )


@router.delete(
    "/conversations/{thread_id}",
    response_model=(
        DeleteConversationResponse
    ),
    summary="删除历史会话",
)
def delete_conversation(
    thread_id: ThreadIdPath,
    request: Request,
) -> DeleteConversationResponse:
    (
        repository,
        settings,
        graph,
        graph_lock,
    ) = _get_dependencies(request)

    conversation = repository.get(
        owner_id=settings.owner_id,
        thread_id=thread_id,
    )

    # 先检查业务元数据，可以避免一个用户
    # 删除不属于自己的checkpoint。
    if conversation is None:
        return DeleteConversationResponse(
            thread_id=thread_id,
            deleted=False,
        )

    checkpointer = getattr(
        request.app.state,
        "checkpointer",
        None,
    )

    if checkpointer is None:
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Checkpoint服务不可用。"
            ),
        )

    with graph_lock:
        # 使用公开接口，不直接操作
        # LangGraph内部数据库表。
        checkpointer.delete_thread(
            thread_id
        )

        metadata_deleted = (
            repository.delete(
                owner_id=(
                    settings.owner_id
                ),
                thread_id=thread_id,
            )
        )

    return DeleteConversationResponse(
        thread_id=thread_id,
        deleted=metadata_deleted,
    )


def _get_dependencies(
    request: Request,
) -> tuple[Any, Any, Any, Any]:
    repository = getattr(
        request.app.state,
        "conversation_repository",
        None,
    )

    settings = getattr(
        request.app.state,
        "settings",
        None,
    )

    graph = getattr(
        request.app.state,
        "agent_graph",
        None,
    )

    graph_lock = getattr(
        request.app.state,
        "graph_lock",
        None,
    )

    if (
        repository is None
        or settings is None
        or graph is None
        or graph_lock is None
    ):
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "会话管理服务不可用。"
            ),
        )

    return (
        repository,
        settings,
        graph,
        graph_lock,
    )


def _convert_messages(
    messages: Sequence[Any],
) -> list[ConversationMessage]:
    result: list[
        ConversationMessage
    ] = []

    for message in messages:
        if isinstance(
            message,
            HumanMessage,
        ):
            role = "user"

        elif isinstance(
            message,
            AIMessage,
        ):
            role = "assistant"

        else:
            # ToolMessage、SystemMessage等
            # 内部消息不直接展示。
            continue

        content = _content_to_text(
            message.content
        )

        if not content:
            continue

        result.append(
            ConversationMessage(
                role=role,
                content=content,
            )
        )

    return result


def _content_to_text(
    content: Any,
) -> str:
    if isinstance(content, str):
        return content.strip()

    if not isinstance(content, list):
        return ""

    parts: list[str] = []

    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue

        if isinstance(block, dict):
            text = block.get("text")

            if isinstance(text, str):
                parts.append(text)

    return "".join(parts).strip()