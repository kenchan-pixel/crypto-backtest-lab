"""Immutable research bundle with exact data, source, outputs and per-file hashes."""
from pathlib import Path
import hashlib,json,os,platform,zipfile
import numpy,pandas,sklearn,nbformat,nbclient
ROOT=Path(__file__).resolve().parent.parent

def package():
    receipt=json.loads((ROOT/'derivative_outputs/execution_status.json').read_text())
    if not receipt.get('completed') or not receipt.get('notebook_executed'):raise ValueError('Research incomplete')
    env={'python':platform.python_version(),'numpy':numpy.__version__,'pandas':pandas.__version__,'sklearn':sklearn.__version__,'nbformat':nbformat.__version__,'nbclient':nbclient.__version__}
    (ROOT/'derivative_outputs/environment.json').write_text(json.dumps(env,indent=2))
    paths=[]
    for name in ['inputs','derivative_inputs','derivative_outputs','multifactor','derivatives','verification']:
        paths.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts)
    manifest={'source_commit':os.environ.get('GITHUB_SHA','local; see verified Git-blob hashes'),'source_runs':[35336304622,35414544625],
        'market_data_simulated':False,'live_approved':False,'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    output=ROOT/'delivery';output.mkdir(exist_ok=True)
    (output/'MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    target=output/'Crypto_Derivatives_Research_20260919.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in paths:z.write(p,str(p.relative_to(ROOT)))
        z.write(output/'MANIFEST.json','MANIFEST.json')
    if target.stat().st_size>60*1024*1024:raise ValueError('Research bundle exceeds budget')
    sha=hashlib.sha256(target.read_bytes()).hexdigest();(output/'SHA256SUMS.txt').write_text(sha+'  '+target.name+'\n')
    print('Bundle bytes',target.stat().st_size,'SHA256',sha)
if __name__=='__main__':package()
