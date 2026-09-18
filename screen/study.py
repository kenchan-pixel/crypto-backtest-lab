"""One frozen exploratory run. No iterative parameter search or live orders."""
from __future__ import annotations
import hashlib,json,os,sys,traceback
from pathlib import Path
import numpy as np
import pandas as pd
from .data import load,TZ,START,END
from .engine import signal,simulate,VARIANTS,PRIMARY,COSTS,block_test,holm
OUT=Path('screen_outputs')
SPLITS={'IS':(START,pd.Timestamp('2024-01-01',tz=TZ)),
 'VALIDATION':(pd.Timestamp('2024-01-01',tz=TZ),pd.Timestamp('2025-01-01',tz=TZ)),
 'OOS_REUSED':(pd.Timestamp('2025-01-01',tz=TZ),END),'FULL':(START,END)}
def clean(x):
    if isinstance(x,dict): return {k:clean(v) for k,v in x.items()}
    if isinstance(x,list): return [clean(v) for v in x]
    if isinstance(x,(float,np.floating)) and not np.isfinite(x): return None
    if isinstance(x,np.integer): return int(x)
    return x

def execute():
    OUT.mkdir(exist_ok=True)
    state={'state':'RUNNING','real_data_screen_completed':False,'live_approved':False,
      'is_untouched_out_of_sample':False,'market_data_simulated':False,
      'protocol_sha256':hashlib.sha256(Path('screen/PROTOCOL.md').read_bytes()).hexdigest(),
      'commit_sha':os.getenv('GITHUB_SHA','local'),'run_id':os.getenv('GITHUB_RUN_ID','local')}
    def save_state(): (OUT/'execution_status.json').write_text(json.dumps(state,indent=2))
    save_state(); rows=[]; senses=[]; annual=[]; infer=[]; diagnostics=[];quality=[];curves={}
    try:
        for sym in ['BTCUSDT','ETHUSDT']:
            arrays,daily,q=load(sym,OUT); quality.append(q)
            q['normalized_minute_sha256']=hashlib.sha256(b''.join(x.tobytes() for x in arrays)).hexdigest()
            (OUT/f'{sym}_quality.json').write_text(json.dumps(q,indent=2))
            sigs={key:signal(daily,fam,a,b) for key,fam,a,b in VARIANTS}
            caches={}
            for name,weight in [('CASH',0.),('BUY_HOLD',1.),('HALF_BUY_HOLD',.5)]:
                for split,(start,end) in SPLITS.items():
                    m,r,tr=simulate(arrays,daily,None,start,end,passive=weight)
                    rows.append(dict(symbol=sym,strategy=name,split=split,cost='base',**m))
                    if split=='OOS_REUSED': caches[name]=r
                    if split=='FULL': curves[(sym,name)]=(1+r).cumprod()
            for key in PRIMARY:
                for split,(start,end) in SPLITS.items():
                    for cost,(fee,slip) in COSTS.items():
                        m,r,tr=simulate(arrays,daily,sigs[key],start,end,fee,slip,minute_dd=cost=='base')
                        rows.append(dict(symbol=sym,strategy=key,split=split,cost=cost,**m))
                        if cost=='base':
                            tr.to_csv(OUT/f'{sym}_{key}_{split}_trades.csv',index=False)
                            r.to_csv(OUT/f'{sym}_{key}_{split}_daily_returns.csv',index_label='hong_kong_day')
                            if split=='FULL': curves[(sym,key)]=(1+r).cumprod()
                            if split=='OOS_REUSED':
                                for benchmark in ['CASH','BUY_HOLD','HALF_BUY_HOLD']:
                                    delta=np.log1p(r.to_numpy())-np.log1p(caches[benchmark].to_numpy())
                                    b=block_test(delta)
                                    infer.append(dict(symbol=sym,strategy=key,benchmark=benchmark,block_days=28,**b))
                                    for length in [7,56]:
                                        diagnostics.append(dict(symbol=sym,strategy=key,benchmark=benchmark,block_days=length,**block_test(delta,block=length)))
                for year in range(2021,2027):
                    a=pd.Timestamp(f'{year}-01-01',tz=TZ); b=min(pd.Timestamp(f'{year+1}-01-01',tz=TZ),END)
                    m,_,_=simulate(arrays,daily,sigs[key],a,b,minute_dd=True)
                    annual.append(dict(symbol=sym,strategy=key,year=year,**m))
            for key,_,_,_ in VARIANTS:
                for split in ['FULL','OOS_REUSED']:
                    for cost in ['base','stress']:
                        a,b=SPLITS[split]; fee,slip=COSTS[cost]
                        m,_,_=simulate(arrays,daily,sigs[key],a,b,fee,slip,minute_dd=False)
                        senses.append(dict(symbol=sym,strategy=key,split=split,cost=cost,**m))
            pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
            print('REAL DATA ANALYSED',sym,flush=True)
        if len(infer)!=18: raise AssertionError('Holm family must contain 18 tests')
        tests=pd.DataFrame(infer); tests['p_holm_18']=holm(tests.p)
        tests.to_csv(OUT/'inference.csv',index=False)
        pd.DataFrame(diagnostics).to_csv(OUT/'block_length_diagnostics.csv',index=False)
        pd.DataFrame(senses).to_csv(OUT/'sensitivity.csv',index=False)
        pd.DataFrame(annual).to_csv(OUT/'annual.csv',index=False)
        metrics=pd.DataFrame(rows); metrics.to_csv(OUT/'metrics.csv',index=False)
        render(metrics,tests,pd.DataFrame(senses),quality,curves)
        state.update(state='EXPLORATORY_SCREEN_COMPLETE',real_data_screen_completed=True,
          reliable_edge_proven=False,limitations=['Historical validation reused; not blind','Few independent market cycles and closed trades',
          'Missing intraday minutes and USDT/custody risk','No tick liquidity or size-impact model'])
        save_state()
        make_notebook()
        state['results_notebook_executed']=True; save_state()
        print('SCREEN_RESULT_JSON',json.dumps(clean(metrics[(metrics.cost=='base')&(metrics.split.isin(['FULL','OOS_REUSED']))].to_dict('records')),ensure_ascii=False,allow_nan=False),flush=True)
        print('SCREEN_INFERENCE_JSON',json.dumps(clean(tests.to_dict('records')),ensure_ascii=False,allow_nan=False),flush=True)
    except Exception as exc:
        state.update(state='FAILED',real_data_screen_completed=False,error=type(exc).__name__+': '+str(exc)); save_state(); traceback.print_exc(); raise

def render(m,tests,sensitivity,quality,curves):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for sym in ['BTCUSDT','ETHUSDT']:
        fig,ax=plt.subplots(figsize=(10,6))
        for (coin,name),v in curves.items():
            if coin==sym and name!='CASH': ax.plot(v.index,v.values,label=name)
        ax.set_yscale('log'); ax.set_ylabel('Account value, initial capital = 1 (log scale)')
        ax.set_title(sym+' | 2021-2026 | net costs | exploratory, reused history')
        ax.legend(); ax.grid(True,alpha=.25); fig.tight_layout(); fig.savefig(OUT/f'{sym}_equity.png',dpi=170);plt.close(fig)
    lines=['# 低頻加密策略：探索性歷史篩選','',
      '**本輪不是已證明有效或已批准實盤。** 舊八句交易法的結果保持不變；本輪沒有根據結果再添加／調整候選。',
      '主候選預先指定 T1_200：每週一，以前一個完整香港日的收價是否高於200日平均線決定持幣／USDT，00:01才成交。',
      'T2_50_200：50日均線高於200日均線。T3_90：90日累積價格變化為正。兩者亦每週檢查。',
      '交易每邊0.10%手續費＋0.05%不利滑價；每段重置本金1，無槓桿；被動50%版本僅期初一半持幣，不定期調倉。','',
      '2025-2026是重用歷史驗證，並非未看過的盲測；勝率和交易數以完整多倉計，期末強制平倉計入。']
    for split,title in [('OOS_REUSED','2025-01-01 至 2026-09-14：重用歷史驗證'),('FULL','2021-01-01 至 2026-09-14：全期描述')]:
        lines+=['','## '+title,'','|幣種|策略|交易數|勝率|淨回報|年化回報|分鐘最大回撤|獲利因子|','|---|---|---:|---:|---:|---:|---:|---:|']
        for _,r in m[(m.split==split)&(m.cost=='base')].iterrows():
            fmt=lambda x: '—' if pd.isna(x) else f'{x:.1%}'
            pf='—' if pd.isna(r.profit_factor) else f'{r.profit_factor:.2f}'
            lines.append(f'|{r.symbol}|{r.strategy}|{int(r.sample_size)}|{fmt(r.win_rate)}|{r.net_return:.1%}|{r.cagr:.1%}|{r.max_drawdown:.1%}|{pf}|')
    lines+=['','## 證據與限制','',
      '18項主要比較的Holm校正及28日區塊抽樣區間見 inference.csv；7/56日區塊僅診斷。不能把分鐘數當獨立試驗數。',
      '全部11組參數、基本／壓力成本與全期／後段結果見 sensitivity.csv，沒有事後挑選最有利格子。',
      'BTC和ETH分開帳戶，不將回報相加。低回撤亦可能只是持幣時間少；所以須看一半持有的控制組。',
      '缺失分鐘不能補造成交；每日均線只需真實每日結束價。分鐘缺口內的真實回撤未知。USDT並非無風險美元。',
      '證據只支持後續研究取捨，不支持「長期必賺」或立即實盤。研究來源及完整凍結規格見 PROTOCOL.md。','',
      '## 資料品質','']
    for q in quality: lines.append(f"- {q['symbol']}: 研究有效分鐘 {q['observed_study_minutes']:,}/{q['expected_study_minutes']:,}; 官方校驗存檔 {q['archives_verified']}; 缺失每日結束價 {q['missing_daily_closes']}; 延誤執行日 {q['execution_delayed_days']}。")
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    (OUT/'PROTOCOL.md').write_text(Path('screen/PROTOCOL.md').read_text())

def make_notebook():
    import nbformat
    from nbclient import NotebookClient
    cells=[nbformat.v4.new_markdown_cell('# Crypto low-frequency screen\nExploratory, reused historical validation; not a reliable-edge or live approval.'),
      nbformat.v4.new_code_cell("from pathlib import Path\nimport json, pandas as pd\nfrom IPython.display import display, Image\np=Path('screen_outputs')\ns=json.loads((p/'execution_status.json').read_text())\nassert s['real_data_screen_completed'] is True\ndisplay(s)"),
      nbformat.v4.new_code_cell("m=pd.read_csv(p/'metrics.csv')\ndisplay(m[(m.cost=='base') & (m.split.isin(['FULL','OOS_REUSED']))])"),
      nbformat.v4.new_code_cell("display(pd.read_csv(p/'inference.csv'))\ndisplay(pd.read_csv(p/'sensitivity.csv'))"),
      nbformat.v4.new_code_cell("display(Image(filename=str(p/'BTCUSDT_equity.png')))\ndisplay(Image(filename=str(p/'ETHUSDT_equity.png')))"),
      nbformat.v4.new_markdown_cell('Re-run the research, including downloads and calculations: `python -m screen.study` from repository root after installing `screen/requirements.txt`. This notebook displays saved actual-run results; source code, source checksums and parameters accompany the output.')]
    nb=nbformat.v4.new_notebook(cells=cells)
    NotebookClient(nb,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(Path.cwd())}}).execute()
    nbformat.write(nb,OUT/'executed_screen.ipynb')
if __name__=='__main__': execute()
