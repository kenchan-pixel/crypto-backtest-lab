import pandas as pd
from forward_paper.opportunity_parity import build_catalysts,collapse_threshold,parent_nonoverlap
TZ='Asia/Hong_Kong'
def idx(n=60):return pd.date_range('2026-01-01',periods=n,freq='h',tz=TZ)
def base():
 i=idx();return pd.DataFrame({'funding_state':['normal']*len(i),'oi_state':['stable']*len(i),'vol_state':['normal']*len(i),'cross_asset_state':['aligned']*len(i),'positioning_state':['balanced']*len(i)},index=i)
def test_transition_cooldown_is_per_state_family():
 r=base();r.loc[r.index[2],'funding_state']='crowded_long';r.loc[r.index[4],'funding_state']='crowded_long';r.loc[r.index[28],'funding_state']='crowded_long'
 rows=build_catalysts(r,pd.DataFrame(columns=['event_type']))
 got=[t for t,c,_,_ in rows if c=='funding_state:crowded_long']
 assert got==[r.index[2],r.index[28]]
def test_simultaneous_threshold_collapse_prefers_prediction_then_name():
 t=pd.Timestamp('2026-01-02',tz=TZ);d=pd.DataFrame([
 {'year':2026,'entry_hkt':t,'catalyst_hkt':t-pd.Timedelta(hours=6,minutes=1),'confirmation_hkt':t-pd.Timedelta(minutes=1),'catalyst_type':'z','predicted_net':.02},
 {'year':2026,'entry_hkt':t,'catalyst_hkt':t-pd.Timedelta(hours=6,minutes=1),'confirmation_hkt':t-pd.Timedelta(minutes=1),'catalyst_type':'a','predicted_net':.03},
 ])
 x=collapse_threshold(d,.01,2026);assert len(x)==1 and x.iloc[0].catalyst_type=='a'
def test_tie_break_uses_catalyst_name():
 t=pd.Timestamp('2026-01-02',tz=TZ);d=pd.DataFrame([
 {'year':2026,'entry_hkt':t,'catalyst_hkt':t-pd.Timedelta(hours=6,minutes=1),'confirmation_hkt':t-pd.Timedelta(minutes=1),'catalyst_type':'z','predicted_net':.02},
 {'year':2026,'entry_hkt':t,'catalyst_hkt':t-pd.Timedelta(hours=6,minutes=1),'confirmation_hkt':t-pd.Timedelta(minutes=1),'catalyst_type':'a','predicted_net':.02},
 ])
 assert collapse_threshold(d,.01,2026).iloc[0].catalyst_type=='a'
def test_parent_busy_is_inclusive_at_prior_exit_decision():
 t=pd.Timestamp('2026-01-01',tz=TZ)
 d=pd.DataFrame([
 {'entry_hkt':t+pd.Timedelta(hours=6,minutes=1),'confirmation_hkt':t+pd.Timedelta(hours=6),'catalyst_hkt':t,'catalyst_type':'a'},
 {'entry_hkt':t+pd.Timedelta(hours=30,minutes=1),'confirmation_hkt':t+pd.Timedelta(hours=30),'catalyst_hkt':t+pd.Timedelta(hours=24),'catalyst_type':'b'},
 {'entry_hkt':t+pd.Timedelta(hours=31,minutes=1),'confirmation_hkt':t+pd.Timedelta(hours=31),'catalyst_hkt':t+pd.Timedelta(hours=25),'catalyst_type':'c'},
 ])
 x=parent_nonoverlap(d);assert list(x.catalyst_type)==['a','c']
