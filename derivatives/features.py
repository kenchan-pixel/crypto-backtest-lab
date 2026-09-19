"""Causal, expiry-limited joins. Archive timestamps do not establish historical vintages."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

RATIO_COLS={
 'count_toptrader_long_short_ratio':'top_account_ratio',
 'sum_toptrader_long_short_ratio':'top_position_ratio',
 'count_long_short_ratio':'all_account_ratio',
 'sum_taker_long_short_vol_ratio':'taker_ratio'}

def asof_past(index, source, lag_hours, expiry_hours):
    source=source.sort_index()
    if not source.index.is_unique: raise ValueError('Conflicting duplicate source timestamp')
    # A source observation can first enter once its explicit assumed lag elapses.
    available=source.index+pd.Timedelta(hours=lag_hours)
    loc=np.searchsorted(available.asi8,index.asi8,side='right')-1
    ok=loc>=0;safe=np.maximum(loc,0)
    age=(index.asi8-source.index.asi8[safe])/3.6e12
    ok &= age <= lag_hours+expiry_hours
    result=source.iloc[safe].copy();result.index=index
    result.loc[~ok,:]=np.nan
    return result,np.where(ok,age,np.nan)

def prepare_sources(folder:Path,symbol:str):
    f=pd.read_csv(folder/f'{symbol}_fundingRate.csv.gz')
    f['timestamp']=pd.to_datetime(f.timestamp_utc,utc=True,format="ISO8601")
    tail=folder/f'{symbol}_funding_tail.json'
    if tail.exists():
        extra=pd.DataFrame(json.loads(tail.read_text()))
        if not extra.empty:
            extra=pd.DataFrame({'timestamp':pd.to_datetime(extra.fundingTime,unit='ms',utc=True),
                'last_funding_rate':pd.to_numeric(extra.fundingRate)})
            f=pd.concat([f,extra],ignore_index=True)
    # Overlap with API tail is permitted only for identical rate values.
    conflict=f.groupby('timestamp').last_funding_rate.nunique()>1
    if conflict.any():raise ValueError('Archive/API settled funding conflict')
    f=f.sort_values('timestamp').drop_duplicates('timestamp').set_index('timestamp')
    actual=f.index.to_series().diff()/pd.Timedelta(hours=1)
    if 'funding_interval_hours' not in f:f['funding_interval_hours']=actual
    f['funding_interval_hours']=f.funding_interval_hours.fillna(actual)
    rate=pd.to_numeric(f.last_funding_rate)/pd.to_numeric(f.funding_interval_hours)
    rate=rate.where(f.funding_interval_hours>0).replace([np.inf,-np.inf],np.nan)
    fund=pd.DataFrame({'funding_per_hour':rate,'funding_mean3':rate.rolling(3).mean(),
                       'funding_change3':rate-rate.shift(3)},index=f.index)
    m=pd.read_csv(folder/f'{symbol}_metrics.csv.gz')
    m.index=pd.to_datetime(m.timestamp_utc,utc=True,format="ISO8601")
    if not m.index.is_unique:raise ValueError('Metric times not unique')
    metrics=m[['sum_open_interest','sum_open_interest_value',*RATIO_COLS]].apply(pd.to_numeric)
    metrics=metrics.where(metrics>0).replace([np.inf,-np.inf],np.nan)
    return fund,metrics

def build_derivatives(index, sources, lag_hours=1):
    fund,metrics=sources
    a,age=asof_past(index,fund,lag_hours,12)
    a['funding_age_hours']=age
    m,_=asof_past(index,metrics,lag_hours,2)
    out=a.copy();families={c:'funding' for c in out}
    for lag in [1,6,24]:
        c=f'oi_logchange_{lag}h';out[c]=np.log(m.sum_open_interest/m.sum_open_interest.shift(lag));families[c]='oi'
    c='oi_value_logchange_24h';out[c]=np.log(m.sum_open_interest_value/m.sum_open_interest_value.shift(24));families[c]='oi'
    for original,name in RATIO_COLS.items():
        out[name]=np.log(m[original]);out[name+'_change6h']=out[name]-out[name].shift(6)
        families[name]=families[name+'_change6h']='positioning'
    return out.replace([np.inf,-np.inf],np.nan),families
