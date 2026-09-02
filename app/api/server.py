"""创建并配置 LifePilot FastAPI 应用。"""

from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.base import BaseCheckpointSaver
from swagger_ui_bundle import swagger_ui_path  # type: ignore[import-untyped]

from app.access.policy import AccessPolicy, AccessPolicyProtocol, AllowAllAccessPolicy
from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.conversation_routes import router as conversation_router
from app.api.health_routes import router as health_router
from app.api.knowledge_routes import router as knowledge_router
from app.api.middleware import RequestContextMiddleware
from app.api.model_routes import router as model_router
from app.api.rate_limit import SlidingWindowRateLimitMiddleware
from app.api.routes import router as chat_router
from app.api.security import require_current_user
from app.api.usage_routes import router as usage_router
from app.auth.rate_limit import LoginRateLimiter
from app.auth.service import AuthService
from app.checkpointing import open_postgres_checkpointer, open_sqlite_checkpointer
from app.config import Settings, apply_runtime_environment, get_settings
from app.credentials.crypto import CredentialCipher
from app.credentials.service import ProviderCredentialService
from app.exceptions import ExecutionBusyError
from app.graph import build_graph
from app.infrastructure import create_repositories
from app.knowledge import KnowledgeBaseService, create_knowledge_base_service
from app.knowledge.production_service import ProductionKnowledgeService
from app.locks import LocalExecutionLock, PostgresExecutionLock
from app.logging_config import configure_logging, shutdown_logging
from app.model import DeepSeekCredentialValidator
from app.model_gateway import DeepSeekModelGateway
from app.observability import configure_observability
from app.quota.service import QuotaService
from app.redis_rate_limit import RedisApiRateLimiter, RedisLoginRateLimiter
from app.repositories.protocols import (
    AuditRepositoryProtocol,
    AuthRepositoryProtocol,
    ConversationRepositoryProtocol,
    EntitlementRepositoryProtocol,
    ProviderCredentialRepositoryProtocol,
    QuotaRepositoryProtocol,
    UsageRepositoryProtocol,
)
from app.usage.service import UsageTracker


def create_app(
    agent_graph: Any | None = None,
    knowledge_service: KnowledgeBaseService | None = None,
    settings: Settings | None = None,
    conversation_repository: ConversationRepositoryProtocol | None = None,
    auth_service: AuthService | None = None,
    audit_repository: AuditRepositoryProtocol | None = None,
    login_rate_limiter: LoginRateLimiter | None = None,
    registration_rate_limiter: LoginRateLimiter | None = None,
    provider_credential_service: ProviderCredentialService | None = None,
    access_policy: AccessPolicyProtocol | None = None,
    entitlement_repository: EntitlementRepositoryProtocol | None = None,
    usage_repository: UsageRepositoryProtocol | None = None,
    quota_service: QuotaService | None = None,
) -> FastAPI:
    """创建可注入测试依赖的 FastAPI 应用。"""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """初始化生产依赖，并在应用退出时释放资源。"""
        active_conversation_repository = conversation_repository

        if agent_graph is not None:
            application.state.agent_graph = agent_graph
            application.state.graph_lock = LocalExecutionLock()
            application.state.settings = settings
            application.state.knowledge_service = knowledge_service
            application.state.conversation_repository = active_conversation_repository
            application.state.auth_service = auth_service
            application.state.auth_repository = getattr(
                auth_service, "_repository", None
            )
            application.state.audit_repository = audit_repository
            application.state.login_rate_limiter = (
                login_rate_limiter
                or LoginRateLimiter(
                    max_failures=5,
                    window_seconds=900,
                )
            )
            application.state.registration_rate_limiter = (
                registration_rate_limiter
                or LoginRateLimiter(
                    max_failures=10,
                    window_seconds=900,
                )
            )
            application.state.provider_credential_service = provider_credential_service
            application.state.access_policy = access_policy or AllowAllAccessPolicy()
            application.state.entitlement_repository = entitlement_repository
            application.state.usage_repository = usage_repository
            application.state.quota_service = quota_service

            application.state.checkpointer = getattr(agent_graph, "checkpointer", None)

            yield
            return

        active_settings = settings if settings is not None else get_settings()

        apply_runtime_environment(active_settings)

        configure_logging(active_settings)

        configure_observability(active_settings)

        active_database = None
        active_api_rate_limiter: RedisApiRateLimiter | None = None
        active_redis_auth_limiters: list[RedisLoginRateLimiter] = []
        try:
            repositories = create_repositories(active_settings)
            active_database = repositories.database
            active_auth_repository: AuthRepositoryProtocol = repositories.auth
            active_audit_repository = audit_repository or repositories.audit
            active_credential_repository: ProviderCredentialRepositoryProtocol = (
                repositories.provider_credential
            )
            active_entitlement_repository = (
                entitlement_repository or repositories.entitlement
            )
            active_usage_repository = usage_repository or repositories.usage
            active_quota_repository: QuotaRepositoryProtocol = repositories.quota
            active_todo_repository = repositories.todo
            active_note_repository = repositories.note
            active_memory_repository = repositories.user_memory
            if active_conversation_repository is None:
                active_conversation_repository = repositories.conversation

            active_auth_service = auth_service or AuthService(
                repository=active_auth_repository,
                session_ttl_hours=active_settings.auth_session_ttl_hours,
                touch_interval_seconds=(
                    active_settings.auth_session_touch_interval_seconds
                ),
                registration_mode=active_settings.registration_mode,
            )

            if (
                active_settings.infrastructure_mode == "production"
                and active_settings.redis_url is not None
            ):
                redis_url = active_settings.redis_url.get_secret_value()
                active_api_rate_limiter = RedisApiRateLimiter(
                    redis_url, active_settings.redis_key_prefix
                )
                active_login_rate_limiter = login_rate_limiter or RedisLoginRateLimiter(
                    redis_url,
                    f"{active_settings.redis_key_prefix}:login",
                    active_settings.auth_login_max_failures,
                    active_settings.auth_login_window_seconds,
                )
                active_registration_rate_limiter = (
                    registration_rate_limiter
                    or RedisLoginRateLimiter(
                        redis_url,
                        f"{active_settings.redis_key_prefix}:registration",
                        active_settings.auth_registration_max_failures,
                        active_settings.auth_registration_window_seconds,
                    )
                )
                active_redis_auth_limiters = [
                    limiter
                    for limiter in (
                        active_login_rate_limiter,
                        active_registration_rate_limiter,
                    )
                    if isinstance(limiter, RedisLoginRateLimiter)
                ]
            else:
                active_login_rate_limiter = login_rate_limiter or LoginRateLimiter(
                    max_failures=active_settings.auth_login_max_failures,
                    window_seconds=active_settings.auth_login_window_seconds,
                )
                active_registration_rate_limiter = (
                    registration_rate_limiter
                    or LoginRateLimiter(
                        max_failures=(active_settings.auth_registration_max_failures),
                        window_seconds=(
                            active_settings.auth_registration_window_seconds
                        ),
                    )
                )

            active_auth_repository.delete_expired_sessions(datetime.now(UTC))

            credential_keyring = active_settings.provider_credential_keyring()
            credential_cipher = (
                CredentialCipher(
                    keyring=credential_keyring,
                    active_key_version=(
                        active_settings.provider_credential_active_key_version
                    ),
                )
                if credential_keyring
                else None
            )
            active_credential_service = (
                provider_credential_service
                or ProviderCredentialService(
                    repository=active_credential_repository,
                    cipher=credential_cipher,
                    validator=DeepSeekCredentialValidator(active_settings),
                )
            )
            active_access_policy = access_policy or AccessPolicy(
                settings=active_settings,
                auth_repository=active_auth_repository,
                entitlement_repository=active_entitlement_repository,
                credential_service=active_credential_service,
            )
            active_usage_tracker = UsageTracker(active_usage_repository)
            active_quota_service = quota_service or QuotaService(
                active_quota_repository
            )
            active_model_gateway = DeepSeekModelGateway(
                settings=active_settings,
                credential_service=active_credential_service,
                access_policy=active_access_policy,
                usage_tracker=active_usage_tracker,
                quota_service=active_quota_service,
            )

            active_knowledge_service: Any
            if knowledge_service is not None:
                active_knowledge_service = knowledge_service
            elif active_database is not None:
                active_knowledge_service = ProductionKnowledgeService(
                    active_database, active_settings
                )
            else:
                active_knowledge_service = create_knowledge_base_service(
                    active_settings
                )

            if active_database is not None:
                active_database.ping()
                if active_api_rate_limiter is not None:
                    await active_api_rate_limiter.ping()
                active_knowledge_service.ping()

            # Checkpointer 连接必须覆盖整个应用生命周期。
            with ExitStack() as stack:
                active_checkpointer: BaseCheckpointSaver[Any]
                if active_settings.infrastructure_mode == "production":
                    if active_settings.checkpoint_database_url is None:
                        raise RuntimeError("CHECKPOINT_DATABASE_URL 尚未配置")
                    active_checkpointer = stack.enter_context(
                        open_postgres_checkpointer(
                            active_settings.checkpoint_database_url.get_secret_value()
                        )
                    )
                else:
                    active_checkpointer = stack.enter_context(
                        open_sqlite_checkpointer(
                            active_settings.checkpoint_database_path
                        )
                    )
                graph = build_graph(
                    settings=active_settings,
                    checkpointer=active_checkpointer,
                    knowledge_service=active_knowledge_service,
                    model_gateway=active_model_gateway,
                    todo_repository=active_todo_repository,
                    note_repository=active_note_repository,
                    memory_repository=active_memory_repository,
                )

                application.state.settings = active_settings
                application.state.knowledge_service = active_knowledge_service
                application.state.conversation_repository = (
                    active_conversation_repository
                )
                application.state.checkpointer = active_checkpointer
                application.state.agent_graph = graph
                application.state.graph_lock = (
                    PostgresExecutionLock(
                        active_database,
                        active_settings.thread_lock_wait_seconds,
                    )
                    if active_database is not None
                    else LocalExecutionLock()
                )
                application.state.database = active_database
                application.state.auth_service = active_auth_service
                application.state.auth_repository = active_auth_repository
                application.state.audit_repository = active_audit_repository
                application.state.login_rate_limiter = active_login_rate_limiter
                application.state.registration_rate_limiter = (
                    active_registration_rate_limiter
                )
                application.state.provider_credential_service = (
                    active_credential_service
                )
                application.state.model_gateway = active_model_gateway
                application.state.access_policy = active_access_policy
                application.state.entitlement_repository = active_entitlement_repository
                application.state.usage_repository = active_usage_repository
                application.state.quota_service = active_quota_service
                application.state.api_rate_limiter = active_api_rate_limiter

                yield

        finally:
            if active_api_rate_limiter is not None:
                await active_api_rate_limiter.close()
            for limiter in active_redis_auth_limiters:
                limiter.close()
            if active_database is not None:
                active_database.close()
            shutdown_logging()

    application = FastAPI(
        title="LifePilot Agent API",
        description="基于LangGraph和DeepSeek的个人助理Agent后端服务",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
    )

    application.add_middleware(SlidingWindowRateLimitMiddleware)
    application.add_middleware(RequestContextMiddleware)

    @application.exception_handler(ExecutionBusyError)
    async def execution_busy_handler(
        _request: Any, error: ExecutionBusyError
    ) -> JSONResponse:
        """将跨实例锁超时转换成可重试的冲突响应。"""
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": error.user_message},
            headers={"Retry-After": "1"},
        )

    application.mount(
        "/docs-assets",
        StaticFiles(directory=swagger_ui_path),
        name="swagger-ui-assets",
    )

    @application.get(
        "/docs",
        include_in_schema=False,
    )
    async def custom_swagger_ui() -> HTMLResponse:
        """返回仅使用本地静态资源的 Swagger UI。"""

        return get_swagger_ui_html(
            openapi_url=(application.openapi_url or "/openapi.json"),
            title=(f"{application.title} - Swagger UI"),
            swagger_js_url=("/docs-assets/swagger-ui-bundle.js"),
            swagger_css_url=("/docs-assets/swagger-ui.css"),
            swagger_favicon_url=("/docs-assets/favicon-32x32.png"),
        )

    application.include_router(
        health_router,
        prefix="/api/v1",
        tags=["System"],
    )

    application.include_router(
        auth_router,
        prefix="/api/v1",
        tags=["Authentication"],
    )

    application.include_router(
        admin_router,
        prefix="/api/v1",
        tags=["Administration"],
    )

    protected_dependencies = [Depends(require_current_user)]

    application.include_router(
        chat_router,
        prefix="/api/v1",
        tags=["LifePilot"],
        dependencies=protected_dependencies,
    )

    application.include_router(
        knowledge_router,
        prefix="/api/v1",
        tags=["Knowledge Base"],
        dependencies=protected_dependencies,
    )

    application.include_router(
        conversation_router,
        prefix="/api/v1",
        tags=["Conversations"],
        dependencies=protected_dependencies,
    )

    application.include_router(
        model_router,
        prefix="/api/v1",
        tags=["Model Access"],
        dependencies=protected_dependencies,
    )

    application.include_router(
        usage_router,
        prefix="/api/v1",
        tags=["Usage"],
        dependencies=protected_dependencies,
    )

    return application


app = create_app()
