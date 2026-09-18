"""Self-financing spot/cash accounts, completed-day signals, observable-minute drawdown."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .data import DAY, MINUTE, TZ, ms
VARIANTS=[('T1_150','T1',150,0),('T1_200','T1',200,0),('T1_250','T1',250,0),
 ('T2_40_200','T2',40,200),('T2_50_150','T2',50,150),('T2_50_200','T2',50,200),
 ('T2_50_250','T2',50,250),('T2_60_200','T2',60,200),
 ('T3_60','T3',60,0),('T3_90','T3',90,0),('T3_120','T3',120,0)]
PRIMARY=['T1_200','T2_50_200','T3_90']
COSTS={'base':(.001,.0005),'low':(.00075,.0002),'stress':(.0015,.0015),'zero':(0.,0.)}
def signal(daily, family, a, b=0):
    close=daily['close']
    if family=='T1':
        left,right=close,close.rolling(a,min_periods=a).mean()
    elif family=='T2':
        left,right=close.rolling(a,min_periods=a).mean(),close.rolling(b,min_periods=b).mean()
    elif family=='T3':
        left,right=close,close.shift(a)
    else: raise ValueError(family)
    raw=(left>right).astype(float).where(left.notna()&right.notna())
    return raw.shift(1)  # Day d decisions use only data through day d-1.

def simulate(arrays,daily,sig,start,end,fee=.001,slip=.0005,minute_dd=True,passive=None):
    t,op,cl=arrays
    lo,hi=ms(start),ms(end)
    part=daily[(daily.index>=start)&(daily.index<end)]
    if part.empty: raise ValueError('Empty segment')
    first=np.searchsorted(t,lo); last=np.searchsorted(t,hi)-1
    if first>=len(t) or t[first]!=lo or t[last]!=hi-MINUTE:
        raise ValueError('Exact requested segment endpoints unavailable')
    end_ms=int(t[last]); cash,units=1.,0.
    events=[(lo,cash,units)]; trades=[]; entry=None; delays=0; missing_signal=0; changes=0
    def sell(j,price,forced=False):
        nonlocal cash,units,entry,changes
        if units<=0: return
        proceeds=units*price*(1-slip)*(1-fee)
        tr={'entry_ms':int(entry[0]),'exit_ms':int(j),'entry_open':entry[1], 'exit_open':float(price),
            'net_return':proceeds/entry[2]-1.,'gross_return':price/entry[1]-1.,'forced_exit':forced}
        trades.append(tr); cash+=proceeds; units=0.; entry=None; changes+=1
        events.append((int(j),cash,units))
    for k,(day,row) in enumerate(part.iterrows()):
        stamp=int(row.execution_ms); price=float(row.execution_open)
        if stamp>=end_ms: continue
        if passive is not None:
            if k!=0: continue
            target=float(passive)
        else:
            if k!=0 and day.weekday()!=0: continue
            target=float(sig.loc[day])
            if not np.isfinite(target): missing_signal+=1; continue
        if target>0 and units==0:
            spend=cash*target
            units=spend/(price*(1+slip)*(1+fee)); cash-=spend
            entry=(stamp,price,spend); events.append((stamp,cash,units)); changes+=1
            delays+=int(row.delay_minutes>0)
        elif target==0 and units>0:
            sell(stamp,price); delays+=int(row.delay_minutes>0)
    sell(end_ms,float(op[last]),True)
    ev=np.array(events,dtype=float); e_t=ev[:,0].astype(np.int64)
    query=np.array([ms(d)+DAY-MINUTE for d in part.index])
    cp=np.searchsorted(t,query)
    if np.any(cp>=len(t)) or np.any(t[cp]!=query):
        raise ValueError('Missing exact daily close for daily inference; no stale mark')
    ei=np.searchsorted(e_t,query,side='right')-1
    equity=ev[ei,1]+ev[ei,2]*cl[cp]
    daily_r=np.diff(np.r_[1.,equity])/np.r_[1.,equity[:-1]]
    if not np.isfinite(equity).all() or np.any(equity<=0): raise ValueError('Invalid account equity')
    peak=1.; worst=0.
    if minute_dd:
        # At an execution minute mark the account AFTER its actual adverse fill/cost.
        # Pre-trade value at the same open is also marked using the previous inventory.
        for j,(stamp,cashj,unitj) in enumerate(events):
            aidx=np.searchsorted(t,stamp)
            nextstamp=events[j+1][0] if j+1<len(events) else hi
            bidx=min(np.searchsorted(t,nextstamp),last+1)
            if j+1<len(events):
                boundary=np.searchsorted(t,nextstamp)
                pre=cashj+unitj*op[boundary]
            else: pre=cashj
            if bidx>aidx:
                values=(cashj+unitj*np.column_stack([op[aidx:bidx],cl[aidx:bidx]])).ravel()
                peaks=np.maximum.accumulate(np.r_[peak,values])[1:]
                worst=min(worst,float(np.min(values/peaks-1.))); peak=max(peak,float(values.max()))
            peak=max(peak,pre); worst=min(worst,pre/peak-1.)
    else:
        peaks=np.maximum.accumulate(np.r_[1.,equity])[1:]; worst=float(np.min(equity/peaks-1.))
    trade_r=np.array([x['net_return'] for x in trades]); wins=trade_r[trade_r>0].sum(); loss=-trade_r[trade_r<0].sum()
    days=(hi-lo)/DAY; vol=float(np.std(daily_r,ddof=1))
    exp_minutes=sum(( (events[j+1][0] if j+1<len(events) else hi)-e[0])/MINUTE for j,e in enumerate(events) if e[2]>0)
    metrics={'sample_size':len(trades),'win_rate':float((trade_r>0).mean()) if len(trades) else None,
      'average_return':float(trade_r.mean()) if len(trades) else None,'median_return':float(np.median(trade_r)) if len(trades) else None,
      'profit_factor':float(wins/loss) if loss>0 else (float('inf') if wins>0 else None),
      'net_return':float(equity[-1]-1),'cagr':float(equity[-1]**(365/days)-1),'max_drawdown':worst,
      'drawdown_basis':'observed_minute_open_close' if minute_dd else 'daily_close',
      'daily_sharpe':float(np.mean(daily_r)/vol*np.sqrt(365)) if vol>1e-15 else None,
      'annual_volatility':vol*np.sqrt(365),'exposure_fraction':exp_minutes/((hi-lo)/MINUTE),
      'orders':changes,'delayed_orders':delays,'unavailable_signal_checks':missing_signal}
    returns=pd.Series(daily_r,index=part.index,name='daily_return')
    trade_frame=pd.DataFrame(trades,columns=['entry_ms','exit_ms','entry_open','exit_open','net_return','gross_return','forced_exit'])
    return metrics,returns,trade_frame

def block_test(values,block=28,reps=4999,seed=20260918):
    """Circular block bootstrap CI and centered one-sided mean-growth test."""
    x=np.asarray(values,dtype=float)
    if len(x)<block*10 or not np.isfinite(x).all():
        return {'p':1.,'mean_log_daily':float(np.mean(x)),'ci_low':None,'ci_high':None,'inference_limited':True}
    n=len(x); mean=float(x.mean()); rng=np.random.default_rng(seed)
    full,rem=divmod(n,block); cs=np.r_[0.,np.cumsum(np.r_[x,x[:block]])]
    starts=rng.integers(0,n,size=(reps,full))
    totals=(cs[starts+block]-cs[starts]).sum(axis=1)
    if rem:
        starts=rng.integers(0,n,size=reps); totals+=cs[starts+rem]-cs[starts]
    boot=totals/n; low,high=np.quantile(boot,[.025,.975])
    p=(1+np.count_nonzero(boot-mean>=mean))/(reps+1)
    return {'p':float(p),'mean_log_daily':mean,'ci_low':float(low),'ci_high':float(high),'inference_limited':False}
def holm(ps):
    p=np.array(ps,dtype=float); order=np.argsort(p); ans=np.empty(len(p)); running=0.
    for k,i in enumerate(order): running=max(running,(len(p)-k)*p[i]); ans[i]=min(1.,running)
    return ans
