"""Bounded second qualifying current receipt wrapper.

Reuses the already-tested persisted extension pipeline unchanged for evidence
construction, then labels only the commissioning ordinal/gate effect. No source
value, model input, candidate, fill or performance field is modified.
"""
from __future__ import annotations
import argparse
import contextlib
import io
import json
from pathlib import Path

from .persisted_extension_pipeline import run as run_extension

MODEL_SHA = "08f2ba34b48d2aa5925af90c13452a34efbb0dc0f88d4694caa330bdf832c3fe"


def run(base_dir, fresh_dir, macro_capture, out_path):
    tmp = Path(str(out_path) + ".inner")
    # The shared pipeline currently labels any qualifying run as Receipt 1.
    # Suppress that intermediate presentation; preserve its evidence verbatim
    # and only correct the ordinal after all fail-closed checks have passed.
    with contextlib.redirect_stdout(io.StringIO()):
        receipt = run_extension(
            base_dir,
            fresh_dir,
            macro_capture,
            tmp,
            qualifying_current=True,
        )
    if not receipt.get("passed") or not receipt.get("qualifying_current_receipt"):
        raise ValueError("Underlying qualifying current pipeline did not pass")
    if receipt.get("model_sha256") != MODEL_SHA:
        raise ValueError("Frozen model identity changed")
    if receipt.get("paper_trades_created") != 0 or receipt.get("performance_started") is not False:
        raise ValueError("Receipt 2 commissioning boundary violated")
    if receipt.get("order_account_endpoints_used") is not False:
        raise ValueError("Forbidden account/order endpoint evidence")
    if receipt.get("raw_source_values_rewritten") is not False:
        raise ValueError("Raw source values were rewritten")

    receipt = dict(receipt)
    receipt["schema"] = "eth-forward-persisted-extension-receipt-v3"
    receipt["scope"] = (
        "Second independently timed qualifying current causal source-to-feature-to-opportunity "
        "receipt from immutable staging base plus genuinely fresh connected Binance public "
        "read-only extension. No fill/performance."
    )
    receipt["qualifying_current_receipt_number"] = 2
    receipt["gate_effect"] = (
        "Receipt 2 of 2 required current full-pipeline observations passed. This is sufficient "
        "evidence to promote only source_freshness/live_feature_parity after the receipt is "
        "saved and verified; execution_ready and performance_started remain blocked pending "
        "durable runtime/fill integration and actual initial weekly decisions."
    )
    Path(out_path).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    tmp.unlink(missing_ok=True)
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", required=True)
    p.add_argument("--fresh-dir", required=True)
    p.add_argument("--macro-capture", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(a.base_dir, a.fresh_dir, a.macro_capture, a.out)
