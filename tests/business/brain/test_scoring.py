from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.business.brain.scoring import compute_recency_score


class TestComputeRecencyScore:
    def test_none_input_returns_half(self):
        assert compute_recency_score(None, half_life_days=7) == 0.5

    def test_empty_string_returns_half(self):
        assert compute_recency_score("", half_life_days=7) == 0.5

    def test_invalid_iso_string_returns_half(self):
        assert compute_recency_score("not-a-date", half_life_days=7) == 0.5

    def test_zero_age_returns_one(self):
        now = datetime.now(timezone.utc).isoformat()
        score = compute_recency_score(now, half_life_days=7)
        assert score == pytest.approx(1.0, abs=1e-4)

    def test_half_life_returns_half(self):
        past = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        score = compute_recency_score(past, half_life_days=7)
        assert score == pytest.approx(0.5, abs=1e-3)

    def test_two_half_lives_returns_quarter(self):
        past = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        score = compute_recency_score(past, half_life_days=7)
        assert score == pytest.approx(0.25, abs=1e-3)

    def test_exponential_decay_formula(self):
        age_days = 30.0
        half_life = 14.0
        past = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
        score = compute_recency_score(past, half_life_days=half_life)
        expected = math.exp(-math.log(2) * age_days / half_life)
        assert score == pytest.approx(expected, abs=1e-3)

    def test_score_between_zero_and_one(self):
        past = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        score = compute_recency_score(past, half_life_days=7)
        assert 0.0 <= score <= 1.0

    def test_future_timestamp_returns_one(self):
        # 未来时间 age_days 被 max(..., 0) 钳制为 0，返回 1
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        score = compute_recency_score(future, half_life_days=7)
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_naive_datetime_treated_as_utc(self):
        # 不带时区的 ISO 字符串应被当作 UTC 处理
        naive_now = datetime.utcnow().isoformat()
        score = compute_recency_score(naive_now, half_life_days=7)
        assert score == pytest.approx(1.0, abs=1e-3)

    def test_z_suffix_handled(self):
        # 带 Z 后缀的 ISO 字符串应正确解析
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        score = compute_recency_score(ts, half_life_days=7)
        assert score == pytest.approx(1.0, abs=1e-3)

    def test_different_half_life_scales(self):
        # 相同时间戳，较短半衰期应产生更低分数
        past = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        score_short = compute_recency_score(past, half_life_days=3)
        score_long = compute_recency_score(past, half_life_days=30)
        assert score_short < score_long

    def test_non_string_numeric_input_returns_half(self):
        assert compute_recency_score(12345, half_life_days=7) == 0.5
