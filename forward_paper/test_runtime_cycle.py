import copy
import json
from datetime import timedelta

import pytest

from forward_paper.core import MODEL_SHA, fresh_state, stamp
from forward_paper.runtime_cycle import (
    _prepare_observing_fixture,
    _fixture_signal,
    due_exit_pending,
    process_cycle,
    run_commissioning_probe,
)
from forward_paper.runtime_store import encode_state, load_state

Q1 = {
    "symbol": "ETHUSDT",
    "price": "2752.17",
    "exchange_time_ms": 1790106277241,
    "observed_at": "2026-09-22T19:44:37.241000+00:00",
    "source": "Binance USD-M public symbol price ticker",
    "evidence_id": "q1",
}
Q2 = {
    "symbol": "ETHUSDT",
    "price": "2752.90",
    "exchange_time_ms": 1790106291246,
    "observed_at": "2026-09-22T19:44:51.246000+00:00",
    "source": "Binance USD-M public symbol price ticker",
    "evidence_id": "q2",
}


def _observing_state():
    base = fresh_state("2026-09-22T17:00:00+00:00")
    return _prepare_observing_fixture(base, Q1["observed_at"])


def test_signal_event_is_appended_before_actual_later_quote_entry():
    state = _observing_state()
    signal = _fixture_signal(Q1["observed_at"])
    result = process_cycle(state, now=Q2["observed_at"], quote=Q2, signal=signal)

    assert result.action == "entry"
    ids = [row["event_id"] for row in result.state["ledger"]]
    assert ids.index(f"signal:{signal['id']}") < ids.index(f"entry:{signal['id']}")
    assert stamp(signal["recorded_at"]) < stamp(Q2["observed_at"])


def test_completed_entry_replay_is_idempotent_after_restart():
    state = _observing_state()
    signal = _fixture_signal(Q1["observed_at"])
    first = process_cycle(state, now=Q2["observed_at"], quote=Q2, signal=signal)
    second = process_cycle(copy.deepcopy(first.state), now=Q2["observed_at"], quote=Q2, signal=signal)

    assert second.action == "entry_already_processed"
    assert second.state == first.state


def test_due_exit_preempts_competing_entry_in_same_cycle():
    state = _observing_state()
    signal = _fixture_signal(Q1["observed_at"])
    opened = process_cycle(state, now=Q2["observed_at"], quote=Q2, signal=signal).state
    due = stamp(opened["parent_busy_until"])
    exit_quote = {
        "symbol": "ETHUSDT",
        "price": "2760.00",
        "observed_at": (due + timedelta(seconds=1)).isoformat(),
        "source": "test quote",
        "evidence_id": "exit-q",
    }
    competing = copy.deepcopy(signal)
    competing["id"] = "competing"
    competing["information_cutoff"] = (due - timedelta(minutes=10)).isoformat()
    competing["recorded_at"] = (due - timedelta(minutes=5)).isoformat()

    assert due_exit_pending(opened, exit_quote["observed_at"])
    result = process_cycle(opened, now=exit_quote["observed_at"], quote=exit_quote, signal=competing)

    assert result.action == "exit"
    assert result.entry_evaluated is False
    assert f"signal:{competing['id']}" not in result.state["processed_events"]
    assert f"entry:{competing['id']}" not in result.state["processed_events"]


def test_due_exit_without_quote_fails_closed_before_new_entry():
    state = _observing_state()
    signal = _fixture_signal(Q1["observed_at"])
    opened = process_cycle(state, now=Q2["observed_at"], quote=Q2, signal=signal).state
    due = stamp(opened["parent_busy_until"])
    competing = copy.deepcopy(signal)
    competing["id"] = "blocked-competing"

    with pytest.raises(ValueError, match="Due exit requires actual quote evidence"):
        process_cycle(opened, now=(due + timedelta(seconds=1)).isoformat(), quote=None, signal=competing)

    assert f"signal:{competing['id']}" not in opened["processed_events"]


def test_commissioning_probe_uses_connected_quotes_but_never_mutates_source(tmp_path):
    source = tmp_path / "state.json"
    source.write_bytes(encode_state(fresh_state("2026-09-22T17:00:00+00:00")))
    before = load_state(source)
    quote_pair = tmp_path / "quotes.json"
    quote_pair.write_text(
        json.dumps(
            {
                "schema": "eth-paper-connected-quote-pair-v1",
                "source": "Binance USD-M public read-only symbol price ticker",
                "tool_operation": "get_futures_usds_symbol_price_ticker",
                "symbol": "ETHUSDT",
                "read_only": True,
                "orders_or_account_data_requested": False,
                "quotes": [Q1, Q2],
            }
        ),
        encoding="utf-8",
    )

    receipt = run_commissioning_probe(source, quote_pair, tmp_path / "probe")
    after = load_state(source)

    assert receipt["passed"] is True
    assert all(receipt["checks"].values())
    assert receipt["engineering_fixture"]["forward_trade_claimed"] is False
    assert receipt["actual_runtime_state_mutated"] is False
    assert receipt["actual_runtime_paper_trades_created"] == 0
    assert receipt["order_account_endpoints_used"] is False
    assert after.content_sha256 == before.content_sha256
    assert after.state["model_sha256"] == MODEL_SHA
