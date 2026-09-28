"""Read-only diagnostic for Binance archive/live timestamp and precision semantics.

Commissioning evidence only. This compares an immutable connected-Binance native
5m snapshot against checksum-verified Binance daily metrics archives. It creates
no paper fills and never calls account/order endpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .persisted_pipeline import load_snapshot
from .live_sources import normalize_metric_bundle
from .live_pipeline import REQ_COLS, fetch_archive_day

OI_COLS = ["sum_open_interest", "sum_open_interest_value"]
RATIO_COLS = [
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
]
RAW_RATIO_FIELDS = {
    "count_toptrader_long_short_ratio": ("top_accounts", "longShortRatio"),
    "sum_toptrader_long_short_ratio": ("top_positions", "longShortRatio"),
    "count_long_short_ratio": ("all_accounts", "longShortRatio"),
    "sum_taker_long_short_vol_ratio": ("taker", "buySellRatio"),
}
FIVE_MIN = pd.Timedelta(minutes=5)


def _close(a: float, b: float) -> bool:
    return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-9)


def _decimal_places(raw_value) -> int:
    d = Decimal(str(raw_value))
    return max(0, -d.as_tuple().exponent)


def _raw_by_timestamp(rows: list[dict], field: str) -> dict[pd.Timestamp, str]:
    return {
        pd.to_datetime(int(r["timestamp"]), unit="ms", utc=True): str(r[field])
        for r in rows
    }


def run(base_dir, out):
    root = Path(base_dir)
    manifest, seen, raw, blob_checks = load_snapshot(base_dir)
    live = normalize_metric_bundle(
        symbol="ETHUSDT",
        period="5m",
        open_interest=raw["open_interest"],
        top_accounts=raw["top_accounts"],
        top_positions=raw["top_positions"],
        all_accounts=raw["all_accounts"],
        taker=raw["taker"],
    )

    # Archive create_time is the semantic under test. Fetch every UTC archive day
    # needed if archive create_time maps to the connected observation five minutes
    # later. fetch_archive_day verifies Binance's published CHECKSUM before use.
    expected_archive_times = live.index - FIVE_MIN
    archive_days = sorted({str(t.date()) for t in expected_archive_times})
    archive_parts = []
    archive_hashes = {}
    for day in archive_days:
        archive_day, frame, digest = fetch_archive_day(day)
        archive_parts.append(frame)
        archive_hashes[archive_day] = digest
    archive_native = pd.concat(archive_parts).sort_index()

    # Identify the timestamp mapping without rewriting either raw source. Count
    # exact/tight open-interest field matches under nearby candidate offsets.
    offset_match_counts = {}
    for minutes in (-10, -5, 0, 5, 10):
        shifted = archive_native.copy()
        shifted.index = shifted.index + pd.Timedelta(minutes=minutes)
        overlap = shifted.index.intersection(live.index)
        matches = 0
        cells = 0
        for t in overlap:
            for col in OI_COLS:
                cells += 1
                if _close(shifted.loc[t, col], live.loc[t, col]):
                    matches += 1
        offset_match_counts[str(minutes)] = {
            "overlap_rows": len(overlap),
            "oi_cells": cells,
            "oi_exact_or_float_safe_matches": matches,
        }

    best_offset = max(
        (-10, -5, 0, 5, 10),
        key=lambda x: offset_match_counts[str(x)]["oi_exact_or_float_safe_matches"],
    )
    best_matches = offset_match_counts[str(best_offset)]["oi_exact_or_float_safe_matches"]
    second_best = max(
        v["oi_exact_or_float_safe_matches"]
        for k, v in offset_match_counts.items()
        if int(k) != best_offset
    )

    # Apply the candidate +5m semantic mapping only inside this diagnostic. Raw
    # timestamps remain immutable. This is the mapping already suggested by the
    # three-row mismatch receipt; here we test the full persisted tail.
    aligned_archive = archive_native.copy()
    aligned_archive.index = aligned_archive.index + FIVE_MIN
    overlap = aligned_archive.index.intersection(live.index).sort_values()

    oi_mismatches = []
    for t in overlap:
        for col in OI_COLS:
            a = float(aligned_archive.loc[t, col])
            b = float(live.loc[t, col])
            if not _close(a, b):
                oi_mismatches.append({
                    "timestamp_utc": t.isoformat(), "field": col,
                    "archive_shifted": a, "connected": b, "abs_delta": b - a,
                })

    raw_ratio_maps = {
        col: _raw_by_timestamp(raw[key], field)
        for col, (key, field) in RAW_RATIO_FIELDS.items()
    }
    ratio_mismatches = []
    ratio_max_abs_delta = {c: 0.0 for c in RATIO_COLS}
    ratio_max_ulps = {c: 0.0 for c in RATIO_COLS}
    precision_seen = {c: set() for c in RATIO_COLS}
    for t in overlap:
        for col in RATIO_COLS:
            raw_live = raw_ratio_maps[col][t]
            places = _decimal_places(raw_live)
            precision_seen[col].add(places)
            unit = 10.0 ** (-places)
            a = float(aligned_archive.loc[t, col])
            b = float(live.loc[t, col])
            delta = abs(a - b)
            ulps = delta / unit if unit else 0.0
            ratio_max_abs_delta[col] = max(ratio_max_abs_delta[col], delta)
            ratio_max_ulps[col] = max(ratio_max_ulps[col], ulps)
            # Connected ratio endpoints publish rounded values (typically 4 dp).
            # Accept only values within half of one published least-significant
            # unit; this preserves archive precision and never rewrites raw data.
            if delta > (0.5 * unit + 1e-12):
                ratio_mismatches.append({
                    "timestamp_utc": t.isoformat(), "field": col,
                    "archive_shifted": a, "connected_raw": raw_live,
                    "connected_precision_dp": places,
                    "abs_delta": delta, "delta_in_connected_units": ulps,
                })

    sample_times = list(overlap[:2]) + (list(overlap[-2:]) if len(overlap) > 2 else [])
    samples = {}
    for t in sample_times:
        samples[t.isoformat()] = {
            c: {
                "archive_create_time_utc": (t - FIVE_MIN).isoformat(),
                "archive_value": float(aligned_archive.loc[t, c]),
                "connected_timestamp_utc": t.isoformat(),
                "connected_value": float(live.loc[t, c]),
            }
            for c in REQ_COLS
        }

    manifest_bytes = (root / "manifest.json").read_bytes()
    enough_breadth = len(overlap) >= 250 and len(archive_days) >= 2
    unique_five_min_mapping = best_offset == 5 and best_matches > second_best
    passed = bool(
        enough_breadth
        and unique_five_min_mapping
        and not oi_mismatches
        and not ratio_mismatches
        and len(overlap) == len(live)
    )

    receipt = {
        "schema": "archive-connected-semantic-validation-v2",
        "passed": passed,
        "scope": "Checksum-verified public archive versus immutable connected read-only native5m tail; semantic/precision validation only, no fill/performance.",
        "base_first_seen_at_utc": seen.isoformat(),
        "connected_manifest": str(root / "manifest.json"),
        "connected_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "connected_blob_checks": blob_checks,
        "connected_common_rows": len(live),
        "connected_first_utc": live.index.min().isoformat(),
        "connected_last_utc": live.index.max().isoformat(),
        "archive_days": archive_days,
        "archive_day_sha256": archive_hashes,
        "archive_checksum_verified": True,
        "timestamp_semantics": {
            "candidate_offsets_minutes_archive_to_connected": offset_match_counts,
            "best_offset_minutes": best_offset,
            "best_oi_matches": best_matches,
            "second_best_oi_matches": second_best,
            "validated_mapping_if_passed": "archive create_time + 5 minutes == connected endpoint timestamp for the same 5m observation",
            "raw_timestamps_rewritten": False,
        },
        "aligned_overlap_rows": len(overlap),
        "all_connected_rows_covered_by_aligned_archive": len(overlap) == len(live),
        "open_interest_contract": {
            "comparison": "tight numeric equality (rtol=1e-12, atol=1e-9)",
            "cells_checked": len(overlap) * len(OI_COLS),
            "mismatches": len(oi_mismatches),
            "examples": oi_mismatches[:5],
        },
        "ratio_contract": {
            "comparison": "absolute archive/live delta <= half one least-significant decimal unit published by the connected endpoint",
            "precision_dp_seen": {k: sorted(v) for k, v in precision_seen.items()},
            "cells_checked": len(overlap) * len(RATIO_COLS),
            "mismatches": len(ratio_mismatches),
            "max_abs_delta": ratio_max_abs_delta,
            "max_delta_in_connected_units": ratio_max_ulps,
            "examples": ratio_mismatches[:5],
            "raw_values_rewritten": False,
        },
        "samples": samples,
        "paper_trades_created": 0,
        "gate_promotion": False,
        "performance_started": False,
        "order_or_account_endpoints_used": False,
        "next_step_if_passed": "Implement the validated +5m archive normalization and precision-aware overlap contract in the commissioning merge path, then rerun a genuinely fresh full source-to-feature-to-opportunity receipt. Do not promote readiness on this semantic diagnostic alone.",
    }
    Path(out).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    print(json.dumps(receipt, indent=2, allow_nan=False))
    if not passed:
        raise SystemExit("Archive/live semantic validation did not pass")
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(a.base_dir, a.out)
