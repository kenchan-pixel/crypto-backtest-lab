from __future__ import annotations

import pandas as pd

from forward_paper.taker_semantic_contract import score


def test_score_same_timestamp_base_ratio_is_exact():
    idx = pd.to_datetime(["2026-09-21T00:00:00Z", "2026-09-21T00:05:00Z"])
    metrics = pd.DataFrame({"metric": [1.25, 0.75]}, index=idx)
    klines = pd.DataFrame({"base_ratio": [1.25, 0.75]}, index=idx)
    got = score(metrics, klines, "base_ratio", 0)
    assert got["rows"] == 2
    assert got["max_abs_delta"] == 0.0


def test_score_offset_moves_kline_timestamp():
    m_idx = pd.to_datetime(["2026-09-21T00:05:00Z"])
    k_idx = pd.to_datetime(["2026-09-21T00:00:00Z"])
    metrics = pd.DataFrame({"metric": [1.2]}, index=m_idx)
    klines = pd.DataFrame({"base_ratio": [1.2]}, index=k_idx)
    assert score(metrics, klines, "base_ratio", 5)["max_abs_delta"] == 0.0
    assert score(metrics, klines, "base_ratio", 0)["rows"] == 0
