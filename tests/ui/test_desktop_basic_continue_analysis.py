from src.recording.desktop_recorder import DesktopRecorderHealth


def test_desktop_basic_continue_analysis_uses_health_stats_shape():
    stats = DesktopRecorderHealth.from_value({"action_type_counts": {"typing": 2}, "frame_total": 3})

    assert stats.action_type_counts == {"typing": 2}
    assert stats.action_total == 2
    assert stats.frame_total == 3
