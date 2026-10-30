# Solana wallet copy-paper pilot

Ken approved this direction on 2026-10-23: follow public wallets using actual newly observed quotes, without real transactions. This supersedes the unstarted `direct_ai` draft, not the frozen `forward_paper` study. No existing schedule, account, main branch or historical result is changed.

## Status and acceptance

Live commissioning on 2026-10-23: provider keys verified against Helius RPC and Jupiter quote-only routes; one candidate selected for an **engineering paper pilot**, not as a verified profitable trader. See `COMMISSIONING-2026-10-23.md` and `screening-2026-10-23.json` for actual deployment and evidence. Source wallet's recent results include losses and fast exits. Forward performance must come from genuinely new fills; historical commissioning replay is never performance.

Stack: Cloudflare Worker + one SQLite Durable Object; Helius enhanced SWAP webhook as notification, canonical read-only Solana RPC for balances; Jupiter Swap V2 `/order` without `taker` for quotes only. No signing code, wallet secret, `/execute`, transfer or transaction-send method exists. Source: https://www.helius.dev/docs/webhooks ; https://developers.jup.ag/docs/api-reference/swap/order ; https://developers.cloudflare.com/durable-objects/api/state/

## Pilot rules (experimental, not proven profitable)

- 10,000 virtual **USDC**, explicitly different from the old USDT accounts. No stablecoin conversion is implied.
- The legacy primary book retains its allowlist. New screened candidates use isolated dynamic paper accounts created at promotion time; no code change or per-wallet Durable Object binding is needed. Each dynamic account starts with 10,000 virtual USDC and only observes events at or after its own `startedAt`; historical leaderboard trades are never backfilled as paper fills. Fixed 200 USDC entry; 1,000 per wallet / 3,000 overall deployed **cost** cap including assumed fees. These are not mark-to-market exposure limits. No averaging, shorts or leverage.
- Copy supported two-asset swaps between a classic SPL token and SOL/USDC. Aggregate exact raw balances; exclude transaction fees and owned token-account rent from SOL delta. Ambiguous multi-asset transactions, transfers, token-to-token swaps, Token-2022 extensions, active mint/freeze authorities and unavailable routes are skipped. This does not certify contract safety or LP lock status.
- Entry observed within 60 seconds of block time. Skip if copied unit cost is >15% above leader's reference. SOL leader cost is converted using current observed SOL→USDC route, **not historical leader-time FX**. Skip if the pre-entry reverse-route probe would lose >10%.
- Save decision before quote. Preview/reverse gates precede the **final fresh** entry quote; do not look ahead then reuse an earlier price. Quote request-to-use <=10 seconds. Apply 1% adverse output haircut plus 1 USDC assumed network/priority budget each side. DEX route fees already reside in quote output; do not add exchange spot fees again. Actual fees/landing success are unknown; this is quote-based paper execution, not a transaction execution simulator.
- Mirror fraction sold = leader tokens sold / leader pretransaction token holding. Positions tracked separately per wallet/mint. Full fallback exit after 24h, checked via minute cron; no guaranteed stop price. Missing sale quotes leave position open and retry; new buys blocked while a known exit remains pending.
- A failed partial sale keeps that proportional retry; `exitPending` does not make the position expire early. Each full fallback verifies the current lot's `openedAt` and 24h age on every attempt, including previously queued jobs with cached signals. Premature or old-lot jobs receive an audited skip without changing balances or clearing risk flags; past fills are not rewritten.
- Duplicate signature+wallet events and crash retries cannot double-fill. Durable event queue; account+receipt+queue removal commit atomically. RPC/network failures retry with backoff. Authenticated webhook ingestion does not trust caller-supplied prices or balances. First-seen and block time retained. No historical backfill fills.
- Every minute, a 100-signature-per-wallet recovery poll and expiry/mark sweep. Recovery overflow sets a persistent new-entry block, requiring operator gap review. This bounded recovery is not guaranteed complete history. Confirmed-chain observations have residual reorg risk; historical canonical correction is not yet implemented.
- Status marks are sequential full-position liquidation quotes, not simultaneous marks; missing quotes produce **unknown NAV**, not zero loss or fabricated prices. AI/API operating costs excluded. No automatic claim of outperforming cash, profit or significance.

## Run tests

Run from the repository root with Node 22+; no dependencies or credentials:

```bash
node copy_paper/test.mjs
node copy_paper/regression.mjs
node copy_paper/expiry_regression.mjs
```

Fixtures test engineering only, never forward trades. Tests include exact balance parsing, fees/rent, partial/full exits, chase/freshness/caps, auth, duplicate delivery, restart and unavailable-exit recovery. Expiry regressions also cover a partial-sale failure across a cron sweep/restart, legacy premature jobs with cached signals, old-lot jobs against replacement positions, and valid 24h/legacy expiry retries. The fake Durable Object store does not prove production Cloudflare semantics or upstream schemas; live commissioning remains mandatory.

## Secrets and deployment

1. Helius: https://dashboard.helius.dev — generate API key. Jupiter: https://developers.jup.ag/portal — create quote API key. Do not paste keys into chat, git, plaintext vars or screenshots.
2. Deploy the disabled Worker `ken-copy-paper` using `wrangler deploy --config copy_paper/wrangler.jsonc` or Cloudflare multipart API with these exact modules/bindings. Keep `ENABLED=false`, `WALLETS=[]`; no cron or webhook needs activating before source checks. SQLite DO binding `BOOK` → `PaperBook`; migration `copy-paper-v1`.
3. Cloudflare Worker → Settings → Variables and Secrets: encrypted `HELIUS_API_KEY`, `JUPITER_API_KEY`; independent random >=32-character `WEBHOOK_SECRET`, `ADMIN_TOKEN`. `WEBHOOK_SECRET` is sent as `Authorization: Bearer …` by Helius; admin token protects `/status`. The app never exposes secret values. No seed phrase or exchange API key needed.
4. Before activation: verify current plan/quota, canonical transaction shapes, supported trade coverage, quote-only responses, and no-quote behavior using real data. Review a fixed historical candidate window for each proposed wallet: trade count, median hold time, realized vs unrealized return, concentration in one lucky token, transfers/airdrops, and whether current routes can reproduce its trade size. Do not select on a single P&L screenshot. Freeze up to 3 candidates with dated rationale; **none yet verified**.
5. Set allowlist and enable only after integration checks. Add Helius enhanced `SWAP` webhook at `https://<worker>/webhook`, allowlisted accounts and authHeader above. Configure minute cron as in wrangler config. Receipt handling begins from actual initialized time; no earlier event is traded. Keep existing old ETH and news automations untouched.
6. Read authenticated `/status`: inspect fills, skips, cash, positions, pending exits and missing marks. Verify persistence after a deployment/restart. A successful `/health` alone is not completion. First pilot review after 7 calendar days plus disclose sample size; do not reset losing accounts or promote to real money.

## Dynamic candidate promotion

Authenticated `POST /dynamic/create` accepts a screened Solana wallet, label and optional chase limit. The controller derives a stable account ID, creates an isolated `DynamicPaperBook`, subscribes the wallet to the existing Helius webhook, and only then changes the account from paused to active. If webhook synchronization fails, the account remains paused. `GET /dynamic`, `GET /dynamic/status?id=...`, `POST /dynamic/pause?id=...` and `POST /dynamic/resume?id=...` support inspection and lifecycle control.

Dynamic accounts are deliberately forward-only. Their state is initialized with the exact promotion timestamp, so older signatures discovered by recovery polling are rejected by the existing pre-start gate. Pausing prevents new processing without deleting balances, history or account identity. Archival is registry-only and should not be used while positions or pending exits remain.

## Operational limits and recovery

- Disabling `ENABLED` also stops exits: use only as an emergency full pause, disclose open positions. Never remove tracked wallets with open positions without an exit plan.
- For a persistent `health.entryBlocked` gap: audit source records and pending exits; use a reviewed migration to clear that field only, retaining all balances and history. No public reset/unblock endpoint is exposed.
- Endpoint authentication, bounded bodies, exact signatures, persisted queue, retry backoff and fail-closed source validation reduce accidental corruption. Secret leakage/compromised provider and prolonged outages remain risks.
- No frontend dashboard or scheduled ChatGPT review is claimed. `/status` is an authenticated machine-readable pilot status endpoint. Keys and real-source checks are complete. Config file intentionally retains disabled defaults; deployed bindings and the commissioning receipt are the runtime source of truth. Provider/account-wide quota usage still needs operational observation.

## Next execution session

Read this file, `core.mjs`, `worker.mjs`, current branch and any deployment receipt. Use existing provider secrets in the Worker; never export them. Check the active deployment and authenticated status before making changes. Report actual transaction signature, observation/quote times, fill/skip reason and persisted account totals. If blocked, name the missing key/access rather than repeating unrelated backtests.

Authenticated operations: `POST /preflight` (optional mint query), `GET /inspect?wallet=...` (bounded 100 history rows; optional before or signature), `POST /connect` (only this Worker webhook), `POST /tick`. All require ADMIN_TOKEN. Solana reads opt into transaction version 1; new versions must be reviewed before accepting.
