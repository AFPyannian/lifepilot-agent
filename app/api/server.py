"""创建并配置 LifePilot FastAPI 应用。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
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
from app.checkpointing import open_sqlite_checkpointer
from app.config import Settings, apply_runtime_environment, get_settings
from app.credentials.crypto import CredentialCipher
from app.credentials.service import ProviderCredentialService
from app.graph import build_graph
from app.knowledge import KnowledgeBaseService, create_knowledge_base_service
from app.logging_config import configure_logging, shutdown_logging
from app.model import DeepSeekCredentialValidator
from app.model_gateway import DeepSeekModelGateway
from app.observability import configure_observability
from app.repositories.audit_repository import AuditRepository
from app.repositories.auth_repository import AuthRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.entitlement_repository import EntitlementRepository
from app.repositories.provider_credential_repository import (
    ProviderCredentialRepository,
)
from app.repositories.usage_repository import UsageRepository
from app.usage.service import UsageTracker


def create_app(
    agent_graph: Any | None = None,
    knowledge_service: KnowledgeBaseService | None = None,
    settings: Settings | None = None,
    conversation_repository: ConversationRepository | None = None,
    auth_service: AuthService | None = None,
    audit_repository: AuditRepository | None = None,
    login_rate_limiter: LoginRateLimiter | None = None,
    registration_rate_limiter: LoginRateLimiter | None = None,
    provider_credential_service: ProviderCredentialService | None = None,
    access_policy: AccessPolicyProtocol | None = None,
    entitlement_repository: EntitlementRepository | None = None,
    usage_repository: UsageRepository | None = None,
) -> FastAPI:
    """创建可注入测试依赖的 FastAPI 应用。"""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """初始化生产依赖，并在应用退出时释放资源。"""
        active_conversation_repository = conversation_repository

        if agent_graph is not None:
            application.state.agent_graph = agent_graph
            application.state.graph_lock = Lock()
            application.state.settings = settings
            application.state.knowledge_service = knowledge_service
            application.state.conversation_repository = active_conversation_repository
            application.state.auth_service = auth_service
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

            application.state.checkpointer = getattr(agent_graph, "checkpointer", None)

            yield
            return

        active_settings = settings if settings is not None else get_settings()

        apply_runtime_environment(active_settings)

        configure_logging(active_settings)

        configure_observability(active_settings)

        try:
            active_auth_repository = AuthRepository(active_settings.app_database_path)

            active_auth_service = auth_service or AuthService(
                repository=active_auth_repository,
                session_ttl_hours=active_settings.auth_session_ttl_hours,
                touch_interval_seconds=(
                    active_settings.auth_session_touch_interval_seconds
                ),
                registration_mode=active_settings.registration_mode,
            )

            active_audit_repository = audit_repository or AuditRepository(
                active_settings.app_database_path
            )

            active_login_rate_limiter = login_rate_limiter or LoginRateLimiter(
                max_failures=active_settings.auth_login_max_failures,
                window_seconds=active_settings.auth_login_window_seconds,
            )

            active_registration_rate_limiter = (
                registration_rate_limiter
                or LoginRateLimiter(
                    max_failures=(active_settings.auth_registration_max_failures),
                    window_seconds=(active_settings.auth_registration_window_seconds),
                )
            )

            active_auth_repository.delete_expired_sessions(datetime.now(UTC))

            active_credential_repository = ProviderCredentialRepository(
                active_settings.app_database_path
            )
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
            active_entitlement_repository = (
                entitlement_repository
                or EntitlementRepository(active_settings.app_database_path)
            )
            active_usage_repository = usage_repository or UsageRepository(
                active_settings.app_database_path
            )
            active_access_policy = access_policy or AccessPolicy(
                settings=active_settings,
                auth_repository=active_auth_repository,
                entitlement_repository=active_entitlement_repository,
                credential_service=active_credential_service,
            )
            active_usage_tracker = UsageTracker(active_usage_repository)
            active_model_gateway = DeepSeekModelGateway(
                settings=active_settings,
                credential_service=active_credential_service,
                access_policy=active_access_policy,
                usage_tracker=active_usage_tracker,
            )

            if active_conversation_repository is None:
                active_conversation_repository = ConversationRepository(
                    active_settings.app_database_path
                )

            active_knowledge_service = (
                knowledge_service or create_knowledge_base_service(active_settings)
            )

            # Checkpointer 连接必须覆盖整个应用生命周期。
            with open_sqlite_checkpointer(
                active_settings.checkpoint_database_path
            ) as active_checkpointer:
                graph = build_graph(
                    settings=active_settings,
                    checkpointer=active_checkpointer,
                    knowledge_service=active_knowledge_service,
                    model_gateway=active_model_gateway,
                )

                application.state.settings = active_settings
                application.state.knowledge_service = active_knowledge_service
                application.state.conversation_repository = (
                    active_conversation_repository
                )
                application.state.checkpointer = active_checkpointer
                application.state.agent_graph = graph
                application.state.graph_lock = Lock()
                application.state.auth_service = active_auth_service
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

                yield

        finally:
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
