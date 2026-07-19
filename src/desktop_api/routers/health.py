from collections.abc import Sequence

from fastapi import APIRouter, Request

from src.business.services.desktop_bootstrap_service import DesktopBootstrapService
from src.business.services.desktop_health_service import DesktopHealthCheck, DesktopHealthService
from src.desktop_api.events import event_queue
from src.desktop_api.schemas import (
    BackendConnectionState,
    BootstrapBrainConfig,
    BootstrapNavigation,
    BootstrapResponse,
    BootstrapSettingsSummary,
    BootstrapUser,
)

router = APIRouter(prefix="/api", tags=["health"])


def _connection_state(
    request: Request,
    extra_checks: Sequence[DesktopHealthCheck] | None = None,
) -> BackendConnectionState:
    scheduling_check = getattr(
        request.app.state,
        "scheduling_health_check",
        DesktopHealthCheck(
            name="scheduling",
            status="degraded",
            message="Scheduling runtime health is not initialized.",
            critical=False,
        ),
    )
    checks = [scheduling_check, *(extra_checks or [])]
    return BackendConnectionState(
        **DesktopHealthService().get_connection_state(
            event_stream_available=event_queue.is_healthy(),
            extra_checks=checks,
        )
    )


@router.get("/health", response_model=BackendConnectionState)
def get_health(request: Request) -> BackendConnectionState:
    return _connection_state(request)


@router.get("/bootstrap", response_model=BootstrapResponse)
def get_bootstrap(request: Request) -> BootstrapResponse:
    service = DesktopBootstrapService()
    data = service.run()
    return BootstrapResponse(
        connection=_connection_state(request, service.health_checks()),
        user=BootstrapUser(**data["user"]),
        navigation=BootstrapNavigation(**data["navigation"]),
        settingsSummary=BootstrapSettingsSummary(**data["settingsSummary"]),
        brain=BootstrapBrainConfig(**data["brain"]),
    )
