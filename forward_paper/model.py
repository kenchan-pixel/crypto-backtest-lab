"""Non-executable, hash-locked tree inference. No new training on live data."""
from pathlib import Path
import json,hashlib,math
from .core import MODEL_SHA

def load(path):
 b=Path(path).read_bytes()
 if hashlib.sha256(b).hexdigest()!=MODEL_SHA:raise ValueError('Frozen model hash mismatch')
 m=json.loads(b)
 if m['schema']!='frozen-hgb-v1' or m['training_year']!=2024 or m['training_events']!=669:raise ValueError('Unexpected frozen model')
 return m

def encode(m, features):
 expected=m['categorical_columns']+m['numeric_columns']
 if set(features)!=set(expected):raise ValueError('Missing/extra feature: future targets are not allowed')
 row=[]
 for c in m['categorical_columns']:
  if features[c] not in m['vocabulary'][c]:raise ValueError('Unknown schema category: '+c)
  row.extend(float(features[c]==v) for v in m['vocabulary'][c])
 for c in m['numeric_columns']:
  v=float(features[c])
  if not math.isfinite(v):raise ValueError('Incomplete numerical feature')
  row.append(v)
 if len(row)!=len(m['feature_columns']):raise ValueError('Frozen feature-order mismatch')
 return row

def predict_row(m,row):
 total=m['base_score']
 for tree in m['trees']:
  i=0;steps=0
  while not tree[i][6]:
   _,j,t,missing,l,r,_=tree[i];v=row[j]
   i=(l if missing else r) if math.isnan(v) else (l if v<=t else r)
   steps+=1
   if steps>len(tree) or i<0 or i>=len(tree):raise ValueError('Malformed non-executable tree')
  total+=tree[i][0]
 return total

def predict(m,features):return predict_row(m,encode(m,features))
