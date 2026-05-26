from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_read_only_resolver_is_the_only_real_tour_keyring_path() -> None:
    resolver = (ROOT / "src/data/credential_resolver.py").read_text(encoding="utf-8")

    assert "get_password" in resolver
    assert "credential_mutation_forbidden" in resolver
    assert "keyring.set_password" not in resolver
    assert "keyring.delete_password" not in resolver


def test_real_tour_specs_do_not_write_settings_secrets() -> None:
    real_specs = list((ROOT / "frontend/tests/e2e").glob("grand-tour.real.spec.ts"))
    assert real_specs, "real Grand Tour spec must exist"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in real_specs)

    assert "/api/settings/secrets/" not in combined
    assert "save_secret" not in combined.lower()
    assert "delete_secret" not in combined.lower()
