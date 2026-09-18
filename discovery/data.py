"""Official minute data -> causal hourly features; gaps never become tradeable prices."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,io,json,re,zipfile
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import requests
TZ='Asia/Hong_Kong'
START=pd.Timestamp('2021-01-01',tz=TZ)
TRAIN_END=pd.Timestamp('2024-01-01',tz=TZ)
END=pd.Timestamp('2026-09-15',tz=TZ)
WARM=pd.Timestamp('2020-10-01',tz=TZ)
MIN=60_000; HOUR=60*MIN

def ms(t): return int(pd.Timestamp(t).value//1_000_000)

def parse(raw):
    if raw.shape[1]!=12 or raw.empty: raise ValueError('Expected 12-column nonempty archive')
    a=raw.to_numpy(dtype=np.float64)
    if not np.isfinite(a).all(): raise ValueError('Non-finite input')
    ot=raw.iloc[:,0].to_numpy(np.int64); ct=raw.iloc[:,6].to_numpy(np.int64)
    us=ot>=100_000_000_000_000
    if np.any(us!=(ct>=100_000_000_000_000)): raise ValueError('Mixed timestamp units')
    ous=np.where(us,ot,ot*1000); cus=np.where(us,ct,ct*1000)
    if np.any(ous%60_000_000): raise ValueError('Minute boundary error')
    anomaly=~np.isin(cus-ous,[59_999_000,59_999_999])
    if np.any(anomaly&(us|(cus-ous>=60_000_000))): raise ValueError('Unsupported duration anomaly')
    o,h,l,c,v,q,n,tb,tq=(a[:,i] for i in [1,2,3,4,5,7,8,9,10])
    valid=(np.minimum.reduce([o,h,l,c])>0)&(h>=np.maximum.reduce([o,l,c]))&(l<=np.minimum.reduce([o,h,c]))
    valid&=(v>=0)&(q>=0)&(n>=0)&(n==np.floor(n))&(tb>=0)&(tq>=0)&(tb<=v+1e-8)&(tq<=q+1e-6)
    t=ous//1000
    if len(np.unique(t))!=len(t): raise ValueError('Duplicate minute; requires manual provenance reconciliation')
    meta={'rows':len(raw),'invalid_rows':int((~valid).sum()),'legacy_close_metadata_rows':int(anomaly.sum()),
          'microsecond_rows':int(us.sum()),'unsorted':bool(np.any(np.diff(t)<0))}
    return pd.DataFrame({'t':t[valid],'open':o[valid],'high':h[valid],'low':l[valid],'close':c[valid],
        'volume':v[valid],'quote_volume':q[valid],'taker_quote':tq[valid]}),meta

def archive_plan(symbol,end):
    final=(end-pd.Timedelta(minutes=1)).tz_convert('UTC')
    periods=pd.period_range(WARM.tz_convert('UTC').strftime('%Y-%m'),final.strftime('%Y-%m'),freq='M')
    jobs=[]
    for period in periods:
        if period.year==2026 and period.month==9:
            specs=[('daily',f'2026-09-{d:02d}') for d in range(1,final.day+1)]
        else: specs=[('monthly',str(period))]
        for kind,date in specs:
            name=f'{symbol}-1m-{date}.zip'
            jobs.append((name,f'https://data.binance.vision/data/spot/{kind}/klines/{symbol}/1m/{name}'))
    return jobs

def load(symbol,end,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    def download(job):
        name,url=job
        for attempt in range(3):
            try:
                r=requests.get(url,timeout=(15,90));r.raise_for_status()
                chk=requests.get(url+'.CHECKSUM',timeout=(15,30));chk.raise_for_status();break
            except requests.RequestException:
                if attempt==2: raise
        digest=hashlib.sha256(r.content).hexdigest()
        checks=[x.split()[0].lower() for x in chk.text.splitlines() if name in x and re.match(r'^[0-9a-fA-F]{64}\s',x)]
        if digest not in checks: raise ValueError('CHECKSUM mismatch: '+name)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            members=[p for p in z.namelist() if p.endswith('.csv')]
            if len(members)!=1: raise ValueError('CSV member count')
            frame,meta=parse(pd.read_csv(z.open(members[0]),header=None))
        meta.update(name=name,url=url,sha256=digest,checksum_verified=True,
                    downloaded_at=datetime.now(timezone.utc).isoformat())
        return frame,meta
    chunks=[];manifest=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for frame,meta in pool.map(download,archive_plan(symbol,end)):
            chunks.append(frame);manifest.append(meta)
    frame=pd.concat(chunks,ignore_index=True).sort_values('t')
    if frame.t.duplicated().any(): raise ValueError('Overlapping archives')
    frame=frame[(frame.t>=ms(WARM))&(frame.t<ms(end))].copy()
    for edge in [ms(WARM),ms(START),ms(end)-MIN]:
        if not np.any(frame.t.to_numpy()==edge): raise ValueError('Missing coverage endpoint')
    frame.index=pd.to_datetime(frame.t,unit='ms',utc=True).dt.tz_convert(TZ)
    quality={'symbol':symbol,'expected_study_minutes':int((ms(end)-ms(START))//MIN),
        'observed_study_minutes':int((frame.t>=ms(START)).sum()),'verified_archives':len(manifest),
        'invalid_rows':sum(m['invalid_rows'] for m in manifest),
        'legacy_metadata_rows':sum(m['legacy_close_metadata_rows'] for m in manifest)}
    (out/f'{symbol}_sources.json').write_text(json.dumps(manifest,indent=2))
    (out/f'{symbol}_quality.json').write_text(json.dumps(quality,indent=2))
    return frame,quality

def features(minute):
    group=minute.resample('1h',label='right',closed='left')
    f=group.agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum','quote_volume':'sum','taker_quote':'sum'})
    f['minutes']=group['t'].count()
    f.loc[f.minutes!=60,['open','high','low','close','volume','quote_volume','taker_quote']]=np.nan
    f['r1']=f.close/f.open-1
    for n in [4,24]:
        f[f'r{n}']=(f.close/f.open.shift(n-1)-1).where(f.minutes.eq(60).rolling(n).sum()==n)
    for n in [168,720]: f[f'r{n}']=f.close/f.close.shift(n)-1
    f['vol7']=np.log(f.close/f.close.shift()).rolling(168,min_periods=168).std()
    f['shock4']=f.r4/(f.vol7.shift()*2)
    f['vol24']=np.log(f.close/f.close.shift()).rolling(24,min_periods=24).std()
    f['vol_ratio']=f.vol24/f.vol7.shift()
    f['volume_ratio']=f.quote_volume/f.quote_volume.rolling(168,min_periods=168).median().shift()
    f['buy_imbalance']=2*f.taker_quote/f.quote_volume-1
    f['close_location']=(f.close-f.low)/(f.high-f.low)
    hi=f.high.rolling(24,min_periods=24).max().shift();lo=f.low.rolling(24,min_periods=24).min().shift()
    f['range_position']=(f.close-lo)/(hi-lo)
    f['breakout7']=f.close/f.high.rolling(168,min_periods=168).max().shift()-1
    vw=f.quote_volume.rolling(24,min_periods=24).sum()/f.volume.rolling(24,min_periods=24).sum()
    f['vwap_distance']=f.close/vw-1
    t=minute.t.to_numpy();p=minute.open.to_numpy();decision=np.array([ms(x) for x in f.index])
    idx=np.searchsorted(t,decision+MIN);valid=idx<len(t);safe=np.minimum(idx,len(t)-1)
    valid&=t[safe]<decision+HOUR
    f['execution_ms']=np.where(valid,t[safe],np.nan)
    f['execution_open']=np.where(valid,p[safe],np.nan)
    f['execution_delay_min']=np.where(valid,(t[safe]-decision-MIN)//MIN,np.nan)
    return f.replace([np.inf,-np.inf],np.nan)

def add_cross(frames):
    for coin,f in frames.items():
        other='ETHUSDT' if coin=='BTCUSDT' else 'BTCUSDT'
        f['other_r24']=frames[other].r24.reindex(f.index)
        f['relative24']=f.r24-f.other_r24
    return frames
