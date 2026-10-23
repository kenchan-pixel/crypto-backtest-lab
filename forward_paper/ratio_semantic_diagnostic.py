"""Bounded commissioning diagnostic for Binance ratio-source semantics.

This module compares checksum-verified Binance daily metrics archives with the
existing immutable connected public read-only native-5m tail. It does not
create paper fills, change raw source values, promote readiness gates, or call
order/account endpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .live_pipeline import fetch_archive_day
from .persisted_pipeline import load_snapshot

OFFSETS_MINUTES = (-10, -5, 0, 5, 10)
FAMILIES = {
    "top_accounts": {
        "raw_key": "top_accounts",
        "archive_col": "count_toptrader_long_short_ratio",
        "raw_field": "longShortRatio",
    },
    "top_positions": {
        "raw_key": "top_positions",
        "archive_col": "sum_toptrader_long_short_ratio",
        "raw_field": "longShortRatio",
    },
    "global_accounts": {
        "raw_key": "all_accounts",
        "archive_col": "count_long_short_ratio",
        "raw_field": "longShortRatio",
    },
    "taker": {
        "raw_key": "taker",
        "archive_col": "sum_taker_long_short_vol_ratio",
        "raw_field": "buySellRatio",
    },
}


def _decimal_places(value: str) -> int:
    d = Decimal(str(value))
    return max(0, -d.as_tuple().exponent)


def _safe_div(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return a / b


def _transforms(family: str, row: dict) -> dict[str, float | None]:
    direct = float(row[FAMILIES[family]["raw_field"]])
    if family != "taker":
        return {"direct_ratio": direct}
    buy = float(row["buyVol"])
    sell = float(row["sellVol"])
    return {
        "direct_ratio": direct,
        "reciprocal_ratio": _safe_div(1.0, direct),
        "buy_volume_over_sell_volume": _safe_div(buy, sell),
        "sell_volume_over_buy_volume": _safe_div(sell, buy),
    }


def _score_candidate(
    archive: pd.DataFrame,
    rows: list[dict],
    family: str,
    transform_name: str,
    offset_minutes: int,
) -> dict:
    archive_col = FAMILIES[family]["archive_col"]
    raw_field = FAMILIES[family]["raw_field"]
    deltas: list[float] = []
    matched = 0
    cells = 0
    examples = []

    for row in rows:
        connected_ts = pd.to_datetime(int(row["timestamp"]), unit="ms", utc=True)
        archive_ts = connected_ts - pd.Timedelta(minutes=offset_minutes)
        if archive_ts not in archive.index:
            continue
        candidate = _transforms(family, row)[transform_name]
        if candidate is None or not math.isfinite(candidate):
            continue
        archive_value = float(archive.loc[archive_ts, archive_col])
        delta = abs(archive_value - candidate)
        places = _decimal_places(str(row[raw_field]))
        unit = 10.0 ** (-places)
        tolerance = 0.5 * unit + 1e-12
        cells += 1
        deltas.append(delta)
        if delta <= tolerance:
            matched += 1
        elif len(examples) < 3:
            examples.append({
                "connected_timestamp_utc": connected_ts.isoformat(),
                "archive_create_time_utc": archive_ts.isoformat(),
                "archive_value": archive_value,
                "connected_raw_ratio": str(row[raw_field]),
                "candidate_value": candidate,
                "abs_delta": delta,
                "tolerance": tolerance,
            })

    if not deltas:
        return {
            "cells": 0,
            "within_half_lsu": 0,
            "match_rate": 0.0,
            "max_abs_delta": None,
            "median_abs_delta": None,
            "mean_abs_delta": None,
            "examples": [],
        }
    s = pd.Series(deltas, dtype="float64")
    return {
        "cells": cells,
        "within_half_lsu": matched,
        "match_rate": matched / cells,
        "max_abs_delta": float(s.max()),
        "median_abs_delta": float(s.median()),
        "mean_abs_delta": float(s.mean()),
        "examples": examples,
    }


def _candidate_sort_key(item: tuple[str, dict]) -> tuple[float, float, float]:
    _, score = item
    median = score["median_abs_delta"]
    mean = score["mean_abs_delta"]
    return (
        float(score["match_rate"]),
        -float("inf") if median is None else -float(median),
        -float("inf") if mean is None else -float(mean),
    )


def diagnose(base_dir: str) -> dict:
    root = Path(base_dir)
    manifest, first_seen, raw, blob_checks = load_snapshot(base_dir)

    all_connected_times = [
        pd.to_datetime(int(row["timestamp"]), unit="ms", utc=True)
        for spec in FAMILIES.values()
        for row in raw[spec["raw_key"]]
    ]
    min_connected = min(all_connected_times)
    max_connected = max(all_connected_times)
    min_archive_needed = min_connected - pd.Timedelta(minutes=max(OFFSETS_MINUTES))
    max_archive_needed = max_connected - pd.Timedelta(minutes=min(OFFSETS_MINUTES))
    archive_days = sorted({
        str((min_archive_needed + pd.Timedelta(days=i)).date())
        for i in range((max_archive_needed.date() - min_archive_needed.date()).days + 1)
    })

    archive_parts = []
    archive_hashes = {}
    for day in archive_days:
        archive_day, frame, digest = fetch_archive_day(day)
        archive_parts.append(frame)
        archive_hashes[archive_day] = digest
    archive = pd.concat(archive_parts).sort_index()

    family_results = {}
    for family, spec in FAMILIES.items():
        rows = raw[spec["raw_key"]]
        transforms = list(_transforms(family, rows[0]).keys())
        candidates = {}
        for transform in transforms:
            for offset in OFFSETS_MINUTES:
                key = f"{transform}@archive_plus_{offset}m"
                candidates[key] = _score_candidate(
                    archive, rows, family, transform, offset
                )
        best_key, best_score = max(candidates.items(), key=_candidate_sort_key)
        runner_up = sorted(candidates.items(), key=_candidate_sort_key, reverse=True)[1]
        family_results[family] = {
            "raw_key": spec["raw_key"],
            "archive_column": spec["archive_col"],
            "connected_rows": len(rows),
            "candidate_offsets_minutes_archive_to_connected": list(OFFSETS_MINUTES),
            "candidates": candidates,
            "best_candidate": best_key,
            "best_score": best_score,
            "runner_up_candidate": runner_up[0],
            "runner_up_score": runner_up[1],
            "unique_perfect_contract": bool(
                best_score["cells"] >= 250
                and best_score["match_rate"] == 1.0
                and runner_up[1]["match_rate"] < 1.0
            ),
        }

    manifest_bytes = (root / "manifest.json").read_bytes()
    direct_best = {
        family: result["best_candidate"]
        for family, result in family_results.items()
    }
    resolved_families = [
        family for family, result in family_results.items()
        if result["unique_perfect_contract"]
    ]
    unresolved_families = [f for f in FAMILIES if f not in resolved_families]

    return {
        "schema": "eth-forward-ratio-semantic-diagnostic-v1",
        "scope": "Bounded checksum-archive versus immutable connected public read-only ratio semantic diagnostic; no fills, no model/strategy change, no gate promotion.",
        "base_first_seen_at_utc": first_seen.isoformat(),
        "connected_manifest": str(root / "manifest.json"),
        "connected_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "connected_blob_checks": blob_checks,
        "archive_days": archive_days,
        "archive_day_sha256": archive_hashes,
        "archive_checksum_verified": True,
        "families": family_results,
        "best_candidates": direct_best,
        "resolved_families": resolved_families,
        "unresolved_families": unresolved_families,
        "diagnostic_completed": True,
        "raw_values_rewritten": False,
        "paper_trades_created": 0,
        "gate_promotion": False,
        "performance_started": False,
        "order_or_account_endpoints_used": False,
    }


def run(base_dir: str, out: str) -> dict:
    receipt = diagnose(base_dir)
    Path(out).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    run(args.base_dir, args.out)
