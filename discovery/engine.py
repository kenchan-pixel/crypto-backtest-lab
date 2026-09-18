"""Causal fixed-horizon spot accounts. Signals do not inspect future price availability."""
import numpy as np
import pandas as pd
from .data import ms,MIN,HOUR,TZ
COSTS={'base':(.001,.0005),'stress':(.0015,.0015),'zero':(0.,0.)}

def simulate(minute,features,mask,start,end,hold_hours,fee=.001,slip=.0005,minute_dd=True,passive=False):
    t=minute.t.to_numpy();op=minute.open.to_numpy();cl=minute.close.to_numpy()
    lo,hi=ms(start),ms(end);last=np.searchsorted(t,hi)-1
    if t[np.searchsorted(t,lo)]!=lo or t[last]!=hi-MIN:raise ValueError('Coverage boundary absent')
    horizon=int(round(hold_hours*HOUR));cash=1.;events=[(lo,1.,0.)];trades=[];last_exit=lo-1
    missed=0;raw_signals=0
    decisions=np.array([ms(x) for x in features.index]);valid=(decisions>=lo)&(decisions<hi)
    signal=np.asarray(mask.fillna(False),dtype=bool)&valid
    stamps=[lo] if passive else decisions[signal]
    for decision in stamps:
        raw_signals+=1;scheduled=int(decision)+MIN
        if scheduled<=last_exit:continue
        en=np.searchsorted(t,scheduled)
        if en>=last:continue
        if t[en]-scheduled>=HOUR:missed+=1;continue
        due=hi-MIN if passive else int(t[en])+horizon
        ex=min(np.searchsorted(t,due),last)
        if ex<=en:continue
        before=cash;units=cash/(op[en]*(1+slip)*(1+fee));events.append((int(t[en]),0.,units))
        cash=units*op[ex]*(1-slip)*(1-fee);events.append((int(t[ex]),cash,0.));last_exit=int(t[ex])
        expected=int((t[ex]-t[en])//MIN);observed=ex-en
        trades.append({'signal_ms':int(decision),'entry_ms':int(t[en]),'exit_ms':int(t[ex]),
          'entry_open':float(op[en]),'exit_open':float(op[ex]),'net_return':cash/before-1,
          'gross_return':float(op[ex]/op[en]-1),'cash_before':before,'cash_after':cash,'pnl':cash-before,
          'entry_delay_min':int((t[en]-scheduled)//MIN),'exit_delay_min':max(0,int((t[ex]-due)//MIN)),
          'missing_minutes_exposed':max(0,expected-observed),'forced_exit':bool(due>t[last])})
        if passive:break
    ev=np.array(events,dtype=float);et=ev[:,0].astype(np.int64)
    days=pd.date_range(start,end,freq='D',inclusive='left');query=np.array([ms(x)+24*HOUR-MIN for x in days])
    qi=np.searchsorted(t,query);ei=np.searchsorted(et,query,side='right')-1
    exact=(qi<len(t))&(t[np.minimum(qi,len(t)-1)]==query)
    if np.any((~exact)&(ev[ei,2]>0)):raise ValueError('Missing daily close while exposed; no fabricated NAV')
    daily=ev[ei,1]+ev[ei,2]*cl[np.minimum(qi,len(t)-1)]
    returns=pd.Series(np.diff(np.r_[1.,daily])/np.r_[1.,daily[:-1]],index=days,name='daily_return')
    peak=1.;dd=0.
    if minute_dd:
        for j,(stamp,ca,un) in enumerate(events):
            a=np.searchsorted(t,stamp);nextstamp=events[j+1][0] if j+1<len(events) else hi
            b=min(np.searchsorted(t,nextstamp),last+1)
            if b>a:
                vals=(ca+un*np.column_stack([op[a:b],cl[a:b]])).ravel()
                peaks=np.maximum.accumulate(np.r_[peak,vals])[1:]
                dd=min(dd,float(np.min(vals/peaks-1)));peak=max(peak,float(vals.max()))
            if j+1<len(events):
                before=ca+un*op[np.searchsorted(t,nextstamp)];peak=max(peak,before);dd=min(dd,before/peak-1)
    else:dd=float(np.min(daily/np.maximum.accumulate(np.r_[1.,daily])[1:]-1))
    cols=['signal_ms','entry_ms','exit_ms','entry_open','exit_open','net_return','gross_return','cash_before','cash_after','pnl','entry_delay_min','exit_delay_min','missing_minutes_exposed','forced_exit']
    tr=pd.DataFrame(trades,columns=cols);r=tr.net_return.to_numpy(dtype=float);pnl=tr.pnl.to_numpy(dtype=float)
    loss=-pnl[pnl<0].sum();gain=pnl[pnl>0].sum();vol=returns.std()
    duration=(hi-lo)/HOUR/24
    metrics={'sample_size':len(r),'signal_count':raw_signals,'win_rate':float(np.mean(r>0)) if len(r) else None,
      'average_return':float(np.mean(r)) if len(r) else None,'median_return':float(np.median(r)) if len(r) else None,
      'profit_factor':float(gain/loss) if loss>0 else (float('inf') if gain>0 else None),
      'net_return':cash-1,'cagr':cash**(365/duration)-1,'max_drawdown':dd,
      'daily_sharpe':float(returns.mean()/vol*np.sqrt(365)) if vol>1e-15 else None,
      'drawdown_basis':'observed_minute_open_close' if minute_dd else 'daily_close',
      'exposure_fraction':float((tr.exit_ms-tr.entry_ms).sum()/(hi-lo)) if len(r) else 0.,
      'missing_minutes_exposed':int(tr.missing_minutes_exposed.sum()),'delayed_orders':int((tr.entry_delay_min>0).sum()+(tr.exit_delay_min>0).sum()),
      'expired_entry_orders':missed}
    return metrics,returns,tr

def shift_dates(mask,seed):
    rng=np.random.default_rng(seed);shifted=mask.copy()
    for year in sorted(set(mask.index.year)):
        idx=np.flatnonzero(mask.index.year==year);shift=int(rng.integers(7,91))*24
        shifted.iloc[idx]=np.roll(mask.iloc[idx].to_numpy(),shift)
    return shifted

def bootstrap(delta,block=7,reps=4999,seed=20260918):
    x=np.asarray(delta,dtype=float);mean=float(x.mean())
    if len(x)<block*10 or not np.isfinite(x).all():return {'mean_log_daily':mean,'ci_low':None,'ci_high':None,'p':1.,'limited':True}
    n=len(x);rng=np.random.default_rng(seed);cs=np.r_[0.,np.cumsum(np.r_[x,x[:block]])]
    full,rem=divmod(n,block);starts=rng.integers(0,n,size=(reps,full));total=(cs[starts+block]-cs[starts]).sum(axis=1)
    if rem:
        starts=rng.integers(0,n,size=reps);total+=cs[starts+rem]-cs[starts]
    boot=total/n;low,high=np.quantile(boot,[.025,.975]);p=(1+np.count_nonzero(boot-mean>=mean))/(reps+1)
    return {'mean_log_daily':mean,'ci_low':float(low),'ci_high':float(high),'p':float(p),'limited':False}

def holm(pvalues):
    p=np.array(pvalues);order=np.argsort(p);out=np.empty(len(p));maximum=0.
    for j,i in enumerate(order):maximum=max(maximum,(len(p)-j)*p[i]);out[i]=min(1.,maximum)
    return out
