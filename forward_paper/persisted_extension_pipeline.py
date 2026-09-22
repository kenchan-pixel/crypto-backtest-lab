"""Commission one current causal receipt by extending the earlier immutable
connected-Binance full tail with a newly observed fresh read-only extension.

The earlier tail supplies checksum-bound archive overlap/warmup. The fresh
extension supplies the current observation boundary. Exact overlapping raw rows
must agree before they can be combined. No order/account endpoint or paper fill.
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
from .persisted_pipeline import load_snapshot

REQ_STATE=['trend_30d','trend_7d','vol_state','cross_asset_state','funding_state','oi_state','positioning_state']
METRIC_KEYS=['open_interest','top_accounts','top_positions','all_accounts','taker']


def _time_key(key,row):
    return int(row['fundingTime'] if key=='funding' else row['timestamp'])


def merge_raw_exact(base, fresh):
    """Merge snapshots without rewriting values; any overlapping disagreement fails."""
    merged={};overlaps={}
    for key in [*METRIC_KEYS,'funding']:
        old={_time_key(key,r):r for r in base[key]}
        overlap=0
        for r in fresh[key]:
            t=_time_key(key,r)
            if t in old:
                overlap+=1
                if old[t]!=r:
                    raise ValueError(f'Conflicting base/fresh raw overlap: {key} {t}')
            else:
                old[t]=r
        merged[key]=[old[t] for t in sorted(old)]
        overlaps[key]=overlap
    return merged,overlaps


def run(base_dir,fresh_dir,macro_capture,out_path):
    base_manifest,base_seen,base_rows,base_checks=load_snapshot(base_dir)
    fresh_manifest,observed,fresh_rows,fresh_checks=load_snapshot(fresh_dir)
    if fresh_manifest.get('capture_mode')!='fresh_incremental_extension':
        raise ValueError('Fresh snapshot is not certified as an incremental extension')
    if fresh_manifest.get('base_snapshot_dir')!=str(Path(base_dir)):
        raise ValueError('Fresh snapshot points to a different immutable base')
    deriv,overlap=merge_raw_exact(base_rows,fresh_rows)
    minimum=int(fresh_manifest['base_extension_overlap_expected']['minimum_common_5m_rows'])
    if any(overlap[k]<minimum for k in METRIC_KEYS):
        raise ValueError(f'Insufficient exact base/fresh 5m overlap: {overlap}')
    if overlap['funding']<3:
        raise ValueError('Insufficient exact base/fresh funding overlap')

    # Fresh conservative first_seen is the causal observation boundary.
    fresh=validate_derivative_freshness(symbol='ETHUSDT',observed_at=observed,
        open_interest=deriv['open_interest'],top_accounts=deriv['top_accounts'],top_positions=deriv['top_positions'],
        all_accounts=deriv['all_accounts'],taker=deriv['taker'],funding=deriv['funding'])
    live_metric=normalize_metric_bundle(symbol='ETHUSDT',period='5m',open_interest=deriv['open_interest'],
        top_accounts=deriv['top_accounts'],top_positions=deriv['top_positions'],all_accounts=deriv['all_accounts'],taker=deriv['taker'])

    # Keep the already-verifiable archive boundary (Sep-20) and bridge forward
    # through the immutable base + fresh extension. Do not depend on a same-day
    # daily archive being published minutes after UTC midnight.
    archive,archive_hashes=archive_warmup(base_seen.to_pydatetime())
    expected=pd.DatetimeIndex(pd.to_datetime(base_manifest['archive_overlap_expected']['timestamps_utc'],utc=True))
    actual_overlap=archive.index.intersection(live_metric.index)
    if not expected.isin(actual_overlap).all():
        raise ValueError('Expected checksum-bound archive/live overlap timestamps missing')
    metrics,max_gap,archive_overlap=merge_metrics(archive,live_metric)
    fund=funding_features(deriv['funding'])

    eth_raw,eth_bytes,eth_url=fetch_spot('ETHUSDT');btc_raw,btc_bytes,btc_url=fetch_spot('BTCUSDT')
    eth,btc=normalize_spot_pair(eth_raw,btc_raw,observed,min_completed_hours=721)
    D,_=build_derivatives(eth.index,(fund,metrics),lag_hours=1)
    regimes=states(eth,btc,D)
    cap=json.loads(Path(macro_capture).read_text());macro_norm=normalize_capture(cap)
    macro=[{'usable_at':e['usable_at_utc'],'indicator':e['indicator'],'sign':e['sign']}
           for e in macro_norm['events'] if e['forward_eligible'] and pd.Timestamp(e['usable_at_utc'])<=observed]
    model=load('forward_paper/model.json');cut=regimes.index[-1];current=regimes.loc[cut]
    if any(str(current[c])=='unknown' for c in REQ_STATE):
        raise ValueError('Current regime has unknown frozen-model state')
    needed=['funding_per_hour','oi_logchange_24h','top_position_ratio']
    if any(pd.isna(D.loc[cut,c]) for c in needed):
        raise ValueError('Required derivative feature is null at cutoff')
    candidates=candidates_at(regimes,macro,cut,model)
    recent=[]
    for c in regimes.index[-25:]:recent.extend(candidates_at(regimes,macro,c,model))
    overlap_values={}
    for t in expected:
        overlap_values[t.isoformat()]={c:{'archive':float(archive.loc[t,c]),'connected':float(live_metric.loc[t,c])}
                                       for c in live_metric.columns if c in archive.columns}
    receipt={
      'schema':'eth-forward-persisted-extension-receipt-v1','passed':True,
      'scope':'Current causal source-to-feature-to-opportunity receipt from immutable base plus fresh connected Binance read-only extension. No fill/performance.',
      'base_snapshot_manifest':str(Path(base_dir)/'manifest.json'),'fresh_snapshot_manifest':str(Path(fresh_dir)/'manifest.json'),
      'base_first_seen_at_utc':base_seen.isoformat(),'fresh_first_seen_at_utc':observed.isoformat(),
      'base_blob_checks':base_checks,'fresh_blob_checks':fresh_checks,'base_fresh_exact_overlap_rows':overlap,
      'derivative_freshness':fresh,
      'spot_latest_complete_utc':cut.isoformat(),'spot_completed_aligned_hours':len(eth),'spot_latest_age_minutes':eth.attrs['latest_complete_age_minutes'],
      'spot_response_sha256':{'ETHUSDT':sha_bytes(eth_bytes),'BTCUSDT':sha_bytes(btc_bytes)},
      'spot_urls':{'ETHUSDT':eth_url,'BTCUSDT':btc_url},
      'archive_verified_days':len(archive_hashes),'archive_day_sha256':archive_hashes,
      'archive_live_overlap_rows':archive_overlap,'expected_overlap_rows':len(expected),'expected_overlap_value_checks':overlap_values,
      'max_merged_metric_gap_minutes':max_gap,
      'derivative_feature_non_null_at_cut':{c:bool(pd.notna(D.loc[cut,c])) for c in needed},
      'current_regime':{c:str(current[c]) for c in REQ_STATE},'eth_30d_return':float(current['return_30d']),
      'macro_capture_sha256':hashlib.sha256(Path(macro_capture).read_bytes()).hexdigest(),
      'macro_forward_eligible_events_at_observation':len(macro),
      'current_cut_candidate_count':len(candidates),'current_cut_threshold_count':sum(bool(x['passes_frozen_threshold']) for x in candidates),
      'recent_24h_candidate_count':len(recent),'recent_24h_threshold_count':sum(bool(x['passes_frozen_threshold']) for x in recent),
      'current_candidates':candidates,'model_sha256':hashlib.sha256(Path('forward_paper/model.json').read_bytes()).hexdigest(),
      'causal_guards':['fresh conservative first_seen boundary','exact base/fresh raw overlap','completed spot bars only','native 5m metrics','checksum-bound archive overlap','1h backward-only derivative availability lag','actual settled funding intervals','late macro bootstrap excluded','six-hour confirmation fully observed'],
      'historical_outcome_columns_used':False,'order_account_endpoints_used':False,'paper_trades_created':0,'performance_started':False,
      'gate_effect':'Receipt 1 of 2 required current full-pipeline observations. live_feature_parity/source_freshness remain false until an independently timed second fresh extension/full snapshot also passes.'
    }
    Path(out_path).write_text(json.dumps(receipt,indent=2,allow_nan=False));print(json.dumps(receipt,indent=2,allow_nan=False));return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-dir',required=True);p.add_argument('--fresh-dir',required=True);p.add_argument('--macro-capture',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    run(a.base_dir,a.fresh_dir,a.macro_capture,a.out)
