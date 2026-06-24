from __future__ import annotations

from src.utils.ids import new_id


def test_new_id_is_50_hex_chars():
    value = new_id()
    assert len(value) == 50
    int(value, 16)  # 合法 hex


def test_new_id_length_is_stable_across_calls():
    # 双 UUID 拼接截取 50：每次都是 50，而非单 UUID 的 32
    lengths = {len(new_id()) for _ in range(100)}
    assert lengths == {50}


def test_new_id_is_unique_across_many_calls():
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000
