"""Bounded commissioning check for Binance taker snapshot stability.

This does NOT promote any readiness gate. It re-queries already-observed historical
public taker rows, compares them with the immutable first capture, then compares
both with checksum-verified Data Vision metrics. The goal is to test whether the
archive/API mismatch can be explained by later mutation of the public endpoint or
by displayed volume precision.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pandas as pd

from forward_paper.taker_semantic_contract import METRICS_BASE, _download_verified

FIELDS = ("buySellRatio", "buyVol", "sellVol")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_old(path: str) -> tuple[dict[int, dict], str]:
    blob = Path(path).read_bytes()
    rows = json.loads(blob)
    return {int(r["timestamp"]): r for r in rows}, sha256_bytes(blob)


def _load_requery(path: str) -> tuple[dict[int, dict], dict, str]:
    blob = Path(path).read_bytes()
    doc = json.loads(blob)
    rows = doc.get("rows", [])
    return {int(r["timestamp"]): r for r in rows}, doc, sha256_bytes(blob)


def compare_snapshots(old: dict[int, dict], new: dict[int, dict], minimum_rows: int = 10) -> dict:
    overlap = sorted(set(old) & set(new))
    if len(overlap) < minimum_rows:
        raise ValueError(f"Insufficient immutable/requery overlap: {len(overlap)} < {minimum_rows}")
    mismatches = []
    for ts in overlap:
        for field in FIELDS:
            if str(old[ts][field]) != str(new[ts][field]):
                mismatches.append({"timestamp": ts, "field": field, "old": str(old[ts][field]), "new": str(new[ts][field])})
    return {
        "rows": len(overlap),
        "cells": len(overlap) * len(FIELDS),
        "exact_match_cells": len(overlap) * len(FIELDS) - len(mismatches),
        "mismatch_cells": len(mismatches),
        "mismatch_examples": mismatches[:10],
        "stable": len(mismatches) == 0,
    }


def _metrics_for_day(day: str) -> tuple[dict[int, str], str]:
    name = f"ETHUSDT-metrics-{day}.zip"
    blob, digest = _download_verified(f"{METRICS_BASE}/{name}")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        members = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(members) != 1:
            raise ValueError("Unexpected metrics archive members")
        frame = pd.read_csv(zf.open(members[0]), dtype=str)
    required = {"create_time", "sum_taker_long_short_vol_ratio"}
    if not required.issubset(frame.columns):
        raise ValueError("Metrics archive schema mismatch")
    times = pd.to_datetime(frame["create_time"], utc=True, errors="raise")
    values = frame["sum_taker_long_short_vol_ratio"].astype(str)
    out = {int(ts.timestamp() * 1000): value for ts, value in zip(times, values)}
    return out, digest


def _half_lsu(text: str) -> Decimal:
    decimals = len(text.partition(".")[2]) if "." in text else 0
    return Decimal(5).scaleb(-(decimals + 1))


def volume_ratio_interval(buy_text: str, sell_text: str) -> tuple[Decimal, Decimal]:
    buy = Decimal(buy_text)
    sell = Decimal(sell_text)
    hb = _half_lsu(buy_text)
    hs = _half_lsu(sell_text)
    buy_lo = max(Decimal(0), buy - hb)
    buy_hi = buy + hb
    sell_lo = sell - hs
    sell_hi = sell + hs
    if sell_lo <= 0:
        raise ValueError("Non-positive sell volume interval")
    return buy_lo / sell_hi, buy_hi / sell_lo


def compare_archive(new: dict[int, dict]) -> dict:
    days = sorted({pd.Timestamp(ts, unit="ms", tz="UTC").strftime("%Y-%m-%d") for ts in new})
    archive: dict[int, str] = {}
    hashes: dict[str, str] = {}
    for day in days:
        rows, digest = _metrics_for_day(day)
        archive.update(rows)
        hashes[day] = digest

    overlap = sorted(set(new) & set(archive))
    if len(overlap) < len(new):
        missing = sorted(set(new) - set(archive))
        raise ValueError(f"Archive missing requery timestamps: {missing[:10]}")

    ratio_deltas = []
    volume_ratio_deltas = []
    volume_interval_hits = 0
    examples = []
    for ts in overlap:
        row = new[ts]
        archived = Decimal(archive[ts])
        displayed = Decimal(str(row["buySellRatio"]))
        buy = Decimal(str(row["buyVol"]))
        sell = Decimal(str(row["sellVol"]))
        volume_ratio = buy / sell
        lo, hi = volume_ratio_interval(str(row["buyVol"]), str(row["sellVol"]))
        interval_hit = lo <= archived <= hi
        volume_interval_hits += int(interval_hit)
        ratio_delta = abs(archived - displayed)
        volume_delta = abs(archived - volume_ratio)
        ratio_deltas.append(ratio_delta)
        volume_ratio_deltas.append(volume_delta)
        examples.append({
            "timestamp": ts,
            "archive_ratio": str(archived),
            "endpoint_display_ratio": str(displayed),
            "endpoint_volume_ratio": str(volume_ratio),
            "archive_vs_display_abs_delta": str(ratio_delta),
            "archive_vs_volume_ratio_abs_delta": str(volume_delta),
            "archive_inside_volume_rounding_interval": interval_hit,
        })

    return {
        "rows": len(overlap),
        "archive_sha256_by_day": hashes,
        "archive_vs_display": {
            "max_abs_delta": str(max(ratio_deltas)),
            "median_abs_delta": str(sorted(ratio_deltas)[len(ratio_deltas) // 2]),
        },
        "archive_vs_endpoint_buy_sell_volume_ratio": {
            "max_abs_delta": str(max(volume_ratio_deltas)),
            "median_abs_delta": str(sorted(volume_ratio_deltas)[len(volume_ratio_deltas) // 2]),
            "within_rounding_interval_rows": volume_interval_hits,
            "all_within_rounding_interval": volume_interval_hits == len(overlap),
        },
        "examples": examples,
    }


def diagnose(old_path: str, requery_path: str) -> dict:
    old, old_sha = _load_old(old_path)
    new, doc, new_sha = _load_requery(requery_path)
    if not new:
        raise ValueError("Requery evidence has no rows")
    stability = compare_snapshots(old, new)
    archive = compare_archive(new)
    return {
        "schema": "eth-forward-taker-snapshot-stability-v1",
        "scope": "Bounded public taker historical requery stability and archive comparison only; no fills, model/strategy changes, gate promotion or account/order endpoint.",
        "observed_at_utc": doc.get("observed_at_utc"),
        "old_immutable_path": old_path,
        "old_immutable_sha256": old_sha,
        "requery_path": requery_path,
        "requery_sha256": new_sha,
        "endpoint_snapshot_stability": stability,
        "archive_comparison": archive,
        "conclusion": (
            "The sampled historical public taker endpoint rows are byte-value stable across the two observation times. Therefore later endpoint mutation does not explain the archive/API mismatch for this sample. The archive value is also not explainable solely by rounding of the endpoint buyVol/sellVol fields when all_within_rounding_interval is false."
            if stability["stable"] and not archive["archive_vs_endpoint_buy_sell_volume_ratio"]["all_within_rounding_interval"]
            else "The bounded evidence does not yet eliminate endpoint mutation and/or displayed-volume precision as an explanation."
        ),
        "source_contract_resolved": False,
        "paper_trades_created": 0,
        "gate_promotion": False,
        "performance_started": False,
        "orders_or_account_data_requested": False,
    }


def run(old_path: str, requery_path: str, out: str) -> dict:
    receipt = diagnose(old_path, requery_path)
    Path(out).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--old", required=True)
    p.add_argument("--requery", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    run(args.old, args.requery, args.out)
