"""Paper-only runtime cycle ordering and commissioning validation.

No network, broker, account, wallet, balance or order calls live here. External
market observations are supplied as already-persisted evidence. The production
ordering contract is deliberately small:

1. service a due exit before considering any new opportunity;
2. persist a causal signal record before an entry fill can be applied;
3. require the fill quote to be genuinely observed after the signal record;
4. make restart/replay idempotent through existing append-only event IDs.

Gap-event persistence and base/stress cost sidecars are separate commissioning
steps and are intentionally not claimed by this module.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from forward_paper.core import MODEL_SHA, append, close_due, open_opportunity, stamp
from forward_paper.runtime_store import encode_state, load_state


@dataclass(frozen=True)
class CycleResult:
    state: dict[str, Any]
    action: str
    entry_evaluated: bool


def _has_open_position(state: dict[str, Any]) -> bool:
    return any(account.get("open") is not None for account in state["accounts"].values())


def due_exit_pending(state: dict[str, Any], now: str) -> bool:
    busy_until = state.get("parent_busy_until")
    return bool(busy_until and _has_open_position(state) and stamp(now) >= stamp(busy_until))


def _signal_event(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": f"signal:{signal['id']}",
        "kind": "signal_record",
        "signal": copy.deepcopy(signal),
    }


def process_cycle(
    state: dict[str, Any],
    *,
    now: str,
    quote: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
) -> CycleResult:
    """Apply one paper-runtime cycle without any external side effects.

    If a due exit exists, it is the only trade action allowed in the cycle. A
    missing exit quote fails closed so a new entry can never leapfrog an exit.
    If no exit is due, a supplied signal is appended before any fill is applied.
    Replaying a previously completed entry is a no-op rather than a duplicate.
    """
    if due_exit_pending(state, now):
        if quote is None:
            raise ValueError("Due exit requires actual quote evidence before any new entry")
        closed = close_due(state, quote, now)
        return CycleResult(state=closed, action="exit", entry_evaluated=False)

    if signal is None:
        return CycleResult(state=copy.deepcopy(state), action="noop", entry_evaluated=False)

    if signal.get("model_sha256") != MODEL_SHA:
        raise ValueError("Changed model prohibited")

    recorded = append(state, _signal_event(signal))
    entry_event_id = f"entry:{signal['id']}"
    if entry_event_id in recorded.get("processed_events", {}):
        return CycleResult(state=recorded, action="entry_already_processed", entry_evaluated=False)

    if quote is None:
        return CycleResult(state=recorded, action="signal_recorded_fill_pending", entry_evaluated=True)

    filled = open_opportunity(recorded, signal, quote, now)
    return CycleResult(state=filled, action="entry", entry_evaluated=True)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_signal(first_quote_time: str) -> dict[str, Any]:
    first = stamp(first_quote_time)
    cutoff = first - timedelta(minutes=5)
    return {
        "id": "commissioning-actual-later-quote-fixture",
        "model_sha256": MODEL_SHA,
        "information_cutoff": cutoff.isoformat(),
        "recorded_at": first.isoformat(),
        "passes_frozen_threshold": True,
        "prediction": 0.0115,
        "evidence_sha256": hashlib.sha256(b"commissioning-synthetic-signal-fixture").hexdigest(),
        "fixture_only": True,
    }


def _prepare_observing_fixture(source_state: dict[str, Any], first_quote_time: str) -> dict[str, Any]:
    """Create an isolated engineering fixture without manufacturing gate receipts."""
    s = copy.deepcopy(source_state)
    first = stamp(first_quote_time)
    s["status"] = "OBSERVING"
    s["execution_ready"] = True
    s["performance_started_at"] = (first - timedelta(hours=2)).isoformat()
    s["decision"] = {
        "event_id": "commissioning-weekly-decision-fixture",
        "kind": "weekly_decision_fixture",
        "committed_at": (first - timedelta(hours=2)).isoformat(),
        "information_cutoff": (first - timedelta(hours=3)).isoformat(),
        "effective_at": (first - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat(),
        "expires_at": (first + timedelta(days=7)).isoformat(),
        "weights": {"AI_WEEKLY": 1.0, "SIMPLE_WEEKLY": 1.0, "HALF": 0.5},
        "packet_sha256": hashlib.sha256(b"commissioning-decision-fixture").hexdigest(),
        "rationale": "isolated engineering fixture only",
        "fixture_only": True,
    }
    return s


def run_commissioning_probe(
    source_state_path: str | Path,
    quote_pair_path: str | Path,
    work_dir: str | Path,
) -> dict[str, Any]:
    """Validate exits-first and signal-before-fill ordering on an isolated copy.

    Two connected public Binance quotes are used exactly as persisted. The
    synthetic threshold-passing signal and observing state exist only to
    exercise engineering paths; they are never written to the source runtime
    and never count as a forward opportunity or trade.
    """
    source_path = Path(source_state_path)
    quote_path = Path(quote_pair_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    source_before = load_state(source_path)
    if source_before.state.get("status") != "COMMISSIONING":
        raise ValueError("Runtime-cycle commissioning probe requires COMMISSIONING source state")
    if source_before.state.get("execution_ready") is not False:
        raise ValueError("Source runtime unexpectedly execution-ready")
    if source_before.state.get("performance_started_at") is not None:
        raise ValueError("Source runtime unexpectedly has a performance start")

    payload = json.loads(quote_path.read_text(encoding="utf-8"))
    quotes = payload.get("quotes", [])
    if payload.get("read_only") is not True or payload.get("orders_or_account_data_requested") is not False:
        raise ValueError("Quote evidence is not marked public read-only")
    if len(quotes) != 2:
        raise ValueError("Expected exactly two connected quote observations")
    q1, q2 = quotes
    if q1.get("symbol") != "ETHUSDT" or q2.get("symbol") != "ETHUSDT":
        raise ValueError("Unexpected quote symbol")
    if not stamp(q1["observed_at"]) < stamp(q2["observed_at"]):
        raise ValueError("Second connected quote is not later than the first")

    isolated = work / "state.json"
    shutil.copyfile(source_path, isolated)
    fixture = _prepare_observing_fixture(source_before.state, q1["observed_at"])
    isolated.write_bytes(encode_state(fixture))

    signal = _fixture_signal(q1["observed_at"])
    entry_result = process_cycle(fixture, now=q2["observed_at"], quote=q2, signal=signal)
    isolated.write_bytes(encode_state(entry_result.state))

    entry_ledger = entry_result.state["ledger"]
    signal_index = next(i for i, row in enumerate(entry_ledger) if row.get("event_id") == f"signal:{signal['id']}")
    entry_index = next(i for i, row in enumerate(entry_ledger) if row.get("event_id") == f"entry:{signal['id']}")
    signal_before_entry = signal_index < entry_index
    actual_later_quote_used = stamp(q2["observed_at"]) > stamp(signal["recorded_at"])

    restarted = load_state(isolated)
    replay = process_cycle(restarted.state, now=q2["observed_at"], quote=q2, signal=signal)
    restart_idempotent = replay.state == restarted.state and replay.action == "entry_already_processed"

    # Separate isolated exits-first fixture. The quote here is synthetic because
    # a real 24h exit cannot be observed during a bounded commissioning run.
    exit_state = copy.deepcopy(entry_result.state)
    due = stamp(exit_state["parent_busy_until"])
    exit_quote = {
        "symbol": "ETHUSDT",
        "price": q2["price"],
        "observed_at": (due + timedelta(seconds=30)).isoformat(),
        "source": "commissioning synthetic due-exit quote fixture",
        "evidence_id": "commissioning-synthetic-exit-quote",
    }
    competing_signal = copy.deepcopy(signal)
    competing_signal["id"] = "commissioning-competing-entry-fixture"
    competing_signal["information_cutoff"] = (due - timedelta(minutes=10)).isoformat()
    competing_signal["recorded_at"] = (due - timedelta(minutes=5)).isoformat()
    exit_result = process_cycle(
        exit_state,
        now=exit_quote["observed_at"],
        quote=exit_quote,
        signal=competing_signal,
    )
    exits_first = (
        exit_result.action == "exit"
        and f"signal:{competing_signal['id']}" not in exit_result.state.get("processed_events", {})
        and f"entry:{competing_signal['id']}" not in exit_result.state.get("processed_events", {})
    )

    source_after = load_state(source_path)
    source_unchanged = source_after.content_sha256 == source_before.content_sha256
    checks = {
        "connected_quote_pair_is_strictly_ordered": True,
        "signal_persisted_before_entry_event": signal_before_entry,
        "actual_second_connected_quote_is_after_signal_record": actual_later_quote_used,
        "restart_replay_is_idempotent": restart_idempotent,
        "due_exit_preempts_competing_new_entry": exits_first,
        "source_runtime_bytes_unchanged": source_unchanged,
    }
    if not all(checks.values()):
        raise AssertionError(f"runtime-cycle commissioning probe failed: {checks}")

    return {
        "schema": "eth-paper-runtime-cycle-commissioning-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "bounded_step": "exits-first orchestration plus signal-before-actual-later-quote ordering",
        "quote_evidence": {
            "path": str(quote_path),
            "sha256": _sha256_file(quote_path),
            "source": payload.get("source"),
            "tool_operation": payload.get("tool_operation"),
            "first_exchange_time_ms": q1.get("exchange_time_ms"),
            "second_exchange_time_ms": q2.get("exchange_time_ms"),
            "elapsed_seconds": (stamp(q2["observed_at"]) - stamp(q1["observed_at"])).total_seconds(),
            "prices": [q1.get("price"), q2.get("price")],
        },
        "checks": checks,
        "engineering_fixture": {
            "synthetic_signal": True,
            "synthetic_armed_state": True,
            "synthetic_due_exit_quote": True,
            "isolated_entry_events": 1,
            "isolated_exit_events": 1,
            "forward_opportunity_claimed": False,
            "forward_trade_claimed": False,
        },
        "actual_runtime_state_mutated": False,
        "actual_runtime_paper_trades_created": 0,
        "real_orders_created": 0,
        "order_account_endpoints_used": False,
        "gate_effect": "none; gap-event persistence, cost sidecars and genuine initial weekly decisions remain incomplete",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Commission paper-runtime cycle ordering on an isolated state copy")
    parser.add_argument("--state", required=True)
    parser.add_argument("--quote-pair", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    receipt = run_commissioning_probe(args.state, args.quote_pair, args.work_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
