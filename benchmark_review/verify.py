"""Independent scalar daily-account audit. Does not import the replay engine."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
TZ='Asia/Hong_Kong'

def verify(root):
    inp=root/'input';out=root/'output'
    raw=pd.read_csv(inp/'ETHUSDT_hourly_features.csv.gz',index_col=0)
    raw.index=pd.to_datetime(raw.index,utc=True).tz_convert(TZ)
    tr=pd.read_csv(inp/'trades.csv');tr=tr[tr.symbol=='ETHUSDT']
    boundary=json.loads((inp/'boundary_klines.json').read_text())
    vals={c[0]:float(c[1]) for rq in boundary['requests'] for c in rq['result']}
    final={2025:vals[1767196740000],2026:vals[1789401540000]}
    checks=[]
    for year in [2025,2026]:
        a=pd.Timestamp(f'{year}-01-01',tz=TZ);b=pd.Timestamp('2026-01-01' if year==2025 else '2026-09-15',tz=TZ)
        dn=pd.read_csv(out/f'{year}_daily_returns.csv',index_col=0)
        dn.index=pd.to_datetime(dn.index,utc=True).tz_convert(TZ)
        for nm,fee,slip in [('Strategy',.001,.0005),('Strategy_stress',.0015,.0015)]:
            group=tr[(tr.year==year)&(tr.cost==('base' if nm=='Strategy' else 'stress'))].copy()
            group['en']=pd.to_datetime(group.entry_hkt,utc=True).dt.tz_convert(TZ)
            group['ex']=pd.to_datetime(group.exit_hkt,utc=True).dt.tz_convert(TZ)
            prev=1.;daily=[]
            for day in dn.index:
                mark=day+pd.Timedelta(days=1);value=1.
                for r in group.itertuples():
                    if r.en>=mark:break
                    entry=float(raw.loc[r.en-pd.Timedelta(minutes=1),'execution_open'])
                    qty=value/(entry*(1+fee)*(1+slip))
                    if r.ex<=mark:
                        exitp=float(raw.loc[r.ex-pd.Timedelta(minutes=1),'execution_open'])
                        value=qty*exitp*(1-fee)*(1-slip)
                    else:
                        value=qty*float(raw.loc[mark,'close']);break
                daily.append(value/prev-1);prev=value
            np.testing.assert_allclose(dn[nm],daily,rtol=0,atol=2e-13)
            checks.append({'year':year,'check':'independent_daily_strategy','account':nm,'daily_marks':len(daily)})
        weights=json.loads((out/'passive_weights.json').read_text())
        w=next(v['expost_matched_initial_eth_fraction'] for v in weights if v['year']==year and 'expost_matched_initial_eth_fraction' in v)
        pw=next(v['expost_matched_initial_eth_fraction'] for v in weights if v['year']==2025)
        mix={'ETH100':1.,'Cash':0.,'ETH25':.25,'ETH50':.5,'Risk_matched_expost':w}
        if year==2026:mix['Prior_year_weight']=pw
        for name,weight in mix.items():
            qty=weight/(float(raw.loc[a,'execution_open'])*1.001*1.0005)
            marked=[]
            for day in dn.index:
                mark=day+pd.Timedelta(days=1)
                v=1-weight+qty*float(raw.loc[mark,'close']) if mark<b else 1-weight+qty*final[year]*.999*.9995
                marked.append(v)
            rr=np.diff(np.r_[1.,marked])/np.r_[1.,marked[:-1]]
            np.testing.assert_allclose(dn[name],rr,rtol=0,atol=2e-13)
            checks.append({'year':year,'check':'independent_passive_formula','account':name,'weight':weight})
        strategy_vol=dn.Strategy.std(ddof=1)*np.sqrt(365)
        riskvol=dn.Risk_matched_expost.std(ddof=1)*np.sqrt(365)
        assert abs(strategy_vol-riskvol)<1e-10
        checks.append({'year':year,'check':'expost_vol_matching','absolute_vol_difference':abs(strategy_vol-riskvol)})
    inf=pd.read_csv(out/'inference_2026.csv');dr=pd.read_csv(out/'2026_daily_returns.csv')
    for r in inf.itertuples():
        delta=np.log1p(dr.Strategy)-np.log1p(dr[r.benchmark])
        assert abs(delta.mean()-r.mean_daily_log_excess)<1e-13
    # Independent Holm implementation.
    rawp=inf.p_centered_one_sided.to_numpy();ix=np.argsort(rawp);pv=np.maximum.accumulate(rawp[ix]*np.arange(len(ix),0,-1));ans=np.empty(len(ix));ans[ix]=np.minimum(pv,1)
    np.testing.assert_allclose(ans,inf.p_holm4,atol=1e-14)
    checks.append({'check':'paired_growth_and_Holm','tests':len(inf)})
    outp={'passed':True,'checks':checks,'check_count':len(checks),
      'scope':'Independent daily strategy/passive arithmetic, exact calendar windows, risk matching and inference input/Holm; not a second independent market-data download or reimplementation of the model/bootstrap/null generator.'}
    (out/'independent_verification.json').write_text(json.dumps(outp,indent=2))
    print(f'Independent verification: {len(checks)} checks passed.')
    return outp
if __name__=='__main__':verify(Path(__file__).resolve().parent.parent)
