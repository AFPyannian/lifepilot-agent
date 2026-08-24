from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any

from fastapi import FastAPI

from app.api.knowledge_routes import (
    router as knowledge_router,
)
from app.api.routes import (
    router as chat_router,
)
from app.checkpointing import (
    open_sqlite_checkpointer,
)
from app.config import (
    Settings,
    apply_runtime_environment,
    get_settings,
)
from app.graph import build_graph
from app.knowledge import (
    KnowledgeBaseService,
    create_knowledge_base_service,
)
from app.logging_config import (
    configure_logging,
    shutdown_logging,
)


def create_app(
    agent_graph: Any | None = None,
    knowledge_service: KnowledgeBaseService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """
    创建 FastAPI 应用。

    agent_graph 参数用于测试时注入 FakeGraph，
    避免调用真实 DeepSeek 和本地数据库。
    """

    @asynccontextmanager
    async def lifespan(
        application: FastAPI,
    ) -> AsyncIterator[None]:
        # 自动化测试可以直接注入 FakeGraph，
        # 此时不读取 .env，也不创建真实数据库。
        if agent_graph is not None:
            application.state.agent_graph = (
                agent_graph
            )
            application.state.graph_lock = Lock()
            application.state.settings = settings
            application.state.knowledge_service = (
                knowledge_service
            )

            yield
            return

        active_settings = (
            settings
            if settings is not None
            else get_settings()
        )

        apply_runtime_environment(
            active_settings
        )

        configure_logging(
            active_settings
        )

        try:
            active_knowledge_service = (
                    knowledge_service
                    or create_knowledge_base_service(
                active_settings
            )
            )

            # 这个 with 必须包围整个 yield。
            # 只有这样 SQLite Checkpointer 连接
            # 才会在 FastAPI 运行期间一直保持打开。
            with open_sqlite_checkpointer(
                active_settings
                .checkpoint_database_path
            ) as checkpointer:
                graph = build_graph(
                    settings=active_settings,
                    checkpointer=checkpointer,
                    knowledge_service=(
                        active_knowledge_service
                    ),
                    owner_id=(
                        active_settings.owner_id
                    ),
                )

                application.state.settings = (
                    active_settings
                )
                application.state.knowledge_service = (
                    active_knowledge_service
                )
                application.state.agent_graph = graph
                application.state.graph_lock = Lock()

                yield

        finally:
            shutdown_logging()

    application = FastAPI(
        title="LifePilot Agent API",
        description=(
            "基于 LangGraph 和 DeepSeek 的个人助理 Agent 后端服务"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    application.include_router(
        chat_router,
        prefix="/api/v1",
        tags=["LifePilot"],
    )

    application.include_router(
        knowledge_router,
        prefix="/api/v1",
        tags=["Knowledge Base"],
    )

    return application


app = create_app()