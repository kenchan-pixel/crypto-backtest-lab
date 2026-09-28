import copy
import hashlib
import json
from datetime import timedelta

import pytest

from forward_paper.core import MODEL_SHA, append, fresh_state, stamp
from forward_paper.runtime_cycle import _fixture_signal, _prepare_observing_fixture, process_cycle
from forward_paper.runtime_integration import (
    commit_weekly_decision,
    commit_weekly_decision_cas,
    process_integrated_cycle,
    run_commissioning_probe,
)
from forward_paper.runtime_store import CASConflict, encode_state, load_state, write_state_cas

Q1 = {
    "symbol": "ETHUSDT",
    "price": "2740.44",
    "exchange_time_ms": 1790115415579,
    "observed_at": "2026-09-22T22:16:55.579000+00:00",
    "source": "Binance USD-M public symbol price ticker",
    "evidence_id": "integration-q1",
}
Q2 = {
    "symbol": "ETHUSDT",
    "price": "2741.37",
    "exchange_time_ms": 1790115435183,
    "observed_at": "2026-09-22T22:17:15.183000+00:00",
    "source": "Binance USD-M public symbol price ticker",
    "evidence_id": "integration-q2",
}


def _opened_fixture():
    base = _prepare_observing_fixture(fresh_state("2026-09-22T20:00:00+00:00"), Q1["observed_at"])
    signal = _fixture_signal(Q1["observed_at"])
    recorded = process_cycle(base, now=Q1["observed_at"], quote=None, signal=signal).state
    opened = process_cycle(recorded, now=Q2["observed_at"], quote=Q2, signal=signal).state
    return opened, signal


def _decision_args(decision_id="integration-decision"):
    return {
        "decision_id": decision_id,
        "information_cutoff": "2026-09-22T22:18:00+00:00",
        "committed_at": "2026-09-22T22:19:00+00:00",
        "effective_at": "2026-09-22T23:00:00+00:00",
        "expires_at": "2026-09-29T23:00:00+00:00",
        "ai_weight": 0.0,
        "simple_weight": 0.5,
        "packet_sha256": hashlib.sha256(b"integration-packet").hexdigest(),
        "rationale": "test fixture only",
    }


def test_integrated_due_exit_appends_cost_sidecar_immediately_after_exit():
    opened, signal = _opened_fixture()
    due = stamp(opened["parent_busy_until"])
    quote = {
        "symbol": "ETHUSDT",
        "price": "2760.00",
        "observed_at": (due + timedelta(seconds=10)).isoformat(),
        "source": "synthetic test ONLY",
        "evidence_id": "integration-exit",
    }

    result = process_integrated_cycle(opened, now=quote["observed_at"], quote=quote, signal={"id": "ignored"})
    assert result.action == "exit"
    ids = [row["event_id"] for row in result.state["ledger"]]
    assert ids[-2:] == [f"exit:{signal['id']}", f"sidecar:cost:{signal['id']}"]
    exit_ev = result.state["ledger"][-2]
    cost_ev = result.state["ledger"][-1]
    assert cost_ev["exit_event_sha256"] == exit_ev["sha256"]
    for arm in ("AI_WEEKLY", "SIMPLE_WEEKLY", "HALF"):
        assert cost_ev["scenarios"]["BASE"]["accounts"][arm]["post_cash"] == pytest.approx(result.state["accounts"][arm]["cash"])


def test_weekly_decision_and_budget_are_atomic_logical_pair_and_exact_replay_is_idempotent():
    state = fresh_state("2026-09-22T20:00:00+00:00")
    args = _decision_args()
    out = commit_weekly_decision(state, **args)
    ids = [row["event_id"] for row in out["ledger"]]
    assert ids[-2:] == [args["decision_id"], f"sidecar:ai-budget:{args['decision_id']}"]
    assert out["accounts"] == state["accounts"]
    assert out["execution_ready"] is False
    assert out["performance_started_at"] is None
    assert commit_weekly_decision(copy.deepcopy(out), **args) == out

    changed = dict(args)
    changed["ai_weight"] = 0.5
    with pytest.raises(ValueError, match="Conflicting repeated weekly decision"):
        commit_weekly_decision(out, **changed)


def test_stale_cas_cannot_persist_partial_decision_or_budget(tmp_path):
    path = tmp_path / "state.json"
    path.write_bytes(encode_state(fresh_state("2026-09-22T20:00:00+00:00")))
    stale = load_state(path)
    winner = append(stale.state, {"event_id": "winner", "kind": "commissioning_probe"})
    write_state_cas(path, winner, expected_content_sha256=stale.content_sha256)

    args = _decision_args("stale-integration-decision")
    with pytest.raises(CASConflict):
        commit_weekly_decision_cas(path, expected_content_sha256=stale.content_sha256, **args)
    after = load_state(path)
    assert args["decision_id"] not in after.state["processed_events"]
    assert f"sidecar:ai-budget:{args['decision_id']}" not in after.state["processed_events"]


def test_integration_commissioning_probe_uses_public_quotes_and_leaves_source_untouched(tmp_path):
    source = tmp_path / "source_state.json"
    source.write_bytes(encode_state(fresh_state("2026-09-22T20:00:00+00:00")))
    before = load_state(source)
    evidence = tmp_path / "public.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": "eth-paper-runtime-integration-public-evidence-v1",
                "source": "Binance connected public read-only market-data tool",
                "tool_operation": "get_futures_usds_symbol_price_ticker",
                "symbol": "ETHUSDT",
                "read_only": True,
                "orders_or_account_data_requested": False,
                "quotes": [Q1, Q2],
            }
        ),
        encoding="utf-8",
    )

    receipt = run_commissioning_probe(source, evidence, tmp_path / "work")
    after = load_state(source)
    assert receipt["passed"] is True
    assert all(receipt["checks"].values())
    assert receipt["engineering_fixture"]["forward_trade_claimed"] is False
    assert receipt["engineering_fixture"]["genuine_weekly_decision_claimed"] is False
    assert receipt["actual_runtime_state_mutated"] is False
    assert receipt["actual_runtime_paper_trades_created"] == 0
    assert receipt["real_orders_created"] == 0
    assert receipt["order_account_endpoints_used"] is False
    assert after.content_sha256 == before.content_sha256
    assert after.state["model_sha256"] == MODEL_SHA
