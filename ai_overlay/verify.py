"""Independent packet/account arithmetic, not a second market source or fresh LLM.
Does not import the main analyzer or its weighted replay function.
"""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];TZ='Asia/Hong_Kong'

def rr(x,n=2):return round(float(x),n) if pd.notna(x) and np.isfinite(x) else None

def main():
    out=ROOT/'output';maps=json.loads((ROOT/'ledger/mapping.json').read_text())
    ds=[json.loads(s) for s in (ROOT/'ledger/decisions.jsonl').read_text().splitlines()]
    raw={}
    for coin in ['ETHUSDT','BTCUSDT']:
        f=pd.read_csv(ROOT/f'inputs/{coin}_hourly_features.csv.gz',index_col=0)
        f.index=pd.to_datetime(f.index,utc=True).tz_convert(TZ);raw[coin]=f
    tr=pd.read_csv(ROOT/'input/trades.csv');tr=tr[(tr.symbol=='ETHUSDT')&(tr.cost=='base')].copy()
    tr['exit']=pd.to_datetime(tr.exit_hkt,utc=True).dt.tz_convert(TZ)
    macro=pd.DataFrame(json.loads((ROOT/'input/macro_events.json').read_text())['events'])
    macro['release']=pd.to_datetime(macro.release_at,utc=True).dt.tz_convert(TZ)
    checks=[];eth=raw['ETHUSDT'];btc=raw['BTCUSDT']
    # Every packet's prices and finished-trade summaries reconstructed independently.
    for m in maps:
        p=json.loads((ROOT/f'ledger/packets/{m["step"]:03d}.json').read_text());c=pd.Timestamp(m['cut'])
        for days,key in [(1,'1d'),(7,'7d'),(30,'30d')]:
            actual=(eth.loc[c,'close']/eth.loc[c-pd.Timedelta(days=days),'close']-1)*100
            assert rr(actual)==p['ETH_pct'][key]
        for days,key in [(7,'7d'),(30,'30d')]:
            actual=(btc.loc[c,'close']/btc.loc[c-pd.Timedelta(days=days),'close']-1)*100
            assert rr(actual)==p['BTC_pct'][key]
        for days in [28,90]:
            z=tr[(tr.exit<c)&(tr.exit>=c-pd.Timedelta(days=days))]
            v=p['closed_parent'][str(days)]
            assert len(z)==v['closed'] and rr(z.net_return.mean()*100)==v['mean_pct']
            assert rr((np.prod(1+z.net_return)-1)*100)==v['total_pct']
        allowed=macro[(macro.release<=c-pd.Timedelta(hours=1))&(macro.release>=c-pd.Timedelta(days=7))].sort_values('release')
        assert len(allowed)==len(p['macro_past7d'])
        for r,v in zip(allowed.itertuples(),p['macro_past7d']):
            assert r.indicator==v['indicator'] and rr(r.surprise_raw,3)==v['surprise']
            assert rr((c-r.release)/pd.Timedelta(days=1),1)==v['age_days']
        checks.append({'check':'causal_packet_price_closed_trade_macro','step':m['step']})
    allouts=pd.read_csv(out/'trades.csv');summary=pd.read_csv(out/'account_summary.csv')
    for year in [2025,2026]:
        parent=tr[tr.year==year].sort_values('entry_hkt')
        dates=pd.to_datetime(pd.read_csv(out/f'{year}_daily_returns.csv',index_col=0).index,utc=True).tz_convert(TZ)
        actual_daily=pd.read_csv(out/f'{year}_daily_returns.csv',index_col=0)
        for account in ['Original','Half','Simple','LLM']:
          for cost,fee,slip in [('base',.001,.0005),('stress',.0015,.0015)]:
            actions=[];expected=[];cash=1.;qty=0.
            for r in parent.itertuples():
                en=pd.Timestamp(r.entry_hkt);ex=pd.Timestamp(r.exit_hkt)
                if account=='Original':w=1.
                elif account=='Half':w=.5
                else:
                    eligible=[x for x in maps if x['year']==year and pd.Timestamp(x['effective'])<=en]
                    w=.5 if not eligible else (eligible[-1]['simple_weight'] if account=='Simple' else ds[eligible[-1]['step']-1]['weight'])
                if w==0:continue
                entrypx=eth.loc[en-pd.Timedelta(minutes=1),'execution_open']
                exitpx=eth.loc[ex-pd.Timedelta(minutes=1),'execution_open']
                before=cash;units=before*w/(entrypx*(1+fee)*(1+slip));cash=before*(1-w)
                actions.append((en,cash,units))
                cash+=units*exitpx*(1-fee)*(1-slip);actions.append((ex,cash,0.))
                expected.append((str(en),str(ex),w,cash,before,cash-before))
            stored=allouts[(allouts.year==year)&(allouts.account==account)&(allouts.cost==cost)]
            assert len(expected)==len(stored)
            for ev,sv in zip(expected,stored.itertuples()):
                assert ev[0]==sv.entry_hkt and ev[1]==sv.exit_hkt and ev[2]==sv.weight
                assert np.isclose(ev[3],sv.cash_after,atol=1e-11,rtol=0)
                assert np.isclose(ev[5],sv.realized_pnl,atol=1e-11,rtol=0)
            nav=[]
            for day in dates:
                end=day+pd.Timedelta(days=1)
                avail=[x for x in actions if x[0]<=end]
                cashmark,units=(avail[-1][1],avail[-1][2]) if avail else (1.,0.)
                nav.append(cashmark+units*eth.loc[end,'close'])
            dr=np.diff(np.r_[1.,nav])/np.r_[1.,nav[:-1]]
            col=account if cost=='base' else account+'_stress'
            assert np.allclose(dr,actual_daily[col].to_numpy(),atol=1e-12,rtol=0)
            metrics=summary[(summary.year==year)&(summary.account==account)&(summary.cost==cost)].iloc[0]
            assert abs(cash-1-metrics.net_return)<1e-11
            p=np.array([v[5] for v in expected]);loss=-p[p<0].sum()
            if loss>0:assert np.isclose(p[p>0].sum()/loss,metrics.profit_factor_realized_pnl,atol=1e-11,rtol=0)
            checks.append({'check':'independent_weighted_account_and_daily_nav','year':year,'account':account,'cost':cost,'trades':len(expected)})
    # Paired daily growth inputs verified separately, not a second bootstrap implementation.
    f=pd.read_csv(out/'2026_daily_returns.csv');a=pd.read_csv(out/'audit_inference.csv')
    for r in a.itertuples():
        delta=np.log1p(f.LLM)-np.log1p(f[r.benchmark])
        assert abs(delta.mean()-r.mean_daily_log_excess)<1e-14
        checks.append({'check':'paired_daily_growth_input','benchmark':r.benchmark})
    result={'passed':True,'checks':checks,'check_count':len(checks),
      'scope':'91 packet price/finished-trade/macro summaries,16 weighted accounts with daily NAV,4 inference inputs. Not independent fresh AI, second market download, or a full independent derivative-feature/bootstrap implementation.'}
    (out/'independent_verification.json').write_text(json.dumps(result,indent=2))
    print('INDEPENDENT CHECKS',len(checks),'PASSED')
    return result
if __name__=='__main__':main()
