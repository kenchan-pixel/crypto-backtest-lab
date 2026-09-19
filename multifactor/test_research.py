"""Synthetic fixtures only: not market evidence, not in exported performance tables."""
import numpy as np
import pandas as pd
from pathlib import Path
import pytest
from multifactor.data import build_features,make_event_file,event_features,labels,period_mask,TZ
from multifactor.evidence import holm,nonoverlap,matched_lift,condition_mask
from multifactor.study import diagnostic_account,score

def fixture():
    idx=pd.date_range('2023-11-01',periods=2100,freq='h',tz=TZ)
    c=100+np.arange(len(idx))*.02+np.sin(np.arange(len(idx))/7)
    f=pd.DataFrame({'open':c-.01,'high':c+.2,'low':c-.2,'close':c,'volume':100.,
      'quote_volume':100*c,'taker_quote':55*c,'minutes':60,
      'execution_open':c,'execution_ms':idx.asi8//1_000_000+60000,'execution_delay_min':0},index=idx)
    return f

def test_future_price_cannot_change_past_features(tmp_path):
    f=fixture();e=make_event_file(tmp_path/'e.csv');old,g=build_features(f,f.copy(),e)
    ch=f.copy();ch.iloc[1500:,:5]*=2
    new,_=build_features(ch,f.copy(),e)
    pd.testing.assert_frame_equal(old.iloc[:1500],new.iloc[:1500])
    assert 'execution_open' not in old and len(set(g.values()))==5

def test_incomplete_4h_not_visible(tmp_path):
    f=fixture();e=make_event_file(tmp_path/'e.csv')
    t=pd.Timestamp('2024-01-15 13:00',tz=TZ)
    original,_=build_features(f,f,e)
    ch=f.copy();ch.loc[t,['open','high','low','close']]*=1.2
    new,_=build_features(ch,ch,e)
    cols=[c for c in original if c.startswith('completed_4h')]
    pd.testing.assert_series_equal(original.loc[t,cols],new.loc[t,cols])

def test_fomc_delay_and_dst(tmp_path):
    e=make_event_file(tmp_path/'e.csv')
    assert len(e)==22 and len(e[e.role=='research'])==21
    date=e[e.event_id=='20240918'].iloc[0]
    t=pd.Timestamp(date.release_utc).tz_convert(TZ)
    ix=pd.DatetimeIndex([t-pd.Timedelta(hours=1),t,t+pd.Timedelta(hours=1)])
    x=event_features(ix,e)
    assert x.fomc_rate_upper.tolist()==[5.5,5.5,5.0]
    assert pd.Timestamp(date.release_utc).hour==18
    assert pd.Timestamp(e[e.event_id=='20241218'].iloc[0].release_utc).hour==19

def test_label_uses_later_execution_not_same_close():
    f=fixture();r,y=labels(f)
    assert r.iloc[100]==pytest.approx(f.execution_open.iloc[124]/f.execution_open.iloc[100]-1)
    assert y.iloc[-24:].isna().all()
    f.loc[f.index[124],'execution_ms']+=60000
    r,_=labels(f);assert np.isnan(r.iloc[100])

def test_purge_boundary():
    idx=pd.date_range('2024-12-29','2025-01-02',freq='h',tz=TZ)
    r=pd.Series(0.,index=idx);mask=period_mask(idx,r,2024)
    assert idx[mask][-1] < pd.Timestamp('2025-01-01',tz=TZ)-pd.Timedelta(hours=25)

def test_round_trip_and_no_reentry():
    f=fixture();f['execution_open']=100.;f['close']=100.
    mask=np.zeros(len(f),dtype=bool);mask[100:128]=True
    m,tr=diagnostic_account(f,mask,.001,.0005)
    expect=(1-.001)*(1-.0005)/((1+.001)*(1+.0005))-1
    assert len(tr)==2 and tr.net_return.iloc[0]==pytest.approx(expect)
    assert m['net_return']==pytest.approx((1+expect)**2-1)
    assert pd.Timestamp(tr.iloc[1].entry_hkt)>pd.Timestamp(tr.iloc[0].exit_hkt)

def test_matched_lift_and_holm():
    mask=np.array([True]*10+[False]*100);y=np.r_[np.ones(6),np.zeros(4),np.ones(30),np.zeros(70)]
    s=pd.Series(['same']*110);l,ps,pc,cov=matched_lift(mask,y,s)
    assert l==pytest.approx(.3) and cov==1
    assert holm([.001,.02,.1]).tolist()==pytest.approx([.003,.04,.1])

def test_nonoverlap_and_scores():
    ix=pd.date_range('2024-01-01',periods=100,freq='h');take=np.ones(100,dtype=bool)
    assert nonoverlap(ix,take).tolist()==[0,24,48,72,96]
    y=np.tile([0,1,2],10);p=np.tile([1/3]*3,(30,1));s=score(y,p)
    assert s['multiclass_brier']==pytest.approx(2/3)
