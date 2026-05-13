from fastapi import APIRouter

from src.business.services.desktop_bootstrap_service import DesktopBootstrapService
from src.business.services.desktop_health_service import DesktopHealthService
from src.desktop_api.events import event_queue
from src.desktop_api.schemas import (
    BackendConnectionState,
    BootstrapNavigation,
    BootstrapResponse,
    BootstrapSettingsSummary,
    BootstrapUser,
)

router = APIRouter(prefix="/api", tags=["health"])


def _connection_state(
    extra_checks: list | None = None,
) -> BackendConnectionState:
    return BackendConnectionState(
        **DesktopHealthService().get_connection_state(
            event_stream_available=event_queue.is_healthy(),
            extra_checks=extra_checks,
        )
    )


@router.get("/health", response_model=BackendConnectionState)
def get_health() -> BackendConnectionState:
    return _connection_state()


@router.get("/bootstrap", response_model=BootstrapResponse)
def get_bootstrap() -> BootstrapResponse:
    service = DesktopBootstrapService()
    data = service.run()
    return BootstrapResponse(
        connection=_connection_state(service.health_checks()),
        user=BootstrapUser(**data["user"]),
        navigation=BootstrapNavigation(**data["navigation"]),
        settingsSummary=BootstrapSettingsSummary(**data["settingsSummary"]),
    )
