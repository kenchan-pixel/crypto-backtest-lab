"""Restore exact inputs, execute notebook, package and optionally publish evidence."""
from pathlib import Path
import argparse,hashlib,io,json,os,shutil,zipfile
import requests
ROOT=Path(__file__).resolve().parent.parent
DERIV_URL='https://github.com/kenchan-pixel/crypto-backtest-lab/releases/download/research-derivatives-20260919-52b24ddfb33c-a1/Crypto_Derivatives_Research_20260919.zip'
DERIV_SHA='034aa3a79ea9451868f862d0796cceb158df956b12c1fe3ccf6901ff3fb43051'
PAYOFF_URL='https://api.github.com/repos/kenchan-pixel/crypto-backtest-lab/actions/artifacts/10604261305/zip'
PAYOFF_SHA='12aaeaa9699645db26036a8433e2c5437c3d4dd233507182452b783434b9314c'

def prepare():
    folder=ROOT/'input';folder.mkdir(exist_ok=True)
    jobs=[(DERIV_URL,DERIV_SHA,['inputs/ETHUSDT_hourly_features.csv.gz','inputs/ETHUSDT_quality.json','inputs/ETHUSDT_sources.json'],False),(PAYOFF_URL,PAYOFF_SHA,['trades.csv','strategy_summary.csv','thresholds.json','execution_status.json'],True)]
    source=[]
    for url,digest,names,auth in jobs:
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN']} if auth else {}
        r=requests.get(url,headers=headers,timeout=(15,120));r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=digest:raise ValueError('Source ZIP hash mismatch')
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for name in names:(folder/Path(name).name).write_bytes(z.read(name))
        source.append({'url':url,'zip_sha256':digest,'members':names})
    shutil.copyfile(ROOT/'benchmark_review/boundary_klines.json',folder/'boundary_klines.json')
    (folder/'SOURCE_MANIFEST.json').write_text(json.dumps(source,indent=2))
    print('Exact source inputs restored; no model fit performed')

def notebook():
    import nbformat
    from nbclient import NotebookClient
    n=nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell('# ETH frozen-model benchmark review\nSame recorded entries/exits. No refit, retuning or live approval. Ex-post volatility matching is diagnostic only; the 2026 prior-year weight uses 2025 data. Running all cells recomputes the review and independent daily arithmetic checks from the bundled genuine inputs.'),
      nbformat.v4.new_code_cell("from pathlib import Path\nimport pandas as pd\nfrom IPython.display import display\nfrom benchmark_review.analyze import run\nfrom benchmark_review.verify import verify\nroot=Path.cwd()\nsummary,inference=run(root)\nchecks=verify(root)\nprint('Independent checks:', checks['check_count'])"),
      nbformat.v4.new_code_cell("display(summary[['year','account','net_return','max_drawdown','volatility_ann','average_coin_weight']])\ndisplay(pd.read_csv(root/'output/passive_weights.json') if False else pd.read_json(root/'output/passive_weights.json'))"),
      nbformat.v4.new_code_cell("display(inference)\ndisplay(pd.read_csv(root/'output/random_control_summary.csv'))"),
      nbformat.v4.new_code_cell("display(pd.read_csv(root/'output/monthly_capture.csv'))\ndisplay(pd.read_csv(root/'output/causal_regime_comparison.csv'))")])
    NotebookClient(n,timeout=300,kernel_name='python3',resources={'metadata':{'path':str(ROOT)}}).execute()
    out=ROOT/'output';nbformat.write(n,out/'ETH_Benchmark_Review_Executed.ipynb')
    p=out/'execution_receipt.json';s=json.loads(p.read_text());s.update(notebook_executed=True,notebook_code_cells=4,notebook_sha256=hashlib.sha256((out/'ETH_Benchmark_Review_Executed.ipynb').read_bytes()).hexdigest(),execution='GitHub Actions' if os.getenv('GITHUB_ACTIONS') else 'local container',source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'))
    p.write_text(json.dumps(s,indent=2))

def package():
    folder=ROOT/'delivery';folder.mkdir(exist_ok=True)
    s=json.loads((ROOT/'output/execution_receipt.json').read_text())
    if not s.get('completed') or not s.get('notebook_executed'):raise ValueError('Execution incomplete')
    paths=[p for name in ['benchmark_review','input','output','verification'] for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts and not p.name.endswith('.log')]
    manifest={'source_commit':os.getenv('GITHUB_SHA'),'model_changed':False,'market_data_simulated':False,'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    (folder/'MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    target=folder/'ETH_Benchmark_Review_20260921.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in paths:z.write(p,str(p.relative_to(ROOT)))
        z.write(folder/'MANIFEST.json','MANIFEST.json')
    if target.stat().st_size>30*1024*1024:raise ValueError('Unexpected archive size')
    digest=hashlib.sha256(target.read_bytes()).hexdigest();(folder/'SHA256SUMS.txt').write_text(digest+'  '+target.name+'\n')
    print('Packaged',target.stat().st_size,'bytes',digest)

def publish():
    repo=os.environ['GITHUB_REPOSITORY']
    if repo!='kenchan-pixel/crypto-backtest-lab':raise ValueError('Unexpected repository')
    sha=os.environ['GITHUB_SHA'];tag='research-eth-benchmark-20260921-'+sha[:12]+'-a'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
    h={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'};base='https://api.github.com/repos/'+repo
    existing=requests.get(base+'/releases/tags/'+tag,headers=h,timeout=30)
    if existing.status_code!=404:raise ValueError('Refusing existing or unresolved tag')
    r=requests.post(base+'/releases',headers=h,json={'tag_name':tag,'target_commitish':sha,'name':'Frozen ETH benchmark review','body':'Relative-performance research only. Same model/trades; no live approval. Exact inputs, notebook, source, all counterfactual outcomes and per-file hashes included.','prerelease':True,'make_latest':'false'},timeout=30);r.raise_for_status();rel=r.json()
    for name in ['ETH_Benchmark_Review_20260921.zip','MANIFEST.json','SHA256SUMS.txt']:
        p=ROOT/'delivery'/name
        with p.open('rb') as f:q=requests.post(rel['upload_url'].split('{')[0],params={'name':name},headers={**h,'Content-Type':'application/octet-stream'},data=f,timeout=180)
        q.raise_for_status()
        if q.json().get('size')!=p.stat().st_size:raise ValueError('Publication byte-count mismatch')
    (ROOT/'delivery/release_receipt.json').write_text(json.dumps({'url':rel['html_url'],'tag':tag,'source_commit':sha},indent=2))
    print(rel['html_url'])

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','notebook','package','publish']);a=ap.parse_args();globals()[a.mode]()
