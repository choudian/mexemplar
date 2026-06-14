from __future__ import annotations

import json

import pytest


def test_real_tour_paid_call_budget_is_recorded_and_enforced(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data import real_tour_audit

    audit_file = tmp_path / "audit.json"
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE", str(audit_file))
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_MAX_PAID_CALLS", "1")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_MAX_MINUTES", "20")

    real_tour_audit.record_paid_call("unit")
    with pytest.raises(real_tour_audit.RealTourBudgetExceeded):
        real_tour_audit.record_paid_call("unit")

    state = json.loads(audit_file.read_text(encoding="utf-8"))
    assert state["paidCallCount"] == 1
    assert state["budgetExceeded"] is True
    assert state["lastBudgetReason"] == "paid_call_count"


def test_existing_corrupt_audit_fails_closed_without_replacing_evidence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data import real_tour_audit

    audit_file = tmp_path / "audit.json"
    audit_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE", str(audit_file))

    with pytest.raises(
        real_tour_audit.RealTourAuditIntegrityError, match="real_tour_audit_invalid"
    ):
        real_tour_audit.record_paid_call("unit")

    assert audit_file.read_text(encoding="utf-8") == "{not valid json"


def test_audit_write_rejects_counter_regression(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.data import real_tour_audit

    audit_file = tmp_path / "audit.json"
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE", str(audit_file))
    audit_file.write_text(
        json.dumps(
            {
                "paidCallCount": 3,
                "budgetExceeded": False,
                "elapsedMs": 10,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        real_tour_audit.RealTourAuditIntegrityError,
        match="real_tour_audit_counter_regression",
    ):
        real_tour_audit._write_state_unlocked(
            {
                "paidCallCount": 2,
                "budgetExceeded": False,
                "elapsedMs": 20,
            }
        )

    assert json.loads(audit_file.read_text(encoding="utf-8"))["paidCallCount"] == 3
