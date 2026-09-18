# Low-frequency crypto candidate screen — 2026-09-18

## Status and decision baseline
This is a NEW exploratory research round requested by Ken after the eight-rule study. It does not change, rescue, overwrite, or reclassify any of the eight original rules. No live execution, wallet, API key, borrowing, short sale, leverage, or paid data. The existing study is the source of scope and cost assumptions, not evidence that the new rules work.

Question: can a simple, low-turnover spot strategy improve on passive holding after costs? Positive absolute return, higher return than buy-and-hold, and lower drawdown are separate outcomes. A lower allocation can also reduce drawdown; include an initially 50%-invested passive account as a diagnostic control. No guaranteed-profit claim.

## Frozen candidates, before executing this screen
Preferred hypothesis chosen before results: T1, the 200-calendar-day price/SMA trend filter. Independently test BTCUSDT and ETHUSDT; do not add their returns as a portfolio.
- T1: previous completed Hong Kong daily close above its 200-day simple moving average => hold spot; otherwise hold USDT.
- T2: previous completed 50-day SMA above the 200-day SMA => hold spot; otherwise USDT.
- T3: previous completed daily close above the close 90 calendar days earlier => hold spot; otherwise USDT.
All check once each Monday at 00:00 Hong Kong time; execute no earlier than 00:01 at the observed minute open. Each independently reset evaluation segment also makes an initial allocation check using only already completed data. No new trade while the target position is unchanged. No stop/target optimized after results. These exact lengths and weekly timing are research assumptions, not claims of exact paper replication.

Descriptive sensitivity, no best-cell selection:
T1 lengths 150/200/250; T2 pairs 40/200, 50/150, 50/200, 50/250, 60/200; T3 lengths 60/90/120. Eleven unique variants, three primary candidates. Report all, including losses.

## Data and execution
Official Binance spot 1-minute monthly ZIPs and daily tail; verify each official CHECKSUM and retain source URL, byte SHA-256, download time and quality counters. Research period stays 2021-01-01 to 2026-09-15 exclusive, Hong Kong time. Warmup starts 2020-01-01 (longer solely because daily trend indicators require it). Parse ms/us timestamps, minute alignment, 12 numeric columns, OHLC relationships, volumes, integer trade count, ordering and duplicates. No invented prices; large real returns are not removed. Legacy anomalous close-time metadata is disclosed separately; open_time governs the minute identity.

Daily indicators use the exact 23:59 minute close, not an earlier last observation. An interior minute gap does not erase an observed daily close, but is disclosed and the minute drawdown is not claimed observable inside the gap. Missing daily-close input => no signal until its necessary history is complete. Missing execution minute => use first genuine later minute in that day and count the delay; an entirely missing day blocks the research. Prices and returns are USDT-denominated; USDT is not risk-free USD and earns no assumed interest.

Each strategy has its own initial capital 1, either 100% spot or 100% USDT. Buy units = cash/[open*(1+slippage)*(1+fee)]; sell cash = units*open*(1-slippage)*(1-fee). Initial and final costs included. Final close is forced at the last observed minute open of the requested segment; no new entry there. Benchmarks: cash; 100% buy-and-hold; initially 50% spot + 50% cash with no rebalancing.
Costs per side: base 0.10% fee + 0.05% adverse slippage; low 0.075%+0.02%; stress 0.15%+0.15%; zero 0%+0%. Primary metrics use all observed minute opens/closes for drawdown, not exact intraminute tick extremes. Sensitivity drawdowns may use daily endpoints and must be labelled. Market impact, minimum notional and exchange failure are not fully modelled.

## Validation, inference and labels
IS: 2021-2023. Validation: 2024. Historical validation segment: 2025-2026-09-14, labelled OOS_REUSED. Full period and each calendar year are descriptive, independently reset. No parameters are fitted or selected using the later segment. This is NOT genuinely untouched OOS: the same market history was already examined in the eight-rule research. Genuine forward evidence must come after the freeze; no three-day sample is used to claim validation.

Primary inference: 4,999 circular block bootstraps, 28 calendar-day blocks, fixed seed 20260918. Test each primary candidate's mean daily log growth relative to cash, 100% buy-and-hold and 50% buy-and-hold on OOS_REUSED; 18 tests form one Holm family. Confidence intervals are pointwise, not family-adjusted. Block lengths 7 and 56 are diagnostic only. Serial dependence, few market cycles, shared exposure and post-research strategy selection remain limitations. Report closed-trade count, win rate, mean/median trade returns, PF, net compounded return, CAGR, annualized daily volatility and Sharpe (zero cash yield), minute max drawdown, exposure and cost stress.

No candidate receives a reliable-edge or live-approved label solely from this screen, even with a positive historical return or an adjusted p-value. Low-frequency sample counts do not inherit independent-minute sample size; do not silently waive the old study's confidence gates or count millions of minutes as millions of independent trials. Outcomes are descriptive: potential follow-up candidate, no demonstrated benchmark improvement, or insufficient evidence. If no candidate passes, say so; do not add or retune candidates after viewing results in this round.

## Research rationale and limits
- Liu & Tsyvinski, Risks and Returns of Cryptocurrency, NBER w24877 (2018; journal version 2021): evidence of crypto time-series momentum, not proof of this exact long-only weekly 200-day rule. https://www.nber.org/papers/w24877
- Moskowitz, Ooi & Pedersen, Time Series Momentum (2012): multi-asset futures evidence; not a directly transferable spot-crypto backtest. https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum
- Rozario et al., A Decade of Evidence of Trend Following Investing in Cryptocurrencies (2020 preprint): supports investigating trend following, but its reported returns are not copied as our results. https://arxiv.org/abs/2009.12155
- Predictability of cryptocurrency returns: evidence from robust inference (2022): significance can weaken under dependence/heterogeneity-robust inference. https://doi.org/10.1515/demo-2022-0111
- Binance official archive documentation: https://github.com/binance/binance-public-data

Re-run: install screen/requirements.txt; pytest screen/test_screen.py; python -m screen.study. Raw data remain ephemeral and are not committed or uploaded in result artifacts.
