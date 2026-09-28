import json
from pathlib import Path

import pandas as pd
import pytest

from forward_paper.live_parity_contract import (
    ALL_COLUMNS,
    FROZEN_MODEL_SHA256,
    merge_archive_connected_metrics,
    validate_dependency_proof,
)


def archive_frame(start="2026-09-21T00:00Z", periods=8):
    idx = pd.date_range(start, periods=periods, freq="5min", tz="UTC")
    data = {}
    for j, col in enumerate(ALL_COLUMNS):
        data[col] = [100.0 + j + i / 10_000 for i in range(periods)]
    # Connected top-position endpoint publishes four decimals. Keep the archive
    # value inside the evidenced half-LSU interval for the positive path.
    data["sum_toptrader_long_short_ratio"] = [1.20001 + i / 10_000 for i in range(periods)]
    return pd.DataFrame(data, index=idx, dtype=float)


def connected_from_archive(archive, rows=4):
    source = archive.iloc[-rows:].copy()
    connected = source.copy()
    connected.index = connected.index + pd.Timedelta(minutes=5)
    connected["sum_toptrader_long_short_ratio"] = (
        connected["sum_toptrader_long_short_ratio"].round(4)
    )
    return connected


def test_dependency_proof_is_pinned_to_frozen_model_and_invariance_receipt():
    proof = validate_dependency_proof()
    assert proof["frozen_model_sha256"] == FROZEN_MODEL_SHA256
    assert proof["taker_enters_frozen_decision"] is False


def test_taker_value_mismatch_does_not_override_proved_decision_dependency():
    archive = archive_frame()
    connected = connected_from_archive(archive)
    connected["sum_taker_long_short_vol_ratio"] = 999.0
    merged, gap, overlap = merge_archive_connected_metrics(archive, connected)
    contract = merged.attrs["live_parity_contract"]
    assert overlap == 4 and gap == 5
    assert contract["taker_value_semantics_resolved"] is False
    assert contract["non_decision_columns_value_parity_asserted"] is False
    assert contract["taker_live_values_quarantined_from_decision_matrix"] is True
    assert merged.loc[connected.index[-1] - pd.Timedelta(minutes=5), "sum_taker_long_short_vol_ratio"] != 999.0
    assert pd.isna(merged.loc[connected.index[-1] - pd.Timedelta(minutes=5), "sum_taker_long_short_vol_ratio"])


def test_open_interest_mismatch_fails_closed():
    archive = archive_frame()
    connected = connected_from_archive(archive)
    connected.iloc[0, connected.columns.get_loc("sum_open_interest")] += 1.0
    with pytest.raises(ValueError, match="sum_open_interest"):
        merge_archive_connected_metrics(archive, connected)


def test_top_position_outside_evidence_precision_interval_fails_closed():
    archive = archive_frame()
    connected = connected_from_archive(archive)
    connected.iloc[0, connected.columns.get_loc("sum_toptrader_long_short_ratio")] += 0.001
    with pytest.raises(ValueError, match="top-position"):
        merge_archive_connected_metrics(archive, connected)


def test_changed_dependency_receipt_fails_closed(tmp_path):
    source = json.loads(Path("forward_paper/receipts/taker_decision_invariance_20260922T134155Z.json").read_text())
    source["dependency_proof"]["taker_enters_frozen_state"] = True
    receipt = tmp_path / "bad_receipt.json"
    receipt.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="dependency proof"):
        validate_dependency_proof(dependency_receipt_path=receipt)


def test_missing_required_metric_family_fails_closed():
    archive = archive_frame()
    connected = connected_from_archive(archive).drop(columns=["sum_taker_long_short_vol_ratio"])
    with pytest.raises(ValueError, match="columns missing"):
        merge_archive_connected_metrics(archive, connected)
