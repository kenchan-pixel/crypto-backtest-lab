import json
from pathlib import Path

import pytest

from forward_paper import taker_decision_invariance as tdi

TAKER = Path('forward_paper/inputs/connected_binance_full_20260922T072853HKT/taker.json')
MODEL = Path('forward_paper/model.json')


def test_dependency_set_excludes_taker():
    assert tdi.state_derivative_inputs() == tdi.REQUIRED_STATE_D_INPUTS
    model = json.loads(MODEL.read_text())
    assert tdi.model_mentions_taker(model) == []


def test_real_connected_taker_is_decision_invariant():
    receipt = tdi.validate(TAKER, MODEL)
    dynamic = receipt['dynamic_invariance']
    assert receipt['conclusion']['frozen_decision_invariant_to_taker'] is True
    assert receipt['conclusion']['taker_source_semantics_resolved'] is False
    assert dynamic['state_value_mismatches'] == 0
    assert dynamic['catalyst_stream_mismatches'] == 0
    assert dynamic['candidate_feature_mismatches'] == 0
    assert dynamic['max_prediction_abs_delta'] == 0.0
    assert dynamic['threshold_decision_mismatches'] == 0
    assert dynamic['parent_opportunity_mismatches'] == 0
    assert receipt['paper_trades_created'] == 0
    assert receipt['gate_promotion'] is False


def test_hash_guard_fails_closed(tmp_path):
    altered = tmp_path / 'taker.json'
    altered.write_bytes(TAKER.read_bytes() + b' ')
    with pytest.raises(AssertionError, match='hash changed'):
        tdi.validate(altered, MODEL)
