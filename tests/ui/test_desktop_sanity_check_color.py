from src.recording.desktop_recorder import DesktopRecorderHealth
from src.ui.widgets.desktop_sanity_check_dialog import determine_health_color


def test_desktop_sanity_check_color_rules():
    assert determine_health_color(DesktopRecorderHealth(), enable_clip=True) == "red"
    assert (
        determine_health_color(
            DesktopRecorderHealth(action_type_counts={"typing": 1}, uia_total=10, uia_hit=4),
            enable_clip=True,
        )
        == "yellow"
    )
    assert (
        determine_health_color(
            DesktopRecorderHealth(action_type_counts={"typing": 1}, clip_total=10, clip_success=7),
            enable_clip=True,
        )
        == "yellow"
    )
    assert (
        determine_health_color(
            DesktopRecorderHealth(action_type_counts={"typing": 1}, clip_total=10, clip_success=7),
            enable_clip=False,
        )
        == "green"
    )
