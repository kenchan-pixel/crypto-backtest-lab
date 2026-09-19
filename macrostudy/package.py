"""Package compact macro research evidence; prior derivative inputs stay in the referenced durable release."""
from pathlib import Path
import hashlib,json,os,zipfile,platform
import numpy,pandas,sklearn
ROOT=Path(__file__).resolve().parent.parent

def package():
    out=ROOT/'macro_outputs'
    state=json.loads((out/'execution_status.json').read_text())
    if not state.get('completed') or not state.get('notebook_executed'): raise ValueError('Research incomplete')
    delivery=ROOT/'macro_delivery';delivery.mkdir(exist_ok=True)
    paths=[]
    for root in ['macrostudy','longbridge_macro','macro_outputs','verification']:
        folder=ROOT/root
        if folder.exists():
            paths.extend(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts)
    manifest={
      'source_commit':os.environ.get('GITHUB_SHA'),
      'prior_derivative_release':'research-derivatives-20260919-52b24ddfb33c-a1',
      'prior_derivative_zip_sha256':'034aa3a79ea9451868f862d0796cceb158df956b12c1fe3ccf6901ff3fb43051',
      'market_data_simulated':False,'live_approved':False,
      'environment':{'python':platform.python_version(),'numpy':numpy.__version__,'pandas':pandas.__version__,'sklearn':sklearn.__version__},
      'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    }
    (delivery/'MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    target=delivery/'Crypto_Longbridge_Macro_Research_20260920.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in paths:z.write(p,str(p.relative_to(ROOT)))
        z.write(delivery/'MANIFEST.json','MANIFEST.json')
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (delivery/'SHA256SUMS.txt').write_text(digest+'  '+target.name+'\n')
    print('bundle',target.stat().st_size,digest)
if __name__=='__main__':package()
