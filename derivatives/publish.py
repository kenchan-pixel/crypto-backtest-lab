"""Archive public research evidence; never overwrites a release or approves trading."""
from pathlib import Path
import json,os
import requests
repo=os.environ['GITHUB_REPOSITORY']
if repo!='kenchan-pixel/crypto-backtest-lab':raise ValueError('Unexpected publication target')
sha=os.environ['GITHUB_SHA'];tag='research-derivatives-20260919-'+sha[:12]+'-a'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'}
base='https://api.github.com/repos/'+repo
r=requests.get(base+'/releases/tags/'+tag,headers=headers,timeout=30)
if r.status_code!=404:raise ValueError('Release exists or cannot be checked; no overwrite')
r=requests.post(base+'/releases',headers=headers,json={'tag_name':tag,'target_commitish':sha,'name':'Derivatives research evidence 2026-09-19','body':'Reproducible research only; no reliable trading edge or live approval. Exact source, inputs, all outcomes, notebook and hashes included. See derivatives/RESULTS.md.','prerelease':True,'draft':False,'make_latest':'false'},timeout=30);r.raise_for_status();release=r.json()
for name in ['Crypto_Derivatives_Research_20260919.zip','MANIFEST.json','SHA256SUMS.txt']:
    path=Path('delivery')/name
    with path.open('rb') as f:
        rr=requests.post(release['upload_url'].split('{')[0],params={'name':name},headers={**headers,'Content-Type':'application/octet-stream'},data=f,timeout=180)
    rr.raise_for_status()
    if rr.json().get('size')!=path.stat().st_size:raise ValueError('Published byte count mismatch')
Path('delivery/release_receipt.json').write_text(json.dumps({'url':release['html_url'],'tag':tag,'source_commit':sha,'release_id':release['id']},indent=2))
print('Research archived:',release['html_url'])
