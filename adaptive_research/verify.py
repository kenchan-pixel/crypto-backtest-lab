"""Independent scalar ledger: does not import study.py or its accounting functions."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
R=Path(__file__).resolve().parent.parent;O=R/'output';TZ='Asia/Hong_Kong'

def verify():
    tests=[];tr=pd.read_csv(O/'trades.csv');ss=pd.read_csv(O/'strategy_summary.csv')
    for c in ['entry_hkt','exit_hkt']:tr[c]=pd.to_datetime(tr[c],utc=True).dt.tz_convert(TZ)
    for symbol in ['BTCUSDT','ETHUSDT']:
        raw=pd.read_csv(R/'inputs'/f'{symbol}_hourly_features.csv.gz',index_col=0)
        raw.index=pd.to_datetime(raw.index,utc=True).tz_convert(TZ)
        for year in [2025,2026]:
            daily=pd.read_csv(O/f'{symbol}_{year}_daily_returns.csv',index_col=0)
            dates=pd.to_datetime(daily.index,utc=True).tz_convert(TZ)+pd.Timedelta(days=1)
            for name in ['FROZEN_RISK','ROLLING_FULL','ROLLING_RISK','SENS_RISK15','SENS_RISK25','SENS_HISTORY180']:
                schedule=pd.read_csv(O/f'{symbol}_{year}_{name}_schedule.csv')
                for cost,f,s in [('base',.001,.0005),('stress',.0015,.0015)]:
                    tt=tr[(tr.symbol==symbol)&(tr.year==year)&(tr.policy==name)&(tr.cost==cost)].sort_values('entry_hkt')
                    wealth=1.;ledger=[];last=None
                    for row in tt.itertuples():
                        en=row.entry_hkt;ex=row.exit_hkt
                        assert ex-en==pd.Timedelta(hours=24)
                        assert last is None or en>last
                        ep=float(raw.loc[en-pd.Timedelta(minutes=1),'execution_open'])
                        xp=float(raw.loc[ex-pd.Timedelta(minutes=1),'execution_open'])
                        assert ep==row.entry_price and xp==row.exit_price and 0<row.weight<=1
                        qty=wealth*row.weight/(ep*(1+s)*(1+f));idle=wealth*(1-row.weight)
                        ending=idle+qty*xp*(1-s)*(1-f)
                        assert abs(ending/wealth-1-row.net_account_return)<1e-12
                        assert abs(ending-row.cash_after)<1e-10
                        ledger.append((en,ex,wealth,idle,qty,ending));wealth=ending;last=ex
                    observed=[]
                    for date in dates:
                        value=1.
                        for en,ex,before,idle,qty,ending in ledger:
                            if date<en:break
                            if date>=ex:value=ending
                            else:value=idle+qty*float(raw.loc[date,'close']);break
                        observed.append(value)
                    col=name if cost=='base' else name+'_stress'
                    expected=np.cumprod(1+daily[col].to_numpy())
                    assert np.allclose(observed,expected,rtol=0,atol=1e-10)
                    row=ss[(ss.symbol==symbol)&(ss.year==year)&(ss.policy==name)&(ss.cost==cost)].iloc[0]
                    assert len(tt)==row.trades and abs(wealth-1-row.net_return)<1e-10
                    tests.append(dict(symbol=symbol,year=year,policy=name,cost=cost,verified_trades=len(tt),daily_nav=True))
            base=pd.read_csv(O/f'{symbol}_{year}_ROLLING_FULL_schedule.csv')
            for nm in ['ROLLING_RISK','SENS_RISK15','SENS_RISK25']:
                side=pd.read_csv(O/f'{symbol}_{year}_{nm}_schedule.csv')
                pd.testing.assert_frame_equal(base[['entry_hkt','exit_hkt']],side[['entry_hkt','exit_hkt']])
                tests.append(dict(symbol=symbol,year=year,policy=nm,same_signals=True))
    audit=pd.read_csv(O/'monthly_fit_audit.csv')
    for row in audit.itertuples():
        assert row.status=='FITTED'
        assert pd.Timestamp(row.fit_last)+pd.Timedelta(hours=24,minutes=1)<pd.Timestamp(row.cal_first)
        assert pd.Timestamp(row.cal_last)+pd.Timedelta(hours=24,minutes=1)<pd.Timestamp(row.month)
    assert len(audit)==126
    tests.append({'chronology_records_checked':len(audit)})
    result={'passed':True,'checks':tests,'count':len(tests),'scope':'Independent scalar account/price/cost/day-NAV reconstruction, schedule equivalence and fit chronology. Not an independent model-library or market-data download.'}
    (O/'independent_verification.json').write_text(json.dumps(result,indent=2))
    print('Independent checks:',len(tests),'passed')
if __name__=='__main__':verify()
