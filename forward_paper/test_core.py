from datetime import timedelta
import copy,pytest
from forward_paper.core import *
A='2026-09-21T14:00:00+00:00'
def initialized():
 s=fresh_state(A)
 s=set_decision(s,decision_id='d1',committed_at='2026-09-21T14:02:00+00:00',information_cutoff=A,effective_at='2026-09-21T15:00:00+00:00',expires_at='2026-09-28T15:00:00+00:00',ai_weight=1.,simple_weight=.5,packet_sha256='a'*64,rationale='Test fixture only')
 return s
def armed():return arm(initialized(),'2026-09-21T15:00:00+00:00',{k:'b'*64 for k in REQUIRED_GATES})
def signal():return {'id':'s1','model_sha256':MODEL_SHA,'information_cutoff':'2026-09-21T15:00:00+00:00','recorded_at':'2026-09-21T15:02:00+00:00','passes_frozen_threshold':True,'prediction':.02,'evidence_sha256':'c'*64}
def quote(t='2026-09-21T15:03:00+00:00',p=100.):return {'symbol':'ETHUSDT','price':p,'observed_at':t,'source':'synthetic test ONLY','evidence_id':'fixture'}
def test_initial_zero_is_not_performance():
 s=initialized();assert not s['execution_ready'] and s['performance_started_at'] is None
 assert all(v['closed_trades']==0 and v['nav']==10000 for v in snapshot(s).values())
def test_missing_readiness_fails():
 with pytest.raises(ValueError):arm(initialized(),'2026-09-21T15:00:00+00:00',{})
def test_no_early_activation():
 with pytest.raises(ValueError):arm(initialized(),A,{k:'a'*64 for k in REQUIRED_GATES})
def test_no_reset():
 with pytest.raises(ValueError):arm(armed(),'2026-09-21T16:00:00+00:00',{k:'a'*64 for k in REQUIRED_GATES})
def test_allocations_and_roundtrip():
 s=open_opportunity(armed(),signal(),quote(),'2026-09-21T15:03:01+00:00')
 expected=10000/(100*(1.0005)*(1.001));assert s['accounts']['AI_WEEKLY']['eth']==pytest.approx(expected)
 assert s['accounts']['HALF']['eth']==pytest.approx(expected/2)
 end=close_due(s,quote('2026-09-22T15:03:00+00:00',110.),'2026-09-22T15:03:01+00:00')
 r=1.1*.999*.9995/(1.001*1.0005)-1
 assert snapshot(end)['AI_WEEKLY']['net_return']==pytest.approx(r)
 assert snapshot(end)['HALF']['net_return']==pytest.approx(r/2)
 assert all(v['closed_trades']==1 for v in snapshot(end).values())
def test_duplicate_rejected():
 s=open_opportunity(armed(),signal(),quote(),'2026-09-21T15:03:01+00:00')
 with pytest.raises(ValueError):open_opportunity(s,signal(),quote(),'2026-09-21T15:03:01+00:00')
def test_no_backfill():
 sig=signal();sig['recorded_at']='2026-09-21T14:59:00+00:00'
 with pytest.raises(ValueError):open_opportunity(armed(),sig,quote(),'2026-09-21T15:03:01+00:00')
def test_no_future_quote():
 with pytest.raises(ValueError):open_opportunity(armed(),signal(),quote(),'2026-09-21T15:02:01+00:00')
def test_no_stale_quote():
 with pytest.raises(ValueError):open_opportunity(armed(),signal(),quote(),'2026-09-21T15:08:00+00:00')
def test_no_future_return_fill():
 sig=signal();sig['recorded_at']='2026-09-21T15:04:00+00:00'
 with pytest.raises(ValueError):open_opportunity(armed(),sig,quote(),'2026-09-21T15:04:01+00:00')
def test_exit_during_pause_allowed():
 s=open_opportunity(armed(),signal(),quote(),'2026-09-21T15:03:01+00:00');s['execution_ready']=False
 s=close_due(s,quote('2026-09-22T15:04:00+00:00'),'2026-09-22T15:04:01+00:00')
 assert s['accounts']['HALF']['open'] is None
 assert s['ledger'][-1]['accounts']['HALF']['late_seconds']==60

def test_hash_chains_and_id_conflicts():
 s=fresh_state(A);e={'event_id':'x','kind':'fixture'};s=append(s,e);assert append(s,e)==s
 with pytest.raises(ValueError):append(s,{'event_id':'x','kind':'different'})
 s=append(s,{'event_id':'y','kind':'fixture'});assert s['ledger'][-1]['previous_sha']==s['ledger'][0]['sha256']

def test_open_nav_requires_actual_mark():
 s=open_opportunity(armed(),signal(),quote(),'2026-09-21T15:03:01+00:00')
 with pytest.raises(ValueError):snapshot(s)

def test_existing_positions_ignore_new_weekly_size():
 s=open_opportunity(armed(),signal(),quote(),'2026-09-21T15:03:01+00:00');units=s['accounts']['AI_WEEKLY']['eth']
 s=set_decision(s,decision_id='d2',committed_at='2026-09-21T16:02:00+00:00',information_cutoff='2026-09-21T16:00:00+00:00',effective_at='2026-09-21T17:00:00+00:00',expires_at='2026-09-28T17:00:00+00:00',ai_weight=0.,simple_weight=.5,packet_sha256='a'*64,rationale='Test fixture new review')
 assert s['accounts']['AI_WEEKLY']['eth']==units
