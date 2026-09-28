"""One-packet-at-a-time retrospective LLM decision recorder. No coded LLM substitute."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json,hashlib,sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
TZ='Asia/Hong_Kong'
PROTOCOL_COMMIT='6486ccec85461e81daf31ce9cca4c2526c90d407'

def dumps(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x): return hashlib.sha256(dumps(x).encode()).hexdigest()
def value(x,d=2): return round(float(x),d) if pd.notna(x) and np.isfinite(x) else None

def init():
 if (ROOT/'ledger/decisions.jsonl').exists() or (ROOT/'ledger/DECISIONS_LOCK.json').exists():
  raise ValueError('Recorded study is append-only; do not regenerate its packets')
 from multifactor.data import load_inputs,build_features
 from derivatives.features import prepare_sources,build_derivatives
 from threadpoolctl import threadpool_limits
 frames,checks=load_inputs(ROOT/'inputs');raw=frames['ETHUSDT'];peer=frames['BTCUSDT']
 f,_=build_features(raw,peer,pd.read_csv(ROOT/'inputs/fomc_events.csv'))
 d,_=build_derivatives(raw.index,prepare_sources(ROOT/'derivative_inputs','ETHUSDT'))
 vol=np.log(raw.close).diff().rolling(24).std()
 vr=vol/vol.shift().rolling(720,min_periods=168).median()
 fz=(d.funding_per_hour-d.funding_per_hour.shift().rolling(720,min_periods=168).mean())/d.funding_per_hour.shift().rolling(720,min_periods=168).std().replace(0,np.nan)
 pz=(d.top_position_ratio-d.top_position_ratio.shift().rolling(720,min_periods=168).mean())/d.top_position_ratio.shift().rolling(720,min_periods=168).std().replace(0,np.nan)
 tr=pd.read_csv(ROOT/'input/trades.csv');tr=tr[(tr.symbol=='ETHUSDT')&(tr.cost=='base')].copy()
 tr['ex']=pd.to_datetime(tr.exit_hkt,utc=True).dt.tz_convert(TZ)
 macros=pd.DataFrame(json.loads((ROOT/'input/macro_events.json').read_text())['events'])
 macros['released']=pd.to_datetime(macros.release_at,utc=True).dt.tz_convert(TZ)
 periods=[]
 for year in [2025,2026]:
  begin=pd.Timestamp(f'{year}-01-01',tz=TZ);end=pd.Timestamp('2026-09-15' if year==2026 else '2026-01-01',tz=TZ)
  cuts=sorted(set([begin]+list(pd.date_range(begin,end,freq='W-MON',inclusive='left'))))
  periods.extend([(t, min(cuts[k+1] if k+1<len(cuts) else end,end),year) for k,t in enumerate(cuts)])
 packetdir=ROOT/'ledger/packets';packetdir.mkdir(exist_ok=True,parents=True)
 mapping=[]
 for k,(cut,end,year) in enumerate(periods):
  row=f.loc[cut];dr=d.loc[cut]
  past=tr[tr.ex<cut]
  perf={}
  for n in [28,90]:
   z=past[past.ex>=cut-pd.Timedelta(days=n)]
   perf[str(n)]={'closed':len(z),'mean_pct':value(z.net_return.mean()*100),'total_pct':value((np.prod(1+z.net_return)-1)*100)}
  m=macros[(macros.released<=cut-pd.Timedelta(hours=1))&(macros.released>=cut-pd.Timedelta(days=7))].sort_values('released')
  recent=[]
  for mr in m.itertuples():
   recent.append({'indicator':mr.indicator,'age_days':value((cut-mr.released)/pd.Timedelta(days=1),1),'actual':value(mr.actual,3),'forecast':value(mr.forecast,3),'surprise':value(mr.surprise_raw,3),'unit':mr.unit})
  p={'step':k+1,'interval_days':value((end-cut)/pd.Timedelta(days=1),0),
   'ETH_pct':{'1d':value(row.return_24h*100),'7d':value(row.return_168h*100),'30d':value(row.own_return_30d*100),'previous7d':value((raw.close.loc[cut-pd.Timedelta(days=7)]/raw.close.loc[cut-pd.Timedelta(days=14)]-1)*100)},
   'BTC_pct':{'7d':value(row.peer_return_168h*100),'30d':value((peer.close.loc[cut]/peer.close.loc[cut-pd.Timedelta(days=30)]-1)*100)},
   'vol_ratio':value(vr.loc[cut]),'from_30d_high_pct':value((raw.close.loc[cut]/raw.high.loc[cut-pd.Timedelta(days=30):cut].max()-1)*100),
   'buy_imbalance_24h':value(row.buy_imbalance_24h,3),'funding_z':value(fz.loc[cut]),'OI_change_24h_pct':value(np.expm1(dr.oi_logchange_24h)*100),'position_z':value(pz.loc[cut]),
   'closed_parent':perf,'macro_past7d':recent,'news':'historical_news_unavailable',
   'quality_ok':bool(pd.notna(dr).all() and pd.notna(vr.loc[cut]) and pd.notna(row.own_return_30d))}
  (packetdir/f'{k+1:03d}.json').write_text(dumps(p))
  mapping.append({'step':k+1,'cut':cut.isoformat(),'effective':(cut+pd.Timedelta(hours=1)).isoformat(),'end':end.isoformat(),'year':year,'packet_sha256':digest(p),'simple_weight':1. if row.own_return_30d>=0 else .5})
 (ROOT/'ledger/mapping.json').write_text(dumps(mapping));(ROOT/'input/source_checks.json').write_text(dumps(checks))
 print('PACKETS_PREPARED',len(mapping),'no future outcomes printed')

def read_ledger():
 p=ROOT/'ledger/decisions.jsonl'
 return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

def next_packet():
 ds=read_ledger();mapping=json.loads((ROOT/'ledger/mapping.json').read_text());i=len(ds)+1
 if i>len(mapping):return {'done':True,'decisions':len(ds)}
 return json.loads((ROOT/f'ledger/packets/{i:03d}.json').read_text())

def record(weight:float,reason:str):
 if (ROOT/'ledger/DECISIONS_LOCK.json').exists():raise ValueError('Decisions locked; append prohibited')
 if weight not in [0.,.5,1.]:raise ValueError('Not allowed')
 p=next_packet()
 if p.get('done'):raise ValueError('All decisions locked')
 if not reason or len(reason)<8:raise ValueError('Rationale required')
 ds=read_ledger()
 obj={'step':p['step'],'weight':weight,'rationale':reason,'packet_sha256':digest(p),'previous_decision_sha256':digest(ds[-1]) if ds else None,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'decision_actor':'ChatGPT GPT-6 Astra Pro, current conversation; build/sampling settings unavailable','protocol_commit':PROTOCOL_COMMIT}
 with (ROOT/'ledger/decisions.jsonl').open('a',encoding='utf-8') as out:out.write(dumps(obj)+'\n')
 return next_packet()

if __name__=='__main__':
 if sys.argv[1]=='init':init()
 elif sys.argv[1]=='next':print(dumps(next_packet()))
 elif sys.argv[1]=='decide':print(dumps(record(float(sys.argv[2]),sys.argv[3])))
