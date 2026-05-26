from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_real_grand_tour_summary_reports_stay_under_ignored_test_results() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "frontend/test-results/" in gitignore

    helper = (ROOT / "frontend/tests/e2e/helpers/real-grand-tour-report.ts").read_text(
        encoding="utf-8"
    )
    assert "assertSanitizedArtifact" in helper
    assert "data:(?:image|audio|video)" in helper
    assert "MEXEMPLAR_DESKTOP_TOKEN" in helper


def test_real_grand_tour_playwright_artifacts_are_off_by_default() -> None:
    config = (ROOT / "frontend/playwright.real-grand-tour.config.ts").read_text(
        encoding="utf-8"
    )

    assert 'trace: "off"' in config
    assert 'video: "off"' in config
    assert 'screenshot: "off"' in config


def test_real_grand_tour_sidecar_token_is_not_passed_in_process_arguments() -> None:
    runtime = (ROOT / "frontend/tests/e2e/helpers/real-grand-tour-runtime.ts").read_text(
        encoding="utf-8"
    )

    assert '"--token", token' not in runtime
    assert "MEXEMPLAR_DESKTOP_TOKEN: token" in runtime


def test_default_playwright_config_excludes_real_grand_tour() -> None:
    config = (ROOT / "frontend/playwright.config.ts").read_text(encoding="utf-8")

    assert 'testIgnore: ["grand-tour.real.spec.ts"]' in config
