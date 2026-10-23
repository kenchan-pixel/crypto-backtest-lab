"""Commission a current source->feature->opportunity receipt from an immutable
connected-Binance snapshot already persisted in GitHub.

No futures HTTP endpoint, account endpoint, order endpoint or paper fill is used.
The snapshot's conservative first_seen timestamp is the observation boundary.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

import pandas as pd

from derivatives.features import build_derivatives
from .features import states, candidates_at
from .freshness import validate_derivative_freshness
from .live_pipeline import fetch_spot, archive_warmup, merge_metrics, funding_features, sha_bytes
from .live_sources import normalize_spot_pair, normalize_metric_bundle
from .macro_first_seen import normalize_capture
from .model import load

FILES={
    'open_interest':'open_interest.json',
    'top_accounts':'top_accounts.json',
    'top_positions':'top_positions.json',
    'all_accounts':'global_accounts.json',
    'taker':'taker.json',
    'funding':'funding.json',
}
REQ_STATE=['trend_30d','trend_7d','vol_state','cross_asset_state','funding_state','oi_state','positioning_state']


def git_blob_sha1(data:bytes)->str:
    return hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()


def load_snapshot(snapshot_dir):
    root=Path(snapshot_dir);manifest=json.loads((root/'manifest.json').read_text())
    if manifest.get('schema')!='connected-binance-native-tail-v1':raise ValueError('Unexpected connected snapshot schema')
    if not manifest.get('read_only_public_market_data_only') or manifest.get('order_or_account_endpoints_used'):
        raise ValueError('Snapshot is not certified read-only public market data')
    observed=pd.Timestamp(manifest['conservative_first_seen_at_utc'])
    if observed.tzinfo is None:raise ValueError('Snapshot first_seen must be timezone-aware')
    observed=observed.tz_convert('UTC')
    rows={};blob_checks={}
    source_map={'open_interest':'open_interest','top_accounts':'top_accounts','top_positions':'top_positions',
                'all_accounts':'global_accounts','taker':'taker','funding':'funding'}
    for key,name in FILES.items():
        data=(root/name).read_bytes();rows[key]=json.loads(data)
        source=manifest['sources'][source_map[key]]
        actual=git_blob_sha1(data);expected=source['git_blob_sha1']
        if actual!=expected:raise ValueError(f'Immutable source blob mismatch: {key}')
        blob_checks[key]={'git_blob_sha1':actual,'sha256':sha_bytes(data),'rows':len(rows[key])}
    return manifest,observed,rows,blob_checks


def run(snapshot_dir,macro_capture,out_path):
    manifest,observed,deriv,blob_checks=load_snapshot(snapshot_dir)
    eth_raw,eth_bytes,eth_url=fetch_spot('ETHUSDT');btc_raw,btc_bytes,btc_url=fetch_spot('BTCUSDT')
    eth,btc=normalize_spot_pair(eth_raw,btc_raw,observed,min_completed_hours=721)
    fresh=validate_derivative_freshness(symbol='ETHUSDT',observed_at=observed,
        open_interest=deriv['open_interest'],top_accounts=deriv['top_accounts'],top_positions=deriv['top_positions'],
        all_accounts=deriv['all_accounts'],taker=deriv['taker'],funding=deriv['funding'])
    live_metric=normalize_metric_bundle(symbol='ETHUSDT',period='5m',open_interest=deriv['open_interest'],
        top_accounts=deriv['top_accounts'],top_positions=deriv['top_positions'],all_accounts=deriv['all_accounts'],taker=deriv['taker'])
    archive,archive_hashes=archive_warmup(observed.to_pydatetime())
    expected=pd.DatetimeIndex(pd.to_datetime(manifest['archive_overlap_expected']['timestamps_utc'],utc=True))
    actual_overlap=archive.index.intersection(live_metric.index)
    if not expected.isin(actual_overlap).all():raise ValueError('Expected checksum-bound archive/live overlap timestamps missing')
    metrics,max_gap,overlap=merge_metrics(archive,live_metric)
    if overlap<len(expected):raise ValueError('Insufficient archive/live overlap rows')
    fund=funding_features(deriv['funding'])
    D,_=build_derivatives(eth.index,(fund,metrics),lag_hours=1)
    regimes=states(eth,btc,D)
    cap=json.loads(Path(macro_capture).read_text());macro_norm=normalize_capture(cap)
    macro=[{'usable_at':e['usable_at_utc'],'indicator':e['indicator'],'sign':e['sign']}
           for e in macro_norm['events'] if e['forward_eligible'] and pd.Timestamp(e['usable_at_utc'])<=observed]
    model=load('forward_paper/model.json');cut=regimes.index[-1];current=regimes.loc[cut]
    if any(str(current[c])=='unknown' for c in REQ_STATE):raise ValueError('Current regime has unknown frozen-model state')
    needed=['funding_per_hour','oi_logchange_24h','top_position_ratio']
    if any(pd.isna(D.loc[cut,c]) for c in needed):raise ValueError('Required derivative feature is null at cutoff')
    candidates=candidates_at(regimes,macro,cut,model)
    recent=[]
    for c in regimes.index[-25:]:recent.extend(candidates_at(regimes,macro,c,model))
    overlap_values={}
    for t in expected:
        overlap_values[t.isoformat()]={c:{'archive':float(archive.loc[t,c]),'connected':float(live_metric.loc[t,c])} for c in live_metric.columns if c in archive.columns}
    receipt={
      'schema':'eth-forward-persisted-pipeline-receipt-v1','passed':True,
      'scope':'First current causal source-to-feature-to-opportunity receipt from immutable connected Binance read-only input. No fill/performance and no gate promotion.',
      'snapshot_manifest':str(Path(snapshot_dir)/'manifest.json'),'snapshot_first_seen_at_utc':observed.isoformat(),
      'snapshot_blob_checks':blob_checks,
      'spot_latest_complete_utc':cut.isoformat(),'spot_completed_aligned_hours':len(eth),
      'spot_latest_age_minutes':eth.attrs['latest_complete_age_minutes'],
      'spot_response_sha256':{'ETHUSDT':sha_bytes(eth_bytes),'BTCUSDT':sha_bytes(btc_bytes)},
      'spot_urls':{'ETHUSDT':eth_url,'BTCUSDT':btc_url},
      'derivative_freshness':fresh,'archive_verified_days':len(archive_hashes),'archive_day_sha256':archive_hashes,
      'archive_live_overlap_rows':overlap,'expected_overlap_rows':len(expected),'expected_overlap_value_checks':overlap_values,
      'max_merged_metric_gap_minutes':max_gap,
      'derivative_feature_non_null_at_cut':{c:bool(pd.notna(D.loc[cut,c])) for c in needed},
      'current_regime':{c:str(current[c]) for c in REQ_STATE},'eth_30d_return':float(current['return_30d']),
      'macro_capture_sha256':hashlib.sha256(Path(macro_capture).read_bytes()).hexdigest(),
      'macro_forward_eligible_events_at_observation':len(macro),
      'current_cut_candidate_count':len(candidates),'current_cut_threshold_count':sum(bool(x['passes_frozen_threshold']) for x in candidates),
      'recent_24h_candidate_count':len(recent),'recent_24h_threshold_count':sum(bool(x['passes_frozen_threshold']) for x in recent),
      'current_candidates':candidates,'model_sha256':hashlib.sha256(Path('forward_paper/model.json').read_bytes()).hexdigest(),
      'causal_guards':['snapshot conservative first_seen boundary','completed spot bars only','native 5m metrics','checksum-bound archive overlap','1h backward-only derivative availability lag','actual settled funding intervals','late macro bootstrap excluded','six-hour confirmation fully observed'],
      'historical_outcome_columns_used':False,'order_account_endpoints_used':False,'paper_trades_created':0,'performance_started':False,
      'gate_effect':'Receipt 1 of 2 required current full-pipeline observations. live_feature_parity/source_freshness remain false until an independently timed second full connected snapshot also passes.'
    }
    Path(out_path).write_text(json.dumps(receipt,indent=2,allow_nan=False));print(json.dumps(receipt,indent=2,allow_nan=False));return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--snapshot-dir',required=True);p.add_argument('--macro-capture',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    run(a.snapshot_dir,a.macro_capture,a.out)
