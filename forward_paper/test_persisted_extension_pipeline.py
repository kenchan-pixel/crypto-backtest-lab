import copy
import pytest
from forward_paper.persisted_pipeline import load_snapshot
from forward_paper.persisted_extension_pipeline import merge_raw_exact,METRIC_KEYS

BASE='forward_paper/inputs/connected_binance_full_20260922T072853HKT'
FRESH='forward_paper/inputs/connected_binance_fresh_20260922T080126HKT'

def test_fresh_extension_is_hash_locked_and_actually_fresh_at_capture():
    _,_,base,_=load_snapshot(BASE)
    m,seen,fresh,_=load_snapshot(FRESH)
    assert seen.isoformat()=='2026-09-22T00:01:26.073897+00:00'
    assert m['capture_mode']=='fresh_incremental_extension'
    assert m['intended_bridge_range']['common_latest_age_minutes_at_first_seen'] < 15
    assert m['intended_bridge_range']['funding_latest_age_minutes_at_first_seen'] < 15
    combined,overlap=merge_raw_exact(base,fresh)
    assert all(overlap[k] >= 16 for k in METRIC_KEYS)
    assert overlap['funding'] >= 3
    assert min(r['timestamp'] for r in fresh['open_interest']) <= 1790028000000
    assert max(r['timestamp'] for r in combined['taker']) == 1790034900000
    assert max(r['fundingTime'] for r in combined['funding']) == 1790035200000

def test_conflicting_overlap_fails_closed():
    _,_,base,_=load_snapshot(BASE);_,_,fresh,_=load_snapshot(FRESH)
    bad=copy.deepcopy(fresh)
    bad['top_positions'][0]['longShortRatio']='999'
    with pytest.raises(ValueError,match='Conflicting base/fresh raw overlap'):
        merge_raw_exact(base,bad)
