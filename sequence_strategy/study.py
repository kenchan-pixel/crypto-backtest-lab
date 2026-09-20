"""Frozen sequence-strategy discovery on Event + Regime Dataset v1."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,traceback
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

from multifactor.data import load_inputs,SEED,TZ
from multifactor.evidence import paths_from_tree,condition_mask,holm

ROOT=Path(__file__).resolve().parent.parent
REGIME=ROOT/'event_regime_outputs/hourly_regimes.csv.gz'
EVENTS=ROOT/'event_regime_outputs/events.csv'
OUT=ROOT/'sequence_outputs'

CATALYST_TRANSITIONS={
 'funding_state':['crowded_long','crowded_short'],
 'oi_state':['leverage_build','deleveraging'],
 'vol_state':['expanded'],
 'cross_asset_state':['leader','laggard'],
 'positioning_state':['long_crowded','short_crowded'],
}
FAMILY_BY_COL={
 'funding_state':'funding','oi_state':'oi','vol_state':'volatility',
 'cross_asset_state':'cross_asset','positioning_state':'positioning'
}
CATEGORICAL=[
 'catalyst_type','catalyst_family','trend_30d','trend_7d','vol_state',
 'cross_asset_state','funding_state','oi_state','positioning_state','confirmation_bucket'
]
NUMERIC=['confirmation_return_6h','confirm_vol_expanded','confirm_oi_leverage_build',
         'confirm_oi_deleveraging','confirm_cross_leader','confirm_cross_laggard']

def dump(obj,path):
    Path(path).write_text(json.dumps(obj,indent=2,default=str))

def cooldown_times(times,hours=24):
    out=[];last=None;gap=pd.Timedelta(hours=hours)
    for t in sorted(pd.DatetimeIndex(times)):
        if last is None or t>=last+gap:
            out.append(t);last=t
    return out

def macro_sign(row):
    if pd.isna(row.forecast) or pd.isna(row.actual): return 'no_forecast'
    d=float(row.actual)-float(row.forecast)
    if d>0: return 'positive'
    if d<0: return 'negative'
    return 'inline'

def confirmation_bucket(r):
    if pd.isna(r): return 'unknown'
    if r<=-.01:return 'strong_down'
    if r<-.0025:return 'down'
    if r<=.0025:return 'flat'
    if r<.01:return 'up'
    return 'strong_up'

def build_sequences(regimes,events,frames):
    allrows=[]
    for sym in ['BTCUSDT','ETHUSDT']:
        r=regimes[regimes.symbol==sym].copy()
        r['decision_hkt']=pd.to_datetime(r.decision_hkt,utc=True).dt.tz_convert(TZ)
        r=r.sort_values('decision_hkt').set_index('decision_hkt')
        raw=frames[sym]
        catalysts=[]
        # Endogenous transitions into a newly extreme state.
        for col,targets in CATALYST_TRANSITIONS.items():
            prev=r[col].shift()
            for state in targets:
                mask=(r[col]==state)&(prev!=state)
                for t in cooldown_times(r.index[mask],24):
                    catalysts.append((t,f'{col}:{state}',FAMILY_BY_COL[col],'endogenous'))
        # Historical macro catalysts, duplicated to each coin.
        m=events[events.event_type=='macro'].copy()
        for _,row in m.iterrows():
            t=pd.Timestamp(row.usable_at_hkt)
            if t.tzinfo is None:t=t.tz_localize(TZ)
            else:t=t.tz_convert(TZ)
            if t not in r.index: continue
            catalysts.append((t,f'macro:{row.event_subtype}:{macro_sign(row)}','macro','macro'))
        catalysts.sort(key=lambda z:(z[0],z[1]))
        for t,ctype,family,origin in catalysts:
            t6=t+pd.Timedelta(hours=6);t30=t+pd.Timedelta(hours=30)
            if t6 not in r.index or t30 not in raw.index or t not in raw.index: continue
            # target must remain inside the same calendar evaluation year and source window.
            if t30.year!=t.year: continue
            if t30>=pd.Timestamp('2026-09-15',tz=TZ): continue
            base=r.loc[t];conf=r.loc[t6]
            c_ret=float(conf['close']/base['close']-1)
            entry=float(raw.loc[t6,'execution_open']);exitp=float(raw.loc[t30,'execution_open'])
            if not np.isfinite(entry) or not np.isfinite(exitp):continue
            rawret=exitp/entry-1
            label=2 if rawret>=.01 else (0 if rawret<=-.01 else 1)
            cost_factor=(1-.001)*(1-.0005)/((1+.001)*(1+.0005))
            event_net=(1+rawret)*cost_factor-1
            row={
              'symbol':sym,'catalyst_hkt':t,'confirmation_hkt':t6,'entry_hkt':t6+pd.Timedelta(minutes=1),
              'exit_hkt':t30+pd.Timedelta(minutes=1),'year':t.year,'quarter':str(t.to_period('Q')),
              'catalyst_type':ctype,'catalyst_family':family,'catalyst_origin':origin,
              'trend_30d':base.trend_30d,'trend_7d':base.trend_7d,'vol_state':base.vol_state,
              'cross_asset_state':base.cross_asset_state,'funding_state':base.funding_state,
              'oi_state':base.oi_state,'positioning_state':base.positioning_state,
              'confirmation_return_6h':c_ret,'confirmation_bucket':confirmation_bucket(c_ret),
              'confirm_vol_expanded':float(conf.vol_state=='expanded'),
              'confirm_oi_leverage_build':float(conf.oi_state=='leverage_build'),
              'confirm_oi_deleveraging':float(conf.oi_state=='deleveraging'),
              'confirm_cross_leader':float(conf.cross_asset_state=='leader'),
              'confirm_cross_laggard':float(conf.cross_asset_state=='laggard'),
              'target':label,'post_confirm_return_24h':rawret,'event_long_net_base':event_net
            }
            allrows.append(row)
    df=pd.DataFrame(allrows).sort_values(['symbol','catalyst_hkt','catalyst_type']).reset_index(drop=True)
    return df

def encode_full_schema(df):
    # Vocabulary uses feature values only, never outcomes.
    cats={c:sorted(df[c].dropna().astype(str).unique().tolist()) for c in CATEGORICAL}
    enc=OneHotEncoder(categories=[cats[c] for c in CATEGORICAL],handle_unknown='ignore',sparse_output=False,dtype=float)
    transformer=ColumnTransformer([('cat',enc,CATEGORICAL),('num','passthrough',NUMERIC)],remainder='drop',verbose_feature_names_out=False)
    X=transformer.fit_transform(df)
    cols=transformer.get_feature_names_out().tolist()
    return pd.DataFrame(X,index=df.index,columns=cols),cats

def nonoverlap_times(times,hours=24):
    return cooldown_times(times,hours)

def matched_lift(df,mask,direction):
    target=(df.target.to_numpy()==direction).astype(float)
    strata=(df.quarter.astype(str)+'|'+df.catalyst_family.astype(str)).to_numpy()
    levels=np.unique(strata)
    sig_total=0.;sig_y=0.;weighted_control=0.;eligible_hours=0
    for s in levels:
        ix=strata==s;sig=ix&mask;ctrl=ix&(~mask)
        ns=int(sig.sum());nc=int(ctrl.sum())
        if ns>0 and nc>=20:
            sig_total+=ns;sig_y+=target[sig].sum()
            weighted_control+=ns*target[ctrl].mean();eligible_hours+=ns
    allsig=int(mask.sum())
    if sig_total==0:return np.nan,np.nan,np.nan,0.
    ps=sig_y/sig_total;pc=weighted_control/sig_total
    return float(ps-pc),float(ps),float(pc),float(eligible_hours/allsig) if allsig else 0.

def describe_rule(df,mask,direction):
    lift,ps,pc,cov=matched_lift(df,mask,direction)
    times=pd.DatetimeIndex(df.loc[mask,'catalyst_hkt'])
    non=len(nonoverlap_times(times,24))
    qs={}
    for q in sorted(df.quarter.unique()):
        take=df.quarter.eq(q).to_numpy()
        qlift,*_=matched_lift(df.loc[take].reset_index(drop=True),mask[take],direction)
        qs[q]=None if not np.isfinite(qlift) else float(qlift)
    ret=df.loc[mask,'post_confirm_return_24h'].to_numpy(float)
    net=df.loc[mask,'event_long_net_base'].to_numpy(float)
    return {
      'signal_events':int(mask.sum()),'nonoverlap_24h_events':int(non),
      'matched_lift':lift,'matched_probability':ps,'matched_control_probability':pc,
      'matched_coverage':cov,'positive_quarters':sum(v is not None and v>0 for v in qs.values()),
      'quarter_lifts':json.dumps(qs),'mean_forward_return':float(np.mean(ret)) if len(ret) else None,
      'median_forward_return':float(np.median(ret)) if len(ret) else None,
      'mean_long_net_return':float(np.mean(net)) if len(net) else None,
      'target_probability':float((df.loc[mask,'target'].to_numpy()==direction).mean()) if mask.sum() else None
    }

def cluster_test(df,mask,direction,reps=1999,block_days=7):
    obs,*_=matched_lift(df,mask,direction)
    if not np.isfinite(obs):return {'p':1.,'ci_low':None,'ci_high':None,'limited':True,'clusters':0}
    t=pd.DatetimeIndex(df.catalyst_hkt)
    start=t.min().floor('D')
    block=((t-start)//pd.Timedelta(days=block_days)).astype(int)
    unique=np.unique(block)
    supporting=len(np.unique(block[mask]))
    if supporting<10:return {'p':1.,'ci_low':None,'ci_high':None,'limited':True,'clusters':supporting}
    rng=np.random.default_rng(SEED);boot=[]
    for _ in range(reps):
        sampled=rng.choice(unique,size=len(unique),replace=True)
        pieces=[]
        for b in sampled:
            z=df.loc[block==b].copy()
            z['_origmask']=mask[block==b]
            pieces.append(z)
        x=pd.concat(pieces,ignore_index=True);m=x.pop('_origmask').to_numpy(bool)
        v,*_=matched_lift(x,m,direction)
        if np.isfinite(v):boot.append(v)
    if len(boot)<reps*.9:return {'p':1.,'ci_low':None,'ci_high':None,'limited':True,'clusters':supporting}
    boot=np.asarray(boot);lo,hi=np.quantile(boot,[.025,.975])
    # one-sided p for lift <= 0, centered empirical approximation.
    p=float((1+np.sum(boot<=0))/(len(boot)+1))
    return {'p':p,'ci_low':float(lo),'ci_high':float(hi),'limited':False,'clusters':supporting,'bootstrap_replicates':len(boot)}

def select_2025(ev):
    chosen=[]
    for sym in ['BTCUSDT','ETHUSDT']:
      for direction,dname in [(2,'up'),(0,'down')]:
        v=ev[(ev.symbol==sym)&(ev.year==2025)&(ev.direction==dname)].copy()
        train=ev[(ev.symbol==sym)&(ev.year==2024)&(ev.direction==dname)].set_index('leaf').matched_lift
        v['train_lift']=v.leaf.map(train)
        ok=(v.nonoverlap_24h_events>=30)&(v.matched_lift>=.08)&(v.matched_coverage>=.70)&(v.positive_quarters>=3)&(v.train_lift>0)
        if dname=='up':ok &= v.mean_long_net_return>0
        good=v[ok].sort_values(['matched_lift','leaf'],ascending=[False,True])
        if len(good):
            r=good.iloc[0];chosen.append({'symbol':sym,'direction':dname,'leaf':int(r.leaf),'rule':r.rule,'validation_lift':float(r.matched_lift)})
    return chosen

def account(df,frames,sym,leaf_mask,year,fee,slip):
    signals=df[(df.symbol==sym)&(df.year==year)].loc[leaf_mask].sort_values('entry_hkt')
    raw=frames[sym];cash=1.;last_exit=None;trades=[];equity=[1.]
    for _,s in signals.iterrows():
        et=pd.Timestamp(s.confirmation_hkt);xt=pd.Timestamp(s.catalyst_hkt)+pd.Timedelta(hours=30)
        if last_exit is not None and et<=last_exit:continue
        entry=float(raw.loc[et,'execution_open']);exitp=float(raw.loc[xt,'execution_open'])
        qty=cash/(entry*(1+fee)*(1+slip));after=qty*exitp*(1-fee)*(1-slip)
        net=after/cash-1
        trades.append({'entry_hkt':str(et+pd.Timedelta(minutes=1)),'exit_hkt':str(xt+pd.Timedelta(minutes=1)),
                       'entry_price':entry,'exit_price':exitp,'net_return':net,'cash_after':after})
        # hourly observable equity marks
        for t in raw.loc[et:xt].index[1:]:
            equity.append(qty*float(raw.loc[t,'close']))
        equity.append(after);cash=after;last_exit=xt
    eq=np.asarray(equity,float);peak=np.maximum.accumulate(eq);dd=np.min(eq/peak-1) if len(eq) else 0.
    rets=np.array([x['net_return'] for x in trades],float)
    gains=rets[rets>0].sum();loss=-rets[rets<0].sum()
    best_removed=None
    if len(rets):
        j=np.argmax(rets);best_removed=float(np.prod(1+np.delete(rets,j))-1) if len(rets)>1 else 0.
    metrics={'trades':len(trades),'win_rate':float((rets>0).mean()) if len(rets) else None,
             'mean_return':float(rets.mean()) if len(rets) else None,'median_return':float(np.median(rets)) if len(rets) else None,
             'profit_factor':float(gains/loss) if loss>0 else (None if gains==0 else float('inf')),
             'compounded_return':float(cash-1),'max_drawdown_hourly':float(dd),'best_trade_removed_return':best_removed}
    return metrics,pd.DataFrame(trades)

def main():
    OUT.mkdir(exist_ok=True)
    state={'completed':False,'protocol_commit':'7b83a4be3b977f97aed2cd8bf9a2c84d7fa3165f',
           'started':datetime.now(timezone.utc).isoformat(),'live_approved':False,'genuine_unseen_holdout':False}
    dump(state,OUT/'execution_status.json')
    try:
      regimes=pd.read_csv(REGIME)
      events=pd.read_csv(EVENTS)
      frames,checks=load_inputs(ROOT/'inputs')
      seq=build_sequences(regimes,events,frames)
      seq.to_csv(OUT/'sequence_events.csv.gz',index=False,compression={'method':'gzip','mtime':0})
      X,vocab=encode_full_schema(seq);dump(vocab,OUT/'categorical_vocabulary.json')
      evidence=[];models={};pathmaps={}
      for sym in ['BTCUSDT','ETHUSDT']:
        d=seq[seq.symbol==sym].copy().reset_index()
        xs=X.loc[d['index']].reset_index(drop=True)
        train=d.year.eq(2024).to_numpy()
        tree=DecisionTreeClassifier(max_depth=4,max_leaf_nodes=12,min_samples_leaf=30,random_state=SEED)
        tree.fit(xs.loc[train],d.loc[train,'target'].astype(int))
        paths=paths_from_tree(tree,list(xs.columns));pathmaps[sym]=(d,xs,tree,paths)
        dump(paths,OUT/f'{sym}_tree_paths.json')
        for path in paths:
          mask=condition_mask(xs,path['conditions'])
          assert np.array_equal(mask,tree.apply(xs)==path['leaf'])
          for year in [2024,2025]:
            take=d.year.eq(year).to_numpy()
            dy=d.loc[take].reset_index(drop=True);mm=mask[take]
            for direction,dname in [(2,'up'),(0,'down')]:
              evidence.append({'symbol':sym,'leaf':path['leaf'],'direction':dname,'year':year,'rule':path['rule'],
                               **describe_rule(dy,mm,direction)})
      ev=pd.DataFrame(evidence)
      selected=select_2025(ev);dump({'selection':selected,'uses_2026_outcomes':False},OUT/'selection_before_2026.json')
      # Audit all paths after selection freeze.
      auditrows=[]
      for sym,(d,xs,tree,paths) in pathmaps.items():
        take=d.year.eq(2026).to_numpy();dy=d.loc[take].reset_index(drop=True)
        for path in paths:
          mask=condition_mask(xs,path['conditions'])[take]
          for direction,dname in [(2,'up'),(0,'down')]:
            desc=describe_rule(dy,mask,direction);inf=cluster_test(dy,mask,direction,1999,7);diag=cluster_test(dy,mask,direction,1999,28)
            auditrows.append({'symbol':sym,'leaf':path['leaf'],'direction':dname,'year':2026,'rule':path['rule'],
                              **desc,**inf,**{'block28_'+k:v for k,v in diag.items()}})
      audit=pd.DataFrame(auditrows)
      audit['p_holm']=holm(audit.p.fillna(1))
      full=pd.concat([ev,audit],ignore_index=True)
      full['selected_2025']=False
      for s in selected:
        full.loc[(full.symbol==s['symbol'])&(full.leaf==s['leaf'])&(full.direction==s['direction']),'selected_2025']=True
      full['audit_pass']=(full.year==2026)&full.selected_2025&(full.nonoverlap_24h_events>=20)&(full.matched_coverage>=.70)&(full.positive_quarters>=2)&(full.matched_lift>0)&(full.p_holm<.05)
      full.to_csv(OUT/'all_rule_evidence.csv',index=False)

      accounts=[]
      for s in [x for x in selected if x['direction']=='up']:
        sym=s['symbol'];d,xs,tree,paths=pathmaps[sym]
        p=next(p for p in paths if p['leaf']==s['leaf'])
        allmask=condition_mask(xs,p['conditions'])
        for year in [2025,2026]:
          yearmask=d.year.eq(year).to_numpy();localmask=allmask[yearmask]
          dy=d.loc[yearmask].reset_index(drop=True)
          for cname,fee,slip in [('base',.001,.0005),('stress',.0015,.0015)]:
            m,tr=account(dy,frames,sym,localmask,year,fee,slip)
            accounts.append({'symbol':sym,'leaf':s['leaf'],'year':year,'cost':cname,**m})
            tr.to_csv(OUT/f'{sym}_leaf{s["leaf"]}_{year}_{cname}_trades.csv',index=False)
      acc=pd.DataFrame(accounts);acc.to_csv(OUT/'diagnostic_accounts.csv',index=False)

      surviving=[]
      for s in [x for x in selected if x['direction']=='up']:
        passed=bool(full[(full.symbol==s['symbol'])&(full.leaf==s['leaf'])&(full.direction=='up')&(full.year==2026)].audit_pass.any())
        aa=acc[(acc.symbol==s['symbol'])&(acc.leaf==s['leaf'])]
        profitability=all(float(aa[(aa.year==yr)&(aa.cost==cost)].iloc[0].compounded_return)>0 for yr in [2025,2026] for cost in ['base','stress']) if len(aa)==4 else False
        if passed and profitability:surviving.append(s)
      dump(selected,OUT/'selected_rules.json');dump(surviving,OUT/'research_candidates.json')
      state.update(completed=True,sequence_rows=len(seq),selected_2025=len(selected),
                   audit_tests=len(audit),audit_passes=int(full.audit_pass.sum()),research_candidates=len(surviving),
                   input_checks=checks,ended=datetime.now(timezone.utc).isoformat())
      dump(state,OUT/'execution_status.json')
      print(json.dumps(state,indent=2,default=str))
    except Exception as e:
      state.update(error=type(e).__name__+': '+str(e));dump(state,OUT/'execution_status.json');traceback.print_exc();raise

if __name__=='__main__':main()
