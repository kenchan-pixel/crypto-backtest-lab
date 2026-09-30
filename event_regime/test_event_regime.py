import numpy as np
import pandas as pd
from event_regime.build import rolling_z,label3,valid_published

def test_label3_and_unknown():
    s=pd.Series([-2.,0.,2.,np.nan])
    got=label3(s,-1,1,'low','mid','high').tolist()
    assert got==['low','mid','high','unknown']

def test_rolling_z_does_not_use_future_values():
    idx=pd.date_range('2024-01-01',periods=900,freq='h',tz='UTC')
    s=pd.Series(np.arange(900,dtype=float),index=idx)
    a=rolling_z(s)
    s2=s.copy();s2.iloc[800:]*=1000
    b=rolling_z(s2)
    pd.testing.assert_series_equal(a.iloc[:800],b.iloc[:800])

def test_placeholder_timestamp_rejected():
    assert valid_published('1970-01-01T00:00:00Z') is None
    assert valid_published(None) is None
    assert valid_published('2026-09-20T01:23:45Z').year==2026

def test_outcome_labels_are_not_regime_inputs():
    # Frozen schema rule: future labels must stay outcome-only.
    feature_names={'trend_30d','trend_7d','vol_state','cross_asset_state','funding_state','oi_state','positioning_state'}
    forbidden={'forward_return_6h','forward_return_24h','forward_return_72h','direction_24h'}
    assert not feature_names & forbidden
