# ETH forward observation — operator entrypoint

## Current verified state

This is the user-approved **new prospective PAPER-ONLY forward experiment**. It is not proof that the old historical paper gate passed, and it is not live-money trading. Preserve the old failed historical gate unchanged.

Execution SOT is `forward_paper/runtime/state.json`. Current verified runtime remains:

- `status=COMMISSIONING`
- `execution_ready=false`
- `performance_started_at=null`
- `initial_decisions=false`
- three independent virtual accounts, each 10,000 USDT, 0 ETH, 0 trades
- frozen model SHA256 `08f2ba34b48d2aa5925af90c13452a34efbb0dc0f88d4694caa330bdf832c3fe`
- original threshold ~`0.010189194004167217`, planned hold 24h
- no retraining, strategy search, leverage, shorts, real orders or paid data provider

Never call Binance/Longbridge order, account, balance, wallet, margin, borrowing, transfer or deposit endpoints, including testnet. Existing Crypto News Collector and unrelated workflows must remain unchanged. No auto-merge.

## Verified commissioning milestones

Model reconstruction is checksum-bound to the original 2024-only ETH model. Actual Actions run `35616440026` verified the model export plus 14 paper-account tests; local feature-value parity covered 1,869 historical sequence rows. Historical opportunity replay reproduced the original signal/opportunity stream but remains historical evidence only.

Direct Binance USD-M REST from GitHub-hosted Azure runners returned HTTP451 in two regions. Do not proxy or bypass it. The approved source is the connected Binance **public read-only** tool, persisted immutably into GitHub before use.

Two independently timed qualifying current receipts have passed the causal source→feature→opportunity path. Receipt 1 is `forward_paper/receipts/qualifying_current_receipt_1_20260923T004308HKT.json`; Receipt 2 is `forward_paper/receipts/qualifying_current_receipt_2_20260923T013124HKT.json`. The second passed Actions `35761800850`. Therefore only `source_freshness=true` and `live_feature_parity=true` were promoted. Taker value semantics remain unresolved but Taker is retained/hash/freshness-checked and quarantined from the frozen decision matrix because the frozen model does not depend on it.

Durable paper runtime commissioning is complete through CAS persistence, restart/idempotency, exits-first ordering, genuine later-quote ordering, append-only late/missing-fill and data-gap events, BASE/STRESS cost sidecars, separate assumed AI operating-budget sidecars, and atomic sidecar wiring. Latest integrated runtime receipt before the weekly path is `forward_paper/receipts/runtime_sidecar_integration_commissioning_20260923T062104HKT.json` (Actions `35791826854`). These probes used isolated copies and public read-only evidence; they did not create actual paper trades or arm performance.

The genuine weekly decision **packet/commit path is now also commissioned**. `forward_paper/weekly_decision_packet.py` binds the current runtime hash, frozen model, immutable public evidence and SIMPLE_WEEKLY rule; it requires an explicit assistant AI weight `1/0.5/0` plus rationale, blocks coded AI fallback, requires a packet no older than 20 minutes at commit, uses CAS, and sets the earliest effect to the next full hour. It does not arm performance.

Verified Actions run `35796569338` passed **110 tests** plus all commissioning-boundary checks. Permanent receipt: `forward_paper/receipts/weekly_decision_packet_commissioning_20260923T071627HKT.json`. Connected preview evidence: `forward_paper/inputs/connected_weekly_packet_preview_20260923T071024HKT.json`, file SHA256 `db4eac67063aa89d90e438436ddf2bcd07a3c94237778f3d3540033b6e422956`. The completed daily closes used only to validate the SIMPLE path were 2422.60 and 2776.19 exactly 30 calendar days apart, giving preview return +14.5954759% and preview SIMPLE weight 1.0. This was Wednesday and therefore **not a genuine weekly decision**: the guard correctly blocked commit, AI remained unset, runtime bytes were unchanged, and no gate was promoted.

## Remaining commissioning action — time-gated

There is no remaining integration step to invent before the weekly decision window. Routine off-window runs should be silent after verifying that SOT has not materially changed.

On the **first eligible Monday run at or after 08:00 Asia/Hong_Kong**:

1. Read PROTOCOL, this OPERATIONS file, latest runtime state/model/parity receipts and latest meaningful receipt.
2. First service any due exit if the runtime has somehow become active; otherwise continue commissioning.
3. Collect a genuinely fresh connected public evidence packet. Do not reuse the Wednesday preview or any stale packet.
4. Derive `SIMPLE_WEEKLY` from that same cutoff: prior-30d ETH return >=0 => 1.0, otherwise 0.5; unknown => no new trade.
5. Make an **actual assistant** `AI_WEEKLY` decision of 1.0 / 0.5 / 0 with a short evidence-based rationale. Never substitute a coded rule and label it AI.
6. Commit AI + SIMPLE through the guarded CAS path before the next eligibility hour; HALF remains 0.5. Read back the persisted decision and AI-budget sidecar.
7. Do **not** set `performance_started_at` merely because the decision was saved. The decision must first become effective at the next full HKT hour. Only then, if every readiness receipt is valid, may `initial_decisions`, `execution_ready` and genuine performance start be considered. Record the actual start time, never retroactively.

Until that point the three accounts remain idle. Zero P&L is not evidence that the signal engine is running.

## Operation after genuine performance start

Collect/check current data on each run. Service due exits before evaluating new opportunities. Preserve the full frozen parent-opportunity stream, including counterexamples and no-signal periods. Save each causal signal before observing a fill; use only a genuinely later public quote. Never invent a backdated fill. All arms share the same parent opportunity and fill observations, and the common parent busy-until marker remains binding even if AI skips.

Maintain append-only idempotent ledgers with compare-and-swap writes. Log late/missing fills and data gaps explicitly. Keep BASE and STRESS cost comparisons on the same opportunities and keep assumed AI operating budgets separate from trading P&L. Planned hold remains 24h. A delayed exit uses genuine subsequent evidence and disclosed latency; it is never silently imputed.

Routine unchanged/no-signal checks are silent. Report a new access/data/exit/ledger blocker only on meaningful transition. If a genuine permission or source-semantic issue prevents safe progress, leave runtime blocked and ask only for what is missing. Do not infer failure from truncated previews.

## Weekly comparison and review

The first eligible Monday decision produces one Chinese weekly comparison. Thereafter report all three arms together: full-period and monthly net return, drawdown, exposure, transaction costs, assumed AI overhead, missed winners/avoided losers, latency/missing data and trade counts. Do not claim significance from a small sample.

Initial review is 12 weeks after the **genuine** `performance_started_at`. Review without auto-promoting to live money, resetting poor results, switching model/strategy, or selecting a winner. Any next phase requires a new explicit decision.

## Evidence and recovery

Important historical source artifacts and receipts remain under `forward_paper/receipts/` and `forward_paper/inputs/`; do not manufacture replacement gate receipts. The model JSON is durable in this branch and normal operation never refits it. Complete at most one bounded commissioning action per scheduled run. Once commissioned, runs are observation/account maintenance only.
