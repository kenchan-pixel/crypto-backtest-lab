# Sequence Strategy Discovery｜2026-09-20

## Conclusion
A frozen state -> catalyst -> 6h confirmation -> next-24h study produced **3,740 causal sequence events**, but **zero 2025 rules passed the predeclared selection gates** and therefore **zero research candidates** were promoted. The 2026 audit retained all 40 actual leaf-direction tests and produced zero audit passes.

This is a negative but useful result: richer sequence conditions did not create a robust spot-long strategy on the reused 2024–2026 BTC/ETH history.

## Data
Sequence-event counts:
| Coin | 2024 discovery | 2025 screen | 2026 reused audit |
|---|---:|---:|---:|
| BTCUSDT | 660 | 750 | 461 |
| ETHUSDT | 669 | 767 | 433 |

Catalysts included funding crowding transitions, OI leverage-build/deleveraging transitions, volatility expansion, BTC/ETH leader/laggard transitions, positioning crowding transitions, and the 214 historical macro releases already collected.

Forward news collected from 2026-09-20 onward was intentionally excluded from historical selection because its coverage is too short.

## Frozen sequence
The candidate model could use:
- pre-catalyst 7d / 30d trend;
- volatility, BTC/ETH relative state, funding, OI and positioning regime;
- catalyst type/family;
- 6h post-catalyst return;
- 6h confirmation volatility/OI/relative state.

A rule could enter only after the 6h confirmation was complete, at the next-minute execution open, then hold spot for exactly 24h. No leverage, no short, no overlapping position per coin.

## Actual trees
The 2024 discovery trees produced:
- BTC: 11 actual leaves;
- ETH: 9 actual leaves.

Thus the 2026 audit family contained 20 leaves x 2 directions = 40 comparisons.

## 2025 selection
No UP or DOWN rule met all gates simultaneously:
- >=30 non-overlapping events;
- >=8 percentage-point matched lift;
- >=70% matched coverage;
- positive lift in at least 3 quarters;
- positive 2024 lift;
- UP additionally required positive mean after-cost long-event return.

The strongest-looking 2025 effects generally failed because they had too few cases, insufficient matched coverage, weak discovery-period consistency, or negative after-cost payoff.

### Informative near-miss
ETH leaf 14:
`no OI-deleveraging confirmation AND 6h confirmation return > 1.71309% AND pre-catalyst positioning balanced`.

Matched UP lift:
- 2024: +4.54pp; 30 non-overlap events; coverage 72.1%;
- 2025: +6.20pp; 46 events; coverage 83.1%;
- 2026: +12.51pp; 19 events; coverage 51.9%.

It was **not selected** because 2025 lift was below the frozen +8pp threshold. In 2026 it also failed minimum events/coverage and the corrected evidence was not significant (Holm p=1.0). It must not be retroactively promoted because its later numbers look interesting.

BTC leaf 3 was another 2025 near-miss (+7.94pp UP lift, 40 events, 73.4% coverage and positive mean event payoff) but its discovery-period lift was negative and its 2026 lift was approximately zero, reinforcing the need for the chronological gate.

## Verification
Successful optimized Actions run: 35506999400
Scientific protocol frozen before execution: `7b83a4be3b977f97aed2cd8bf9a2c84d7fa3165f`
Final execution commit: `cc0b9d00725f0842e68c8bcd67dd2473ab5c58d8`

The only post-protocol implementation change was vectorizing the same predeclared weekly-cluster bootstrap for runtime; no data, feature, threshold, model, selection gate or result criterion changed.

Run output:
- sequence_rows: 3,740
- selected_2025: 0
- audit_tests: 40
- audit_passes: 0
- research_candidates: 0

Artifact: `sequence-strategy-research-20260920`
Artifact SHA256: `e1208b70c78cd60137d62a40db0c1a0f2d1c46fec0a9c8bfeeda742d370d5736`

Spot input hashes remained:
- BTC: `ae239e8ef6fac21dee8ac648e9ac2b52e699a64002a98d353c567a452ec65b5f`
- ETH: `25e534123a8a4b0154cd378b2841bd89eae0f1904d6ea0e7dfeb6a6440dc029b`

## Research implication
The recurring failure mode is now clearer: several conditions can raise the probability of a +1% move while still failing stability, coverage, or payoff requirements. The next strategy experiment should therefore optimize **after-cost payoff / expected return**, not another directional hit-rate threshold, while the forward Event + Regime collector continues accumulating genuinely new news evidence.
