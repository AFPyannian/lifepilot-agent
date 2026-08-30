"""提供当前用户的模型访问和凭据管理接口。"""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.audit import record_audit_event
from app.api.schemas import (
    ModelAccessResponse,
    ProviderCredentialResponse,
    ProviderCredentialUpsertRequest,
)
from app.api.security import CurrentUser
from app.credentials.errors import CredentialValidationError
from app.credentials.models import ProviderCredentialMetadata
from app.credentials.service import ProviderCredentialService

router = APIRouter()


def _get_service(request: Request) -> ProviderCredentialService:
    service = getattr(request.app.state, "provider_credential_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="模型凭据服务不可用。",
        )

    return service


def _to_response(
    metadata: ProviderCredentialMetadata,
) -> ProviderCredentialResponse:
    return ProviderCredentialResponse(
        provider=metadata.provider,
        masked_key=f"••••{metadata.masked_suffix}",
        status=metadata.status,
        validated_at=metadata.validated_at,
        last_used_at=metadata.last_used_at,
        created_at=metadata.created_at,
        revoked_at=metadata.revoked_at,
    )


@router.get("/model/access", response_model=ModelAccessResponse)
def get_model_access(
    request: Request,
    current_user: CurrentUser,
) -> ModelAccessResponse:
    """返回当前账号可选择的模型模式，不返回任何 Secret。"""
    settings = request.app.state.settings
    metadata = _get_service(request).get_metadata(user_id=current_user.user_id)

    return ModelAccessResponse(
        byok_enabled=settings.byok_enabled,
        byok_configured=metadata is not None and metadata.status == "active",
        byok_status=None if metadata is None else metadata.status,
        platform_enabled=settings.platform_model_enabled,
        default_mode=settings.default_model_mode,
    )


@router.get(
    "/model/credentials/deepseek",
    response_model=ProviderCredentialResponse,
)
def get_deepseek_credential(
    request: Request,
    current_user: CurrentUser,
) -> ProviderCredentialResponse:
    """读取当前用户的掩码凭据元数据。"""
    metadata = _get_service(request).get_metadata(user_id=current_user.user_id)

    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="当前账号尚未配置 DeepSeek API Key。",
        )

    return _to_response(metadata)


@router.put(
    "/model/credentials/deepseek",
    response_model=ProviderCredentialResponse,
)
def save_deepseek_credential(
    payload: ProviderCredentialUpsertRequest,
    request: Request,
    current_user: CurrentUser,
) -> ProviderCredentialResponse:
    """受控验证并创建或轮换当前用户的 DeepSeek Key。"""
    settings = request.app.state.settings

    if not settings.byok_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前实例未开放用户自带模型 Key。",
        )

    service = _get_service(request)
    existing = service.get_metadata(user_id=current_user.user_id)

    try:
        metadata = service.save_or_rotate(
            user_id=current_user.user_id,
            api_key=payload.api_key,
        )
    except CredentialValidationError as error:
        record_audit_event(
            request,
            user_id=current_user.user_id,
            action="credential.validate",
            resource_type="model_credential",
            resource_id="deepseek",
            outcome="denied",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error.user_message,
        ) from None

    record_audit_event(
        request,
        user_id=current_user.user_id,
        action="credential.rotate" if existing is not None else "credential.create",
        resource_type="model_credential",
        resource_id="deepseek",
        outcome="success",
    )
    return _to_response(metadata)


@router.post(
    "/model/credentials/deepseek/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_deepseek_credential(
    request: Request,
    current_user: CurrentUser,
) -> Response:
    """撤销当前用户凭据并销毁可恢复的密文。"""
    _get_service(request).revoke(user_id=current_user.user_id)
    record_audit_event(
        request,
        user_id=current_user.user_id,
        action="credential.revoke",
        resource_type="model_credential",
        resource_id="deepseek",
        outcome="success",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/model/credentials/deepseek",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_deepseek_credential(
    request: Request,
    current_user: CurrentUser,
) -> Response:
    """物理删除当前用户的凭据记录。"""
    _get_service(request).delete(user_id=current_user.user_id)
    record_audit_event(
        request,
        user_id=current_user.user_id,
        action="credential.delete",
        resource_type="model_credential",
        resource_id="deepseek",
        outcome="success",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
