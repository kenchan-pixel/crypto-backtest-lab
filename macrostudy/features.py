"""Causal Longbridge macro-release features."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

GROUPS={
    'inflation':['cpi_yoy','core_cpi_mom','core_pce_yoy','ppi_yoy'],
    'labour':['nfp','unemployment'],
    'policy':['fed_funds_target'],
}

def load_events(path:Path):
    obj=json.loads(path.read_text())
    df=pd.DataFrame(obj['events'])
    df['release_at']=pd.to_datetime(df.release_at,utc=True)
    for c in ['actual','forecast','previous','surprise_raw','actual_minus_previous']:
        df[c]=pd.to_numeric(df[c],errors='coerce')
    return df.sort_values(['indicator','release_at']).reset_index(drop=True)

def _first_full_hour_after(ts:pd.Timestamp):
    # Strictly after publication, including exact-hour releases.
    return ts.floor('h')+pd.Timedelta(hours=1)

def build_macro(index:pd.DatetimeIndex, events:pd.DataFrame, extra_lag_hours:int=0, active_hours:int=24):
    if index.tz is None: raise ValueError('Decision index must be timezone-aware')
    idx=index.tz_convert('UTC')
    out=pd.DataFrame(index=index)
    families={}
    coverage=[]
    for indicator in sorted(events.indicator.unique()):
        e=events[events.indicator==indicator].copy()
        available=pd.DatetimeIndex([_first_full_hour_after(x)+pd.Timedelta(hours=extra_lag_hours) for x in e.release_at])
        if not available.is_monotonic_increasing: raise ValueError('Release order error')
        loc=np.searchsorted(available.asi8,idx.asi8,side='right')-1
        valid=loc>=0
        safe=np.maximum(loc,0)
        age=np.full(len(idx),np.nan)
        age[valid]=(idx.asi8[valid]-available.asi8[safe[valid]])/3.6e12
        active=valid & (age>=0) & (age<active_hours)

        a=e.actual.to_numpy(float)
        f=e.forecast.to_numpy(float)
        p=e.previous.to_numpy(float)
        f_ok=np.isfinite(f[safe])
        p_ok=np.isfinite(p[safe])
        surprise=np.where(active & f_ok,a[safe]-f[safe],0.0)
        delta=np.where(active & p_ok,a[safe]-p[safe],0.0)

        prefix=indicator
        out[prefix+'_active']=active.astype(float)
        out[prefix+'_forecast_available']=(active & f_ok).astype(float)
        out[prefix+'_surprise_raw']=surprise
        out[prefix+'_actual_minus_previous']=delta
        out[prefix+'_age_norm']=np.where(active,age/active_hours,0.0)
        group=next(k for k,v in GROUPS.items() if indicator in v)
        for c in out.columns[-5:]: families[c]=group

        for year in [2024,2025,2026]:
            yr=e[e.release_at.dt.year==year]
            coverage.append({
                'indicator':indicator,'group':group,'year':year,'release_count':len(yr),
                'forecast_missing':int(yr.forecast.isna().sum()),
                'previous_missing':int(yr.previous.isna().sum()),
            })
    if out.isna().any().any(): raise ValueError('Macro feature matrix contains NaN')
    return out,families,pd.DataFrame(coverage)

def columns_for(families,group):
    return [c for c,g in families.items() if g==group]
