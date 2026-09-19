# Longbridge 宏觀 surprise 增益研究｜2026-09-20

## 結論
已把 Longbridge 214 筆宏觀發布紀錄轉成 35 項因果時間特徵，加入既有 92 項 BTC/ETH 價量、衍生品及環境特徵。2024 訓練、2025 驗證、2026 至 9 月 14 日作重用歷史審核。

**0 個宏觀 feature family 通過預設 2026 多重檢驗門檻；0 條交易規律通過 2026 audit。** 宏觀資料有少量描述性改善，但目前未形成可靠預測或盈利策略。

## Primary 2026 incremental test
Log-loss reduction >0 代表相對既有 92-feature baseline 改善。

| 幣種 | 新增組別 | mean loss reduction | 7-day 95% pointwise interval | Holm(8) p |
|---|---|---:|---:|---:|
| BTC | Inflation | -0.003904 | [-0.010775, +0.002633] | 1.000 |
| BTC | Labour | +0.002629 | [-0.001686, +0.007475] | 0.9415 |
| BTC | Policy rate | 0.000000 | [0,0] | 1.000 |
| BTC | All macro | -0.004101 | [-0.008703, +0.000418] | 1.000 |
| ETH | Inflation | +0.003234 | [-0.002584, +0.009255] | 0.9415 |
| ETH | Labour | +0.000750 | [-0.005243, +0.006741] | 1.000 |
| ETH | Policy rate | 0.000000 | [0,0] | 1.000 |
| ETH | All macro | +0.004846 | [-0.002151, +0.011992] | 0.712 |

沒有一項 corrected p<0.05。28-day grouping only diagnostic.

## Model context
2026 ETH: existing 92-feature log loss 1.166910; +all macro 1.162065 (small descriptive improvement), but unconditional train-frequency prior is 1.102009 and remains better. 2025 ETH: 92-feature 1.092748; +all macro 1.091063; prior 1.098604.

2026 BTC: 92-feature 1.181741; +all macro 1.185842 (worse); prior 1.082234.

Adding an extra 1-hour publication lag weakens/does not stabilize the macro effect: ETH +macro 2026 becomes 1.164568 and 2025 becomes 1.094158. This supports caution about timing sensitivity.

## Interpretable rule screen
The 2024 shallow trees used **no macro feature in any path** for either BTC or ETH. The two rules selected in 2025 are the same price/derivative patterns already seen in the prior study:
- BTC down-risk pattern;
- ETH up pattern using weekday, top-position long/short ratio, 7-day relative underperformance and 30-day return.

There are 19 actual leaves (38 2026 directional tests). No selected rule passes the frozen 2026 audit gate.

ETH selected UP diagnostic account is unchanged in substance:
- 2025: 46 trades, base-cost compounded return -1.60%;
- 2026: 4 trades, base-cost compounded return -3.21%.

Thus macro data did not create a tradable candidate in this run.

## Data and timing
Seven Longbridge indicators: CPI YoY, Core CPI MoM, NFP, unemployment, Core PCE YoY, PPI YoY, Fed Funds target. 214 release records total. Each indicator uses active flag, forecast availability, raw actual-minus-forecast, actual-minus-previous and event age; 35 macro features total.

Release information is first usable at the first full hour strictly after `release_at`; event features expire after 24h. Missing forecasts remain explicitly unavailable, not imputed. Fed Funds forecasts are frequently missing, explaining why its incremental model is effectively unchanged.

The collected forecast fields are not independently certified as original consensus vintages. Historical periods have been studied repeatedly and are not genuine unseen OOS.

## Verification
- Frozen protocol commit: `9fef5a1b856d80e21d93b1cc4cf5fe0a0ed68e3e`.
- Actual successful research commit: `ec5117dfa663d07410cc7941a7456e7215db8f21`.
- GitHub Actions run: 35457093300.
- 22 tests passed.
- Executed notebook SHA256: `d4e06e4a9ba574ae140bc141083e9061c8865496952c10102b619a44803fa2cf`.
- Durable prerelease tag: `research-macro-20260920-ec5117dfa663-a1`.
- Research ZIP SHA256: `a852dca87aafd3cbc062276f69c7ab0444dcf163c2e5c9be088204a6a45626ac`.
- No simulated market data, no live trading approval.

## Next
The macro-surprise layer is worth retaining as context but does not justify strategy promotion. The larger remaining information gap is timestamp-complete news / ETF-flow data or genuinely new forward observations; do not keep adding technical indicators to the same reused history until something becomes significant.
