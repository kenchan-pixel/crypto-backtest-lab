"""One-time reconstruction using original hash-bound artifacts. Never fits new data."""
from pathlib import Path
from datetime import datetime,timezone
import os,io,json,hashlib,zipfile
import requests
import numpy as np,pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
from .core import MODEL_SHA
from .model import predict_row
REPO='kenchan-pixel/crypto-backtest-lab';BRANCH='research/payoff-aware-20260920'
ROOT=Path(__file__).resolve().parents[1]
SOURCES=[(10603752542,'e1208b70c78cd60137d62a40db0c1a0f2d1c46fec0a9c8bfeeda742d370d5736','sequence'),(10604261305,'12aaeaa9699645db26036a8433e2c5437c3d4dd233507182452b783434b9314c','payoff')]

def api(method,path,payload=None):
 url='https://api.github.com/repos/'+REPO+'/'+path
 r=requests.request(method,url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'},json=payload,timeout=90)
 r.raise_for_status();return r.json()

def restore():
 data={}
 for id,sha,name in SOURCES:
  r=requests.get(f'https://api.github.com/repos/{REPO}/actions/artifacts/{id}/zip',headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'},timeout=90)
  r.raise_for_status()
  if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('Original artifact hash mismatch')
  with zipfile.ZipFile(io.BytesIO(r.content)) as z:
   data[name]={p:z.read(p) for p in z.namelist() if p.endswith(('.csv.gz','.json'))}
 return data

def build():
 path=ROOT/'forward_paper/model.json';rp=ROOT/'forward_paper/model_receipt.json'
 if path.exists():
  if hashlib.sha256(path.read_bytes()).hexdigest()!=MODEL_SHA:raise ValueError('Existing frozen model changed')
  print('Existing frozen model verified; NOT retrained');return
 data=restore();seq=data['sequence'];pay=data['payoff']
 vocab=json.loads(pay['categorical_vocabulary.json'])
 d=pd.read_csv(io.BytesIO(seq['sequence_events.csv.gz']),compression='gzip');d=d[d.symbol.eq('ETHUSDT')]
 cat=['catalyst_type','catalyst_family','trend_30d','trend_7d','vol_state','cross_asset_state','funding_state','oi_state','positioning_state','confirmation_bucket']
 num=['confirmation_return_6h','confirm_vol_expanded','confirm_oi_leverage_build','confirm_oi_deleveraging','confirm_cross_leader','confirm_cross_laggard']
 enc=ColumnTransformer([('cat',OneHotEncoder(categories=[vocab[c] for c in cat],handle_unknown='ignore',sparse_output=False,dtype=float),cat),('num','passthrough',num)],verbose_feature_names_out=False)
 X=enc.fit_transform(d);fit=d.year.eq(2024).to_numpy()
 with threadpool_limits(limits=1):
  m=HistGradientBoostingRegressor(max_iter=100,learning_rate=.05,max_leaf_nodes=7,max_depth=3,min_samples_leaf=30,l2_regularization=10,early_stopping=False,random_state=20260919).fit(X[fit],d.loc[fit,'event_long_net_base'])
  p=m.predict(X);th=max(0.,float(np.quantile(p[fit],.9)))
 trees=[]
 for predictor in m._predictors:
  trees.append([[float(n['value']),int(n['feature_idx']),float(n['num_threshold']),int(n['missing_go_to_left']),int(n['left']),int(n['right']),int(n['is_leaf'])] for n in predictor[0].nodes])
 obj={'schema':'frozen-hgb-v1','base_score':float(m._baseline_prediction[0,0]),'threshold':th,'feature_columns':list(enc.get_feature_names_out()),'categorical_columns':cat,'numeric_columns':num,'vocabulary':vocab,'trees':trees,'model_spec':m.get_params(),'training_events':int(fit.sum()),'training_year':2024}
 q=np.array([predict_row(obj,x) for x in X]);assert np.allclose(q,p,atol=1e-12,rtol=0)
 expected=pd.read_csv(io.BytesIO(pay['raw_signals.csv.gz']),compression='gzip');expected=expected[expected.symbol.eq('ETHUSDT')]
 counts={}
 for yr in [2025,2026]:
  got=d[(d.year==yr)&(p>=th)].copy();got['predicted_net']=p[(d.year==yr)&(p>=th)]
  got=got.sort_values(['entry_hkt','predicted_net','catalyst_type'],ascending=[True,False,True]).drop_duplicates('entry_hkt')
  want=expected[expected.year==yr]
  assert set(got.entry_hkt)==set(want.entry_hkt)
  assert np.allclose(got.set_index('entry_hkt').predicted_net.sort_index(),want.set_index('entry_hkt').predicted_net.sort_index(),atol=1e-12,rtol=0)
  counts[str(yr)]=len(got)
 binary=json.dumps(obj,separators=(',',':'),allow_nan=False).encode()
 if hashlib.sha256(binary).hexdigest()!=MODEL_SHA:raise ValueError('Model differs from locally verified canonical JSON')
 path.write_bytes(binary)
 receipt={'reconstruction_passed':True,'training_events':int(fit.sum()),'training_year':2024,'threshold':th,'json_equivalence_rows':len(X),'max_abs_error':float(abs(q-p).max()),'historical_signal_timestamp_checks':counts,'model_sha256':MODEL_SHA,'no_new_market_data_used':True,'verified_at':datetime.now(timezone.utc).isoformat(),'code_commit':os.getenv('GITHUB_SHA'),'run_id':os.getenv('GITHUB_RUN_ID'),'not_a_forward_performance_result':True}
 rp.write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2))

def persist():
 # Contents/commit mutation is limited to the two immutable model evidence files.
 base=api('GET','git/ref/heads/'+BRANCH)['object']['sha']
 commit=api('GET','git/commits/'+base)
 entries=[]
 for name in ['model.json','model_receipt.json']:
  path=ROOT/'forward_paper'/name
  blob=api('POST','git/blobs',{'content':path.read_text(),'encoding':'utf-8'})
  entries.append({'path':'forward_paper/'+name,'mode':'100644','type':'blob','sha':blob['sha']})
 tree=api('POST','git/trees',{'base_tree':commit['tree']['sha'],'tree':entries})
 identity={'name':'github-actions[bot]','email':'41898282+github-actions[bot]@users.noreply.github.com'}
 c=api('POST','git/commits',{'message':'paper: preserve reconstructed frozen ETH model and parity receipt','tree':tree['sha'],'parents':[base],'author':identity,'committer':identity})
 api('PATCH','git/refs/heads/'+BRANCH,{'sha':c['sha'],'force':False})
 print('MODEL_EVIDENCE_COMMIT',c['sha'])

if __name__=='__main__':
 if os.environ.get('GITHUB_REPOSITORY')!=REPO:raise ValueError('Unexpected repository')
 build();persist()
