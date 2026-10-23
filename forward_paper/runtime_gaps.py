"""Append-only paper-runtime gap events for commissioning and live operation.

No network, broker, account, wallet, balance or order calls live here. Missing
or late observations are recorded as durable evidence; this module never
manufactures backdated fills. Entry fill gaps become terminal for that parent
opportunity, while an exit gap may later resolve only with a genuinely observed
late quote through the normal exits-first path.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from forward_paper.core import MODEL_SHA, append, open_opportunity, stamp
from forward_paper.runtime_cycle import _prepare_observing_fixture, due_exit_pending
from forward_paper.runtime_store import encode_state, load_state

ALLOWED_GAPS = {"data_gap", "entry_fill_gap", "exit_fill_gap"}


def _append_once(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Preserve the first immutable event for a stable gap event_id."""
    if event["event_id"] in state.get("processed_events", {}):
        return copy.deepcopy(state)
    return append(state, event)


def record_data_gap(
    state: dict[str, Any],
    *,
    gap_key: str,
    observed_at: str,
    expected_cutoff: str,
    source: str,
    reason: str,
) -> dict[str, Any]:
    stamp(observed_at)
    stamp(expected_cutoff)
    if not gap_key or not source or not reason:
        raise ValueError("Data-gap provenance required")
    event = {
        "event_id": f"gap:data:{gap_key}:{expected_cutoff}",
        "kind": "data_gap",
        "observed_at": observed_at,
        "expected_cutoff": expected_cutoff,
        "source": source,
        "reason": reason,
        "backfill_trade_allowed": False,
    }
    return _append_once(state, event)


def record_entry_fill_gap(
    state: dict[str, Any],
    *,
    signal: dict[str, Any],
    observed_at: str,
    max_latency_minutes: int = 90,
) -> dict[str, Any]:
    now = stamp(observed_at)
    if signal.get("model_sha256") != MODEL_SHA:
        raise ValueError("Changed model prohibited")
    if f"signal:{signal['id']}" not in state.get("processed_events", {}):
        raise ValueError("Signal must be durably recorded before a fill gap")
    if f"entry:{signal['id']}" in state.get("processed_events", {}):
        raise ValueError("Entry already filled; cannot record missing fill")
    cutoff = stamp(signal["information_cutoff"])
    deadline = cutoff + timedelta(minutes=max_latency_minutes)
    if now <= deadline:
        raise ValueError("Entry fill still within allowed latency window")
    event = {
        "event_id": f"gap:entry-fill:{signal['id']}",
        "kind": "entry_fill_gap",
        "observed_at": observed_at,
        "signal_id": signal["id"],
        "information_cutoff": signal["information_cutoff"],
        "fill_deadline": deadline.isoformat(),
        "reason": "no genuine later quote/fill evidence within allowed latency",
        "terminal_for_entry": True,
        "backfill_trade_allowed": False,
    }
    return _append_once(state, event)


def record_due_exit_gap(
    state: dict[str, Any],
    *,
    observed_at: str,
    source: str,
    reason: str = "due exit has no genuine quote evidence yet",
) -> dict[str, Any]:
    if not source or not reason:
        raise ValueError("Exit-gap provenance required")
    if not due_exit_pending(state, observed_at):
        raise ValueError("No due exit to gap-log")
    open_ids = {
        account["open"]["id"]
        for account in state["accounts"].values()
        if account.get("open") is not None
    }
    if len(open_ids) != 1:
        raise ValueError("Inconsistent shared parent opportunity")
    opportunity_id = next(iter(open_ids))
    due_at = state["parent_busy_until"]
    event = {
        "event_id": f"gap:exit-fill:{opportunity_id}:{due_at}",
        "kind": "exit_fill_gap",
        "observed_at": observed_at,
        "opportunity_id": opportunity_id,
        "due_at": due_at,
        "source": source,
        "reason": reason,
        "position_remains_open": True,
        "late_resolution_requires_actual_quote": True,
        "backfill_trade_allowed": False,
    }
    return _append_once(state, event)


def entry_gap_blocks_backfill(state: dict[str, Any], signal_id: str) -> bool:
    return f"gap:entry-fill:{signal_id}" in state.get("processed_events", {})


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_commissioning_probe(
    source_state_path: str | Path,
    public_evidence_path: str | Path,
    work_dir: str | Path,
) -> dict[str, Any]:
    """Exercise data/entry/exit gap persistence on isolated state copies only."""
    source_path = Path(source_state_path)
    evidence_path = Path(public_evidence_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    source_before = load_state(source_path)
    if source_before.state.get("status") != "COMMISSIONING":
        raise ValueError("Gap commissioning requires COMMISSIONING source state")
    if source_before.state.get("execution_ready") is not False:
        raise ValueError("Source runtime unexpectedly execution-ready")
    if source_before.state.get("performance_started_at") is not None:
        raise ValueError("Source runtime unexpectedly started")

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("orders_or_account_data_requested") is not False:
        raise ValueError("Evidence is not public read-only")
    ticker = evidence["ticker"]
    quote_time = datetime.fromtimestamp(ticker["exchange_time_ms"] / 1000, tz=timezone.utc)
    quote = {
        "symbol": "ETHUSDT",
        "price": ticker["price"],
        "observed_at": quote_time.isoformat(),
        "source": evidence["source"],
        "evidence_id": f"gap-commissioning-ticker-{ticker['exchange_time_ms']}",
    }

    isolated = work / "state.json"
    shutil.copyfile(source_path, isolated)
    fixture = _prepare_observing_fixture(source_before.state, quote["observed_at"])
    isolated.write_bytes(encode_state(fixture))

    cutoff = quote_time - timedelta(minutes=5)
    signal = {
        "id": "commissioning-gap-fixture",
        "model_sha256": MODEL_SHA,
        "information_cutoff": cutoff.isoformat(),
        "recorded_at": (quote_time - timedelta(seconds=1)).isoformat(),
        "passes_frozen_threshold": True,
        "prediction": 0.0115,
        "evidence_sha256": hashlib.sha256(b"commissioning-gap-signal-fixture").hexdigest(),
        "fixture_only": True,
    }
    signal_event = {
        "event_id": f"signal:{signal['id']}",
        "kind": "signal_record",
        "signal": copy.deepcopy(signal),
    }
    recorded = append(fixture, signal_event)

    missing_at = (cutoff + timedelta(minutes=91)).isoformat()
    entry_gap = record_entry_fill_gap(recorded, signal=signal, observed_at=missing_at)
    entry_gap_replay = record_entry_fill_gap(
        entry_gap,
        signal=signal,
        observed_at=(stamp(missing_at) + timedelta(minutes=10)).isoformat(),
    )
    entry_gap_idempotent = entry_gap_replay == entry_gap
    entry_not_filled = f"entry:{signal['id']}" not in entry_gap["processed_events"]

    # Separate fixture opens from the actual connected public quote, then tests
    # a missing due-exit observation without inventing a historical exit price.
    opened = open_opportunity(recorded, signal, quote, quote["observed_at"])
    due = stamp(opened["parent_busy_until"])
    exit_gap_time = (due + timedelta(seconds=30)).isoformat()
    exit_gap = record_due_exit_gap(
        opened,
        observed_at=exit_gap_time,
        source="runtime quote collector",
    )
    exit_gap_replay = record_due_exit_gap(
        exit_gap,
        observed_at=(due + timedelta(minutes=10)).isoformat(),
        source="runtime quote collector",
    )
    exit_gap_idempotent = exit_gap_replay == exit_gap
    no_exit_fabricated = not any(row.get("kind") == "paper_exit" for row in exit_gap["ledger"])
    positions_remain_open = any(a.get("open") is not None for a in exit_gap["accounts"].values())

    completed_close = evidence["five_minute_klines"]["latest_completed_row_close_utc"]
    data_gap = record_data_gap(
        fixture,
        gap_key="required-derivative-family-example",
        observed_at=quote["observed_at"],
        expected_cutoff=completed_close,
        source="commissioning synthetic missing-family fixture anchored to connected completed 5m evidence",
        reason="required family intentionally absent in engineering fixture",
    )
    data_gap_replay = record_data_gap(
        data_gap,
        gap_key="required-derivative-family-example",
        observed_at=(quote_time + timedelta(minutes=5)).isoformat(),
        expected_cutoff=completed_close,
        source="commissioning synthetic missing-family fixture anchored to connected completed 5m evidence",
        reason="required family intentionally absent in engineering fixture",
    )
    data_gap_idempotent = data_gap_replay == data_gap

    source_after = load_state(source_path)
    checks = {
        "entry_fill_gap_append_only": any(row.get("kind") == "entry_fill_gap" for row in entry_gap["ledger"]),
        "entry_gap_restart_replay_idempotent": entry_gap_idempotent,
        "missing_entry_not_backfilled": entry_not_filled and entry_gap_blocks_backfill(entry_gap, signal["id"]),
        "due_exit_gap_append_only": any(row.get("kind") == "exit_fill_gap" for row in exit_gap["ledger"]),
        "due_exit_gap_restart_replay_idempotent": exit_gap_idempotent,
        "missing_exit_keeps_position_open": positions_remain_open,
        "no_exit_price_fabricated": no_exit_fabricated,
        "data_gap_append_only": any(row.get("kind") == "data_gap" for row in data_gap["ledger"]),
        "data_gap_restart_replay_idempotent": data_gap_idempotent,
        "source_runtime_bytes_unchanged": source_after.content_sha256 == source_before.content_sha256,
    }
    if not all(checks.values()):
        raise AssertionError(f"gap commissioning failed: {checks}")

    return {
        "schema": "eth-paper-runtime-gap-commissioning-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "bounded_step": "append-only late/missing fill and data-gap persistence only",
        "public_evidence": {
            "path": str(evidence_path),
            "sha256": _sha256_file(evidence_path),
            "source": evidence["source"],
            "ticker_exchange_time_ms": ticker["exchange_time_ms"],
            "ticker_price": ticker["price"],
            "latest_completed_5m_close_utc": completed_close,
        },
        "checks": checks,
        "engineering_fixture": {
            "synthetic_threshold_signal": True,
            "synthetic_missing_entry_fill": True,
            "synthetic_missing_exit_quote": True,
            "synthetic_missing_data_family": True,
            "actual_connected_public_quote_used_for_open_path_test": True,
            "forward_opportunity_claimed": False,
            "forward_trade_claimed": False,
        },
        "actual_runtime_state_mutated": False,
        "actual_runtime_paper_trades_created": 0,
        "real_orders_created": 0,
        "order_account_endpoints_used": False,
        "gate_effect": "none; base/stress cost sidecars and genuine initial weekly decisions remain incomplete",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Commission append-only paper runtime gap events")
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
