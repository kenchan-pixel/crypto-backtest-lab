"""Durable paper-runtime state persistence primitives.

This module is deliberately market- and broker-agnostic: it performs no HTTP,
order, account, wallet or balance calls.  GitHub/runtime orchestration supplies
observations separately.  The store only validates and atomically persists the
paper state using an explicit compare-and-swap token.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forward_paper.core import ARMS, MODEL_SHA, append, canonical


class CASConflict(RuntimeError):
    """The durable state changed after the caller read it."""


@dataclass(frozen=True)
class StateSnapshot:
    state: dict[str, Any]
    content_sha256: str
    semantic_sha256: str


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def semantic_sha256(state: dict[str, Any]) -> str:
    return _sha256(canonical(state))


def validate_runtime_state(state: dict[str, Any]) -> None:
    if state.get("schema") != "eth-paper-v1":
        raise ValueError("Unexpected runtime schema")
    if state.get("model_sha256") != MODEL_SHA:
        raise ValueError("Frozen model identity changed")
    if state.get("live_orders_allowed") is not False:
        raise ValueError("Live orders must remain disabled")
    accounts = state.get("accounts")
    if not isinstance(accounts, dict) or set(accounts) != set(ARMS):
        raise ValueError("Runtime must contain exactly the three approved paper arms")
    for name in ARMS:
        account = accounts[name]
        if float(account.get("initial_virtual_usdt", 0.0)) != 10000.0:
            raise ValueError(f"Unexpected initial virtual capital for {name}")
        if int(account.get("trades", -1)) < 0:
            raise ValueError(f"Invalid trade count for {name}")
    if state.get("performance_started_at") is None and state.get("execution_ready") is True:
        raise ValueError("Execution cannot be ready before performance start")


def encode_state(state: dict[str, Any]) -> bytes:
    validate_runtime_state(state)
    return (json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def load_state(path: str | Path) -> StateSnapshot:
    p = Path(path)
    raw = p.read_bytes()
    state = json.loads(raw.decode("utf-8"))
    validate_runtime_state(state)
    return StateSnapshot(state=state, content_sha256=_sha256(raw), semantic_sha256=semantic_sha256(state))


def write_state_cas(path: str | Path, new_state: dict[str, Any], *, expected_content_sha256: str) -> StateSnapshot:
    """Atomically replace *path* only when its exact bytes still match expectation.

    This is a local durable-store primitive.  The GitHub contents API adds a
    second repository-level CAS boundary by requiring the current blob SHA on
    update.  Callers must re-read and reconcile after CASConflict; never retry
    by blindly overwriting a newer state.
    """
    p = Path(path)
    current = load_state(p)
    if current.content_sha256 != expected_content_sha256:
        raise CASConflict(
            f"stale runtime state: expected {expected_content_sha256}, current {current.content_sha256}"
        )

    raw = encode_state(new_state)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, p)
        try:
            dir_fd = os.open(str(p.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Some filesystems do not support directory fsync.  The file fsync
            # and atomic replace above still preserve the fail-closed CAS rule.
            pass
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return load_state(p)


def _paper_trade_count(state: dict[str, Any]) -> int:
    return sum(int(state["accounts"][name].get("trades", 0)) for name in ARMS)


def run_commissioning_probe(source_state_path: str | Path, work_dir: str | Path) -> dict[str, Any]:
    """Exercise CAS/restart semantics on an isolated byte-for-byte state copy.

    The source runtime is never written.  Probe events live only in the
    temporary copy and are engineering evidence, not forward observations.
    """
    source_path = Path(source_state_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    source_before = load_state(source_path)

    if source_before.state.get("status") != "COMMISSIONING":
        raise ValueError("This commissioning probe may only run while status=COMMISSIONING")
    if source_before.state.get("execution_ready") is not False:
        raise ValueError("Commissioning runtime unexpectedly execution-ready")
    if source_before.state.get("performance_started_at") is not None:
        raise ValueError("Commissioning runtime already has a performance start")
    if _paper_trade_count(source_before.state) != 0:
        raise ValueError("Commissioning source state unexpectedly contains closed paper trades")

    isolated = work / "state.json"
    shutil.copyfile(source_path, isolated)
    reader_a = load_state(isolated)
    reader_b = load_state(isolated)

    probe_a = {
        "event_id": "commissioning-cas-probe-a",
        "kind": "commissioning_probe",
        "scope": "isolated_copy_only",
    }
    next_a = append(reader_a.state, probe_a)
    written = write_state_cas(isolated, next_a, expected_content_sha256=reader_a.content_sha256)

    restarted = load_state(isolated)
    replayed = append(restarted.state, probe_a)
    restart_idempotent = replayed == restarted.state

    stale_writer_rejected = False
    probe_b = {
        "event_id": "commissioning-cas-probe-b",
        "kind": "commissioning_probe",
        "scope": "isolated_copy_only",
    }
    try:
        write_state_cas(
            isolated,
            append(reader_b.state, probe_b),
            expected_content_sha256=reader_b.content_sha256,
        )
    except CASConflict:
        stale_writer_rejected = True

    final_copy = load_state(isolated)
    source_after = load_state(source_path)
    source_unchanged = source_after.content_sha256 == source_before.content_sha256
    probe_a_present = "commissioning-cas-probe-a" in final_copy.state.get("processed_events", {})
    probe_b_absent = "commissioning-cas-probe-b" not in final_copy.state.get("processed_events", {})
    safety_fields_preserved = all(
        final_copy.state.get(key) == source_before.state.get(key)
        for key in ("status", "execution_ready", "performance_started_at", "live_orders_allowed", "model_sha256", "accounts", "parent_busy_until", "decision")
    )

    checks = {
        "atomic_cas_write_succeeded": written.content_sha256 == restarted.content_sha256,
        "stale_writer_rejected": stale_writer_rejected,
        "restart_replay_idempotent": restart_idempotent,
        "winning_probe_present": probe_a_present,
        "losing_stale_probe_absent": probe_b_absent,
        "runtime_safety_fields_preserved": safety_fields_preserved,
        "source_runtime_bytes_unchanged": source_unchanged,
    }
    if not all(checks.values()):
        raise AssertionError(f"CAS commissioning probe failed: {checks}")

    return {
        "schema": "eth-paper-runtime-store-commissioning-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "scope": "durable CAS/restart/idempotency foundation only; isolated-copy probe, no fill integration",
        "source_state_path": str(source_path),
        "source_content_sha256": source_before.content_sha256,
        "source_semantic_sha256": source_before.semantic_sha256,
        "source_status": source_before.state["status"],
        "source_execution_ready": source_before.state["execution_ready"],
        "source_performance_started_at": source_before.state["performance_started_at"],
        "source_paper_closed_trades": _paper_trade_count(source_before.state),
        "checks": checks,
        "temporary_copy_initial_content_sha256": reader_a.content_sha256,
        "temporary_copy_after_cas_content_sha256": final_copy.content_sha256,
        "actual_runtime_state_mutated": False,
        "paper_trades_created": 0,
        "real_orders_created": 0,
        "order_account_endpoints_used": False,
        "gate_effect": "none; runtime/fill readiness remains incomplete and execution_ready must remain false",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Commission paper-runtime CAS persistence on an isolated state copy")
    parser.add_argument("--state", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    receipt = run_commissioning_probe(args.state, args.work_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
