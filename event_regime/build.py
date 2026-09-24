"""Build Event + Regime Dataset v1 from causal, previously verified inputs."""
from __future__ import annotations
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd

from multifactor.data import load_inputs,build_features,labels,TZ,START,END
from derivatives.features import prepare_sources,build_derivatives

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'event_regime_outputs'
MACRO=ROOT/'longbridge_macro/normalized/macro_events.json'

def rolling_z(s:pd.Series,window=720,minp=168):
    mean=s.rolling(window,min_periods=minp).mean()
    std=s.rolling(window,min_periods=minp).std()
    return (s-mean)/std.replace(0,np.nan)

def label3(x,lo,hi,low_name,mid_name,high_name):
    a=np.full(len(x),mid_name,dtype=object)
    a[np.asarray(x)<lo]=low_name
    a[np.asarray(x)>hi]=high_name
    a[pd.isna(x)]= 'unknown'
    return a

def build_regime():
    OUT.mkdir(exist_ok=True)
    frames,checks=load_inputs(ROOT/'inputs')
    fomc=pd.read_csv(ROOT/'inputs/fomc_events.csv')
    rows=[]
    for sym,raw in frames.items():
        peer_sym='ETHUSDT' if sym=='BTCUSDT' else 'BTCUSDT'
        peer=frames[peer_sym]
        X,_=build_features(raw,peer,fomc)
        D,_=build_derivatives(X.index,prepare_sources(ROOT/'derivative_inputs',sym))
        idx=(X.index>=START)&(X.index<END)
        x=X.loc[idx]; d=D.loc[idx]; rr=raw.loc[idx]
        out=pd.DataFrame(index=x.index)
        out['symbol']=sym
        out['close']=rr.close
        out['return_24h']=x['return_24h']
        out['return_7d']=x['return_168h']
        out['return_30d']=x['own_return_30d']
        out['volatility24']=x['volatility24']
        trailing_med=x['volatility24'].rolling(720,min_periods=168).median()
        out['vol_ratio_30d_median']=x['volatility24']/trailing_med
        out['peer_correlation_168h']=x['peer_correlation_168h']
        out['relative_return_24h']=x['relative_return_24h']

        out['funding_per_hour']=d['funding_per_hour']
        out['funding_z30d']=rolling_z(d['funding_per_hour'])
        out['oi_logchange_24h']=d['oi_logchange_24h']
        out['oi_change_z30d']=rolling_z(d['oi_logchange_24h'])
        out['top_position_log_ratio']=d['top_position_ratio']
        out['positioning_z30d']=rolling_z(d['top_position_ratio'])
        out['taker_log_ratio']=d['taker_ratio']

        out['trend_30d']=label3(out.return_30d,-.05,.05,'down','flat','up')
        out['trend_7d']=label3(out.return_7d,-.02,.02,'down','flat','up')
        out['vol_state']=label3(out.vol_ratio_30d_median,.75,1.25,'compressed','normal','expanded')
        out['cross_asset_state']=label3(out.relative_return_24h,-.02,.02,'laggard','aligned','leader')
        out['funding_state']=label3(out.funding_z30d,-1.5,1.5,'crowded_short','normal','crowded_long')
        out['oi_state']=label3(out.oi_change_z30d,-1.,1.,'deleveraging','stable','leverage_build')
        out['positioning_state']=label3(out.positioning_z30d,-1.5,1.5,'short_crowded','balanced','long_crowded')
        cats=['trend_30d','trend_7d','vol_state','cross_asset_state','funding_state','oi_state','positioning_state']
        out['regime_id']=out[cats].astype(str).agg('|'.join,axis=1)

        for h in [6,24,72]:
            future=raw.execution_open.shift(-h)/raw.execution_open-1
            timediff=raw.execution_ms.shift(-h)-raw.execution_ms
            future=future.where(timediff==h*3_600_000)
            out[f'forward_return_{h}h']=future.reindex(out.index)
        f24=out.forward_return_24h
        out['direction_24h']=np.select([f24<=-.01,f24>=.01],['down','up'],default='neutral')
        out.loc[f24.isna(),'direction_24h']='unavailable'
        out['outcome_ready_at_hkt']=(out.index+pd.Timedelta(hours=72)).astype(str)

        out.index.name='decision_hkt'
        rows.append(out.reset_index())
    result=pd.concat(rows,ignore_index=True)
    result.to_csv(OUT/'hourly_regimes.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    (OUT/'market_input_checks.json').write_text(json.dumps(checks,indent=2))
    return result

def valid_published(value):
    if not value: return None
    try:
        t=pd.Timestamp(value)
        if t.year<=1971: return None
        return t.tz_convert('UTC') if t.tzinfo else t.tz_localize('UTC')
    except Exception:
        return None

def news_events():
    records=[]
    for path in sorted((ROOT/'event_regime/raw_news').glob('*.json')):
        obj=json.loads(path.read_text())
        first=pd.Timestamp(obj['first_seen_hkt'])
        raw=obj.get('raw',{})
        text=raw.get('text','[]') if isinstance(raw,dict) else '[]'
        try: items=json.loads(text)
        except Exception: items=[]
        for item in items:
            published=valid_published(item.get('time') or item.get('publish_at'))
            usable=first
            title=item.get('title') or ''
            url=item.get('url') or ''
            base='news|'+str(item.get('id'))+'|'+title+'|'+url
            records.append({
              'event_id':hashlib.sha256(base.encode()).hexdigest()[:24],
              'event_type':'news','event_subtype':'search_hit',
              'source':item.get('source_name') or item.get('source'),
              'first_seen_at_hkt':first.isoformat(),
              'published_at_utc':published.isoformat() if published is not None else None,
              'usable_at_hkt':usable.isoformat(),
              'timestamp_quality':'first_seen_only' if published is None else 'search_timestamp',
              'title':title,'url':url,'asset_tags':'',
              'query':obj.get('query'),'actual':None,'forecast':None,'previous':None,'surprise_raw':None,
              'content_hash':hashlib.sha256((title+'|'+str(item.get('excerpt',''))).encode()).hexdigest(),
              'is_forward_collected':True,'raw_file':str(path.relative_to(ROOT))
            })
    return records

def macro_events():
    obj=json.loads(MACRO.read_text());records=[]
    for e in obj['events']:
        release=pd.Timestamp(e['release_at'])
        hkt=release.tz_convert(TZ)
        base='macro|'+e['indicator']+'|'+e['release_at']+'|'+str(e.get('actual'))
        records.append({
          'event_id':hashlib.sha256(base.encode()).hexdigest()[:24],
          'event_type':'macro','event_subtype':e['indicator'],'source':'Longbridge macrodata',
          'first_seen_at_hkt':None,'published_at_utc':release.isoformat(),
          'usable_at_hkt':(hkt.floor('h')+pd.Timedelta(hours=1)).isoformat(),
          'timestamp_quality':'macro_release','title':e['indicator_name'],'url':'','asset_tags':'BTC;ETH',
          'query':'','actual':e.get('actual'),'forecast':e.get('forecast'),'previous':e.get('previous'),
          'surprise_raw':e.get('surprise_raw'),
          'content_hash':hashlib.sha256(json.dumps(e,sort_keys=True).encode()).hexdigest(),
          'is_forward_collected':False,'raw_file':'longbridge_macro/normalized/macro_events.json'
        })
    return records

def build_events():
    records=macro_events()+news_events()
    frame=pd.DataFrame(records).drop_duplicates('event_id').sort_values(['usable_at_hkt','event_id'],na_position='last')
    frame.to_csv(OUT/'events.csv',index=False)
    summary={
      'rows':len(frame),'macro_rows':int((frame.event_type=='macro').sum()),
      'forward_news_rows':int((frame.event_type=='news').sum()),
      'forward_news_unique_ids':int(frame.loc[frame.event_type=='news','event_id'].nunique()),
      'timestamp_quality':frame.timestamp_quality.value_counts(dropna=False).to_dict()
    }
    (OUT/'event_summary.json').write_text(json.dumps(summary,indent=2))
    return frame

def main():
    regimes=build_regime();events=build_events()
    manifest={}
    for p in OUT.glob('*'):
        if p.is_file(): manifest[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT/'MANIFEST.json').write_text(json.dumps({
      'schema_version':'event-regime-v1','market_data_simulated':False,'live_approved':False,
      'regime_rows':len(regimes),'event_rows':len(events),'files':manifest
    },indent=2))
    print('REGIMES',len(regimes),'EVENTS',len(events))
if __name__=='__main__':main()
