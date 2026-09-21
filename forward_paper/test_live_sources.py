import pytest
from forward_paper.live_sources import normalize_metric_bundle, normalize_funding_history

SYMBOL='ETHUSDT'
OI=[
 {'symbol':SYMBOL,'sumOpenInterest':'2386398.57000000','sumOpenInterestValue':'6541291244.52971500','timestamp':1790004000000},
 {'symbol':SYMBOL,'sumOpenInterest':'2384197.57200000','sumOpenInterestValue':'6514128448.19412000','timestamp':1790004300000},
 {'symbol':SYMBOL,'sumOpenInterest':'2383523.83000000','sumOpenInterestValue':'6511906279.75150000','timestamp':1790004600000},
]
TP=[
 {'symbol':SYMBOL,'longShortRatio':'1.5781','timestamp':1790004000000},
 {'symbol':SYMBOL,'longShortRatio':'1.5786','timestamp':1790004300000},
 {'symbol':SYMBOL,'longShortRatio':'1.5856','timestamp':1790004600000},
]
TA=[
 {'symbol':SYMBOL,'longShortRatio':'1.2707','timestamp':1790004000000},
 {'symbol':SYMBOL,'longShortRatio':'1.2732','timestamp':1790004300000},
 {'symbol':SYMBOL,'longShortRatio':'1.2707','timestamp':1790004600000},
]
AA=[
 {'symbol':SYMBOL,'longShortRatio':'2.3256','timestamp':1790004000000},
 {'symbol':SYMBOL,'longShortRatio':'2.3300','timestamp':1790004300000},
 {'symbol':SYMBOL,'longShortRatio':'2.3234','timestamp':1790004600000},
]
TK=[
 {'buySellRatio':'0.8327','symbol':SYMBOL,'timestamp':1790003700000},
 {'buySellRatio':'0.5631','symbol':SYMBOL,'timestamp':1790004000000},
 {'buySellRatio':'0.6106','symbol':SYMBOL,'timestamp':1790004300000},
]
FUND=[
 {'symbol':SYMBOL,'fundingTime':1789920000000,'fundingRate':'0.00003468'},
 {'symbol':SYMBOL,'fundingTime':1789948800007,'fundingRate':'0.00008166'},
 {'symbol':SYMBOL,'fundingTime':1789977600004,'fundingRate':'0.00008660'},
]

def bundle(**overrides):
 args=dict(symbol=SYMBOL,period='5m',open_interest=OI,top_accounts=TA,top_positions=TP,all_accounts=AA,taker=TK)
 args.update(overrides);return normalize_metric_bundle(**args)

def test_current_public_samples_map_to_archive_contract():
 f=bundle()
 # Taker sample ends one interval earlier; exact intersection must be kept, not forward-filled.
 assert len(f)==2
 assert list(f.columns)==['symbol','sum_open_interest','sum_open_interest_value','count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']
 assert f.iloc[-1].sum_open_interest==pytest.approx(2384197.572)
 assert f.iloc[-1].sum_toptrader_long_short_ratio==pytest.approx(1.5786)
 assert f.iloc[-1].count_toptrader_long_short_ratio==pytest.approx(1.2732)
 assert f.iloc[-1].count_long_short_ratio==pytest.approx(2.3300)
 assert f.iloc[-1].sum_taker_long_short_vol_ratio==pytest.approx(.6106)

def test_one_hour_endpoint_cannot_silently_replace_archive_5m_metrics():
 with pytest.raises(ValueError,match='5m'):
  bundle(period='1h')

def test_missing_family_is_not_imputed():
 with pytest.raises(ValueError,match='No exact common'):
  bundle(taker=[{'buySellRatio':'1','symbol':SYMBOL,'timestamp':1790004900000}])

def test_non_aligned_metric_timestamp_is_rejected():
 bad=[dict(OI[0],timestamp=1790004000001)]
 with pytest.raises(ValueError,match='5m aligned'):
  bundle(open_interest=bad)

def test_symbol_conflict_is_rejected():
 bad=[dict(x,symbol='BTCUSDT') for x in TA]
 with pytest.raises(ValueError,match='Symbol mismatch'):
  bundle(top_accounts=bad)

def test_duplicate_or_out_of_order_source_is_rejected():
 bad=[OI[1],OI[0]]
 with pytest.raises(ValueError,match='unique and increasing'):
  bundle(open_interest=bad)

def test_funding_keeps_actual_settlement_jitter_and_infers_interval():
 f=normalize_funding_history(SYMBOL,FUND)
 assert len(f)==3
 assert f.iloc[1].funding_interval_hours==pytest.approx(8.000001944444444)
 assert f.iloc[2].funding_interval_hours==pytest.approx(7.999999166666667)
 assert f.iloc[-1].last_funding_rate==pytest.approx(.00008660)

def test_funding_negative_rate_is_valid():
 f=normalize_funding_history(SYMBOL,[{'symbol':SYMBOL,'fundingTime':1789977600004,'fundingRate':'-0.00001'}])
 assert f.iloc[0].last_funding_rate<0
