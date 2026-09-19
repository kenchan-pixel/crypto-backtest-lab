"""Frozen macro-surprise incremental-information experiment."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,traceback,os
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from threadpoolctl import threadpool_limits

from multifactor.data import load_inputs,build_features,labels,period_mask,SEED
from multifactor.study import boost,score,dump,clean,diagnostic_account
from multifactor.evidence import paths_from_tree,condition_mask,strata_for,describe,cluster_inference,holm
from derivatives.features import prepare_sources,build_derivatives
from derivatives.study import loss_each,paired_loss_test
from .features import load_events,build_macro,columns_for

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'macro_outputs'
EVENTS=ROOT/'longbridge_macro/normalized/macro_events.json'

def select_rules(ev,sym):
    result=[]
    for direction in ['up','down']:
        cand=ev[(ev.year==2025)&(ev.direction==direction)].copy()
        train_lift=ev[(ev.year==2024)&(ev.direction==direction)].set_index('leaf').matched_lift
        cand['train_lift']=cand.leaf.map(train_lift)
        cand['passes']=(cand.nonoverlap_24h_events>=30)&(cand.matched_lift>=.05)&(cand.matched_coverage>=.70)&(cand.positive_quarters>=3)&(cand.train_lift>0)
        if direction=='up': cand['passes'] &= cand.mean_long_net_return>0
        cand.to_csv(OUT/f'{sym}_{direction}_selection_gates.csv',index=False)
        good=cand[cand.passes].sort_values(['matched_lift','leaf'],ascending=[False,True])
        if len(good):
            row=good.iloc[0]
            result.append({'symbol':sym,'direction':direction,'leaf':int(row.leaf),
                           'validation_lift':float(row.matched_lift),'rule':row.rule})
    return result

def run():
    OUT.mkdir(exist_ok=True)
    state={'completed':False,'notebook_executed':False,'market_data_simulated':False,
           'live_approved':False,'genuine_unseen_holdout':False,
           'started':datetime.now(timezone.utc).isoformat(),
           'protocol_commit':'9fef5a1b856d80e21d93b1cc4cf5fe0a0ed68e3e',
           'macro_event_sha256':hashlib.sha256(EVENTS.read_bytes()).hexdigest(),
           'feature_count_baseline':92,'feature_count_macro_added':35}
    dump(state,OUT/'execution_status.json')
    try:
        frames,checks=load_inputs(ROOT/'inputs')
        dump(checks,OUT/'spot_input_checks.json')
        fomc=pd.read_csv(ROOT/'inputs/fomc_events.csv')
        macro_events=load_events(EVENTS)

        scores=[];increments=[];coverage=[];event_coverage=[];calibration=[]
        evidence=[];selected=[];accounts=[];cache=[]
        for sym,raw in frames.items():
            peer=frames['ETHUSDT' if sym=='BTCUSDT' else 'BTCUSDT']
            X,_=build_features(raw,peer,fomc)
            D,dfamilies=build_derivatives(X.index,prepare_sources(ROOT/'derivative_inputs',sym))
            M,mfamilies,cov=build_macro(X.index,macro_events,extra_lag_hours=0)
            Mstress,_,_=build_macro(X.index,macro_events,extra_lag_hours=1)
            cov.insert(0,'symbol',sym);event_coverage.append(cov)

            ret,y=labels(raw)
            available=D.notna().all(axis=1).to_numpy()
            per={yr:period_mask(X.index,ret,yr)&available for yr in [2024,2025,2026]}
            B=pd.concat([X,D],axis=1)
            A=pd.concat([B,M],axis=1)
            Astress=pd.concat([B,Mstress],axis=1)

            for yr,take in per.items():
                base=period_mask(X.index,ret,yr)
                coverage.append({'symbol':sym,'year':yr,'original_cases':int(base.sum()),
                                 'eligible_cases':int(take.sum()),'coverage':float(take.sum()/base.sum())})
                if take.sum()<1000: raise ValueError(f'Insufficient common rows {sym} {yr}')

            groups={
                'I':columns_for(mfamilies,'inflation'),
                'L':columns_for(mfamilies,'labour'),
                'P':columns_for(mfamilies,'policy'),
                'M':list(M.columns),
            }
            sets={'B':list(B.columns)}
            for name,cols in groups.items(): sets[name]=list(B.columns)+cols

            train=per[2024]
            prior=np.bincount(y[train].astype(int),minlength=3)/train.sum()
            pred={yr:{} for yr in [2025,2026]}
            for name,cols in sets.items():
                model=boost().fit(A.loc[train,cols],y[train].astype(int))
                for yr in [2025,2026]:
                    take=per[yr]
                    p=model.predict_proba(A.loc[take,cols]);pred[yr][name]=p
                    scores.append(dict(symbol=sym,model='boosted',features=name,year=yr,**score(y[take],p)))
            for yr in [2025,2026]:
                take=per[yr]
                scores.append(dict(symbol=sym,model='prior',features='prior',year=yr,
                                   **score(y[take],np.tile(prior,(take.sum(),1)))))
                for name,p in pred[yr].items():
                    for k,direction in enumerate(['down','neutral','up']):
                        bins=np.minimum((p[:,k]*10).astype(int),9)
                        for b in np.unique(bins):
                            z=bins==b
                            calibration.append({'symbol':sym,'year':yr,'features':name,'direction':direction,
                                                'bin':int(b),'cases':int(z.sum()),'predicted':float(p[z,k].mean()),
                                                'actual':float((y[take].to_numpy()[z]==k).mean())})

            for name in ['I','L','P','M']:
                take=per[2026]
                delta=loss_each(y[take],pred[2026]['B'])-loss_each(y[take],pred[2026][name])
                inf=paired_loss_test(X.index[take],delta,7,1999)
                diag=paired_loss_test(X.index[take],delta,28,1999)
                increments.append(dict(symbol=sym,features=name,**inf,
                                       **{'block28_'+k:v for k,v in diag.items()}))

            # Diagnostic models: fixed logistic baseline vs all-macro.
            for name in ['B','M']:
                cols=sets[name]
                model=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),
                                    LogisticRegression(C=.1,max_iter=2000,random_state=SEED))
                model.fit(A.loc[train,cols],y[train].astype(int))
                for yr in [2025,2026]:
                    take=per[yr]
                    scores.append(dict(symbol=sym,model='logistic',features=name,year=yr,
                                       **score(y[take],model.predict_proba(A.loc[take,cols]))))

            # Additional one-hour publication-lag stress, baseline vs all macro only.
            for name,frame,cols in [('B_lagstress',Astress,list(B.columns)),
                                    ('M_lagstress',Astress,list(B.columns)+list(Mstress.columns))]:
                model=boost().fit(frame.loc[train,cols],y[train].astype(int))
                for yr in [2025,2026]:
                    take=per[yr]
                    scores.append(dict(symbol=sym,model='lagstress_boosted',features=name,year=yr,
                                       **score(y[take],model.predict_proba(frame.loc[take,cols]))))

            # All-macro ablation diagnostics; no significance fishing.
            for dropped in ['inflation','labour','policy']:
                keep=[c for c in M.columns if mfamilies[c]!=dropped]
                cols=list(B.columns)+keep
                model=boost().fit(A.loc[train,cols],y[train].astype(int))
                for yr in [2025,2026]:
                    take=per[yr]
                    scores.append(dict(symbol=sym,model='ablation_boosted',
                                       features='M_without_'+dropped,year=yr,
                                       **score(y[take],model.predict_proba(A.loc[take,cols]))))

            # Interpretable tree trained on 2024 only.
            imputer=SimpleImputer(strategy='median').fit(A.loc[train])
            filled=pd.DataFrame(imputer.transform(A),index=A.index,columns=A.columns)
            tree=DecisionTreeClassifier(max_depth=4,max_leaf_nodes=10,min_samples_leaf=168,random_state=SEED)
            tree.fit(filled.loc[train],y[train].astype(int))
            paths=paths_from_tree(tree,list(A.columns))
            dump(paths,OUT/f'{sym}_tree_paths.json')
            cuts=np.quantile(X.loc[train,'volatility24'],[1/3,2/3])
            strata=strata_for(X,cuts)
            ev=[]
            for path in paths:
                mask=condition_mask(filled,path['conditions'])
                assert np.array_equal(mask,tree.apply(filled)==path['leaf'])
                for yr in [2024,2025]:
                    take=per[yr]
                    for direction,dname in [(0,'down'),(2,'up')]:
                        desc=describe(X.index[take],mask[take],y[take].to_numpy(),ret[take].to_numpy(),
                                      strata[take],direction)
                        ev.append(dict(symbol=sym,leaf=path['leaf'],direction=dname,year=yr,
                                       rule=path['rule'],**desc))
            selected+=select_rules(pd.DataFrame(ev),sym)
            evidence+=ev
            cache.append((sym,raw,X,ret,y,per,filled,paths,strata))
            print('MACRO MODEL + 2025 SELECTION',sym,flush=True)

        dump({'selection':selected,'uses_2026_rule_outcomes':False},OUT/'selection_before_rule_audit.json')

        # Only now inspect selected/all rule outcomes on 2026.
        for sym,raw,X,ret,y,per,filled,paths,strata in cache:
            take=per[2026];idx=X.index[take]
            for path in paths:
                mask=condition_mask(filled,path['conditions'])
                for direction,dname in [(0,'down'),(2,'up')]:
                    desc=describe(idx,mask[take],y[take].to_numpy(),ret[take].to_numpy(),strata[take],direction)
                    inf=cluster_inference(idx,mask[take],(y[take].to_numpy()==direction).astype(float),strata[take])
                    diag=cluster_inference(idx,mask[take],(y[take].to_numpy()==direction).astype(float),strata[take],block_days=28)
                    evidence.append(dict(symbol=sym,leaf=path['leaf'],direction=dname,year=2026,
                                         rule=path['rule'],**desc,**inf,
                                         **{'block28_'+k:v for k,v in diag.items()}))
            for chosen in [s for s in selected if s['symbol']==sym and s['direction']=='up']:
                path=next(p for p in paths if p['leaf']==chosen['leaf'])
                mask=condition_mask(filled,path['conditions'])
                for yr in [2025,2026]:
                    for cost,fee,slip in [('base',.001,.0005),('stress',.0015,.0015)]:
                        m,tr=diagnostic_account(raw,mask&per[yr],fee,slip)
                        accounts.append(dict(symbol=sym,leaf=chosen['leaf'],year=yr,cost=cost,**m))
                        tr.to_csv(OUT/f'{sym}_leaf{chosen["leaf"]}_{yr}_{cost}_trades.csv',index=False)

        inc=pd.DataFrame(increments);inc['p_holm8']=holm(inc.p);inc.to_csv(OUT/'incremental_loss_tests.csv',index=False)
        ev=pd.DataFrame(evidence)
        audit=ev.year==2026
        ev.loc[audit,'p_holm']=holm(ev.loc[audit,'p'].fillna(1))
        ev['selected_2025']=False
        for s in selected:
            ev.loc[(ev.symbol==s['symbol'])&(ev.leaf==s['leaf'])&(ev.direction==s['direction']),'selected_2025']=True
        ev['audit_pass']=audit&ev.selected_2025&(ev.nonoverlap_24h_events>=30)&(ev.matched_coverage>=.70)&(ev.positive_quarters>=2)&(ev.matched_lift>0)&(ev.p_holm<.05)
        ev.to_csv(OUT/'all_rule_evidence.csv',index=False)
        pd.DataFrame(scores).to_csv(OUT/'model_scores.csv',index=False)
        pd.concat(event_coverage,ignore_index=True).drop_duplicates().to_csv(OUT/'event_coverage.csv',index=False)
        pd.DataFrame(coverage).to_csv(OUT/'common_sample_coverage.csv',index=False)
        pd.DataFrame(calibration).to_csv(OUT/'calibration.csv',index=False)
        pd.DataFrame(accounts).to_csv(OUT/'diagnostic_accounts.csv',index=False)
        dump(selected,OUT/'selected_rules.json')

        state.update(research_calculated=True,selected_2025=len(selected),
                     patterns_passing_2026=int(ev.audit_pass.sum()),
                     macro_increments_corrected_significant=int(((inc.p_holm8<.05)&(inc.mean_loss_reduction>0)).sum()),
                     actual_rule_tests_2026=int(audit.sum()))
        dump(state,OUT/'execution_status.json')
        notebook()
        state.update(completed=True,notebook_executed=True,
                     notebook_sha256=hashlib.sha256((OUT/'Research_Executed.ipynb').read_bytes()).hexdigest(),
                     ended=datetime.now(timezone.utc).isoformat())
        dump(state,OUT/'execution_status.json')
        print(json.dumps(clean(state),ensure_ascii=False),flush=True)
    except Exception as exc:
        state.update(completed=False,error=type(exc).__name__+': '+str(exc))
        dump(state,OUT/'execution_status.json');traceback.print_exc();raise

def notebook():
    import nbformat
    from nbclient import NotebookClient
    n=nbformat.v4.new_notebook(cells=[
      nbformat.v4.new_markdown_cell('# Longbridge macro-surprise incremental research\nRetrospective, reused history; not forward evidence or live approval.'),
      nbformat.v4.new_code_cell("from pathlib import Path\nimport pandas as pd, json\nfrom IPython.display import display\np=Path('macro_outputs')\ndisplay(pd.read_csv(p/'event_coverage.csv'))"),
      nbformat.v4.new_code_cell("display(pd.read_csv(p/'model_scores.csv'))\ndisplay(pd.read_csv(p/'incremental_loss_tests.csv'))"),
      nbformat.v4.new_code_cell("e=pd.read_csv(p/'all_rule_evidence.csv')\ndisplay(e[e.selected_2025])\nprint('Audit passes:', int(e.audit_pass.sum()))"),
      nbformat.v4.new_code_cell("a=pd.read_csv(p/'diagnostic_accounts.csv')\ndisplay(a)\nprint(json.loads((p/'execution_status.json').read_text()))")
    ])
    NotebookClient(n,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(ROOT)}}).execute()
    nbformat.write(n,OUT/'Research_Executed.ipynb')

if __name__=='__main__':
    with threadpool_limits(limits=1): run()
