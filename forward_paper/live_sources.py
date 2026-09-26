"""Read-only live-source normalization for the frozen ETH forward study.

This module only validates/normalizes already-fetched public market data. It has no
HTTP, account, wallet or order client. Raw 5-minute metric observations are kept at
their native cadence so the inherited one-hour availability lag/as-of join can be
applied later without silently changing the historical feature definition.

Spot hour records follow the inherited convention: the dataframe index is the exact
end of a completed hour (for example the 15:00-15:59:59.999 UTC Binance kline is
indexed at 16:00 UTC). The still-open current hour is never admitted.
"""
from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

FIVE_MIN_MS = 5 * 60 * 1000
HOUR_MS = 60 * 60 * 1000


def _num(value, name: str, *, positive: bool = True) -> float:
    x = float(value)
    if not math.isfinite(x) or (positive and x <= 0):
        raise ValueError(f"Invalid {name}")
    return x


def _nonnegative(value, name: str) -> float:
    x = float(value)
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"Invalid {name}")
    return x


def _ts_ms(value, name: str = "timestamp") -> int:
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    x = int(value)
    if x <= 0:
        raise ValueError(f"Invalid {name}")
    return x


def _observed_ms(observed_at) -> int:
    t = pd.Timestamp(observed_at)
    if t.tzinfo is None:
        raise ValueError("observed_at must include timezone")
    return int(t.tz_convert("UTC").value // 1_000_000)


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


def normalize_spot_klines(
    symbol: str,
    rows: Iterable,
    observed_at,
    *,
    max_age_minutes: float = 90.0,
    min_completed_hours: int = 1,
) -> pd.DataFrame:
    """Validate public Binance 1h spot klines and keep completed hours only.

    Binance returns the currently forming hour in the same response as settled
    klines. A row is usable only when its close timestamp is strictly before the
    actual observation time. No incomplete bar is truncated or inferred.

    The normalized index is ``closeTime + 1 ms``. This reproduces the frozen
    historical convention that each row is labelled by the exact hour it has just
    completed, while deliberately omitting the historical ``execution_open`` field
    because a future next-minute fill is not known in a forward run.
    """
    if symbol not in {"ETHUSDT", "BTCUSDT"}:
        raise ValueError("Unexpected spot symbol")
    obs_ms = _observed_ms(observed_at)
    source = list(rows)
    if not source:
        raise ValueError("Empty spot kline series")
    opens = []
    normalized = []
    for raw in source:
        if not isinstance(raw, (list, tuple)) or len(raw) < 11:
            raise ValueError("Unexpected Binance spot kline schema")
        open_ms = _ts_ms(raw[0], "open_time")
        close_ms = _ts_ms(raw[6], "close_time")
        opens.append(open_ms)
        if close_ms != open_ms + HOUR_MS - 1:
            raise ValueError("Spot kline is not an exact one-hour interval")

        o = _num(raw[1], "open")
        h = _num(raw[2], "high")
        l = _num(raw[3], "low")
        c = _num(raw[4], "close")
        volume = _nonnegative(raw[5], "volume")
        quote_volume = _nonnegative(raw[7], "quote_volume")
        taker_quote = _nonnegative(raw[10], "taker_quote")
        if h < max(o, c, l) or l > min(o, c, h) or h < l:
            raise ValueError("Invalid OHLC relationship")

        # Current/partial future-closing rows are intentionally ignored only after
        # their schema/OHLC has been validated; they never enter feature history.
        if close_ms >= obs_ms:
            continue
        normalized.append({
            "decision_utc": pd.to_datetime(close_ms + 1, unit="ms", utc=True),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": volume,
            "quote_volume": quote_volume,
            "taker_quote": taker_quote,
            "minutes": 60,
            "source_open_ms": open_ms,
            "source_close_ms": close_ms,
        })

    if opens != sorted(opens) or len(set(opens)) != len(opens):
        raise ValueError("Spot kline open times must be unique and increasing")
    if len(normalized) < min_completed_hours:
        raise ValueError("Insufficient completed spot-hour history")
    frame = pd.DataFrame(normalized).set_index("decision_utc").sort_index()
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("Normalized spot-hour index invalid")
    gaps = frame.index.to_series().diff().dropna()
    if (gaps != pd.Timedelta(hours=1)).any():
        raise ValueError("Missing completed spot-hour slot")
    if not (frame.index.minute == 0).all() or not (frame.index.second == 0).all():
        raise ValueError("Spot decision index must be exact hourly boundary")
    age_minutes = (obs_ms - int(frame.index[-1].value // 1_000_000)) / 60_000
    if age_minutes < 0 or age_minutes > max_age_minutes:
        raise ValueError("Latest completed spot hour is stale or future")
    frame.attrs.update({
        "symbol": symbol,
        "observed_at_utc": pd.to_datetime(obs_ms, unit="ms", utc=True).isoformat(),
        "latest_complete_age_minutes": float(age_minutes),
        "partial_rows_excluded": len(source) - len(frame),
    })
    return frame


def normalize_spot_pair(
    eth_rows: Iterable,
    btc_rows: Iterable,
    observed_at,
    *,
    max_age_minutes: float = 90.0,
    min_completed_hours: int = 721,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return exactly aligned ETH/BTC completed-hour histories with no fill."""
    eth = normalize_spot_klines(
        "ETHUSDT", eth_rows, observed_at,
        max_age_minutes=max_age_minutes, min_completed_hours=min_completed_hours,
    )
    btc = normalize_spot_klines(
        "BTCUSDT", btc_rows, observed_at,
        max_age_minutes=max_age_minutes, min_completed_hours=min_completed_hours,
    )
    if not eth.index.equals(btc.index):
        raise ValueError("ETH/BTC completed spot-hour timing mismatch")
    return eth, btc


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
