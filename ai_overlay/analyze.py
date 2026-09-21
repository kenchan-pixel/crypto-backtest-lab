"""Evaluate a locked, actual assistant decision ledger, not an LLM rule proxy.
Replaying this module never regenerates or selects AI responses.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json
import numpy as np
import pandas as pd
from ai_overlay.session import ROOT, TZ, PROTOCOL_COMMIT, digest
from benchmark_review.analyze import evaluate, build_grid, replay, after_cost, paired_inference, holm, write_json
COSTS={'base':(.001,.0005),'stress':(.0015,.0015)}
TRADE_COLS=['entry_hkt','exit_hkt','decision_step','weight','entry_open','exit_open','raw_return','net_asset_return','account_return','realized_pnl','cash_before','cash_after']

def verify_ledger(root=ROOT):
    folder=root/'ledger'
    locked=json.loads((folder/'DECISIONS_LOCK.json').read_text())
    for name,h in locked['decision_files'].items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=h:
            raise ValueError('Frozen ledger hash changed: '+name)
    mapping=json.loads((folder/'mapping.json').read_text())
    ds=[json.loads(line) for line in (folder/'decisions.jsonl').read_text().splitlines()]
    if len(ds)!=len(mapping) or len(ds)!=91:raise ValueError('Decision coverage incomplete')
    previous=None;last_recorded=None
    for i,(m,d) in enumerate(zip(mapping,ds),1):
        p=json.loads((folder/f'packets/{i:03d}.json').read_text())
        if m['step']!=i or d['step']!=i or p['step']!=i:raise ValueError('Out-of-order decision')
        if d['packet_sha256']!=digest(p) or m['packet_sha256']!=digest(p):raise ValueError('Packet hash mismatch')
        if d['previous_decision_sha256']!=previous:raise ValueError('Decision hash chain broken')
        if d['weight'] not in [0,.5,1] or d['protocol_commit']!=PROTOCOL_COMMIT:raise ValueError('Unauthorized decision')
        if pd.Timestamp(m['effective'])-pd.Timestamp(m['cut'])!=pd.Timedelta(hours=1):raise ValueError('Effectiveness lag error')
        recorded=pd.Timestamp(d['recorded_at_utc'])
        if last_recorded is not None and recorded<last_recorded:raise ValueError('Recording time order')
        if recorded>pd.Timestamp(locked['locked_at_utc']):raise ValueError('Decision recorded after lock')
        if 'forward_return' in str(p) or 'cash_after' in str(p):raise ValueError('Forbidden future outcome key')
        if p['news']!='historical_news_unavailable':raise ValueError('Unexpected unverified news')
        previous=digest(d);last_recorded=recorded
    return mapping,ds,{'decisions':len(ds),'packets':len(mapping),'hash_chain_valid':True,'lock':locked,
          'not_blind':True,'historical_context_already_known':True,'fresh_model_responses_reproducible':False}

def allocation(entry,year,name,mapping,ds):
    if name=='Original':return 1.,None
    if name=='Half':return .5,None
    if name not in ['LLM','Simple']:raise ValueError(name)
    candidates=[m for m in mapping if m['year']==year and pd.Timestamp(m['effective'])<=entry]
    if not candidates:return .5,None
    m=candidates[-1]
    return (float(ds[m['step']-1]['weight']) if name=='LLM' else float(m['simple_weight'])),m['step']

def weighted_replay(prices,a,b,trades,weights,decision_steps,fee,slip):
    """Same exported opportunities, sized at entry only; no new overlapping signals."""
    if len(weights)!=len(trades) or len(decision_steps)!=len(trades):raise ValueError('Weight/trade length mismatch')
    events={};last=None
    for row,w,step in zip(trades.itertuples(),weights,decision_steps):
        en,ex=pd.Timestamp(row.entry_hkt),pd.Timestamp(row.exit_hkt)
        if w not in [0,.5,1]:raise ValueError('Unsupported allocation')
        if ex-en!=pd.Timedelta(hours=24) or not a<en<ex<b:raise ValueError('Holding period or bounds')
        if last is not None and en<=last:raise ValueError('Parent overlap or same-minute reentry')
        last=ex
        if en not in prices.index or ex not in prices.index:raise ValueError('Missing actual execution price')
        if w>0:events[en]=('buy',w,step);events[ex]=('sell',w,step)
    cash=1.;qty=0.;post=[];pre=[];holding=[];trade_rows=[];entry=None
    for t,px in prices.items():
        pre.append(cash+qty*px)
        if t in events:
            side,w,step=events[t]
            if side=='buy':
                if qty!=0:raise ValueError('Double buy')
                before=cash;spend=cash*w;qty=spend/(px*(1+fee)*(1+slip));cash-=spend
                entry=(t,px,spend,before,w,step)
            else:
                if entry is None or qty<=0:raise ValueError('Missing entry')
                proceeds=qty*px*(1-fee)*(1-slip);pnl=proceeds-entry[2];cash+=proceeds
                trade_rows.append(dict(entry_hkt=str(entry[0]),exit_hkt=str(t),decision_step=entry[5],weight=entry[4],
                  entry_open=entry[1],exit_open=px,raw_return=px/entry[1]-1,
                  net_asset_return=proceeds/entry[2]-1,account_return=cash/entry[3]-1,realized_pnl=pnl,
                  cash_before=entry[3],cash_after=cash))
                qty=0.;entry=None
        nav=cash+qty*px
        if not np.isfinite(nav) or nav<=0:raise ValueError('Invalid NAV')
        post.append(nav);holding.append(qty*px/nav)
    if qty!=0:raise ValueError('Missing exit')
    path=evaluate(pd.Series(post,index=prices.index),pd.Series(pre,index=prices.index),pd.Series(holding,index=prices.index),a,b)
    tt=pd.DataFrame(trade_rows,columns=TRADE_COLS)
    pnls=tt.realized_pnl.to_numpy(float);ar=tt.account_return.to_numpy(float)
    positive=pnls[pnls>0].sum();negative=-pnls[pnls<0].sum()
    m=dict(path.metrics)
    m.update(trades=len(tt),win_rate=float((pnls>0).mean()) if len(tt) else None,
      mean_account_trade_return=float(ar.mean()) if len(tt) else None,median_account_trade_return=float(np.median(ar)) if len(tt) else None,
      profit_factor_realized_pnl=float(positive/negative) if negative>0 else (float('inf') if positive>0 else None),
      best_trade_removed_return=float(np.prod(1+np.delete(ar,np.argmax(ar)))-1) if len(tt) else 0.,
      held_time_fraction=float(len(tt)*24*3600/(b-a).total_seconds()),skipped_opportunities=len(trades)-len(tt))
    if abs(np.sum(pnls)-(cash-1))>1e-10:raise ValueError('Realized PnL accounting')
    return path,tt,m

def inputs(root=ROOT):
    from multifactor.data import load_inputs
    frames,checks=load_inputs(root/'inputs')
    raw=frames['ETHUSDT']
    tx=pd.read_csv(root/'input/trades.csv');alltr=tx[tx.symbol.eq('ETHUSDT')].copy()
    b=json.loads((root/'input/boundary_klines.json').read_text())
    candles=[c for rq in b['requests'] for c in rq['result']]
    last={2025:float(next(c[1] for c in candles if c[0]==1767196740000)),2026:float(next(c[1] for c in candles if c[0]==1789401540000))}
    reconc=[]
    for (year,cost),rows in alltr.groupby(['year','cost']):
        cash=1.
        for r in rows.itertuples():
            en=pd.Timestamp(r.entry_hkt)-pd.Timedelta(minutes=1);ex=pd.Timestamp(r.exit_hkt)-pd.Timedelta(minutes=1)
            actual=raw.loc[ex,'execution_open']/raw.loc[en,'execution_open']-1
            net=after_cost(actual,*COSTS[cost]);cash*=1+net
            if not np.isclose(actual,r.raw_return,atol=1e-12,rtol=0) or not np.isclose(net,r.net_return,atol=1e-12,rtol=0) or not np.isclose(cash,r.cash_after,atol=1e-11,rtol=0):raise ValueError('Original trade does not reconcile')
        reconc.append(dict(year=year,cost=cost,trades=len(rows),net_return=cash-1))
    return raw,alltr,last,{'market_checks':checks,'original_trade_reconciliation':reconc}

def run(root=ROOT):
    out=root/'output';out.mkdir(exist_ok=True)
    mapping,decisions,ledger=verify_ledger(root)
    status={'completed':False,'paper_trade_enabled':False,'live_approved':False,'protocol_commit':PROTOCOL_COMMIT,
       'decision_ledger_sha256':ledger['lock']['decision_files']['decisions.jsonl'],'started_at_utc':datetime.now(timezone.utc).isoformat(),
       'execution_location':'ChatGPT computation container','model_calls':'91 sequential assistant-written decisions in this conversation; no external API batch',
       'not_blind':True,'cost_method':'Trading accounts self-financing; review budget accrued separately and subtracted from daily NAV / terminal wealth; not paid out of trading cash.'}
    write_json(status,out/'execution_receipt.json')
    raw,alltr,last,checks=inputs(root)
    summary=[];fulltr=[];audit=[];overhead=[];opportunities=[];yearpaths={};decisiontable=[]
    for m,d in zip(mapping,decisions):decisiontable.append({**m,**d})
    pd.DataFrame(decisiontable).to_csv(out/'weekly_decisions.csv',index=False)
    for year in [2025,2026]:
        prices,a,b=build_grid(raw,year,last[year]);tr=alltr[(alltr.year==year)&(alltr.cost=='base')].copy().reset_index(drop=True)
        paths={};empty=tr.iloc[:0]
        for name in ['Original','Simple','Half','LLM']:
            ws,steps=zip(*[allocation(pd.Timestamp(r.entry_hkt),year,name,mapping,decisions) for r in tr.itertuples()]) if len(tr) else ([],[])
            for cost,(fee,slip) in COSTS.items():
                path,tt,metrics=weighted_replay(prices,a,b,tr,ws,steps,fee,slip)
                key=name if cost=='base' else name+'_stress';paths[key]=path
                summary.append(dict(year=year,account=name,cost=cost,**metrics))
                if name=='Original':
                    expected=alltr[(alltr.year==year)&(alltr.cost==cost)].cash_after.iloc[-1]-1
                    if abs(metrics['net_return']-expected)>1e-10:raise ValueError('Full-size baseline reproduction')
                tt.insert(0,'account',name);tt.insert(0,'year',year);tt.insert(2,'cost',cost);fulltr.append(tt)
            if name=='LLM':
                for r,w,step in zip(tr.itertuples(),ws,steps):
                    opportunities.append(dict(year=year,entry_hkt=r.entry_hkt,step=step,weight=w,original_net_return=r.net_return,
                        reduced_fraction=1-w,reduction_label='missed_winner' if r.net_return>0 else 'avoided_loser',
                        scaled_effect_on_one_unit=(w-1)*r.net_return))
        for name,w in [('ETH100',1),('ETH25',.25),('Cash',0)]:
            path=replay(prices,a,b,empty,*COSTS['base'],initial_weight=w);paths[name]=path
            summary.append(dict(year=year,account=name,cost='base',**path.metrics))
        # Operating budgets are explicitly a separate accrued expense, not a claim about billing.
        cuts=[pd.Timestamp(m['effective']) for m in mapping if m['year']==year]
        for cost in COSTS:
            key='LLM' if cost=='base' else 'LLM_stress';path=paths[key]
            dailyend=path.daily_nav.index
            charged=np.array([sum(c<=t for c in cuts) for t in dailyend],int)
            for budget in [0,.0001,.0005]:
                dn=path.daily_nav-budget*charged
                dr=pd.Series(np.diff(np.r_[1.,dn])/np.r_[1.,dn[:-1]],index=path.daily_returns.index)
                dr.to_csv(out/f'{year}_LLM_{cost}_overhead_{budget:.4f}_daily.csv',index_label='day_hkt')
                overhead.append(dict(year=year,cost=cost,initial_capital_budget_per_review=budget,reviews=len(cuts),total_budget=len(cuts)*budget,
                                     return_after_budget=path.metrics['net_return']-len(cuts)*budget))
        pd.DataFrame({k:v.daily_returns for k,v in paths.items()}).to_csv(out/f'{year}_daily_returns.csv',index_label='day_hkt')
        pd.DataFrame({k:v.nav for k,v in paths.items()}).to_csv(out/f'{year}_nav.csv.gz',index_label='time_hkt',compression={'method':'gzip','mtime':0})
        monthly=pd.DataFrame({k:np.expm1(np.log1p(v.daily_returns).groupby(v.daily_returns.index.strftime('%Y-%m')).sum()) for k,v in paths.items()})
        monthly.to_csv(out/f'{year}_monthly_returns.csv',index_label='month_hkt')
        if year==2026:
            for benchmark in ['Original','Simple','Half','Cash']:
                delta=np.log1p(paths['LLM'].daily_returns)-np.log1p(paths[benchmark].daily_returns)
                main=paired_inference(delta.to_numpy(),7,4999);diag=paired_inference(delta.to_numpy(),28,4999)
                audit.append(dict(benchmark=benchmark,**main,**{'block28_'+k:v for k,v in diag.items()}))
        yearpaths[year]=paths
    su=pd.DataFrame(summary);trades=pd.concat(fulltr,ignore_index=True)
    ai=pd.DataFrame(audit);ai['p_holm4']=holm(ai.p_centered_one_sided)
    ov=pd.DataFrame(overhead);ops=pd.DataFrame(opportunities)
    su.to_csv(out/'account_summary.csv',index=False);trades.to_csv(out/'trades.csv',index=False)
    ai.to_csv(out/'audit_inference.csv',index=False);ov.to_csv(out/'overhead_scenarios.csv',index=False);ops.to_csv(out/'opportunity_effects.csv',index=False)
    get=lambda y,n:su[(su.year==y)&(su.account==n)&(su.cost=='base')].iloc[0]
    r25=get(2025,'LLM');r26=get(2026,'LLM');simple=get(2026,'Simple');half=get(2026,'Half')
    stress_after=ov[(ov.cost=='stress')&(ov.initial_capital_budget_per_review==.0001)].return_after_budget.to_numpy()
    compound_stress=float(np.prod(1+stress_after)-1)
    financial_gates={
      '2026_at_least_15_trades':r26.trades>=15,
      '2025_nonnegative_base_return':r25.net_return>=0,
      '2026_return_at_least_simple':r26.net_return>=simple.net_return,
      '2026_return_at_least_half':r26.net_return>=half.net_return,
      '2026_drawdown_no_worse_than_simple':r26.max_drawdown>=simple.max_drawdown,
      'combined_stress_after_review_budget_positive':compound_stress>0,
      '2026_best_trade_removed_nonnegative':r26.best_trade_removed_return>=0}
    gate={'financial_gates':financial_gates,'all_financial_gates_pass':all(financial_gates.values()),
          'combined_stress_after_001pct_review_budget':compound_stress,'technical_tests_independent_verification_pending':True,
          'paper_trade_enabled':False,'live_approved':False}
    write_json(gate,out/'paper_gate.json');write_json(checks,out/'input_checks.json');write_json(ledger,out/'ledger_verification.json')
    status.update(completed=True,ended_at_utc=datetime.now(timezone.utc).isoformat(),decisions=len(decisions),financial_gate_pass=all(financial_gates.values()),
       stored_ledger_replayed=True,AI_regenerated=False)
    write_json(status,out/'execution_receipt.json')
    print(su[['year','account','cost','net_return','max_drawdown','trades']].to_string(index=False))
    print(json.dumps(gate,indent=2,default=lambda x:bool(x) if isinstance(x,np.bool_) else x))
    return su
if __name__=='__main__':run()
