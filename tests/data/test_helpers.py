from __future__ import annotations

import pytest

from src.data.helpers import build_like_pattern


def test_build_like_pattern_contains_wraps_with_percent():
    assert build_like_pattern("foo") == "%foo%"


def test_build_like_pattern_prefix_no_leading_percent():
    assert build_like_pattern("foo", contains=False) == "foo%"


def test_build_like_pattern_escapes_percent():
    assert build_like_pattern(r"a%b") == r"%a\%b%"


def test_build_like_pattern_escapes_underscore():
    assert build_like_pattern("a_b") == r"%a\_b%"


def test_build_like_pattern_escapes_backslash():
    # 反斜杠必须先转义，否则会错误转义后续 %/_（tool/skill_composition 的 latent bug）
    assert build_like_pattern(r"a\b") == r"%a\\b%"


def test_build_like_pattern_escapes_all_metachars_combined():
    assert build_like_pattern(r"a\b%c_d") == r"%a\\b\%c\_d%"


def test_build_like_pattern_strips_whitespace():
    assert build_like_pattern("  foo  ") == "%foo%"


def test_build_like_pattern_rejects_empty():
    with pytest.raises(ValueError):
        build_like_pattern("")


def test_build_like_pattern_rejects_whitespace_only():
    with pytest.raises(ValueError):
        build_like_pattern("   ")
