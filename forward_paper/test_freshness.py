import copy,json
from pathlib import Path
import pytest
from forward_paper.freshness import validate_derivative_freshness

P=Path('forward_paper/inputs/derivative_freshness_probe_20260922T0117HKT.json')


def load():
    return json.loads(P.read_text())


def check(p, **overrides):
    args=dict(
        symbol=p['symbol'],observed_at=p['observed_at_utc'],
        open_interest=p['open_interest'],top_accounts=p['top_accounts'],
        top_positions=p['top_positions'],all_accounts=p['all_accounts'],
        taker=p['taker'],funding=p['funding'],
    )
    args.update(overrides)
    return validate_derivative_freshness(**args)


def test_connected_probe_is_fresh_on_latest_common_timestamp():
    r=check(load())
    assert r['fresh'] is True
    assert r['latest_common_metric_utc']=='2026-09-21T17:10:00+00:00'
    assert r['common_metric_age_minutes']==pytest.approx(7.8374,abs=1e-4)
    assert r['latest_funding_utc']=='2026-09-21T16:00:00.002000+00:00'
    assert r['funding_age_minutes']==pytest.approx(77.8373666667,abs=1e-4)
    assert r['latest_funding_interval_hours']==pytest.approx(7.999999444444445,abs=1e-8)


def test_freshness_uses_common_metric_not_best_single_endpoint():
    p=load()
    # Position/account ratios reach 17:15, but OI+taker only reach 17:10.
    r=check(p)
    assert r['latest_by_family']['top_accounts']['timestamp_utc']=='2026-09-21T17:15:00+00:00'
    assert r['latest_by_family']['open_interest']['timestamp_utc']=='2026-09-21T17:10:00+00:00'
    assert r['latest_common_metric_utc']=='2026-09-21T17:10:00+00:00'


def test_stale_common_metric_fails_closed():
    p=load();p['observed_at_utc']='2026-09-21T17:26:00+00:00'
    with pytest.raises(ValueError,match='metric timestamp is stale'):
        check(p)


def test_future_endpoint_timestamp_fails_closed_even_if_common_is_old():
    p=load();p['top_accounts']=copy.deepcopy(p['top_accounts'])
    p['top_accounts'][-1]['timestamp']=1790011200000  # 17:20, later than captured observed_at.
    with pytest.raises(ValueError,match='future'):
        check(p)


def test_stale_funding_fails_closed_using_observed_interval():
    p=load();p['observed_at_utc']='2026-09-22T01:31:00+00:00'
    # Metric freshness would also be stale, so relax only that threshold to isolate funding.
    with pytest.raises(ValueError,match='funding history is stale'):
        check(p,metric_max_age_minutes=600)


def test_single_funding_row_cannot_claim_freshness():
    p=load()
    with pytest.raises(ValueError,match='two settled funding'):
        check(p,funding=p['funding'][-1:])
