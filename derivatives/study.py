"""Fixed derivatives-vs-original-feature experiment. Run python -m derivatives.study."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,platform,traceback
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
from .features import prepare_sources,build_derivatives
ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'derivative_outputs';INPUT=ROOT/'derivative_inputs'

def loss_each(y,p):
    return -np.log(np.clip(p[np.arange(len(y)),np.asarray(y,int)],1e-12,1.))

def paired_loss_test(index, delta, days=7, reps=1999):
    x=np.asarray(delta,float);mu=float(x.mean())
    codes=np.asarray((index.asi8-index.asi8[0])//pd.Timedelta(days=days).value,int)
    sums=np.bincount(codes,weights=x);counts=np.bincount(codes)
    valid=counts>0;sums,counts=sums[valid],counts[valid];n=len(sums)
    if n<10:return {'mean_loss_reduction':mu,'ci_low':None,'ci_high':None,'p':1.,'limited':True,'clusters':n}
    rng=np.random.default_rng(SEED);w=rng.multinomial(n,np.ones(n)/n,size=reps)
    boot=(w@sums)/(w@counts);lo,hi=np.quantile(boot,[.025,.975])
    return {'mean_loss_reduction':mu,'ci_low':float(lo),'ci_high':float(hi),
      'p':float((1+np.sum(boot-mu>=mu))/(reps+1)),'limited':False,'clusters':n}

def select_rules(ev,sym):
    result=[]
    for direction in ['up','down']:
        cand=ev[(ev.year==2025)&(ev.direction==direction)].copy()
        tl=ev[(ev.year==2024)&(ev.direction==direction)].set_index('leaf').matched_lift
        cand['train_lift']=cand.leaf.map(tl)
        cand['passes']=(cand.nonoverlap_24h_events>=30)&(cand.matched_lift>=.05)&(cand.matched_coverage>=.7)&(cand.positive_quarters>=3)&(cand.train_lift>0)
        if direction=='up':cand['passes'] &= cand.mean_long_net_return>0
        cand.to_csv(OUT/f'{sym}_{direction}_selection_gates.csv',index=False)
        good=cand[cand.passes].sort_values(['matched_lift','leaf'],ascending=[False,True])
        if len(good):
            r=good.iloc[0];result.append({'symbol':sym,'direction':direction,'leaf':int(r.leaf),
                'validation_lift':float(r.matched_lift),'rule':r.rule})
    return result

def run():
    OUT.mkdir(exist_ok=True)
    state={'completed':False,'notebook_executed':False,'market_data_simulated':False,
      'live_approved':False,'genuine_unseen_holdout':False,'started':datetime.now(timezone.utc).isoformat(),
      'collector_run':35414544625,'protocol_commit':'44b6e3f0c6d3dac2219b0a94fd46b34fbab69e9a',
      'execution_location':'ChatGPT computation container','archive_first_publication_verified':False,
      'latency_assumption_hours':1,'latency_stress_hours':6}
    dump(state,OUT/'execution_status.json')
    dump({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['multifactor','derivatives'] for p in (ROOT/folder).glob('*.py')},OUT/'code_before_fit.json')
    try:
        man=json.loads((INPUT/'MANIFEST.json').read_text())
        # Logs may have been open when the collector wrote its input manifest.
        verified=[]
        for name,digest in man['files'].items():
            if name.endswith('.log'):continue
            p=INPUT/name
            if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('Collector hash mismatch '+name)
            verified.append(name)
        supp=json.loads((INPUT/'connector_tail_provenance.json').read_text())
        for name,item in supp['files'].items():
            if hashlib.sha256((INPUT/name).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Connector-tail hash mismatch')
        dump({'collector_verified_files':verified,'connector_tail':supp},OUT/'verified_input_manifest.json')
        frames,checks=load_inputs(ROOT/'inputs');dump(checks,OUT/'spot_input_checks.json')
        events=pd.read_csv(ROOT/'inputs/fomc_events.csv')
        cache={};scores=[];evidence=[];selected=[];coverage=[];increment=[];accounts=[];calibration=[]
        for sym,raw in frames.items():
            X,_=build_features(raw,frames['ETHUSDT' if sym=='BTCUSDT' else 'BTCUSDT'],events)
            sources=prepare_sources(INPUT,sym);D,families=build_derivatives(X.index,sources)
            D6,_=build_derivatives(X.index,sources,6)
            ret,y=labels(raw);available=D.notna().all(axis=1).to_numpy()
            per={yr:period_mask(X.index,ret,yr)&available for yr in [2024,2025,2026]}
            A=pd.concat([X,D],axis=1)
            for yr in per:
                orig=period_mask(X.index,ret,yr)
                ix=X.index[per[yr]]
                coverage.append({'symbol':sym,'year':yr,'original_cases':int(orig.sum()),'common_cases':int(per[yr].sum()),
                  'coverage':float(per[yr].sum()/orig.sum()),'first':str(ix.min()),'last':str(ix.max())})
                if per[yr].sum()<1000:raise ValueError('Insufficient derivative coverage to fit/evaluate '+sym+str(yr))
            for family in ['funding','oi','positioning']:
                cols=[c for c in D if families[c]==family]
                print('AVAILABLE',sym,family,D.loc[period_mask(X.index,ret,2026),cols].notna().all(axis=1).mean(),flush=True)
            dictionary=pd.DataFrame([{'feature':c,'family':families[c],'lag_hours':1} for c in D]);dictionary.to_csv(OUT/f'{sym}_derivative_dictionary.csv',index=False)
            # Context-only all-date baseline is separate from the paired common-date comparisons.
            original_train=period_mask(X.index,ret,2024)
            original_model=boost().fit(X[original_train],y[original_train].astype(int))
            for yr in [2025,2026]:
                take=period_mask(X.index,ret,yr)
                scores.append(dict(symbol=sym,model='all_date_boosted',features='B',year=yr,**score(y[take],original_model.predict_proba(X[take]))))
            # All primary models use the exact same eligible training/evaluation dates.
            sets={'B':list(X),'F':list(X)+[c for c in D if families[c]=='funding'],
                'O':list(X)+[c for c in D if families[c]=='oi'],
                'P':list(X)+[c for c in D if families[c]=='positioning'],'A':list(A)}
            train=per[2024];prior=np.bincount(y[train].astype(int),minlength=3)/train.sum()
            pred={yr:{} for yr in [2025,2026]};fitted={}
            for name,cols in sets.items():
                model=boost().fit(A.loc[train,cols],y[train].astype(int));fitted[name]=model
                for yr in [2025,2026]:
                    take=per[yr];p=model.predict_proba(A.loc[take,cols]);pred[yr][name]=p
                    scores.append(dict(symbol=sym,model='boosted',features=name,year=yr,**score(y[take],p)))
            for name in ['B','A']:
                cols=sets[name]
                logit=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=.1,max_iter=2000,random_state=SEED)).fit(A.loc[train,cols],y[train].astype(int))
                for yr in [2025,2026]:scores.append(dict(symbol=sym,model='logistic',features=name,year=yr,**score(y[per[yr]],logit.predict_proba(A.loc[per[yr],cols]))))
            med=SimpleImputer(strategy='median').fit(A[train]);filled=pd.DataFrame(med.transform(A),index=A.index,columns=A.columns)
            tree=DecisionTreeClassifier(max_depth=4,max_leaf_nodes=10,min_samples_leaf=168,random_state=SEED).fit(filled[train],y[train].astype(int))
            treeb=DecisionTreeClassifier(max_depth=4,max_leaf_nodes=10,min_samples_leaf=168,random_state=SEED).fit(filled.loc[train,X.columns],y[train].astype(int))
            paths=paths_from_tree(tree,list(A));dump(paths,OUT/f'{sym}_tree_paths.json')
            cuts=np.quantile(X.loc[train,'volatility24'],[1/3,2/3]);strata=strata_for(X,cuts)
            for yr in [2025,2026]:
                take=per[yr]
                scores.append(dict(symbol=sym,model='prior',features='B',year=yr,**score(y[take],np.tile(prior,(take.sum(),1)))))
                for nm,tr,col in [('A',tree,list(A)),('B',treeb,list(X))]:
                    scores.append(dict(symbol=sym,model='tree',features=nm,year=yr,**score(y[take],tr.predict_proba(filled.loc[take,col]))))
                out=pd.DataFrame({'label':y[take].astype(int),'return_24h':ret[take]},index=X.index[take])
                for name,p in pred[yr].items():
                    for k,cl in enumerate(['down','neutral','up']):
                        out[f'{name}_{cl}']=p[:,k]
                        bins=np.minimum((p[:,k]*10).astype(int),9)
                        for b in np.unique(bins):
                            z=bins==b;calibration.append(dict(symbol=sym,year=yr,features=name,direction=cl,bin=int(b),cases=int(z.sum()),predicted=float(p[z,k].mean()),actual=float((y[take].to_numpy()[z]==k).mean())))
                out.to_csv(OUT/f'{sym}_{yr}_paired_predictions.csv.gz',compression={'method':'gzip','mtime':0},index_label='decision_hkt')
            for name in ['F','O','P','A']:
                take=per[2026];delta=loss_each(y[take],pred[2026]['B'])-loss_each(y[take],pred[2026][name])
                inf=paired_loss_test(X.index[take],delta);diag=paired_loss_test(X.index[take],delta,28)
                increment.append(dict(symbol=sym,features=name,**inf,**{'block28_'+k:v for k,v in diag.items()}))
            # Late availability stress uses a common subset and retrains every model on that subset.
            common6=available&D6.notna().all(axis=1).to_numpy();A6=pd.concat([X,D6],axis=1)
            train6=period_mask(X.index,ret,2024)&common6
            for name in ['B','A']:
                model=boost().fit(A6.loc[train6,sets[name]],y[train6].astype(int))
                for yr in [2025,2026]:
                    take=period_mask(X.index,ret,yr)&common6
                    scores.append(dict(symbol=sym,model='lag6_boosted',features=name,year=yr,**score(y[take],model.predict_proba(A6.loc[take,sets[name]]))))
            ev=[]
            for path in paths:
                mask=condition_mask(filled,path['conditions'])
                assert np.array_equal(mask,tree.apply(filled)==path['leaf'])
                for yr in [2024,2025]:
                    take=per[yr]
                    for direction,dname in [(0,'down'),(2,'up')]:
                        desc=describe(X.index[take],mask[take],y[take].to_numpy(),ret[take].to_numpy(),strata[take],direction)
                        ev.append(dict(symbol=sym,leaf=path['leaf'],direction=dname,year=yr,rule=path['rule'],**desc))
            selected+=select_rules(pd.DataFrame(ev),sym);evidence+=ev
            cache[sym]=dict(X=X,A=A,D=D,raw=raw,ret=ret,y=y,per=per,filled=filled,paths=paths,strata=strata)
            print('MODELS AND 2025 RULE SELECTION COMPLETED',sym,flush=True)
        dump({'selection':selected,'uses_2026_rule_outcomes':False},OUT/'selection_before_rule_audit.json')
        for sym,c in cache.items():
            for path in c['paths']:
                mask=condition_mask(c['filled'],path['conditions']);take=c['per'][2026];idx=c['X'].index[take]
                for direction,dname in [(0,'down'),(2,'up')]:
                    desc=describe(idx,mask[take],c['y'][take].to_numpy(),c['ret'][take].to_numpy(),c['strata'][take],direction)
                    inf=cluster_inference(idx,mask[take],(c['y'][take].to_numpy()==direction).astype(float),c['strata'][take])
                    di=cluster_inference(idx,mask[take],(c['y'][take].to_numpy()==direction).astype(float),c['strata'][take],block_days=28)
                    evidence.append(dict(symbol=sym,leaf=path['leaf'],direction=dname,year=2026,rule=path['rule'],**desc,**inf,**{'block28_'+k:v for k,v in di.items()}))
            for chosen in [s for s in selected if s['symbol']==sym and s['direction']=='up']:
                path=next(p for p in c['paths'] if p['leaf']==chosen['leaf']);mask=condition_mask(c['filled'],path['conditions'])
                for yr in [2025,2026]:
                    for name,fee,slip in [('base',.001,.0005),('stress',.0015,.0015)]:
                        m,tr=diagnostic_account(c['raw'],mask&c['per'][yr],fee,slip)
                        accounts.append(dict(symbol=sym,leaf=chosen['leaf'],year=yr,cost=name,**m));tr.to_csv(OUT/f'{sym}_leaf{chosen["leaf"]}_{yr}_{name}_trades.csv',index=False)
        inc=pd.DataFrame(increment);inc['p_holm8']=holm(inc.p);inc.to_csv(OUT/'incremental_loss_tests.csv',index=False)
        ev=pd.DataFrame(evidence);audit=ev.year==2026;ev.loc[audit,'p_holm']=holm(ev.loc[audit,'p'].fillna(1))
        ev['selected_2025']=False
        for s in selected:ev.loc[(ev.symbol==s['symbol'])&(ev.leaf==s['leaf'])&(ev.direction==s['direction']),'selected_2025']=True
        ev['audit_pass']=audit&ev.selected_2025&(ev.nonoverlap_24h_events>=30)&(ev.matched_coverage>=.7)&(ev.positive_quarters>=2)&(ev.matched_lift>0)&(ev.p_holm<.05)
        ev.to_csv(OUT/'all_rule_evidence.csv',index=False)
        pd.DataFrame(scores).to_csv(OUT/'model_scores.csv',index=False);pd.DataFrame(accounts).to_csv(OUT/'diagnostic_accounts.csv',index=False)
        pd.DataFrame(coverage).to_csv(OUT/'common_sample_coverage.csv',index=False);pd.DataFrame(calibration).to_csv(OUT/'calibration.csv',index=False)
        dump(selected,OUT/'selected_rules.json')
        state.update(research_calculated=True,selected_2025=len(selected),patterns_passing_2026=int(ev.audit_pass.sum()),
            models_with_corrected_loss_improvement=int(((inc.p_holm8<.05)&(inc.mean_loss_reduction>0)).sum()),
            coverage_over90_each=all(r['coverage']>=.9 for r in coverage),feature_count=92)
        dump(state,OUT/'execution_status.json');notebook()
        state.update(completed=True,notebook_executed=True,notebook_sha256=hashlib.sha256((OUT/'Research_Executed.ipynb').read_bytes()).hexdigest(),ended=datetime.now(timezone.utc).isoformat())
        dump(state,OUT/'execution_status.json')
        print(json.dumps(clean(state),ensure_ascii=False),flush=True)
    except Exception as e:
        state.update(completed=False,error=str(e));dump(state,OUT/'execution_status.json');traceback.print_exc();raise

def notebook():
    import nbformat
    from nbclient import NotebookClient
    n=nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell('# Derivatives incremental-information research\nReal retrospective archives; not certified historical publication vintages; not forward evidence. The receipt is finalized after successful notebook execution.'),
      nbformat.v4.new_code_cell("from pathlib import Path\nimport pandas as pd, json\nfrom IPython.display import display\np=Path('derivative_outputs')\ndisplay(pd.read_csv(p/'common_sample_coverage.csv'))"),
      nbformat.v4.new_code_cell("display(pd.read_csv(p/'model_scores.csv'))\ndisplay(pd.read_csv(p/'incremental_loss_tests.csv'))"),
      nbformat.v4.new_code_cell("e=pd.read_csv(p/'all_rule_evidence.csv')\ndisplay(e[e.selected_2025])\nprint('Audit passes:', e.audit_pass.sum())"),
      nbformat.v4.new_code_cell("f=p/'diagnostic_accounts.csv'\nprint('No selected UP account' if f.stat().st_size<5 else pd.read_csv(f).to_string(index=False))\nprint(json.loads((Path('derivative_inputs')/'external_coverage.json').read_text()))")])
    NotebookClient(n,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(ROOT)}}).execute()
    nbformat.write(n,OUT/'Research_Executed.ipynb')

if __name__=='__main__':
    with threadpool_limits(limits=1):run()
