# Longbridge macro/news collection — 2026-09-20

Purpose: add point-in-time macro surprises and forward news snapshots to the existing BTC/ETH precursor research without changing prior strategy results.

## Collected historical macro releases
Release window: 2024-01-01 through 2026-09-14. Raw responses are preserved verbatim under `raw/`; `normalized/macro_events.json` contains 214 normalized events with raw actual-minus-forecast surprises.

| Indicator | Code | Rows |
|---|---|---:|
| US CPI YoY | 30771871 | 32 |
| US Core CPI MoM | 30771844 | 31 |
| US Nonfarm payroll change | 30771890 | 33 |
| US Unemployment rate | 30771865 | 32 |
| US Core PCE YoY | 30771724 | 32 |
| US PPI final demand YoY | 30771924 | 33 |
| Fed funds target rate | 30771885 | 21 |

Fields retained where Longbridge returned them: period, release_at, actual_value, forecast_value, previous_value, unit, importance. Missing forecasts/months are not filled.

### Important causal-use limits
- `release_at` can be used to prevent using a release before it appeared in this dataset.
- The historical forecast value is useful as a candidate surprise feature, but this collection does **not** independently certify the original consensus-vintage methodology or later revisions.
- Do not compare raw surprise magnitudes across indicators. Standardize using training-only history inside each indicator.
- NFP values/units are kept exactly as returned. Do not silently infer “thousands” despite conventional reporting until independently verified.
- This is retrospective history already inside the broader research era; it is not a new blind forward sample.

## News collection
Longbridge keyword news search works. Current Bitcoin/ETF search results are snapshotted under `news_snapshots/`, and five article details were saved to preserve article-level publication timestamps.

Known limitation: search-list timestamps were observed as 1970 placeholders while `news_detail` returned usable `published_at` on sampled articles. Every article used as a model feature must therefore be expanded via detail and timestamp-checked. The exposed search action has no date-range parameter, so this collection does not claim a complete 2024–2026 historical news corpus.

## Market-data limitation
Recent candlesticks work, but the connected account's dated historical-candlestick request returned error 301607 with history quota limit 0. Historical ETF/equity prices must not be inferred from the recent-bar endpoint.

## Next research use
The next model increment should first test macro surprises as a distinct feature family on the same eligible BTC/ETH hourly rows. Compare baseline vs +macro on identical dates, then only promote a rule if later-period evidence improves after multiple-testing correction and transaction costs. News should be accumulated prospectively unless a timestamp-complete historical corpus becomes available.
