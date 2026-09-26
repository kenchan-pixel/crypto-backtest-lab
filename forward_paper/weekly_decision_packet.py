"""Weekly PAPER-ONLY evidence packet and guarded commit path.

No network client, model fitting, signal search, brokerage/account API or arming
logic lives here. Connected public evidence is supplied as an immutable file by
the orchestrator. AI_WEEKLY must be an explicit assistant choice at commit time;
only SIMPLE_WEEKLY is derived mechanically from the approved prior-30d ETH rule.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from forward_paper.core import MODEL_SHA, canonical, stamp
from forward_paper.runtime_integration import commit_weekly_decision_cas
from forward_paper.runtime_store import load_state

HKT = ZoneInfo("Asia/Hong_Kong")
PREDECISION_GATES = ("model_identity", "live_feature_parity", "source_freshness", "accounting_tests")
MAX_COMMIT_EVIDENCE_AGE = timedelta(minutes=20)
DAY_MS = 86_400_000


def _file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_bar(bar: dict[str, Any], name: str) -> tuple[int, int, float]:
    try:
        open_ms = int(bar["open_time_ms"])
        close_ms = int(bar["close_time_ms"])
        close = float(bar["close"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name} bar") from exc
    if close_ms <= open_ms or not math.isfinite(close) or close <= 0:
        raise ValueError(f"Invalid {name} bar")
    return open_ms, close_ms, close


def derive_simple_control(evidence: dict[str, Any]) -> dict[str, Any]:
    """Derive the approved SIMPLE_WEEKLY prior-30d ETH direction control.

    Uses two completed UTC daily Binance spot bars exactly 30 calendar days
    apart. The end bar must already be closed before the connected observation.
    """
    if evidence.get("schema") != "eth-weekly-connected-evidence-v1":
        raise ValueError("Unexpected weekly evidence schema")
    if evidence.get("source") != "Binance connected public read-only market-data tool":
        raise ValueError("Unexpected weekly evidence source")
    if evidence.get("tool_operation") != "get_spot_kline_candlestick_data":
        raise ValueError("Unexpected weekly evidence operation")
    if evidence.get("read_only") is not True or evidence.get("orders_or_account_data_requested") is not False:
        raise ValueError("Weekly evidence is not public read-only")
    query = evidence.get("query_contract") or {}
    if query.get("symbol") != "ETHUSDT" or query.get("interval") != "1d" or query.get("time_zone") != "UTC":
        raise ValueError("Weekly evidence query contract changed")

    observed = stamp(str(evidence["observed_at"]))
    bars = evidence.get("bars") or {}
    start = bars.get("start_30d")
    end = bars.get("end_latest_completed")
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise ValueError("Weekly evidence bars missing")
    start_open, start_close_ms, start_price = _validate_bar(start, "start_30d")
    end_open, end_close_ms, end_price = _validate_bar(end, "end_latest_completed")
    if end_open - start_open != 30 * DAY_MS:
        raise ValueError("Weekly simple-control bars are not exactly 30 days apart")
    if start_close_ms >= end_open:
        raise ValueError("Weekly simple-control bars overlap")
    end_close = stamp(str(evidence["end_bar_close_at"]))
    if int(end_close.timestamp() * 1000) != end_close_ms:
        raise ValueError("End-bar close timestamp mismatch")
    if end_close > observed:
        raise ValueError("Weekly simple-control end bar is not completed")

    ret = end_price / start_price - 1.0
    weight = 1.0 if ret >= 0.0 else 0.5
    return {
        "rule": "prior30d_eth_return>=0 => 1.0 else 0.5; unknown => no new trade",
        "start_open_time_ms": start_open,
        "start_close": start_price,
        "end_open_time_ms": end_open,
        "end_close": end_price,
        "return_30d": ret,
        "direction": "nonnegative" if ret >= 0.0 else "negative",
        "weight": weight,
        "bars_sha256": hashlib.sha256(canonical({"start_30d": start, "end_latest_completed": end})).hexdigest(),
    }


def _same_hkt_week(a: str, b: str) -> bool:
    aa = stamp(a).astimezone(HKT).isocalendar()
    bb = stamp(b).astimezone(HKT).isocalendar()
    return (aa.year, aa.week) == (bb.year, bb.week)


def weekly_commit_eligibility(state: dict[str, Any], when: str) -> dict[str, Any]:
    t = stamp(when).astimezone(HKT)
    reasons: list[str] = []
    if state.get("model_sha256") != MODEL_SHA:
        reasons.append("frozen_model_mismatch")
    gates = state.get("gates") or {}
    for gate in PREDECISION_GATES:
        if gates.get(gate) is not True:
            reasons.append(f"gate_false:{gate}")
    if t.weekday() != 0 or t.hour < 8:
        reasons.append("outside_monday_after_0800_hkt")
    current = state.get("decision")
    if current and _same_hkt_week(str(current["committed_at"]), when):
        reasons.append("weekly_decision_already_committed")
    return {
        "eligible": not reasons,
        "checked_at": when,
        "checked_at_hkt": t.isoformat(),
        "window_contract": "Monday 08:00 HKT or later on Monday; first successful uncommitted run only",
        "reasons": reasons,
    }


def build_weekly_packet(state_path: str | Path, evidence_path: str | Path) -> tuple[dict[str, Any], str]:
    state_snapshot = load_state(state_path)
    evidence_path = Path(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    cutoff = str(evidence["observed_at"])
    simple = derive_simple_control(evidence)
    eligibility = weekly_commit_eligibility(state_snapshot.state, cutoff)
    packet = {
        "schema": "eth-weekly-decision-packet-v1",
        "experiment": "new_forward_paper_observation",
        "paper_only": True,
        "information_cutoff": cutoff,
        "runtime_content_sha256": state_snapshot.content_sha256,
        "frozen_model_sha256": MODEL_SHA,
        "evidence_file_sha256": _file_sha256(evidence_path),
        "readiness_gates": {
            key: bool((state_snapshot.state.get("gates") or {}).get(key))
            for key in PREDECISION_GATES
        },
        "simple_control": simple,
        "ai_control": {
            "weight": None,
            "allowed_weights": [0.0, 0.5, 1.0],
            "rationale": None,
            "must_be_explicit_assistant_choice_at_commit": True,
            "coded_fallback_prohibited": True,
        },
        "half_control": {"weight": 0.5},
        "eligibility": eligibility,
        "genuine_decision_committed": False,
        "execution_ready_changed": False,
        "performance_started_changed": False,
    }
    return packet, hashlib.sha256(canonical(packet)).hexdigest()


def prepare_commit_args(
    state_path: str | Path,
    evidence_path: str | Path,
    *,
    committed_at: str,
    ai_weight: float,
    rationale: str,
) -> dict[str, Any]:
    """Prepare, but do not persist, one genuine weekly decision.

    AI weight/rationale must be supplied explicitly by the assistant on the
    eligible run. SIMPLE_WEEKLY is bound to the immutable evidence packet.
    """
    if ai_weight not in (0.0, 0.5, 1.0):
        raise ValueError("AI_WEEKLY requires an explicit 0/0.5/1 choice")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("AI_WEEKLY requires an explicit rationale")
    packet, packet_sha = build_weekly_packet(state_path, evidence_path)
    snapshot = load_state(state_path)
    eligibility = weekly_commit_eligibility(snapshot.state, committed_at)
    if not eligibility["eligible"]:
        raise ValueError("Weekly decision commit is not eligible: " + ",".join(eligibility["reasons"]))

    cutoff = stamp(packet["information_cutoff"])
    commit = stamp(committed_at)
    age = commit - cutoff
    if age < timedelta(0) or age > MAX_COMMIT_EVIDENCE_AGE:
        raise ValueError("Weekly evidence is stale/future at commit")
    if snapshot.content_sha256 != packet["runtime_content_sha256"]:
        raise ValueError("Runtime state changed after weekly packet construction")

    effect = commit.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    expiry = effect + timedelta(days=7)
    monday = commit.astimezone(HKT).date().isoformat()
    return {
        "expected_content_sha256": snapshot.content_sha256,
        "decision_id": f"weekly:{monday}",
        "committed_at": committed_at,
        "information_cutoff": packet["information_cutoff"],
        "effective_at": effect.isoformat(),
        "expires_at": expiry.isoformat(),
        "ai_weight": float(ai_weight),
        "simple_weight": float(packet["simple_control"]["weight"]),
        "packet_sha256": packet_sha,
        "rationale": rationale.strip(),
    }


def commit_weekly_from_packet_cas(
    state_path: str | Path,
    evidence_path: str | Path,
    *,
    committed_at: str,
    ai_weight: float,
    rationale: str,
):
    """Persist decision+AI-budget atomically; does not arm performance."""
    args = prepare_commit_args(
        state_path,
        evidence_path,
        committed_at=committed_at,
        ai_weight=ai_weight,
        rationale=rationale,
    )
    return commit_weekly_decision_cas(state_path, **args)


def run_commissioning_probe(state_path: str | Path, evidence_path: str | Path) -> dict[str, Any]:
    """Validate today's connected packet while proving it cannot commit off-window."""
    before = load_state(state_path)
    packet, packet_sha = build_weekly_packet(state_path, evidence_path)
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    blocked = False
    block_reason = None
    try:
        prepare_commit_args(
            state_path,
            evidence_path,
            committed_at=str(evidence["observed_at"]),
            ai_weight=0.0,
            rationale="commissioning guard probe only; not a genuine AI allocation",
        )
    except ValueError as exc:
        blocked = True
        block_reason = str(exc)
    after = load_state(state_path)
    source_trades = sum(int(a.get("trades", 0)) for a in before.state.get("accounts", {}).values())
    checks = {
        "connected_public_read_only_evidence": evidence.get("read_only") is True
        and evidence.get("orders_or_account_data_requested") is False,
        "frozen_model_bound": packet["frozen_model_sha256"] == MODEL_SHA,
        "predecision_readiness_gates_true": all(packet["readiness_gates"].values()),
        "simple_control_derived_from_exact_completed_30d_bars": packet["simple_control"]["end_open_time_ms"]
        - packet["simple_control"]["start_open_time_ms"] == 30 * DAY_MS,
        "ai_choice_not_synthesized": packet["ai_control"]["weight"] is None
        and packet["ai_control"]["must_be_explicit_assistant_choice_at_commit"] is True,
        "current_off_window_commit_blocked": packet["eligibility"]["eligible"] is False and blocked,
        "runtime_bytes_unchanged": before.content_sha256 == after.content_sha256,
        "no_genuine_weekly_decision_written": after.state.get("decision") == before.state.get("decision") is None,
        "still_unarmed": after.state.get("execution_ready") is False
        and after.state.get("performance_started_at") is None,
        "zero_paper_trades": source_trades == 0,
    }
    return {
        "schema": "eth-weekly-packet-commissioning-receipt-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "packet_sha256": packet_sha,
        "packet": packet,
        "off_window_block_reason": block_reason,
        "actual_runtime_state_mutated": before.content_sha256 != after.content_sha256,
        "actual_runtime_paper_trades_created": 0,
        "genuine_weekly_decision_committed": False,
        "real_orders_created": 0,
        "order_account_endpoints_used": False,
        "gate_effect": "none; commissioning validation only",
        "next_bounded_step": "On the first eligible Monday run after 08:00 HKT, collect a fresh connected packet, make an explicit AI 0/0.5/1 choice plus rationale, commit AI+simple through CAS, then verify before any arming.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--public-evidence", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    receipt = run_commissioning_probe(args.state, args.public_evidence)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    if not receipt["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
