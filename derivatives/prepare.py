"""Restore two exact research inputs; only GitHub downloads need the CI token."""
from pathlib import Path
import hashlib,io,json,os,shutil,zipfile
import requests
from multifactor.data import make_event_file
ROOT=Path(__file__).resolve().parent.parent
SOURCES=[(10542637403,'9a93581498e47a09c592db20f1395e85a447dcba198d6e2c98f2417ef61500dd','spot'),(10575272946,'8b82198cded56e8668af2726da8310256dbf0bde39625e91538615ee22623e91','derivatives')]

def prepare():
    for artifact,sha,kind in SOURCES:
        url=f'https://api.github.com/repos/kenchan-pixel/crypto-backtest-lab/actions/artifacts/{artifact}/zip'
        r=requests.get(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'},timeout=(15,120))
        r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('Input artifact checksum mismatch')
        folder=ROOT/('inputs' if kind=='spot' else 'derivative_inputs');folder.mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for name in z.namelist():
                p=Path(name)
                if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe archive path')
                if kind=='spot' and name not in [f'{s}_{ending}' for s in ['BTCUSDT','ETHUSDT'] for ending in ['hourly_features.csv.gz','quality.json','sources.json']]:continue
                z.extract(name,folder)
    make_event_file(ROOT/'inputs/fomc_events.csv')
    # Connector-returned September observations are explicit fixed source data.
    from . import supplement
    print('Exact research inputs restored; no newly invented market observations')
if __name__=='__main__':prepare()
