"""Relative-risk audit of an unchanged ETH model. No fitting or trading actions.
Run: python -m benchmark_review.analyze --root <extracted-bundle-root>
All counterfactual returns use the saved genuine prices, not simulated market data.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import brentq

TZ = 'Asia/Hong_Kong'
COSTS = {'base': (.001, .0005), 'stress': (.0015, .0015)}
SEED = 20260921
REPS = 4999
PRICE_SHA = '25e534123a8a4b0154cd378b2841bd89eae0f1904d6ea0e7dfeb6a6440dc029b'
PROTOCOL_COMMIT = '8618ef2ff1663babc9bca166274a66a5e835c637'

def clean(x):
    if isinstance(x, dict): return {str(k): clean(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [clean(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (float,np.floating)): return float(x) if np.isfinite(x) else None
    if isinstance(x, (np.bool_,)): return bool(x)
    return x

def write_json(obj, path):
    Path(path).write_text(json.dumps(clean(obj), indent=2, ensure_ascii=False, default=str), encoding='utf-8')

def bounds(year):
    return pd.Timestamp(f'{year}-01-01',tz=TZ), pd.Timestamp('2026-09-15' if year==2026 else '2026-01-01',tz=TZ)

def after_cost(raw_return, fee, slip):
    return (1+raw_return)*(1-fee)*(1-slip)/((1+fee)*(1+slip))-1

@dataclass
class PathResult:
    nav: pd.Series
    pre: pd.Series
    holding: pd.Series
    daily_nav: pd.Series
    daily_returns: pd.Series
    metrics: dict

def evaluate(nav, pre, holding, begin, end):
    # Every sampled price/time is real. Include both sides of transaction costs.
    matrix=np.column_stack([pre.to_numpy(),nav.to_numpy()]).ravel()
    peak=np.maximum.accumulate(matrix)
    dd=matrix/peak-1
    times=np.repeat(nav.index.asi8,2)
    last_peak=np.maximum.accumulate(np.where(matrix>=peak-1e-12,np.arange(len(matrix)),0))
    duration=(times-times[last_peak])/86_400e9
    eods=pd.date_range(begin+pd.Timedelta(days=1),end,freq='D')
    dn=nav.reindex(eods)
    if dn.isna().any(): raise ValueError('Exact daily marks unavailable; no interpolation')
    daily=pd.Series(np.diff(np.r_[1.,dn.to_numpy()])/np.r_[1.,dn.to_numpy()[:-1]], index=eods-pd.Timedelta(days=1))
    days=(end-begin)/pd.Timedelta(days=1)
    sd=daily.std(ddof=1); down=np.sqrt(np.mean(np.minimum(daily,0)**2))
    weights=(nav.index[1:].asi8-nav.index[:-1].asi8)/1e9
    avg_weight=float(np.dot(weights,holding.to_numpy()[:-1]) / ((end-begin).total_seconds()))
    metrics={'net_return':float(nav.iloc[-1]-1),'volatility_ann':float(sd*np.sqrt(365)),
      'sharpe_zero_yield':float(daily.mean()/sd*np.sqrt(365)) if sd>1e-14 else None,
      'sortino_zero_yield':float(daily.mean()/down*np.sqrt(365)) if down>1e-14 else None,
      'max_drawdown':float(dd.min()),'max_drawdown_days':float(duration.max()),
      'worst_day':float(daily.min()), 'expected_shortfall_day_5pct':float(daily[daily<=daily.quantile(.05)].mean()),
      'mean_daily_return':float(daily.mean()), 'average_coin_weight':avg_weight,
      'calendar_days':int(days),'observation_basis':'hourly_close_and_execution_open_pre_post_cost'}
    return PathResult(nav,pre,holding,dn,daily,metrics)

def build_grid(raw, year, final_open):
    a,b=bounds(year)
    closes=raw.loc[a:b,'close'].copy()
    opens=raw.loc[(raw.index>=a)&(raw.index<b),'execution_open'].copy()
    if closes.isna().any() or opens.isna().any(): raise ValueError('Incomplete grid prices')
    opens.index=opens.index+pd.Timedelta(minutes=1)
    prices=pd.concat([closes,opens,pd.Series([final_open],index=[b-pd.Timedelta(minutes=1)])]).sort_index()
    if not prices.index.is_unique: raise ValueError('Duplicate grid timestamps')
    if prices.index[0]!=a or prices.index[-1]!=b or not (prices>0).all(): raise ValueError('Bad grid boundary')
    return prices,a,b

def replay(prices, a, b, trades, fee, slip, initial_weight=None):
    # Frozen strategy when initial_weight is None, otherwise fixed initial passive mix.
    events={}
    if initial_weight is not None:
        w=float(initial_weight)
        if not 0<=w<=1: raise ValueError('Leverage prohibited')
        if w>0:
            events[a+pd.Timedelta(minutes=1)]=('buy',w)
            events[b-pd.Timedelta(minutes=1)]=('sell',1.)
    else:
        last=None
        for tr in trades.itertuples():
            en,ex=pd.Timestamp(tr.entry_hkt),pd.Timestamp(tr.exit_hkt)
            if en not in prices.index or ex not in prices.index: raise ValueError('Exact execution price absent')
            if ex-en!=pd.Timedelta(hours=24) or not a<en<ex<b: raise ValueError('Frozen holding period/segment violation')
            if last is not None and en<=last: raise ValueError('Overlapping or same-minute reentry')
            if en in events or ex in events: raise ValueError('Duplicate order')
            events[en]=('buy',1.);events[ex]=('sell',1.);last=ex
    cash=1.;qty=0.;post=[];pre=[];holding=[]
    for time,price in prices.items():
        pre.append(cash+qty*price)
        if time in events:
            side,weight=events[time]
            if side=='buy':
                if qty!=0: raise ValueError('Duplicate buy')
                spend=cash*weight;qty=spend/(price*(1+slip)*(1+fee));cash-=spend
            else:
                cash+=qty*price*(1-slip)*(1-fee);qty=0.
        v=cash+qty*price;post.append(v);holding.append(qty*price/v)
    if qty!=0: raise ValueError('Unliquidated position')
    n=pd.Series(post,index=prices.index);p=pd.Series(pre,index=prices.index);h=pd.Series(holding,index=prices.index)
    return evaluate(n,p,h,a,b)

def matched_weight(full_path, target_vol, a, b):
    def vol(w):
        dn=1-w+w*full_path.daily_nav.to_numpy()
        r=np.diff(np.r_[1.,dn])/np.r_[1.,dn[:-1]]
        return np.std(r,ddof=1)*np.sqrt(365)
    if target_vol<=0:return 0.
    if target_vol>=vol(1.):return 1.
    return float(brentq(lambda w:vol(w)-target_vol,0.,1.,xtol=1e-12))

def paired_inference(values,block=7,reps=REPS):
    x=np.asarray(values,float);n=len(x);m=x.mean()
    rng=np.random.default_rng(SEED);starts=rng.integers(0,n,size=(reps,int(np.ceil(n/block))))
    ix=((starts[:,:,None]+np.arange(block))%n).reshape(reps,-1)[:,:n]
    boot=x[ix].mean(1)
    lo,hi=np.quantile(boot,[.025,.975])
    p=(1+int(np.sum(boot-m>=m-1e-15)))/(reps+1)
    return {'mean_daily_log_excess':float(m),'ci_low_daily_log':float(lo),'ci_high_daily_log':float(hi),
       'p_centered_one_sided':float(p),'block_days':block,'observations':n}

def holm(ps):
    ps=np.asarray(ps,float);order=np.argsort(ps);ans=np.ones(len(ps));last=0.
    for k,j in enumerate(order):last=max(last,(len(ps)-k)*ps[j]);ans[j]=min(1.,last)
    return ans

def random_schedules(raw,year,trades,fee,slip,reps=REPS):
    a,b=bounds(year);r=raw.loc[(raw.index>=a)&(raw.index<b),'execution_open']
    if r.isna().any(): raise ValueError('Null control cannot use missing prices')
    px=r.to_numpy();n=len(px);allpositions=np.arange(n-24)
    quarters=r.index.quarter.to_numpy();hours=r.index.hour.to_numpy()
    specs=[]
    for en in pd.to_datetime(trades.entry_hkt,utc=True).dt.tz_convert(TZ):
        poss=allpositions[(quarters[:n-24]==en.quarter)&(hours[:n-24]==en.hour)]
        if len(poss)==0:raise ValueError('No control support')
        specs.append(poss)
    rng=np.random.default_rng(SEED+year);rets=[];minsep=[]
    cost=np.log((1-fee)*(1-slip)/((1+fee)*(1+slip)))
    for rep in range(reps):
        accepted=[]
        for i in rng.permutation(len(specs)):
            pool=specs[i]
            if accepted: pool=pool[np.all(np.abs(pool[:,None]-np.array(accepted)[None,:])>24,axis=1)]
            if not len(pool): raise RuntimeError('Null schedule placement failed; do not drop difficult replicates')
            accepted.append(int(rng.choice(pool)))
        accepted=np.sort(accepted)
        lg=np.log(px[accepted+24]/px[accepted])+cost
        rets.append(float(np.expm1(lg.sum())))
        minsep.append(int(np.diff(accepted).min()) if len(accepted)>1 else n)
    return np.array(rets),{'replicates':reps,'trades_per_replicate':len(specs),'minimum_gap_hours':min(minsep),
      'entry_quarter_counts':pd.to_datetime(trades.entry_hkt,utc=True).dt.tz_convert(TZ).dt.quarter.value_counts().sort_index().to_dict(),
      'preserves':'entry quarter counts, entry-hour multiset, 24h duration, turnover, no overlap; not exact within-quarter regime'}

def verify_inputs(folder):
    p=folder/'ETHUSDT_hourly_features.csv.gz'
    if hashlib.sha256(p.read_bytes()).hexdigest()!=PRICE_SHA: raise ValueError('Market hash differs')
    raw=pd.read_csv(p,index_col=0);raw.index=pd.to_datetime(raw.index,utc=True).tz_convert(TZ)
    if not raw.index.is_unique or not raw.index.is_monotonic_increasing: raise ValueError('Bad hourly index')
    rows=raw.loc[(raw.index>=pd.Timestamp('2025-01-01',tz=TZ))&(raw.index<pd.Timestamp('2026-09-15',tz=TZ))]
    if (rows.minutes!=60).any() or (rows.execution_delay_min!=0).any(): raise ValueError('Inherited price completeness check failed')
    if not np.array_equal(rows.execution_ms.astype('int64'), rows.index.asi8//1_000_000+60_000):raise ValueError('Execution misaligned')
    boundary=json.loads((folder/'boundary_klines.json').read_text())
    candles=[c for rq in boundary['requests'] for c in rq['result']]
    checks=[]
    for c in candles:
        time=pd.Timestamp(c[0],unit='ms',tz='UTC').tz_convert(TZ)
        if time.minute==1:
            got=raw.loc[time-pd.Timedelta(minutes=1),'execution_open'];assert got==float(c[1]);checks.append(str(time)+' open verified')
        if time.minute==59:
            got=raw.loc[time+pd.Timedelta(minutes=1),'close'];assert got==float(c[4]);checks.append(str(time)+' close verified')
    last={2025:float(next(c[1] for c in candles if c[0]==1767196740000)),2026:float(next(c[1] for c in candles if c[0]==1789401540000))}
    alltr=pd.read_csv(folder/'trades.csv');tr=alltr[alltr.symbol.eq('ETHUSDT')].copy()
    consistency=[]
    for (yr,cost),group in tr.groupby(['year','cost']):
        cash=1.;fee,slip=COSTS[cost]
        for rr in group.itertuples():
            en=pd.Timestamp(rr.entry_hkt)-pd.Timedelta(minutes=1);ex=pd.Timestamp(rr.exit_hkt)-pd.Timedelta(minutes=1)
            raw_r=raw.loc[ex,'execution_open']/raw.loc[en,'execution_open']-1
            assert abs(raw_r-rr.raw_return)<1e-12
            net=after_cost(raw_r,fee,slip);cash*=1+net
            assert abs(net-rr.net_return)<1e-12 and abs(cash-rr.cash_after)<1e-11
        consistency.append({'year':yr,'cost':cost,'trades':len(group),'net_return':cash-1})
    return raw,tr,last,{'boundary_checks':checks,'trade_reconciliation':consistency,'market_sha256':PRICE_SHA}

def monthly_info(paths,year):
    logs={key:np.log1p(v.daily_returns).groupby(v.daily_returns.index.strftime('%Y-%m')).sum() for key,v in paths.items()}
    log=pd.DataFrame(logs);m=np.expm1(log)
    records=[]
    for name in m:
        for state,mask in [('up',m.ETH100>0),('down',m.ETH100<0)]:
            n=int(mask.sum())
            bm=float(np.expm1(log.loc[mask,'ETH100'].mean())) if n else None
            sm=float(np.expm1(log.loc[mask,name].mean())) if n else None
            records.append({'year':year,'benchmark':name,'market_months':state,'months':n,
                'geomean_strategy_per_month':sm,'geomean_eth_per_month':bm,'capture_ratio':sm/bm if n and abs(bm)>1e-12 else None})
    return m,records

def run(root):
    inp=root/'input';out=root/'output';out.mkdir(exist_ok=True)
    status={'completed':False,'model_changed':False,'live_approved':False,'blind_oos':False,
      'protocol_commit':PROTOCOL_COMMIT,'started_at_utc':datetime.now(timezone.utc).isoformat(),
      'execution':'local container, analysis-only'}
    write_json(status,out/'execution_receipt.json')
    raw,tr,last,checks=verify_inputs(inp)
    summaries=[];captures=[];regimes=[];inference=[];nulls=[];monthly=[];weights=[];allpaths={};w25=None
    for yr in [2025,2026]:
        price,a,b=build_grid(raw,yr,last[yr]);tt=tr[(tr.year==yr)&(tr.cost=='base')].copy()
        empty=tt.iloc[:0];paths={}
        for cost,(fee,slip) in COSTS.items():
            name='Strategy' if cost=='base' else 'Strategy_stress'
            paths[name]=replay(price,a,b,tt,fee,slip)
            actual=float(tr[(tr.year==yr)&(tr.cost==cost)].cash_after.iloc[-1])-1
            assert abs(paths[name].metrics['net_return']-actual)<1e-11
        for nm,w in [('ETH100',1.),('Cash',0.),('ETH25',.25),('ETH50',.5)]:
            paths[nm]=replay(price,a,b,empty,*COSTS['base'],initial_weight=w)
        w=matched_weight(paths['ETH100'],paths['Strategy'].metrics['volatility_ann'],a,b)
        weights.append({'year':yr,'expost_matched_initial_eth_fraction':w,'known_in_advance':False})
        paths['Risk_matched_expost']=replay(price,a,b,empty,*COSTS['base'],initial_weight=w)
        if yr==2025:w25=w
        else:
            paths['Prior_year_weight']=replay(price,a,b,empty,*COSTS['base'],initial_weight=w25)
            weights.append({'year':yr,'prior_year_initial_eth_fraction':w25,'calibration_year':2025,'known_in_advance':True})
        # Passive higher-cost comparators preserve the same initial allocation.
        for nm,w in [('ETH100_stress',1.),('ETH25_stress',.25),('Risk_matched_expost_stress',w)]:
            paths[nm]=replay(price,a,b,empty,*COSTS['stress'],initial_weight=w)
        if yr==2026:
            paths['Prior_year_weight_stress']=replay(price,a,b,empty,*COSTS['stress'],initial_weight=w25)
        for name,p in paths.items():
            cov=np.cov(p.daily_returns,paths['ETH100'].daily_returns,ddof=1)
            beta=float(cov[0,1]/cov[1,1])
            held_days=len(tt) if name.startswith('Strategy') else None
            summaries.append({'year':yr,'account':name,**p.metrics,'beta_to_eth_daily':beta,
              'held_days':held_days,'closed_trades':len(tt) if name.startswith('Strategy') else (0 if name=='Cash' else 1),
              'excess_return_pp_vs_ETH100':100*(p.metrics['net_return']-paths['ETH100'].metrics['net_return']),
              'terminal_wealth_ratio_vs_ETH100':(1+p.metrics['net_return'])/(1+paths['ETH100'].metrics['net_return'])})
        navs=pd.DataFrame({k:p.nav for k,p in paths.items()});navs.to_csv(out/f'{yr}_common_grid_nav.csv.gz',index_label='time_hkt',compression={'method':'gzip','mtime':0})
        dr=pd.DataFrame({k:p.daily_returns for k,p in paths.items()})
        # Past 30d trend is defined at the start of each calendar day.
        start_prices=raw.close.reindex(dr.index).to_numpy()
        earlier=raw.close.reindex(dr.index-pd.Timedelta(days=30)).to_numpy()
        r30=start_prices/earlier-1
        dr['past30_regime']=np.where(r30>.05,'up',np.where(r30<-.05,'down','flat'))
        dr.to_csv(out/f'{yr}_daily_returns.csv',index_label='day_hkt')
        for state in ['down','flat','up']:
            ix=dr.past30_regime.eq(state)
            for name in ['Strategy','Strategy_stress','ETH100','ETH25','Risk_matched_expost']:
                vals=dr.loc[ix,name];eth=dr.loc[ix,'ETH100']
                regimes.append({'year':yr,'state_known_before_day':state,'account':name,'days':len(vals),
                  'mean_daily_return':float(vals.mean()),'conditional_compounded_return':float(np.expm1(np.log1p(vals).sum())),
                  'mean_daily_excess_vs_eth':float((vals-eth).mean())})
        mm,cc=monthly_info(paths,yr);mm.insert(0,'year',yr);monthly.append(mm);captures+=cc
        if yr==2026:
            for bench in ['Cash','ETH100','ETH25','Prior_year_weight']:
                delta=np.log1p(paths['Strategy'].daily_returns)-np.log1p(paths[bench].daily_returns)
                test=paired_inference(delta);d28=paired_inference(delta,28)
                inference.append({'benchmark':bench,**test,**{'block28_'+k:v for k,v in d28.items()}})
        for cost,(fee,slip) in COSTS.items():
            rnd,info=random_schedules(raw,yr,tt,fee,slip)
            actual=paths['Strategy' if cost=='base' else 'Strategy_stress'].metrics['net_return']
            q=np.quantile(rnd,[.025,.5,.975]);tail=(1+int(np.sum(rnd>=actual)))/(len(rnd)+1)
            nulls.append({'year':yr,'cost':cost,'actual_net_return':actual,'null_q025':q[0],'null_median':q[1],
              'null_q975':q[2],'empirical_upper_tail':tail,'actual_percentile':float((rnd<actual).mean()),**info})
            pd.DataFrame({'replicate':np.arange(len(rnd)),'net_return':rnd}).to_csv(out/f'{yr}_{cost}_random_controls.csv',index=False)
        allpaths[yr]=paths
    inf=pd.DataFrame(inference);inf['p_holm4']=holm(inf.p_centered_one_sided);inf.to_csv(out/'inference_2026.csv',index=False)
    pd.DataFrame(summaries).to_csv(out/'comparison.csv',index=False)
    pd.DataFrame(captures).to_csv(out/'monthly_capture.csv',index=False)
    pd.DataFrame(regimes).to_csv(out/'causal_regime_comparison.csv',index=False)
    pd.concat(monthly).to_csv(out/'monthly_returns.csv',index_label='month')
    pd.DataFrame(nulls).to_csv(out/'random_control_summary.csv',index=False)
    write_json(weights,out/'passive_weights.json');write_json(checks,out/'input_verification.json')
    joined=[]
    for nm in ['Strategy','Strategy_stress','ETH100','Cash','ETH25','ETH50']:
        combined=pd.concat([allpaths[y][nm].daily_returns for y in [2025,2026]])
        joined.append({'account':nm,'net_return_2025_through_20260914':float(np.expm1(np.log1p(combined).sum())),
            'boundary_convention':'concatenation of independently reset annual accounts; benchmark year-end turnover retained'})
    pd.DataFrame(joined).to_csv(out/'linked_periods.csv',index=False)
    status.update(completed=True,ended_at_utc=datetime.now(timezone.utc).isoformat(),
       original_trade_dates_preserved=True,new_strategy_fits=0,original_qualification_gate_unchanged=True,
       benchmark_rows=len(summaries),daily_rows=365+257,random_price_data_simulated=False,
       limitations=['Repeatedly reused history','Hourly closes/execution opens, not minute/tick extreme drawdown',
       'Ex-post risk-matched allocation is diagnostic only','Null dates match quarters/hours/turnover, not every market state',
       'USDT cash no yield/depeg/custody costs modelled','Analysis result does not approve live trading'])
    write_json(status,out/'execution_receipt.json')
    return pd.DataFrame(summaries),inf

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    args=ap.parse_args();s,i=run(args.root)
    print(s[['year','account','net_return','max_drawdown','volatility_ann','average_coin_weight']].to_string(index=False))
    print(i.to_string(index=False))
