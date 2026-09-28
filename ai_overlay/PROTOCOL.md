# Weekly LLM management overlay — frozen 2026-09-21

## Approved goal and boundary
Ken approved trying AI analysis that manages a strategy weekly, then paper trading only if the trial is acceptable. This is NOT another numerical-model retrain labelled AI. The assistant itself will read causal weekly packets and explicitly choose new-entry capital weights; software only prepares packets, checks decisions and replays accounts. Preserve the frozen ETH payoff signal/24h exit engine, failed BTC and old results. No new entry signal, leverage, shorts, real-money orders, paid API, automatic merge or changes to existing news automation.

## Limited historical pilot
Evaluate the existing ETH long-only payoff model over 2025-01-01 through 2026-09-14 inclusive, HKT, separate capital1 for each year as before. Historical raw signals/trades and market inputs are inherited with exact hashes from prior evidence. The strategy was fitted on2024. This replay explicitly does NOT test free-form weekly strategy rewrites, news-reading alpha or BTC. Macro records are retrospective; complete time-stamped crypto news is unavailable and is not filled with invented stories.

Decisions at year start and each Monday00:00HKT. Only information completed by the cut is permitted. A generous computation lag makes each decision effective01:00HKT; before the first effective decision use half size. A week decision affects only later entries; open positions retain original size and24h exit. Weeks with no parent signals still require a decision. Skipped original entries do not unlock other suppressed parent signals: an offline capital overlay on the frozen exported executable opportunities, not a complete rerun of alternative signal-generation logic.

## Actual AI decision, not coded rule substitution
At each step the assistant receives one packet only, then writes its decision and a short evidence-grounded rationale to an append-only hash-linked ledger before the next packet is exposed. No future week return, entry schedule or unclosed trade outcome is included. Calendar dates and absolute price are hidden from the displayed packet to reduce recognition; true dates remain in the audit mapping. The assistant already has project history in conversation and may have pretrained historical knowledge, so this is NOT blind, fresh-session, point-in-time-model or contamination-free evidence. Masking is mitigation only. No regenerated alternative LLM responses or outcome-based revisions.

Allowed new-entry weights:1.0 maintain original size,0.5 reduce,0 pause. Fixed management rubric: default1.0 absent a grounded reason to change;0.5 when independent price/flow/positioning or macro evidence materially conflicts;0 only for convergent severe downside stress or unavailable/stale required data. Negative30d trend alone is not sufficient AI analysis. Account for rebound opportunities and costs of missing recoveries. Do not interpret one or two losing trades as statistical proof. No claim to quantify a calibrated probability. Save brief rationale and source packet hash, not hidden chain-of-thought.

Packets use genuine past ETH/BTC7/30d changes, realized volatility and trailing-median ratio, drawdown from past30d high, taker imbalance, settled funding and trailing z-score, open-interest and positioning information (same1h assumed availability lag as prior study), and realized frozen-parent trade performance over prior28/90days only. Macro actual/forecast differences and age may be shown when released before the cut, with vintage limitation. No raw unrelated news corpus or remembered event names are allowed in reasoning. No current-web historical outcome searches during decision generation.

## Controls on the same opportunities and dates
A Original: weight1 always.
B Simple rule: at each weekly cut, weight1 if ETH past30d return>=0; otherwise0.5; unavailable=>0. Same1h effectiveness lag.
C LLM decisions:1/.5/0, first committed response only.
D Constant half-size parent strategy to isolate de-risking.
Also report ETH25%,ETH100%,zero-yield USDT as descriptive passive benchmarks.

## Costs, accounting and reproducibility
Base per side .10% fee+.05% adverse slippage; stress .15%+.15%. Buy units=(current cash*weight)/(open*(1+fee)*(1+slippage)); uninvested cash remains. Sell at exact original exit open net of fees/slippage. No leverage. Mark hourly closes plus execution opens/pre-post cost, include inactive days, realized-P&L profit factor rather than summing return percentages. Price gaps never become fabricated fills. Original full-size returns must reproduce original exported cash_after. Independently verify weighted trade arithmetic and daily NAV.

This session has no separately billed model API; that does NOT establish deployed cost0. Report estimated overhead sensitivity of0,0.01%,0.05% of initial account capital per weekly review, charged even in no-trade weeks. Distinguish hypothetical all-in operating budget from actual subscription allocation. Freeze model label,prompt,packet schema,all responses and hashes. Stored-decision execution is exactly replayable; fresh LLM decisions are NOT guaranteed reproducible. Report missing model-build/sampling metadata honestly.

## Tests and gates, before any new results
All weekly packets and decisions must be present, point-in-time bounded, no duplicate/missing exit; full-signal baseline reconciles; zero signals must yield valid empty metrics. Primary2026 comparison is LLM minus original/simple/constant-half/cash paired daily log returns,4999 circular7day block bootstraps,seed20260921,Holm4;28day diagnostic. Historical2025 is descriptive, not refit/tuning. Report sample count,return,win rate,average/median trade return,realized-P&L PF,exposure,volatility,maxDD,opportunity costs of skipped winners and avoided losers.

Conditional paper gate is an operational research gate, not proof of investable edge: data/test/replay passes;>=15 positive-weight2026 executed trades;2025 LLM net>=0;2026 LLM base return at least simple-rule return and constant-half return;2026 LLM maxDD no worse than simple rule; combined2025–2026 stress-cost compounded return including0.01% initial-capital overhead per review>0;2026 best-trade-removed base return>=0. No relaxing or swapping gates after outcomes. Statistical intervals and hindsight remain explicit even if this modest paper gate passes. If any gate fails, do not initiate paper trading; report what failed. If all pass, verify runnable frozen-model live packet/ledger path before activating any paper automation, no backfilled paper trades. Previously approved news collection remains unchanged.

References on limitations: https://arxiv.org/abs/2602.14233 ; https://arxiv.org/abs/2601.13770 . This is a bounded retrospective pilot of capital management, not evidence that unrestricted AI-managed trading works.
