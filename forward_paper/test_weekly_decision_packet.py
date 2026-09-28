import json
from datetime import datetime, timedelta, timezone

import pytest

from forward_paper.core import MODEL_SHA, fresh_state, stamp
from forward_paper.runtime_store import encode_state, load_state
from forward_paper.weekly_decision_packet import (
    build_weekly_packet,
    commit_weekly_from_packet_cas,
    derive_simple_control,
    prepare_commit_args,
    run_commissioning_probe,
    weekly_commit_eligibility,
)


def _ready_commissioning_state(created_at="2026-09-20T00:00:00+00:00"):
    state = fresh_state(created_at)
    for key in ("model_identity", "live_feature_parity", "source_freshness", "accounting_tests"):
        state["gates"][key] = True
    return state


def _evidence(observed_at="2026-09-21T00:10:00+00:00", start_close=2400.0, end_close=2600.0):
    end_open_ms = int((stamp(observed_at) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    start_open_ms = end_open_ms - 30 * 86_400_000
    return {
        "schema": "eth-weekly-connected-evidence-v1",
        "observed_at": observed_at,
        "end_bar_close_at": datetime.fromtimestamp((end_open_ms + 86_400_000 - 1) / 1000, tz=timezone.utc).isoformat(),
        "source": "Binance connected public read-only market-data tool",
        "tool_operation": "get_spot_kline_candlestick_data",
        "read_only": True,
        "orders_or_account_data_requested": False,
        "query_contract": {"symbol": "ETHUSDT", "interval": "1d", "time_zone": "UTC"},
        "bars": {
            "start_30d": {
                "open_time_ms": start_open_ms,
                "close_time_ms": start_open_ms + 86_400_000 - 1,
                "close": str(start_close),
            },
            "end_latest_completed": {
                "open_time_ms": end_open_ms,
                "close_time_ms": end_open_ms + 86_400_000 - 1,
                "close": str(end_close),
            },
        },
    }


def _write(tmp_path, state, evidence):
    state_path = tmp_path / "state.json"
    evidence_path = tmp_path / "evidence.json"
    state_path.write_bytes(encode_state(state))
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return state_path, evidence_path


def test_simple_control_positive_and_negative_direction():
    pos = derive_simple_control(_evidence(start_close=2000.0, end_close=2100.0))
    neg = derive_simple_control(_evidence(start_close=2100.0, end_close=2000.0))
    assert pos["weight"] == 1.0 and pos["return_30d"] > 0
    assert neg["weight"] == 0.5 and neg["return_30d"] < 0


def test_simple_control_rejects_future_or_not_exactly_30d():
    evidence = _evidence()
    evidence["bars"]["start_30d"]["open_time_ms"] += 1
    with pytest.raises(ValueError, match="exactly 30 days"):
        derive_simple_control(evidence)


def test_monday_after_0800_hkt_is_eligible_only_once_ready():
    state = _ready_commissioning_state()
    assert weekly_commit_eligibility(state, "2026-09-21T00:00:00+00:00")["eligible"] is True
    assert weekly_commit_eligibility(state, "2026-09-20T23:59:59+00:00")["eligible"] is False
    state["model_sha256"] = "0" * 64
    assert weekly_commit_eligibility(state, "2026-09-21T00:00:00+00:00")["eligible"] is False


def test_prepare_and_atomic_commit_path_requires_explicit_ai_choice_and_does_not_arm(tmp_path):
    state, evidence = _write(
        tmp_path,
        _ready_commissioning_state(),
        _evidence(observed_at="2026-09-21T00:10:00+00:00", start_close=2400.0, end_close=2600.0),
    )
    args = prepare_commit_args(
        state,
        evidence,
        committed_at="2026-09-21T00:15:00+00:00",
        ai_weight=0.5,
        rationale="Explicit commissioning fixture choice only.",
    )
    assert args["simple_weight"] == 1.0
    assert args["effective_at"] == "2026-09-21T01:00:00+00:00"
    assert args["expires_at"] == "2026-09-28T01:00:00+00:00"

    out = commit_weekly_from_packet_cas(
        state,
        evidence,
        committed_at="2026-09-21T00:15:00+00:00",
        ai_weight=0.5,
        rationale="Explicit commissioning fixture choice only.",
    )
    assert out.state["model_sha256"] == MODEL_SHA
    assert out.state["decision"]["weights"] == {"AI_WEEKLY": 0.5, "SIMPLE_WEEKLY": 1.0, "HALF": 0.5}
    assert out.state["execution_ready"] is False
    assert out.state["performance_started_at"] is None
    assert out.state["gates"]["initial_decisions"] is False
    ids = [row["event_id"] for row in out.state["ledger"]]
    assert ids[-2:] == ["weekly:2026-09-21", "sidecar:ai-budget:weekly:2026-09-21"]


def test_off_window_real_packet_preview_cannot_commit_or_mutate_source(tmp_path):
    state, evidence = _write(
        tmp_path,
        _ready_commissioning_state(),
        _evidence(observed_at="2026-09-23T00:10:00+00:00"),
    )
    before = load_state(state)
    packet, packet_sha = build_weekly_packet(state, evidence)
    assert len(packet_sha) == 64
    assert packet["eligibility"]["eligible"] is False
    assert packet["ai_control"]["weight"] is None

    receipt = run_commissioning_probe(state, evidence)
    after = load_state(state)
    assert receipt["passed"] is True
    assert all(receipt["checks"].values())
    assert receipt["genuine_weekly_decision_committed"] is False
    assert after.content_sha256 == before.content_sha256
    assert after.state["decision"] is None


def test_stale_or_future_weekly_evidence_fails_closed(tmp_path):
    state, evidence = _write(
        tmp_path,
        _ready_commissioning_state(),
        _evidence(observed_at="2026-09-21T00:10:00+00:00"),
    )
    with pytest.raises(ValueError, match="stale/future"):
        prepare_commit_args(
            state,
            evidence,
            committed_at="2026-09-21T00:31:00+00:00",
            ai_weight=0.0,
            rationale="fixture",
        )
