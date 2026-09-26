"""Synthetic prices ONLY for code tests, never for research evidence."""
import json
import numpy as np
import pandas as pd
import pytest
from ai_overlay import session
from ai_overlay.analyze import allocation,weighted_replay,verify_ledger
from benchmark_review.analyze import after_cost

def example():
    a=pd.Timestamp('2025-01-01',tz='Asia/Hong_Kong');b=a+pd.Timedelta(days=4)
    idx=pd.date_range(a,b,freq='h').union(pd.DatetimeIndex([a+pd.Timedelta(hours=1,minutes=1),a+pd.Timedelta(hours=25,minutes=1)]))
    prices=pd.Series(100.,index=idx.sort_values())
    trades=pd.DataFrame([{'entry_hkt':str(a+pd.Timedelta(hours=1,minutes=1)), 'exit_hkt':str(a+pd.Timedelta(hours=25,minutes=1))}])
    return prices,a,b,trades

@pytest.mark.parametrize('weight',[0,.5,1])
def test_weighted_flat_cost(weight):
    p,a,b,t=example();nav,tr,m=weighted_replay(p,a,b,t,[weight],[None],.001,.0005)
    expected=weight*after_cost(0,.001,.0005)
    assert m['net_return']==pytest.approx(expected)
    assert m['trades']==int(weight>0)
    assert m['max_drawdown']==pytest.approx(expected)
    assert m['held_time_fraction']==pytest.approx(.25 if weight else 0)

def test_empty_is_complete_schema():
    p,a,b,t=example();nav,tr,m=weighted_replay(p,a,b,t.iloc[:0],[],[],.001,.0005)
    assert m['trades']==0 and m['net_return']==0 and m['profit_factor_realized_pnl'] is None
    assert {'win_rate','mean_account_trade_return','median_account_trade_return','max_drawdown','best_trade_removed_return'}<=set(m)
    assert nav.daily_returns.eq(0).all()

def test_same_minute_overlap_rejected():
    p,a,b,t=example();t=pd.concat([t,t])
    with pytest.raises(ValueError,match='overlap'):weighted_replay(p,a,b,t,[1,1],[None,None],.001,.0005)

def test_missing_fill_rejected():
    p,a,b,t=example();p=p.drop(pd.Timestamp(t.entry_hkt.iloc[0]))
    with pytest.raises(ValueError,match='Missing'):weighted_replay(p,a,b,t,[1],[None],.001,.0005)

def test_weight_bounds():
    p,a,b,t=example()
    with pytest.raises(ValueError,match='allocation'):weighted_replay(p,a,b,t,[1.5],[None],0,0)

def test_future_price_does_not_change_past_nav():
    p,a,b,t=example();v1,_,_=weighted_replay(p,a,b,t,[1],[None],.001,.0005)
    change=a+pd.Timedelta(hours=26);p2=p.copy();p2.loc[change:]*=2
    v2,_,_=weighted_replay(p2,a,b,t,[1],[None],.001,.0005)
    pd.testing.assert_series_equal(v1.nav.loc[:change-pd.Timedelta(hours=1)],v2.nav.loc[:change-pd.Timedelta(hours=1)])

def test_partial_weight_realized_pnl_not_return_sum():
    p,a,b,t=example();ex=pd.Timestamp(t.exit_hkt.iloc[0]);p.loc[ex:]=110.
    nav,tr,m=weighted_replay(p,a,b,t,[.5],[4],.001,.0005)
    asset=after_cost(.10,.001,.0005)
    assert tr.iloc[0].net_asset_return==pytest.approx(asset)
    assert tr.iloc[0].account_return==pytest.approx(.5*asset)
    assert tr.iloc[0].realized_pnl==pytest.approx(nav.nav.iloc[-1]-1)
    assert tr.iloc[0].decision_step==4

def test_effective_time_lag():
    a=pd.Timestamp('2025-01-01',tz='Asia/Hong_Kong')
    mapping=[{'year':2025,'effective':str(a+pd.Timedelta(hours=1)),'step':1,'simple_weight':1}]
    ds=[{'weight':0}]
    assert allocation(a+pd.Timedelta(minutes=1),2025,'LLM',mapping,ds)==(.5,None)
    assert allocation(a+pd.Timedelta(hours=1),2025,'LLM',mapping,ds)==(0,1)
    assert allocation(a+pd.Timedelta(hours=1),2025,'Simple',mapping,ds)==(1,1)

def test_year_start_does_not_inherit_prior_year_choice():
    a=pd.Timestamp('2026-01-01',tz='Asia/Hong_Kong')
    mapping=[{'year':2025,'effective':str(a-pd.Timedelta(days=5)),'step':1,'simple_weight':1}]
    assert allocation(a+pd.Timedelta(minutes=1),2026,'LLM',mapping,[{'weight':0}])==(.5,None)

def test_full_ledger_hash_chain_and_coverage():
    m,d,proof=verify_ledger(); assert len(d)==91 and proof['hash_chain_valid']

def test_locked_recorder_does_not_append():
    before=(session.ROOT/'ledger/decisions.jsonl').read_bytes()
    with pytest.raises(ValueError,match='locked'):session.record(1,'Do not overwrite stored decisions')
    assert (session.ROOT/'ledger/decisions.jsonl').read_bytes()==before

def test_locked_packets_cannot_reinitialize():
    with pytest.raises(ValueError,match='append-only'):session.init()
