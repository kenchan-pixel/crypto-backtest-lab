# Post-2024 volatility hypotheses — frozen after inspecting 2024 only

All candidates are exploratory; previous project-wide exposure to 2025–2026 is not forgotten or declared blind.

The complete 504-cell 2024 conditional event table is retained. This is a selected subset, not 504 independent confirmations. Overlapping forward returns are NOT compounded as a strategy. Mean results include a fixed 0.10% fee and 0.05% slippage per side. Dates with future labels outside 2024 are purged in discovery. The following rules are frozen BEFORE loading the new round's 2025/2026 conditional performance.

## V1: volatility contraction plus discounted price during a declining 30-day trend
At a completed hourly bar: close is at or below its value 720h earlier; realized standard deviation of hourly log returns over 24h divided by the preceding 168h standard deviation is below 0.8; close is more than 1% below the past 24h volume-weighted average price (sum quote volume / sum base volume). Buy that coin next minute, sell 48h after actual entry. One independent position per coin/account, no leverage or additions.

Training-only event evidence (2024): BTC 140 overlapping events, mean 48h net return +1.320%, median +0.919%, 3/4 quarters' means positive; ETH 193, mean +1.151%, median +0.730%, 4/4 quarters positive. Contrary evidence: at 12h both means are negative (-0.216% BTC, -0.212% ETH), and quarter counts are unbalanced. Thus a 48h rebound is only a hypothesis, not an immediately liquid arbitrage.

## V2: relative leadership with volatility expansion in an advancing 30-day trend
Completed hourly close above its value 720h earlier; volatility ratio at least 1.2; that coin's 24h percentage return exceeds the other coin's by more than 2 percentage points. Buy the leading coin next minute; exit 48h later. BTC and ETH are tested separately, not summed as one portfolio. Unlike the old D4 laggard rule, this hypothesis buys strength during an expanding-volatility state.

Training-only evidence: BTC 328 overlapping 48h events, mean +0.996%, median +0.716%, 4/4 quarterly means positive; ETH 261, mean +2.509%, median +2.696%, 3/4 quarters positive. Contrary evidence: ETH Q3 has only five events and a mean near -8.99%; BTC 12h mean is -0.211%, with only one positive quarter. Duration was selected from training data and carries selection risk.

## V3: deterministic two-state switch (not a third independent anomaly)
Buy when V1 OR V2 holds, using the same 48h hold and single-position gate. The two regimes are disjoint due to their opposite 30-day direction. Ignore new signals while holding; no state-based early exit. This tests the practical hypothesis that contraction/rebound and expansion/continuation can coexist without one fixed directional rule. It uses no additional fit, thresholds or performance-based switching. V3 is derived from V1/V2 and must not be treated as independent supporting evidence.

## Comparator and frozen testing
Old D4 (including its mirror BTC control) is reported unchanged, as a comparison only. The primary family is V1/V2/V3 x two coins x cash, buy-and-hold, unconditional same-horizon entry, 31 date shifts =24 comparisons on the 2026 audit. 2025 is shown separately and cannot be ignored. 2024 is in-sample for this new experiment, not a validation result. All parameter sensitivity, higher costs, best-trade concentration and quarterly data are disclosed. No parameter or rule is changed after seeing 2025/2026 outcomes.
