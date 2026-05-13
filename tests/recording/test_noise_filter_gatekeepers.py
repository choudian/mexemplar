from pathlib import Path


def _python_files() -> list[Path]:
    return [
        path
        for root in ("src", "tests")
        for path in Path(root).rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _matches_import(text: str, package_name: str) -> bool:
    return f"import {package_name}" in text or f"from {package_name}" in text


def test_sqlglot_imports_are_limited_to_filtering_package():
    offenders = []

    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if not _matches_import(text, "sqlglot"):
            continue
        normalized = path.as_posix()
        if normalized.startswith("src/recording/filtering/"):
            continue
        if normalized.startswith("tests/recording/filtering/"):
            continue
        offenders.append(normalized)

    assert offenders == []


def test_tldextract_imports_are_limited_to_filtering_package():
    offenders = []

    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if not _matches_import(text, "tldextract"):
            continue
        normalized = path.as_posix()
        if normalized.startswith("src/recording/filtering/"):
            continue
        if normalized.startswith("tests/recording/filtering/"):
            continue
        offenders.append(normalized)

    assert offenders == []


def test_persister_and_recovery_both_wire_shared_filter_hook():
    persister_source = Path("src/recording/browser/duckdb_recording_persister.py").read_text(
        encoding="utf-8"
    )
    recovery_source = Path("src/data/recording_recovery.py").read_text(encoding="utf-8")

    assert "persist_filtered_network_requests" in persister_source
    assert "persist_filtered_network_requests" in recovery_source
