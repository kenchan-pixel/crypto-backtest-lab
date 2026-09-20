"""Payoff-aware expected-return strategy on frozen sequence features."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,traceback
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from multifactor.data import load_inputs,SEED,TZ
from multifactor.evidence import holm
from sequence_strategy.study import build_sequences,encode_full_schema

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'payoff_outputs'

def dump(obj,path):
    Path(path).write_text(json.dumps(obj,indent=2,default=str))

def cost_net(rawret,fee,slip):
    return (1+rawret)*(1-fee)*(1-slip)/((1+fee)*(1+slip))-1

def choose_and_execute(events,frames,sym,year,pred,threshold,fee,slip):
    d=events[(events.symbol==sym)&(events.year==year)].copy()
    d['predicted_net']=pred
    d=d[d.predicted_net>=threshold].copy()
    if d.empty:
        return {},pd.DataFrame(),d
    # Deterministic collapse of simultaneous catalysts.
    d=d.sort_values(['entry_hkt','predicted_net','catalyst_type'],ascending=[True,False,True])
    d=d.drop_duplicates('entry_hkt',keep='first').sort_values('entry_hkt')
    raw=frames[sym];cash=1.;last_exit=None;trades=[];marks=[1.]
    for _,r in d.iterrows():
        entry_decision=pd.Timestamp(r.confirmation_hkt)
        exit_decision=pd.Timestamp(r.catalyst_hkt)+pd.Timedelta(hours=30)
        if last_exit is not None and entry_decision<=last_exit: continue
        rawret=float(r.post_confirm_return_24h)
        net=cost_net(rawret,fee,slip)
        before=cash;cash*=1+net
        # Mark hourly while holding using close, after paying entry costs.
        entry=float(raw.loc[entry_decision,'execution_open'])
        qty=before/(entry*(1+fee)*(1+slip))
        for t in raw.loc[entry_decision:exit_decision].index[1:]:
            marks.append(qty*float(raw.loc[t,'close']))
        marks.append(cash)
        trades.append({
          'symbol':sym,'year':year,'catalyst_hkt':r.catalyst_hkt,'entry_hkt':r.entry_hkt,'exit_hkt':r.exit_hkt,
          'catalyst_type':r.catalyst_type,'predicted_net':float(r.predicted_net),
          'raw_return':rawret,'net_return':net,'cash_after':cash
        })
        last_exit=exit_decision
    tr=pd.DataFrame(trades)
    if tr.empty:
        return {'trades':0,'compounded_return':0.},tr,d
    rets=tr.net_return.to_numpy(float)
    gains=rets[rets>0].sum();loss=-rets[rets<0].sum()
    m=np.asarray(marks,float);peak=np.maximum.accumulate(m)
    br=np.prod(1+np.delete(rets,np.argmax(rets)))-1 if len(rets)>1 else 0.
    rankcorr=tr.predicted_net.rank().corr(tr.net_return.rank()) if len(tr)>=3 else np.nan
    metrics={
      'trades':len(tr),'raw_signals_after_threshold':len(d),
      'win_rate':float((rets>0).mean()),'mean_return':float(rets.mean()),'median_return':float(np.median(rets)),
      'profit_factor':float(gains/loss) if loss>0 else (None if gains==0 else float('inf')),
      'compounded_return':float(cash-1),'max_drawdown_hourly':float(np.min(m/peak-1)),
      'best_trade_removed_return':float(br),'predicted_realized_rank_corr':None if pd.isna(rankcorr) else float(rankcorr)
    }
    return metrics,tr,d

def weekly_bootstrap(trades,reps=1999,days=7):
    if trades.empty:return {'p':1.,'ci_low':None,'ci_high':None,'clusters':0,'limited':True}
    t=pd.to_datetime(trades.entry_hkt,utc=True)
    start=t.min().floor('D');block=np.asarray((t-start)//pd.Timedelta(days=days),int)
    unique=np.unique(block);n=len(unique)
    if n<10:return {'p':1.,'ci_low':None,'ci_high':None,'clusters':n,'limited':True}
    sums=np.array([trades.loc[block==b,'net_return'].sum() for b in unique],float)
    counts=np.array([(block==b).sum() for b in unique],float)
    rng=np.random.default_rng(SEED);w=rng.multinomial(n,np.full(n,1/n),size=reps)
    boot=(w@sums)/(w@counts)
    lo,hi=np.quantile(boot,[.025,.975]);p=(1+np.sum(boot<=0))/(reps+1)
    return {'p':float(p),'ci_low':float(lo),'ci_high':float(hi),'clusters':n,'limited':False}

def model():
    return HistGradientBoostingRegressor(max_iter=100,learning_rate=.05,max_leaf_nodes=7,max_depth=3,
        min_samples_leaf=30,l2_regularization=10,early_stopping=False,random_state=SEED)

def main():
    OUT.mkdir(exist_ok=True)
    state={'completed':False,'protocol_commit':'a2e2c9dc87abc8c2219e6b8fc5c8c94e13345620',
           'started':datetime.now(timezone.utc).isoformat(),'live_approved':False,'genuine_unseen_holdout':False}
    dump(state,OUT/'execution_status.json')
    try:
        frames,checks=load_inputs(ROOT/'inputs')
        regimes=pd.read_csv(ROOT/'event_regime_outputs/hourly_regimes.csv.gz')
        events=pd.read_csv(ROOT/'event_regime_outputs/events.csv')
        seq=build_sequences(regimes,events,frames)
        X,vocab=encode_full_schema(seq);dump(vocab,OUT/'categorical_vocabulary.json')
        summaries=[];trades_all=[];signals_all=[];audit=[]
        thresholds={}
        for sym in ['BTCUSDT','ETHUSDT']:
            d=seq[seq.symbol==sym].copy()
            xs=X.loc[d.index]
            train=d.year.eq(2024).to_numpy()
            mdl=model();mdl.fit(xs.loc[train],d.loc[train,'event_long_net_base'].to_numpy(float))
            train_pred=mdl.predict(xs.loc[train])
            threshold=max(0.,float(np.quantile(train_pred,.90)));thresholds[sym]=threshold
            for year in [2025,2026]:
                take=d.year.eq(year).to_numpy();pred=mdl.predict(xs.loc[take])
                dy=d.loc[take].copy()
                # same prediction vector for base/stress; only costs differ.
                base,trb,sigs=choose_and_execute(d,frames,sym,year,pred,threshold,.001,.0005)
                stress,trs,_=choose_and_execute(d,frames,sym,year,pred,threshold,.0015,.0015)
                row={'symbol':sym,'year':year,'threshold':threshold,
                     **{'base_'+k:v for k,v in base.items()},**{'stress_'+k:v for k,v in stress.items()}}
                summaries.append(row)
                if not trb.empty:
                    trb['cost']='base';trades_all.append(trb)
                if not trs.empty:
                    trs['cost']='stress';trades_all.append(trs)
                if not sigs.empty:
                    sigs=sigs.copy();sigs['symbol']=sym;sigs['year']=year;signals_all.append(sigs)
                if year==2026:
                    inf=weekly_bootstrap(trb,1999,7);diag=weekly_bootstrap(trb,1999,28)
                    audit.append({'symbol':sym,**inf,**{'block28_'+k:v for k,v in diag.items()}})
        summary=pd.DataFrame(summaries)
        aud=pd.DataFrame(audit);aud['p_holm2']=holm(aud.p)
        # Candidate gates fixed before reading results.
        candidates=[]
        for sym in ['BTCUSDT','ETHUSDT']:
            s25=summary[(summary.symbol==sym)&(summary.year==2025)].iloc[0]
            s26=summary[(summary.symbol==sym)&(summary.year==2026)].iloc[0]
            p=float(aud[aud.symbol==sym].iloc[0].p_holm2)
            gate25=(s25.base_trades>=30 and s25.base_compounded_return>0 and s25.stress_compounded_return>0 and
                    s25.base_profit_factor>1.10 and s25.base_best_trade_removed_return>0)
            gate26=(s26.base_trades>=15 and s26.base_compounded_return>0 and s26.stress_compounded_return>0 and
                    s26.base_profit_factor>1.10 and s26.base_best_trade_removed_return>0 and p<.05)
            if gate25 and gate26:candidates.append({'symbol':sym,'threshold':thresholds[sym]})
        summary.to_csv(OUT/'strategy_summary.csv',index=False)
        aud.to_csv(OUT/'audit_inference.csv',index=False)
        if trades_all:pd.concat(trades_all,ignore_index=True).to_csv(OUT/'trades.csv',index=False)
        else:pd.DataFrame().to_csv(OUT/'trades.csv',index=False)
        if signals_all:pd.concat(signals_all,ignore_index=True).to_csv(OUT/'raw_signals.csv.gz',index=False,compression={'method':'gzip','mtime':0})
        dump(thresholds,OUT/'thresholds.json');dump(candidates,OUT/'research_candidates.json')
        state.update(completed=True,thresholds=thresholds,research_candidates=len(candidates),input_checks=checks,
                     ended=datetime.now(timezone.utc).isoformat())
        dump(state,OUT/'execution_status.json');print(json.dumps(state,indent=2,default=str));print(summary.to_string(index=False));print(aud.to_string(index=False))
    except Exception as e:
        state.update(error=type(e).__name__+': '+str(e));dump(state,OUT/'execution_status.json');traceback.print_exc();raise

if __name__=='__main__':main()
