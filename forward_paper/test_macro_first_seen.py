import copy,json
from pathlib import Path
import pytest

from forward_paper.macro_first_seen import EXPECTED, merge_ledger, normalize_capture

CAPTURE=Path(__file__).parent/'inputs/macro_first_seen_20260922T031843HKT.json'

def real_capture():return json.loads(CAPTURE.read_text())

def timely():
 c=real_capture();c['batch_first_seen_at_utc']='2026-09-11T12:35:00+00:00'
 # Keep only one row fresh by moving the other historical releases after first_seen would be invalid,
 # so convert every non-empty row to the same causal test release while preserving indicator mapping.
 for i in c['indicators']:
  if i['latest'] is not None:
   i['latest']['period']='2026-09-01';i['latest']['release_at']='2026-09-11T12:30:00Z'
 return c

def test_real_capture_covers_all_seven_and_does_not_backdate_stale_rows():
 n=normalize_capture(real_capture())
 assert len(n['events'])==6
 assert len(n['empty_indicators'])==1
 assert n['empty_indicators'][0]['indicator']=='core_pce_yoy'
 assert n['empty_indicators'][0]['forward_interpretation']=='unknown_not_no_event'
 assert n['forward_eligible_event_count']==0
 assert n['late_bootstrap_event_count']==6
 assert all(e['usable_at_utc'] is None for e in n['events'])
 assert all(e['first_seen_at_utc']=='2026-09-21T19:18:43.656843+00:00' for e in n['events'])

def test_timely_first_seen_only_becomes_usable_next_full_hour():
 n=normalize_capture(timely())
 assert n['forward_eligible_event_count']==6
 assert all(e['usable_at_utc']=='2026-09-11T13:00:00+00:00' for e in n['events'])

def test_capture_must_cover_exact_frozen_indicator_set():
 c=real_capture();c['indicators']=c['indicators'][:-1]
 with pytest.raises(ValueError):normalize_capture(c)
 c=real_capture();c['indicators'][0]['indicator_code']='wrong'
 with pytest.raises(ValueError):normalize_capture(c)

def test_future_release_relative_to_first_seen_is_rejected():
 c=timely();c['indicators'][0]['latest']['release_at']='2026-09-11T12:36:00Z'
 with pytest.raises(ValueError):normalize_capture(c)

def test_zero_count_never_synthesizes_macro_event():
 n=normalize_capture(real_capture())
 assert all(e['indicator']!='core_pce_yoy' for e in n['events'])

def test_historical_macro_sign_semantics_are_preserved():
 n=normalize_capture(timely())
 by={e['indicator']:e for e in n['events']}
 assert by['core_cpi_mom']['sign']=='positive'
 assert by['cpi_yoy']['sign']=='inline'

def test_no_forecast_is_explicit_not_guessed():
 c=timely();fed=next(x for x in c['indicators'] if x['indicator']=='fed_funds_target');fed['latest']['forecast_value']=None
 n=normalize_capture(c);e=next(x for x in n['events'] if x['indicator']=='fed_funds_target')
 assert e['sign']=='no_forecast' and e['surprise_raw'] is None

def test_first_seen_ledger_never_overwrites_initial_values():
 first=normalize_capture(timely());ledger=merge_ledger(None,first)
 revised=timely();revised['batch_first_seen_at_utc']='2026-09-11T13:35:00+00:00'
 row=next(x for x in revised['indicators'] if x['indicator']=='core_cpi_mom');row['latest']['actual_value']='0.4'
 later=normalize_capture(revised,max_forward_lag_minutes=180)
 out=merge_ledger(ledger,later)
 event=next(v for v in out['events'].values() if v['indicator']=='core_cpi_mom')
 assert event['actual']==0.3
 assert event['first_seen_at_utc']=='2026-09-11T12:35:00+00:00'
 assert event['later_revisions'][0]['changed_fields']['actual']==0.4

def test_replaying_identical_capture_is_idempotent():
 n=normalize_capture(real_capture());a=merge_ledger(None,n);b=merge_ledger(a,n)
 assert a==b
