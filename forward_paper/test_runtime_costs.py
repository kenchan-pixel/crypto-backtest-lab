from datetime import timedelta
import copy
import hashlib

import pytest

from forward_paper.core import MODEL_SHA, append, close_due, open_opportunity, set_decision, stamp
from forward_paper.runtime_costs import (
    AI_BUDGET_RATES,
    BASE_COST,
    STRESS_COST,
    append_ai_operating_budget_sidecar,
    append_cost_comparison_sidecar,
)
from forward_paper.runtime_cycle import _prepare_observing_fixture
from forward_paper.core import fresh_state


def _closed_fixture():
    first = "2026-09-22T21:37:48.639000+00:00"
    base = _prepare_observing_fixture(fresh_state("2026-09-22T18:00:00+00:00"), first)
    t = stamp(first)
    sig = {
        "id": "cost-test",
        "model_sha256": MODEL_SHA,
        "information_cutoff": (t - timedelta(minutes=5)).isoformat(),
        "recorded_at": (t - timedelta(seconds=1)).isoformat(),
        "passes_frozen_threshold": True,
        "prediction": 0.02,
        "evidence_sha256": "c" * 64,
    }
    recorded = append(base, {"event_id": "signal:cost-test", "kind": "signal_record", "signal": copy.deepcopy(sig)})
    quote = {"symbol": "ETHUSDT", "price": 2750.0, "observed_at": first, "source": "synthetic test ONLY", "evidence_id": "fixture"}
    opened = open_opportunity(recorded, sig, quote, first)
    due = stamp(opened["parent_busy_until"])
    exit_quote = {"symbol": "ETHUSDT", "price": 2800.0, "observed_at": (due + timedelta(seconds=30)).isoformat(), "source": "synthetic test ONLY", "evidence_id": "fixture-exit"}
    closed = close_due(opened, exit_quote, exit_quote["observed_at"])
    return closed


def test_cost_contract_constants_are_protocol_exact():
    assert BASE_COST == {"fee_per_side": 0.001, "slippage_per_side": 0.0005}
    assert STRESS_COST == {"fee_per_side": 0.0015, "slippage_per_side": 0.0015}
    assert AI_BUDGET_RATES == {"0pct": 0.0, "0.01pct": 0.0001, "0.05pct": 0.0005}


def test_cost_sidecar_uses_saved_parent_entry_exit_and_base_matches_core():
    closed = _closed_fixture()
    out = append_cost_comparison_sidecar(closed, "cost-test")
    ev = next(row for row in out["ledger"] if row.get("event_id") == "sidecar:cost:cost-test")
    assert ev["same_parent_opportunity"] is True
    for arm in ("AI_WEEKLY", "SIMPLE_WEEKLY", "HALF"):
        assert ev["scenarios"]["BASE"]["accounts"][arm]["post_cash"] == pytest.approx(closed["accounts"][arm]["cash"])
        assert ev["scenarios"]["STRESS"]["accounts"][arm]["post_cash"] < ev["scenarios"]["BASE"]["accounts"][arm]["post_cash"]
    assert append_cost_comparison_sidecar(out, "cost-test") == out


def test_cost_sidecar_fails_without_closed_parent_events():
    s = fresh_state("2026-09-22T18:00:00+00:00")
    with pytest.raises(ValueError):
        append_cost_comparison_sidecar(s, "missing")


def test_ai_budget_is_separate_and_counts_inactive_review():
    s = fresh_state("2026-09-22T18:00:00+00:00")
    s = set_decision(
        s,
        decision_id="inactive-review",
        committed_at="2026-09-22T21:38:00+00:00",
        information_cutoff="2026-09-22T21:37:00+00:00",
        effective_at="2026-09-22T22:00:00+00:00",
        expires_at="2026-09-29T22:00:00+00:00",
        ai_weight=0.0,
        simple_weight=0.5,
        packet_sha256=hashlib.sha256(b"packet").hexdigest(),
        rationale="fixture only",
    )
    accounts_before = copy.deepcopy(s["accounts"])
    out = append_ai_operating_budget_sidecar(s, "inactive-review")
    ev = next(row for row in out["ledger"] if row.get("event_id") == "sidecar:ai-budget:inactive-review")
    assert ev["inactive_ai_allocation"] is True
    assert ev["increment_assumed_usdt"] == {"0pct": 0.0, "0.01pct": 1.0, "0.05pct": 5.0}
    assert ev["cumulative_assumed_usdt"] == {"0pct": 0.0, "0.01pct": 1.0, "0.05pct": 5.0}
    assert ev["deducted_from_trading_nav"] is False
    assert out["accounts"] == accounts_before
    assert append_ai_operating_budget_sidecar(out, "inactive-review") == out
