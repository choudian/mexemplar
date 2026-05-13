from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read_tree(root: Path, suffixes: tuple[str, ...]) -> list[tuple[Path, str]]:
    if not root.exists():
        return []
    return [
        (path, path.read_text(encoding="utf-8"))
        for path in root.rglob("*")
        if path.is_file() and path.suffix in suffixes
    ]


def test_frontend_does_not_import_storage_or_python_internals() -> None:
    forbidden = [
        "sqlite",
        "duckdb",
        "keyring",
        "src/data",
        "src.data",
        "Repository",
    ]

    for path, content in _read_tree(ROOT / "frontend" / "src", (".ts", ".tsx")):
        for token in forbidden:
            assert token not in content, f"{path} must not reference {token}"


def test_desktop_api_does_not_import_repositories_or_storage_engines() -> None:
    forbidden = [
        "src.data.repositories",
        "src.data.repos",
        "src.data.recording_repository",
        "sqlite3",
        "duckdb",
        "keyring",
    ]

    for path, content in _read_tree(ROOT / "src" / "desktop_api", (".py",)):
        for token in forbidden:
            assert token not in content, f"{path} must not reference {token}"
