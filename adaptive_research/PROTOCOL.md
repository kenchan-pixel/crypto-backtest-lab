# Adaptive multi-factor payoff and risk-budget research — 2026-09-21

## Decision baseline and change
Continue Ken's search, including relative defensive value rather than demanding a profit every calendar year. Preserve the eight-rule, sequence, original payoff, ETH and BTC benchmark results and all existing automations. No live trading, borrowing, shorting, leverage, paid data, merge or new scheduled task. This is one new experiment inside existing PR9, not an in-place change of a failed model.

The identified gap is training/calibration age and portfolio risk: earlier payoff models were trained once on2024 and screened on their own in-sample prediction quantile. Test a monthly rolling model with a strictly later calibration block, and independently isolate position sizing. This is a methodological hypothesis, NOT proof that the old strategy failed because of regime drift.

## True inputs and observation space
Use the exact prior derivatives research ZIP SHA256 034aa3a79ea9451868f862d0796cceb158df956b12c1fe3ccf6901ff3fb43051, preserved original Binance hourly prices/next-minute execution opens, funding/OI/positioning data and official numeric FOMC context. Inherit the original76 plus16 derivatives features with hash-verified source code. Do not add retrospective news or Longbridge consensus vintages. Candidate decisions at completed Hong Kong hours00,06,12,18. This is a different observation space from the earlier catalyst-only model; comparisons between old/new results cannot attribute every difference only to retraining. The within-experiment frozen-model control does isolate updating.

Eligibility uses finite inputs for all92 features, causal annualized volatility and known time; never outcome direction. At each eligible decision, the target is exact next-minute open to24h-later next-minute open return, net of base round-trip costs. Training labels must finish strictly before calibration/fit boundaries. No price or outcome imputation; missing observation cannot cause a fabricated order. Keep all invalid/missing counts. Research scope2024 warmup/training; evaluation2025-01-01..2026-09-15 exclusive Hong Kong time. Last possible entry must leave its full24h exit within the segment. Yearly accounts reset as before.

## Fixed monthly estimator and calibration
One HistGradientBoostingRegressor per coin, max_iter100, learning_rate.05, max_leaf_nodes7, max_depth3, min_samples_leaf60, l2_regularization10, early_stoppingFalse, random_state20260921. No hyperparameter sweep or training sample weights.

At each month start M, use trailing365 calendar days. Fit on [M-365d,M-90d-25h); calibrate on [M-90d,M-25h). Thus every label ends before the next block; last90days are strictly later and not used to fit the trees. Minimum200 fit observations and100 calibration observations; failure yields explicit unavailable predictions/no new positions, never a fabricated result. Mean prediction bias from the calibration block is subtracted from future scores. Entry threshold=max(0,90th percentile of bias-corrected calibration scores). Both correction and threshold are fixed for the entire next month. No 2025/2026 result-based choice. Retain every monthly fit boundary, input count, threshold, error and predictions.

Frozen control uses the identical model/calibration procedure at2025-01-01 and never updates it. This is a NEW matched static control, not the earlier original payoff model. A180-day rolling-history version is declared as descriptive sensitivity only, with the same90-day calibration and minimum sample counts, not a candidate-selecting alternative.

## Three predeclared policies per coin
FROZEN_RISK: fixed Jan2025 model/calibration; risk-capped fractional entry.
ROLLING_FULL: monthly rolling365 model/calibration;100% of current account on eligible entry.
ROLLING_RISK (primary): same rolling365 signals but weight=min(1,0.20/annualized_vol30d). Annualized volatility uses the preceding720 completed hourly log returns, sample standard deviation times sqrt(24*365); minimum720. This is a20%-per-annum exposure budget proxy, not a guarantee of realized portfolio volatility. Weight remains fixed in units until the24h exit. All residual USDT stays idle at zero assumed yield.

One spot position per coin, no overlap, no same-minute re-entry. Entries execute no earlier than next observed minute open; exits at24h. No stop, take-profit, martingale or leverage. Base fee .10% plus slippage .05% per side; stress .15%+.15% per side on identical signal/entry schedules. Cash/quantity accounting must conserve wealth including both costs. Save allocated-account return separately from full-coin return. Missing/zero signals must output full schema with trade_count0 and net_return0.

## Benchmarks and controls
For each coin/year: cash;100% buy/hold;25% and50% initial coin/cash with no rebalancing. Boundaries use exact preserved Binance minute observations from the already completed BTC/ETH benchmark reviews. Common hourly-close/execution-open/pre/post-cost NAV marks, all idle days included. New strategy results must not reuse old trade figures.

Additionally report a passive risk-match with weight calibrated from2025 daily volatility of ROLLING_RISK and applied unchanged in2026, plus same-year ex-post risk match clearly labelled diagnostic. Small drawdown alone does not establish timing skill. Combined equal initial-capital BTC/ETH sleeve results are descriptive, not independently selected portfolios.

## Evaluation before promotion
Report2025 and2026 separately: trades, allocated-account trade win rate/mean/median/PF, compounded net return, hourly-observable MDD, daily volatility, time/average capital exposure, best-trade removal, stress costs, monthly returns, actual versus predicted score calibration.90% training/calibration quantile is NOT a stated probability of winning.

Primary2026 inference: paired daily log-growth ROLLING_RISK versus cash,25% buy/hold,FROZEN_RISK for each coin:6 comparisons in one Holm family.4,999 circular7-day-block bootstrap draws, seed20260921, centered one-sided mean test;28-day diagnostic. Pointwise95% intervals are not simultaneous guarantees. Preserve all results and negative controls. Confidence must not be overstated after repeated searches on the same history.

Promote only to further forward research, not validated/live edge: at least30 trades in2025 and15 in2026; both periods positive under base and stress costs, base PF>1.1, removing best trade still positive;2026 ROLLING_RISK outperforms the prior-year-calibrated passive risk match and has evidence against cash and25% control after the stated correction. Otherwise label insufficient or failed, with relative-defense findings reported separately. Do not loosen the criteria after results.

Sensitivity: risk budget15/25% on the same frozen signals,180-day lookback diagnostic, all base/stress outputs. None may replace the predeclared365/20% main result as the winner.

## Evidence and limitations
Retrospective history2025/2026 has already been read repeatedly. Monthly chronological training prevents local look-ahead but does not make it an untouched holdout. Funding/metrics1h assumed availability lag and archive-vintage limitations persist. No tick depth, size impact, minimum-notional, taxes, exchange-failure or USDT-depeg model. Original zero-signal schema P2 stays open unless separately fixed; new evaluator must test zero-signal cases. No requirement to use GitHub Actions when the same computation can complete locally; execution location and actual tests must be recorded truthfully.

Deliver exact input hashes, source, training chronology, predictions, trades, NAVs, benchmarks, all sensitivity and inference tables, executed notebook and execution receipt. Save a readable result to existing GitHub/Notion SOT and provide the runnable evidence ZIP.

Rationale only, not a replication or promised crypto result: Moreira and Muir, Volatility Managed Portfolios, NBER w22208, https://www.nber.org/papers/w22208 . Chronological evaluation documentation: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html .
