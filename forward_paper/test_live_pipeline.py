import pandas as pd
import pytest
from forward_paper.live_pipeline import merge_metrics,funding_features,REQ_COLS


def metric_frame(start,periods,value0=1.):
    idx=pd.date_range(start,periods=periods,freq='5min',tz='UTC')
    return pd.DataFrame({c:[value0+i for i in range(periods)] for c in REQ_COLS},index=idx,dtype=float)

def test_metric_merge_accepts_identical_overlap_and_keeps_live():
    a=metric_frame('2026-09-21T00:00Z',6)
    b=a.iloc[-2:].copy()
    out,gap,overlap=merge_metrics(a,b)
    assert len(out)==6 and overlap==2 and gap==5
    assert out.index.is_unique

def test_metric_merge_rejects_overlap_disagreement():
    a=metric_frame('2026-09-21T00:00Z',6);b=a.iloc[-2:].copy();b.iloc[0,0]+=1
    with pytest.raises(ValueError,match='overlap'):merge_metrics(a,b)

def test_metric_merge_rejects_large_gap():
    a=metric_frame('2026-09-21T00:00Z',2);b=metric_frame('2026-09-21T00:30Z',2,10)
    with pytest.raises(ValueError,match='gap'):merge_metrics(a,b)

def test_funding_features_infer_actual_interval_not_fixed_eight_hours():
    rows=[
      {'symbol':'ETHUSDT','fundingTime':1000,'fundingRate':'0.00008'},
      {'symbol':'ETHUSDT','fundingTime':1000+4*3600*1000,'fundingRate':'0.00004'},
      {'symbol':'ETHUSDT','fundingTime':1000+12*3600*1000,'fundingRate':'0.00016'},
    ]
    f=funding_features(rows)
    assert f.funding_per_hour.iloc[1]==pytest.approx(.00001)
    assert f.funding_per_hour.iloc[2]==pytest.approx(.00002)
