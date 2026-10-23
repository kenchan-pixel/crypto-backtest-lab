"""Historical replay parity for the frozen parent-opportunity stream.

This validator reconstructs catalysts/features/signals WITHOUT using future target,
post-confirmation return, or execution-price columns to make any decision. The old
right-edge/year guard is used only to compare against the finite historical
artifact; it is not part of live eligibility.
"""
from __future__ import annotations
import argparse,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np,pandas as pd
from .features import TARGETS,FAMILY,sequence_features
from .model import load,predict

TZ='Asia/Hong_Kong'
CATS=['catalyst_type','catalyst_family','trend_30d','trend_7d','vol_state','cross_asset_state','funding_state','oi_state','positioning_state','confirmation_bucket']
NUMS=['confirmation_return_6h','confirm_vol_expanded','confirm_oi_leverage_build','confirm_oi_deleveraging','confirm_cross_leader','confirm_cross_laggard']
HIST_END=pd.Timestamp('2026-09-15',tz=TZ)

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_zip_csv(path,name,gzip=False):
    with zipfile.ZipFile(path) as z:
        return pd.read_csv(io.BytesIO(z.read(name)),compression='gzip' if gzip else None)

def macro_sign(row):
    if pd.isna(row.forecast) or pd.isna(row.actual): return 'no_forecast'
    d=float(row.actual)-float(row.forecast)
    return 'positive' if d>0 else ('negative' if d<0 else 'inline')

def build_catalysts(regimes,events):
    rows=[]
    for col,targets in TARGETS.items():
        prev=regimes[col].shift()
        for target in targets:
            last=None
            for t in regimes.index[(regimes[col]==target)&(prev!=target)]:
                if last is None or t>=last+pd.Timedelta(hours=24):
                    rows.append((t,f'{col}:{target}',FAMILY[col],'endogenous'));last=t
    for _,r in events[events.event_type.eq('macro')].iterrows():
        t=pd.Timestamp(r.usable_at_hkt)
        t=t.tz_localize(TZ) if t.tzinfo is None else t.tz_convert(TZ)
        if t in regimes.index:
            rows.append((t,f'macro:{r.event_subtype}:{macro_sign(r)}','macro','macro'))
    return sorted(rows,key=lambda x:(x[0],x[1]))

def history_comparable(t,regimes):
    """Finite-artifact comparison guard only; never use this in forward runtime."""
    t6=t+pd.Timedelta(hours=6);t30=t+pd.Timedelta(hours=30)
    return t6 in regimes.index and t30.year==t.year and t30<HIST_END

def reconstruct(regimes,events,model):
    out=[]
    for t,ctype,family,origin in build_catalysts(regimes,events):
        if not history_comparable(t,regimes): continue
        f=sequence_features(regimes,t,ctype,family)
        score=float(predict(model,f))
        out.append({'catalyst_hkt':t,'confirmation_hkt':t+pd.Timedelta(hours=6),
                    'entry_hkt':t+pd.Timedelta(hours=6,minutes=1),'exit_hkt':t+pd.Timedelta(hours=30,minutes=1),
                    'year':t.year,'catalyst_type':ctype,'catalyst_family':family,'catalyst_origin':origin,
                    **{k:f[k] for k in CATS if k not in ('catalyst_type','catalyst_family')},
                    **{k:f[k] for k in NUMS},'predicted_net':score})
    return pd.DataFrame(out).sort_values(['catalyst_hkt','catalyst_type']).reset_index(drop=True)

def collapse_threshold(df,threshold,year):
    d=df[(df.year==year)&(df.predicted_net>=threshold)].copy()
    if d.empty:return d
    return d.sort_values(['entry_hkt','predicted_net','catalyst_type'],ascending=[True,False,True]).drop_duplicates('entry_hkt',keep='first').sort_values('entry_hkt').reset_index(drop=True)

def parent_nonoverlap(df):
    keep=[];last_exit=None
    for i,r in df.sort_values('entry_hkt').iterrows():
        entry=pd.Timestamp(r.confirmation_hkt);exit_=pd.Timestamp(r.catalyst_hkt)+pd.Timedelta(hours=30)
        if last_exit is not None and entry<=last_exit:continue
        keep.append(i);last_exit=exit_
    return df.loc[keep].reset_index(drop=True)

def keys(df):
    return [(pd.Timestamp(t).isoformat(),str(c)) for t,c in zip(df.catalyst_hkt,df.catalyst_type)]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--event',required=True);ap.add_argument('--sequence',required=True);ap.add_argument('--payoff',required=True);ap.add_argument('--model',default='forward_paper/model.json');ap.add_argument('--out',required=True);a=ap.parse_args()
    regimes=read_zip_csv(a.event,'hourly_regimes.csv.gz',True);events=read_zip_csv(a.event,'events.csv')
    regimes=regimes[regimes.symbol.eq('ETHUSDT')].copy();regimes['decision_hkt']=pd.to_datetime(regimes.decision_hkt,utc=True).dt.tz_convert(TZ);regimes=regimes.sort_values('decision_hkt').set_index('decision_hkt')
    expected=read_zip_csv(a.sequence,'sequence_events.csv.gz',True);expected=expected[expected.symbol.eq('ETHUSDT')].copy()
    raw=read_zip_csv(a.payoff,'raw_signals.csv.gz',True);raw=raw[raw.symbol.eq('ETHUSDT')].copy()
    trades=read_zip_csv(a.payoff,'trades.csv');trades=trades[(trades.symbol.eq('ETHUSDT'))&(trades.cost.eq('base'))].copy()
    for d in (expected,raw,trades):
        for c in ['catalyst_hkt','confirmation_hkt','entry_hkt','exit_hkt']:
            if c in d:d[c]=pd.to_datetime(d[c],utc=True).dt.tz_convert(TZ)
    model=load(a.model);got=reconstruct(regimes,events,model)
    if keys(got)!=keys(expected.sort_values(['catalyst_hkt','catalyst_type'])):raise AssertionError('Complete catalyst stream mismatch')
    exp=expected.sort_values(['catalyst_hkt','catalyst_type']).reset_index(drop=True)
    for c in CATS:
        if not (got[c].astype(str).to_numpy()==exp[c].astype(str).to_numpy()).all():raise AssertionError('Categorical feature mismatch: '+c)
    numeric_error={c:float(np.max(np.abs(got[c].to_numpy(float)-exp[c].to_numpy(float)))) for c in NUMS}
    if max(numeric_error.values())>1e-12:raise AssertionError('Numeric feature parity failed')
    signal_counts={};executed_counts={};pred_error={};same_time_discarded={};busy_skipped={}
    for year in (2025,2026):
        collapsed=collapse_threshold(got,model['threshold'],year);want=raw[raw.year.eq(year)].sort_values('entry_hkt').reset_index(drop=True)
        if keys(collapsed)!=keys(want):raise AssertionError(f'Raw-signal stream mismatch {year}')
        pe=float(np.max(np.abs(collapsed.predicted_net.to_numpy(float)-want.predicted_net.to_numpy(float)))) if len(want) else 0.
        if pe>1e-12:raise AssertionError(f'Prediction parity failed {year}')
        executed=parent_nonoverlap(collapsed);want_t=trades[trades.year.eq(year)].sort_values('entry_hkt').reset_index(drop=True)
        if keys(executed)!=keys(want_t):raise AssertionError(f'Parent non-overlap stream mismatch {year}')
        pre=got[(got.year==year)&(got.predicted_net>=model['threshold'])]
        signal_counts[str(year)]=len(collapsed);executed_counts[str(year)]=len(executed);pred_error[str(year)]=pe
        same_time_discarded[str(year)]=len(pre)-len(collapsed);busy_skipped[str(year)]=len(collapsed)-len(executed)
    # Enumerate every historically comparable confirmation hour, including hours with no catalyst/signal.
    hours=[]
    for cut in regimes.index:
        t=cut-pd.Timedelta(hours=6)
        if t in regimes.index and history_comparable(t,regimes):hours.append(cut)
    candidate_hours=set(got.confirmation_hkt);signal_hours=set(got.loc[got.predicted_net>=model['threshold'],'confirmation_hkt'])
    receipt={'passed':True,'scope':'Historical complete ETH parent-opportunity replay parity only; NOT live readiness/performance.',
      'decision_columns_excluded':['target','post_confirm_return_24h','event_long_net_base','execution_open','execution_exit'],
      'historical_right_censor_guard_comparison_only':True,'sequence_rows':len(got),'expected_sequence_rows':len(exp),
      'catalyst_key_mismatches':0,'numeric_feature_max_abs_error':numeric_error,'signal_counts':signal_counts,
      'executed_counts':executed_counts,'prediction_max_abs_error':pred_error,'same_time_threshold_candidates_discarded':same_time_discarded,
      'parent_busy_signals_skipped':busy_skipped,'eligible_confirmation_hours':len(hours),
      'hours_without_any_catalyst':sum(h not in candidate_hours for h in hours),'hours_without_threshold_signal':sum(h not in signal_hours for h in hours),
      'sequence_zip_sha256':sha(a.sequence),'payoff_zip_sha256':sha(a.payoff),'event_zip_sha256':sha(a.event),
      'model_sha256':hashlib.sha256(Path(a.model).read_bytes()).hexdigest(),'performance_started':False,'paper_trades_created':0}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
