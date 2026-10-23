import numpy as np
import pandas as pd
import pytest
from adaptive_research.study import (account, cost_return, split_masks, model, make_schedule,
                                    inference, holm, match_weight, TZ)

def fixture():
    a=pd.Timestamp('2025-01-01',tz=TZ);b=a+pd.Timedelta(days=4)
    ts=pd.date_range(a,b,freq='h').union(pd.date_range(a,b-pd.Timedelta(hours=1),freq='h')+pd.Timedelta(minutes=1)).union(pd.DatetimeIndex([b-pd.Timedelta(minutes=1)]))
    px=pd.Series(100.,index=ts)
    en=a+pd.Timedelta(minutes=1);ex=en+pd.Timedelta(hours=24)
    schedule=pd.DataFrame([dict(entry_hkt=en,exit_hkt=ex,weight=.4)])
    return a,b,px,schedule

def test_exact_fractional_costs():
    a,b,p,s=fixture();m,r,t=account(p,a,b,s,.001,.0005)
    assert m['net_return']==pytest.approx(.4*cost_return(0,.001,.0005))
    assert t.net_account_return.iloc[0]==pytest.approx(m['net_return'])
    assert m['max_drawdown']==pytest.approx(m['net_return'])

def test_cash_zero_signals_schema():
    a,b,p,s=fixture();m,r,t=account(p,a,b,s.iloc[:0],.001,.0005)
    assert m['trades']==0 and m['net_return']==0 and m['max_drawdown']==0
    assert m['win_rate'] is None and m['profit_factor'] is None
    assert len(t)==0 and {'cash_after','net_account_return'}<=set(t.columns)
    assert (r==0).all()

def test_all_zero_accounts_no_missing_fields():
    a,b,p,s=fixture()
    rows=[account(p,a,b,s.iloc[:0],.001,.0005)[0] for _ in range(4)]
    d=pd.DataFrame(rows)
    assert (d.trades==0).all() and (d.net_return==0).all() and 'best_trade_removed' in d

def test_passive_fraction_and_risk_match():
    a,b,p,s=fixture();p.iloc[10:]=120
    mf,rf,_=account(p,a,b,s.iloc[:0],.001,.0005,passive=1)
    mh,rh,_=account(p,a,b,s.iloc[:0],.001,.0005,passive=.5)
    assert mh['net_return']==pytest.approx(.5*mf['net_return'])
    assert match_weight(rf,mh['volatility_ann'])==pytest.approx(.5,abs=1e-8)

def test_overlap_rejected():
    a,b,p,s=fixture();s=pd.concat([s,s],ignore_index=True)
    with pytest.raises(ValueError,match='Overlapping'):account(p,a,b,s,.001,.0005)

def test_no_same_minute_reentry():
    a,b,p,s=fixture();r=s.iloc[0].copy();r['entry_hkt']=s.exit_hkt.iloc[0];r['exit_hkt']=r.entry_hkt+pd.Timedelta(hours=24)
    with pytest.raises(ValueError,match='Overlapping'):account(p,a,b,pd.concat([s,r.to_frame().T]),.001,.0005)

def test_fractional_account_up_move():
    a,b,p,s=fixture();p.loc[p.index>=s.exit_hkt.iloc[0]]=110
    m,_,_=account(p,a,b,s,.001,.0005)
    assert m['net_return']==pytest.approx(.4*cost_return(.1,.001,.0005))

def test_temporal_purge_train_cal_eval():
    ix=pd.date_range('2024-01-01','2025-01-02',freq='6h',tz=TZ);y=pd.Series(0.,index=ix)
    month=pd.Timestamp('2025-01-01',tz=TZ);tr,ca=split_masks(ix,np.ones(len(ix),bool),y,month)
    assert ix[tr].max()+pd.Timedelta(hours=24,minutes=1)<ix[ca].min()
    assert ix[ca].max()+pd.Timedelta(hours=24,minutes=1)<month
    y.loc[y.index>=month]=1000
    t2,c2=split_masks(ix,np.ones(len(ix),bool),y,month)
    assert np.array_equal(tr,t2) and np.array_equal(ca,c2)

def test_future_prices_cannot_change_past_nav():
    a,b,p,s=fixture();_,r,_=account(p,a,b,s,.001,.0005)
    pp=p.copy();pp.loc[pp.index>=a+pd.Timedelta(days=3)]=10000
    _,r2,_=account(pp,a,b,s,.001,.0005)
    pd.testing.assert_series_equal(r,r2)

def test_future_pred_cannot_change_past_schedule():
    ix=pd.date_range('2025-01-01',periods=144,freq='h',tz=TZ)
    raw=pd.DataFrame({'execution_open':100.},index=ix)
    pred=pd.DataFrame({'decision_hkt':ix[::6],'eligible_signal':True,'score':.02,'threshold':.01})
    vol=pd.Series(.5,index=ix)
    pred=pred[pred.decision_hkt<=ix[-25]]
    a=make_schedule(raw,pred,vol,2025,.2)
    p2=pred.copy();cut=ix[72];p2.loc[p2.decision_hkt>=cut,'eligible_signal']=False
    b=make_schedule(raw,p2,vol,2025,.2)
    pd.testing.assert_frame_equal(a[a.entry_hkt<cut].reset_index(drop=True),b[b.entry_hkt<cut].reset_index(drop=True))
    assert (a.weight==.4).all()

def test_bootstrap_and_holm():
    assert inference(np.zeros(257),reps=99)['p']==1
    assert inference(np.ones(257)*.001,reps=99)['p']==.01
    assert list(holm([.001,.02,.1]))==pytest.approx([.003,.04,.1])

def test_no_autostopping_or_refit_sweep():
    m=model();assert m.early_stopping is False and m.max_iter==100 and m.min_samples_leaf==60
