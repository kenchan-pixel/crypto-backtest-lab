# Multi-factor precursor discovery — frozen method, 2026-09-19

## Decision baseline
Ken requests evidence for combinations and sequences BEFORE rises/falls, including technical indicators and available news/environment, before promoting any trading rule. Study BTCUSDT/ETHUSDT from 2024, preserve all old experiments. No live trading, short positions, leverage, paid data, or automatic merge. This is pattern research, not proof of causation or a guaranteed-profit search.

## Inputs and information timing
Reuse the genuine hourly OHLCV/quote/taker-buy series and exact next-minute opens from successful Binance archive run 35336304622, code 51ff63b106e63920f21cc92b5ab7d15b5f5c12af. Original artifact SHA256: 9a93581498e47a09c592db20f1395e85a447dcba198d6e2c98f2417ef61500dd. Verify individual input hashes and monotonic hourly coverage; retain official source/checksum manifests. Underlying minute archive audit is inherited, not falsely claimed re-downloaded in this run. Do not use execution prices, future labels or future availability as predictive inputs.

Official FOMC rate statements: complete regular-decision series in 2024 through 2026-09-14, plus 2023-12-13 warmup. Read original official release dates/times/rate decisions, preserve URL per row, use America/New_York DST, then UTC/Hong Kong. Only information published at least one minute before a decision time may enter features. Thus a 14:00 release first enters the 15:00 hourly decision, not the same-hour past return. Use elapsed release windows and the already announced rate level/change, not future outcomes, market surprise without expectations, or invented news sentiment. General crypto-news corpus feasibility is a separate coverage check; failure/partial access is not 'no news'. FOMC is not representative of all news.

## Labels and chronological partitions
Main target at each hourly decision t: actual next-minute-open to t+24h+1min-open return >=+1%, <=-1%, or between (up/down/neutral). All hourly cases, including failed patterns and neutral returns, enter prediction evaluation. Labels are not model inputs. Secondary 6h and +/-0.5%/2% labels are descriptive checks of already frozen rules only, never alternate winning-model selection.

Training: 2024. Rule screening: 2025. Audit: 2026-01-01 through 2026-09-14, with incomplete terminal labels excluded consistently. Purge 25 hours from training/validation right boundaries. This historical data has been examined before; do NOT claim genuine untouched OOS or forward evidence.

Additional fixed expanding-in-time evaluation: fit the same boosted classifier to the immediately preceding 12 months, purging 25 hours, and predict the next calendar quarter from 2025Q1 through 2026Q3. No random split; train-only scaling/imputation. No post-result changes to hyperparameters or feature set.

## Feature families, computed only from completed bars
1. Technical price/trend/volatility: lagged returns, RSI14, ATR14, ADX14, normalized MACD12/26/9, Bollinger20 position/width, prior-range breakout distances, VWAP distance and completed 4-hour indicators.
2. Volume/order-flow proxies: relative quote volume, taker-buy quote imbalance and trailing multi-hour changes. These are trade-flow proxies, NOT a full order book.
3. Ordered history: previous 3/6-hour RSI, MACD, volatility compression and flow values/changes; the model may discover sequences rather than requiring all contemporaneous values. No sequence is presumed predictive.
4. Cross-market and context: peer returns, relative performance, rolling correlation, own 30-day direction and clock/weekend controls.
5. FOMC environment: past-only rate level/change and post-release timing. No claims of broad headline sentiment coverage.

## Fixed models, not a parameter hunt
Unconditional class-probability baseline; standardized multinomial logistic regression C=0.1; single decision tree max_depth=4, max_leaf_nodes=10, min_samples_leaf=168; histogram gradient boosting max_iter=100, learning_rate=0.05, max_leaf_nodes=7, max_depth=3, min_samples_leaf=168, l2_regularization=10, early_stopping=False. Seed 20260919. Fit each coin separately. No hyperparameter sweep or selecting a favourable test period.

Compare out-of-period log loss, multiclass Brier score, directional AUC and calibration, not accuracy alone. Refit boosted model after removing each feature family using identical settings, recording ablation changes without tuning. The quarterly rolling model tests adaptation, not a claim that changing the training window creates alpha.

## Rule evidence and counterexamples
Extract every leaf/path from the 2024-trained tree. For each path report up/down frequencies, all signal-hour counts, non-overlapping 24h event count, mean/median forward and after-cost return, false alarms, quarter-by-quarter results and conditions. Compare with non-signal cases in the same quarter, own 30-day direction and 2024-defined volatility tercile (minimum 30 control hours per stratum). This is retrospective control evaluation, not information fed to trading.

Bootstrap 1,999 weekly clusters for approximate pointwise confidence intervals and one-sided positive probability-lift tests, recomputing matched-control probabilities per replicate. All leaf x direction x coin tests in the audit form a single Holm family (up to 40). Record the whole family; prior experiments and model/rule selection bias are NOT erased by this correction. Overlapping hours are not independent trades. A 28-day grouping is an uncertainty diagnostic, never a replacement chosen for significance.

A rule is selected BEFORE inspecting its 2026 performance only if 2025 has at least 30 non-overlapping cases, matched lift >=5 percentage points, >=70% matched coverage, positive lift in at least 3 quarters and positive 2024 lift. Up rules additionally require positive mean next-day return after base costs. Rank qualifying rules by 2025 matched lift, at most one up and one down per coin. If none qualify, no invented candidate. Inspect 2026 with the same rule and gates (30 non-overlapping events, >=70% matching, positive lift in at least two quarters and corrected p<.05 for stronger evidence). Any surviving rule remains a research candidate pending genuinely new forward data.

Only selected UP patterns may get a diagnostic spot/cash 24h-hold account, one position at a time, no same-minute reentry; per-side 0.10% fee +0.05% adverse slippage, stress 0.15%+0.15%. Down patterns are risk alerts, not simulated unauthorized short trading. Clearly label hourly-observable drawdown; it is NOT minute-level or intraminute worst drawdown. Preserve loss concentration and best-trade removal diagnostics. This first acceptance is a pattern-evidence table; no qualified pattern means no promotion to trading strategy.

## Deliverables
Reproducible source and executed notebook; input provenance, timestamp/label tests, feature dictionary, all model/ablation/quarter scores, all tree paths and probability evidence/counterexamples, selection gates, news-source coverage limitations. Concise Chinese conclusion that separates useful prediction, tradable edge and insufficient evidence. Methods may only change for documented correctness bugs, not profitability.

Primary documentation: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm ; official linked rate statements; https://github.com/binance/binance-public-data ; https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html .
