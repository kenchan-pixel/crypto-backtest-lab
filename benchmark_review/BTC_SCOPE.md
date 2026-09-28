# BTC extension of the frozen benchmark review — 2026-09-21

Ken asked for the corresponding BTC evaluation after the ETH defensive-value review. Apply the existing benchmark_review/PROTOCOL.md methods unchanged to BTCUSDT, not a newly fitted or tuned model.

Replay original BTC payoff-model trades: 51 in 2025 and 32 in 2026 (both numbers known before this extension), fixed 24h holding periods and original execution times. Use the exact original Payoff_Aware_Research_20260920.zip (SHA256 12aaeaa9699645db26036a8433e2c5437c3d4dd233507182452b783434b9314c) and BTC hourly input SHA256 ae239e8ef6fac21dee8ac648e9ac2b52e699a64002a98d353c567a452ec65b5f from the prior derivative bundle (034aa3a79ea9451868f862d0796cceb158df956b12c1fe3ccf6901ff3fb43051). Independently read Binance spot minute candles at the same calendar boundaries; preserve those observed rows.

Periods remain 2025 full year and 2026-01-01 through 2026-09-14 inclusive, Hong Kong time. Enter passive holdings at Jan1 00:01 and exit at the final 23:59 minute open. Base per-side costs .10% fee+.05% adverse slippage; stress .15%+.15%; cash earns zero. Same-grid hourly close and execution-open pre/post-cost NAV marks.

Controls unchanged: full BTC, cash, 25%/50% initial BTC passive mixes, ex-post volatility-matched passive mix, and 2026 use of the initial weight calibrated solely on 2025 volatility. Do not reuse ETH's 43% weight for BTC. Risk matching is not matching every risk; same-year matching is diagnostic and not ex-ante.

Repeat the same fixed-seed 4,999 randomized real-price schedules per year/cost, preserving quarter counts, entry-hour multiset, 24h duration and non-overlap. They are counterfactual schedules, not synthetic prices. Same four primary 2026 paired daily log-growth tests, seven-day block bootstrap/Holm, with28-day diagnostic. Record all results without modifying gates or selecting another model.

Reuse the reviewed ETH computational source by explicit symbol/hash/label substitutions only, retaining a manifest of original and adapted code. Original model and ETH outputs remain unchanged. The BTC exercise is retrospective and after viewing old strategy returns; it is not blind validation. Do not assert a completed GitHub run unless actually executed; container-only execution must be labelled accordingly. No real trading, auto-merge, new schedule or paid service.
