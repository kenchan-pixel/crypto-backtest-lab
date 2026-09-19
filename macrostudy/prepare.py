"""Restore exact durable derivative-study inputs from the prior prerelease."""
from pathlib import Path
import hashlib,io,zipfile,requests

ROOT=Path(__file__).resolve().parent.parent
URL='https://github.com/kenchan-pixel/crypto-backtest-lab/releases/download/research-derivatives-20260919-52b24ddfb33c-a1/Crypto_Derivatives_Research_20260919.zip'
SHA='034aa3a79ea9451868f862d0796cceb158df956b12c1fe3ccf6901ff3fb43051'

def prepare():
    r=requests.get(URL,timeout=(15,180));r.raise_for_status()
    if hashlib.sha256(r.content).hexdigest()!=SHA: raise ValueError('Prior durable research ZIP checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            p=Path(name)
            if p.is_absolute() or '..' in p.parts: raise ValueError('Unsafe archive path')
            if not (name.startswith('inputs/') or name.startswith('derivative_inputs/')): continue
            z.extract(name,ROOT)
    required=[
      'inputs/BTCUSDT_hourly_features.csv.gz','inputs/ETHUSDT_hourly_features.csv.gz','inputs/fomc_events.csv',
      'derivative_inputs/BTCUSDT_fundingRate.csv.gz','derivative_inputs/ETHUSDT_fundingRate.csv.gz',
      'derivative_inputs/BTCUSDT_metrics.csv.gz','derivative_inputs/ETHUSDT_metrics.csv.gz',
      'derivative_inputs/BTCUSDT_funding_tail.json','derivative_inputs/ETHUSDT_funding_tail.json'
    ]
    missing=[x for x in required if not (ROOT/x).exists()]
    if missing: raise ValueError('Missing restored inputs: '+str(missing))
    print('Restored exact durable prior inputs',len(required))
if __name__=='__main__':prepare()
