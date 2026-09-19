"""Causal multi-factor features from provenance-checked true hourly observations."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd
TZ='Asia/Hong_Kong'
SEED=20260919
EXPECTED_HASH={
 'BTCUSDT':'ae239e8ef6fac21dee8ac648e9ac2b52e699a64002a98d353c567a452ec65b5f',
 'ETHUSDT':'25e534123a8a4b0154cd378b2841bd89eae0f1904d6ea0e7dfeb6a6440dc029b'}
START=pd.Timestamp('2024-01-01',tz=TZ)
END=pd.Timestamp('2026-09-15',tz=TZ)


def make_event_file(path: Path) -> pd.DataFrame:
    # Values transcribed from the official time-stamped rate statements, not media
    # summaries or effective-date tables. All 21 in-window regular decisions retained.
    dates=['20231213','20240131','20240320','20240501','20240612','20240731',
           '20240918','20241107','20241218','20250129','20250319','20250507',
           '20250618','20250730','20250917','20251029','20251210','20260128',
           '20260318','20260429','20260617','20260729']
    uppers=[5.5,5.5,5.5,5.5,5.5,5.5,5.,4.75,4.5,4.5,4.5,4.5,4.5,4.5,4.25,4.,3.75,3.75,3.75,3.75,3.75,3.75]
    rows=[]
    for i,(date,upper) in enumerate(zip(dates,uppers)):
        local=pd.Timestamp(date+' 14:00',tz='America/New_York')
        url=f'https://www.federalreserve.gov/newsevents/pressreleases/monetary{date}a.htm'
        if date=='20250730':
            url='https://www.federalreserve.gov/monetarypolicy/monetary20250730a.htm'
        rows.append({'event_id':date,'release_et':local.isoformat(),
          'release_utc':local.tz_convert('UTC').isoformat(),
          'release_hkt':local.tz_convert(TZ).isoformat(),
          'usable_from_utc':(local+pd.Timedelta(minutes=1)).tz_convert('UTC').isoformat(),
          'target_lower_percent':upper-.25,'target_upper_percent':upper,
          'change_percentage_points':upper-uppers[i-1] if i else 0.,
          'source_url':url,'verified_date':'2026-09-19',
          'role':'warmup' if i==0 else 'research',
          'provenance':'official_publication_numeric_transcription',
          'not_market_surprise':True})
    frame=pd.DataFrame(rows); frame.to_csv(path,index=False)
    return frame


def load_inputs(folder: Path):
    frames={}; checks=[]
    for symbol in EXPECTED_HASH:
        path=folder/f'{symbol}_hourly_features.csv.gz'
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=EXPECTED_HASH[symbol]: raise ValueError('Input hash differs: '+symbol)
        f=pd.read_csv(path,index_col=0,parse_dates=True)
        f.index=f.index.tz_convert(TZ)
        if not f.index.is_monotonic_increasing or not f.index.is_unique:
            raise ValueError('Non-unique or unordered hours')
        if (f.index.to_series().diff().dropna()!=pd.Timedelta(hours=1)).any():
            raise ValueError('Missing hourly time slots')
        window=f[(f.index>=START)&(f.index<END)]
        if not (window.minutes==60).all(): raise ValueError('Incomplete hours inside study')
        if window[['open','high','low','close','volume','quote_volume','taker_quote']].isna().any().any():
            raise ValueError('Missing OHLCV inside study')
        if not (window.execution_delay_min==0).all(): raise ValueError('Delayed execution in study')
        expected_ms=window.index.asi8//1_000_000+60_000
        if not np.array_equal(window.execution_ms.to_numpy(),expected_ms):
            raise ValueError('Execution not exactly next minute')
        frames[symbol]=f
        checks.append({'symbol':symbol,'input_sha256':digest,'hour_rows_with_warmup':len(f),
         'study_hour_rows':len(window),'one_minute_execution_alignment':True,
         'inherited_minute_archive_audit':True,'raw_minutes_redownloaded_in_this_run':False})
    if not frames['BTCUSDT'].index.equals(frames['ETHUSDT'].index): raise ValueError('Peer timing mismatch')
    return frames,checks


def technical(raw: pd.DataFrame) -> pd.DataFrame:
    c,h,l=raw.close,raw.high,raw.low
    x=pd.DataFrame(index=raw.index)
    for n in [1,3,6,12,24,72,168]: x[f'return_{n}h']=c/c.shift(n)-1
    delta=c.diff(); up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    down=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    x['rsi14']=100*up/(up+down)
    x['rsi14']=x.rsi14.mask((up+down)==0,50.)
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    x['atr14_fraction']=atr/c
    moveup=h.diff(); movedown=-l.diff()
    plus=moveup.where((moveup>movedown)&(moveup>0),0.).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    minus=movedown.where((movedown>moveup)&(movedown>0),0.).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    den=plus+minus
    dx=100*(plus-minus).abs()/den.replace(0,np.nan)
    x['adx14']=dx.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    ema12=c.ewm(span=12,adjust=False,min_periods=12).mean()
    ema26=c.ewm(span=26,adjust=False,min_periods=26).mean()
    macd=ema12-ema26; macdsig=macd.ewm(span=9,adjust=False,min_periods=9).mean()
    x['macd_fraction']=macd/c; x['macd_hist_fraction']=(macd-macdsig)/c
    ma=c.rolling(20).mean();sd=c.rolling(20).std()
    x['bollinger_position']=(c-ma)/(2*sd.replace(0,np.nan))
    x['bollinger_width']=4*sd/ma
    for n in [24,168]:
        x[f'prior_high_distance_{n}h']=c/h.shift().rolling(n).max()-1
        x[f'prior_low_distance_{n}h']=c/l.shift().rolling(n).min()-1
    logret=np.log(c).diff()
    x['volatility24']=logret.rolling(24).std()
    x['volatility_ratio']=x.volatility24/logret.rolling(168).std().shift()
    x['close_location']=(c-l)/(h-l).replace(0,np.nan)
    x['body_fraction']=(c-raw.open)/c
    x['vwap_distance']=c/(raw.quote_volume.rolling(24).sum()/raw.volume.rolling(24).sum())-1
    return x


def event_features(index: pd.DatetimeIndex, events: pd.DataFrame) -> pd.DataFrame:
    release=pd.to_datetime(events.release_utc,utc=True)
    usable=pd.to_datetime(events.usable_from_utc,utc=True)
    positions=np.searchsorted(usable.astype('int64'),index.asi8,side='right')-1
    ok=positions>=0; pos=positions.clip(0)
    hours=(index.asi8-release.astype('int64').to_numpy()[pos])/3.6e12
    out=pd.DataFrame(index=index)
    out['fomc_rate_upper']=events.target_upper_percent.to_numpy()[pos]
    out['fomc_last_change']=events.change_percentage_points.to_numpy()[pos]
    out['fomc_hours_since']=np.clip(hours,0,1440)
    out['fomc_after_6h']=((hours>0)&(hours<=6)).astype(float)
    out['fomc_after_6_to_24h']=((hours>6)&(hours<=24)).astype(float)
    out['fomc_after_24_to_72h']=((hours>24)&(hours<=72)).astype(float)
    out.loc[~ok,:]=np.nan
    return out


def build_features(raw: pd.DataFrame, peer: pd.DataFrame, events: pd.DataFrame):
    x=technical(raw); families={c:'technical' for c in x}
    # Hour records end at their index. The 00:00 4h bar contains (20:00,00:00]
    # completed hourly rows and is not made visible to 21/22/23h decisions.
    four=raw.resample('4h',closed='right',label='right',origin='start_day').agg(
        {'open':'first','high':'max','low':'min','close':'last','volume':'sum','quote_volume':'sum','minutes':'count'})
    four.loc[four.minutes!=4,['open','high','low','close','volume','quote_volume']]=np.nan
    ft=technical(four)[['rsi14','atr14_fraction','adx14','macd_hist_fraction','bollinger_width','bollinger_position']]
    ft=ft.add_prefix('completed_4h_').reindex(x.index,method='ffill')
    for c in ft: x[c]=ft[c];families[c]='technical'
    flow=pd.DataFrame(index=x.index)
    flow['relative_quote_volume']=raw.quote_volume/raw.quote_volume.shift().rolling(168).median()
    for n in [1,3,6,24]:
        flow[f'buy_imbalance_{n}h']=2*raw.taker_quote.rolling(n).sum()/raw.quote_volume.rolling(n).sum()-1
    flow['volume_growth_6h']=raw.quote_volume.rolling(6).sum()/raw.quote_volume.shift(6).rolling(6).sum()-1
    for c in flow: x[c]=flow[c];families[c]='flow'
    lagcols=['rsi14','macd_hist_fraction','bollinger_width','volatility_ratio','buy_imbalance_6h','relative_quote_volume']
    for c in lagcols:
        for lag in [3,6]:
            for suffix,val in [('lag',x[c].shift(lag)),('change',x[c]-x[c].shift(lag))]:
                name=f'seq_{c}_{suffix}{lag}h';x[name]=val;families[name]='sequence'
    context=pd.DataFrame(index=x.index)
    for n in [6,24,168]:
        context[f'peer_return_{n}h']=peer.close/peer.close.shift(n)-1
        context[f'relative_return_{n}h']=raw.close/raw.close.shift(n)-1-context[f'peer_return_{n}h']
    context['peer_correlation_168h']=np.log(raw.close).diff().rolling(168).corr(np.log(peer.close).diff())
    context['own_return_30d']=raw.close/raw.close.shift(720)-1
    context['hour_sin']=np.sin(2*np.pi*x.index.hour/24);context['hour_cos']=np.cos(2*np.pi*x.index.hour/24)
    context['weekend']=(x.index.weekday>=5).astype(float)
    for c in context: x[c]=context[c];families[c]='context'
    news=event_features(x.index,events)
    for c in news: x[c]=news[c];families[c]='fomc'
    x=x.replace([np.inf,-np.inf],np.nan)
    assert not any(c in x for c in ['execution_open','execution_ms','future_return','label'])
    return x,families


def labels(raw: pd.DataFrame, hours=24, threshold=.01):
    ret=raw.execution_open.shift(-hours)/raw.execution_open-1
    # Fail closed on future price/misalignment for labels, not on a past signal.
    timediff=raw.execution_ms.shift(-hours)-raw.execution_ms
    ret=ret.where(timediff==hours*3_600_000)
    y=pd.Series(np.select([ret<=-threshold,ret>=threshold],[0,2],default=1),index=raw.index,dtype=float)
    y[ret.isna()]=np.nan
    return ret,y


def period_mask(index, ret, year):
    a=pd.Timestamp(f'{year}-01-01',tz=TZ)
    b=min(pd.Timestamp(f'{year+1}-01-01',tz=TZ),END)
    # Purge labels crossing training/screening boundaries; audit lacks terminal labels.
    cutoff=b-pd.Timedelta(hours=25) if year in [2024,2025] else b
    return (index>=a)&(index<cutoff)&ret.notna().to_numpy()
