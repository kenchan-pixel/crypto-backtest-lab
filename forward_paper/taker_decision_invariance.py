"""Bounded proof that the unresolved taker metric cannot change frozen decisions.

This commissioning validator does not relax any source gate. It proves dependency
invariance only: perturbing the already-persisted real connected taker series must
not change frozen regimes, catalysts, scores, threshold decisions, or the parent
opportunity stream. No fill/account/order logic is present here.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import features as ff
from .model import load

EXPECTED_TAKER_SHA256 = "f82b99061a41b6ff05733e27060f9602ec0396483ba494c84fd762837791b62c"
REQUIRED_STATE_D_INPUTS = {"funding_per_hour", "oi_logchange_24h", "top_position_ratio"}
TAKER_DERIVED_COLUMNS = {"taker_ratio", "taker_ratio_change6h"}
STATE_COLUMNS = [
    "trend_30d", "trend_7d", "vol_state", "cross_asset_state",
    "funding_state", "oi_state", "positioning_state",
]


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state_derivative_inputs() -> set[str]:
    """Extract D.<name> dependencies directly from the frozen state builder."""
    tree = ast.parse(inspect.getsource(ff.states))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "D":
            out.add(node.attr)
    return out


def model_mentions_taker(model: dict) -> list[str]:
    names: list[str] = []
    for key in ("categorical_columns", "numeric_columns", "feature_columns"):
        for value in model.get(key, []):
            if "taker" in str(value).lower():
                names.append(f"{key}:{value}")
    return names


def _history(real_taker_rows: list[dict], periods: int = 1100):
    idx = pd.date_range("2026-08-08 00:00", periods=periods, freq="h", tz=ff.TZ)
    x = np.arange(periods, dtype=float)
    eth_close = 2850.0 * np.exp(0.00018 * x + 0.018 * np.sin(x / 31.0) + 0.006 * np.sin(x / 7.0))
    btc_close = 88000.0 * np.exp(0.00012 * x + 0.014 * np.sin(x / 37.0) - 0.004 * np.sin(x / 11.0))
    eth = pd.DataFrame({"close": eth_close}, index=idx)
    btc = pd.DataFrame({"close": btc_close}, index=idx)

    top_position = np.exp(0.16 * np.sin(x / 43.0) + 0.05 * np.cos(x / 9.0))
    d = pd.DataFrame(index=idx)
    d["funding_per_hour"] = 0.00001 + 0.000025 * np.sin(x / 29.0)
    d["oi_logchange_24h"] = 0.035 * np.sin(x / 23.0) + 0.008 * np.cos(x / 5.0)
    d["top_position_ratio"] = np.log(top_position)

    ratios = np.array([float(r["buySellRatio"]) for r in real_taker_rows], dtype=float)
    if len(ratios) < 10 or not np.isfinite(ratios).all() or (ratios <= 0).any():
        raise ValueError("Persisted connected taker series is invalid")
    tiled = np.resize(np.log(ratios), periods)
    d["taker_ratio"] = tiled
    d["taker_ratio_change6h"] = d["taker_ratio"] - d["taker_ratio"].shift(6)
    d["top_account_ratio"] = 0.1 * np.sin(x / 17.0)
    d["top_account_ratio_change6h"] = d["top_account_ratio"] - d["top_account_ratio"].shift(6)
    d["all_account_ratio"] = 0.08 * np.cos(x / 19.0)
    d["all_account_ratio_change6h"] = d["all_account_ratio"] - d["all_account_ratio"].shift(6)
    return eth, btc, d


def _candidate_signature(records: list[dict]):
    out = []
    for r in records:
        out.append((
            r["catalyst_at"], r["information_cutoff"], r["catalyst_type"],
            json.dumps(r["features"], sort_keys=True, separators=(",", ":")),
            float(r["prediction"]), bool(r["passes_frozen_threshold"]),
        ))
    return out


def _parent_stream(regimes: pd.DataFrame, macro: list[dict], model: dict, cuts: pd.DatetimeIndex):
    parent = []
    busy_until = None
    for cut in cuts:
        candidates = ff.candidates_at(regimes, macro, cut, model)
        passing = [r for r in candidates if r["passes_frozen_threshold"]]
        if not passing:
            continue
        chosen = passing[0]  # candidates_at is deterministic score-descending order.
        if busy_until is not None and cut <= busy_until:
            continue
        parent.append((cut.isoformat(), chosen["catalyst_type"], float(chosen["prediction"])))
        busy_until = cut + pd.Timedelta(hours=24)
    return parent


def validate(taker_path: str | Path, model_path: str | Path) -> dict:
    taker_path = Path(taker_path)
    taker_sha = sha256_file(taker_path)
    if taker_sha != EXPECTED_TAKER_SHA256:
        raise AssertionError("Persisted connected taker hash changed")
    rows = json.loads(taker_path.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError("Connected taker source is empty")

    model = load(model_path)
    model_taker_refs = model_mentions_taker(model)
    if model_taker_refs:
        raise AssertionError("Frozen model unexpectedly contains taker feature")
    deps = state_derivative_inputs()
    if deps != REQUIRED_STATE_D_INPUTS:
        raise AssertionError(f"Frozen state dependency set changed: {sorted(deps)}")
    if deps & TAKER_DERIVED_COLUMNS:
        raise AssertionError("Taker unexpectedly enters frozen regime state")

    eth, btc, base_d = _history(rows)
    variant_d = base_d.copy()
    # Deliberately destroy both level and six-hour change semantics while leaving
    # every actual frozen decision dependency byte-for-byte unchanged.
    n = len(variant_d)
    variant_d["taker_ratio"] = np.linspace(-7.0, 7.0, n)[::-1]
    variant_d["taker_ratio_change6h"] = np.sin(np.arange(n, dtype=float) / 2.0) * 20.0

    base = ff.states(eth, btc, base_d)
    variant = ff.states(eth, btc, variant_d)
    comparable = base.index.intersection(variant.index)
    state_mismatches = 0
    for c in STATE_COLUMNS + ["close", "return_30d", "return_7d", "relative_return_24h"]:
        a = base.loc[comparable, c]
        b = variant.loc[comparable, c]
        if pd.api.types.is_numeric_dtype(a):
            state_mismatches += int((~np.isclose(a.to_numpy(float), b.to_numpy(float), rtol=0, atol=0, equal_nan=True)).sum())
        else:
            state_mismatches += int((a.astype(str).to_numpy() != b.astype(str).to_numpy()).sum())
    if state_mismatches:
        raise AssertionError("Taker perturbation changed frozen regime state")

    valid = base.index[base.index >= base.index[800]]
    # Add deterministic macro catalysts to prove taker cannot alter macro candidate paths either.
    macro = []
    for t, indicator, sign in [
        (valid[24], "diagnostic_a", "positive"),
        (valid[96], "diagnostic_b", "negative"),
        (valid[168], "diagnostic_c", "inline"),
    ]:
        macro.append({"usable_at": t.isoformat(), "indicator": indicator, "sign": sign})

    cuts = valid[6:]
    candidate_mismatches = 0
    threshold_mismatches = 0
    max_prediction_delta = 0.0
    candidate_count = 0
    catalyst_keys_base = []
    catalyst_keys_variant = []
    for cut in cuts:
        a = ff.candidates_at(base, macro, cut, model)
        b = ff.candidates_at(variant, macro, cut, model)
        candidate_count += len(a)
        catalyst_keys_base.extend((r["catalyst_at"], r["catalyst_type"]) for r in a)
        catalyst_keys_variant.extend((r["catalyst_at"], r["catalyst_type"]) for r in b)
        sa, sb = _candidate_signature(a), _candidate_signature(b)
        if len(sa) != len(sb):
            candidate_mismatches += abs(len(sa) - len(sb)) + 1
            continue
        for ra, rb in zip(sa, sb):
            if ra[:4] != rb[:4]:
                candidate_mismatches += 1
            max_prediction_delta = max(max_prediction_delta, abs(ra[4] - rb[4]))
            if ra[5] != rb[5]:
                threshold_mismatches += 1
    catalyst_mismatches = int(catalyst_keys_base != catalyst_keys_variant)
    if candidate_mismatches or threshold_mismatches or max_prediction_delta != 0.0 or catalyst_mismatches:
        raise AssertionError("Taker perturbation changed frozen candidate/score/threshold stream")

    parent_a = _parent_stream(base, macro, model, cuts)
    parent_b = _parent_stream(variant, macro, model, cuts)
    parent_mismatches = int(parent_a != parent_b)
    if parent_mismatches:
        raise AssertionError("Taker perturbation changed parent opportunity stream")

    timestamps = [int(r["timestamp"]) for r in rows]
    return {
        "schema": "eth-forward-taker-decision-invariance-receipt-v1",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Bounded commissioning proof of frozen decision dependency only; unresolved taker archive/live value semantics remain unresolved and no source gate is promoted here.",
        "frozen_model": {
            "sha256": sha256_file(model_path),
            "threshold": float(model["threshold"]),
            "taker_feature_references": model_taker_refs,
        },
        "dependency_proof": {
            "state_derivative_inputs": sorted(deps),
            "taker_derived_columns": sorted(TAKER_DERIVED_COLUMNS),
            "taker_enters_frozen_state": False,
            "taker_enters_frozen_model": False,
        },
        "real_connected_taker_evidence": {
            "path": str(taker_path),
            "sha256": taker_sha,
            "rows": len(rows),
            "first_timestamp_ms": min(timestamps),
            "last_timestamp_ms": max(timestamps),
        },
        "dynamic_invariance": {
            "hourly_rows": len(base),
            "evaluated_confirmation_cuts": len(cuts),
            "state_value_mismatches": state_mismatches,
            "catalyst_stream_mismatches": catalyst_mismatches,
            "candidate_records_evaluated": candidate_count,
            "candidate_feature_mismatches": candidate_mismatches,
            "max_prediction_abs_delta": max_prediction_delta,
            "threshold_decision_mismatches": threshold_mismatches,
            "parent_opportunities": len(parent_a),
            "parent_opportunity_mismatches": parent_mismatches,
        },
        "conclusion": {
            "frozen_decision_invariant_to_taker": True,
            "taker_source_semantics_resolved": False,
            "meaning": "For the frozen model and opportunity logic, taker_ratio/taker_ratio_change6h are computed side columns but are not consumed by regimes, catalysts, sequence features, score, threshold, or parent busy-stream construction.",
            "next_bounded_step": "Define a fail-closed live parity contract that still captures/hashes/checks freshness of the full taker stream but does not require archive/live taker value equivalence for a decision path that provably cannot consume it; retain exact verified contracts for decision-relevant OI/top-position/funding data, then rerun a fresh current causal receipt.",
        },
        "raw_values_rewritten": False,
        "paper_trades_created": 0,
        "gate_promotion": False,
        "performance_started": False,
        "order_or_account_endpoints_used": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--taker", required=True)
    p.add_argument("--model", default="forward_paper/model.json")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    receipt = validate(a.taker, a.model)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    print(json.dumps(receipt, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
