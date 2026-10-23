# Solana wallet copy-paper pilot

Ken approved this direction on 2026-10-23: follow public wallets using actual newly observed quotes, without real transactions. This supersedes the unstarted `direct_ai` draft, not the frozen `forward_paper` study. No existing schedule, account, main branch or historical result is changed.

## Status and acceptance

Implementation + local fixture tests are available. **Not live, no wallets selected, no real-source integration validated, no forward performance.** Helius account creation alone does not connect its API key. Deployment starts disabled with an empty allowlist. Do not declare started until a canonical chain event is received, independently read, queued durably, and either a genuine quote-based fill or a documented skip is read back after restart.

Stack: Cloudflare Worker + one SQLite Durable Object; Helius enhanced SWAP webhook as notification, canonical read-only Solana RPC for balances; Jupiter Swap V2 `/order` without `taker` for quotes only. No signing code, wallet secret, `/execute`, transfer or transaction-send method exists. Source: https://www.helius.dev/docs/webhooks ; https://developers.jup.ag/docs/api-reference/swap/order ; https://developers.cloudflare.com/durable-objects/api/state/

## Pilot rules (experimental, not proven profitable)

- 10,000 virtual **USDC**, explicitly different from the old USDT accounts. No stablecoin conversion is implied.
- Up to 3 allowlisted public wallets. Fixed 200 USDC entry; 1,000 per wallet / 3,000 overall deployed **cost** cap including assumed fees. These are not mark-to-market exposure limits. No averaging, shorts or leverage.
- Copy supported two-asset swaps between a classic SPL token and SOL/USDC. Aggregate exact raw balances; exclude transaction fees and owned token-account rent from SOL delta. Ambiguous multi-asset transactions, transfers, token-to-token swaps, Token-2022 extensions, active mint/freeze authorities and unavailable routes are skipped. This does not certify contract safety or LP lock status.
- Entry observed within 60 seconds of block time. Skip if copied unit cost is >15% above leader's reference. SOL leader cost is converted using current observed SOL→USDC route, **not historical leader-time FX**. Skip if the pre-entry reverse-route probe would lose >10%.
- Save decision before quote. Preview/reverse gates precede the **final fresh** entry quote; do not look ahead then reuse an earlier price. Quote request-to-use <=10 seconds. Apply 1% adverse output haircut plus 1 USDC assumed network/priority budget each side. DEX route fees already reside in quote output; do not add exchange spot fees again. Actual fees/landing success are unknown; this is quote-based paper execution, not a transaction execution simulator.
- Mirror fraction sold = leader tokens sold / leader pretransaction token holding. Positions tracked separately per wallet/mint. Full fallback exit after 24h, checked via minute cron; no guaranteed stop price. Missing sale quotes leave position open and retry; new buys blocked while a known exit remains pending.
- Duplicate signature+wallet events and crash retries cannot double-fill. Durable event queue; account+receipt+queue removal commit atomically. RPC/network failures retry with backoff. Authenticated webhook ingestion does not trust caller-supplied prices or balances. First-seen and block time retained. No historical backfill fills.
- Every minute, a 100-signature-per-wallet recovery poll and expiry/mark sweep. Recovery overflow sets a persistent new-entry block, requiring operator gap review. This bounded recovery is not guaranteed complete history. Confirmed-chain observations have residual reorg risk; historical canonical correction is not yet implemented.
- Status marks are sequential full-position liquidation quotes, not simultaneous marks; missing quotes produce **unknown NAV**, not zero loss or fabricated prices. AI/API operating costs excluded. No automatic claim of outperforming cash, profit or significance.

## Run tests

`node --test copy_paper/test.mjs` from repository root; Node 22+; no dependencies or credentials. Fixtures test engineering only, never forward trades. Tests include exact balance parsing, fees/rent, partial/full exits, chase/freshness/caps, auth, duplicate delivery, restart and unavailable-exit recovery. The fake Durable Object store does not prove production Cloudflare semantics or upstream schemas; live commissioning remains mandatory.

## Secrets and deployment

1. Helius: https://dashboard.helius.dev — generate API key. Jupiter: https://developers.jup.ag/portal — create quote API key. Do not paste keys into chat, git, plaintext vars or screenshots.
2. Deploy the disabled Worker `ken-copy-paper` using `wrangler deploy --config copy_paper/wrangler.jsonc` or Cloudflare multipart API with these exact modules/bindings. Keep `ENABLED=false`, `WALLETS=[]`; no cron or webhook needs activating before source checks. SQLite DO binding `BOOK` → `PaperBook`; migration `copy-paper-v1`.
3. Cloudflare Worker → Settings → Variables and Secrets: encrypted `HELIUS_API_KEY`, `JUPITER_API_KEY`; independent random >=32-character `WEBHOOK_SECRET`, `ADMIN_TOKEN`. `WEBHOOK_SECRET` is sent as `Authorization: Bearer …` by Helius; admin token protects `/status`. The app never exposes secret values. No seed phrase or exchange API key needed.
4. Before activation: verify current plan/quota, canonical transaction shapes, supported trade coverage, quote-only responses, and no-quote behavior using real data. Review a fixed historical candidate window for each proposed wallet: trade count, median hold time, realized vs unrealized return, concentration in one lucky token, transfers/airdrops, and whether current routes can reproduce its trade size. Do not select on a single P&L screenshot. Freeze up to 3 candidates with dated rationale; **none yet verified**.
5. Set allowlist and enable only after integration checks. Add Helius enhanced `SWAP` webhook at `https://<worker>/webhook`, allowlisted accounts and authHeader above. Configure minute cron as in wrangler config. Receipt handling begins from actual initialized time; no earlier event is traded. Keep existing old ETH and news automations untouched.
6. Read authenticated `/status`: inspect fills, skips, cash, positions, pending exits and missing marks. Verify persistence after a deployment/restart. A successful `/health` alone is not completion. First pilot review after 7 calendar days plus disclose sample size; do not reset losing accounts or promote to real money.

## Operational limits and recovery

- Disabling `ENABLED` also stops exits: use only as an emergency full pause, disclose open positions. Never remove tracked wallets with open positions without an exit plan.
- For a persistent `health.entryBlocked` gap: audit source records and pending exits; use a reviewed migration to clear that field only, retaining all balances and history. No public reset/unblock endpoint is exposed.
- Endpoint authentication, bounded bodies, exact signatures, persisted queue, retry backoff and fail-closed source validation reduce accidental corruption. Secret leakage/compromised provider and prolonged outages remain risks.
- No frontend dashboard or scheduled ChatGPT review is claimed. `/status` is an authenticated machine-readable pilot status endpoint. Wallet discovery, real-source validation, account quotas and activation are pending keys; no need to restart architecture work when keys arrive.

## Next execution session

Read this file, `core.mjs`, `worker.mjs`, current branch and any deployment receipt. Obtain secrets through provider secret storage, not git. Finish the real-source commissioning and wallet selection, then activate the same Worker. Report actual transaction signature, observation/quote times, fill/skip reason and persisted account totals. If blocked, name the missing key/access rather than repeating unrelated backtests.
