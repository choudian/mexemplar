from src.business.services.desktop_recording_service import DesktopRecordingService
from src.recording.browser_recorder import RecordingMode
from src.ui.mixins.recording_mixin import RecordingMixin


class _Repo:
    pass


class _Logger:
    def info(self, *args, **kwargs):
        pass


class _RecordingHost(RecordingMixin):
    def __init__(self):
        self.logger = _Logger()
        self.desktop_started = False

    def _start_desktop_recording(self):
        self.desktop_started = True


def test_desktop_service_exposes_start_after_minimize_entrypoint():
    service = DesktopRecordingService(repository=_Repo())

    assert callable(service.start_after_minimize)
    assert callable(service.stop)


def test_recording_mixin_routes_desktop_mode_to_desktop_service_path():
    host = _RecordingHost()

    host._on_recording_started(RecordingMode.DESKTOP, "")

    assert host.desktop_started is True
