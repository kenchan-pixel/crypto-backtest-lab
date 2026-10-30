import test from 'node:test';
import assert from 'node:assert/strict';
import {PaperBook} from './worker.mjs';
import {USDC, POLICY, initial, plan} from './core.mjs';

const WALLET = '1'.repeat(32), MINT = '2'.repeat(32);
const POSITION = `${WALLET}:${MINT}`;

class Store {
  constructor() { this.rows = new Map(); }
  async get(key) { return structuredClone(this.rows.get(key)); }
  async put(key, value) { this.rows.set(key, structuredClone(value)); }
  async delete(key) { this.rows.delete(key); }
  async setAlarm(at) { this.alarm = at; }
  async list({prefix = '', limit = 1000, reverse = false} = {}) {
    const rows = [...this.rows].filter(([key]) => key.startsWith(prefix));
    rows.sort(([a], [b]) => reverse ? b.localeCompare(a) : a.localeCompare(b));
    return new Map(structuredClone(rows.slice(0, limit)));
  }
  async transaction(fn) {
    const before = structuredClone(this.rows);
    try { return await fn(this); }
    catch (error) { this.rows = before; throw error; }
  }
}

async function fixture(ageMs = 5000) {
  const now = Date.now(), store = new Store(), quotes = [];
  const control = {unavailable: false};
  const env = {
    ENABLED: 'true', WALLETS: JSON.stringify([WALLET]),
    HELIUS_API_KEY: 'fixture', JUPITER_API_KEY: 'fixture',
    QUOTE_GATE: {
      idFromName: name => name,
      get: () => ({fetch: async (_url, options) => {
        const spec = JSON.parse(options.body); quotes.push(spec);
        if (control.unavailable) return Response.json({error: 'offline'}, {status: 503});
        const at = Date.now();
        return Response.json({inputMint: spec.inputMint, outputMint: spec.outputMint,
          inAmount: spec.amount, outAmount: '100000000', swapMode: 'ExactIn',
          routePlan: [{}], requestedAt: at, receivedAt: at});
      }})
    }
  };
  const state = initial(now - ageMs - 1000);
  state.cash = '9799000000'; state.fees = '1000000'; state.fills = 1;
  state.positions[POSITION] = {wallet: WALLET, mint: MINT, qty: '1000',
    cost: '201000000', openedAt: now - ageMs, decimals: 6, exitPending: false};
  await store.put('state', state);
  const ctx = {storage: store, blockConcurrencyWhile: fn => fn()};
  return {store, state, quotes, control, book: new PaperBook(ctx, env),
    restart: () => new PaperBook(ctx, env)};
}

async function pendingPartial(f) {
  const now = Date.now();
  const signal = {id: 'partial-sell', wallet: WALLET, mint: MINT, side: 'SELL',
    qty: '500', leaderPre: '1000', chainAt: now - 1000, receivedAt: now, slot: 100};
  const job = {id: signal.id, signal, receivedAt: now, nextAt: 0, attempts: 0};
  await f.store.put('pending:' + job.id, job);
  return job;
}

function legacyExpiry(position, {cached = false} = {}) {
  const id = `expiry:${POSITION}:${position.openedAt}`;
  const job = {id, expiry: true, wallet: WALLET, mint: MINT,
    receivedAt: Date.now(), attempts: 0, nextAt: 0};
  if (cached) job.signal = {id, wallet: WALLET, mint: MINT, side: 'SELL',
    qty: position.qty, leaderPre: position.qty, chainAt: position.openedAt,
    receivedAt: job.receivedAt, expiry: true};
  return job;
}

test('failed partial sell survives sweep and restart without becoming a full exit', async () => {
  const f = await fixture();
  const original = await pendingPartial(f);
  f.control.unavailable = true;
  await f.book.alarm();
  const failed = await f.store.get('state');
  assert.equal(failed.positions[POSITION].exitPending, true);
  assert.throws(() => plan(failed, {wallet: WALLET, mint: '3'.repeat(32),
    side: 'BUY', chainAt: Date.now()}, Date.now()), /unresolved exit/);

  await f.book.fetch(new Request('https://internal/sweep', {method: 'POST'}));
  assert.equal([...(await f.store.list({prefix: 'pending:'})).values()]
    .some(job => job.expiry), false, 'a failed partial sell is not a 24h expiry');

  const retry = await f.store.get('pending:' + original.id);
  retry.nextAt = 0; await f.store.put('pending:' + retry.id, retry);
  f.control.unavailable = false;
  await f.restart().alarm();
  const recovered = await f.store.get('state');
  assert.equal(recovered.positions[POSITION].qty, '500');
  assert.equal(recovered.positions[POSITION].cost, '100500000');
  assert.equal(recovered.positions[POSITION].exitPending, false);
  assert.equal(recovered.cash, '9897000000');
  assert.equal(recovered.realized, '-2500000');
  assert.equal(recovered.fees, '2000000');
  assert.equal(recovered.fills, 2);
  assert.equal(await f.store.get('pending:' + original.id), undefined);
});

test('legacy premature expiry is rejected even with a cached full-sell signal', async () => {
  const f = await fixture();
  const original = await pendingPartial(f);
  const job = legacyExpiry(f.state.positions[POSITION], {cached: true});
  await f.store.put('pending:' + job.id, job);
  await f.restart().process(job);
  assert.deepEqual(await f.store.get('state'), f.state);
  assert.equal(f.quotes.length, 0);
  assert.equal((await f.store.get('done:' + job.id)).status, 'SKIP');
  assert.equal(await f.store.get('pending:' + job.id), undefined);
  assert.ok(await f.store.get('pending:' + original.id), 'original sell must remain retryable');
});

test('old expiry cannot sell a replacement lot even if that replacement is now due', async () => {
  const f = await fixture(POLICY.maxHoldMs + 1000);
  const previous = {...f.state.positions[POSITION], openedAt: f.state.startedAt - POLICY.maxHoldMs};
  f.state.startedAt = previous.openedAt - 1000;
  await f.store.put('state', f.state);
  const job = legacyExpiry(previous, {cached: true});
  await f.store.put('pending:' + job.id, job);
  await f.restart().process(job);
  assert.deepEqual(await f.store.get('state'), f.state);
  assert.equal(f.quotes.length, 0);
  assert.equal((await f.store.get('done:' + job.id)).status, 'SKIP');
  assert.equal(await f.store.get('pending:' + job.id), undefined);
});

test('genuine 24h expiry still retries and closes the lot once after restart', async () => {
  const f = await fixture(POLICY.maxHoldMs);
  await f.book.fetch(new Request('https://internal/sweep', {method: 'POST'}));
  const jobs = [...(await f.store.list({prefix: 'pending:'})).values()];
  const job = jobs.find(value => value.expiry);
  assert.ok(job, '24h fallback must still be queued');
  assert.equal(job.openedAt, f.state.positions[POSITION].openedAt);
  f.control.unavailable = true;
  await f.book.alarm();
  assert.equal((await f.store.get('state')).positions[POSITION].exitPending, true);
  const retry = await f.store.get('pending:' + job.id);
  retry.nextAt = 0; await f.store.put('pending:' + job.id, retry);
  f.control.unavailable = false;
  await f.restart().alarm();
  const closed = await f.store.get('state');
  assert.deepEqual(closed.positions, {});
  assert.equal(closed.fills, 2);
  assert.equal(closed.cash, '9897000000');
  assert.equal(closed.realized, '-103000000');
  assert.equal(closed.fees, '2000000');
  assert.equal(await f.store.get('pending:' + job.id), undefined);
  assert.equal((await f.store.get('done:' + job.id)).status, 'FILLED');
  await f.restart().alarm();
  assert.equal((await f.store.get('state')).fills, 2);
});

test('a due legacy job without openedAt metadata still closes only the remaining lot', async () => {
  const f = await fixture(POLICY.maxHoldMs + 1000);
  const job = legacyExpiry(f.state.positions[POSITION], {cached: true});
  const reduced = structuredClone(f.state);
  reduced.positions[POSITION].qty = '500';
  reduced.positions[POSITION].cost = '100500000';
  await f.store.put('state', reduced);
  await f.store.put('pending:' + job.id, job);
  await f.restart().process(job);
  assert.equal(f.quotes.length, 1);
  assert.equal(f.quotes[0].amount, '500');
  assert.deepEqual((await f.store.get('state')).positions, {});
  assert.equal((await f.store.get('done:' + job.id)).status, 'FILLED');
});
