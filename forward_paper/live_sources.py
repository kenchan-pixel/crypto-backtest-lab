"""Read-only live-source normalization for the frozen ETH forward study.

This module only validates/normalizes already-fetched public market data. It has no
HTTP, account, wallet or order client. Raw 5-minute metric observations are kept at
their native cadence so the inherited one-hour availability lag/as-of join can be
applied later without silently changing the historical feature definition.
"""
from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

FIVE_MIN_MS = 5 * 60 * 1000


def _num(value, name: str, *, positive: bool = True) -> float:
    x = float(value)
    if not math.isfinite(x) or (positive and x <= 0):
        raise ValueError(f"Invalid {name}")
    return x


def _ts_ms(value, name: str = "timestamp") -> int:
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    x = int(value)
    if x <= 0:
        raise ValueError(f"Invalid {name}")
    return x


def _validate_series(
    rows: Iterable[dict], symbol: str, *, timestamp_key: str = "timestamp", require_symbol: bool = True
) -> list[dict]:
    rows = [dict(r) for r in rows]
    if not rows:
        raise ValueError("Empty source series")
    seen = []
    for r in rows:
        if require_symbol:
            if r.get("symbol") != symbol:
                raise ValueError("Symbol mismatch")
        elif "symbol" in r and r.get("symbol") != symbol:
            raise ValueError("Symbol mismatch")
        seen.append(_ts_ms(r[timestamp_key], timestamp_key))
    if seen != sorted(seen) or len(set(seen)) != len(seen):
        raise ValueError("Source timestamps must be unique and increasing")
    return rows


def normalize_metric_bundle(
    *,
    symbol: str,
    period: str,
    open_interest: Iterable[dict],
    top_accounts: Iterable[dict],
    top_positions: Iterable[dict],
    all_accounts: Iterable[dict],
    taker: Iterable[dict],
) -> pd.DataFrame:
    """Map current Binance 5m public APIs to the archived metrics column contract.

    The old archive contains 5-minute `metrics` rows. A 1h endpoint is therefore
    not accepted as a substitute even if it exposes similarly named values.
    Only timestamps present in every required family are emitted; missing rows are
    not forward-filled here. The taker endpoint omits symbol in its response, so
    its symbol identity comes from the explicit request context supplied here.
    """
    if period != "5m":
        raise ValueError("Frozen source contract requires native 5m metric observations")

    def indexed(rows, mapping, *, require_symbol=True):
        rows = _validate_series(rows, symbol, require_symbol=require_symbol)
        out = {}
        for r in rows:
            t = _ts_ms(r["timestamp"])
            if t % FIVE_MIN_MS:
                raise ValueError("Metric timestamp is not 5m aligned")
            item = {}
            for src, dst in mapping.items():
                item[dst] = _num(r[src], src)
            out[t] = item
        return out

    oi = indexed(open_interest, {
        "sumOpenInterest": "sum_open_interest",
        "sumOpenInterestValue": "sum_open_interest_value",
    })
    ta = indexed(top_accounts, {"longShortRatio": "count_toptrader_long_short_ratio"})
    tp = indexed(top_positions, {"longShortRatio": "sum_toptrader_long_short_ratio"})
    aa = indexed(all_accounts, {"longShortRatio": "count_long_short_ratio"})
    tk = indexed(taker, {"buySellRatio": "sum_taker_long_short_vol_ratio"}, require_symbol=False)

    common = sorted(set(oi) & set(ta) & set(tp) & set(aa) & set(tk))
    if not common:
        raise ValueError("No exact common 5m timestamps across required metric families")
    rows = []
    for t in common:
        row = {"timestamp_utc": pd.to_datetime(t, unit="ms", utc=True), "symbol": symbol}
        for source in (oi, ta, tp, aa, tk):
            row.update(source[t])
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("timestamp_utc").sort_index()
    if not frame.index.is_unique:
        raise ValueError("Conflicting normalized metric timestamp")
    return frame


def normalize_funding_history(symbol: str, rows: Iterable[dict]) -> pd.DataFrame:
    """Normalize settled funding history while preserving millisecond jitter.

    The actual interval is inferred from consecutive settlement timestamps, as in
    the frozen historical pipeline. Current interval metadata may be used only as
    a consistency check, never to rewrite historical settlement spacing.
    """
    rows = _validate_series(rows, symbol, timestamp_key="fundingTime")
    out = []
    for r in rows:
        t = _ts_ms(r["fundingTime"], "fundingTime")
        out.append({
            "timestamp_utc": pd.to_datetime(t, unit="ms", utc=True),
            "last_funding_rate": _num(r["fundingRate"], "fundingRate", positive=False),
        })
    frame = pd.DataFrame(out).set_index("timestamp_utc").sort_index()
    if len(frame) >= 2:
        hours = frame.index.to_series().diff() / pd.Timedelta(hours=1)
        frame["funding_interval_hours"] = hours.values
        if ((hours.dropna() <= 0) | (hours.dropna() > 24)).any():
            raise ValueError("Implausible funding interval")
    else:
        frame["funding_interval_hours"] = float("nan")
    return frame
