# Private paper-trading viewer — implementation ready, not deployed

Ken requested a live mobile visual for the existing Solana paper engine. This is an independent read-only Cloudflare Worker. It does not change `copy_paper`, its wallet allowlist, policy, ledger, cron, or webhook. The existing PR #10 remains draft; deployment and merging require Ken's approval. No live viewer URL is claimed yet.

## User experience

NAV and total return first, then cash, realized/unrealized P&L, fills/positions, timestamped SVG observations, position liquidation estimates, recent fills/skips and diagnostics. Unknown liquidation NAV stays unknown. Health null is labeled absent diagnostic data, never healthy. Values displayed to two decimals; original USDC atoms retained in JSON. SVG gaps above six minutes remain unconnected. Data can be exported.

One responsive HTML page, no third-party scripts/fonts, one SVG chart, no WebSocket and no new Helius/Jupiter quotes. Page polls every 30 seconds while visible; on focus/reconnect it refreshes. The independent `ViewHistory` Durable Object collects authenticated engine `/status` and one bounded `/audit` page every minute. It stores the latest snapshot and five-minute observations for seven days even when the viewer is closed. Observations begin on actual deployment, never fabricated/backfilled; recent event lists are bounded, not the complete ledger. Failed collection retains the last good observation and its old timestamp. Storage is separate from the trading book.

## Security / deployment contract

Use a separate worker named `ken-copy-paper-view` and new DO namespace/class `ViewHistory`. Use the included `wrangler.jsonc`; do not deploy with the trading engine's wrangler config. There are no viewer trade, reset, unblock, wallet-edit or arbitrary-proxy endpoints. Only a fixed engine host with GET `/status` and GET `/audit` exists. Admin secret is backend-only. It remains a powerful upstream credential; protect this worker deployment access, and a scoped upstream read token would reduce that residual risk in a future separately reviewed engine change.

Required encrypted secrets (no values in git):
- `ENGINE_ADMIN_TOKEN`: existing engine admin token, securely provisioned server-side.
- `VIEWER_PASSWORD`: independent random password, at least 16 characters (recommend 32 random characters), not the engine token.
- `SESSION_SECRET`: independent cryptographically random 32+ characters; rotate to invalidate all sessions.

Login is POST JSON, requires matching Origin, limits body to 1 KB and sets signed expiring Secure/HttpOnly/SameSite=Strict cookie. No credentials in URLs, HTML, browser storage, reports or logs. The HTML shell contains no account data. API requires a valid cookie; no CORS access. Keep the password private; the viewer is not public sharing. Add Cloudflare rate limiting if the login becomes an abuse target. Credential provisioning and live browser/Worker verification must occur after deployment approval.

## Verification

Run `node --test copy_dashboard/test.mjs` (Node 22+). Eight tests cover exact atoms and stale/incoherent marks, projection/secret stripping, auth and origin checks, fixed read-only upstream calls, partial/total failures, cookie clearing, independent retention and outage persistence. In-memory DO test does not prove Cloudflare production semantics.

Browser rendering: attempted Chromium and headless-shell installation, both downloads returned invalid ZIP data in this session. No visual/mobile-layout pass is claimed. The separate real-data preview is explicitly a dated snapshot, not live. Final predeployment acceptance: render at 390px and desktop, exercise tabs/ranges/login/logout, reject unauthenticated API, verify real cron samples across time and persistence after restart, confirm the engine state is unchanged except natural trades.

Source editing: `dashboard.html` is canonical UI source; regenerate `view.mjs` as `export const HTML = <JSON-escaped HTML>;` after edits. No copied credentials or account snapshots belong in the source repo.

DOM interaction check using the actual sanitized snapshot passed: NAV, three positions, SVG observation points, tabs, time-range selection and explicit preview state; no JavaScript errors. This is not a browser layout or live deployment test.
