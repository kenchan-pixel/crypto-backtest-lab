"""All-path evidence; resample weekly groups rather than independent hours."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from .data import SEED


def paths_from_tree(tree, columns):
    structure=tree.tree_;out=[]
    def visit(node,conditions):
        left,right=structure.children_left[node],structure.children_right[node]
        if left==right:
            out.append({'leaf':int(node),'conditions':conditions,
              'rule':' AND '.join(f"{v['feature']} {v['operator']} {v['threshold']:.6g}" for v in conditions)})
            return
        base={'feature':columns[structure.feature[node]],'threshold':float(structure.threshold[node])}
        visit(left,conditions+[dict(base,operator='<=')]);visit(right,conditions+[dict(base,operator='>')])
    visit(0,[])
    return out


def condition_mask(x, conditions):
    m=np.ones(len(x),dtype=bool)
    for c in conditions:
        v=x[c['feature']].to_numpy()
        m &= v<=c['threshold'] if c['operator']=='<=' else v>c['threshold']
    return m


def nonoverlap(index, mask, hours=24):
    selected=[];last=None;duration=pd.Timedelta(hours=hours)
    for i in np.flatnonzero(mask):
        t=index[i]
        if last is None or t>=last+duration: selected.append(i);last=t
    return np.array(selected,dtype=int)


def strata_for(x, vol_cuts):
    quarter=x.index.tz_localize(None).to_period('Q').astype(str)
    regime=(x['own_return_30d']>0).astype(int).astype(str)
    vol=pd.Series(np.digitize(x.volatility24,vol_cuts),index=x.index).astype(str)
    return pd.Series(np.asarray(quarter)+'|'+regime.to_numpy()+'|'+vol.to_numpy(),index=x.index)


def _matched_arrays(mask, target, strata):
    codes,levels=pd.factorize(strata,sort=True);S=len(levels)
    count=np.bincount(codes,minlength=S)
    ns=np.bincount(codes,weights=mask,minlength=S);nc=count-ns
    ys=np.bincount(codes,weights=mask*target,minlength=S)
    yc=np.bincount(codes,weights=(~mask)*target,minlength=S)
    eligible=(nc>=30)&(ns>0)
    return codes,S,ns,nc,ys,yc,eligible


def matched_lift(mask,target,strata):
    _,_,ns,nc,ys,yc,eligible=_matched_arrays(mask,target,strata)
    n=ns[eligible].sum();alln=mask.sum()
    if n==0: return np.nan,np.nan,np.nan,0.
    ps=ys[eligible].sum()/n
    pc=np.sum(ns[eligible]*yc[eligible]/nc[eligible])/n
    return float(ps-pc),float(ps),float(pc),float(n/alln) if alln else 0.


def cluster_inference(index,mask,target,strata,block_days=7,reps=1999):
    codes,S,ns,nc,ys,yc,eligible=_matched_arrays(mask,target,strata)
    observed,ps,pc,coverage=matched_lift(mask,target,strata)
    if not np.isfinite(observed):
        return {'p':1.,'ci_low':None,'ci_high':None,'limited':True,'clusters':0}
    # Fixed calendar buckets, paired signal/control within each sampled bucket.
    elapsed=(index.asi8-index[0].value)//int(pd.Timedelta(days=block_days).value)
    weeks=np.asarray(elapsed,dtype=int);W=int(weeks.max())+1
    supporting=len(np.unique(weeks[mask]))
    if W<10 or supporting<10:
        return {'p':1.,'ci_low':None,'ci_high':None,'limited':True,'clusters':supporting}
    flat=weeks*S+codes
    buckets=[np.bincount(flat,weights=z,minlength=W*S).reshape(W,S)[:,eligible]
             for z in [mask.astype(float),mask*target,(~mask).astype(float),(~mask)*target]]
    rng=np.random.default_rng(SEED)
    weights=rng.multinomial(W,np.full(W,1/W),size=reps)
    n_s,y_s,n_c,y_c=[weights@arr for arr in buckets]
    validstratum=n_c>0
    used_n=n_s*validstratum
    denom=used_n.sum(axis=1)
    ctr=np.divide(y_c,n_c,out=np.zeros_like(y_c),where=n_c>0)
    boot=np.divide((y_s*validstratum).sum(axis=1)-(used_n*ctr).sum(axis=1),denom,
                   out=np.full(reps,np.nan),where=denom>0)
    boot=boot[np.isfinite(boot)]
    if len(boot)<reps*.9:
        return {'p':1.,'ci_low':None,'ci_high':None,'limited':True,'clusters':supporting}
    ci=np.quantile(boot,[.025,.975])
    p=(1+np.sum(boot-observed>=observed))/(len(boot)+1)
    return {'p':float(p),'ci_low':float(ci[0]),'ci_high':float(ci[1]),'limited':False,
            'clusters':supporting,'bootstrap_replicates':len(boot)}


def describe(index,mask,y,ret,strata,direction):
    target=(y==direction).astype(float)
    n=int(mask.sum());n_non=len(nonoverlap(index,mask))
    lift,ps,pc,coverage=matched_lift(mask,target,strata)
    selected=ret[mask]
    # Returns are long-spot hypothetical one-event net returns, NOT short profits.
    cost_factor=(1-.001)*(1-.0005)/((1+.001)*(1+.0005))
    net=(1+selected)*cost_factor-1
    quarters=np.asarray(index.tz_localize(None).to_period('Q').astype(str))
    qr={}
    for q in sorted(set(quarters)):
        take=quarters==q
        qlift,*_=matched_lift(mask[take],target[take],strata.iloc[np.flatnonzero(take)])
        qr[q]=None if not np.isfinite(qlift) else float(qlift)
    return {'signal_hours':n,'nonoverlap_24h_events':n_non,
      'target_probability':float(target[mask].mean()) if n else None,
      'unconditional_probability':float(target.mean()),'matched_probability':ps,
      'matched_control_probability':pc,'matched_lift':lift,'matched_coverage':coverage,
      'false_alarms':int(n-target[mask].sum()),
      'mean_forward_return':float(np.mean(selected)) if n else None,
      'median_forward_return':float(np.median(selected)) if n else None,
      'mean_long_net_return':float(np.mean(net)) if n else None,
      'positive_quarters':sum(v is not None and v>0 for v in qr.values()),
      'quarter_lifts':json.dumps(qr),
      'nonoverlap_target_probability':float(target[nonoverlap(index,mask)].mean()) if n_non else None}


def holm(p):
    p=np.asarray(p,float);order=np.argsort(p);out=np.ones(len(p));high=0.
    for j,i in enumerate(order):high=max(high,(len(p)-j)*p[i]);out[i]=min(1.,high)
    return out
