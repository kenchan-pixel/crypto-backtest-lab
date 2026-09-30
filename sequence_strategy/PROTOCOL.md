# Sequence Strategy Discovery — frozen 2026-09-20

## Goal
Discover interpretable BTC/ETH spot-long candidates from **market state -> catalyst -> 6h confirmation -> next-24h outcome**, using Event + Regime Dataset v1 and exact next-minute execution prices. This is exploratory historical research on reused data, not blind OOS and not live approval.

## Information timing
- Regime state at catalyst hour uses only completed information available by that hour.
- Confirmation is the price/regime response over the next 6 completed hours.
- A candidate can enter only after the 6h confirmation is fully known, at the next available minute open.
- Exit is fixed 24h after entry.
- No same-minute re-entry, no overlapping position per coin, no leverage, no shorts.
- Costs per side: base 0.10% fee + 0.05% adverse slippage; stress 0.15% + 0.15%.

## Catalyst family
Endogenous catalysts are state transitions into an extreme condition, with a 24h same-catalyst cooldown:
1. funding -> crowded_long / crowded_short
2. OI -> leverage_build / deleveraging
3. volatility -> expanded
4. BTC/ETH relative state -> leader / laggard
5. positioning -> long_crowded / short_crowded

Macro catalysts are the 7 Longbridge macro indicators already stored. Surprise sign is descriptive only:
- positive if actual > forecast
- negative if actual < forecast
- inline if equal
- no_forecast if unavailable

Forward-collected news is **not used for historical candidate selection yet** because coverage begins only on 2026-09-20 and is too short. It remains forward validation evidence for later.

## Sequence features
At catalyst hour:
- catalyst_type and catalyst_family
- trend_30d, trend_7d
- vol_state
- cross_asset_state
- funding_state
- oi_state
- positioning_state

At +6h confirmation:
- exact completed-hour close return from catalyst hour close
- confirmation bucket: strong_down <= -1%, down (-1%,-0.25%), flat [-0.25%,0.25%], up (0.25%,1%), strong_up >=1%
- whether volatility is expanded at +6h
- whether OI is leverage_build/deleveraging at +6h
- whether cross-asset state is leader/laggard at +6h

The target is the exact next-minute-open return from entry after confirmation to 24h later:
- up >= +1%
- down <= -1%
- neutral otherwise

## Chronology
- 2024: discovery only.
- 2025: candidate selection.
- 2026 through 2026-09-14: reused historical audit.
All target windows crossing period boundaries are purged.

## Fixed discovery model
Per coin, train one interpretable decision tree on 2024 event sequences:
- max_depth=4
- max_leaf_nodes=12
- min_samples_leaf=30
- random_state=20260919
Categorical sequence fields are one-hot encoded with a fixed lexicographic vocabulary learned from the full frozen schema, not from outcome performance.
No parameter sweep.

All actual leaf paths are retained.

## Candidate evidence
For each leaf and direction, compare event outcomes against **same catalyst-family and same quarter** control events not in that leaf. Require >=20 controls in each eligible stratum.

Before reading 2026 leaf outcomes, select at most one UP and one DOWN rule per coin from 2025:
- >=30 non-overlapping 24h events
- matched probability lift >= +8 percentage points
- matched coverage >=70%
- lift positive in >=3 quarters
- 2024 matched lift >0
- UP only: mean single-event long net return after base costs >0

Rank qualifying rules by 2025 matched lift; deterministic leaf id tie-break.

## 2026 audit
Selected rule passes stronger audit only if:
- >=20 non-overlapping 24h events
- matched coverage >=70%
- positive lift in >=2 quarters
- positive matched lift
- one-sided 7-day-cluster bootstrap p<.05 after Holm correction over all actual leaf x direction x coin tests
28-day clusters are diagnostic only.

## Trading diagnostic
Only a selected UP rule gets a spot/cash account:
- enter next minute after 6h confirmation
- fixed 24h hold
- ignore new signals while holding
- no same-minute re-entry
Report trade count, win rate, mean/median, profit factor, compounded return, hourly-observable max drawdown, base/stress costs, and best-trade removal concentration.

DOWN patterns are risk alerts only; no short-profit simulation.

## Acceptance
A candidate can be called a **research candidate** only if it passes the 2026 audit and has positive base- and stress-cost diagnostic return in both 2025 and 2026. Otherwise preserve it as a failed/insufficient pattern.

No result from this reused history is “validated live edge.” A surviving candidate must next be frozen for forward observation using the Event + Regime collector.
