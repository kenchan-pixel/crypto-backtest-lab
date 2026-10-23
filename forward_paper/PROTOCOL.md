# ETH parallel forward observation v1 — approved 2026-09-21

## Authorization and source of truth
Ken explicitly accepted a NEW forward paper observation comparing AI weekly management, simple weekly risk control and constant half-size, after reviewing 2025 and combined historical performance. This is an experimental observation authorization, NOT a claim that the old paper gate passed. Preserve all old failed gates, reports and decisions. No real orders, broker account writes, leverage, shorts, deposits, fees paid to a new service, automatic merges or changes to existing Crypto News Collector.

Use existing PR9 branch research/payoff-aware-20260920 and this forward_paper directory. Notion Trading Incubator remains decision/progress SOT; GitHub model/config/runtime/ledger is execution SOT. Do not create another project or retrospective performance record.

## Three separate shadow accounts
Each starts with an assumed virtual 10,000 USDT, zero ETH and zero return; it is not the user's money, wallet or balance.
- AI_WEEKLY: actual assistant chooses 1.0,0.5,0 for new entries using a recorded fresh packet and short rationale. No coded rule may be substituted and labelled AI.
- SIMPLE_WEEKLY: prior30d ETH return >=0 =>1.0, otherwise0.5; unknown => no new trade.
- HALF:0.5 on every valid parent opportunity.
All use the same frozen ETH payoff predictor, threshold, opportunity stream and fixed24h exit; open positions are not resized by a weekly review. Keep a common parent busy-until marker even if AI skips, so skipping cannot unlock extra opportunities. No model refit or strategy switching.

## Model identity gate
Reconstruct the original 2024-only ETH model once from the checksum-bound original sequence artifact. Verify threshold ~0.010189194004167216, JSON prediction equivalence, and exact original54/34 raw-signal timestamps in2025/2026. Export non-executable JSON, no untrusted pickle. Preserve source commits, training count669, frozen vocabulary, full feature-column order and model hash. New observations must not be used in fitting.

## Before performance starts
Require (1) frozen model identity, (2) causal complete live feature builder with replay agreement, (3) current source time/freshness/provenance checks, (4) paper fill/account/duplicate/exit tests, (5) initial genuine weekly AI and simple decisions committed BEFORE eligible entries. Until all are met, execution_ready=false, performance_started_at=null, accounts idle and 0 executed trades. Zero initial balances/P&L are NOT evidence of a running successful strategy. Persist specific readiness blockers. Do not invent model signals from a short chart or treat unavailable news as no-news.

## Forward timing
Collect/verify hourly. Evaluate completed information only; timestamp actual observed_at, information_cutoff, decision_committed_at, effective_at and each observed fill separately. No paper trade may be backdated before initialization or before its signal/weekly choice was saved. If infrastructure cannot meet the historical next-minute-open fill, log actual latency and use only a genuine later observable quote; do not pretend a delayed run traded at the old open. All three accounts share the same fill observations. Fixed24h exits known at entry may be settled on later reads using authenticated actual price evidence at their precommitted exit time; otherwise mark exit pending/late and disclose latency, never fabricate. Gaps cause skipped entries or explicit pending exits, not silent imputation.

## Weekly controls and reporting
A single hourly orchestration task may perform data checks and ledger maintenance, and do the weekly AI review on its first eligible run Monday morning HKT. Weekly decisions take effect no earlier than the next full HKT hour AFTER actual commit; missing/expired AI decision blocks new AI entries (not a synthetic fallback). Initial review can occur after readiness completes, not retrospectively at last Monday. One weekly report: all three accumulated net returns, drawdowns, turnover/fees, exposure, skipped winners/avoided losses, operational gaps and whether AI adds value over both controls. Report whole period and monthly splits; do not declare significance from a few trades. Routine no-change checks are silent; significant data/exit/state failures are reported.

## Costs and duration
Base fee0.10% plus adverse slippage0.05% per side; no assumed USDT yield. Record stress sidecar0.15%+0.15% on identical decisions. AI/subscription overhead unknown; separately report budget sensitivity0/0.01%/0.05% of starting account per actual AI review, including inactive weeks. Initial review horizon12weeks AFTER genuine performance start, not12weeks from this approval; it tests operation and comparative evidence, not proof of edge. No reset, winner selection or live promotion without a new explicit decision. Comparison weights are fractions of each account's own current available NAV/cash, not leveraged notional.

## Failure and audit
Append-only evidence and event IDs, idempotent updates, immutable prior decisions, content hashes and compare-and-swap state writes. Store paper trades only; never invoke Binance/Longbridge order/account endpoints, even testnet. Preserve old upstream findings. Tests using synthetic fixtures are only engineering tests, never forward results. No successful runtime claim unless a current receipt proves it. A scheduled orchestrator alone does not prove the signal engine is live.
