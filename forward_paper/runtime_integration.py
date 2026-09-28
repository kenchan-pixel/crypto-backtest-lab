"""Integrated durable PAPER-ONLY runtime hooks for costs and weekly AI budget.

This module is the commissioning/production persistence entrypoint around the
already-verified pure runtime primitives.  It adds two atomic sidecar hooks:

* every completed paper exit is followed, in the same in-memory transition,
  by the BASE/STRESS cost comparison for that SAME saved parent opportunity;
* every genuine weekly decision is followed, in the same transition, by the
  separate assumed AI operating-budget sidecar.

Only the fully assembled next state is offered to the CAS store.  A sidecar
failure or stale CAS therefore cannot durably leave half of either transition.
No market network client, brokerage/order/account API, arming logic, retraining
or strategy search exists here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from forward_paper.core import append, fresh_state, set_decision, stamp
from forward_paper.runtime_costs import (
    append_ai_operating_budget_sidecar,
    append_cost_comparison_sidecar,
)
from forward_paper.runtime_cycle import (
    CycleResult,
    _fixture_signal,
    _prepare_observing_fixture,
    process_cycle,
)
from forward_paper.runtime_store import CASConflict, encode_state, load_state, write_state_cas


def _ledger_event(state: dict[str, Any], event_id: str) -> dict[str, Any]:
    for row in state.get("ledger", []):
        if row.get("event_id") == event_id:
            return row
    raise ValueError(f"Required durable event not found: {event_id}")


def process_integrated_cycle(
    state: dict[str, Any],
    *,
    now: str,
    quote: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
) -> CycleResult:
    """Run one paper cycle and attach cost sidecar to a completed exit.

    The underlying runtime preserves exits-first and signal-before-fill ordering.
    If cost-sidecar construction fails, this function raises before returning a
    next state, so callers using ``apply_cycle_cas`` have nothing partial to
    persist.
    """
    result = process_cycle(state, now=now, quote=quote, signal=signal)
    if result.action != "exit":
        return result

    exit_event = result.state.get("ledger", [])[-1]
    event_id = str(exit_event.get("event_id", ""))
    if exit_event.get("kind") != "paper_exit" or not event_id.startswith("exit:"):
        raise ValueError("Completed runtime exit is missing its durable parent event")
    opportunity_id = event_id.split(":", 1)[1]
    with_cost = append_cost_comparison_sidecar(result.state, opportunity_id)
    return CycleResult(state=with_cost, action=result.action, entry_evaluated=result.entry_evaluated)


def _expected_weekly_decision(
    *,
    decision_id: str,
    committed_at: str,
    information_cutoff: str,
    effective_at: str,
    expires_at: str,
    ai_weight: float,
    simple_weight: float,
    packet_sha256: str,
    rationale: str,
) -> dict[str, Any]:
    return {
        "event_id": decision_id,
        "kind": "weekly_decision",
        "committed_at": committed_at,
        "information_cutoff": information_cutoff,
        "effective_at": effective_at,
        "expires_at": expires_at,
        "weights": {"AI_WEEKLY": ai_weight, "SIMPLE_WEEKLY": simple_weight, "HALF": 0.5},
        "packet_sha256": packet_sha256,
        "rationale": rationale,
    }


def commit_weekly_decision(
    state: dict[str, Any],
    *,
    decision_id: str,
    committed_at: str,
    information_cutoff: str,
    effective_at: str,
    expires_at: str,
    ai_weight: float,
    simple_weight: float,
    packet_sha256: str,
    rationale: str,
) -> dict[str, Any]:
    """Commit weekly decision and AI-budget sidecar as one logical transition.

    Exact replay of an already committed decision is idempotent.  Reusing the
    same decision ID with different content fails closed.
    """
    expected = _expected_weekly_decision(
        decision_id=decision_id,
        committed_at=committed_at,
        information_cutoff=information_cutoff,
        effective_at=effective_at,
        expires_at=expires_at,
        ai_weight=ai_weight,
        simple_weight=simple_weight,
        packet_sha256=packet_sha256,
        rationale=rationale,
    )

    if decision_id in state.get("processed_events", {}):
        existing = _ledger_event(state, decision_id)
        durable_payload = {k: v for k, v in existing.items() if k not in ("previous_sha", "sha256")}
        if durable_payload != expected or state.get("decision") != expected:
            raise ValueError("Conflicting repeated weekly decision")
        return append_ai_operating_budget_sidecar(state, decision_id)

    decided = set_decision(
        state,
        decision_id=decision_id,
        committed_at=committed_at,
        information_cutoff=information_cutoff,
        effective_at=effective_at,
        expires_at=expires_at,
        ai_weight=ai_weight,
        simple_weight=simple_weight,
        packet_sha256=packet_sha256,
        rationale=rationale,
    )
    return append_ai_operating_budget_sidecar(decided, decision_id)


def apply_cycle_cas(
    state_path: str | Path,
    *,
    expected_content_sha256: str,
    now: str,
    quote: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
):
    """CAS-persist one fully integrated runtime cycle."""
    snapshot = load_state(state_path)
    if snapshot.content_sha256 != expected_content_sha256:
        raise CASConflict(
            f"stale runtime state: expected {expected_content_sha256}, current {snapshot.content_sha256}"
        )
    next_state = process_integrated_cycle(snapshot.state, now=now, quote=quote, signal=signal).state
    return write_state_cas(state_path, next_state, expected_content_sha256=expected_content_sha256)


def commit_weekly_decision_cas(
    state_path: str | Path,
    *,
    expected_content_sha256: str,
    decision_id: str,
    committed_at: str,
    information_cutoff: str,
    effective_at: str,
    expires_at: str,
    ai_weight: float,
    simple_weight: float,
    packet_sha256: str,
    rationale: str,
):
    """CAS-persist weekly decision + AI-budget sidecar atomically."""
    snapshot = load_state(state_path)
    if snapshot.content_sha256 != expected_content_sha256:
        raise CASConflict(
            f"stale runtime state: expected {expected_content_sha256}, current {snapshot.content_sha256}"
        )
    next_state = commit_weekly_decision(
        snapshot.state,
        decision_id=decision_id,
        committed_at=committed_at,
        information_cutoff=information_cutoff,
        effective_at=effective_at,
        expires_at=expires_at,
        ai_weight=ai_weight,
        simple_weight=simple_weight,
        packet_sha256=packet_sha256,
        rationale=rationale,
    )
    return write_state_cas(state_path, next_state, expected_content_sha256=expected_content_sha256)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decision_fixture_times(anchor: str) -> dict[str, str]:
    a = stamp(anchor)
    cutoff = a + timedelta(minutes=1)
    commit = a + timedelta(minutes=2)
    effect = commit.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    expiry = effect + timedelta(days=7)
    return {
        "information_cutoff": cutoff.isoformat(),
        "committed_at": commit.isoformat(),
        "effective_at": effect.isoformat(),
        "expires_at": expiry.isoformat(),
    }


def run_commissioning_probe(
    source_state_path: str | Path,
    public_evidence_path: str | Path,
    work_dir: str | Path,
) -> dict[str, Any]:
    """Validate integrated hooks on isolated copies; never mutate source state."""
    source_path = Path(source_state_path)
    evidence_path = Path(public_evidence_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    source_before = load_state(source_path)
    source_state = source_before.state
    if source_state.get("status") != "COMMISSIONING":
        raise ValueError("Integration commissioning requires COMMISSIONING source state")
    if source_state.get("execution_ready") is not False or source_state.get("performance_started_at") is not None:
        raise ValueError("Source runtime unexpectedly armed or started")
    if source_state.get("decision") is not None:
        raise ValueError("Genuine initial weekly decision already exists")
    if any(int(a.get("trades", 0)) for a in source_state["accounts"].values()):
        raise ValueError("Source runtime unexpectedly contains paper trades")

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    quotes = evidence.get("quotes", [])
    if evidence.get("read_only") is not True or evidence.get("orders_or_account_data_requested") is not False:
        raise ValueError("Public evidence is not marked read-only")
    if evidence.get("symbol") != "ETHUSDT" or len(quotes) != 2:
        raise ValueError("Expected exactly two ETHUSDT public quotes")
    q1, q2 = quotes
    if q1.get("symbol") != "ETHUSDT" or q2.get("symbol") != "ETHUSDT":
        raise ValueError("Unexpected public quote symbol")
    if not stamp(q1["observed_at"]) < stamp(q2["observed_at"]):
        raise ValueError("Public quote evidence is not strictly ordered")

    # Exit path: create an isolated engineering-only open position using the two
    # real public quotes, then settle a synthetic 24h-due quote solely to exercise
    # atomic exit+cost persistence.  It is never a forward result.
    exit_dir = work / "exit_atomic"
    exit_dir.mkdir(parents=True, exist_ok=True)
    exit_path = exit_dir / "state.json"
    fixture = _prepare_observing_fixture(source_state, q1["observed_at"])
    signal = _fixture_signal(q1["observed_at"])
    recorded = process_cycle(fixture, now=q1["observed_at"], quote=None, signal=signal).state
    opened = process_cycle(recorded, now=q2["observed_at"], quote=q2, signal=signal).state
    exit_path.write_bytes(encode_state(opened))
    exit_before = load_state(exit_path)
    due = stamp(opened["parent_busy_until"])
    exit_quote = {
        "symbol": "ETHUSDT",
        "price": q2["price"],
        "observed_at": (due + timedelta(seconds=30)).isoformat(),
        "source": "commissioning same-price synthetic due-exit fixture; not future market evidence",
        "evidence_id": "runtime-integration-synthetic-exit",
    }
    exit_written = apply_cycle_cas(
        exit_path,
        expected_content_sha256=exit_before.content_sha256,
        now=exit_quote["observed_at"],
        quote=exit_quote,
        signal={"id": "must-not-run"},
    )
    exit_restart = load_state(exit_path)
    exit_event = _ledger_event(exit_restart.state, f"exit:{signal['id']}")
    cost_event = _ledger_event(exit_restart.state, f"sidecar:cost:{signal['id']}")
    exit_index = next(i for i, row in enumerate(exit_restart.state["ledger"]) if row.get("event_id") == exit_event["event_id"])
    cost_index = next(i for i, row in enumerate(exit_restart.state["ledger"]) if row.get("event_id") == cost_event["event_id"])
    cost_after_exit = cost_index == exit_index + 1
    same_parent = cost_event.get("opportunity_id") == signal["id"] and cost_event.get("exit_event_sha256") == exit_event["sha256"]
    base_matches_core = all(
        abs(float(cost_event["scenarios"]["BASE"]["accounts"][arm]["post_cash"]) - float(exit_restart.state["accounts"][arm]["cash"])) < 1e-9
        for arm in ("AI_WEEKLY", "SIMPLE_WEEKLY", "HALF")
    )

    # Weekly decision path: decision + budget must become durable together and
    # exact replay must be idempotent.
    decision_dir = work / "decision_atomic"
    decision_dir.mkdir(parents=True, exist_ok=True)
    decision_path = decision_dir / "state.json"
    shutil.copyfile(source_path, decision_path)
    decision_before = load_state(decision_path)
    times = _decision_fixture_times(q2["observed_at"])
    decision_args = {
        "decision_id": "commissioning-integrated-weekly-decision-fixture",
        **times,
        "ai_weight": 0.0,
        "simple_weight": 0.5,
        "packet_sha256": hashlib.sha256(b"commissioning-integrated-weekly-packet").hexdigest(),
        "rationale": "isolated commissioning fixture only; not a genuine weekly allocation",
    }
    decision_written = commit_weekly_decision_cas(
        decision_path,
        expected_content_sha256=decision_before.content_sha256,
        **decision_args,
    )
    decision_restart = load_state(decision_path)
    decision_event = _ledger_event(decision_restart.state, decision_args["decision_id"])
    budget_event = _ledger_event(decision_restart.state, f"sidecar:ai-budget:{decision_args['decision_id']}")
    decision_index = next(i for i, row in enumerate(decision_restart.state["ledger"]) if row.get("event_id") == decision_event["event_id"])
    budget_index = next(i for i, row in enumerate(decision_restart.state["ledger"]) if row.get("event_id") == budget_event["event_id"])
    decision_budget_adjacent = budget_index == decision_index + 1
    replayed = commit_weekly_decision_cas(
        decision_path,
        expected_content_sha256=decision_written.content_sha256,
        **decision_args,
    )
    replay_idempotent = replayed.semantic_sha256 == decision_restart.semantic_sha256

    # Stale writer: another event wins first.  The stale integrated transition
    # must persist neither its weekly decision nor its budget sidecar.  Then a
    # caller may explicitly reread and retry from the new state.
    conflict_dir = work / "stale_conflict"
    conflict_dir.mkdir(parents=True, exist_ok=True)
    conflict_path = conflict_dir / "state.json"
    shutil.copyfile(source_path, conflict_path)
    stale = load_state(conflict_path)
    winner_state = append(
        stale.state,
        {"event_id": "commissioning-concurrent-writer", "kind": "commissioning_probe", "scope": "isolated_copy_only"},
    )
    write_state_cas(conflict_path, winner_state, expected_content_sha256=stale.content_sha256)
    stale_rejected = False
    try:
        commit_weekly_decision_cas(conflict_path, expected_content_sha256=stale.content_sha256, **decision_args)
    except CASConflict:
        stale_rejected = True
    after_conflict = load_state(conflict_path)
    no_partial_after_conflict = (
        decision_args["decision_id"] not in after_conflict.state.get("processed_events", {})
        and f"sidecar:ai-budget:{decision_args['decision_id']}" not in after_conflict.state.get("processed_events", {})
    )
    retried = commit_weekly_decision_cas(
        conflict_path,
        expected_content_sha256=after_conflict.content_sha256,
        **decision_args,
    )
    retry_has_both = (
        decision_args["decision_id"] in retried.state.get("processed_events", {})
        and f"sidecar:ai-budget:{decision_args['decision_id']}" in retried.state.get("processed_events", {})
    )

    source_after = load_state(source_path)
    source_unchanged = source_after.content_sha256 == source_before.content_sha256
    safety_preserved = all(
        decision_restart.state.get(key) == source_state.get(key)
        for key in ("status", "execution_ready", "performance_started_at", "live_orders_allowed", "model_sha256", "accounts", "parent_busy_until")
    )

    checks = {
        "public_quote_pair_strictly_ordered": True,
        "exit_and_cost_sidecar_persisted_in_one_cas": exit_written.content_sha256 == exit_restart.content_sha256,
        "cost_sidecar_immediately_follows_saved_exit": cost_after_exit,
        "cost_sidecar_references_same_parent_and_exit_hash": same_parent,
        "base_cost_sidecar_matches_core_exit_accounting": base_matches_core,
        "decision_and_ai_budget_persisted_in_one_cas": decision_written.content_sha256 == decision_restart.content_sha256,
        "ai_budget_immediately_follows_weekly_decision": decision_budget_adjacent,
        "exact_weekly_decision_replay_is_idempotent": replay_idempotent,
        "stale_integrated_writer_rejected": stale_rejected,
        "stale_conflict_leaves_no_partial_decision_or_budget": no_partial_after_conflict,
        "explicit_reread_retry_persists_both_decision_and_budget": retry_has_both,
        "commissioning_safety_fields_preserved": safety_preserved,
        "source_runtime_bytes_unchanged": source_unchanged,
    }
    if not all(checks.values()):
        raise AssertionError(f"runtime integration commissioning probe failed: {checks}")

    return {
        "schema": "eth-paper-runtime-sidecar-integration-commissioning-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "bounded_step": "atomic runtime wiring for exit cost sidecar and weekly-decision AI-budget sidecar",
        "source_runtime": {
            "path": str(source_path),
            "content_sha256": source_before.content_sha256,
            "semantic_sha256": source_before.semantic_sha256,
            "status": source_state["status"],
            "execution_ready": source_state["execution_ready"],
            "performance_started_at": source_state["performance_started_at"],
            "paper_closed_trades": sum(int(a.get("trades", 0)) for a in source_state["accounts"].values()),
        },
        "public_evidence": {
            "path": str(evidence_path),
            "sha256": _sha256_file(evidence_path),
            "source": evidence.get("source"),
            "tool_operation": evidence.get("tool_operation"),
            "prices": [q1.get("price"), q2.get("price")],
            "elapsed_seconds": (stamp(q2["observed_at"]) - stamp(q1["observed_at"])).total_seconds(),
            "read_only": True,
            "orders_or_account_data_requested": False,
        },
        "checks": checks,
        "engineering_fixture": {
            "isolated_synthetic_threshold_signal": True,
            "isolated_synthetic_24h_exit_quote": True,
            "isolated_synthetic_weekly_decision": True,
            "forward_opportunity_claimed": False,
            "forward_trade_claimed": False,
            "genuine_weekly_decision_claimed": False,
        },
        "actual_runtime_state_mutated": False,
        "actual_runtime_paper_trades_created": 0,
        "real_orders_created": 0,
        "order_account_endpoints_used": False,
        "gate_promotion": False,
        "gate_effect": "none; integrated persistence hooks are commissioned but genuine initial weekly decisions remain absent and runtime must stay unarmed",
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Commission integrated paper-runtime sidecar persistence on isolated state copies")
    parser.add_argument("--state", required=True)
    parser.add_argument("--public-evidence", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    receipt = run_commissioning_probe(args.state, args.public_evidence, args.work_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
