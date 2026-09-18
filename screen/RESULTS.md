# Low-frequency spot strategy screen — actual results, 2026-09-18

## Verdict
The three predeclared primary candidates did NOT establish a reliable positive edge. No live strategy is approved. The preselected price/SMA200 hypothesis (T1_200) reduced historical drawdown, but lower losses are not reliable profitability. All three primary candidates lost money on both BTCUSDT and ETHUSDT in the reused 2025-2026 validation segment. Do not select a profitable sensitivity cell after seeing the results. This is a first trend-family screen, not an exhaustive search of all crypto strategies.

Actual successful Actions run: https://github.com/kenchan-pixel/crypto-backtest-lab/actions/runs/35297157819
Code commit: 840227eb83efdf38ca40ab315141722c13e6f8c5
Protocol SHA-256: 6e7bf5fcb888f6df744fb6af619d2faa9588b166a0007d12d40219ee6af4d097
Original artifact SHA-256: 76353607b2f242d0ef8bf40044a7ba32e5040494ca0543d8386ed1aa7407fb55
Flags: real_data_screen_completed=true; results_notebook_executed=true; market_data_simulated=false; reliable_edge_proven=false; live_approved=false.

## Tested rules and costs
T1_200: previous completed Hong Kong daily close > its 200-calendar-day SMA.
T2_50_200: previous completed 50-day SMA > 200-day SMA.
T3_90: previous completed close > close 90 calendar days earlier.
Each rule checks Monday at 00:00 Hong Kong time and executes at the genuine minute open no earlier than 00:01. Independently reset segments also make an initial allocation check using historical data. A positive signal holds 100% spot; otherwise USDT with no assumed yield. No repeated trade when the target is unchanged. No leverage or shorts. Base cost per side: 0.10% fee + 0.05% adverse slippage, including initial/final orders. The original eight-rule study is unchanged.

## Reused historical validation: 2025-01-01 through 2026-09-14 inclusive
This is not genuinely untouched out-of-sample evidence: this market history was already examined in the eight-rule project.

| Market | Rule | Closed trades | Win rate | Net total return | Observed-minute max drawdown |
|---|---|---:|---:|---:|---:|
| BTCUSDT | Buy and hold | 1 | 0.0% | -17.8% | -54.1% |
| BTCUSDT | Initially 50% coin / 50% cash, no rebalance | 1 | 0.0% | -8.9% | -30.8% |
| BTCUSDT | T1_200 | 4 | 50.0% | -5.9% | -28.2% |
| BTCUSDT | T2_50_200 | 3 | 33.3% | -27.7% | -42.2% |
| BTCUSDT | T3_90 | 4 | 25.0% | -18.2% | -34.9% |
| ETHUSDT | Buy and hold | 1 | 0.0% | -26.7% | -69.5% |
| ETHUSDT | Initially 50% coin / 50% cash, no rebalance | 1 | 0.0% | -13.3% | -41.1% |
| ETHUSDT | T1_200 | 3 | 66.7% | -4.1% | -41.8% |
| ETHUSDT | T2_50_200 | 3 | 66.7% | -22.1% | -46.9% |
| ETHUSDT | T3_90 | 4 | 50.0% | -5.7% | -41.8% |

T1_200 base vs stress net return: BTC -5.9200% vs -7.0422%; ETH -4.0502% vs -4.9099%. Stress is 0.15% fee + 0.15% slippage per side. All 18 predeclared positive-edge tests (3 primary strategies x 2 markets x 3 controls) have Holm-adjusted p=1.0; their pointwise intervals include zero. Lack of significance does not prove every possible version ineffective. Four/three closed trades do not provide strong repeated-trial evidence. Much lower risk can also be achieved by holding less coin, as shown by the half-invested control; its ETH drawdown is slightly smaller than T1's in this segment.

## Full-period description: 2021-01-01 through 2026-09-14 inclusive
| Market | Rule | Closed trades | Net total return | CAGR | Observed-minute max drawdown |
|---|---|---:|---:|---:|---:|
| BTCUSDT | Buy and hold | 1 | +171.8% | +19.2% | -77.5% |
| BTCUSDT | T1_200 | 11 | +141.2% | +16.7% | -38.5% |
| BTCUSDT | T2_50_200 | 6 | +89.6% | +11.9% | -44.2% |
| BTCUSDT | T3_90 | 16 | +223.1% | +22.8% | -49.7% |
| ETHUSDT | Buy and hold | 1 | +239.8% | +23.9% | -81.8% |
| ETHUSDT | T1_200 | 9 | +88.9% | +11.8% | -56.5% |
| ETHUSDT | T2_50_200 | 6 | +8.1% | +1.4% | -66.9% |
| ETHUSDT | T3_90 | 16 | +144.2% | +16.9% | -78.4% |

**Material warmup qualification:** exact Hong Kong daily closing observations are missing on 2020-02-19 and 2020-12-21, both in warmup. The frozen no-imputation rule makes 200-day indicators unavailable at 28 initial/weekly checks in 2021; T1/T2 stay in cash until their required history is complete. This affects full-period comparison with buy-and-hold, which can invest immediately. These are results of the specified data-availability implementation, not an unrestricted conventional SMA backtest. No missing daily-close inputs or delayed strategy orders occur in the 2025-2026 validation segment. Do not attribute the entire full-period drawdown improvement solely to superior trend prediction.

## Data, robustness, and verification
- Official Binance spot minute archives: 95 checksum-verified files per coin, including warmup from 2020-01-01 Hong Kong time. No market data was simulated.
- Research-window observations per coin: 2,998,447 / 2,999,520 minutes (1,073 missing). Gaps are not filled into tradeable prices. There are 0 invalid OHLCV rows under the implemented checks. Drawdown inside missing minutes remains unobserved.
- Two missing daily closes and two potential daily execution delays in the loader summary are both in 2020 warmup, not the 2025-2026 validation period.
- All eleven sensitivity configurations were reported, not optimized: T1 150/200/250; T2 40/200,50/150,50/200,50/250,60/200; T3 60/90/120. All primary cost models and calendar-year results are in the artifact.
- Nine cloud unit tests passed. Independent scalar reconstruction from exported genuine daily inputs verified signal timing, entry/exit timestamps, trade count, exact round-trip costs and daily compounding for 24 primary-strategy/market/segment cases. Four result-notebook code cells executed without errors. Minute drawdown was not independently recomputed from a second raw-data download.
- Non-base cost scenarios and sensitivity drawdowns use daily marks, labelled daily_close. Their resolution differs from the observed-minute base drawdowns.
- USDT/custody risk, intraminute execution and size-dependent impact remain unmodelled. Whole-period profit is not proof of persistent alpha or future returns.

## Deliverables / status
The Actions artifact contains metrics.csv, inference.csv, sensitivity.csv, annual.csv, per-strategy daily returns and trades, official source manifests, quality files, charts, executed_screen.ipynb and reproducible source. The separate research branch and draft PR #1 remain unmerged. This is an executed exploratory screen, not an approved trading system. Further research must address missing warmup observations and use genuinely new forward evidence rather than relabelling the same history as blind validation.
