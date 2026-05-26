from __future__ import annotations

import json
import sys

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


def test_real_tour_keyring_mutation_guard_records_and_rejects(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data import real_tour_audit

    class FakeKeyring:
        def set_password(self, *_args):
            raise AssertionError("original set_password should be patched")

        def delete_password(self, *_args):
            raise AssertionError("original delete_password should be patched")

    fake_keyring = FakeKeyring()
    audit_file = tmp_path / "audit.json"
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE", str(audit_file))
    monkeypatch.setattr(real_tour_audit, "_KEYRING_GUARD_INSTALLED", False)
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    real_tour_audit.install_keyring_mutation_guard()

    with pytest.raises(real_tour_audit.RealTourCredentialMutationError):
        fake_keyring.set_password("svc", "user", "secret")
    with pytest.raises(real_tour_audit.RealTourCredentialMutationError):
        fake_keyring.delete_password("svc", "user")

    state = json.loads(audit_file.read_text(encoding="utf-8"))
    assert state["credentialMutationCount"] == 2


def test_real_tour_missing_keyring_guard_fails_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data import real_tour_audit

    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE", str(tmp_path / "audit.json"))
    monkeypatch.setattr(real_tour_audit, "_KEYRING_GUARD_INSTALLED", False)
    monkeypatch.setitem(sys.modules, "keyring", None)

    with pytest.raises(
        real_tour_audit.RealTourCredentialMutationError,
        match="credential_mutation_guard_unavailable",
    ):
        real_tour_audit.install_keyring_mutation_guard()


def test_existing_corrupt_audit_fails_closed_without_replacing_evidence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data import real_tour_audit

    audit_file = tmp_path / "audit.json"
    audit_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE", str(audit_file))

    with pytest.raises(real_tour_audit.RealTourAuditIntegrityError, match="real_tour_audit_invalid"):
        real_tour_audit.record_paid_call("unit")

    assert audit_file.read_text(encoding="utf-8") == "{not valid json"


def test_audit_write_rejects_counter_regression(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data import real_tour_audit

    audit_file = tmp_path / "audit.json"
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE", str(audit_file))
    audit_file.write_text(
        json.dumps(
            {
                "paidCallCount": 3,
                "credentialMutationCount": 2,
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
                "credentialMutationCount": 2,
                "budgetExceeded": False,
                "elapsedMs": 20,
            }
        )

    assert json.loads(audit_file.read_text(encoding="utf-8"))["paidCallCount"] == 3
