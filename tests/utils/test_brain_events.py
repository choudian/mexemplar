"""Brain blinker event contract tests"""

import pytest

from src.utils import events


@pytest.fixture(autouse=True)
def clean_events():
    events.clear_all()
    yield
    events.clear_all()


class TestBrainEventsExist:
    """Verify all brain blinker signals are defined"""

    def test_brain_zone_changed_exists(self):
        assert events.brain_zone_changed is not None
        assert events.brain_zone_changed.name == "brain_zone_changed"

    def test_brain_specialist_changed_exists(self):
        assert events.brain_specialist_changed is not None
        assert events.brain_specialist_changed.name == "brain_specialist_changed"

    def test_segment_boundary_triggered_exists(self):
        assert events.segment_boundary_triggered is not None
        assert events.segment_boundary_triggered.name == "segment_boundary_triggered"

    def test_segment_idle_trigger_exists(self):
        assert events.segment_idle_trigger is not None
        assert events.segment_idle_trigger.name == "segment_idle_trigger"

    def test_brain_specialist_recruited_exists(self):
        assert events.brain_specialist_recruited is not None
        assert events.brain_specialist_recruited.name == "brain_specialist_recruited"

    def test_brain_context_ready_exists(self):
        assert events.brain_context_ready is not None
        assert events.brain_context_ready.name == "brain_context_ready"


class TestBrainEventEmit:
    """Verify brain events can be emitted and received"""

    def test_brain_zone_changed_receives_payload(self):
        received = []
        events.connect("brain_zone_changed", lambda sender, **kw: received.append(kw), weak=False)
        events.emit(
            "brain_zone_changed",
            zone="hot",
            entry_id="entry-1",
            change_type="created",
        )
        assert len(received) == 1
        assert received[0]["zone"] == "hot"
        assert received[0]["entry_id"] == "entry-1"

    def test_segment_boundary_triggered_receives_payload(self):
        received = []
        events.connect("segment_boundary_triggered", lambda sender, **kw: received.append(kw), weak=False)
        events.emit(
            "segment_boundary_triggered",
            session_id="sess-1",
            segment_id="seg-1",
            reason="idle",
        )
        assert len(received) == 1
        assert received[0]["session_id"] == "sess-1"
        assert received[0]["reason"] == "idle"

    def test_brain_context_ready_receives_payload(self):
        received = []
        events.connect("brain_context_ready", lambda sender, **kw: received.append(kw), weak=False)
        events.emit("brain_context_ready", session_id="sess-1")
        assert len(received) == 1
        assert received[0]["session_id"] == "sess-1"

    def test_brain_specialist_recruited_receives_payload(self):
        received = []
        events.connect("brain_specialist_recruited", lambda sender, **kw: received.append(kw), weak=False)
        events.emit(
            "brain_specialist_recruited",
            specialist_id="spec-1",
            name="Data Analyst",
            reason="Pattern detected",
        )
        assert len(received) == 1
        assert received[0]["name"] == "Data Analyst"

    def test_brain_event_names_in_signal_names_list(self):
        brain_names = [n for n in events._signal_names if n.startswith("brain_") or n.startswith("segment_")]
        assert "brain_zone_changed" in brain_names
        assert "brain_specialist_changed" in brain_names
        assert "segment_boundary_triggered" in brain_names
        assert "segment_idle_trigger" in brain_names
        assert "brain_specialist_recruited" in brain_names
        assert "brain_context_ready" in brain_names
