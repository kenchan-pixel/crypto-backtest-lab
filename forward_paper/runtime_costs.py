"""Durable paper-only cost comparison and AI operating-budget sidecars.

The trading accounts in core.py use the approved BASE transaction-cost case.
This module appends independent audit sidecars only: it never changes strategy
signals, allocation decisions, broker/account data, or the core account cash.

Cost sidecars are computed from the already-saved paper_entry/paper_exit events
for the SAME parent opportunity. AI operating-budget sidecars are computed from
an already-saved weekly_decision and remain separate from trading P&L.
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

from forward_paper.core import ARMS, MODEL_SHA, append, close_due, open_opportunity, set_decision, stamp
from forward_paper.runtime_cycle import _prepare_observing_fixture
from forward_paper.runtime_store import load_state, write_state_cas

BASE_COST = {"fee_per_side": 0.001, "slippage_per_side": 0.0005}
STRESS_COST = {"fee_per_side": 0.0015, "slippage_per_side": 0.0015}
AI_BUDGET_RATES = {"0pct": 0.0, "0.01pct": 0.0001, "0.05pct": 0.0005}


def _find_ledger_event(state: dict[str, Any], event_id: str) -> dict[str, Any]:
    for row in state.get("ledger", []):
        if row.get("event_id") == event_id:
            return row
    raise ValueError(f"Required durable event not found: {event_id}")


def _latest_cost_balances(state: dict[str, Any]) -> dict[str, dict[str, float]]:
    latest = None
    for row in state.get("ledger", []):
        if row.get("kind") == "cost_comparison_sidecar":
            latest = row
    if latest is not None:
        return {
            scenario: {
                arm: float(latest["scenarios"][scenario]["accounts"][arm]["post_cash"])
                for arm in ARMS
            }
            for scenario in ("BASE", "STRESS")
        }
    return {
        scenario: {
            arm: float(state["accounts"][arm]["initial_virtual_usdt"])
            for arm in ARMS
        }
        for scenario in ("BASE", "STRESS")
    }


def _scenario_round_trip(
    *,
    pre_cash: float,
    weight: float,
    entry_price: float,
    exit_price: float,
    fee: float,
    slippage: float,
    initial_capital: float,
) -> dict[str, float]:
    values = (pre_cash, weight, entry_price, exit_price, fee, slippage, initial_capital)
    if not all(isinstance(v, (int, float)) for v in values):
        raise ValueError("Cost sidecar inputs must be numeric")
    if pre_cash < 0 or initial_capital <= 0 or not 0 <= weight <= 1:
        raise ValueError("Invalid sidecar cash/allocation")
    if entry_price <= 0 or exit_price <= 0 or not 0 <= fee < 0.01 or not 0 <= slippage < 0.01:
        raise ValueError("Invalid sidecar price/cost")

    spend = pre_cash * weight
    if spend == 0:
        quantity = 0.0
        proceeds = 0.0
        pnl = 0.0
        post_cash = pre_cash
    else:
        quantity = spend / (entry_price * (1 + slippage) * (1 + fee))
        proceeds = quantity * exit_price * (1 - slippage) * (1 - fee)
        pnl = proceeds - spend
        post_cash = pre_cash - spend + proceeds
    return {
        "pre_cash": pre_cash,
        "weight": weight,
        "spend": spend,
        "quantity": quantity,
        "proceeds": proceeds,
        "realized_pnl": pnl,
        "post_cash": post_cash,
        "cumulative_net_return": post_cash / initial_capital - 1,
    }


def append_cost_comparison_sidecar(state: dict[str, Any], opportunity_id: str) -> dict[str, Any]:
    """Append BASE/STRESS results from an existing closed parent opportunity.

    Prices and weights are read from immutable runtime ledger events rather than
    accepted from the caller, preventing a sidecar from silently using a
    different opportunity, allocation, or fill reference.
    """
    event_id = f"sidecar:cost:{opportunity_id}"
    if event_id in state.get("processed_events", {}):
        return copy.deepcopy(state)

    entry = _find_ledger_event(state, f"entry:{opportunity_id}")
    exit_event = _find_ledger_event(state, f"exit:{opportunity_id}")
    if entry.get("kind") != "paper_entry" or exit_event.get("kind") != "paper_exit":
        raise ValueError("Cost sidecar requires saved paper entry and exit events")

    entry_price = float(entry["quote"]["price"])
    exit_price = float(exit_event["quote"]["price"])
    if entry_price <= 0 or exit_price <= 0:
        raise ValueError("Invalid saved quote price")

    weights = {arm: float(entry["accounts"][arm]["weight"]) for arm in ARMS}
    balances = _latest_cost_balances(state)
    scenarios: dict[str, Any] = {}
    for scenario_name, costs in (("BASE", BASE_COST), ("STRESS", STRESS_COST)):
        accounts = {}
        for arm in ARMS:
            accounts[arm] = _scenario_round_trip(
                pre_cash=balances[scenario_name][arm],
                weight=weights[arm],
                entry_price=entry_price,
                exit_price=exit_price,
                fee=costs["fee_per_side"],
                slippage=costs["slippage_per_side"],
                initial_capital=float(state["accounts"][arm]["initial_virtual_usdt"]),
            )
        scenarios[scenario_name] = {**costs, "accounts": accounts}

    event = {
        "event_id": event_id,
        "kind": "cost_comparison_sidecar",
        "opportunity_id": opportunity_id,
        "observed_at": exit_event["observed_at"],
        "entry_event_sha256": entry["sha256"],
        "exit_event_sha256": exit_event["sha256"],
        "entry_reference": entry_price,
        "exit_reference": exit_price,
        "weights": weights,
        "scenarios": scenarios,
        "same_parent_opportunity": True,
        "changes_trading_decision": False,
    }
    return append(state, event)


def _latest_budget_cumulative(state: dict[str, Any]) -> tuple[int, dict[str, float]]:
    count = 0
    cumulative = {name: 0.0 for name in AI_BUDGET_RATES}
    for row in state.get("ledger", []):
        if row.get("kind") == "ai_operating_budget_sidecar":
            count = int(row["review_count"])
            cumulative = {name: float(row["cumulative_assumed_usdt"][name]) for name in AI_BUDGET_RATES}
    return count, cumulative


def append_ai_operating_budget_sidecar(state: dict[str, Any], decision_id: str) -> dict[str, Any]:
    """Append assumed AI review overhead without deducting it from trading NAV."""
    event_id = f"sidecar:ai-budget:{decision_id}"
    if event_id in state.get("processed_events", {}):
        return copy.deepcopy(state)

    decision = _find_ledger_event(state, decision_id)
    if decision.get("kind") != "weekly_decision":
        raise ValueError("AI budget sidecar requires a saved weekly_decision")
    ai_weight = float(decision["weights"]["AI_WEEKLY"])
    if ai_weight not in (0.0, 0.5, 1.0):
        raise ValueError("Unexpected AI weekly allocation")

    previous_count, prior = _latest_budget_cumulative(state)
    starting_account = float(state["accounts"]["AI_WEEKLY"]["initial_virtual_usdt"])
    increment = {name: starting_account * rate for name, rate in AI_BUDGET_RATES.items()}
    cumulative = {name: prior[name] + increment[name] for name in AI_BUDGET_RATES}

    event = {
        "event_id": event_id,
        "kind": "ai_operating_budget_sidecar",
        "decision_id": decision_id,
        "observed_at": decision["committed_at"],
        "review_count": previous_count + 1,
        "ai_allocation": ai_weight,
        "inactive_ai_allocation": ai_weight == 0.0,
        "starting_account_usdt": starting_account,
        "rates_of_starting_account_per_review": AI_BUDGET_RATES,
        "increment_assumed_usdt": increment,
        "cumulative_assumed_usdt": cumulative,
        "deducted_from_trading_nav": False,
    }
    return append(state, event)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_commissioning_probe(
    source_state_path: str | Path,
    public_evidence_path: str | Path,
    work_dir: str | Path,
) -> dict[str, Any]:
    """Commission cost/budget sidecars on an isolated copy only."""
    source_path = Path(source_state_path)
    evidence_path = Path(public_evidence_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    source_before = load_state(source_path)
    if source_before.state.get("status") != "COMMISSIONING":
        raise ValueError("Cost commissioning requires COMMISSIONING source state")
    if source_before.state.get("execution_ready") is not False:
        raise ValueError("Source runtime unexpectedly execution-ready")
    if source_before.state.get("performance_started_at") is not None:
        raise ValueError("Source runtime unexpectedly started")
    if any(int(source_before.state["accounts"][arm].get("trades", 0)) for arm in ARMS):
        raise ValueError("Source runtime unexpectedly contains paper trades")

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("read_only") is not True or evidence.get("orders_or_account_data_requested") is not False:
        raise ValueError("Cost evidence is not marked public read-only")
    ticker = evidence["ticker"]
    if ticker.get("symbol") != "ETHUSDT":
        raise ValueError("Unexpected public ticker symbol")
    reference_price = float(ticker["price"])
    if reference_price <= 0:
        raise ValueError("Invalid public ticker price")
    quote_time = datetime.fromtimestamp(int(ticker["exchange_time_ms"]) / 1000, tz=timezone.utc)

    fixture = _prepare_observing_fixture(source_before.state, quote_time.isoformat())
    cutoff = quote_time - timedelta(minutes=5)
    signal = {
        "id": "commissioning-cost-sidecar-fixture",
        "model_sha256": MODEL_SHA,
        "information_cutoff": cutoff.isoformat(),
        "recorded_at": (quote_time - timedelta(seconds=1)).isoformat(),
        "passes_frozen_threshold": True,
        "prediction": 0.0115,
        "evidence_sha256": hashlib.sha256(b"commissioning-cost-sidecar-signal-fixture").hexdigest(),
        "fixture_only": True,
    }
    signal_event = {"event_id": f"signal:{signal['id']}", "kind": "signal_record", "signal": copy.deepcopy(signal)}
    recorded = append(fixture, signal_event)
    entry_quote = {
        "symbol": "ETHUSDT",
        "price": reference_price,
        "observed_at": quote_time.isoformat(),
        "source": evidence["source"],
        "evidence_id": f"cost-commissioning-public-ticker-{ticker['exchange_time_ms']}",
    }
    opened = open_opportunity(recorded, signal, entry_quote, quote_time.isoformat())
    due = stamp(opened["parent_busy_until"])
    synthetic_exit_time = due + timedelta(seconds=30)
    exit_quote = {
        "symbol": "ETHUSDT",
        "price": reference_price,
        "observed_at": synthetic_exit_time.isoformat(),
        "source": "commissioning same-price cost-isolation fixture; not an observed future market quote",
        "evidence_id": "commissioning-synthetic-cost-isolation-exit",
    }
    closed = close_due(opened, exit_quote, synthetic_exit_time.isoformat())
    with_cost = append_cost_comparison_sidecar(closed, signal["id"])
    cost_event = _find_ledger_event(with_cost, f"sidecar:cost:{signal['id']}")

    base_matches_core = all(
        abs(float(cost_event["scenarios"]["BASE"]["accounts"][arm]["post_cash"]) - float(closed["accounts"][arm]["cash"])) < 1e-9
        for arm in ARMS
    )
    stress_not_better = all(
        float(cost_event["scenarios"]["STRESS"]["accounts"][arm]["post_cash"])
        <= float(cost_event["scenarios"]["BASE"]["accounts"][arm]["post_cash"])
        for arm in ARMS
    )
    cost_replay = append_cost_comparison_sidecar(with_cost, signal["id"])
    cost_idempotent = cost_replay == with_cost

    # A separate actual weekly decision does not exist yet. Exercise the budget
    # sidecar with an isolated future decision fixture whose AI allocation is 0,
    # proving the assumed review overhead is still counted in inactive weeks.
    review_info_cut = synthetic_exit_time + timedelta(minutes=1)
    review_commit = synthetic_exit_time + timedelta(minutes=2)
    review_effective = review_commit.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    review_expiry = review_effective + timedelta(days=7)
    with_decision = set_decision(
        with_cost,
        decision_id="commissioning-inactive-ai-review-fixture",
        committed_at=review_commit.isoformat(),
        information_cutoff=review_info_cut.isoformat(),
        effective_at=review_effective.isoformat(),
        expires_at=review_expiry.isoformat(),
        ai_weight=0.0,
        simple_weight=0.5,
        packet_sha256=hashlib.sha256(b"commissioning-inactive-ai-review-packet").hexdigest(),
        rationale="isolated commissioning fixture only",
    )
    with_budget = append_ai_operating_budget_sidecar(with_decision, "commissioning-inactive-ai-review-fixture")
    budget_event = _find_ledger_event(with_budget, "sidecar:ai-budget:commissioning-inactive-ai-review-fixture")
    budget_replay = append_ai_operating_budget_sidecar(with_budget, "commissioning-inactive-ai-review-fixture")
    budget_idempotent = budget_replay == with_budget

    isolated = work / "state.json"
    shutil.copyfile(source_path, isolated)
    isolated_before = load_state(isolated)
    written = write_state_cas(isolated, with_budget, expected_content_sha256=isolated_before.content_sha256)
    restarted = load_state(isolated)
    durable_round_trip = written.content_sha256 == restarted.content_sha256
    restart_replay = (
        append_ai_operating_budget_sidecar(
            append_cost_comparison_sidecar(restarted.state, signal["id"]),
            "commissioning-inactive-ai-review-fixture",
        )
        == restarted.state
    )

    source_after = load_state(source_path)
    source_unchanged = source_after.content_sha256 == source_before.content_sha256
    trading_accounts_unchanged_by_budget = with_budget["accounts"] == with_decision["accounts"]
    expected_budget = {"0pct": 0.0, "0.01pct": 1.0, "0.05pct": 5.0}
    budget_exact = all(abs(float(budget_event["increment_assumed_usdt"][k]) - v) < 1e-12 for k, v in expected_budget.items())

    checks = {
        "base_cost_contract_exact": cost_event["scenarios"]["BASE"]["fee_per_side"] == 0.001 and cost_event["scenarios"]["BASE"]["slippage_per_side"] == 0.0005,
        "stress_cost_contract_exact": cost_event["scenarios"]["STRESS"]["fee_per_side"] == 0.0015 and cost_event["scenarios"]["STRESS"]["slippage_per_side"] == 0.0015,
        "same_parent_and_saved_fill_references": cost_event["same_parent_opportunity"] is True and cost_event["entry_event_sha256"] == _find_ledger_event(closed, f"entry:{signal['id']}")["sha256"] and cost_event["exit_event_sha256"] == _find_ledger_event(closed, f"exit:{signal['id']}")["sha256"],
        "base_sidecar_matches_core_accounting": base_matches_core,
        "stress_cost_is_not_better_than_base": stress_not_better,
        "cost_sidecar_replay_idempotent": cost_idempotent,
        "ai_budget_rates_exact": budget_event["rates_of_starting_account_per_review"] == AI_BUDGET_RATES and budget_exact,
        "inactive_ai_review_still_counted": budget_event["inactive_ai_allocation"] is True and budget_event["review_count"] == 1,
        "ai_budget_separate_from_trading_nav": budget_event["deducted_from_trading_nav"] is False and trading_accounts_unchanged_by_budget,
        "ai_budget_replay_idempotent": budget_idempotent,
        "isolated_cas_persistence_round_trip": durable_round_trip and restart_replay,
        "source_runtime_bytes_unchanged": source_unchanged,
    }
    if not all(checks.values()):
        raise AssertionError(f"cost sidecar commissioning failed: {checks}")

    return {
        "schema": "eth-paper-runtime-cost-sidecar-commissioning-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "bounded_step": "base/stress transaction-cost comparison plus separate AI operating-budget sidecars",
        "public_evidence": {
            "path": str(evidence_path),
            "sha256": _sha256_file(evidence_path),
            "source": evidence["source"],
            "tool_operation": evidence.get("tool_operation"),
            "ticker_exchange_time_ms": ticker["exchange_time_ms"],
            "ticker_price": ticker["price"],
        },
        "cost_contract": {"BASE": BASE_COST, "STRESS": STRESS_COST},
        "ai_budget_contract": {
            "rates_of_starting_account_per_actual_ai_review": AI_BUDGET_RATES,
            "assumed_usdt_per_review_at_10000_start": expected_budget,
            "applies_on_inactive_ai_week": True,
            "deducted_from_trading_nav": False,
        },
        "checks": checks,
        "engineering_fixture": {
            "synthetic_threshold_signal": True,
            "actual_connected_public_price_anchor": True,
            "synthetic_24h_exit_timestamp": True,
            "synthetic_same_price_exit_for_cost_isolation": True,
            "synthetic_inactive_ai_weekly_review": True,
            "forward_opportunity_claimed": False,
            "forward_trade_claimed": False,
        },
        "isolated_fixture_account_trade_counts": {arm: int(closed["accounts"][arm]["trades"]) for arm in ARMS},
        "actual_runtime_state_mutated": False,
        "actual_runtime_paper_trades_created": 0,
        "real_orders_created": 0,
        "order_account_endpoints_used": False,
        "gate_effect": "none; sidecar mechanics are commissioned but runtime-cycle wiring and genuine initial weekly decisions remain incomplete",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Commission paper-runtime cost and AI-budget sidecars")
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
