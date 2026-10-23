"""Pure, paper-only accounting. No HTTP client and no brokerage/order API.
Input observations and authorization must be persisted by the orchestrator.
"""
from __future__ import annotations
import copy, hashlib, json, math
from datetime import datetime, timedelta, timezone

ARMS=('AI_WEEKLY','SIMPLE_WEEKLY','HALF')
MODEL_SHA='08f2ba34b48d2aa5925af90c13452a34efbb0dc0f88d4694caa330bdf832c3fe'
REQUIRED_GATES=('model_identity','live_feature_parity','source_freshness','accounting_tests','initial_decisions')

def stamp(value: str) -> datetime:
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('Timezone required')
    return t.astimezone(timezone.utc)

def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def fresh_state(now: str, capital: float=10000.) -> dict:
    stamp(now)
    if not math.isfinite(capital) or capital<=0: raise ValueError('Invalid virtual capital')
    return {'schema':'eth-paper-v1','created_at':now,'status':'COMMISSIONING',
      'research_authorized':True,'execution_ready':False,'performance_started_at':None,
      'live_orders_allowed':False,'model_sha256':MODEL_SHA,'gates':{k:False for k in REQUIRED_GATES},
      'accounts':{n:{'initial_virtual_usdt':capital,'cash':capital,'eth':0.,'open':None,'realized_pnl':0.,'trades':0} for n in ARMS},
      'parent_busy_until':None,'processed_events':{},'ledger':[],'decision':None}

def append(state: dict,event: dict) -> dict:
    s=copy.deepcopy(state);event=copy.deepcopy(event)
    key=event['event_id']
    if key in s['processed_events']:
        previous=s['processed_events'][key]
        if previous!=hashlib.sha256(canonical(event)).hexdigest(): raise ValueError('Conflicting repeated event ID')
        return s
    event_sha=hashlib.sha256(canonical(event)).hexdigest()
    record={**event,'previous_sha':s['ledger'][-1]['sha256'] if s['ledger'] else None}
    record['sha256']=hashlib.sha256(canonical(record)).hexdigest()
    s['ledger'].append(record);s['processed_events'][key]=event_sha
    return s

def set_decision(state:dict, *, decision_id:str, committed_at:str, information_cutoff:str,
                 effective_at:str, expires_at:str, ai_weight:float, simple_weight:float,
                 packet_sha256:str, rationale:str) -> dict:
    if ai_weight not in (0.,.5,1.) or simple_weight not in (.5,1.): raise ValueError('Invalid weekly allocation')
    cut,commit,effect,expiry=map(stamp,[information_cutoff,committed_at,effective_at,expires_at])
    if not cut<=commit<effect<expiry: raise ValueError('Noncausal decision timestamps')
    if effect.minute!=0 or effect.second!=0 or effect.microsecond!=0: raise ValueError('Effect starts on next full hour')
    if effect<commit.replace(minute=0,second=0,microsecond=0)+timedelta(hours=1):raise ValueError('Insufficient decision lag')
    if not rationale or len(packet_sha256)!=64: raise ValueError('Evidence/rationale required')
    if state.get('decision') and commit<=stamp(state['decision']['committed_at']): raise ValueError('Old/repeated decision cannot overwrite')
    event={'event_id':decision_id,'kind':'weekly_decision','committed_at':committed_at,'information_cutoff':information_cutoff,
       'effective_at':effective_at,'expires_at':expires_at,'weights':{'AI_WEEKLY':ai_weight,'SIMPLE_WEEKLY':simple_weight,'HALF':.5},
       'packet_sha256':packet_sha256,'rationale':rationale}
    s=append(state,event);s['decision']=event;return s

def arm(state:dict, now:str, gate_receipts:dict) -> dict:
    if set(gate_receipts)!=set(REQUIRED_GATES) or not all(isinstance(x,str) and len(x)==64 for x in gate_receipts.values()):
        raise ValueError('Every readiness gate requires verified evidence hash')
    now_dt=stamp(now);d=state.get('decision')
    if not d or not stamp(d['effective_at'])<=now_dt<stamp(d['expires_at']): raise ValueError('Initial decisions not yet effective')
    if state['performance_started_at'] is not None: raise ValueError('Never reset existing performance')
    s=copy.deepcopy(state);s['gate_receipts']=gate_receipts;s['gates']={k:True for k in REQUIRED_GATES}
    s['execution_ready']=True;s['status']='OBSERVING';s['performance_started_at']=now
    return append(s,{'event_id':'performance-start','kind':'start','observed_at':now,'gate_receipts':gate_receipts})

def validate_quote(quote:dict,now:str):
    t,observed=stamp(now),stamp(quote['observed_at'])
    px=float(quote['price'])
    if quote.get('symbol')!='ETHUSDT' or not math.isfinite(px) or px<=0:raise ValueError('Invalid ETH quote')
    if not timedelta(0)<=t-observed<=timedelta(seconds=120):raise ValueError('Stale/future quote')
    if not quote.get('source') or not quote.get('evidence_id'):raise ValueError('Quote provenance missing')
    return px,observed

def open_opportunity(state:dict,signal:dict,quote:dict,now:str,fee=.001,slippage=.0005) -> dict:
    if not state['execution_ready'] or not state['performance_started_at']:raise ValueError('Not commissioned')
    if signal['model_sha256']!=MODEL_SHA:raise ValueError('Changed model prohibited')
    t=stamp(now);price,seen=validate_quote(quote,now)
    cut,committed=stamp(signal['information_cutoff']),stamp(signal['recorded_at'])
    if not stamp(state['performance_started_at'])<=cut<=committed<seen<=t:raise ValueError('Backdated signal or predecision quote')
    if t-cut>timedelta(minutes=90):raise ValueError('Signal too late; record skipped, never backfill')
    if len(signal.get('evidence_sha256',''))!=64:raise ValueError('Signal evidence missing')
    if not signal.get('passes_frozen_threshold') or not math.isfinite(float(signal.get('prediction',float('nan')))) or float(signal['prediction'])<0.010189194004167217:raise ValueError('No parent opportunity')
    eid='entry:'+signal['id']
    if eid in state['processed_events']:raise ValueError('Duplicate opportunity')
    if state['parent_busy_until'] and seen<=stamp(state['parent_busy_until']):raise ValueError('Parent stream busy')
    if state.get('last_exit_observed_at') and seen.replace(second=0,microsecond=0)<=stamp(state['last_exit_observed_at']).replace(second=0,microsecond=0):raise ValueError('Same-minute reentry prohibited')
    d=state['decision']
    if not stamp(d['effective_at'])<=t<stamp(d['expires_at']):raise ValueError('Weekly decisions absent/expired')
    if not (0<=fee<.01 and 0<=slippage<.01):raise ValueError('Invalid research cost')
    s=copy.deepcopy(state);due=(seen+timedelta(hours=24)).isoformat();detail={}
    for name in ARMS:
        a=s['accounts'][name];w=d['weights'][name]
        if a['open'] is not None or a['eth']!=0:raise ValueError('Duplicate open position')
        if w==0:detail[name]={'weight':0,'skipped':True};continue
        spend=a['cash']*w;qty=spend/(price*(1+slippage)*(1+fee));a['cash']-=spend;a['eth']=qty
        a['open']={'id':signal['id'],'entry_at':quote['observed_at'],'due_at':due,'spend':spend,'entry_reference':price,'weight':w,'fee':fee,'slippage':slippage}
        detail[name]={'weight':w,'spend':spend,'quantity':qty}
    s['parent_busy_until']=due
    return append(s,{'event_id':eid,'kind':'paper_entry','observed_at':now,'signal':signal,'quote':quote,'due_at':due,'accounts':detail})

def close_due(state:dict,quote:dict,now:str) -> dict:
    t=stamp(now);price,seen=validate_quote(quote,now)
    if not state['parent_busy_until'] or t<stamp(state['parent_busy_until']):raise ValueError('Not due')
    s=copy.deepcopy(state);details={};ids=set()
    for name in ARMS:
        a=s['accounts'][name];p=a['open']
        if p is None:continue
        if seen<stamp(p['due_at']):raise ValueError('Quote before predetermined exit')
        proceeds=a['eth']*price*(1-p['slippage'])*(1-p['fee']);pnl=proceeds-p['spend']
        a['cash']+=proceeds;a['eth']=0.;a['realized_pnl']+=pnl;a['trades']+=1;a['open']=None
        details[name]={'proceeds':proceeds,'realized_pnl':pnl,'due_at':p['due_at'],'late_seconds':(seen-stamp(p['due_at'])).total_seconds()};ids.add(p['id'])
    if len(ids)>1:raise ValueError('Inconsistent shared opportunity')
    if not ids:raise ValueError('No open positions; do not create repeated empty exits')
    s['last_exit_observed_at']=quote['observed_at']
    event_id='exit:'+next(iter(ids)) if ids else 'empty-exit:'+s['parent_busy_until']
    # Keep busy-until through due time; the next actual fill must be later.
    return append(s,{'event_id':event_id,'kind':'paper_exit','observed_at':now,'quote':quote,'accounts':details})

def snapshot(state:dict,price:float|None=None) -> dict:
    out={}
    for n,a in state['accounts'].items():
        if a['eth'] and (price is None or not math.isfinite(price) or price<=0):raise ValueError('Open NAV needs valid mark')
        nav=a['cash']+a['eth']*(price or 0.)
        out[n]={'virtual_cash':a['cash'],'eth_quantity':a['eth'],'nav':nav,'net_return':nav/a['initial_virtual_usdt']-1,'closed_trades':a['trades']}
    return out
