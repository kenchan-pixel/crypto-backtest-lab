"""Frozen post-2024 hypotheses; real minute data, no live execution."""
from pathlib import Path
import hashlib,json,traceback,os
import numpy as np,pandas as pd
from discovery import data
from discovery.engine import simulate,COSTS,shift_dates,bootstrap,holm
from recent.signals import PRIMARY,HOURS,mask
TZ=data.TZ
SPLITS={'TRAIN_2024':('2024-01-01','2025-01-01'),'VALIDATE_2025':('2025-01-01','2026-01-01'),
 'AUDIT_2026':('2026-01-01','2026-09-15'),'POST2024':('2025-01-01','2026-09-15'),'FULL_RECENT':('2024-01-01','2026-09-15')}
SPLITS={k:tuple(pd.Timestamp(z,tz=TZ) for z in v) for k,v in SPLITS.items()}
OUT=Path('recent_outputs')
def run():
 OUT.mkdir(exist_ok=True)
 status={'state':'RUNNING','completed':False,'market_data_simulated':False,'genuine_unseen_holdout':False,'live_approved':False,
 'commit':os.getenv('GITHUB_SHA','local'),'run_id':os.getenv('GITHUB_RUN_ID','local'),
 'hypotheses_sha256':hashlib.sha256(Path('recent/HYPOTHESES.md').read_bytes()).hexdigest()}
 def save(): (OUT/'execution_status.json').write_text(json.dumps(status,indent=2))
 save()
 try:
  data.START=pd.Timestamp('2024-01-01',tz=TZ);data.WARM=pd.Timestamp('2023-10-01',tz=TZ)
  markets={};frames={};quality=[]
  for sym in ['BTCUSDT','ETHUSDT']:
   markets[sym],q=data.load(sym,data.END,OUT);quality.append(q);frames[sym]=data.features(markets[sym])
  data.add_cross(frames)
  metrics=[];inf=[];diagnostics=[];sens=[];quarterly=[];shifts=[];concentrations=[];allcurves={}
  for sym,f in frames.items():
   f.to_csv(OUT/f'{sym}_hourly_features.csv.gz',index_label='decision_hkt',compression='gzip')
   minute=markets[sym];store={}
   for split,(a,b) in SPLITS.items():
    m,r,_=simulate(minute,f,pd.Series(False,index=f.index),a,b,48,passive=True)
    metrics.append(dict(symbol=sym,strategy='BUY_HOLD',split=split,cost='base',**m));store[(split,'BUY_HOLD')]=r
    m,r,_=simulate(minute,f,pd.Series(True,index=f.index),a,b,48,minute_dd=False)
    metrics.append(dict(symbol=sym,strategy='UNCONDITIONAL_48H',split=split,cost='base',**m));store[(split,'UNCONDITIONAL')]=r
   for key in PRIMARY+['OLD_D4']:
    signal=mask(f,key);h=HOURS[key]
    for split,(a,b) in SPLITS.items():
     for cost,(fee,slip) in COSTS.items():
      m,r,tr=simulate(minute,f,signal,a,b,h,fee,slip,minute_dd=(cost=='base'))
      metrics.append(dict(symbol=sym,strategy=key,split=split,cost=cost,**m))
      if cost=='base':
       tr.to_csv(OUT/f'{sym}_{key}_{split}_trades.csv',index=False)
       r.to_csv(OUT/f'{sym}_{key}_{split}_daily.csv',index_label='day')
       if split=='POST2024':allcurves[(sym,key)]=(1+r).cumprod()
       returns=tr.net_return.to_numpy(dtype=float)
       without=np.prod(1+np.delete(returns,np.argmax(returns)))-1 if len(returns) else np.nan
       concentrations.append(dict(symbol=sym,strategy=key,split=split,n=len(tr),best_trade=returns.max() if len(returns) else np.nan,net_without_best=without))
       if key in PRIMARY and split=='AUDIT_2026':
        shuffled=[]
        for i in range(31):
         mm,rr,_=simulate(minute,f,shift_dates(signal,20260918+i),a,b,h,minute_dd=False)
         shifts.append(dict(symbol=sym,strategy=key,seed=20260918+i,**mm));shuffled.append(np.log1p(rr.to_numpy()))
        controls={'CASH':np.zeros(len(r)),'BUY_HOLD':np.log1p(store[(split,'BUY_HOLD')].to_numpy()),
          'UNCONDITIONAL':np.log1p(store[(split,'UNCONDITIONAL')].to_numpy()),'DATE_SHIFTS':np.mean(shuffled,axis=0)}
        for label,c in controls.items():
         delta=np.log1p(r.to_numpy())-c
         inf.append(dict(symbol=sym,strategy=key,control=label,**bootstrap(delta)))
         diagnostics.append(dict(symbol=sym,strategy=key,control=label,**bootstrap(delta,block=28)))
    if key in PRIMARY:
     for year in [2025,2026]:
      for q in [1,2,3,4]:
       a=pd.Timestamp(f'{year}-{1+3*(q-1):02d}-01',tz=TZ)
       b=min(a+pd.DateOffset(months=3),data.END)
       if a>=b:continue
       m,_,_=simulate(minute,f,signal,a,b,h,minute_dd=False)
       quarterly.append(dict(symbol=sym,strategy=key,year=year,quarter=q,**m))
     for factor in [.75,1.,1.25]:
      for duration in [.75,1.,1.25]:
       for split in ['VALIDATE_2025','AUDIT_2026','POST2024']:
        for cost in ['base','stress']:
         a,b=SPLITS[split];fee,slip=COSTS[cost]
         m,_,_=simulate(minute,f,mask(f,key,factor),a,b,h*duration,fee,slip,minute_dd=False)
         sens.append(dict(symbol=sym,strategy=key,factor=factor,duration_factor=duration,split=split,cost=cost,**m))
    print('EXECUTED',sym,key,flush=True)
   allcurves[(sym,'BUY_HOLD')]=(1+store[('POST2024','BUY_HOLD')]).cumprod()
  assert len(inf)==24
  inf=pd.DataFrame(inf);inf['p_holm24']=holm(inf.p)
  tables={'metrics':metrics,'inference':inf,'block28_diagnostic':diagnostics,'sensitivity':sens,'quarterly':quarterly,'date_controls':shifts,'concentration':concentrations}
  for name,t in tables.items():pd.DataFrame(t).to_csv(OUT/f'{name}.csv',index=False)
  pd.DataFrame(quality).to_csv(OUT/'quality.csv',index=False)
  pd.DataFrame(allcurves).to_csv(OUT/'equity.csv',index_label='day')
  make_charts(allcurves)
  status.update(state='COMPLETE_EXPLORATORY',completed=True);save()
  notebook();status['notebook_executed']=True;save()
  print(pd.DataFrame(metrics).query("cost=='base' and split in ['VALIDATE_2025','AUDIT_2026']")[['symbol','strategy','split','sample_size','net_return','max_drawdown']].to_string(index=False),flush=True)
 except Exception as e:
  status.update(state='FAILED',completed=False,error=repr(e));save();traceback.print_exc();raise

def make_charts(curves):
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 for sym in ['BTCUSDT','ETHUSDT']:
  fig,ax=plt.subplots(figsize=(10,6))
  for (coin,k),v in curves.items():
   if coin==sym:ax.plot(v.index,v.values,label=k)
  ax.set_title(sym+' | 2025-2026 | cost-adjusted | reused historical data')
  ax.set_ylabel('Account value, initial capital = 1');ax.legend();ax.grid(alpha=.2);fig.tight_layout()
  fig.savefig(OUT/f'{sym}_post2024_equity.png',dpi=160);plt.close(fig)

def notebook():
 import nbformat as nbf
 from nbclient import NotebookClient
 nb=nbf.v4.new_notebook(cells=[nbf.v4.new_markdown_cell('# Post-2024 volatility study\n2024 discovery; 2025 validation; 2026 later historical audit. Not untouched OOS or live approval.'),
  nbf.v4.new_code_cell("from pathlib import Path\nimport json,pandas as pd\nfrom IPython.display import display,Image\np=Path('recent_outputs')\ns=json.loads((p/'execution_status.json').read_text())\nassert s['completed']\ndisplay(s)"),
  nbf.v4.new_code_cell("m=pd.read_csv(p/'metrics.csv')\ndisplay(m[(m.cost=='base') & m.split.isin(['VALIDATE_2025','AUDIT_2026','POST2024'])])"),
  nbf.v4.new_code_cell("display(pd.read_csv(p/'inference.csv'))\ndisplay(pd.read_csv(p/'concentration.csv'))\ndisplay(pd.read_csv(p/'sensitivity.csv'))"),
  nbf.v4.new_code_cell("display(Image(filename=str(p/'BTCUSDT_post2024_equity.png')))\ndisplay(Image(filename=str(p/'ETHUSDT_post2024_equity.png')))"),
  nbf.v4.new_markdown_cell('Full rerun from repository root: `python -m pytest -q discovery/ recent/test_recent.py` then `python -m recent.study`. This notebook displays actual-run outputs; it does not claim to redownload raw data.')])
 NotebookClient(nb,timeout=300,kernel_name='python3',resources={'metadata':{'path':str(Path.cwd())}}).execute()
 nbf.write(nb,OUT/'Executed_Recent_Research.ipynb')
if __name__=='__main__':run()
