import json
from pathlib import Path
import pytest
from forward_paper.freshness import validate_derivative_freshness
from forward_paper.live_sources import normalize_metric_bundle, normalize_funding_history


def latest():
    paths=sorted(Path('forward_paper/inputs').glob('connected_binance_snapshot_*.json'))
    assert paths
    return paths[-1],json.loads(paths[-1].read_text())


def test_snapshot_is_paper_only_and_provenanced():
    _,s=latest()
    assert s['schema']=='eth-connected-binance-snapshot-v1'
    assert s['source']=='Connected Binance public read-only market-data tools'
    assert s['symbol']=='ETHUSDT' and s['period']=='5m'
    assert s['order_or_account_endpoints_used'] is False
    assert s['paper_trades_created']==0 and s['performance_started'] is False


def test_snapshot_normalizes_exact_common_rows():
    _,s=latest()
    m=normalize_metric_bundle(symbol=s['symbol'],period=s['period'],open_interest=s['open_interest'],
        top_accounts=s['top_accounts'],top_positions=s['top_positions'],all_accounts=s['all_accounts'],taker=s['taker'])
    assert len(m)==2
    assert m.index[-1].isoformat()=='2026-09-21T22:10:00+00:00'
    f=normalize_funding_history(s['symbol'],s['funding'])
    assert len(f)==5


def test_snapshot_was_fresh_at_actual_observation():
    _,s=latest()
    r=validate_derivative_freshness(symbol=s['symbol'],observed_at=s['observed_after_reads_utc'],
        open_interest=s['open_interest'],top_accounts=s['top_accounts'],top_positions=s['top_positions'],
        all_accounts=s['all_accounts'],taker=s['taker'],funding=s['funding'])
    assert r['fresh'] is True
    assert r['latest_common_metric_utc']=='2026-09-21T22:10:00+00:00'
    assert r['common_metric_age_minutes']==pytest.approx(s['latest_common_metric_age_minutes_at_observation'])


def test_missing_family_fails_closed():
    _,s=latest()
    with pytest.raises(ValueError):
        validate_derivative_freshness(symbol=s['symbol'],observed_at=s['observed_after_reads_utc'],
            open_interest=s['open_interest'],top_accounts=s['top_accounts'],top_positions=[],
            all_accounts=s['all_accounts'],taker=s['taker'],funding=s['funding'])
