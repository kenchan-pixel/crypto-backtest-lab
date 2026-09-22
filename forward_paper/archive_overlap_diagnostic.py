"""Read-only diagnostic for the commissioning archive/live overlap mismatch."""
import argparse,json
from pathlib import Path
import pandas as pd
from .persisted_pipeline import load_snapshot
from .live_sources import normalize_metric_bundle
from .live_pipeline import archive_warmup,REQ_COLS

def run(base_dir,out):
 m,seen,r,_=load_snapshot(base_dir)
 live=normalize_metric_bundle(symbol='ETHUSDT',period='5m',open_interest=r['open_interest'],top_accounts=r['top_accounts'],top_positions=r['top_positions'],all_accounts=r['all_accounts'],taker=r['taker'])
 archive,hashes=archive_warmup(seen.to_pydatetime())
 expected=pd.DatetimeIndex(pd.to_datetime(m['archive_overlap_expected']['timestamps_utc'],utc=True))
 detail={};mismatches=0
 for t in expected:
  row={}
  for c in REQ_COLS:
   a=float(archive.loc[t,c]);b=float(live.loc[t,c]);same=abs(a-b)<=1e-12+1e-10*abs(a)
   row[c]={'archive':a,'connected':b,'abs_delta':b-a,'match':same}
   mismatches+=0 if same else 1
  detail[t.isoformat()]=row
 receipt={'schema':'archive-connected-overlap-diagnostic-v1','passed':mismatches==0,'base_first_seen_at_utc':seen.isoformat(),'archive_day_sha256':hashes.get('2026-09-20'),'expected_timestamps':[x.isoformat() for x in expected],'mismatch_cells':mismatches,'detail':detail,'paper_trades_created':0,'gate_promotion':False}
 Path(out).write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2));return receipt
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base-dir',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.base_dir,a.out)
