"""Bounded commissioning diagnostic for the remaining taker source contract.

Compares checksum-verified Binance Data Vision UM 5m metrics with checksum-
verified UM 5m klines, plus the existing immutable connected read-only taker
snapshot. No fills, gate promotion, account/order calls, model changes, or raw
rewrites.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

METRICS_BASE = "https://data.binance.vision/data/futures/um/daily/metrics/ETHUSDT"
KLINE_BASE = "https://data.binance.vision/data/futures/um/daily/klines/ETHUSDT/5m"
UA = {"User-Agent": "crypto-backtest-lab-forward-paper/1"}
OFFSETS_MIN = (-5, 0, 5)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _download_verified(url: str) -> tuple[bytes, str]:
    r = requests.get(url, headers=UA, timeout=(10, 30))
    r.raise_for_status()
    c = requests.get(url + ".CHECKSUM", headers=UA, timeout=(10, 20))
    c.raise_for_status()
    digest = sha256_bytes(r.content)
    name = url.rsplit("/", 1)[-1]
    if not any(
        line.split()[0].lower() == digest and name in line
        for line in c.text.splitlines()
        if re.match(r"^[0-9a-fA-F]{64}\s", line)
    ):
        raise ValueError(f"CHECKSUM mismatch: {name}")
    return r.content, digest


def _read_single_csv(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("Unexpected archive members")
        return pd.read_csv(z.open(names[0]))


def fetch_day(day: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    m_name = f"ETHUSDT-metrics-{day}.zip"
    k_name = f"ETHUSDT-5m-{day}.zip"
    m_blob, m_hash = _download_verified(f"{METRICS_BASE}/{m_name}")
    k_blob, k_hash = _download_verified(f"{KLINE_BASE}/{k_name}")
    metrics = _read_single_csv(m_blob)
    klines = _read_single_csv(k_blob)

    required_m = {"create_time", "sum_taker_long_short_vol_ratio"}
    if not required_m.issubset(metrics.columns):
        raise ValueError("Metrics archive schema mismatch")
    # Daily futures kline archives currently carry the standard named columns.
    required_k = {"open_time", "volume", "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"}
    if not required_k.issubset(klines.columns):
        raise ValueError("Kline archive schema mismatch")

    m = pd.DataFrame({
        "metric": pd.to_numeric(metrics["sum_taker_long_short_vol_ratio"], errors="raise")
    }, index=pd.to_datetime(metrics["create_time"], utc=True, errors="raise"))
    kt = pd.to_datetime(pd.to_numeric(klines["open_time"], errors="raise"), unit="ms", utc=True)
    volume = pd.to_numeric(klines["volume"], errors="raise")
    buy = pd.to_numeric(klines["taker_buy_volume"], errors="raise")
    quote = pd.to_numeric(klines["quote_volume"], errors="raise")
    buy_quote = pd.to_numeric(klines["taker_buy_quote_volume"], errors="raise")
    sell = volume - buy
    sell_quote = quote - buy_quote
    k = pd.DataFrame({
        "base_ratio": np.where(sell > 0, buy / sell, np.nan),
        "quote_ratio": np.where(sell_quote > 0, buy_quote / sell_quote, np.nan),
    }, index=kt)
    return m.sort_index(), k.sort_index(), {"metrics_sha256": m_hash, "kline_sha256": k_hash}


def score(metrics: pd.DataFrame, klines: pd.DataFrame, column: str, offset_min: int) -> dict:
    shifted = klines[[column]].copy()
    shifted.index = shifted.index + pd.Timedelta(minutes=offset_min)
    joined = metrics.join(shifted, how="inner").dropna()
    if joined.empty:
        return {"rows": 0, "max_abs_delta": None, "median_abs_delta": None, "p99_abs_delta": None}
    d = (joined["metric"] - joined[column]).abs()
    return {
        "rows": int(len(d)),
        "max_abs_delta": float(d.max()),
        "median_abs_delta": float(d.median()),
        "p99_abs_delta": float(d.quantile(0.99)),
    }


def _load_connected(path: str) -> tuple[pd.DataFrame, str]:
    b = Path(path).read_bytes()
    rows = json.loads(b)
    f = pd.DataFrame(rows)
    f.index = pd.to_datetime(pd.to_numeric(f["timestamp"]), unit="ms", utc=True)
    f["connected_ratio"] = pd.to_numeric(f["buySellRatio"])
    return f[["connected_ratio"]].sort_index(), sha256_bytes(b)


def diagnose(days: list[str], connected_taker_path: str) -> dict:
    metric_parts, kline_parts, hashes = [], [], {}
    for day in days:
        m, k, h = fetch_day(day)
        metric_parts.append(m)
        kline_parts.append(k)
        hashes[day] = h
    metrics = pd.concat(metric_parts).sort_index()
    klines = pd.concat(kline_parts).sort_index()
    connected, connected_hash = _load_connected(connected_taker_path)

    candidates = {}
    for col in ("base_ratio", "quote_ratio"):
        for off in OFFSETS_MIN:
            candidates[f"{col}@kline_plus_{off}m"] = score(metrics, klines, col, off)
    ranked = sorted(
        candidates.items(),
        key=lambda x: (
            float("inf") if x[1]["median_abs_delta"] is None else x[1]["median_abs_delta"],
            float("inf") if x[1]["p99_abs_delta"] is None else x[1]["p99_abs_delta"],
        ),
    )
    best_name, best = ranked[0]
    second_name, second = ranked[1]

    overlap = metrics.join(connected, how="inner").dropna()
    conn_delta = (overlap["metric"] - overlap["connected_ratio"]).abs()

    # A source contract is accepted here only if the same-time final 5m base-volume
    # ratio is uniquely dominant and agrees to archive precision across essentially
    # the full two-day sample. The strict 5e-10 bound corresponds to a 10-decimal
    # archive field, not an ad-hoc fit to observed deltas.
    resolved = bool(
        best_name == "base_ratio@kline_plus_0m"
        and best["rows"] >= 500
        and best["max_abs_delta"] is not None
        and best["max_abs_delta"] <= 5e-10
        and second["median_abs_delta"] is not None
        and second["median_abs_delta"] > 1e-6
    )

    return {
        "schema": "eth-forward-taker-semantic-contract-v1",
        "scope": "Bounded checksum-archive taker semantics validation; no fill, model/strategy change, gate promotion, or account/order endpoint.",
        "archive_days": days,
        "archive_checksums": hashes,
        "connected_taker_path": connected_taker_path,
        "connected_taker_sha256": connected_hash,
        "official_endpoint_semantics": {
            "endpoint": "/futures/data/takerlongshortRatio",
            "timestamp": "start time of period",
            "fields": ["buySellRatio", "buyVol", "sellVol"],
        },
        "candidates": candidates,
        "best_candidate": best_name,
        "best_score": best,
        "runner_up_candidate": second_name,
        "runner_up_score": second,
        "connected_archive_same_timestamp": {
            "rows": int(len(conn_delta)),
            "max_abs_delta": None if conn_delta.empty else float(conn_delta.max()),
            "median_abs_delta": None if conn_delta.empty else float(conn_delta.median()),
        },
        "resolved": resolved,
        "resolved_contract": (
            "Data Vision sum_taker_long_short_vol_ratio equals final UM 5m kline taker-buy base volume divided by taker-sell base volume at the same period-start timestamp."
            if resolved else None
        ),
        "raw_values_rewritten": False,
        "paper_trades_created": 0,
        "gate_promotion": False,
        "performance_started": False,
        "order_or_account_endpoints_used": False,
    }


def run(days: list[str], connected_taker_path: str, out: str) -> dict:
    receipt = diagnose(days, connected_taker_path)
    Path(out).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", nargs="+", required=True)
    p.add_argument("--connected-taker", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(a.days, a.connected_taker, a.out)
