"""Public read-only research collection. No secrets, trades or synthetic data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import hashlib, io, json, re, time, zipfile
import pandas as pd
import requests
OUT=Path('derivative_inputs'); OUT.mkdir(exist_ok=True)
ROOT='https://data.binance.vision/data/futures/um/'

def fetch(job):
    sym,kind,period=job
    cadence='monthly' if kind=='fundingRate' else 'daily'
    name=f'{sym}-{kind}-{period}.zip';url=f'{ROOT}{cadence}/{kind}/{sym}/{name}'
    meta={'symbol':sym,'kind':kind,'period':period,'url':url,'checksum_url':url+'.CHECKSUM','status':'pending'}
    for attempt in range(2):
        try:
            r=requests.get(url,timeout=(10,30));meta['http_status']=r.status_code
            if r.status_code==404:meta['status']='missing_archive';return None,meta
            r.raise_for_status();chk=requests.get(url+'.CHECKSUM',timeout=(10,20));chk.raise_for_status()
            digest=hashlib.sha256(r.content).hexdigest()
            if not any(line.split()[0].lower()==digest and name in line for line in chk.text.splitlines() if re.match(r'^[0-9a-fA-F]{64}\s',line)):
                raise ValueError('CHECKSUM mismatch')
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                names=[n for n in z.namelist() if n.endswith('.csv')]
                if len(names)!=1:raise ValueError('CSV member count')
                data=pd.read_csv(z.open(names[0]))
            meta.update(status='verified',sha256=digest,rows=len(data),columns=list(data),downloaded_at=datetime.now(timezone.utc).isoformat())
            return data,meta
        except (requests.RequestException,ValueError,zipfile.BadZipFile) as e:
            if attempt==1:meta.update(status='failed',error=str(e)[:300]);return None,meta
            time.sleep(.25)

def unique(frame,key):
    # Exact duplicates are recorded separately; conflicts are never arbitrarily chosen.
    before=len(frame);frame=frame.drop_duplicates()
    if frame[key].duplicated().any():raise ValueError('Conflicting repeated timestamps: '+key)
    return frame.sort_values(key),before-len(frame)

def collect():
    jobs=[]
    for s in ['BTCUSDT','ETHUSDT']:
        jobs += [(s,'fundingRate',str(p)) for p in pd.period_range('2023-12','2026-09',freq='M')]
        jobs += [(s,'metrics',str(d.date())) for d in pd.date_range('2023-12-01','2026-09-14')]
    manifests=[];parts={(s,k):[] for s in ['BTCUSDT','ETHUSDT'] for k in ['fundingRate','metrics']}
    # Small schema/endpoint probe first. Failure is saved, not silently swapped for simulated data.
    for job in [('BTCUSDT','fundingRate','2024-01'),('BTCUSDT','metrics','2024-01-01')]:
        data,meta=fetch(job);print('PROBE',json.dumps(meta),flush=True)
        if data is not None:print(data.head(2).to_json(orient='records'),flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for data,meta in pool.map(fetch,jobs):
            manifests.append(meta)
            if data is not None:parts[(meta['symbol'],meta['kind'])].append(data)
            if len(manifests)%200==0:
                print('Archives checked',len(manifests),flush=True)
                (OUT/'archive_manifest.json').write_text(json.dumps(manifests,indent=2))
    (OUT/'archive_manifest.json').write_text(json.dumps(manifests,indent=2))
    quality=[]
    for (sym,kind),chunks in parts.items():
        if not chunks:quality.append({'symbol':sym,'kind':kind,'status':'NO_DATA'});continue
        frame=pd.concat(chunks,ignore_index=True)
        key='calc_time' if kind=='fundingRate' else 'create_time'
        if key not in frame:raise ValueError('Unexpected schema '+str(frame.columns))
        frame,dups=unique(frame,key)
        if kind=='metrics':
            stamp=pd.to_datetime(frame[key],utc=True,errors='raise')
            if 'symbol' in frame and not frame.symbol.eq(sym).all():raise ValueError('Symbol mismatch')
            for c in frame.columns.difference([key,'symbol']):frame[c]=pd.to_numeric(frame[c],errors='raise')
        else:
            stamp=pd.to_datetime(pd.to_numeric(frame[key]),unit='ms',utc=True,errors='raise')
            for c in frame.columns:frame[c]=pd.to_numeric(frame[c],errors='raise')
        frame.insert(0,'timestamp_utc',stamp.astype(str))
        frame.to_csv(OUT/f'{sym}_{kind}.csv.gz',index=False,compression={'method':'gzip','mtime':0})
        quality.append({'symbol':sym,'kind':kind,'rows':len(frame),'first':str(stamp.min()),'last':str(stamp.max()),
            'identical_duplicates_removed':dups,'na_by_column':frame.isna().sum().to_dict()})
    # Settled-rate tail: archive month may not exist yet. Public API, never testnet.
    tails=[]
    for sym in ['BTCUSDT','ETHUSDT']:
        url='https://fapi.binance.com/fapi/v1/fundingRate'
        params={'symbol':sym,'startTime':1788220800000,'endTime':1789430399999,'limit':1000}
        # Dates are recomputed explicitly to prevent a mistyped epoch being accepted.
        params['startTime']=int(pd.Timestamp('2026-09-01',tz='UTC').timestamp()*1000)
        params['endTime']=int(pd.Timestamp('2026-09-15',tz='UTC').timestamp()*1000)-1
        try:
            r=requests.get(url,params=params,timeout=(10,20));info={'symbol':sym,'url':r.url,'http_status':r.status_code}
            r.raise_for_status();value=r.json()
            if not isinstance(value,list):raise ValueError('Expected list')
            (OUT/f'{sym}_funding_tail.json').write_text(json.dumps(value,indent=2))
            info.update(status='downloaded',rows=len(value),sha256=hashlib.sha256(r.content).hexdigest())
        except Exception as e:info={'symbol':sym,'url':url,'status':'unavailable','error':str(e)[:300]}
        tails.append(info)
    (OUT/'funding_tail_status.json').write_text(json.dumps(tails,indent=2))
    (OUT/'quality.json').write_text(json.dumps(quality,indent=2))
    probe_external()
    hashes={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file()}
    (OUT/'MANIFEST.json').write_text(json.dumps({'files':hashes,'collector_commit':__import__('os').getenv('GITHUB_SHA'),
       'complete_archive_requests':len(manifests),'verified':sum(x['status']=='verified' for x in manifests),
       'missing':sum(x['status']=='missing_archive' for x in manifests),'failed':sum(x['status']=='failed' for x in manifests),
       'market_data_simulated':False,'research_model_executed':False},indent=2))

def probe_external():
    rows=[]
    for date in ['20240110','20250110','20260910']:
        url='https://api.gdeltproject.org/api/v2/doc/doc'
        params={'query':'(bitcoin OR ethereum) sourcelang:english','mode':'artlist','format':'json','maxrecords':10,
                'startdatetime':date+'000000','enddatetime':date+'235959'}
        row={'source':'GDELT','date':date}
        try:
            r=requests.get(url,params=params,timeout=(10,25));row.update(url=r.url,http_status=r.status_code)
            r.raise_for_status();j=r.json();arts=j.get('articles',[])
            row.update(returned_records=len(arts),sample_seen_dates=[a.get('seendate') for a in arts],
                       complete_versioned_corpus=False)
            (OUT/f'news_probe_{date}.json').write_text(json.dumps(j,indent=2))
        except Exception as e:row.update(status='probe_failed',error=str(e)[:300])
        rows.append(row)
    for coin in ['bitcoin','ethereum']:
        url=f'https://farside.co.uk/{coin}-etf-flow-all-data/'
        row={'source':'Farside','coin':coin,'url':url,'historical_first_publication_verified':False}
        try:
            r=requests.get(url,timeout=(10,25));row.update(http_status=r.status_code);r.raise_for_status()
            tables=pd.read_html(io.StringIO(r.text))
            table=max(tables,key=len);table.to_csv(OUT/f'{coin}_etf_table_UNVERIFIED_VINTAGE.csv',index=False)
            row.update(table_rows=len(table),columns=[str(c) for c in table.columns],usable_as_point_in_time_predictor=False)
        except Exception as e:row.update(status='probe_failed',error=str(e)[:300])
        rows.append(row)
    (OUT/'external_coverage.json').write_text(json.dumps(rows,indent=2))

if __name__=='__main__':collect()
