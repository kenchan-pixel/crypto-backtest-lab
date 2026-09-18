"""Phase 2: evaluate recorded hypotheses without tuning them on later years."""
from pathlib import Path
import hashlib,json,os,traceback
import numpy as np
import pandas as pd
from .data import load,features,add_cross,START,TRAIN_END,END,TZ
from .engine import simulate,shift_dates,bootstrap,holm,COSTS
OUT=Path('discovery_outputs')
SPLITS={'IS':(START,TRAIN_END),'VALIDATION_2024':(TRAIN_END,pd.Timestamp('2025-01-01',tz=TZ)),
 'AUDIT_2025_2026':(pd.Timestamp('2025-01-01',tz=TZ),END),'FULL':(START,END)}

def mask_for(f,spec,scale=1.):
    m=f.minutes.eq(60)
    for column,op,value in spec['conditions']:
        s=f[column];threshold=value*scale
        if op=='gt':c=s>threshold
        elif op=='ge':c=s>=threshold
        elif op=='lt':c=s<threshold
        elif op=='le':c=s<=threshold
        else:raise ValueError('Invalid operator')
        m&=s.notna()&c
    return m

def execute():
    OUT.mkdir(exist_ok=True)
    config=json.loads(Path('discovery/candidates.json').read_text());candidates=config['candidates']
    status={'state':'RUNNING','full_backtest_executed':False,'market_data_simulated':False,
      'genuinely_unseen_holdout':False,'live_approved':False,'code_commit':os.getenv('GITHUB_SHA'),
      'run_id':os.getenv('GITHUB_RUN_ID'),'hypotheses_sha256':hashlib.sha256(Path('discovery/candidates.json').read_bytes()).hexdigest()}
    def state(): (OUT/'execution_status.json').write_text(json.dumps(status,indent=2))
    state();markets={};frames={};qualities=[];rows=[];annual=[];sens=[];tests=[];diag=[];randoms=[];curves=[]
    try:
        for coin in ['BTCUSDT','ETHUSDT']:
            minute,q=load(coin,END,OUT);markets[coin]=minute;qualities.append(q);frames[coin]=features(minute)
        add_cross(frames)
        for coin,f in frames.items():
            f.to_csv(OUT/f'{coin}_hourly_features.csv.gz',compression='gzip',index_label='decision_hkt')
            minute=markets[coin];mask_all=f.minutes.eq(60)
            baseline={}
            for split,(a,b) in SPLITS.items():
                m,r,tr=simulate(minute,f,mask_all,a,b,24,passive=True)
                rows.append(dict(symbol=coin,strategy='BUY_HOLD',split=split,cost='base',**m));baseline[split]=r
            for spec in candidates:
                key=spec['id'];hold=spec['hold_hours'];mask=mask_for(f,spec)
                for split,(a,b) in SPLITS.items():
                    u,ur,_=simulate(minute,f,mask_all,a,b,hold,minute_dd=False)
                    rows.append(dict(symbol=coin,strategy=key+'_UNCONDITIONAL',split=split,cost='base',**u))
                    for cost,(fee,slip) in COSTS.items():
                        m,r,tr=simulate(minute,f,mask,a,b,hold,fee,slip,minute_dd=cost=='base')
                        rows.append(dict(symbol=coin,strategy=key,split=split,cost=cost,**m))
                        if cost=='base':
                            tr.to_csv(OUT/f'{coin}_{key}_{split}_trades.csv',index=False)
                            r.to_csv(OUT/f'{coin}_{key}_{split}_daily.csv',index_label='day_hkt')
                            if split in ['FULL','AUDIT_2025_2026']:
                                curves.append(pd.DataFrame({'day':r.index,'equity':(1+r).cumprod().values,'symbol':coin,'strategy':key,'split':split}))
                            if split=='AUDIT_2025_2026':
                                placebo=[]
                                for seed in range(31):
                                    rm,rr,_=simulate(minute,f,shift_dates(mask,20260918+seed)&mask_all,a,b,hold,minute_dd=False)
                                    randoms.append(dict(symbol=coin,strategy=key,seed=seed,**rm));placebo.append(np.log1p(rr.to_numpy()))
                                controls={'CASH':np.zeros(len(r)),'BUY_HOLD':np.log1p(baseline[split].to_numpy()),
                                          'UNCONDITIONAL':np.log1p(ur.to_numpy()),'SHIFTED_DATES':np.mean(placebo,axis=0)}
                                for name,br in controls.items():
                                    delta=np.log1p(r.to_numpy())-br
                                    tests.append(dict(symbol=coin,strategy=key,control=name,block_days=7,**bootstrap(delta)))
                                    diag.append(dict(symbol=coin,strategy=key,control=name,block_days=28,**bootstrap(delta,block=28)))
                for year in range(2021,2027):
                    a=pd.Timestamp(f'{year}-01-01',tz=TZ);b=min(pd.Timestamp(f'{year+1}-01-01',tz=TZ),END)
                    m,_,_=simulate(minute,f,mask,a,b,hold,minute_dd=True)
                    annual.append(dict(symbol=coin,strategy=key,year=year,**m))
                for scale in [.75,1.,1.25]:
                    for duration in [.75,1.,1.25]:
                        for cost in ['base','stress']:
                            a,b=SPLITS['AUDIT_2025_2026'];fee,slip=COSTS[cost]
                            sm,sr,_=simulate(minute,f,mask_for(f,spec,scale),a,b,hold*duration,fee,slip,minute_dd=False)
                            sens.append(dict(symbol=coin,strategy=key,threshold_scale=scale,hold_scale=duration,cost=cost,**sm))
                print('PRIMARY HYPOTHESIS EXECUTED',coin,key,flush=True)
            pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
        infer=pd.DataFrame(tests);expected=len(candidates)*2*4
        assert len(infer)==expected
        infer['p_holm']=holm(infer.p);infer['family_size']=expected
        for name,frame in [('metrics',pd.DataFrame(rows)),('annual',pd.DataFrame(annual)),('sensitivity',pd.DataFrame(sens)),
           ('inference',infer),('block28_diagnostic',pd.DataFrame(diag)),('date_controls',pd.DataFrame(randoms)),('equity',pd.concat(curves,ignore_index=True))]:
            frame.to_csv(OUT/f'{name}.csv',index=False)
        for name in ['PROTOCOL.md','HYPOTHESES.md','candidates.json']:(OUT/name).write_text(Path('discovery',name).read_text())
        status.update(state='CALCULATIONS_COMPLETE',full_backtest_executed=True,quality=qualities,
           limitations=['All old market history reused, not genuine forward evidence','Discovery cells are in-sample; selected patterns can overfit',
             'Missing-minute drawdowns unobserved; fixed costs are assumptions; USDT and exchange risk'])
        state();make_notebook(candidates)
        status.update(state='COMPLETE_WITH_DISCLOSED_LIMITATIONS',notebook_executed=True);state()
        print(pd.DataFrame(rows).query("split=='AUDIT_2025_2026' and cost=='base'")[['symbol','strategy','sample_size','net_return','max_drawdown','profit_factor']].to_string(index=False),flush=True)
    except Exception as exc:
        status.update(state='FAILED',error=type(exc).__name__+': '+str(exc));state();traceback.print_exc();raise

def make_notebook(candidates):
    import nbformat
    from nbclient import NotebookClient
    code1="from pathlib import Path\nimport json, pandas as pd, numpy as np\nfrom IPython.display import display\np=Path('discovery_outputs') if Path('discovery_outputs/metrics.csv').exists() else Path('.')\nstate=json.loads((p/'execution_status.json').read_text())\nassert state['full_backtest_executed']\ndisplay(state)\nm=pd.read_csv(p/'metrics.csv')\ndisplay(m[(m.cost=='base') & (m.split=='AUDIT_2025_2026')])"
    code2="checks=[]\nfor file in p.glob('*_trades.csv'):\n    t=pd.read_csv(file)\n    if len(t):\n        assert (t.entry_ms>t.signal_ms).all()\n        assert (t.exit_ms>t.entry_ms).all()\n        factor=(1-.0005)*(1-.001)/((1+.0005)*(1+.001))\n        assert np.allclose(t.net_return,(t.exit_open/t.entry_open)*factor-1,rtol=1e-8,atol=1e-10)\n        assert np.allclose(np.prod(1+t.net_return),t.cash_after.iloc[-1],rtol=1e-8,atol=1e-10)\n    checks.append((file.name,len(t)))\nprint('Executed ledger arithmetic/timing checks:',len(checks))\ndisplay(pd.DataFrame(checks,columns=['ledger','closed_trades']))"
    code3="display(pd.read_csv(p/'inference.csv'))\ndisplay(pd.read_csv(p/'annual.csv'))\ndisplay(pd.read_csv(p/'sensitivity.csv'))"
    code4="import matplotlib.pyplot as plt\ne=pd.read_csv(p/'equity.csv',parse_dates=['day'])\nfor coin in ['BTCUSDT','ETHUSDT']:\n    fig,ax=plt.subplots(figsize=(9,5))\n    q=e[(e.symbol==coin)&(e.split=='AUDIT_2025_2026')]\n    for key,g in q.groupby('strategy'): ax.plot(g.day,g.equity,label=key)\n    ax.set_title(coin+' | later historical audit, after costs')\n    ax.set_ylabel('Capital, starting at 1')\n    ax.legend();fig.tight_layout();fig.savefig(p/(coin+'_audit_equity.png'),dpi=160);plt.show()"
    nb=nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell('# Data-driven crypto discovery\nTraining exploration -> frozen hypotheses -> real minute-data backtests. Not a live-trading approval.'),
      *[nbformat.v4.new_code_cell(c) for c in [code1,code2,code3,code4]],
      nbformat.v4.new_markdown_cell('Full rerun, including genuine source downloads and all calculations: install discovery/requirements.txt, then run `python -m discovery.explore` and `python -m discovery.study` from source root. HYPOTHESES.md preserves the intervening human-readable freeze; do not change candidate rules based on the later audit.')])
    NotebookClient(nb,timeout=240,kernel_name='python3',resources={'metadata':{'path':str(Path.cwd())}}).execute()
    nbformat.write(nb,OUT/'Executed_Discovery.ipynb')
if __name__=='__main__':execute()
