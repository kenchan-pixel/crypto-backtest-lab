"""Synthetic prices below are only unit-test fixtures, never research evidence."""
import numpy as np
import pandas as pd
import pytest
from benchmark_review.analyze import (TZ, after_cost, replay, matched_weight, holm,
                                      paired_inference, random_schedules)

def data(days=120):
    a=pd.Timestamp('2025-01-01',tz=TZ);b=a+pd.Timedelta(days=days)
    ix=pd.date_range(a,b,freq='h')
    raw=pd.DataFrame({'close':np.full(len(ix),100.),'execution_open':np.full(len(ix),100.)},index=ix)
    px=raw.close.copy();op=raw.execution_open.iloc[:-1].copy();op.index+=pd.Timedelta(minutes=1)
    px=pd.concat([px,op,pd.Series([100.],index=[b-pd.Timedelta(minutes=1)])]).sort_index()
    tr=pd.DataFrame({'entry_hkt':[a+pd.Timedelta(hours=3,minutes=1)],'exit_hkt':[a+pd.Timedelta(hours=27,minutes=1)]})
    return raw,px,tr,a,b

def test_fee_identity_and_passive_linearity():
    _,px,tr,a,b=data()
    full=replay(px,a,b,tr,.001,.0005,initial_weight=1)
    quarter=replay(px,a,b,tr,.001,.0005,initial_weight=.25)
    cash=replay(px,a,b,tr,.001,.0005,initial_weight=0)
    assert full.metrics['net_return']==pytest.approx(after_cost(0,.001,.0005))
    assert quarter.metrics['net_return']==pytest.approx(full.metrics['net_return']*.25)
    assert cash.metrics['net_return']==0 and cash.metrics['max_drawdown']==0
    np.testing.assert_allclose(quarter.nav, .75+.25*full.nav)

def test_trade_replay_and_full_calendar_cash_days():
    _,px,tr,a,b=data();r=replay(px,a,b,tr,.001,.0005)
    assert r.metrics['net_return']==pytest.approx(after_cost(0,.001,.0005))
    assert len(r.daily_returns)==120
    assert np.count_nonzero(r.daily_returns)==2
    assert r.metrics['average_coin_weight']==pytest.approx(1/120)

def test_zero_trade_schema_safe():
    _,px,tr,a,b=data();r=replay(px,a,b,tr.iloc[:0],.001,.0005)
    assert r.metrics['net_return']==0 and r.metrics['volatility_ann']==0
    assert r.metrics['sharpe_zero_yield'] is None

def test_future_price_changes_do_not_affect_past_nav():
    _,px,tr,a,b=data();r=replay(px,a,b,tr,.001,.0005)
    new=px.copy();new.loc[new.index>a+pd.Timedelta(days=60)]*=5
    n=replay(new,a,b,tr,.001,.0005)
    pd.testing.assert_series_equal(r.nav.loc[:a+pd.Timedelta(days=60)],n.nav.loc[:a+pd.Timedelta(days=60)])

def test_overlap_and_wrong_duration_rejected():
    _,px,tr,a,b=data()
    bad=pd.concat([tr,tr],ignore_index=True)
    with pytest.raises(ValueError,match='Overlapping'):replay(px,a,b,bad,.001,.0005)
    bad=tr.copy();bad.exit_hkt+=pd.Timedelta(hours=1)
    with pytest.raises(ValueError,match='holding'):replay(px,a,b,bad,.001,.0005)

def test_risk_weight_solution_only_target_not_return():
    _,px,tr,a,b=data();px*=np.exp(.08*np.sin(np.arange(len(px))*.023))
    full=replay(px,a,b,tr,.001,.0005,initial_weight=1.)
    part=replay(px,a,b,tr,.001,.0005,initial_weight=.37)
    w=matched_weight(full,part.metrics['volatility_ann'],a,b)
    assert w==pytest.approx(.37,abs=1e-10)

def test_holm_and_centered_bootstrap():
    np.testing.assert_allclose(holm([.001,.02,.20]),[.003,.04,.20])
    z=paired_inference(np.zeros(257),reps=100)
    pos=paired_inference(np.full(257,.01),reps=100)
    neg=paired_inference(np.full(257,-.01),reps=100)
    assert z['p_centered_one_sided']==1 and neg['p_centered_one_sided']==1
    assert pos['p_centered_one_sided']==pytest.approx(1/101)

def test_random_controls_flat_prices_exact_same_turnover():
    raw,_,tr,a,b=data(365)
    tr=pd.concat([tr,tr+pd.Timedelta(days=60),tr+pd.Timedelta(days=170)],ignore_index=True)
    rr,meta=random_schedules(raw,2025,tr,.001,.0005,reps=50)
    expected=(1+after_cost(0,.001,.0005))**3-1
    np.testing.assert_allclose(rr,expected,atol=1e-12)
    assert meta['minimum_gap_hours']>24 and meta['trades_per_replicate']==3
