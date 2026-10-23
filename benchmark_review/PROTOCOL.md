# Frozen ETH payoff model: benchmark and defensive-value review

## Decision baseline
Ken approved a separate relative-performance evaluation: keep the ETH payoff model, score threshold, signals, 24h holding period and prior negative gate result unchanged. Assess whether its lower loss/profit in a falling ETH market is worth further research rather than declaring that it must profit every year. No live orders, new model, threshold search, leverage, automatic merge or new automation. Extend existing PR #9, not another parallel strategy. The current frozen source is 1d934c8b7f6957d2bdc82f8424391b87954ea8ec; the actual strategy run was 35507321273 on 06ac20da9736362f06c5b2988558d676ca5d8b39.

## Inputs and replay
Replay exact exported ETH entry/exit timestamps from the payoff artifact, rather than refitting or selecting different trades. Payoff ZIP SHA256: 12aaeaa9699645db26036a8433e2c5437c3d4dd233507182452b783434b9314c. Genuine ETH hourly closes and next-minute execution opens come from the previous derivatives release, ZIP SHA256: 034aa3a79ea9451868f862d0796cceb158df956b12c1fe3ccf6901ff3fb43051; hourly file SHA256:25e534123a8a4b0154cd378b2841bd89eae0f1904d6ea0e7dfeb6a6440dc029b. Independently spot-check boundary prices using connected Binance spot klines and retain exact responses.

Evaluate 2025-01-01..2026-01-01 exclusive and 2026-01-01..2026-09-15 exclusive in Asia/Hong_Kong. Reset initial capital to 1 for each period as the original study did. Benchmarks enter at Jan1 00:01 and liquidate at the final 23:59 real-minute open (obtained separately); all accounts are observed on the same calendar window, including idle cash time. Also describe the concatenation of the two chronological periods, explicitly retaining year-end reset/benchmark re-entry costs. This is not genuinely unseen OOS.

## Costs, equity and risk
Base per side fee .10% plus adverse slippage .05%; stress .15% plus .15%, identical for comparable orders. USDT cash yield assumed zero, not risk-free USD. Buy quantity=cash/[price*(1+fee)*(1+slippage)], sell receipts=quantity*price*(1-fee)*(1-slippage). Existing strategy proceeds must reproduce exported raw returns, per-trade net returns, cash_after and aggregate returns to numerical tolerance.

Mark all account NAVs on the union of genuine hourly closes and genuine minute execution opens; include pre/post-trade cost marks and exact boundaries. Daily returns include zero-return cash days. Recompute drawdown on this common grid; distinguish any resolution difference from previously reported close-only drawdown rather than claiming a strategy change. No interpolation into missing executable prices. Actual intrahour/tick drawdown remains unobserved.

## Benchmarks fixed before calculation
1. 100% ETH buy-and-hold.
2. Cash/USDT with no yield.
3. Initially 25% ETH / 75% USDT, no rebalancing.
4. Initially 50% ETH / 50% USDT, no rebalancing.
5. Realized-volatility-matched passive mix per period: solve initial ETH fraction in [0,1] so the passive daily NAV volatility matches the frozen strategy's base-cost daily volatility. This uses that period's outcomes and MUST be labelled ex-post diagnostic, never a tradeable ex-ante rule or independently validated benchmark.
6. For 2026 only, apply the volatility-matched initial ETH weight calculated from 2025, without refitting to 2026. This is prior-year-calibrated and historically implementable but does not guarantee identical realized risk in 2026. Its calibration remains conditioned on a retrospectively selected strategy.

No choosing the best benchmark after results. All weights and results are retained.

## Metrics
Net cumulative return; excess return in percentage points and terminal wealth ratio; daily volatility annualized by sqrt(365); descriptive Sharpe/Sortino with zero cash yield; common-grid maximum drawdown and duration; worst day; average coin NAV weight; exact held-time percentage; daily beta to ETH; monthly returns and geometric upside/downside capture with subset counts. Within-year up/down months are descriptive outcome groups, NOT ex-ante market labels. Also report performance conditional on causal 30-day ETH direction (>5%, <-5%, otherwise flat), fixed before each daily interval, without retuning signals.

## Does timing add value?
A predeclared random-entry diagnostic uses 4,999 counterfactual schedules per period, seed 20260921. Preserve actual trade counts by entry quarter, original entry hour, 24h hold, non-overlap and no same-minute re-entry. Randomize dates only within the same quarter, require genuine entry/exit prices inside the study window, and apply identical costs. Keep losing schedules. This uses REAL prices with randomized schedules, not fabricated market observations or claimed real trades. Report actual return percentile, randomized distribution, and empirical upper-tail frequency. It is an exposure/turnover control under limited exchangeability assumptions, not causal proof. Regime distribution need not match exactly; disclose this limitation.

## Inference
For 2026 only, compare paired daily log-growth of strategy against cash, full ETH, fixed25% mix and prior-year-calibrated mix. Circular 7-day block bootstrap,4,999 draws,seed20260921; centered one-sided mean-growth test; four tests in one Holm family. Pointwise95% intervals,28-day diagnostic. Do not use ex-post risk-matching for primary inference. 2025 is descriptive validation; do not turn repeated research history into a blind test. Show broad intervals and sensitivity, not just p-values.

## Interpretation gate
This is a new question, not permission to overwrite the old absolute-profit candidate gate. Separate observed relative defensive value, evidence of incremental timing, cost robustness, and readiness for forward observation. No result in this retrospective benchmark review alone certifies a reliable strategy or authorizes real-money use. Existing upstream review findings and hourly data/vintage limitations remain.

Method reference: CFA Institute, Portfolio Performance Evaluation: appropriate benchmarks, upside/downside capture, drawdown and appraisal limitations. https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation
