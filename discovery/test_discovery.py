import numpy as np
import pandas as pd
import pytest
from discovery.data import parse,features,TZ,ms,MIN
from discovery.explore import decimate

def test_parse_units_and_invalid_prices():
    row=[1613014800000,100,101,99,100,10,1613014854773,1000,4,5,500,0]
    f,m=parse(pd.DataFrame([row]));assert len(f)==1 and m['legacy_close_metadata_rows']==1
    u=row.copy();u[0]=1735689600000000;u[6]=u[0]+59999999
    f,m=parse(pd.DataFrame([u]));assert f.t.iloc[0]==1735689600000
    u[6]=1735689659999
    with pytest.raises(ValueError,match='Mixed'):parse(pd.DataFrame([u]))
    bad=row.copy();bad[2]=98
    f,m=parse(pd.DataFrame([bad]));assert len(f)==0 and m['invalid_rows']==1

def fixture(hours=200):
    idx=pd.date_range('2021-01-01',periods=hours*60,freq='min',tz=TZ)
    p=100+np.arange(len(idx))*.0001
    return pd.DataFrame({'t':[ms(x) for x in idx],'open':p,'high':p+.01,'low':p-.01,'close':p+.001,
       'volume':1.,'quote_volume':p,'taker_quote':p*.5},index=idx)

def test_hourly_timing_and_no_future_in_features():
    m=fixture();f=features(m)
    decision=pd.Timestamp('2021-01-07',tz=TZ)
    assert f.loc[decision,'execution_ms']==ms(decision)+MIN
    changed=m.copy();changed.loc[changed.index>=decision,['high','low','close']]*=2
    g=features(changed)
    for col in ['r1','r4','r24','shock4','volume_ratio','buy_imbalance']:
        pd.testing.assert_series_equal(f.loc[:decision,col],g.loc[:decision,col])

def test_incomplete_hour_is_not_filled():
    m=fixture();m=m.drop(m.index[30]);f=features(m)
    assert f.iloc[0].minutes==59 and np.isnan(f.iloc[0].close)

def test_event_nonoverlap():
    assert decimate([0,1,3,4,5,8],4).tolist()==[0,4,8]
