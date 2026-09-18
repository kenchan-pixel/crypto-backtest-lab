"""Audited official Binance minute inputs. No market-data simulation or imputation."""
from __future__ import annotations
import hashlib, io, json, re, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
TZ = 'Asia/Hong_Kong'
MINUTE = 60_000
DAY = 86_400_000
START = pd.Timestamp('2021-01-01', tz=TZ)
END = pd.Timestamp('2026-09-15', tz=TZ)
WARM = pd.Timestamp('2020-01-01', tz=TZ)
def ms(t):
    return int(pd.Timestamp(t).value // 1_000_000)
def parse(raw: pd.DataFrame):
    if raw.shape[1] != 12 or raw.empty:
        raise ValueError('Expected nonempty 12-column archive')
    a = raw.to_numpy(dtype=np.float64)
    if not np.isfinite(a).all():
        raise ValueError('Non-numeric or non-finite input')
    ot, ct = raw.iloc[:,0].to_numpy(np.int64), raw.iloc[:,6].to_numpy(np.int64)
    us = ot >= 100_000_000_000_000
    if np.any(us != (ct >= 100_000_000_000_000)):
        raise ValueError('Mixed timestamp units inside a row')
    ous, cus = np.where(us,ot,ot*1000), np.where(us,ct,ct*1000)
    if np.any(ous % 60_000_000):
        raise ValueError('Minute boundary error')
    anomalous = ~np.isin(cus-ous,[59_999_000,59_999_999])
    if np.any(anomalous & (us | (cus-ous >= 60_000_000))):
        raise ValueError('Unsupported duration anomaly')
    o,h,l,c,v,q,n,tb,tq = (a[:,i] for i in [1,2,3,4,5,7,8,9,10])
    valid = (np.minimum.reduce([o,h,l,c])>0)&(h>=np.maximum.reduce([o,l,c]))&(l<=np.minimum.reduce([o,h,c]))
    valid &= (v>=0)&(q>=0)&(n>=0)&(n==np.floor(n))&(tb>=0)&(tq>=0)&(tb<=v+1e-8)&(tq<=q+1e-6)
    times = ous//1000
    if len(np.unique(times)) != len(times):
        raise ValueError('Duplicate minute in archive; not selecting a version')
    meta = {'raw_rows':len(raw),'valid_rows':int(valid.sum()),'invalid_rows':int((~valid).sum()),
            'nonstandard_close_time_rows':int(anomalous.sum()),'microsecond_rows':int(us.sum()),
            'source_unsorted':bool(np.any(np.diff(times)<0))}
    return (times[valid],o[valid],c[valid]),meta

def plan(symbol):
    periods = pd.period_range(WARM.tz_convert('UTC').strftime('%Y-%m'), '2026-08',freq='M')
    jobs = [('monthly',str(p)) for p in periods]
    jobs += [('daily',f'2026-09-{d:02d}') for d in range(1,15)]
    return [(f'{symbol}-1m-{d}.zip',f'https://data.binance.vision/data/spot/{k}/klines/{symbol}/1m/{symbol}-1m-{d}.zip') for k,d in jobs]

def load(symbol, out: Path):
    def get(job):
        name,url = job
        for attempt in range(3):
            try:
                r=requests.get(url,timeout=(15,90)); r.raise_for_status()
                chk=requests.get(url+'.CHECKSUM',timeout=(15,30)); chk.raise_for_status()
                break
            except requests.RequestException:
                if attempt==2: raise
        digest=hashlib.sha256(r.content).hexdigest()
        matches=[line.split()[0].lower() for line in chk.text.splitlines() if name in line and re.match(r'^[0-9a-fA-F]{64}\s',line)]
        # Accommodate a single conventional sha256sum record, but verify its name.
        if digest not in matches:
            raise ValueError('Official CHECKSUM mismatch: '+name)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            members=[x for x in z.namelist() if x.endswith('.csv')]
            if len(members)!=1: raise ValueError('CSV member count')
            raw=pd.read_csv(z.open(members[0]),header=None)
        arrays,meta=parse(raw)
        meta.update(symbol=symbol,name=name,url=url,checksum_url=url+'.CHECKSUM',sha256=digest,
                    checksum_verified=True,downloaded_at=datetime.now(timezone.utc).isoformat())
        return arrays,meta
    chunks, manifests = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for arrays,meta in pool.map(get,plan(symbol)):
            chunks.append(arrays); manifests.append(meta)
            if len(manifests)%20==0: print(symbol,'verified archives',len(manifests),flush=True)
            (out/f'{symbol}_sources.json').write_text(json.dumps(manifests,indent=2))
    t,o,c = [np.concatenate([x[j] for x in chunks]) for j in range(3)]
    order=np.argsort(t); t,o,c=t[order],o[order],c[order]
    if np.any(np.diff(t)<=0): raise ValueError('Overlapping or conflicting archive timestamps')
    keep=(t>=ms(WARM))&(t<ms(END)); t,o,c=t[keep],o[keep],c[keep]
    for edge in [ms(WARM),ms(END)-MINUTE,ms(START)]:
        if edge not in t: raise ValueError('Requested coverage boundary missing')
    dates=pd.date_range(WARM,END,freq='D',inclusive='left')
    starts=np.array([ms(x) for x in dates]); closes=starts+DAY-MINUTE
    cp=np.searchsorted(t,closes); exact=(cp<len(t))&(t[np.minimum(cp,len(t)-1)]==closes)
    daily_close=np.full(len(dates),np.nan); daily_close[exact]=c[cp[exact]]
    ep=np.searchsorted(t,starts+MINUTE)
    if np.any(ep>=len(t)) or np.any(t[ep]>=starts+DAY): raise ValueError('Entire execution day unavailable')
    counts=np.searchsorted(t,starts+DAY)-np.searchsorted(t,starts)
    daily=pd.DataFrame({'close':daily_close,'execution_ms':t[ep],'execution_open':o[ep],
                        'delay_minutes':(t[ep]-starts-MINUTE)//MINUTE,'observed_minutes':counts},index=dates)
    d={'symbol':symbol,'expected_warmup_minutes':int((ms(END)-ms(WARM))//MINUTE),'observed_warmup_minutes':len(t),
       'expected_study_minutes':int((ms(END)-ms(START))//MINUTE),'observed_study_minutes':int((t>=ms(START)).sum()),
       'missing_daily_closes':int((~exact).sum()),'incomplete_days':int((counts<1440).sum()),
       'execution_delayed_days':int((daily.delay_minutes>0).sum()),'invalid_rows':sum(m['invalid_rows'] for m in manifests),
       'nonstandard_close_time_rows':sum(m['nonstandard_close_time_rows'] for m in manifests),'archives_verified':len(manifests)}
    (out/f'{symbol}_quality.json').write_text(json.dumps(d,indent=2))
    daily.to_csv(out/f'{symbol}_daily_inputs.csv',index_label='hong_kong_day')
    return (t,o,c),daily,d
