import numpy as np
import pandas as pd
import pytest
from multifactor.evidence import cluster_inference,matched_lift,holm
from derivatives.features import asof_past,build_derivatives,RATIO_COLS
from derivatives.study import paired_loss_test

def fixture(weeks=20):
    index=pd.date_range('2024-01-01',periods=weeks*168,freq='h',tz='UTC')
    mask=np.arange(len(index))%2==0
    strata=pd.Series('s',index=index)
    return index,mask,strata

def test_cluster_zero_lift():
    i,m,s=fixture();result=cluster_inference(i,m,np.zeros(len(i)),s)
    assert result['p']==1 and result['ci_low']==0 and not result['limited']

def test_cluster_positive_lift_and_holm():
    i,m,s=fixture();r=cluster_inference(i,m,m.astype(float),s)
    assert r['ci_low']==pytest.approx(1) and r['p']==.0005
    assert holm([r['p']]*40).max()==pytest.approx(.02)

def test_cluster_small_support_limited():
    i,m,s=fixture();m[8*168:]=False;r=cluster_inference(i,m,m.astype(float),s)
    assert r['limited'] and r['p']==1 and r['clusters']==8

def test_cluster_ineligible_strata_excluded():
    i,m,s=fixture();s.iloc[:168]='ineligible';m[:168]=True
    r=cluster_inference(i,m,m.astype(float),s)
    assert r['ci_low']==pytest.approx(1)
    s.iloc[:]='no_controls';m[:]=True
    r=cluster_inference(i,m,m.astype(float),s)
    assert r['limited'] and r['p']==1

def test_pair_loss_sign_zero_and_limitation():
    i,_,_=fixture();z=paired_loss_test(i,np.zeros(len(i)));p=paired_loss_test(i,np.ones(len(i))*.02)
    n=paired_loss_test(i,np.ones(len(i))*-.02)
    assert z['p']==1 and p['p']==.0005 and n['p']==1
    assert paired_loss_test(i[:100],np.zeros(100))['limited']

def test_asof_lag_no_future_no_backfill_expiry():
    i=pd.date_range('2024-01-01',periods=6,freq='h',tz='UTC')
    src=pd.DataFrame({'x':[5.,99.]},index=i[[1,4]])
    out,age=asof_past(i,src,1,1)
    assert out.iloc[:2].isna().all().all()
    assert out.iloc[2,0]==5 and out.iloc[3,0]==5 and pd.isna(out.iloc[4,0]) and out.iloc[5,0]==99
    assert age[2]==1

def test_derivative_future_perturbation_invariance():
    i=pd.date_range('2024-01-01',periods=100,freq='h',tz='UTC')
    f=pd.DataFrame({'funding_per_hour':1.,'funding_mean3':1.,'funding_change3':0.},index=i[::8])
    m=pd.DataFrame({c:np.arange(100)+100. for c in ['sum_open_interest','sum_open_interest_value',*RATIO_COLS]},index=i)
    a,_=build_derivatives(i,(f,m),1)
    ff=f.copy();mm=m.copy();ff.loc[ff.index>=i[60]]*=10;mm.loc[mm.index>=i[60]]*=2
    b,_=build_derivatives(i,(ff,mm),1)
    pd.testing.assert_frame_equal(a.iloc[:61],b.iloc[:61])
    assert a.shape[1]==16


def test_archive_subsecond_timestamps_are_preserved(tmp_path):
    from derivatives.features import prepare_sources, RATIO_COLS
    f=pd.DataFrame({'timestamp_utc':['2024-01-01 00:00:00+00:00','2024-01-01 08:00:00.001000+00:00','2024-01-01 16:00:00+00:00','2024-01-02 00:00:00+00:00'], 'funding_interval_hours':8,'last_funding_rate':.0001})
    f.to_csv(tmp_path/'BTCUSDT_fundingRate.csv.gz',index=False)
    m=pd.DataFrame({'timestamp_utc':['2024-01-01 00:00:00+00:00'],'sum_open_interest':[100.],'sum_open_interest_value':[1000.],**{c:[1.] for c in RATIO_COLS}})
    m.to_csv(tmp_path/'BTCUSDT_metrics.csv.gz',index=False)
    fund,_=prepare_sources(tmp_path,'BTCUSDT')
    assert fund.index[1].microsecond==1000
    assert fund.iloc[-1].funding_mean3==pytest.approx(.0001/8)
