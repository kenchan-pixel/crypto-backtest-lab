"""Synthetic fixtures are only unit tests and are never exported as market evidence."""
import numpy as np
import pandas as pd
import pytest
from screen.data import ms,TZ,MINUTE,parse
from screen.engine import simulate,signal,holm,block_test

def fixture(days=4):
    dates=pd.date_range('2021-01-01',periods=days,tz=TZ)
    t=np.arange(ms(dates[0]),ms(dates[-1]+pd.Timedelta(days=1)),MINUTE,dtype=np.int64)
    op=np.full(len(t),100.); cl=op.copy()
    d=pd.DataFrame({'close':np.full(days,100.),'execution_ms':[ms(x)+MINUTE for x in dates],
      'execution_open':np.full(days,100.),'delay_minutes':0,'observed_minutes':1440},index=dates)
    return (t,op,cl),d,dates[0],dates[-1]+pd.Timedelta(days=1)

def test_exact_roundtrip_and_drawdown():
    a,d,s,e=fixture(); m,r,tr=simulate(a,d,None,s,e,passive=1.)
    expect=(1-.0005)*(1-.001)/((1+.0005)*(1+.001))-1
    assert m['net_return']==pytest.approx(expect)
    assert m['max_drawdown']==pytest.approx(expect)
    assert m['sample_size']==1 and m['orders']==2
    assert tr.iloc[0].net_return==pytest.approx(expect)

def test_cash_and_half_passive():
    a,d,s,e=fixture(); full,_,_=simulate(a,d,None,s,e,passive=1.)
    half,_,_=simulate(a,d,None,s,e,passive=.5)
    cash,_,_=simulate(a,d,None,s,e,passive=0.)
    assert half['net_return']==pytest.approx(full['net_return']/2)
    assert cash['net_return']==0 and cash['sample_size']==0

def test_zero_cost_flat_is_flat():
    a,d,s,e=fixture(); m,r,tr=simulate(a,d,None,s,e,fee=0,slip=0,passive=1.)
    assert m['net_return']==0 and m['max_drawdown']==0 and (r==0).all()

def test_weekly_turnover_no_repeated_buys():
    a,d,s,e=fixture(25); sig=pd.Series(1.,index=d.index)
    m,r,tr=simulate(a,d,sig,s,e)
    assert m['sample_size']==1 and m['orders']==2
    assert tr.iloc[0].entry_ms==ms(s)+MINUTE

def test_future_close_does_not_change_current_signal():
    a,d,s,e=fixture(20); d['close']=np.arange(100.,120.)
    for fam,x,y in [('T1',3,0),('T2',2,4),('T3',4,0)]:
        old=signal(d,fam,x,y); changed=d.copy(); changed.iloc[10:,0]=1.
        new=signal(changed,fam,x,y)
        pd.testing.assert_series_equal(old.iloc[:11],new.iloc[:11])
        assert old.iloc[:x].isna().all() if fam!='T2' else old.iloc[:y].isna().all()

def test_monday_rebalance_only():
    a,d,s,e=fixture(14); sig=pd.Series(0.,index=d.index); sig.iloc[1:]=1.
    m,r,tr=simulate(a,d,sig,s,e)
    assert pd.Timestamp(int(tr.iloc[0].entry_ms),unit='ms',tz='UTC').tz_convert(TZ).weekday()==0

def test_holm_and_robust_bootstrap():
    assert holm([.001,.02,.1]).tolist()==pytest.approx([.003,.04,.1])
    assert block_test(np.zeros(400))['p']==1.
    assert block_test(np.ones(20)*.01)['inference_limited'] is True

def test_parser_ms_us_and_metadata():
    row=[1613014800000,100,101,99,100,10,1613014854773,1000,4,5,500,0]
    arr,meta=parse(pd.DataFrame([row])); assert meta['nonstandard_close_time_rows']==1
    u=row.copy(); u[0]=1735689600000000;u[6]=u[0]+59999999
    arr,meta=parse(pd.DataFrame([u])); assert arr[0][0]==1735689600000
    u[6]=1735689659999
    with pytest.raises(ValueError,match='Mixed'): parse(pd.DataFrame([u]))

def test_intraday_gap_not_fabricated():
    a,d,s,e=fixture(); t,o,c=a; mask=np.ones(len(t),dtype=bool);mask[400:450]=False
    m,_,_=simulate((t[mask],o[mask],c[mask]),d,None,s,e,passive=1.)
    assert m['sample_size']==1
    with pytest.raises(ValueError,match='endpoints'):
        simulate((t[:-1],o[:-1],c[:-1]),d,None,s,e,passive=1.)
