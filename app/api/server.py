from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from swagger_ui_bundle import swagger_ui_path

from app.api.conversation_routes import router as conversation_router
from app.api.knowledge_routes import router as knowledge_router
from app.api.routes import router as chat_router
from app.api.middleware import RequestContextMiddleware
from app.checkpointing import open_sqlite_checkpointer
from app.config import Settings, apply_runtime_environment, get_settings
from app.graph import build_graph
from app.knowledge import KnowledgeBaseService, create_knowledge_base_service
from app.logging_config import configure_logging, shutdown_logging
from app.observability import configure_observability
from app.repositories.conversation_repository import  ConversationRepository


def create_app(
    agent_graph: Any | None = None,
    knowledge_service: KnowledgeBaseService | None = None,
    settings: Settings | None = None,
    conversation_repository: ConversationRepository | None = None,
) -> FastAPI:
    """
    创建FastAPI应用。可选参数主要用于自动化测试

    Arg:
        agent_graph: 注入FakeGraph，避免调用真实DeepSeek。
        knowledge_service: 注入FakeKnowledgeService，避免加载Embedding模型和真实Chroma。
        settings: 注入测试配置。
        conversation_repository: 注入测试会话Repository。
    """

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active_conversation_repository = conversation_repository

        # 自动化测试可以直接注入FakeGraph。此时不读取.env、不创建真实数据库，也不加载Embedding模型。
        if agent_graph is not None:
            application.state.agent_graph = agent_graph
            application.state.graph_lock = Lock()
            application.state.settings = settings
            application.state.knowledge_service = knowledge_service
            application.state.conversation_repository = active_conversation_repository

            # 如果FakeGraph提供checkpointer，会话删除测试也可以验证delete_thread()是否被调用。
            application.state.checkpointer = (
                getattr(agent_graph, "checkpointer", None)
            )

            yield
            return

        active_settings = (
            settings
            if settings is not None
            else get_settings()
        )

        apply_runtime_environment(active_settings)

        configure_logging(active_settings)

        configure_observability(active_settings)

        try:
            # 会话元数据与待办、笔记等业务数据共用lifepilot.db，但使用独立的数据表。
            if active_conversation_repository is None:
                active_conversation_repository = (
                    ConversationRepository(active_settings.app_database_path)
                )

            active_knowledge_service = (
                knowledge_service or create_knowledge_base_service(active_settings)
            )

            # 这个with必须包围整个yield。只有这样SQLite Checkpointer连接才会在FastAPI运行期间保持打开。
            with open_sqlite_checkpointer(
                active_settings.checkpoint_database_path
            ) as active_checkpointer:
                graph = build_graph(
                    settings=active_settings,
                    checkpointer=active_checkpointer,
                    knowledge_service=active_knowledge_service,
                    owner_id=active_settings.owner_id,
                )

                application.state.settings = active_settings
                application.state.knowledge_service = active_knowledge_service
                application.state.conversation_repository =  active_conversation_repository
                application.state.checkpointer = active_checkpointer
                application.state.agent_graph = graph
                application.state.graph_lock = Lock()

                yield

        finally:
            shutdown_logging()

    application = FastAPI(
        title="LifePilot Agent API",
        description="基于LangGraph和DeepSeek的个人助理Agent后端服务",
        version="0.1.0",
        lifespan=lifespan,
        # 禁用FastAPI默认的在线Swagger资源，后面改用本地静态资源。
        docs_url=None,
    )

    application.add_middleware(RequestContextMiddleware)

    # 加载本地Swagger UI资源，
    # 避免浏览器访问外部CDN。
    application.mount(
        "/docs-assets",
        StaticFiles(
            directory=swagger_ui_path
        ),
        name="swagger-ui-assets",
    )

    @application.get(
        "/docs",
        include_in_schema=False,
    )
    async def custom_swagger_ui():
        """返回使用本地静态资源的Swagger UI。"""

        return get_swagger_ui_html(
            openapi_url=(
                application.openapi_url
                or "/openapi.json"
            ),
            title=(
                f"{application.title} "
                "- Swagger UI"
            ),
            swagger_js_url=(
                "/docs-assets/"
                "swagger-ui-bundle.js"
            ),
            swagger_css_url=(
                "/docs-assets/"
                "swagger-ui.css"
            ),
            swagger_favicon_url=(
                "/docs-assets/"
                "favicon-32x32.png"
            ),
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

    application.include_router(
        conversation_router,
        prefix="/api/v1",
        tags=["Conversations"],
    )

    return application


app = create_app()