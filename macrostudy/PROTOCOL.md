# Macro-surprise incremental test — frozen 2026-09-20

## Question
Does adding timestamped US macro releases and actual-minus-forecast surprises improve BTCUSDT/ETHUSDT 24-hour direction prediction beyond the existing 92-feature price/flow/derivatives model?

This is an incremental-information experiment, not a strategy hunt. Prior results remain unchanged. No live trading, leverage, shorts, paid data, parameter sweep, auto-merge, or post-result threshold tuning.

## Data and chronology
- Reuse the exact spot/derivatives inputs and causal feature code from the successful derivatives research lineage.
- Add Longbridge macro records already frozen on this branch: CPI YoY, core CPI MoM, NFP, unemployment rate, core PCE YoY, PPI YoY, Fed funds target.
- Preserve each release_at, actual, forecast, previous and unit exactly as collected. No missing forecast imputation.
- A release may first affect an hourly decision at the first full hour strictly after release_at. Add a conservative +1h availability stress version separately.
- A release is “active” for 24h; after that its event-specific feature returns to inactive. Absence of an active release is a known zero state, not missing data.
- NFP scale/unit is left exactly as returned. Indicator-specific values are never directly pooled as one raw magnitude.

## Fixed macro features
For each of 7 indicators:
1. active flag;
2. forecast_available flag;
3. raw surprise = actual - forecast, else 0 with availability flag 0;
4. actual-minus-previous, else 0;
5. event age / 24 while active, else 0.

35 added features total. The model may learn indicator-specific interactions; no hand-coded “hawkish/bullish” sign assumptions.

Predeclared grouped increments:
- Inflation: CPI YoY, core CPI MoM, core PCE YoY, PPI YoY.
- Labour: NFP, unemployment.
- Policy: Fed funds target.
- All macro: all 7.

## Target and partitions
Same target as previous study: next genuine minute-open to 24h-later minute-open return: down <= -1%, neutral, up >= +1%.
Training 2024; validation 2025; reused audit 2026-01-01 through 2026-09-14 with the existing 25h right-edge purge. These periods are historical and previously studied; they are not blind OOS.

## Fixed models and primary comparison
Primary model is the unchanged constrained HistGradientBoostingClassifier from derivatives.study.
Baseline = existing 92 features.
Compare baseline plus Inflation, Labour, Policy, and All-macro on identical eligible rows.
Primary inference: per-observation log-loss reduction on 2026, 1,999 circular/calendar 7-day cluster bootstrap replicates, fixed seed 20260919, 8-test Holm family (4 increments x 2 coins). 28-day block result is diagnostic only.
Also report multiclass Brier, up/down AUC and calibration. Logistic and shallow-tree baseline-vs-All are diagnostic only and do not enlarge the primary family.

No “best macro family” becomes a trading strategy from score improvement alone. A family must first beat baseline after correction; beating the unconditional prior is separately required before describing the full model as useful probability prediction.

## Interpretable rule screen
Fit one shallow tree per coin with baseline+all macro on 2024 only. Extract every actual leaf/path.
Use the same matched-control evidence method and same 2025 selection gates as the derivative study:
>=30 non-overlap cases, matched lift >=5pp, coverage >=70%, >=3 positive quarters, positive 2024 lift; up rules also need positive mean after-cost long-event return.
Select at most one up/down per coin before reading 2026 path outcomes.
2026 audit gate unchanged: >=30 non-overlap cases, >=70% coverage, >=2 positive quarters, positive lift, corrected p<.05 across every actual leaf x direction x coin test.
Only a selected UP path gets a diagnostic spot/cash 24h account with the existing base/stress costs. Down paths remain risk alerts, not shorts.

## Robustness
- Release +1h additional availability-lag stress for baseline vs All-macro.
- Remove each macro group from All as a diagnostic, not a model-selection route.
- Report event counts and forecast-missing counts by indicator/year.
- Preserve all negative results and counterexamples.
- No news text is included in this model. News snapshots remain a separate prospective-data track because historical search completeness is not established.

## Acceptance
Deliver source, exact macro event file/hash, input provenance, model scores, 8 primary increment tests, calibration, all paths/evidence, any diagnostic account, executed notebook and a completion receipt. If no macro increment or rule survives, say so without changing the model or feature definitions.
