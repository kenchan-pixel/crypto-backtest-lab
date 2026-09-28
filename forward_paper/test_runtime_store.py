import copy

import pytest

from forward_paper.core import MODEL_SHA, append, fresh_state
from forward_paper.runtime_store import (
    CASConflict,
    encode_state,
    load_state,
    run_commissioning_probe,
    write_state_cas,
)

NOW = "2026-09-23T00:00:00+00:00"


def _store(tmp_path):
    path = tmp_path / "state.json"
    path.write_bytes(encode_state(fresh_state(NOW)))
    return path


def test_compare_and_swap_rejects_stale_writer_without_overwrite(tmp_path):
    path = _store(tmp_path)
    reader_a = load_state(path)
    reader_b = load_state(path)

    event_a = {"event_id": "a", "kind": "commissioning_fixture"}
    winner = write_state_cas(
        path,
        append(reader_a.state, event_a),
        expected_content_sha256=reader_a.content_sha256,
    )

    event_b = {"event_id": "b", "kind": "commissioning_fixture"}
    with pytest.raises(CASConflict):
        write_state_cas(
            path,
            append(reader_b.state, event_b),
            expected_content_sha256=reader_b.content_sha256,
        )

    final = load_state(path)
    assert final.content_sha256 == winner.content_sha256
    assert "a" in final.state["processed_events"]
    assert "b" not in final.state["processed_events"]


def test_restart_replay_is_idempotent_and_hash_chain_survives(tmp_path):
    path = _store(tmp_path)
    first = load_state(path)
    event = {"event_id": "same", "kind": "commissioning_fixture"}
    written = write_state_cas(
        path,
        append(first.state, event),
        expected_content_sha256=first.content_sha256,
    )

    restarted = load_state(path)
    replayed = append(restarted.state, event)
    assert replayed == restarted.state
    assert restarted.semantic_sha256 == written.semantic_sha256
    assert len(restarted.state["ledger"]) == 1
    assert restarted.state["ledger"][0]["previous_sha"] is None


def test_safety_validation_fails_closed_before_write(tmp_path):
    path = _store(tmp_path)
    snap = load_state(path)
    changed = copy.deepcopy(snap.state)
    changed["model_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="Frozen model identity changed"):
        write_state_cas(path, changed, expected_content_sha256=snap.content_sha256)

    assert load_state(path).content_sha256 == snap.content_sha256
    assert load_state(path).state["model_sha256"] == MODEL_SHA


def test_commissioning_probe_uses_isolated_copy_and_preserves_idle_runtime(tmp_path):
    source = _store(tmp_path)
    before = load_state(source)
    receipt = run_commissioning_probe(source, tmp_path / "probe")
    after = load_state(source)

    assert receipt["passed"] is True
    assert all(receipt["checks"].values())
    assert receipt["actual_runtime_state_mutated"] is False
    assert receipt["paper_trades_created"] == 0
    assert receipt["source_execution_ready"] is False
    assert receipt["source_performance_started_at"] is None
    assert after.content_sha256 == before.content_sha256
    assert after.state["ledger"] == []
