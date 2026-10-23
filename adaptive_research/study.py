"""Monthly chronological calibration and volatility-sized spot research.
Run from the extracted evidence root: python -m adaptive_research.study
No trading API, secrets, model selection or fabricated market observations.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, platform, time
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
from multifactor.data import load_inputs, build_features, labels, TZ, END
from derivatives.features import prepare_sources, build_derivatives

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'output'
SEED=20260921
COSTS={'base':(.001,.0005),'stress':(.0015,.0015)}
PROTOCOL='3e304ec547fb64805c56d6c1d6dc12de553f6155'
POLICIES={'FROZEN_RISK':('frozen',.20),'ROLLING_FULL':('rolling',None),
          'ROLLING_RISK':('rolling',.20),'SENS_RISK15':('rolling',.15),
          'SENS_RISK25':('rolling',.25),'SENS_HISTORY180':('rolling180',.20)}

def js(x):
    if isinstance(x,dict):return {str(k):js(v) for k,v in x.items()}
    if isinstance(x,(tuple,list)):return [js(v) for v in x]
    if isinstance(x,(np.integer,)):return int(x)
    if isinstance(x,(np.bool_,)):return bool(x)
    if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
    if isinstance(x,(pd.Timestamp,Path)):return str(x)
    return x

def write(x,p):Path(p).write_text(json.dumps(js(x),indent=2,ensure_ascii=False),encoding='utf8')
def now():return datetime.now(timezone.utc).isoformat()
def cost_return(r,f,s):return (1+r)*(1-f)*(1-s)/((1+f)*(1+s))-1

def model():
    return HistGradientBoostingRegressor(max_iter=100,learning_rate=.05,max_leaf_nodes=7,
        max_depth=3,min_samples_leaf=60,l2_regularization=10,early_stopping=False,random_state=SEED)

def split_masks(index,eligible,y,month,window=365):
    cal_start=month-pd.Timedelta(days=90)
    train=(index>=month-pd.Timedelta(days=window))&(index<cal_start-pd.Timedelta(hours=25))
    cal=(index>=cal_start)&(index<month-pd.Timedelta(hours=25))
    return train&eligible&y.notna().to_numpy(),cal&eligible&y.notna().to_numpy()

def fit_period(X,y,eligible,month,window=365):
    tr,ca=split_masks(X.index,eligible,y,month,window)
    info={'month':str(month),'history_days':window,'fit_rows':int(tr.sum()),'cal_rows':int(ca.sum()),
          'fit_first':str(X.index[tr].min()),'fit_last':str(X.index[tr].max()),
          'cal_first':str(X.index[ca].min()),'cal_last':str(X.index[ca].max())}
    if tr.sum()<200 or ca.sum()<100:
        return None,0.,float('inf'),dict(info,status='INSUFFICIENT_DATA')
    assert X.index[tr].max()+pd.Timedelta(hours=24,minutes=1)<X.index[ca].min()
    assert X.index[ca].max()+pd.Timedelta(hours=24,minutes=1)<month
    est=model().fit(X.loc[tr],y.loc[tr])
    p=est.predict(X.loc[ca]);bias=float(np.mean(p-y.loc[ca].to_numpy()))
    threshold=max(0.,float(np.quantile(p-bias,.90)))
    info.update(status='FITTED',bias=bias,threshold=threshold,
                cal_mean_observed=float(y.loc[ca].mean()),cal_mean_predicted=float(p.mean()),
                cal_rmse=float(np.sqrt(np.mean((p-y.loc[ca].to_numpy())**2))))
    return est,bias,threshold,info

def predictions(X,y,eligible,symbol):
    rows=[];logs=[]
    frozen=fit_period(X,y,eligible,pd.Timestamp('2025-01-01',tz=TZ))
    months=pd.date_range('2025-01-01','2026-09-01',freq='MS',tz=TZ)
    for month in months:
        next_month=min(month+pd.offsets.MonthBegin(1),END)
        take=(X.index>=month)&(X.index<next_month)&eligible
        for mode,fit in [('frozen',frozen),('rolling',fit_period(X,y,eligible,month,365)),
                         ('rolling180',fit_period(X,y,eligible,month,180))]:
            est,bias,threshold,info=fit
            logs.append(dict(info,symbol=symbol,mode=mode,applied_month=str(month)))
            pred=est.predict(X.loc[take])-bias if est is not None else np.full(take.sum(),np.nan)
            for t,p in zip(X.index[take],pred):
                rows.append({'decision_hkt':t,'symbol':symbol,'mode':mode,'score':p,'threshold':threshold,
                             'month':str(month),'eligible_signal':bool(np.isfinite(p) and p>0 and p>=threshold)})
        print('FITTED',symbol,str(month.date()),flush=True)
    return pd.DataFrame(rows),pd.DataFrame(logs)

def make_schedule(raw,pred,vol,year,risk):
    a=pd.Timestamp(f'{year}-01-01',tz=TZ);b=min(a+pd.DateOffset(years=1),END)
    picks=pred[(pred.decision_hkt>=a)&(pred.decision_hkt<b)&pred.eligible_signal].sort_values('decision_hkt')
    rows=[];last_exit=None
    for p in picks.itertuples():
        t=p.decision_hkt;en=t+pd.Timedelta(minutes=1);ex=en+pd.Timedelta(hours=24)
        if ex>=b or (last_exit is not None and en<=last_exit):continue
        v=float(vol.loc[t])
        if not np.isfinite(v) or v<=0:continue
        w=1. if risk is None else min(1.,risk/v)
        xp=float(raw.loc[t+pd.Timedelta(hours=24),'execution_open']);ep=float(raw.loc[t,'execution_open'])
        if not np.isfinite(xp) or not np.isfinite(ep) or xp<=0 or ep<=0:raise ValueError('Missing real execution price')
        rows.append({'entry_hkt':en,'exit_hkt':ex,'weight':w,'score':p.score,'threshold':p.threshold,
                     'entry_price':ep,'exit_price':xp,'vol30d_ann':v})
        last_exit=ex
    return pd.DataFrame(rows,columns=['entry_hkt','exit_hkt','weight','score','threshold','entry_price','exit_price','vol30d_ann'])

def price_grid(raw,year,boundary):
    a=pd.Timestamp(f'{year}-01-01',tz=TZ);b=min(a+pd.DateOffset(years=1),END)
    close=raw.loc[a:b,'close'].copy()
    op=raw.loc[(raw.index>=a)&(raw.index<b),'execution_open'].copy();op.index+=pd.Timedelta(minutes=1)
    final=float(boundary[year]);end_price=pd.Series([final],index=[b-pd.Timedelta(minutes=1)])
    grid=pd.concat([close,op,end_price]).sort_index()
    assert grid.index.is_unique and grid.index[0]==a and grid.index[-1]==b
    assert np.isfinite(grid).all() and (grid>0).all()
    return grid,a,b

def account(grid,a,b,schedule,fee,slip,passive=None):
    events={};records=[]
    if passive is not None:
        if not 0<=passive<=1:raise ValueError('Leverage prohibited')
        if passive>0:
            events[a+pd.Timedelta(minutes=1)]=('buy',passive,None)
            events[b-pd.Timedelta(minutes=1)]=('sell',0.,None)
    else:
        last=None
        for tr in schedule.itertuples():
            en,ex=pd.Timestamp(tr.entry_hkt),pd.Timestamp(tr.exit_hkt)
            if en not in grid.index or ex not in grid.index:raise ValueError('Missing real execution')
            if not a<en<ex<b or ex-en!=pd.Timedelta(hours=24) or not 0<tr.weight<=1:raise ValueError('Invalid frozen order')
            if last is not None and en<=last:raise ValueError('Overlapping order')
            events[en]=('buy',float(tr.weight),tr);events[ex]=('sell',0.,tr);last=ex
    cash=1.;qty=0.;post=[];pre=[];weights=[];entry=None
    for t,p in grid.items():
        before=cash+qty*p;pre.append(before)
        if t in events:
            side,w,tr=events[t]
            if side=='buy':
                if qty!=0:raise ValueError('Repeated entry')
                spend=cash*w;qty=spend/(p*(1+slip)*(1+fee));cash-=spend
                entry=(t,before,p,w,qty)
            else:
                cash+=qty*p*(1-slip)*(1-fee);qty=0
                en,nav0,ep,ew,q=entry
                records.append({'entry_hkt':en,'exit_hkt':t,'weight':ew,'entry_price':ep,'exit_price':p,
                    'raw_coin_return':p/ep-1,'net_account_return':cash/nav0-1,'cash_after':cash})
                entry=None
        nav=cash+qty*p;post.append(nav);weights.append(qty*p/nav)
    if qty!=0:raise ValueError('Unclosed position')
    post=np.asarray(post);pre=np.asarray(pre);weights=np.asarray(weights)
    nav=pd.Series(post,index=grid.index)
    marks=np.column_stack([pre,post]).ravel();peaks=np.maximum.accumulate(marks)
    eods=pd.date_range(a+pd.Timedelta(days=1),b,freq='D')
    dn=nav.reindex(eods)
    if dn.isna().any():raise ValueError('Missing exact daily close')
    dr=pd.Series(np.diff(np.r_[1.,dn])/np.r_[1.,dn.to_numpy()[:-1]],index=eods-pd.Timedelta(days=1))
    dt=np.diff(grid.index.asi8)/1e9;seconds=(b-a).total_seconds()
    rets=np.array([r['net_account_return'] for r in records]);gains=rets[rets>0].sum();losses=-rets[rets<0].sum()
    vol=float(dr.std(ddof=1)*np.sqrt(365))
    m={'trades':len(records),'net_return':post[-1]-1,'max_drawdown':float((marks/peaks-1).min()),
       'volatility_ann':vol,'sharpe_zero_yield':float(dr.mean()*365/vol) if vol>1e-14 else None,
       'win_rate':float((rets>0).mean()) if len(rets) else None,
       'mean_trade':float(rets.mean()) if len(rets) else None,'median_trade':float(np.median(rets)) if len(rets) else None,
       'profit_factor':float(gains/losses) if losses>0 else (None if gains==0 else float('inf')),
       'best_trade_removed':float(np.prod(1+np.delete(rets,np.argmax(rets)))-1) if len(rets)>1 else (0. if len(rets) else None),
       'capital_exposure':float(np.dot(dt,weights[:-1])/seconds),'time_exposure':float(np.dot(dt,weights[:-1]>0)/seconds),
       'worst_day':float(dr.min()),'days':len(dr)}
    return m,dr,pd.DataFrame(records,columns=['entry_hkt','exit_hkt','weight','entry_price','exit_price','raw_coin_return','net_account_return','cash_after'])

def match_weight(full_daily,target):
    def v(w):
        n=1-w+w*np.cumprod(1+full_daily.to_numpy())
        r=np.diff(np.r_[1.,n])/np.r_[1.,n[:-1]]
        return np.std(r,ddof=1)*np.sqrt(365)
    if target<=0:return 0.
    if target>=v(1.):return 1.
    return float(brentq(lambda w:v(w)-target,0,1))

def inference(x,block=7,reps=4999):
    x=np.asarray(x,float);n=len(x);mu=x.mean();rng=np.random.default_rng(SEED)
    starts=rng.integers(0,n,(reps,int(np.ceil(n/block))))
    ix=((starts[:,:,None]+np.arange(block))%n).reshape(reps,-1)[:,:n]
    boot=x[ix].mean(1);lo,hi=np.quantile(boot,[.025,.975])
    return {'mean_log_excess':mu,'ci_low':lo,'ci_high':hi,'p':(1+np.sum(boot-mu>=mu-1e-15))/(reps+1)}
def holm(p):
    p=np.asarray(p,float);order=np.argsort(p);ans=np.ones(len(p));last=0
    for k,i in enumerate(order):last=max(last,(len(p)-k)*p[i]);ans[i]=min(1,last)
    return ans

def run():
    OUT.mkdir(exist_ok=True)
    state={'completed':False,'started_at_utc':now(),'protocol_commit':PROTOCOL,'execution':'ChatGPT local container',
           'model_changed_from_old':True,'old_models_overwritten':False,'live_approved':False,'blind_holdout':False,
           'market_data_simulated':False}
    write(state,OUT/'execution_receipt.json')
    manifest=json.loads((ROOT/'INPUT_MANIFEST.json').read_text())
    for n,h in manifest['files'].items():
        if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h:raise ValueError('Input/source hash mismatch: '+n)
    frames,quality=load_inputs(ROOT/'inputs');fomc=pd.read_csv(ROOT/'inputs/fomc_events.csv')
    summary=[];fits=[];allpred=[];alltr=[];daily={};controls=[];tests=[];monthly=[];equal=[]
    for symbol,raw in frames.items():
        peer=frames['ETHUSDT' if symbol=='BTCUSDT' else 'BTCUSDT']
        X,_=build_features(raw,peer,fomc);D,_=build_derivatives(X.index,prepare_sources(ROOT/'derivative_inputs',symbol))
        X=pd.concat([X,D],axis=1);assert X.shape[1]==92
        vol=np.log(raw.close).diff().rolling(720,min_periods=720).std()*np.sqrt(24*365)
        mask=np.isfinite(X.to_numpy()).all(1)&np.isfinite(vol.to_numpy())&(X.index.hour%6==0)
        rawret=labels(raw)[0];y=cost_return(rawret,*COSTS['base'])
        pred,fit=predictions(X,y,mask,symbol);fits.append(fit);allpred.append(pred)
        write(quality,OUT/'market_quality.json')
        bb=json.loads((ROOT/'inputs'/f'{symbol[:3]}_boundary_klines.json').read_text())
        candles=[c for req in bb['requests'] for c in req['result']]
        bounds={2025:float(next(c[1] for c in candles if c[0]==1767196740000)),2026:float(next(c[1] for c in candles if c[0]==1789401540000))}
        for c in candles:
            ts=pd.Timestamp(c[0],unit='ms',tz='UTC').tz_convert(TZ)
            if ts.minute==1:assert raw.loc[ts-pd.Timedelta(minutes=1),'execution_open']==float(c[1])
            if ts.minute==59:assert raw.loc[ts+pd.Timedelta(minutes=1),'close']==float(c[4])
        priorw=None
        for year in [2025,2026]:
            grid,a,b=price_grid(raw,year,bounds);paths={};stats={};empty=pd.DataFrame()
            for policy,(mode,risk) in POLICIES.items():
                schedule=make_schedule(raw,pred[pred['mode']==mode],vol,year,risk)
                schedule.to_csv(OUT/f'{symbol}_{year}_{policy}_schedule.csv',index=False)
                for cost,(fee,slip) in COSTS.items():
                    m,r,t=account(grid,a,b,schedule,fee,slip)
                    name=policy if cost=='base' else policy+'_stress'
                    paths[name]=r;stats[name]=m
                    summary.append(dict(symbol=symbol,year=year,policy=policy,cost=cost,**m))
                    if len(t):
                        t['symbol']=symbol;t['year']=year;t['policy']=policy;t['cost']=cost;alltr.append(t)
            for nm,w in [('HOLD100',1.),('HOLD50',.5),('HOLD25',.25),('CASH',0.)]:
                for cost,(fee,slip) in COSTS.items():
                    m,r,_=account(grid,a,b,empty,fee,slip,passive=w)
                    key=nm if cost=='base' else nm+'_stress';paths[key]=r;stats[key]=m
                    summary.append(dict(symbol=symbol,year=year,policy=nm,cost=cost,**m))
            target=stats['ROLLING_RISK']['volatility_ann'];w=match_weight(paths['HOLD100'],target)
            controls.append(dict(symbol=symbol,year=year,kind='expost',weight=w))
            m,r,_=account(grid,a,b,empty,*COSTS['base'],passive=w)
            paths['RISK_MATCH_EXPOST']=r;summary.append(dict(symbol=symbol,year=year,policy='RISK_MATCH_EXPOST',cost='base',**m))
            if year==2025:priorw=w
            else:
                for cost,(fee,slip) in COSTS.items():
                    m,r,_=account(grid,a,b,empty,fee,slip,passive=priorw)
                    key='PRIOR_RISK_MATCH' if cost=='base' else 'PRIOR_RISK_MATCH_stress';paths[key]=r
                    summary.append(dict(symbol=symbol,year=year,policy='PRIOR_RISK_MATCH',cost=cost,**m))
                controls.append(dict(symbol=symbol,year=year,kind='calibrated2025',weight=priorw))
                for control in ['CASH','HOLD25','FROZEN_RISK']:
                    delta=np.log1p(paths['ROLLING_RISK'])-np.log1p(paths[control])
                    result=inference(delta);stress=inference(delta,28)
                    tests.append(dict(symbol=symbol,control=control,**result,**{'block28_'+k:v for k,v in stress.items()}))
            daily[(symbol,year)]=pd.DataFrame(paths)
            daily[(symbol,year)].to_csv(OUT/f'{symbol}_{year}_daily_returns.csv',index_label='date_hkt')
            mm=np.expm1(np.log1p(daily[(symbol,year)]).groupby(daily[(symbol,year)].index.strftime('%Y-%m')).sum())
            mm.index.name='month';mm=mm.reset_index();mm['symbol']=symbol;monthly.append(mm)
            pd.DataFrame(summary).to_csv(OUT/'strategy_summary.csv',index=False)
        print('ANALYSED',symbol,flush=True)
    ss=pd.DataFrame(summary);tt=pd.DataFrame(tests);tt['p_holm6']=holm(tt.p)
    tt.to_csv(OUT/'inference.csv',index=False);ss.to_csv(OUT/'strategy_summary.csv',index=False)
    pd.concat(fits).to_csv(OUT/'monthly_fit_audit.csv',index=False)
    pp=pd.concat(allpred);pp.to_csv(OUT/'all_predictions.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    trades=pd.concat(alltr,ignore_index=True) if alltr else pd.DataFrame()
    trades.to_csv(OUT/'trades.csv',index=False)
    pd.DataFrame(controls).to_csv(OUT/'passive_weights.csv',index=False);pd.concat(monthly).to_csv(OUT/'monthly_returns.csv',index=False)
    for year in [2025,2026]:
        x=daily[('BTCUSDT',year)];z=daily[('ETHUSDT',year)]
        for policy in ['ROLLING_RISK','FROZEN_RISK','ROLLING_FULL','HOLD25','HOLD100']:
            nav=.5*(1+x[policy]).cumprod()+.5*(1+z[policy]).cumprod()
            equal.append(dict(year=year,policy=policy,return_equal_sleeves=float(nav.iloc[-1]-1),
                              daily_mdd=float((nav/np.maximum.accumulate(np.r_[1.,nav])[1:]-1).min()),descriptive_only=True))
    pd.DataFrame(equal).to_csv(OUT/'equal_sleeve_description.csv',index=False)
    gates=[]
    for sym in frames:
        ok=True;details={}
        for year,minimum in [(2025,30),(2026,15)]:
            base=ss[(ss.symbol==sym)&(ss.year==year)&(ss.policy=='ROLLING_RISK')&(ss.cost=='base')].iloc[0]
            stress=ss[(ss.symbol==sym)&(ss.year==year)&(ss.policy=='ROLLING_RISK')&(ss.cost=='stress')].iloc[0]
            g={'trades':bool(base.trades>=minimum),'base_positive':bool(base.net_return>0),'stress_positive':bool(stress.net_return>0),
               'pf_over1p1':bool(base.profit_factor>1.1),'best_removed_positive':bool(base.best_trade_removed>0)}
            details[str(year)]=g;ok &= all(g.values())
        own=ss[(ss.symbol==sym)&(ss.year==2026)&(ss.policy=='ROLLING_RISK')&(ss.cost=='base')].net_return.iloc[0]
        passive=ss[(ss.symbol==sym)&(ss.year==2026)&(ss.policy=='PRIOR_RISK_MATCH')&(ss.cost=='base')].net_return.iloc[0]
        req=tt[(tt.symbol==sym)&tt.control.isin(['CASH','HOLD25'])]
        details['beats_prior_risk']=bool(own>passive);details['evidence']=bool((req.p_holm6<.05).all() and (req.mean_log_excess>0).all())
        ok &= details['beats_prior_risk'] and details['evidence']
        gates.append(dict(symbol=sym,promoted=bool(ok),gates=details))
    write(gates,OUT/'candidate_gates.json')
    state.update(completed=True,finished_at_utc=now(),features=92,coins=list(frames),months_per_coin=21,
        promoted=sum(r['promoted'] for r in gates),input_files_verified=len(manifest['files']),
        python=platform.python_version(),source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    write(state,OUT/'execution_receipt.json')
    print(ss[(ss.cost=='base')&ss.policy.isin(['FROZEN_RISK','ROLLING_FULL','ROLLING_RISK','HOLD25','HOLD100','PRIOR_RISK_MATCH'])].to_string(index=False))
    print(tt.to_string(index=False));print('GATES',json.dumps(gates))

if __name__=='__main__':
    with threadpool_limits(limits=1):run()
