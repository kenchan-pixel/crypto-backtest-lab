"""Current read-only ETH source -> feature -> opportunity commissioning pipeline.

This is commissioning evidence only. It never creates a paper fill, changes account
state, or calls any account/order endpoint. Historical outcomes/execution prices are
not inputs.
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, io, json, math, re, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from derivatives.features import build_derivatives
from .features import states, candidates_at
from .freshness import validate_derivative_freshness
from .live_sources import normalize_spot_pair, normalize_metric_bundle, normalize_funding_history
from .macro_first_seen import normalize_capture
from .model import load

SPOT='https://data-api.binance.vision/api/v3/klines'
FAPI='https://fapi.binance.com'
ARCHIVE='https://data.binance.vision/data/futures/um/daily/metrics/ETHUSDT'
UA={'User-Agent':'crypto-backtest-lab-forward-paper/1'}
REQ_COLS=['sum_open_interest','sum_open_interest_value','count_toptrader_long_short_ratio',
          'sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']


def sha_bytes(b:bytes)->str:return hashlib.sha256(b).hexdigest()

def get_json(url,params=None):
    r=requests.get(url,params=params,headers=UA,timeout=(10,30));r.raise_for_status()
    value=r.json()
    if not isinstance(value,list):raise ValueError('Expected list from '+url)
    return value,r.content,r.url

def fetch_spot(symbol):return get_json(SPOT,{'symbol':symbol,'interval':'1h','limit':1000})

def fetch_live_derivatives():
    specs={
      'open_interest':('/futures/data/openInterestHist',{'symbol':'ETHUSDT','period':'5m','limit':500}),
      'top_accounts':('/futures/data/topLongShortAccountRatio',{'symbol':'ETHUSDT','period':'5m','limit':500}),
      'top_positions':('/futures/data/topLongShortPositionRatio',{'symbol':'ETHUSDT','period':'5m','limit':500}),
      'all_accounts':('/futures/data/globalLongShortAccountRatio',{'symbol':'ETHUSDT','period':'5m','limit':500}),
      'taker':('/futures/data/takerlongshortRatio',{'symbol':'ETHUSDT','period':'5m','limit':500}),
      'funding':('/fapi/v1/fundingRate',{'symbol':'ETHUSDT','limit':1000}),
    }
    out={};raw={};urls={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        fut={ex.submit(get_json,FAPI+p,q):k for k,(p,q) in specs.items()}
        for f,k in [(f,k) for f,k in fut.items()]:
            rows,b,url=f.result();out[k]=rows;raw[k]=sha_bytes(b);urls[k]=url
    return out,raw,urls

def fetch_archive_day(day):
    name=f'ETHUSDT-metrics-{day}.zip';url=f'{ARCHIVE}/{name}'
    r=requests.get(url,headers=UA,timeout=(10,30));r.raise_for_status()
    chk=requests.get(url+'.CHECKSUM',headers=UA,timeout=(10,20));chk.raise_for_status()
    digest=sha_bytes(r.content)
    if not any(line.split()[0].lower()==digest and name in line for line in chk.text.splitlines() if re.match(r'^[0-9a-fA-F]{64}\s',line)):
        raise ValueError('Archive CHECKSUM mismatch '+day)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        if len(names)!=1:raise ValueError('Unexpected archive members '+day)
        frame=pd.read_csv(z.open(names[0]))
    if 'create_time' not in frame or any(c not in frame for c in REQ_COLS):raise ValueError('Archive schema mismatch '+day)
    idx=pd.to_datetime(frame.create_time,utc=True,errors='raise')
    out=frame[REQ_COLS].apply(pd.to_numeric,errors='raise');out.index=idx
    if not out.index.is_unique:raise ValueError('Archive duplicate metric time '+day)
    return day,out,digest

def archive_warmup(observed):
    # 36 completed UTC days provide >720 hourly warmup with overlap into the 500x5m live tail.
    today=observed.date();days=[str(today-timedelta(days=d)) for d in range(36,0,-1)]
    parts=[];hashes={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for day,frame,digest in ex.map(fetch_archive_day,days):parts.append(frame);hashes[day]=digest
    out=pd.concat(parts).sort_index()
    if out.index.duplicated().any():
        dup=out[out.index.duplicated(False)]
        for _,g in dup.groupby(level=0):
            if len(g.drop_duplicates())!=1:raise ValueError('Conflicting archive overlap')
        out=out[~out.index.duplicated(keep='last')]
    return out,hashes

def merge_metrics(archive,live):
    overlap=archive.index.intersection(live.index)
    if len(overlap):
        a=archive.loc[overlap,REQ_COLS].astype(float);b=live.loc[overlap,REQ_COLS].astype(float)
        if not np.allclose(a.to_numpy(),b.to_numpy(),rtol=1e-10,atol=1e-12,equal_nan=False):
            raise ValueError('Archive/live 5m overlap value mismatch')
    first_live=live.index.min();left=archive.loc[archive.index<first_live,REQ_COLS]
    merged=pd.concat([left,live[REQ_COLS]]).sort_index()
    if not merged.index.is_unique:raise ValueError('Merged metric index duplicate')
    gap=merged.index.to_series().diff().dropna().max()
    if gap>pd.Timedelta(minutes=10):raise ValueError('Metric warmup/live gap too large')
    return merged,float(gap/pd.Timedelta(minutes=1)),len(overlap)

def funding_features(rows):
    f=normalize_funding_history('ETHUSDT',rows)
    interval=pd.to_numeric(f.funding_interval_hours)
    rate=(pd.to_numeric(f.last_funding_rate)/interval).where(interval>0)
    return pd.DataFrame({'funding_per_hour':rate,'funding_mean3':rate.rolling(3).mean(),
                         'funding_change3':rate-rate.shift(3)},index=f.index)

def run(macro_capture,out_path):
    observed=datetime.now(timezone.utc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        e1=ex.submit(fetch_spot,'ETHUSDT');e2=ex.submit(fetch_spot,'BTCUSDT');e3=ex.submit(fetch_live_derivatives)
        eth_raw,eth_bytes,eth_url=e1.result();btc_raw,btc_bytes,btc_url=e2.result();deriv,deriv_hashes,deriv_urls=e3.result()
    eth,btc=normalize_spot_pair(eth_raw,btc_raw,observed,min_completed_hours=721)
    fresh=validate_derivative_freshness(symbol='ETHUSDT',observed_at=observed,
        open_interest=deriv['open_interest'],top_accounts=deriv['top_accounts'],top_positions=deriv['top_positions'],
        all_accounts=deriv['all_accounts'],taker=deriv['taker'],funding=deriv['funding'])
    live_metric=normalize_metric_bundle(symbol='ETHUSDT',period='5m',open_interest=deriv['open_interest'],
        top_accounts=deriv['top_accounts'],top_positions=deriv['top_positions'],all_accounts=deriv['all_accounts'],taker=deriv['taker'])
    archive,archive_hashes=archive_warmup(observed)
    metrics,max_gap,overlap=merge_metrics(archive,live_metric)
    fund=funding_features(deriv['funding'])
    D,_=build_derivatives(eth.index,(fund,metrics),lag_hours=1)
    regimes=states(eth,btc,D)
    cap=json.loads(Path(macro_capture).read_text());macro_norm=normalize_capture(cap)
    macro=[{'usable_at':e['usable_at_utc'],'indicator':e['indicator'],'sign':e['sign']}
           for e in macro_norm['events'] if e['forward_eligible']]
    model=load('forward_paper/model.json');cut=regimes.index[-1]
    current=regimes.loc[cut]
    required_state=['trend_30d','trend_7d','vol_state','cross_asset_state','funding_state','oi_state','positioning_state']
    if any(str(current[c])=='unknown' for c in required_state):raise ValueError('Current regime has unknown frozen-model state')
    candidates=candidates_at(regimes,macro,cut,model)
    recent=[]
    for c in regimes.index[-25:]:
        recent.extend(candidates_at(regimes,macro,c,model))
    receipt={
      'schema':'eth-forward-live-pipeline-receipt-v1','passed':True,
      'scope':'Current causal source-to-feature-to-opportunity commissioning evidence only; not a fill or performance result.',
      'observed_at_utc':observed.isoformat(),'latest_complete_spot_utc':cut.isoformat(),
      'spot_completed_aligned_hours':len(eth),'spot_latest_age_minutes':eth.attrs['latest_complete_age_minutes'],
      'spot_response_sha256':{'ETHUSDT':sha_bytes(eth_bytes),'BTCUSDT':sha_bytes(btc_bytes)},
      'spot_urls':{'ETHUSDT':eth_url,'BTCUSDT':btc_url},
      'derivative_freshness':fresh,'derivative_live_response_sha256':deriv_hashes,'derivative_urls':deriv_urls,
      'archive_verified_days':len(archive_hashes),'archive_day_sha256':archive_hashes,
      'archive_live_overlap_rows':overlap,'max_merged_metric_gap_minutes':max_gap,
      'derivative_feature_non_null_at_cut':{c:bool(pd.notna(D.loc[cut,c])) for c in ['funding_per_hour','oi_logchange_24h','top_position_ratio']},
      'current_regime':{c:str(current[c]) for c in required_state},
      'eth_30d_return':float(current['return_30d']),'macro_capture_sha256':hashlib.sha256(Path(macro_capture).read_bytes()).hexdigest(),
      'macro_forward_eligible_events':len(macro),'current_cut_candidate_count':len(candidates),
      'current_cut_threshold_count':sum(bool(x['passes_frozen_threshold']) for x in candidates),
      'recent_24h_candidate_count':len(recent),'recent_24h_threshold_count':sum(bool(x['passes_frozen_threshold']) for x in recent),
      'current_candidates':candidates,'model_sha256':hashlib.sha256(Path('forward_paper/model.json').read_bytes()).hexdigest(),
      'causal_guards':['completed spot bars only','native 5m metrics','1h backward-only derivative availability lag','actual settled funding intervals','late macro bootstrap excluded','six-hour confirmation fully observed'],
      'historical_outcome_columns_used':False,'order_account_endpoints_used':False,
      'paper_trades_created':0,'performance_started':False,
      'gate_effect':'First current live end-to-end snapshot only; do not promote live_feature_parity/source_freshness until an independent repeated live pipeline snapshot also passes.'
    }
    Path(out_path).write_text(json.dumps(receipt,indent=2,allow_nan=False));print(json.dumps(receipt,indent=2,allow_nan=False))
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--macro-capture',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    run(a.macro_capture,a.out)
