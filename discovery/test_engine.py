import numpy as np
import pandas as pd
import pytest
from discovery.test_discovery import fixture
from discovery.data import features,TZ,MIN,HOUR,ms
from discovery.engine import simulate,bootstrap,holm

def test_exact_costs_compound_and_flat_drawdown():
    minute=fixture(96)
    for col in ['open','close']:minute[col]=100.
    f=features(minute);a=minute.index[0];b=a+pd.Timedelta(days=4)
    m,r,t=simulate(minute,f,f.minutes.eq(60),a,b,4)
    factor=(1-.0005)*(1-.001)/((1+.0005)*(1+.001))
    assert m['net_return']==pytest.approx(factor**len(t)-1)
    assert m['max_drawdown']==pytest.approx(m['net_return'])
    assert np.allclose(t.net_return,factor-1)
    assert (t.entry_ms>t.signal_ms).all()
    assert (t.entry_ms.iloc[1:].to_numpy()>t.exit_ms.iloc[:-1].to_numpy()).all()

def test_cash_and_zero_cost_flat():
    minute=fixture(96)
    for col in ['open','close']:minute[col]=100.
    f=features(minute);a=minute.index[0];b=a+pd.Timedelta(days=4)
    m,_,_=simulate(minute,f,f.minutes.eq(-1),a,b,4)
    assert m['net_return']==0 and m['sample_size']==0 and m['max_drawdown']==0
    m,_,_=simulate(minute,f,f.minutes.eq(60),a,b,4,fee=0,slip=0)
    assert m['net_return']==0

def test_missing_future_exit_does_not_cancel_past_entry():
    minute=fixture(96);f=features(minute);a=minute.index[0];b=a+pd.Timedelta(days=4)
    mask=pd.Series(False,index=f.index);mask.iloc[0]=True
    due=ms(f.index[0])+MIN+4*HOUR
    minute=minute[minute.t!=due]
    m,_,t=simulate(minute,f,mask,a,b,4)
    assert len(t)==1 and t.exit_delay_min.iloc[0]==1
    assert t.missing_minutes_exposed.iloc[0]==1

def test_bootstrap_and_family_adjustment():
    assert bootstrap(np.zeros(300))['p']==1
    assert holm([.001,.02,.1]).tolist()==pytest.approx([.003,.04,.1])
