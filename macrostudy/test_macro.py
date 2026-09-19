import numpy as np
import pandas as pd
import pytest
from macrostudy.features import build_macro

def sample_events():
    return pd.DataFrame([
      {'indicator':'cpi_yoy','release_at':pd.Timestamp('2024-01-10T12:30:00Z'),'actual':3.5,'forecast':3.4,'previous':3.2},
      {'indicator':'cpi_yoy','release_at':pd.Timestamp('2024-02-10T13:00:00Z'),'actual':3.2,'forecast':np.nan,'previous':3.5},
      {'indicator':'nfp','release_at':pd.Timestamp('2024-01-05T13:30:00Z'),'actual':200,'forecast':180,'previous':170},
    ])

def test_half_hour_release_first_next_hour():
    idx=pd.date_range('2024-01-10T12:00:00Z',periods=4,freq='h')
    x,_,_=build_macro(idx,sample_events(),0)
    assert x.loc[idx[0],'cpi_yoy_active']==0
    assert x.loc[idx[1],'cpi_yoy_active']==1
    assert x.loc[idx[1],'cpi_yoy_surprise_raw']==pytest.approx(.1)

def test_exact_hour_release_still_waits_one_hour():
    idx=pd.date_range('2024-02-10T13:00:00Z',periods=3,freq='h')
    x,_,_=build_macro(idx,sample_events(),0)
    assert x.loc[idx[0],'cpi_yoy_active']==0
    assert x.loc[idx[1],'cpi_yoy_active']==1
    assert x.loc[idx[1],'cpi_yoy_forecast_available']==0
    assert x.loc[idx[1],'cpi_yoy_surprise_raw']==0

def test_extra_lag_stress():
    idx=pd.date_range('2024-01-10T12:00:00Z',periods=4,freq='h')
    a,_,_=build_macro(idx,sample_events(),0)
    b,_,_=build_macro(idx,sample_events(),1)
    assert a.loc[idx[1],'cpi_yoy_active']==1
    assert b.loc[idx[1],'cpi_yoy_active']==0
    assert b.loc[idx[2],'cpi_yoy_active']==1

def test_expiry_and_no_backfill():
    idx=pd.date_range('2024-01-09T12:00:00Z',periods=50,freq='h')
    x,_,_=build_macro(idx,sample_events(),0,active_hours=24)
    assert x.iloc[0].filter(like='_active').sum()==0
    target=pd.Timestamp('2024-01-11T13:00:00Z')
    assert x.loc[target,'cpi_yoy_active']==0

def test_future_event_perturbation_does_not_change_past():
    idx=pd.date_range('2024-01-01',periods=1200,freq='h',tz='UTC')
    e=sample_events()
    a,_,_=build_macro(idx,e,0)
    e2=e.copy();e2.loc[e2.release_at>pd.Timestamp('2024-02-01',tz='UTC'),'actual']=999
    b,_,_=build_macro(idx,e2,0)
    pd.testing.assert_frame_equal(a.loc[:'2024-01-31'],b.loc[:'2024-01-31'])

def test_all_features_finite_and_count():
    idx=pd.date_range('2024-01-01',periods=1000,freq='h',tz='UTC')
    x,f,c=build_macro(idx,sample_events(),0)
    assert np.isfinite(x.to_numpy()).all()
    assert x.shape[1]==10
    assert set(f.values())=={'inflation','labour'}
    assert {'release_count','forecast_missing'}<=set(c.columns)
