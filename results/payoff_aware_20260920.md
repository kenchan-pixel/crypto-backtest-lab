# Payoff-aware Sequence Strategy｜2026-09-20

## Conclusion
This experiment changed the target from directional hit-rate to **expected after-cost spot return** using the same causal state/catalyst/6h-confirmation features.

**No coin passes the frozen candidate gate.** However, ETH is the strongest near-miss seen in the current research series: 2025 is profitable under both base and stress costs, but the effect decays in 2026 and does not survive concentration/stress/statistical requirements.

## Frozen model
Per coin, one fixed HistGradientBoostingRegressor is trained on 2024 event sequences. Target = exact 24h spot return after the 6h confirmation, net of base costs.

Frozen signal threshold = max(0, 90th percentile of 2024 training predictions):
- BTCUSDT: 0.9746% predicted base-cost net return
- ETHUSDT: 1.0189%

The threshold, model, 24h hold and feature set were frozen before 2025/2026 evaluation.

## Actual strategy results

| Coin / period | Trades | Base compounded | Stress compounded | Base PF | Base best-trade removed | Weekly audit |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2025 | 51 | -9.27% | -22.14% | 0.824 | -15.05% | validation fail |
| BTC 2026 | 32 | -19.99% | -27.32% | 0.562 | -25.58% | Holm p=0.9155 |
| ETH 2025 | 45 | **+25.42%** | **+9.58%** | **1.584** | **+4.69%** | validation pass on payoff criteria |
| ETH 2026 | 26 | **+1.62%** | -6.00% | 1.099 | -5.76% | Holm p=0.8580 |

2026 is through 2026-09-14 and uses historical data previously seen elsewhere in this project. It is not blind OOS.

## Why ETH is not promoted
The frozen candidate gate required 2026:
- >=15 trades: pass (26)
- base compounded return >0: pass (+1.62%)
- stress compounded return >0: **fail (-6.00%)**
- base profit factor >1.10: **fail narrowly (1.0986)**
- best-trade-removed compounded return >0: **fail (-5.76%)**
- corrected weekly-cluster p<0.05: **fail (0.858)**

So the apparent 2025 edge materially weakens in 2026.

## What the ETH model is selecting
This is a model score, not a single hand-written rule. Among raw ETH threshold signals:

2025 catalyst mix:
- OI: 23
- cross-asset BTC/ETH state transitions: 15
- funding: 8
- positioning: 5
- macro: 3

2026:
- OI: 16
- cross-asset: 6
- funding: 4
- volatility: 3
- macro: 3
- positioning: 2

Most selected ETH signals occur after a strong 6h move and with non-extreme/short-biased positioning rather than long-crowded positioning. This is descriptive; removing a weak-looking catalyst family now would be post-hoc and is not used to create another same-history winner.

## Payoff concentration / model ranking
ETH:
- 2025 win rate 55.6%, mean net trade +0.604%, median +0.229%, max hourly-observable drawdown -22.38%.
- 2026 win rate 53.8%, mean +0.111%, median +0.225%, max drawdown -16.85%.

Predicted-vs-realized rank correlation is weak/unstable:
- 2025: -0.174
- 2026: +0.199

Thus the model's high-score ordering is not yet a reliable payoff ranking.

## Inference
2026 weekly-cluster one-sided tests:
- BTC p=0.9155, Holm=0.9155, 95% pointwise mean-return interval roughly [-1.53%, +0.32%]
- ETH p=0.4290, Holm=0.8580, interval roughly [-1.02%, +1.31%]

28-day diagnostics are limited by too few clusters.

## Verification
Protocol frozen at:
`a2e2c9dc87abc8c2219e6b8fc5c8c94e13345620`

Successful Actions run:
`35507321273`

Execution commit:
`06ac20da9736362f06c5b2988558d676ca5d8b39`

Artifact:
`payoff-aware-research-20260920`

Artifact SHA256:
`12aaeaa9699645db26036a8433e2c5437c3d4dd233507182452b783434b9314c`

No simulated market data, no leverage, no shorts and no live approval.

## Research implication
This is the first recent experiment where ETH shows a substantial 2025 after-cost payoff (+25.4%, +9.6% under stress) rather than only a classification-probability lift. But the 2026 decay is strong enough that the frozen gate rejects it.

The correct next use is **forward monitoring of the frozen ETH payoff model**, not another same-history threshold/family optimization. New Event + Regime observations and the forward news collector can provide genuinely later evidence.
