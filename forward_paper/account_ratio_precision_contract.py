"""Bounded commissioning validation for Binance account-ratio precision semantics.

Uses the immutable connected public read-only tail and checksum-verified daily
metrics archives. It tests whether the unresolved account-ratio differences are
fully explained by the documented Long Account % / Short Account % formula plus
the connector's published component precision, under the already evidenced
archive create_time + 5m -> endpoint period-end mapping.

No fills, model changes, raw rewrites or readiness promotion occur here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

from .live_pipeline import fetch_archive_day
from .persisted_pipeline import load_snapshot

OFFSET_MINUTES = 5
FAMILIES = {
    "top_accounts": {
        "raw_key": "top_accounts",
        "archive_col": "count_toptrader_long_short_ratio",
    },
    "global_accounts": {
        "raw_key": "all_accounts",
        "archive_col": "count_long_short_ratio",
    },
}
DOC_URL = "https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Get-Funding-Info"


def _places(value: str) -> int:
    return max(0, -Decimal(str(value)).as_tuple().exponent)


def _half_unit(value: str) -> Decimal:
    return Decimal("0.5") * (Decimal(10) ** (-_places(value)))


def _component_ratio_interval(row: dict) -> tuple[Decimal, Decimal]:
    """Return ratio bounds consistent with rounded long/short account shares.

    Binance documents longShortRatio = Long Account % / Short Account %, and the
    two account shares exhaust the counted accounts. The endpoint publishes each
    component to finite decimal precision. We therefore intersect the possible
    true long-share interval implied independently by longAccount and by
    1-shortAccount, then map that interval monotonically through p/(1-p).
    """
    long_v = Decimal(str(row["longAccount"]))
    short_v = Decimal(str(row["shortAccount"]))
    long_h = _half_unit(str(row["longAccount"]))
    short_h = _half_unit(str(row["shortAccount"]))

    p_low = max(long_v - long_h, Decimal(1) - (short_v + short_h))
    p_high = min(long_v + long_h, Decimal(1) - (short_v - short_h))
    if not (Decimal(0) < p_low <= p_high < Decimal(1)):
        raise ValueError("invalid rounded account-share interval")
    return p_low / (Decimal(1) - p_low), p_high / (Decimal(1) - p_high)


def _reported_ratio_from_published_components(row: dict) -> Decimal:
    places = _places(str(row["longShortRatio"]))
    quantum = Decimal(1).scaleb(-places)
    ratio = Decimal(str(row["longAccount"])) / Decimal(str(row["shortAccount"]))
    return ratio.quantize(quantum, rounding=ROUND_HALF_UP)


def _load_archives(rows_by_family: dict[str, list[dict]]) -> tuple[pd.DataFrame, dict[str, str]]:
    times = [
        pd.to_datetime(int(row["timestamp"]), unit="ms", utc=True)
        - pd.Timedelta(minutes=OFFSET_MINUTES)
        for rows in rows_by_family.values()
        for row in rows
    ]
    days = sorted({str(ts.date()) for ts in times})
    parts = []
    hashes: dict[str, str] = {}
    for day in days:
        archive_day, frame, digest = fetch_archive_day(day)
        parts.append(frame)
        hashes[archive_day] = digest
    return pd.concat(parts).sort_index(), hashes


def _score_family(archive: pd.DataFrame, rows: list[dict], archive_col: str) -> dict:
    covered = 0
    internal_formula_matches = 0
    archive_inside_interval = 0
    interval_failures = []
    max_interval_width = Decimal(0)
    max_direct_archive_delta = Decimal(0)

    for row in rows:
        connected_ts = pd.to_datetime(int(row["timestamp"]), unit="ms", utc=True)
        archive_ts = connected_ts - pd.Timedelta(minutes=OFFSET_MINUTES)
        if archive_ts not in archive.index:
            continue
        covered += 1
        direct = Decimal(str(row["longShortRatio"]))
        reconstructed = _reported_ratio_from_published_components(row)
        if reconstructed == direct:
            internal_formula_matches += 1

        low, high = _component_ratio_interval(row)
        archive_value = Decimal(str(archive.loc[archive_ts, archive_col]))
        width = high - low
        if width > max_interval_width:
            max_interval_width = width
        delta = abs(archive_value - direct)
        if delta > max_direct_archive_delta:
            max_direct_archive_delta = delta
        if low <= archive_value <= high:
            archive_inside_interval += 1
        elif len(interval_failures) < 5:
            interval_failures.append({
                "connected_timestamp_utc": connected_ts.isoformat(),
                "archive_create_time_utc": archive_ts.isoformat(),
                "longAccount": str(row["longAccount"]),
                "shortAccount": str(row["shortAccount"]),
                "connected_longShortRatio": str(row["longShortRatio"]),
                "archive_value": str(archive_value),
                "allowed_ratio_low": str(low),
                "allowed_ratio_high": str(high),
            })

    return {
        "rows_expected": len(rows),
        "rows_covered": covered,
        "reported_ratio_equals_rounded_ratio_of_published_components": internal_formula_matches,
        "archive_value_within_component_rounding_interval": archive_inside_interval,
        "all_rows_internal_formula_consistent": covered == len(rows) and internal_formula_matches == covered,
        "all_archive_values_precision_compatible": covered == len(rows) and archive_inside_interval == covered,
        "max_component_implied_ratio_interval_width": float(max_interval_width),
        "max_abs_archive_vs_connected_direct_ratio": float(max_direct_archive_delta),
        "examples_outside_interval": interval_failures,
    }


def diagnose(base_dir: str, connector_probe: str | None = None) -> dict:
    root = Path(base_dir)
    manifest, first_seen, raw, blob_checks = load_snapshot(base_dir)
    rows_by_family = {name: raw[spec["raw_key"]] for name, spec in FAMILIES.items()}
    archive, archive_hashes = _load_archives(rows_by_family)

    results = {
        name: _score_family(archive, rows_by_family[name], spec["archive_col"])
        for name, spec in FAMILIES.items()
    }
    resolved = [
        name for name, result in results.items()
        if result["all_rows_internal_formula_consistent"]
        and result["all_archive_values_precision_compatible"]
        and result["rows_covered"] >= 250
    ]

    probe_sha = None
    if connector_probe:
        probe_sha = hashlib.sha256(Path(connector_probe).read_bytes()).hexdigest()

    return {
        "schema": "eth-forward-account-ratio-precision-contract-v1",
        "scope": "Bounded source-semantic validation for top/global account ratios only; no taker resolution, fills, model/strategy change, raw rewrite or gate promotion.",
        "base_first_seen_at_utc": first_seen.isoformat(),
        "connected_manifest": str(root / "manifest.json"),
        "connected_manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
        "connected_blob_checks": blob_checks,
        "corroborating_connector_probe": connector_probe,
        "corroborating_connector_probe_sha256": probe_sha,
        "official_semantic_evidence": {
            "source": "Binance Developer Docs",
            "url": DOC_URL,
            "formula": "Long/Short Ratio (Accounts) = Long Account % / Short Account %",
            "timestamp_semantic": "endpoint timestamp is documented as end time of the period",
            "use": "semantic support only; archive equivalence is established by data checks below",
        },
        "archive_create_time_to_connected_period_end_offset_minutes": OFFSET_MINUTES,
        "archive_day_sha256": archive_hashes,
        "archive_checksum_verified": True,
        "families": results,
        "resolved_account_ratio_families": resolved,
        "all_account_ratio_families_resolved": set(resolved) == set(FAMILIES),
        "taker_semantics_resolved": False,
        "raw_values_rewritten": False,
        "paper_trades_created": 0,
        "gate_promotion": False,
        "performance_started": False,
        "order_or_account_endpoints_used": False,
    }


def run(base_dir: str, out: str, connector_probe: str | None = None) -> dict:
    receipt = diagnose(base_dir, connector_probe=connector_probe)
    Path(out).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--connector-probe")
    args = p.parse_args()
    run(args.base_dir, args.out, connector_probe=args.connector_probe)
