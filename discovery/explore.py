"""Phase 1: inspect training years only. This is hypothesis generation, not validation."""
import json,hashlib,os
from pathlib import Path
import numpy as np
import pandas as pd
from .data import load,features,add_cross,START,TRAIN_END,HOUR,ms
FEATURES=['r1','r4','r24','r168','r720','shock4','vol_ratio','volume_ratio','buy_imbalance','close_location','range_position','vwap_distance','relative24']
HORIZONS=[4,24,72]
FACTOR=(1-.0005)*(1-.001)/((1+.0005)*(1+.001))

def conditions(f):
    up=f.r720>0;down=f.r720<0;crash=f.shock4<=-2;rally=f.shock4>=2
    return {'shock_down':crash,'shock_up':rally,
      'down_shock_up_regime':crash&up,'down_shock_down_regime':crash&down,
      'up_shock_up_regime':rally&up,'up_shock_down_regime':rally&down,
      'down_shock_high_volume':crash&(f.volume_ratio>=2),
      'down_shock_low_volume':crash&(f.volume_ratio<1),
      'up_shock_high_volume':rally&(f.volume_ratio>=2),
      'up_shock_low_volume':rally&(f.volume_ratio<1),
      'new_7d_high':f.breakout7>0,'new_7d_high_high_volume':(f.breakout7>0)&(f.volume_ratio>=2),
      'squeeze_then_breakout':(f.vol_ratio.shift()<.75)&(f.range_position>1),
      'buyers_price_flat':(f.buy_imbalance>=.10)&(f.r1.abs()<.001),
      'sellers_price_flat':(f.buy_imbalance<=-.10)&(f.r1.abs()<.001),
      'cross_asset_catchup':(f.relative24<=-.02)&(f.other_r24>=.02),
      'cross_asset_catchup_up':(f.relative24<=-.02)&(f.other_r24>=.02)&up,
      'relative_leader':(f.relative24>=.02)&(f.other_r24>0),
      'below_vwap_up_regime':(f.vwap_distance<=-.01)&up,
      'below_vwap_down_regime':(f.vwap_distance<=-.01)&down}

def decimate(indices,horizon):
    chosen=[];next_allowed=-1
    for i in indices:
        if i>=next_allowed:chosen.append(int(i));next_allowed=i+horizon
    return np.array(chosen,dtype=int)

def summarize(f,mask,h,condition,coin):
    price=f.execution_open
    gross=price.shift(-h)/price-1
    valid=(f.index>=START)&(f.index<TRAIN_END-pd.Timedelta(hours=h))
    valid&=f.execution_delay_min.eq(0)&f.execution_delay_min.shift(-h).eq(0)&gross.notna()
    baseline=(1+gross)*FACTOR-1
    month=pd.Series(f.index.strftime('%Y-%m'),index=f.index)
    background=baseline.where(valid).groupby(month).transform('mean')
    idx=decimate(np.flatnonzero(np.asarray(mask.fillna(False))&valid),h)
    rows=[]
    for year in [0,2021,2022,2023]:
        take=idx if year==0 else idx[f.index[idx].year==year]
        net=baseline.iloc[take].to_numpy();g=gross.iloc[take].to_numpy();delta=net-background.iloc[take].to_numpy()
        rows.append({'symbol':coin,'condition':condition,'hold_hours':h,'year':year,
         'raw_events':int((np.asarray(mask.fillna(False))&valid).sum()) if year==0 else None,
         'nonoverlap_events':len(take),'mean_gross':np.mean(g) if len(g) else None,
         'mean_net':np.mean(net) if len(net) else None,'median_net':np.median(net) if len(net) else None,
         'win_rate':np.mean(net>0) if len(net) else None,'mean_excess_month_control':np.mean(delta) if len(delta) else None})
    return rows

def execute():
    out=Path('discovery_outputs');out.mkdir(exist_ok=True)
    frames={};quality=[];allrows=[];quantiles={}
    for coin in ['BTCUSDT','ETHUSDT']:
        minute,q=load(coin,TRAIN_END,out);quality.append(q);frames[coin]=features(minute);del minute
    add_cross(frames)
    for coin,f in frames.items():
        f.to_csv(out/f'{coin}_training_features.csv.gz',compression='gzip',index_label='decision_hkt')
        study=f[(f.index>=START)&(f.index<TRAIN_END)]
        quantiles[coin]={}
        masks=conditions(f)
        for feature in FEATURES:
            edges=study[feature].dropna().quantile([.2,.4,.6,.8]).to_numpy()
            if len(np.unique(edges))!=4:continue
            quantiles[coin][feature]=edges.tolist()
            bins=np.digitize(f[feature],edges)
            for group in range(5):masks[f'{feature}_Q{group+1}']=pd.Series((bins==group)&f[feature].notna(),index=f.index)
        for name,mask in masks.items():
            for h in HORIZONS:allrows+=summarize(f,mask,h,name,coin)
    table=pd.DataFrame(allrows);table.to_csv(out/'training_exploration_all.csv',index=False)
    (out/'training_quantiles.json').write_text(json.dumps(quantiles,indent=2))
    pooled=table[table.year==0].groupby(['condition','hold_hours']).agg(mean_net=('mean_net','mean'),
      excess=('mean_excess_month_control','mean'),min_coin_events=('nonoverlap_events','min'))
    annual=table[table.year!=0].groupby(['condition','hold_hours']).agg(min_coin_year_net=('mean_net','min'),
      min_coin_year_events=('nonoverlap_events','min'))
    ranked=pooled.join(annual).sort_values('excess',ascending=False)
    ranked.to_csv(out/'training_ranked_for_hypotheses.csv')
    state={'phase':'TRAINING_EXPLORATION_COMPLETE','training_end_exclusive':str(TRAIN_END),
       '2024_or_later_loaded':False,'simulated_market_data_used':False,
       'explored_cells':int(len(table[table.year==0])),'run_id':os.getenv('GITHUB_RUN_ID'),
       'code_commit':os.getenv('GITHUB_SHA'),'quality':quality,
       'warning':'All displayed feature relations are in-sample hypotheses; no strategy selected or validated yet.'}
    (out/'execution_status.json').write_text(json.dumps(state,indent=2))
    (out/'PROTOCOL.md').write_text(Path('discovery/PROTOCOL.md').read_text())
    print(ranked[ranked.min_coin_events>=30].head(30).to_string(),flush=True)
    print(json.dumps(state,indent=2),flush=True)
if __name__=='__main__':execute()
