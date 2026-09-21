"""Outcome-free adaptation of the original regime and six-hour sequence definitions."""
import numpy as np,pandas as pd
from .model import encode,predict_row
TZ='Asia/Hong_Kong'
ORIGIN=pd.Timestamp('2024-01-01',tz=TZ)
TARGETS={'funding_state':['crowded_long','crowded_short'],'oi_state':['leverage_build','deleveraging'],'vol_state':['expanded'],'cross_asset_state':['leader','laggard'],'positioning_state':['long_crowded','short_crowded']}
FAMILY={'funding_state':'funding','oi_state':'oi','vol_state':'volatility','cross_asset_state':'cross_asset','positioning_state':'positioning'}
CATS=['trend_30d','trend_7d','vol_state','cross_asset_state','funding_state','oi_state','positioning_state']

def zscore(s):return (s-s.rolling(720,min_periods=168).mean())/s.rolling(720,min_periods=168).std().replace(0,np.nan)
def label(s,lo,hi,a,b,c):
 out=np.full(len(s),b,dtype=object);out[np.asarray(s)<lo]=a;out[np.asarray(s)>hi]=c;out[pd.isna(s)]='unknown';return out

def states(raw,peer,D):
 r=pd.DataFrame(index=raw.index)
 r['close']=raw.close;r['return_30d']=raw.close/raw.close.shift(720)-1;r['return_7d']=raw.close/raw.close.shift(168)-1
 r['relative_return_24h']=raw.close/raw.close.shift(24)-peer.close/peer.close.shift(24)
 r['volatility24']=np.log(raw.close).diff().rolling(24).std()
 # Match original study's indicator window start, while using already completed prices.
 r=r.loc[r.index>=ORIGIN];D=D.reindex(r.index)
 r['vol_ratio']=r.volatility24/r.volatility24.rolling(720,min_periods=168).median()
 r['funding_z']=zscore(D.funding_per_hour);r['oi_z']=zscore(D.oi_logchange_24h);r['position_z']=zscore(D.top_position_ratio)
 r['trend_30d']=label(r.return_30d,-.05,.05,'down','flat','up');r['trend_7d']=label(r.return_7d,-.02,.02,'down','flat','up')
 r['vol_state']=label(r.vol_ratio,.75,1.25,'compressed','normal','expanded')
 r['cross_asset_state']=label(r.relative_return_24h,-.02,.02,'laggard','aligned','leader')
 r['funding_state']=label(r.funding_z,-1.5,1.5,'crowded_short','normal','crowded_long')
 r['oi_state']=label(r.oi_z,-1,1,'deleveraging','stable','leverage_build')
 r['positioning_state']=label(r.position_z,-1.5,1.5,'short_crowded','balanced','long_crowded')
 return r

def bucket(v):
 if v<=-.01:return 'strong_down'
 if v<-.0025:return 'down'
 if v<=.0025:return 'flat'
 if v<.01:return 'up'
 return 'strong_up'

def sequence_features(regimes,when,ctype,family):
 t=pd.Timestamp(when);c=t+pd.Timedelta(hours=6)
 if t not in regimes.index or c not in regimes.index:raise ValueError('Confirmation not fully observed')
 a=regimes.loc[t];b=regimes.loc[c];ret=float(b.close/a.close-1)
 return {'catalyst_type':ctype,'catalyst_family':family,**{k:str(a[k]) for k in CATS},
  'confirmation_bucket':bucket(ret),'confirmation_return_6h':ret,
  'confirm_vol_expanded':float(b.vol_state=='expanded'),
  'confirm_oi_leverage_build':float(b.oi_state=='leverage_build'),'confirm_oi_deleveraging':float(b.oi_state=='deleveraging'),
  'confirm_cross_leader':float(b.cross_asset_state=='leader'),'confirm_cross_laggard':float(b.cross_asset_state=='laggard')}

def catalysts(regimes,macro):
 rows=[]
 for col,targets in TARGETS.items():
  prev=regimes[col].shift()
  for target in targets:
   last=None
   for t in regimes.index[(regimes[col]==target)&(prev!=target)]:
    if last is None or t>=last+pd.Timedelta(hours=24):rows.append((t,col+':'+target,FAMILY[col]));last=t
 for e in macro:
  t=pd.Timestamp(e['usable_at']).tz_convert(TZ)
  if t in regimes.index:rows.append((t,'macro:'+e['indicator']+':'+e['sign'],'macro'))
 return sorted(rows,key=lambda x:(x[0],x[1]))

def candidates_at(regimes,macro,cut,model):
 cut=pd.Timestamp(cut);records=[]
 for t,ctype,family in catalysts(regimes,macro):
  if t+pd.Timedelta(hours=6)!=cut:continue
  f=sequence_features(regimes,t,ctype,family)
  score=predict_row(model,encode(model,f))
  records.append({'catalyst_at':t.isoformat(),'information_cutoff':cut.isoformat(),'catalyst_type':ctype,'features':f,'prediction':score,'passes_frozen_threshold':bool(score>=model['threshold'])})
 return sorted(records,key=lambda e:(-e['prediction'],e['catalyst_type']))
