# Live commissioning — 2026-10-23

## Current wallet update — 2026-10-23 22:56 HKT

Ken explicitly approved switching the paper monitor to Scharo, `4sAUSQFdvWRBxR8UoLBYbw8CcXuwXWxnN8pXa4mtm5nU`. Deployment `fb9141612390426084254a41d77ceb16` uses unchanged worker/core code, preserves secrets and the same Durable Object ledger. Runtime WALLETS readback contains only Scharo; ENABLED=true. Helius webhook `d38aa202-bf3f-4269-bd0d-c8e1f3490b02` update returned success. Prior BWP selection below is historical, superseded.

Screened at 22:46 HKT: latest 100 enhanced records span 100 minutes, 42 own SWAP records, 22 within the preceding hour. Four canonical samples parsed as 3 BUY and 1 SELL. This is an activity/compatibility test, not a profitability recommendation. Discovery: https://kolscan.io/account/4sAUSQFdvWRBxR8UoLBYbw8CcXuwXWxnN8pXa4mtm5nU .

Manual recovery tick queued 14 records; subsequent readback queue=0, health=null. Receipts include late-entry skips, unsupported swaps and no-copied-position sells. Cash remains 10,000 USDC, positions=0, fills=0; original startedAt preserved. No historical event counted as a forward fill. First qualifying new-event fill remains unverified.

## Original commissioning state

Worker `ken-copy-paper` is enabled with one experimental wallet, authenticated Helius SWAP webhook and minute recovery/mark cron. Book initialized 2026-10-23T20:39:30.161000+08:00, 10,000 virtual USDC. At final readback: zero fills, no positions, zero fees, zero queue, no health error. This is **not proof of a profitable strategy or a live natural-event fill**. No private trading key, transaction signing or on-chain submission exists.

Final deployment: `11795ddae64b41ae9ffdb7b6266c2a96`. Machine receipt: `deployment-2026-10-23.json`. Default wrangler vars deliberately remain disabled; they are safe redeployment defaults, not current runtime state. PR #10 remains unmerged.

## Evidence

- Helius RPC read USDC mint at slot 460444034; Jupiter quote-only response for 200 USDC to SOL returned 1,912,479,868 lamports at Unix ms 1792758720615. A second quote for a candidate SPL mint also passed schema/freshness checks. Quotes are connectivity probes, not fills.
- Real source discovered RPC -32015 for v1 transactions. Fixed every getTransaction call to pass integer maxSupportedTransactionVersion=1. Official reference: https://solana.com/docs/core/transactions/versioned-transactions . Parsed canonical v1 fixture retained; no custom binary decoding introduced.
- 17 local tests passed, including provider-check authentication, no-book preflight, and real v1 fixture. Other fixture tests remain simulations, not forward evidence.
- Authenticated historical replay signature `5nd4uBSMYohstaWHKojLkpKUBQz6snyfLq5FUZ2BaXLs5zj1mgtjAYm3GPazaAUo53WVfuL6LpUHHSwwe9BFax7h` was queued, reread from Helius, normalized and **SKIP/pre-start event** recorded. It did not change balances or count as a fill.
- Re-uploaded identical modules and read status again: account state and historical skip retained, queue empty. Actual natural webhook delivery and a new quote-based fill are still awaiting future candidate activity. Minute cron configuration is read back; its first autonomous firing was not separately established in this session.

## Candidate and limitations

Selected solely for an engineering paper pilot: `BwPFmWgirMuf7RDyxxBg8eBHwFuqSTupSdtgG3DRNpDd`. Fixed 7-day screening window and all 33 canonical signals in `screening-2026-10-23.json`; 22 buys and 11 sells parsed. Six sells could be matched entirely to within-window purchases; four lost SOL before fee adjustments, median matched hold ~3.76 minutes. Other sells have pre-window basis; open positions and transfers make complete PnL/concentration unverified. **This is not a recommended profitable wallet.** The purpose is to measure real follow delay, route availability and paper outcomes. Current 200 USDC ticket/no averaging/24h fallback differs from leader behavior.

Earlier `GnVv…66Ek` temporarily initialized the book while commissioning, but only 13/47 own swaps parsed; it was removed after verifying zero fills, zero positions and empty queue. No account history or loss was reset. Other candidates deferred for noisy feeds or absent recent own swaps. Discovery source (claims not accepted as performance evidence): https://dextrading.com/academy/solana-meme-coin-traders-to-copy .

## Operations and next acceptance

Keys remain encrypted in Cloudflare. ADMIN_TOKEN protects status, preflight, inspect, connect and tick; WEBHOOK_SECRET authenticates ingress. Neither secret is in git. `/health` is public and reports configuration only; it is not a trading dashboard. Read `/status` through authenticated operator access and inspect genuine new event latency, fill/skip receipts, queued errors and NAV. Do not replay history as forward trades or reset the account to improve results. Review first natural provider event and first qualifying fill; absence of a fill is not an error when no qualifying new buy has occurred.

No ChatGPT review automation or frontend dashboard was created. Existing ETH study and its automations remain untouched. No paid plan was purchased. Actual shared-account quotas were not independently measured; monitor service usage after enabling.
