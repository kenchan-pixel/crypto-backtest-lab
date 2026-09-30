# Event + Regime Dataset v1 — frozen schema, 2026-09-20

## Purpose
Build a causal dataset for discovering sequences such as **market state -> catalyst -> confirmation -> later outcome**. This dataset is evidence infrastructure, not a trading strategy and not a live-order system.

## Time rule
Every row must state when its information became usable. Future outcomes are labels only and must never enter features. Forward news uses our own `first_seen_at_hkt` as the conservative availability time unless an independently checked article detail provides an earlier valid publication timestamp. A search-list placeholder such as 1970 is invalid and stored as null.

## 1. Hourly regime table
One row per symbol x completed Hong Kong hour.

Core identity:
- `decision_hkt`
- `symbol`
- `close`

Causal numeric state:
- 24h / 7d / 30d return
- 24h realized volatility and ratio to trailing 30d median
- 168h BTC/ETH correlation
- 24h relative return versus peer
- settled funding rate per hour and its trailing z-score
- 24h open-interest log change and trailing z-score
- top-position long/short log ratio and trailing z-score
- taker ratio log value

Deterministic regime labels:
- `trend_30d`: up / flat / down using +/-5%
- `trend_7d`: up / flat / down using +/-2%
- `vol_state`: expanded if vol-ratio >1.25, compressed if <0.75, else normal
- `cross_asset_state`: leader if peer-relative 24h return >2pp, laggard if <-2pp, else aligned
- `funding_state`: crowded_long if funding z>1.5, crowded_short if z<-1.5, else normal
- `oi_state`: leverage_build if OI-change z>1, deleveraging if z<-1, else stable
- `positioning_state`: long_crowded if position-ratio z>1.5, short_crowded if z<-1.5, else balanced
- `regime_id`: stable concatenation of the above categorical states

Rolling z-scores/medians use only observations available at or before the current decision hour; minimum history is required and unavailable states remain `unknown`.

Outcome columns are labels only:
- forward 6h / 24h / 72h return
- >=+1%, <=-1% 24h direction label
- `outcome_ready_at_hkt`

## 2. Event table
One row per normalized event occurrence.

Fields:
- `event_id`: deterministic SHA-256-based id
- `event_type`: macro / news
- `event_subtype`: indicator or normalized topic
- `source`
- `first_seen_at_hkt`
- `published_at_utc` (nullable)
- `usable_at_hkt`: conservative timestamp used for causal joins
- `timestamp_quality`: verified_detail / macro_release / first_seen_only / invalid_placeholder
- `title`, `url`, `asset_tags`, `query`
- macro: actual / forecast / previous / raw surprise
- `content_hash`
- `is_forward_collected`

Historical Longbridge macro rows are retrospective and `is_forward_collected=false`. News snapshots collected from 2026-09-20 onward are `true`.

## 3. Sequence table — generated later, never hand-labelled for profit
A candidate sequence links:
1. regime at event usable time;
2. event/catalyst;
3. post-event confirmation measured after a fixed delay;
4. later outcome.

Initial confirmation windows to *describe*, not optimize: 1h and 6h.
Outcome windows: 6h, 24h, 72h.

Sequence mining must keep counterexamples and same-regime controls. No candidate becomes a strategy until it is frozen and tested on genuinely later data.

## Provenance
- Market/derivative history comes from prior durable research releases and their hashes.
- Macro history comes from the frozen Longbridge collection on the parent branch.
- Forward news snapshots are append-only research records. Re-running a search must create a new snapshot, not overwrite the old one.
