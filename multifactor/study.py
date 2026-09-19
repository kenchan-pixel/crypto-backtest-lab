"""Frozen 2024-trained multivariate discovery, 2025 screening, 2026 audit.
Run from package root: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m multifactor.study
"""
from __future__ import annotations
import os, json, hashlib, platform, traceback, warnings
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import log_loss,roc_auc_score,accuracy_score
from threadpoolctl import threadpool_limits
from .data import load_inputs,make_event_file,build_features,labels,period_mask,TZ,START,END,SEED
from .evidence import paths_from_tree,condition_mask,strata_for,describe,cluster_inference,holm

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'outputs';INP=ROOT/'inputs'

def clean(v):
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    if isinstance(v,np.ndarray): return clean(v.tolist())
    if isinstance(v,(float,np.floating)): return float(v) if np.isfinite(v) else None
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,np.bool_): return bool(v)
    return v

def dump(obj,path):
    path.write_text(json.dumps(clean(obj),ensure_ascii=False,indent=2,allow_nan=False))

def boost():
    return make_pipeline(SimpleImputer(strategy='median'),HistGradientBoostingClassifier(
      max_iter=100,learning_rate=.05,max_leaf_nodes=7,max_depth=3,min_samples_leaf=168,
      l2_regularization=10,early_stopping=False,random_state=SEED))

def score(y,p):
    y=np.asarray(y,int);p=np.asarray(p,float);p=np.clip(p,1e-12,1);p/=p.sum(axis=1,keepdims=True)
    hot=np.eye(3)[y];chosen=p.argmax(axis=1);confidence=p.max(axis=1)
    bins=np.minimum((confidence*10).astype(int),9);ece=0.
    for b in range(10):
        take=bins==b
        if take.any():ece+=take.mean()*abs((chosen[take]==y[take]).mean()-confidence[take].mean())
    ans={'hours':len(y),'log_loss':log_loss(y,p,labels=[0,1,2]),
      'multiclass_brier':float(np.mean(np.sum((p-hot)**2,axis=1))),
      'accuracy':accuracy_score(y,chosen),'calibration_ece_10bins':float(ece)}
    for d,n in [(0,'down'),(2,'up')]:
        binary=y==d;ans[n+'_auc']=roc_auc_score(binary,p[:,d]) if binary.any() and (~binary).any() else None
    return clean(ans)

def diagnostic_account(raw,mask,fee,slip):
    """Only called for an UP rule chosen using 2025, never for a down/short rule."""
    candidates=raw.index[mask];last_exit=None;cash=1.;trades=[]
    for t in candidates:
        en=t+pd.Timedelta(minutes=1);ex=en+pd.Timedelta(hours=24)
        if last_exit is not None and en<=last_exit:continue
        if t+pd.Timedelta(hours=24) not in raw.index:continue
        px=raw.loc[t,'execution_open'];exitpx=raw.loc[t+pd.Timedelta(hours=24),'execution_open']
        if not np.isfinite(px) or not np.isfinite(exitpx):continue
        before=cash;units=cash/(px*(1+slip)*(1+fee));cash=units*exitpx*(1-slip)*(1-fee)
        path=raw.loc[(raw.index>en)&(raw.index<ex),'close'].to_numpy()
        # Only hourly-observable values plus actual entry/exit prices, no invented ticks.
        nav=np.r_[before,units*px,units*path,units*exitpx,cash]
        trades.append({'signal_hkt':str(t),'entry_hkt':str(en),'exit_hkt':str(ex),
          'entry_open':float(px),'exit_open':float(exitpx),'net_return':cash/before-1,
          'cash_before':before,'cash_after':cash,'pnl':cash-before,'nav_path':nav.tolist()})
        last_exit=ex
    vals=np.r_[1.,*[np.array(x['nav_path']) for x in trades]] if trades else np.array([1.])
    dd=float(np.min(vals/np.maximum.accumulate(vals)-1))
    tr=pd.DataFrame([{k:v for k,v in x.items() if k!='nav_path'} for x in trades])
    if not len(tr):return {'trades':0,'net_return':0.,'max_drawdown_hourly_observable':0.},tr
    loss=-tr.loc[tr.pnl<0,'pnl'].sum();gain=tr.loc[tr.pnl>0,'pnl'].sum()
    no_best=float((1+tr.net_return.drop(tr.net_return.idxmax())).prod()-1)
    return {'trades':len(tr),'net_return':cash-1,'win_rate':float((tr.net_return>0).mean()),
      'mean_net_return':float(tr.net_return.mean()),'median_net_return':float(tr.net_return.median()),
      'profit_factor_cash':float(gain/loss) if loss else None,'best_trade_removed_return':no_best,
      'max_drawdown_hourly_observable':dd},tr


def run():
    OUT.mkdir(exist_ok=True)
    status={'started_at':datetime.now(timezone.utc).isoformat(),'state':'RUNNING','completed':False,
      'market_data_simulated':False,'genuinely_blind_history':False,'live_approved':False,
      'protocol_commit':'92cd2856d1db278961b1000bcd23f21982c35655',
      'source_actions_run':35336304622,'execution_location':'ChatGPT computational container',
      'broad_news_corpus_included':False,'fomc_original_statements_included':True}
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'multifactor').glob('*.py')}
    dump(sources,OUT/'code_hashes_before_fit.json');dump(status,OUT/'execution_status.json')
    try:
        events=make_event_file(INP/'fomc_events.csv')
        frames,checks=load_inputs(INP);dump(checks,OUT/'input_checks.json')
        dump({'source_artifact_sha256':'9a93581498e47a09c592db20f1395e85a447dcba198d6e2c98f2417ef61500dd',
          'source_run':35336304622,'binance_archives_redownloaded_this_turn':False,
          'fomc_official_records':len(events),'in_window_fomc_records':int((events.role=='research').sum()),
          'broad_crypto_headlines_status':'NOT_OBTAINED_COVERAGE_UNVERIFIED',
          'not_available_as_features':['versioned crypto headlines and sentiment','ETF point-in-time flows',
             'macro surprises vs contemporaneous consensus','historical full order book','derivatives open interest/funding'],
          'news_readout_limit':'FOMC alone is not a broad news test; no-news missingness not zero-coded'},OUT/'coverage.json')
        all_scores=[];all_evidence=[];all_paths={};cached={};selection=[];rolling_scores=[];ablations=[];calibration=[]
        for sym,raw in frames.items():
            peer=frames['ETHUSDT' if sym=='BTCUSDT' else 'BTCUSDT']
            X,families=build_features(raw,peer,events);ret,y=labels(raw)
            per={str(yr):period_mask(X.index,ret,yr) for yr in [2024,2025,2026]}
            train=per['2024'];Xi=X[train];yi=y[train].astype(int)
            if Xi.isna().any().any():print('TRAIN missing cells',sym,int(Xi.isna().sum().sum()),flush=True)
            prior=np.bincount(yi,minlength=3)/len(yi)
            med=SimpleImputer(strategy='median').fit(Xi)
            filled=pd.DataFrame(med.transform(X),columns=X.columns,index=X.index)
            tree=DecisionTreeClassifier(max_depth=4,max_leaf_nodes=10,min_samples_leaf=168,random_state=SEED)
            tree.fit(filled[train],yi)
            paths=paths_from_tree(tree,list(X.columns));all_paths[sym]=paths
            dump(paths,OUT/f'{sym}_tree_paths.json')
            dictionary=[{'feature':c,'family':families[c],'available_at':'completed_hour_or_earlier',
                         'training_imputation_median':float(med.statistics_[i])} for i,c in enumerate(X)]
            pd.DataFrame(dictionary).to_csv(OUT/f'{sym}_feature_dictionary.csv',index=False)
            cuts=np.quantile(Xi.volatility24,[1/3,2/3]);strata=strata_for(X,cuts)
            dump({'volatility_tercile_cuts_2024_only':cuts,'features':len(X.columns),
                 'train_hours':int(train.sum()),'screen_hours':int(per['2025'].sum()),
                 'audit_hours':int(per['2026'].sum()),'train_last':str(X.index[train][-1]),
                 'screen_last':str(X.index[per['2025']][-1]),'audit_last':str(X.index[per['2026']][-1])},OUT/f'{sym}_split_checks.json')
            # Extract and screen rules before examining their 2026 outcomes.
            evidence=[]
            for path in paths:
                mask=condition_mask(filled,path['conditions'])
                assert np.array_equal(mask,tree.apply(filled)==path['leaf'])
                for year in ['2024','2025']:
                    take=per[year];idx=X.index[take]
                    for direction,dname in [(0,'down'),(2,'up')]:
                        row=describe(idx,mask[take],y[take].to_numpy(),ret[take].to_numpy(),strata[take],direction)
                        evidence.append(dict(symbol=sym,leaf=path['leaf'],direction=dname,year=year,rule=path['rule'],**row))
            ev=pd.DataFrame(evidence)
            for dname in ['up','down']:
                candidates=ev[(ev.year=='2025')&(ev.direction==dname)].copy()
                trainlifts=ev[(ev.year=='2024')&(ev.direction==dname)].set_index('leaf').matched_lift
                candidates['training_lift']=candidates.leaf.map(trainlifts)
                candidates['passed_validation']=(candidates.nonoverlap_24h_events>=30)&(candidates.matched_lift>=.05)&(
                  candidates.matched_coverage>=.7)&(candidates.positive_quarters>=3)&(candidates.training_lift>0)
                if dname=='up':candidates['passed_validation'] &= candidates.mean_long_net_return>0
                candidates.to_csv(OUT/f'{sym}_{dname}_validation_gates.csv',index=False)
                good=candidates[candidates.passed_validation].sort_values('matched_lift',ascending=False)
                if len(good):
                    row=good.iloc[0];selection.append({'symbol':sym,'direction':dname,'leaf':int(row.leaf),
                    'validation_lift':float(row.matched_lift),'rule':row.rule,'selected_from':'2025 only'})
            cached[sym]={'X':X,'y':y,'ret':ret,'per':per,'filled':filled,'tree':tree,'prior':prior,
               'families':families,'strata':strata,'paths':paths}
            all_evidence+=evidence
            print('TRAIN/SREEN FINISHED',sym,'features',len(X.columns),'leaves',len(paths),flush=True)
        # Explicit selection snapshot exists before any per-rule 2026 outcome is evaluated.
        dump({'selection':selection,'created_before_rule_audit':True,'selection_uses_2026_outcomes':False},OUT/'selection_pre_audit.json')
        for sym,raw in frames.items():
            c=cached[sym];X,y,ret=c['X'],c['y'],c['ret'];per=c['per'];train=per['2024']
            models={
              'logistic':make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),
                 LogisticRegression(C=.1,max_iter=2000,random_state=SEED)),
              'boosted':boost()}
            models={name:model.fit(X[train],y[train].astype(int)) for name,model in models.items()}
            for year in ['2025','2026']:
                take=per[year];pdict={'unconditional':np.tile(c['prior'],(int(take.sum()),1)),
                  'tree':c['tree'].predict_proba(c['filled'][take]),
                  **{name:model.predict_proba(X[take]) for name,model in models.items()}}
                preds=pd.DataFrame({'true_class':y[take].astype(int),'return_24h':ret[take]},index=X.index[take])
                for name,p in pdict.items():
                    all_scores.append(dict(symbol=sym,model=name,period=year,**score(y[take],p)))
                    for d,label in enumerate(['down','neutral','up']):preds[f'{name}_{label}']=p[:,d]
                    for direction in [0,2]:
                        bins=np.minimum((p[:,direction]*10).astype(int),9)
                        for b in sorted(set(bins)):
                            ix=bins==b;calibration.append({'symbol':sym,'model':name,'period':year,
                             'direction':'up' if direction==2 else 'down','bin':int(b),'hours':int(ix.sum()),
                             'mean_predicted_probability':float(p[ix,direction].mean()),
                             'actual_probability':float((y[take].to_numpy()[ix]==direction).mean())})
                preds.to_csv(OUT/f'{sym}_{year}_predictions.csv.gz',compression='gzip',index_label='decision_hkt')
            # Remove each information family, retrain with identical fixed settings.
            for family in sorted(set(c['families'].values())):
                columns=[col for col in X if c['families'][col]!=family]
                model=boost().fit(X.loc[train,columns],y[train].astype(int))
                for year in ['2025','2026']:
                    take=per[year];s=score(y[take],model.predict_proba(X.loc[take,columns]))
                    ablations.append(dict(symbol=sym,removed_family=family,period=year,**s))
            for path in c['paths']:
                mask=condition_mask(c['filled'],path['conditions']);take=per['2026'];idx=X.index[take]
                for direction,dname in [(0,'down'),(2,'up')]:
                    row=describe(idx,mask[take],y[take].to_numpy(),ret[take].to_numpy(),c['strata'][take],direction)
                    inf=cluster_inference(idx,mask[take],(y[take].to_numpy()==direction).astype(float),c['strata'][take])
                    longinf=cluster_inference(idx,mask[take],(y[take].to_numpy()==direction).astype(float),c['strata'][take],block_days=28)
                    row.update(inf);row.update({f'block28_{k}':v for k,v in longinf.items()})
                    all_evidence.append(dict(symbol=sym,leaf=path['leaf'],direction=dname,year='2026',rule=path['rule'],**row))
            # Fixed prior-12-month fits; a purge protects each next-quarter forecast.
            for qstart in pd.date_range('2025-01-01','2026-07-01',freq='QS',tz=TZ):
                qend=min(qstart+pd.DateOffset(months=3),END)
                training=(X.index>=qstart-pd.DateOffset(months=12))&(X.index<qstart-pd.Timedelta(hours=25))&ret.notna()
                testing=(X.index>=qstart)&(X.index<qend)&ret.notna()
                model=boost().fit(X[training],y[training].astype(int));p=model.predict_proba(X[testing])
                prior=np.bincount(y[training].astype(int),minlength=3)/training.sum()
                for name,prob in [('rolling_boosted',p),('rolling_prior',np.tile(prior,(int(testing.sum()),1)))]:
                    rolling_scores.append(dict(symbol=sym,model=name,period=str(qstart.tz_localize(None).to_period('Q')),
                       train_first=str(X.index[training][0]),train_last=str(X.index[training][-1]),**score(y[testing],prob)))
            print('AUDIT/MODELS FINISHED',sym,flush=True)
        scores=pd.DataFrame(all_scores);ev=pd.DataFrame(all_evidence)
        audit=ev.year=='2026';ev.loc[audit,'p_holm']=holm(ev.loc[audit,'p'].fillna(1))
        ev['validation_selected']=False
        for s in selection:ev.loc[(ev.symbol==s['symbol'])&(ev.direction==s['direction'])&(ev.leaf==s['leaf']),'validation_selected']=True
        ev['audit_gate_passed']=audit&(ev.nonoverlap_24h_events>=30)&(ev.matched_coverage>=.7)&(ev.positive_quarters>=2)&(ev.p_holm<.05)&(ev.matched_lift>0)&ev.validation_selected
        ev.to_csv(OUT/'all_rule_evidence.csv',index=False)
        scores.to_csv(OUT/'model_scores.csv',index=False)
        pd.DataFrame(rolling_scores).to_csv(OUT/'rolling_quarter_scores.csv',index=False)
        pd.DataFrame(ablations).to_csv(OUT/'feature_family_ablation.csv',index=False)
        pd.DataFrame(calibration).to_csv(OUT/'calibration.csv',index=False)
        # Secondary horizon/label diagnostics and one-antecedent removal, no selection from these.
        extra=[];drop_conditions=[];examples=[];news_rows=[];account_rows=[]
        for sym,raw in frames.items():
            c=cached[sym]
            for path in c['paths']:
                mask=condition_mask(c['filled'],path['conditions'])
                for horizon,threshold in [(6,.01),(24,.005),(24,.02)]:
                    r,y=labels(raw,horizon,threshold)
                    take=period_mask(raw.index,r,2026)
                    for direction,dname in [(0,'down'),(2,'up')]:
                        d=describe(raw.index[take],mask[take],y[take].to_numpy(),r[take].to_numpy(),c['strata'][take],direction)
                        extra.append(dict(symbol=sym,leaf=path['leaf'],direction=dname,horizon=horizon,threshold=threshold,**d))
                for j,condition in enumerate(path['conditions']):
                    reduced=condition_mask(c['filled'],path['conditions'][:j]+path['conditions'][j+1:])
                    for year in ['2025','2026']:
                        take=c['per'][year]
                        for direction,dname in [(0,'down'),(2,'up')]:
                            d=describe(raw.index[take],reduced[take],c['y'][take].to_numpy(),c['ret'][take].to_numpy(),c['strata'][take],direction)
                            drop_conditions.append(dict(symbol=sym,leaf=path['leaf'],removed_condition=json.dumps(condition),year=year,direction=dname,**d))
                # ALL 2026 examples; selection status explicit, not handpicked anecdotes.
                take=c['per']['2026']&mask
                for t in raw.index[take]:
                    examples.append({'symbol':sym,'leaf':path['leaf'],'decision_hkt':str(t),
                     'actual_class':int(c['y'].loc[t]),'return_24h':float(c['ret'].loc[t])})
            # Descriptive event-timing rate observations; not conditioning on future headlines.
            for _,event in events[events.role=='research'].iterrows():
                start=pd.Timestamp(event.usable_from_utc).tz_convert(TZ).ceil('h')
                if start not in c['ret'].index:continue
                news_rows.append({'symbol':sym,'event_id':event.event_id,'first_hourly_decision':str(start),
                  'rate_change':event.change_percentage_points,'actual_next_24h_return':c['ret'].loc[start],
                  'actual_class':c['y'].loc[start],'source_url':event.source_url})
            for selected in [s for s in selection if s['symbol']==sym and s['direction']=='up']:
                path=next(p for p in c['paths'] if p['leaf']==selected['leaf'])
                mask=condition_mask(c['filled'],path['conditions'])
                for year in ['2025','2026']:
                    for name,fee,slip in [('base',.001,.0005),('stress',.0015,.0015)]:
                        m,tr=diagnostic_account(raw,mask&c['per'][year],fee,slip)
                        account_rows.append(dict(symbol=sym,leaf=path['leaf'],year=year,cost=name,**m))
                        tr.to_csv(OUT/f'{sym}_leaf{path["leaf"]}_{year}_{name}_diagnostic_trades.csv',index=False)
        pd.DataFrame(extra).to_csv(OUT/'secondary_label_checks.csv',index=False)
        pd.DataFrame(drop_conditions).to_csv(OUT/'drop_one_condition.csv',index=False)
        pd.DataFrame(examples).to_csv(OUT/'all_audit_examples.csv.gz',compression='gzip',index=False)
        pd.DataFrame(news_rows).to_csv(OUT/'fomc_event_observations.csv',index=False)
        pd.DataFrame(account_rows).to_csv(OUT/'selected_up_diagnostic_accounts.csv',index=False)
        dump(selection,OUT/'selected_rules.json')
        summary={'features_per_coin':{s:len(c['X'].columns) for s,c in cached.items()},
          'rules_per_coin':{s:len(c['paths']) for s,c in cached.items()},'audit_hypothesis_family':int(audit.sum()),
          'selected_on_2025':selection,'selected_patterns_passing_2026_gate':ev[ev.audit_gate_passed].to_dict('records')}
        dump(summary,OUT/'summary.json')
        status.update(state='PATTERN_RESEARCH_EXECUTED',completed=True,selected_patterns=len(selection),
          patterns_passing_audit=int(ev.audit_gate_passed.sum()),ended_at=datetime.now(timezone.utc).isoformat(),
          notebook_executed=False)
        dump(status,OUT/'execution_status.json')
        print('RESULT_SUMMARY',json.dumps(clean(summary),ensure_ascii=False),flush=True)
    except Exception as exc:
        status.update(state='FAILED',error=str(exc));dump(status,OUT/'execution_status.json');traceback.print_exc();raise

if __name__=='__main__':
    with threadpool_limits(limits=1):run()
