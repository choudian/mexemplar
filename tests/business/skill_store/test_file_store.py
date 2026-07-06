"""file_store 边界与原子性测试（029 T006 / CC-174）。"""

from __future__ import annotations

import pytest

from src.business.skill_store import file_store
from src.business.skill_store.file_store import (
    MAX_FILE_COUNT,
    SkillFile,
    SkillFileStoreError,
    remove_install_dir,
    write_install_dir,
)


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path))
    yield


def test_write_and_read_back(tmp_path):
    files = [
        SkillFile(path="SKILL.md", content="---\nname: t\n---\nbody"),
        SkillFile(path="references/notes.md", content="notes"),
    ]
    final_dir = write_install_dir("esi_test1", files)
    assert final_dir.exists()
    assert (final_dir / "SKILL.md").read_text(encoding="utf-8").endswith("body")
    assert (final_dir / "references" / "notes.md").read_text(encoding="utf-8") == "notes"
    # 无临时目录残留
    assert not any(p.name.startswith(".tmp_") for p in final_dir.parent.iterdir())


@pytest.mark.parametrize(
    "bad_path",
    ["../escape.md", "/abs/path.md", "C:evil.md", "a/../../b.md", ""],
)
def test_path_traversal_rejected_with_zero_residue(tmp_path, bad_path):
    files = [SkillFile(path="SKILL.md", content="x"), SkillFile(path=bad_path, content="y")]
    with pytest.raises(SkillFileStoreError):
        write_install_dir("esi_bad", files)
    root = file_store.external_skills_root()
    assert not (root / "esi_bad").exists()
    assert not any(p.name.startswith(".tmp_") for p in root.iterdir())


def test_single_file_size_limit(tmp_path):
    oversized = "x" * (file_store.MAX_FILE_BYTES + 1)
    with pytest.raises(SkillFileStoreError):
        write_install_dir("esi_big", [SkillFile(path="SKILL.md", content=oversized)])


def test_total_size_limit(tmp_path):
    chunk = "x" * (file_store.MAX_FILE_BYTES - 1)
    files = [SkillFile(path=f"f{i}.md", content=chunk) for i in range(6)]
    with pytest.raises(SkillFileStoreError):
        write_install_dir("esi_total", files)


def test_file_count_limit(tmp_path):
    files = [SkillFile(path=f"f{i}.md", content="x") for i in range(MAX_FILE_COUNT + 1)]
    with pytest.raises(SkillFileStoreError):
        write_install_dir("esi_count", files)


def test_duplicate_install_dir_rejected(tmp_path):
    files = [SkillFile(path="SKILL.md", content="x")]
    write_install_dir("esi_dup", files)
    with pytest.raises(SkillFileStoreError):
        write_install_dir("esi_dup", files)


def test_remove_install_dir(tmp_path):
    files = [SkillFile(path="SKILL.md", content="x")]
    final_dir = write_install_dir("esi_rm", files)
    assert final_dir.exists()
    remove_install_dir("esi_rm")
    assert not final_dir.exists()


def test_remove_install_dir_rejects_traversal(tmp_path):
    with pytest.raises(SkillFileStoreError):
        remove_install_dir("../outside")
