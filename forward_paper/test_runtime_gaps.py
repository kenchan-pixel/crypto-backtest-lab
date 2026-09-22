import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from forward_paper.core import MODEL_SHA, append, fresh_state, open_opportunity, stamp
from forward_paper.runtime_cycle import _prepare_observing_fixture
from forward_paper.runtime_gaps import (
    entry_gap_blocks_backfill,
    record_data_gap,
    record_due_exit_gap,
    record_entry_fill_gap,
    run_commissioning_probe,
)
from forward_paper.runtime_store import encode_state, load_state

QUOTE = {
    "symbol": "ETHUSDT",
    "price": "2753.77",
    "observed_at": "2026-09-22T20:37:32.323000+00:00",
    "source": "Binance connected public read-only market-data tool",
    "evidence_id": "test-connected-ticker",
}


def _fixture():
    base = fresh_state("2026-09-22T18:00:00+00:00")
    state = _prepare_observing_fixture(base, QUOTE["observed_at"])
    qt = stamp(QUOTE["observed_at"])
    signal = {
        "id": "gap-test",
        "model_sha256": MODEL_SHA,
        "information_cutoff": (qt - timedelta(minutes=5)).isoformat(),
        "recorded_at": (qt - timedelta(seconds=1)).isoformat(),
        "passes_frozen_threshold": True,
        "prediction": 0.0115,
        "evidence_sha256": "a" * 64,
        "fixture_only": True,
    }
    recorded = append(
        state,
        {"event_id": "signal:gap-test", "kind": "signal_record", "signal": copy.deepcopy(signal)},
    )
    return recorded, signal


def test_entry_fill_gap_is_append_only_and_terminal_for_backfill():
    state, signal = _fixture()
    cutoff = stamp(signal["information_cutoff"])
    first = record_entry_fill_gap(
        state,
        signal=signal,
        observed_at=(cutoff + timedelta(minutes=91)).isoformat(),
    )
    replay = record_entry_fill_gap(
        first,
        signal=signal,
        observed_at=(cutoff + timedelta(minutes=120)).isoformat(),
    )

    assert replay == first
    assert entry_gap_blocks_backfill(first, signal["id"])
    assert f"entry:{signal['id']}" not in first["processed_events"]
    with pytest.raises(ValueError, match="Signal too late"):
        open_opportunity(
            first,
            signal,
            {**QUOTE, "observed_at": (cutoff + timedelta(minutes=91, seconds=1)).isoformat()},
            (cutoff + timedelta(minutes=91, seconds=1)).isoformat(),
        )


def test_entry_fill_gap_requires_durable_signal_and_expired_latency():
    state, signal = _fixture()
    no_signal = fresh_state("2026-09-22T18:00:00+00:00")
    cutoff = stamp(signal["information_cutoff"])
    with pytest.raises(ValueError, match="durably recorded"):
        record_entry_fill_gap(
            no_signal,
            signal=signal,
            observed_at=(cutoff + timedelta(minutes=91)).isoformat(),
        )
    with pytest.raises(ValueError, match="still within"):
        record_entry_fill_gap(
            state,
            signal=signal,
            observed_at=(cutoff + timedelta(minutes=30)).isoformat(),
        )


def test_due_exit_gap_keeps_position_open_and_replay_is_idempotent():
    state, signal = _fixture()
    opened = open_opportunity(state, signal, QUOTE, QUOTE["observed_at"])
    due = stamp(opened["parent_busy_until"])
    first = record_due_exit_gap(
        opened,
        observed_at=(due + timedelta(seconds=30)).isoformat(),
        source="runtime quote collector",
    )
    replay = record_due_exit_gap(
        first,
        observed_at=(due + timedelta(minutes=10)).isoformat(),
        source="runtime quote collector",
    )

    assert replay == first
    assert any(row["kind"] == "exit_fill_gap" for row in first["ledger"])
    assert not any(row["kind"] == "paper_exit" for row in first["ledger"])
    assert any(account["open"] is not None for account in first["accounts"].values())


def test_data_gap_is_first-seen_append_only():
    state = fresh_state("2026-09-22T18:00:00+00:00")
    first = record_data_gap(
        state,
        gap_key="oi-missing",
        observed_at="2026-09-22T20:37:32.323000+00:00",
        expected_cutoff="2026-09-22T20:34:59.999000+00:00",
        source="connected public source",
        reason="required row absent",
    )
    replay = record_data_gap(
        first,
        gap_key="oi-missing",
        observed_at="2026-09-22T20:42:32.323000+00:00",
        expected_cutoff="2026-09-22T20:34:59.999000+00:00",
        source="connected public source",
        reason="required row absent",
    )
    assert replay == first
    event = next(row for row in first["ledger"] if row["kind"] == "data_gap")
    assert event["backfill_trade_allowed"] is False


def test_commissioning_probe_uses_public_evidence_without_mutating_runtime(tmp_path):
    source = tmp_path / "state.json"
    source.write_bytes(encode_state(fresh_state("2026-09-22T18:00:00+00:00")))
    before = load_state(source)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": "eth-paper-gap-commissioning-public-evidence-v1",
                "source": "Binance connected public read-only market-data tool",
                "symbol": "ETHUSDT",
                "orders_or_account_data_requested": False,
                "ticker": {
                    "tool_operation": "get_futures_usds_symbol_price_ticker",
                    "price": "2753.77",
                    "exchange_time_ms": 1790109452323,
                    "exchange_time_utc": "2026-09-22T20:37:32.323000+00:00",
                },
                "five_minute_klines": {
                    "tool_operation": "get_futures_usds_kline_candlestick_data",
                    "interval": "5m",
                    "requested_limit": 2,
                    "rows": [],
                    "latest_completed_row_open_utc": "2026-09-22T20:30:00+00:00",
                    "latest_completed_row_close_utc": "2026-09-22T20:34:59.999000+00:00",
                    "second_row_was_not_relied_on_as_completed": True,
                },
            }
        ),
        encoding="utf-8",
    )

    receipt = run_commissioning_probe(source, evidence, tmp_path / "probe")
    after = load_state(source)

    assert receipt["passed"] is True
    assert all(receipt["checks"].values())
    assert receipt["engineering_fixture"]["forward_trade_claimed"] is False
    assert receipt["actual_runtime_state_mutated"] is False
    assert receipt["actual_runtime_paper_trades_created"] == 0
    assert receipt["order_account_endpoints_used"] is False
    assert after.content_sha256 == before.content_sha256
