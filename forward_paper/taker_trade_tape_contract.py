"""Bounded commissioning diagnostic for Binance taker cut-off semantics.

Reconstruct each checksum-verified Data Vision 5m taker ratio directly from the
checksum-verified USD-M ETHUSDT aggregate-trade tape, then test small symmetric
window offsets around the nominal 5m boundary.  This is evidence only: it does
not alter raw values, source gates, model inputs, paper state, or any account/order
endpoint.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from forward_paper.taker_semantic_contract import METRICS_BASE, _download_verified

AGG_BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades/ETHUSDT"
OFFSETS_SECONDS = (-60, -30, -15, -5, 0, 5, 15, 30, 60)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _single_csv(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("Unexpected archive members")
        return pd.read_csv(zf.open(names[0]))


def fetch_day(day: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    m_name = f"ETHUSDT-metrics-{day}.zip"
    a_name = f"ETHUSDT-aggTrades-{day}.zip"
    m_blob, m_hash = _download_verified(f"{METRICS_BASE}/{m_name}")
    a_blob, a_hash = _download_verified(f"{AGG_BASE}/{a_name}")
    metrics = _single_csv(m_blob)
    trades = _single_csv(a_blob)

    if not {"create_time", "sum_taker_long_short_vol_ratio"}.issubset(metrics.columns):
        raise ValueError("Metrics archive schema mismatch")
    aliases = {
        "quantity": ("quantity", "qty"),
        "transact_time": ("transact_time", "timestamp", "time"),
        "is_buyer_maker": ("is_buyer_maker", "was_buyer_maker", "m"),
    }
    resolved = {}
    for target, names in aliases.items():
        for name in names:
            if name in trades.columns:
                resolved[target] = name
                break
        if target not in resolved:
            raise ValueError(f"AggTrades archive schema missing {target}: {list(trades.columns)}")

    mt = pd.to_datetime(metrics["create_time"], utc=True, errors="raise")
    m = pd.DataFrame(
        {"archive_ratio": pd.to_numeric(metrics["sum_taker_long_short_vol_ratio"], errors="raise").to_numpy()},
        index=mt,
    ).sort_index()

    t = pd.DataFrame({
        "time": pd.to_datetime(pd.to_numeric(trades[resolved["transact_time"]], errors="raise"), unit="ms", utc=True),
        "quantity": pd.to_numeric(trades[resolved["quantity"]], errors="raise"),
        "is_buyer_maker": trades[resolved["is_buyer_maker"]].astype(str).str.lower().map({"true": True, "false": False}),
    })
    if t["is_buyer_maker"].isna().any() or (t["quantity"] <= 0).any():
        raise ValueError("Invalid aggregate-trade maker flag or quantity")
    if not t["time"].is_monotonic_increasing:
        t = t.sort_values("time").reset_index(drop=True)
    return m, t, {"metrics_sha256": m_hash, "aggtrades_sha256": a_hash, "aggtrade_rows": int(len(t))}


def aggregate_window(trades: pd.DataFrame, offset_seconds: int) -> pd.DataFrame:
    offset = pd.Timedelta(seconds=offset_seconds)
    nominal = (trades["time"] - offset).dt.floor("5min")
    buy = trades["quantity"].where(~trades["is_buyer_maker"], 0.0)
    sell = trades["quantity"].where(trades["is_buyer_maker"], 0.0)
    g = pd.DataFrame({"nominal": nominal, "buy": buy, "sell": sell}).groupby("nominal", sort=True)[["buy", "sell"]].sum()
    g["tape_ratio"] = np.where(g["sell"] > 0, g["buy"] / g["sell"], np.nan)
    return g[["tape_ratio", "buy", "sell"]]


def score(metrics: pd.DataFrame, trades: pd.DataFrame, offset_seconds: int) -> dict:
    tape = aggregate_window(trades, offset_seconds)
    j = metrics.join(tape[["tape_ratio"]], how="inner").dropna()
    if len(j) < 250:
        raise ValueError(f"Insufficient metric/trade-tape overlap at offset {offset_seconds}s: {len(j)}")
    delta = (j["archive_ratio"] - j["tape_ratio"]).abs()
    return {
        "rows": int(len(delta)),
        "median_abs_delta": float(delta.median()),
        "p95_abs_delta": float(delta.quantile(0.95)),
        "p99_abs_delta": float(delta.quantile(0.99)),
        "max_abs_delta": float(delta.max()),
        "exact_1e_10_rows": int((delta <= 1e-10).sum()),
    }


def load_connected(path: str) -> tuple[pd.DataFrame, str]:
    blob = Path(path).read_bytes()
    rows = json.loads(blob)
    frame = pd.DataFrame(rows)
    frame.index = pd.to_datetime(pd.to_numeric(frame["timestamp"], errors="raise"), unit="ms", utc=True)
    frame["endpoint_ratio"] = pd.to_numeric(frame["buySellRatio"], errors="raise")
    return frame[["endpoint_ratio"]].sort_index(), sha256_bytes(blob)


def diagnose(day: str, connected_taker_path: str) -> dict:
    metrics, trades, hashes = fetch_day(day)
    candidates = {str(off): score(metrics, trades, off) for off in OFFSETS_SECONDS}
    ranked = sorted(candidates.items(), key=lambda kv: (kv[1]["median_abs_delta"], kv[1]["p99_abs_delta"]))
    best_offset, best = ranked[0]

    connected, connected_sha = load_connected(connected_taker_path)
    endpoint = metrics.join(connected, how="inner").dropna()
    if len(endpoint) < 200:
        raise ValueError(f"Insufficient archive/connected endpoint overlap: {len(endpoint)}")
    endpoint_delta = (endpoint["archive_ratio"] - endpoint["endpoint_ratio"]).abs()

    # A resolved cut-off contract requires the trade tape to reproduce the archive
    # essentially exactly, not merely to be the least-bad offset.
    resolved = bool(best["max_abs_delta"] <= 1e-10 and int(best_offset) == 0)
    exact_zero = candidates["0"]
    return {
        "schema": "eth-forward-taker-trade-tape-contract-v1",
        "scope": "Bounded checksum-verified Data Vision metric vs USD-M aggregate-trade tape cut-off diagnostic only; no fills, gate promotion, model/strategy change, or account/order endpoint.",
        "day_utc": day,
        "archive_sources": hashes,
        "connected_taker_path": connected_taker_path,
        "connected_taker_sha256": connected_sha,
        "window_definition": "For offset s, metric timestamp t is compared with aggregate trades in [t+s, t+s+5m); buyer-is-maker=false is taker buy, true is taker sell.",
        "tested_offsets_seconds": list(OFFSETS_SECONDS),
        "offset_scores": candidates,
        "best_offset_seconds": int(best_offset),
        "best_score": best,
        "nominal_zero_offset_score": exact_zero,
        "archive_vs_connected_endpoint": {
            "rows": int(len(endpoint_delta)),
            "median_abs_delta": float(endpoint_delta.median()),
            "p99_abs_delta": float(endpoint_delta.quantile(0.99)),
            "max_abs_delta": float(endpoint_delta.max()),
        },
        "source_contract_resolved": resolved,
        "resolved_contract": "Archive ratio equals exact same-period aggregate-trade taker-buy/taker-sell base quantity ratio." if resolved else None,
        "conclusion": (
            "Checksum-verified aggregate trades reproduce the archive ratio exactly at the nominal same-period cut-off."
            if resolved else
            "No tested ±60s cut-off reconstructs the Data Vision taker metric exactly from the checksum-verified aggregate-trade tape; keep the taker source contract unresolved and fail closed."
        ),
        "raw_values_rewritten": False,
        "paper_trades_created": 0,
        "gate_promotion": False,
        "performance_started": False,
        "order_or_account_endpoints_used": False,
    }


def run(day: str, connected_taker_path: str, out: str) -> dict:
    receipt = diagnose(day, connected_taker_path)
    Path(out).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--day", required=True)
    p.add_argument("--connected-taker", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(a.day, a.connected_taker, a.out)
