# Event + Regime Dataset v1 bootstrap — 2026-09-20

## Status
Bootstrap completed successfully on GitHub Actions run 35487384248. This is research infrastructure, not a trading strategy or live approval.

## Outputs
- 47,424 hourly regime rows across BTCUSDT and ETHUSDT for the inherited 2024–2026 research window.
- 356 normalized event rows:
  - 214 retrospective Longbridge macro-release events;
  - 142 unique forward-collected news search hits from the initial 2026-09-20 HKT seed.
- Initial forward news queries: Bitcoin, Ethereum, Bitcoin ETF, SEC crypto.
- Invalid 1970 search timestamps are not used as publication time; the conservative causal timestamp for those items is our own first_seen timestamp.

## Regime dimensions
- 7d and 30d trend
- volatility expansion/compression
- BTC/ETH relative leadership
- funding crowding
- OI leverage build/deleveraging
- top-position long/short crowding
- stable combined regime_id

Future 6h/24h/72h returns and the 24h direction label are outputs only, never regime inputs.

## Verification
Run 35487384248 passed:
- event/regime causal tests;
- inherited derivatives and multifactor regression tests;
- exact durable market-input restore;
- output integrity checks.

Artifact: event-regime-v1-bootstrap
Artifact SHA256: 71cecfbf527363f9ab50c1a34296eb791436c37a2a8c6877820182bff2558194
Manifest:
- hourly_regimes.csv.gz: d6b789f936b2ff34bfbe136e78e8e401f667a90d7bfd04ff423b7f7758784af8
- events.csv: bc425163cb87c8ab3737caeb301707a9674eaec15caf12a74b98eb0b8b709aee
- event_summary.json: 014256d04cf7184552174f3b6c0e2a3d8172bdb82ff29bd5da9a06793c0df5b9
- market_input_checks.json: 3482558296dffe742fc331ecd6f71ffef95aee839a81b049ab2b03d8b25e718c

## Important limits
Historical news is incomplete; only the new forward news collection is treated as point-in-time first-seen evidence. Macro history is retrospective. Existing price/derivatives history has been reused in previous experiments and is not blind OOS.

## Next
Do not mine trading rules yet. Accumulate forward events, enrich each new article with article-detail publication timestamps where available, then mine state -> catalyst -> 1h/6h confirmation -> 6h/24h/72h outcome sequences once enough forward observations exist.
