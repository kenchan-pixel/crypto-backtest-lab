"""Independent output arithmetic and source-join checks; never imports study.py."""
from pathlib import Path
from bisect import bisect_right
import hashlib,json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'derivative_outputs'

def verify():
    checks=[];raw={}
    for sym in ['BTCUSDT','ETHUSDT']:
        f=pd.read_csv(ROOT/'inputs'/f'{sym}_hourly_features.csv.gz',index_col=0)
        f.index=pd.to_datetime(f.index,utc=True).tz_convert('Asia/Hong_Kong');raw[sym]=f
    scores=pd.read_csv(OUT/'model_scores.csv')
    for sym in raw:
        for year in [2025,2026]:
            pp=pd.read_csv(OUT/f'{sym}_{year}_paired_predictions.csv.gz',index_col=0)
            pp.index=pd.to_datetime(pp.index,utc=True).tz_convert('Asia/Hong_Kong')
            r=raw[sym].execution_open.reindex(pp.index+pd.Timedelta(hours=24)).to_numpy()/raw[sym].execution_open.reindex(pp.index).to_numpy()-1
            assert np.allclose(r,pp.return_24h,rtol=0,atol=1e-13)
            y=np.where(r>=.01,2,np.where(r<=-.01,0,1));assert np.array_equal(y,pp.label)
            for name in ['B','F','O','P','A']:
                p=pp[[name+'_'+z for z in ['down','neutral','up']]].to_numpy()
                assert np.allclose(p.sum(1),1)
                ll=float(np.mean([-np.log(p[i,j]) for i,j in enumerate(y)]))
                br=float(np.mean(np.sum((p-np.eye(3)[y])**2,axis=1)))
                stored=scores[(scores.symbol==sym)&(scores.model=='boosted')&(scores.features==name)&(scores.year==year)].iloc[0]
                assert abs(ll-stored.log_loss)<1e-12 and abs(br-stored.multiclass_brier)<1e-12
                checks.append({'check':'labels_and_score','symbol':sym,'year':year,'features':name,'hours':len(y)})
    # Reconstruct published selected rules directly from raw prices and past metric observation.
    selected=json.loads((OUT/'selected_rules.json').read_text())
    ev=pd.read_csv(OUT/'all_rule_evidence.csv')
    for item in selected:
        sym=item['symbol'];f=raw[sym];peer=raw['ETHUSDT' if sym=='BTCUSDT' else 'BTCUSDT']
        ret=f.close/f.close.shift(168)-1;other=peer.close/peer.close.shift(168)-1
        corr=np.log(f.close).diff().rolling(168,min_periods=168).corr(np.log(peer.close).diff())
        vals={'weekend':pd.Series((f.index.weekday>=5).astype(float),index=f.index),'return_168h':ret,
              'relative_return_168h':ret-other,'peer_correlation_168h':corr,'own_return_30d':f.close/f.close.shift(720)-1}
        m=pd.read_csv(ROOT/'derivative_inputs'/f'{sym}_metrics.csv.gz')
        mt=pd.to_datetime(m.timestamp_utc,utc=True,format='ISO8601')
        observed=(pd.DatetimeIndex(mt)+pd.Timedelta(hours=1)).asi8.tolist();ratio=[]
        for t in f.index.asi8:
            j=bisect_right(observed,int(t))-1
            ratio.append(np.log(m.sum_toptrader_long_short_ratio.iloc[j]) if j>=0 and t-observed[j]<=2*3600e9 else np.nan)
        vals['top_position_ratio']=pd.Series(ratio,index=f.index)
        paths=json.loads((OUT/f'{sym}_tree_paths.json').read_text());path=next(p for p in paths if p['leaf']==item['leaf'])
        for year in [2025,2026]:
            pp=pd.read_csv(OUT/f'{sym}_{year}_paired_predictions.csv.gz',index_col=0);idx=pd.to_datetime(pp.index,utc=True).tz_convert('Asia/Hong_Kong')
            mask=np.ones(len(idx),bool)
            for c in path['conditions']:
                v=vals[c['feature']].reindex(idx).to_numpy();assert np.isfinite(v).all()
                mask &= v<=c['threshold'] if c['operator']=='<=' else v>c['threshold']
            entry=ev[(ev.symbol==sym)&(ev.leaf==item['leaf'])&(ev.direction==item['direction'])&(ev.year==year)].iloc[0]
            assert mask.sum()==entry.signal_hours
            direction=2 if item['direction']=='up' else 0
            assert abs((pp.label.to_numpy()[mask]==direction).mean()-entry.target_probability)<1e-12
            spaced=[]
            for t in idx[mask]:
                if not spaced or t>=spaced[-1]+pd.Timedelta(hours=24):spaced.append(t)
            assert len(spaced)==entry.nonoverlap_24h_events
            checks.append({'check':'selected_rule_from_raw','symbol':sym,'year':year,'signal_hours':int(mask.sum())})
            if direction!=2:continue
            for name,fee,slip in [('base',.001,.0005),('stress',.0015,.0015)]:
                tr=pd.read_csv(OUT/f'{sym}_leaf{item["leaf"]}_{year}_{name}_trades.csv');cash=1.;last=None;rows=[]
                for t in idx[mask]:
                    en=t+pd.Timedelta(minutes=1);ex=en+pd.Timedelta(hours=24)
                    if last is not None and en<=last:continue
                    px=f.loc[t,'execution_open'];xp=f.loc[t+pd.Timedelta(hours=24),'execution_open']
                    q=cash/(px*(1+fee)*(1+slip));after=q*xp*(1-fee)*(1-slip)
                    rows.append((str(en),str(ex),after/cash-1,after));cash=after;last=ex
                assert len(rows)==len(tr)
                for i,(en,ex,net,endcash) in enumerate(rows):
                    assert tr.iloc[i].entry_hkt==en and tr.iloc[i].exit_hkt==ex
                    assert abs(tr.iloc[i].net_return-net)<1e-12 and abs(tr.iloc[i].cash_after-endcash)<1e-12
                checks.append({'check':'independent_spot_replay','symbol':sym,'year':year,'cost':name,'rows':len(rows),'net_return':cash-1})
    receipt=json.loads((OUT/'execution_status.json').read_text())
    nbpath=OUT/'Research_Executed.ipynb';nb=json.loads(nbpath.read_text());code=[c for c in nb['cells'] if c['cell_type']=='code']
    assert receipt['completed'] and receipt['notebook_executed'] and receipt['notebook_sha256']==hashlib.sha256(nbpath.read_bytes()).hexdigest()
    assert all(c.get('execution_count') is not None and not any(x.get('output_type')=='error' for x in c.get('outputs',[])) for c in code)
    checks.append({'check':'bound_notebook_receipt','executed_cells':len(code)})
    result={'passed':True,'checks':checks,'check_count':len(checks),'scope':'Scores/labels, selected-rule raw conditions and account arithmetic. Entire feature set and bootstrap not independently reimplemented; same original market sources.'}
    (OUT/'independent_verification.json').write_text(json.dumps(result,indent=2))
    print('Independent verification passed',len(checks),'checks')
if __name__=='__main__':verify()
