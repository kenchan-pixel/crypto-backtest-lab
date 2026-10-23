"""Fail-closed freshness checks for the frozen ETH forward study.

This module only validates public read-only derivative snapshots already fetched by
an external collector. It performs no HTTP or trading/account actions.
"""
from __future__ import annotations

import math
import pandas as pd

from .live_sources import normalize_metric_bundle, normalize_funding_history


def _obs(observed_at) -> pd.Timestamp:
    t = pd.Timestamp(observed_at)
    if t.tzinfo is None:
        raise ValueError("observed_at must include timezone")
    return t.tz_convert("UTC")


def _age_minutes(observed: pd.Timestamp, source: pd.Timestamp, name: str) -> float:
    age = (observed - source) / pd.Timedelta(minutes=1)
    if not math.isfinite(float(age)) or age < 0:
        raise ValueError(f"{name} timestamp is future or invalid")
    return float(age)


def validate_derivative_freshness(
    *,
    symbol: str,
    observed_at,
    open_interest,
    top_accounts,
    top_positions,
    all_accounts,
    taker,
    funding,
    metric_max_age_minutes: float = 15.0,
    funding_extra_grace_minutes: float = 90.0,
) -> dict:
    """Validate one causal live derivative snapshot.

    The archived metrics contract is native 5-minute data. Freshness is assessed
    on the latest timestamp common to every required metric family, not on the
    newest timestamp from any single endpoint. Settled funding has a different
    cadence: its permitted age is the most recently observed settlement interval
    plus a bounded publication/collection grace period.
    """
    if metric_max_age_minutes <= 0 or funding_extra_grace_minutes < 0:
        raise ValueError("Invalid freshness thresholds")
    observed = _obs(observed_at)

    metric = normalize_metric_bundle(
        symbol=symbol,
        period="5m",
        open_interest=open_interest,
        top_accounts=top_accounts,
        top_positions=top_positions,
        all_accounts=all_accounts,
        taker=taker,
    )
    latest_common = metric.index[-1]
    metric_age = _age_minutes(observed, latest_common, "Metric")
    if metric_age > metric_max_age_minutes:
        raise ValueError("Common derivative metric timestamp is stale")

    funding_frame = normalize_funding_history(symbol, funding)
    if len(funding_frame) < 2:
        raise ValueError("At least two settled funding rows required for cadence freshness")
    latest_funding = funding_frame.index[-1]
    funding_age = _age_minutes(observed, latest_funding, "Funding")
    intervals = funding_frame["funding_interval_hours"].dropna()
    if intervals.empty:
        raise ValueError("Funding interval unavailable")
    latest_interval_hours = float(intervals.iloc[-1])
    if not math.isfinite(latest_interval_hours) or latest_interval_hours <= 0 or latest_interval_hours > 24:
        raise ValueError("Funding interval invalid")
    funding_limit_minutes = latest_interval_hours * 60.0 + funding_extra_grace_minutes
    if funding_age > funding_limit_minutes:
        raise ValueError("Settled funding history is stale")

    families = {
        "open_interest": open_interest,
        "top_accounts": top_accounts,
        "top_positions": top_positions,
        "all_accounts": all_accounts,
        "taker": taker,
    }
    latest_by_family = {}
    for name, rows in families.items():
        rows = list(rows)
        if not rows:
            raise ValueError(f"Empty {name} series")
        latest = pd.to_datetime(int(rows[-1]["timestamp"]), unit="ms", utc=True)
        age = _age_minutes(observed, latest, name)
        latest_by_family[name] = {
            "timestamp_utc": latest.isoformat(),
            "age_minutes": age,
        }

    return {
        "symbol": symbol,
        "observed_at_utc": observed.isoformat(),
        "latest_common_metric_utc": latest_common.isoformat(),
        "common_metric_age_minutes": metric_age,
        "metric_max_age_minutes": float(metric_max_age_minutes),
        "latest_funding_utc": latest_funding.isoformat(),
        "funding_age_minutes": funding_age,
        "latest_funding_interval_hours": latest_interval_hours,
        "funding_freshness_limit_minutes": funding_limit_minutes,
        "latest_by_family": latest_by_family,
        "fresh": True,
    }
