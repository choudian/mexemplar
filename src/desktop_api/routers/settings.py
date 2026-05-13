from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.business.services.settings_actions_service import SettingsActionsService
from src.business.services.settings_service import SettingsService, SettingsValidationError
from src.desktop_api.schemas import (
    SettingsActionResponse,
    SettingsActionRequest,
    SettingsSchemaResponse,
    SettingsSecretResponse,
    SettingsSecretWriteRequest,
    SettingsValuesResponse,
    SettingsValuesUpdateRequest,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def get_settings_service() -> SettingsService:
    return SettingsService()


def get_settings_actions_service() -> SettingsActionsService:
    return SettingsActionsService()


@router.get("/schema", response_model=SettingsSchemaResponse)
def get_settings_schema(service: SettingsService = Depends(get_settings_service)) -> dict:
    return service.get_schema()


@router.get("/values", response_model=SettingsValuesResponse)
def get_settings_values(service: SettingsService = Depends(get_settings_service)) -> dict:
    return service.get_values()


@router.get("", response_model=SettingsValuesResponse)
def get_settings_root(service: SettingsService = Depends(get_settings_service)) -> dict:
    return service.get_values()


@router.patch("/values", response_model=SettingsValuesResponse)
def update_settings_values(
    request: SettingsValuesUpdateRequest,
    service: SettingsService = Depends(get_settings_service),
) -> dict:
    try:
        return service.update_values(request.values)
    except SettingsValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "settings_validation_error", "key": exc.key, "message": exc.message},
        ) from exc


@router.post("/secrets/{secret_key:path}", response_model=SettingsSecretResponse)
def write_secret(
    secret_key: str,
    request: SettingsSecretWriteRequest,
    service: SettingsService = Depends(get_settings_service),
) -> dict:
    try:
        return service.write_secret(secret_key, request.value)
    except SettingsValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "settings_validation_error", "key": exc.key, "message": exc.message},
        ) from exc


@router.delete("/secrets/{secret_key:path}", response_model=SettingsSecretResponse)
def delete_secret(
    secret_key: str,
    service: SettingsService = Depends(get_settings_service),
) -> dict:
    try:
        return service.delete_secret(secret_key)
    except SettingsValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "settings_validation_error", "key": exc.key, "message": exc.message},
        ) from exc


@router.post("/actions/{action_name}", response_model=SettingsActionResponse)
def run_settings_action(
    action_name: str,
    request: SettingsActionRequest | None = None,
    service: SettingsActionsService = Depends(get_settings_actions_service),
) -> dict:
    return service.run_action(action_name, confirmed=bool(request and request.confirmed))
