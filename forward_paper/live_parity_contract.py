"""Fail-closed archive/live parity contract for the frozen ETH forward study.

The contract separates evidence required by the frozen decision path from public
market-data families that are still captured for provenance/freshness but cannot
change this frozen model. Raw source payloads are never rewritten here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

FROZEN_MODEL_SHA256 = "08f2ba34b48d2aa5925af90c13452a34efbb0dc0f88d4694caa330bdf832c3fe"
DEPENDENCY_RECEIPT = Path("forward_paper/receipts/taker_decision_invariance_20260922T134155Z.json")
MODEL_PATH = Path("forward_paper/model.json")
ARCHIVE_TO_CONNECTED_OFFSET_MINUTES = 5
DECISION_EXACT_COLUMNS = ("sum_open_interest", "sum_open_interest_value")
DECISION_PRECISION_COLUMNS = ("sum_toptrader_long_short_ratio",)
NON_DECISION_COLUMNS = (
    "count_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)
ALL_COLUMNS = (*DECISION_EXACT_COLUMNS, *DECISION_PRECISION_COLUMNS, *NON_DECISION_COLUMNS)
TOP_POSITION_CONNECTED_DECIMALS = 4
TOP_POSITION_HALF_LSU = 0.5 * 10 ** (-TOP_POSITION_CONNECTED_DECIMALS)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_dependency_proof(
    *,
    model_path: str | Path = MODEL_PATH,
    dependency_receipt_path: str | Path = DEPENDENCY_RECEIPT,
) -> dict:
    """Pin the exemption to the exact frozen model and proved dependency graph."""
    model_path = Path(model_path)
    receipt_path = Path(dependency_receipt_path)
    model_sha = _sha256(model_path)
    if model_sha != FROZEN_MODEL_SHA256:
        raise ValueError("Frozen model hash changed; live parity exemption invalid")
    r = json.loads(receipt_path.read_text())
    if r.get("schema") != "eth-forward-taker-decision-invariance-receipt-v1":
        raise ValueError("Unexpected taker dependency receipt schema")
    frozen = r.get("frozen_model", {})
    proof = r.get("dependency_proof", {})
    conclusion = r.get("conclusion", {})
    if frozen.get("sha256") != FROZEN_MODEL_SHA256 or frozen.get("taker_feature_references") != []:
        raise ValueError("Taker dependency receipt is not pinned to the frozen model")
    if proof.get("state_derivative_inputs") != ["funding_per_hour", "oi_logchange_24h", "top_position_ratio"]:
        raise ValueError("Frozen derivative dependency set changed")
    if proof.get("taker_enters_frozen_state") is not False or proof.get("taker_enters_frozen_model") is not False:
        raise ValueError("Taker dependency proof no longer excludes the decision path")
    if conclusion.get("frozen_decision_invariant_to_taker") is not True:
        raise ValueError("Taker invariance conclusion missing")
    if conclusion.get("taker_source_semantics_resolved") is not False:
        raise ValueError("Unexpected taker semantic status")
    if r.get("gate_promotion") is not False or r.get("performance_started") is not False:
        raise ValueError("Dependency receipt crossed commissioning boundary")
    return {
        "frozen_model_sha256": model_sha,
        "dependency_receipt": str(receipt_path),
        "dependency_receipt_sha256": _sha256(receipt_path),
        "decision_derivative_inputs": proof["state_derivative_inputs"],
        "taker_enters_frozen_decision": False,
    }


def _validate_frames(archive: pd.DataFrame, connected: pd.DataFrame) -> None:
    for name, frame in (("archive", archive), ("connected", connected)):
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError(f"{name} metric index must be timezone-aware DatetimeIndex")
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError(f"{name} metric index must be unique and increasing")
        missing = [c for c in ALL_COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"{name} metric columns missing: {missing}")
        values = frame[list(ALL_COLUMNS)].apply(pd.to_numeric, errors="coerce")
        if values.isna().any().any() or not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any():
            raise ValueError(f"{name} metric values must be finite positive numbers")


def merge_archive_connected_metrics(
    archive: pd.DataFrame,
    connected: pd.DataFrame,
    *,
    model_path: str | Path = MODEL_PATH,
    dependency_receipt_path: str | Path = DEPENDENCY_RECEIPT,
) -> tuple[pd.DataFrame, float, int]:
    """Validate and merge a connected period-end tail onto archive create-time semantics.

    Evidence established that decision-relevant OI and top-position endpoint rows
    correspond to archive ``create_time + 5m``. The connected tail is therefore
    mapped back five minutes only in the normalized decision matrix; raw payloads
    and hashes stay untouched. Taker raw rows remain mandatory upstream for common
    cadence, provenance and freshness, but unresolved taker values are quarantined
    as NaN in the live portion of this decision matrix rather than assigned an
    unproved archive-equivalent meaning.
    """
    proof = validate_dependency_proof(
        model_path=model_path, dependency_receipt_path=dependency_receipt_path
    )
    _validate_frames(archive, connected)

    canonical = connected[list(ALL_COLUMNS)].astype(float).copy()
    canonical.index = canonical.index - pd.Timedelta(minutes=ARCHIVE_TO_CONNECTED_OFFSET_MINUTES)
    if not canonical.index.is_unique or not canonical.index.is_monotonic_increasing:
        raise ValueError("Canonical connected metric index invalid after evidenced offset")

    overlap = archive.index.intersection(canonical.index)
    if len(overlap) == 0:
        raise ValueError("No evidenced archive/live overlap after timestamp mapping")

    exact_mismatches = {}
    for col in DECISION_EXACT_COLUMNS:
        a = archive.loc[overlap, col].astype(float).to_numpy()
        b = canonical.loc[overlap, col].astype(float).to_numpy()
        bad = ~np.isclose(a, b, rtol=1e-12, atol=1e-12, equal_nan=False)
        exact_mismatches[col] = int(bad.sum())
        if bad.any():
            raise ValueError(f"Decision-relevant archive/live overlap mismatch: {col}")

    top_col = DECISION_PRECISION_COLUMNS[0]
    live_top = canonical.loc[overlap, top_col].astype(float).to_numpy()
    scaled = live_top * (10 ** TOP_POSITION_CONNECTED_DECIMALS)
    if not np.allclose(scaled, np.round(scaled), rtol=0.0, atol=1e-8):
        raise ValueError("Top-position connected precision contract changed")
    archive_top = archive.loc[overlap, top_col].astype(float).to_numpy()
    top_delta = np.abs(archive_top - live_top)
    if (top_delta > TOP_POSITION_HALF_LSU + 1e-12).any():
        raise ValueError("Decision-relevant archive/live overlap mismatch: top-position ratio")

    # Do not invent a taker archive-equivalent value while its source semantics are unresolved.
    canonical.loc[:, "sum_taker_long_short_vol_ratio"] = np.nan

    first_live = canonical.index.min()
    left = archive.loc[archive.index < first_live, list(ALL_COLUMNS)].astype(float)
    merged = pd.concat([left, canonical]).sort_index()
    if not merged.index.is_unique:
        raise ValueError("Merged metric index duplicate")
    gap = merged.index.to_series().diff().dropna().max()
    if gap > pd.Timedelta(minutes=10):
        raise ValueError("Metric warmup/live gap too large")

    merged.attrs["live_parity_contract"] = {
        "schema": "eth-forward-live-parity-contract-v1",
        **proof,
        "archive_create_time_to_connected_period_end_offset_minutes": ARCHIVE_TO_CONNECTED_OFFSET_MINUTES,
        "decision_exact_columns": list(DECISION_EXACT_COLUMNS),
        "decision_precision_columns": {
            top_col: {
                "connected_decimal_places": TOP_POSITION_CONNECTED_DECIMALS,
                "max_abs_delta": float(top_delta.max()),
                "half_lsu": TOP_POSITION_HALF_LSU,
            }
        },
        "archive_live_overlap_rows": len(overlap),
        "decision_exact_mismatches": exact_mismatches,
        "non_decision_columns_value_parity_asserted": False,
        "taker_value_semantics_resolved": False,
        "taker_live_values_quarantined_from_decision_matrix": True,
        "full_taker_stream_required_upstream": True,
        "raw_values_rewritten": False,
        "gate_promotion": False,
    }
    return merged, float(gap / pd.Timedelta(minutes=1)), len(overlap)
