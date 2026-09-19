"""Publish one versioned prerelease; refuse overwrite."""
from pathlib import Path
import json,os,requests
repo=os.environ['GITHUB_REPOSITORY'];sha=os.environ['GITHUB_SHA']
tag='research-macro-20260920-'+sha[:12]+'-a'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'}
base='https://api.github.com/repos/'+repo
old=requests.get(base+'/releases/tags/'+tag,headers=headers,timeout=30)
if old.status_code!=404: raise ValueError('Release tag already exists; refusing overwrite')
r=requests.post(base+'/releases',headers=headers,json={
 'tag_name':tag,'target_commitish':sha,'name':'Longbridge macro research evidence 2026-09-20',
 'body':'Retrospective research only; no live approval. Macro raw/normalized data, source, outputs, notebook and hashes included. Prior durable derivative input release is referenced by SHA.',
 'prerelease':True,'draft':False,'make_latest':'false'},timeout=30);r.raise_for_status();release=r.json()
for name in ['Crypto_Longbridge_Macro_Research_20260920.zip','MANIFEST.json','SHA256SUMS.txt']:
    p=Path('macro_delivery')/name
    with p.open('rb') as f:
        q=requests.post(release['upload_url'].split('{')[0],params={'name':name},
          headers={**headers,'Content-Type':'application/octet-stream'},data=f,timeout=180)
    q.raise_for_status()
Path('macro_delivery/release_receipt.json').write_text(json.dumps({'url':release['html_url'],'tag':tag,'source_commit':sha},indent=2))
print(release['html_url'])
