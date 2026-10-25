import test from 'node:test';
import assert from 'node:assert/strict';
import {USDC,SOL,SPL,POLICY,initial,normalize,plan,fill,checkQuote} from './core.mjs';
import worker,{PaperBook,wallets,supportedMint} from './worker.mjs';
const W='11111111111111111111111111111111', M='22222222222222222222222222222222', SIG='3'.repeat(88);
const T=1792756800000;
function signal(over={}){return {id:SIG+':'+W,signature:SIG,wallet:W,mint:M,side:'BUY',qty:'1000000000',leaderPre:'0',baseMint:USDC,baseQty:'200000000',chainAt:T,receivedAt:T+100,slot:100,decimals:6,...over};}
function qt(p,over={}){return {inputMint:p.inputMint,outputMint:p.outputMint,inAmount:p.amount,outAmount:'1000000000',swapMode:'ExactIn',routePlan:[{}],requestedAt:T+200,receivedAt:T+300,...over};}
function transaction({sell=false,native=false,failed=false}={}){
  const preTokenBalances=[{accountIndex:1,mint:M,owner:W,uiTokenAmount:{amount:sell?'1000000000':'0',decimals:6}}];
  const postTokenBalances=[{accountIndex:1,mint:M,owner:W,uiTokenAmount:{amount:sell?'500000000':'1000000000',decimals:6}}];
  if(!native){preTokenBalances.push({accountIndex:2,mint:USDC,owner:W,uiTokenAmount:{amount:'500000000',decimals:6}});postTokenBalances.push({accountIndex:2,mint:USDC,owner:W,uiTokenAmount:{amount:sell?'600000000':'300000000',decimals:6}});}
  return {slot:100,blockTime:T/1000,transaction:{signatures:[SIG],message:{accountKeys:[{pubkey:W,signer:true},{pubkey:M,signer:false},{pubkey:USDC,signer:false}]}},meta:{logMessages:['Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA invoke [1]','Program log: Instruction: Swap','Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA success'],err:failed?{}:null,fee:5000,preBalances:[10000000000,2039280,2039280],postBalances:[native?8999995000:9999995000,2039280,2039280],preTokenBalances,postTokenBalances}};
}
test('USDC buy and partial sell decode from exact token balances',()=>{
  assert.equal(normalize(transaction(),W,SIG,T+100).side,'BUY');
  const s=normalize(transaction({sell:true}),W,SIG,T+100);assert.equal(s.side,'SELL');assert.equal(s.qty,'500000000');assert.equal(s.leaderPre,'1000000000');
});
test('SOL buy excludes transaction fee and ATA rent',()=>{
  const tx=transaction({native:true});tx.meta.preBalances[1]=0;tx.meta.postBalances[0]-=2039280;
  const s=normalize(tx,W,SIG,T+100);assert.equal(s.baseMint,SOL);assert.equal(s.baseQty,'1000000000');
});
test('failed, non-signer, and ambiguous transactions are rejected',()=>{
  assert.throws(()=>normalize(transaction({failed:true}),W,SIG,T+100));
  const tx=transaction();tx.transaction.message.accountKeys[0].signer=false;assert.throws(()=>normalize(tx,W,SIG,T+100));
  const a=transaction();a.meta.postBalances[0]-=123;assert.throws(()=>normalize(a,W,SIG,T+100),/ambiguous/);
});
test('buy accounting conserves cash and charges explicit network budget',()=>{
  const st=initial(T-1000),s=signal(),p=plan(st,s,T+100),r=fill(st,s,p,qt(p),T+150,T+400,200000000n);
  assert.equal(r.state.cash,'9799000000');assert.equal(r.state.fees,'1000000');assert.equal(r.state.positions[`${W}:${M}`].qty,'990000000');assert.equal(st.cash,'10000000000');
});
test('partial sale realizes allocated cost and retains remaining lot',()=>{
  const s=signal(),p=plan(initial(T-1000),s,T+100),b=fill(initial(T-1000),s,p,qt(p),T+150,T+400,200000000n).state;
  const sell=signal({side:'SELL',qty:'500',leaderPre:'1000'}),sp=plan(b,sell,T+500);
  const r=fill(b,sell,sp,qt(sp,{outAmount:'150000000',requestedAt:T+600,receivedAt:T+700}),T+550,T+800,0n);
  assert.equal(r.state.positions[`${W}:${M}`].qty,'495000000');assert.equal(r.state.positions[`${W}:${M}`].cost,'100500000');assert.equal(r.state.realized,'47000000');assert.equal(r.state.cash,'9946500000');
});
test('full exit removes position and balances realized PnL',()=>{
  const s=signal(),p=plan(initial(T-1000),s,T+100),b=fill(initial(T-1000),s,p,qt(p),T+150,T+400,200000000n).state;
  const sell=signal({side:'SELL',qty:'1000',leaderPre:'1000'}),sp=plan(b,sell,T+500);
  const r=fill(b,sell,sp,qt(sp,{outAmount:'250000000'}),T+150,T+800,0n);
  assert.equal(Object.keys(r.state.positions).length,0);assert.equal(BigInt(r.state.cash)-POLICY.initial,BigInt(r.state.realized));
});
test('late or pre-start buys never get historical fills',()=>{
  assert.throws(()=>plan(initial(T-1),signal(),T+60001),/late/);
  assert.throws(()=>plan(initial(T+1),signal(),T+100),/pre-start/);
});
test('chase limit, timestamp, amount and route checks fail closed',()=>{
  const st=initial(T-1),s=signal(),p=plan(st,s,T+100);
  assert.throws(()=>fill(st,s,p,qt(p,{outAmount:'800000000'}),T+150,T+400,200000000n),/chase/);
  for(const bad of [{receivedAt:T-1},{requestedAt:T-1},{inAmount:'1'},{routePlan:[]},{transaction:'unsigned bytes'},{outAmount:'NaN'}])assert.throws(()=>checkQuote(qt(p,bad),p,T+150,T+400));
});
test('no averaging, wallet cap, total cap and pending exits block entry',()=>{
  const st=initial(T-1),s=signal(),p=plan(st,s,T+100),b=fill(st,s,p,qt(p),T+150,T+400,200000000n).state;
  assert.throws(()=>plan(b,s,T+500),/averaging/);
  b.positions.x={wallet:W,cost:'999000000',qty:'1'};assert.throws(()=>plan(b,signal({mint:'4'.repeat(32)}),T+500),/cap/);
  delete b.positions.x;b.positions[`${W}:${M}`].exitPending=true;assert.throws(()=>plan(b,signal({mint:'4'.repeat(32)}),T+500),/unresolved/);
});
test('integer tokens above floating point safe range retain precision',()=>{
  const tx=transaction();tx.meta.postTokenBalances[0].uiTokenAmount.amount='900719925474099312345';
  assert.equal(normalize(tx,W,SIG,T+100).qty,'900719925474099312345');
});
test('allowlist rejects duplicates and more than three wallets',()=>{
  assert.throws(()=>wallets({WALLETS:JSON.stringify([W,W])}));assert.throws(()=>wallets({WALLETS:'["bad"]'}));assert.deepEqual(wallets({}),[]);
});
test('public endpoint cannot read account or submit unauthenticated event',async()=>{
  const env={};assert.equal((await worker.fetch(new Request('https://x/status'),env)).status,401);
  assert.equal((await worker.fetch(new Request('https://x/webhook',{method:'POST',body:'[]'}),env)).status,401);
  assert.equal((await worker.fetch(new Request('https://x/order',{method:'POST'}),env)).status,404);
});
class Store {
  constructor(){this.m=new Map();}
  async get(k){return structuredClone(this.m.get(k));}async put(k,v){this.m.set(k,structuredClone(v));}
  async delete(k){this.m.delete(k);}async setAlarm(t){this.alarm=t;}
  async list({prefix='',limit=1000,reverse=false}={}){let a=[...this.m].filter(([k])=>k.startsWith(prefix)).sort(([a],[b])=>a.localeCompare(b));if(reverse)a.reverse();return new Map(structuredClone(a.slice(0,limit)));}
  async transaction(fn){const backup=structuredClone(this.m);try{return await fn(this);}catch(e){this.m=backup;throw e;}}
}
test('failed sell stays pending and restart can settle without fabricating proceeds',async()=>{
  const store=new Store(),env={ENABLED:'true',WALLETS:JSON.stringify([W]),HELIUS_API_KEY:'fixture',JUPITER_API_KEY:'fixture'};
  const ctx={storage:store,blockConcurrencyWhile:fn=>fn()},now=Date.now();
  const s=signal(),p=plan(initial(T-1000),s,T+100);
  const state=fill(initial(T-1000),s,p,qt(p),T+150,T+400,200000000n).state;
  await store.put('state',state);
  const sell=signal({id:'sell:'+W,side:'SELL',qty:'1000',leaderPre:'1000',chainAt:now-1000,receivedAt:now});
  await store.put('pending:'+sell.id,{id:sell.id,signal:sell,receivedAt:now,nextAt:0,attempts:0});
  const oldFetch=globalThis.fetch;globalThis.fetch=async()=>new Response('',{status:503});
  try{
    await new PaperBook(ctx,env).alarm();
    const failed=await store.get('state');assert.equal(failed.cash,state.cash);assert.equal(failed.fills,1);assert.equal(failed.positions[`${W}:${M}`].exitPending,true);
    const job=await store.get('pending:'+sell.id);assert.equal(job.attempts,1);job.nextAt=0;await store.put('pending:'+sell.id,job);
    globalThis.fetch=async url=>{const u=new URL(url);return Response.json({inputMint:M,outputMint:USDC,inAmount:u.searchParams.get('amount'),outAmount:'180000000',swapMode:'ExactIn',routePlan:[{}]});};
    await new PaperBook(ctx,env).alarm();const recovered=await store.get('state');assert.equal(recovered.fills,2);assert.equal(Object.keys(recovered.positions).length,0);assert.equal(await store.get('pending:'+sell.id),undefined);
  }finally{globalThis.fetch=oldFetch;}
});
test('duplicate webhook delivery and process restart produce one fill',async()=>{
  const store=new Store(),env={ENABLED:'true',WALLETS:JSON.stringify([W]),HELIUS_API_KEY:'fixture',JUPITER_API_KEY:'fixture'};
  const ctx={storage:store,blockConcurrencyWhile:fn=>fn()};let book=new PaperBook(ctx,env);
  const now=Date.now();await store.put('state',initial(now-10000));
  const tx=transaction();tx.blockTime=Math.floor(now/1000);
  const oldFetch=globalThis.fetch;globalThis.fetch=async(url,opts)=>{
    const u=new URL(url);
    if(u.hostname==='api-mainnet.helius-rpc.com')return Response.json([{signature:SIG,type:'SWAP'}]);
    if(u.hostname==='mainnet.helius-rpc.com'){
      const r=JSON.parse(opts.body);return Response.json({result:r.method==='getTransaction'?tx:{value:{owner:SPL,data:{parsed:{info:{mintAuthority:null,freezeAuthority:null,decimals:6}}}}}});
    }
    assert.equal(u.pathname,'/swap/v2/order');assert.equal(u.searchParams.has('taker'),false);
    return Response.json({inputMint:u.searchParams.get('inputMint'),outputMint:u.searchParams.get('outputMint'),inAmount:u.searchParams.get('amount'),outAmount:u.searchParams.get('inputMint')===USDC?'1000000000':'200000000',swapMode:'ExactIn',routePlan:[{}]});
  };
  try{
    const enqueue=()=>book.fetch(new Request('https://i/enqueue',{method:'POST',body:JSON.stringify({signatures:[SIG],receivedAt:Date.now()})}));
    await enqueue();await enqueue();assert.equal((await store.list({prefix:'pending:'})).size,1);
    await book.alarm();assert.equal((await store.get('state')).fills,1);
    book=new PaperBook(ctx,env);await enqueue();await book.alarm();assert.equal((await store.get('state')).fills,1);
    assert.equal((await store.get('state')).cash,'9799000000');
  }finally{globalThis.fetch=oldFetch;}
});

test('commissioning endpoints deny unauthenticated calls before any upstream work',async()=>{
  const oldFetch=globalThis.fetch;globalThis.fetch=async()=>{throw Error('must not call upstream');};
  try{for(const [path,method]of [['preflight','POST'],['inspect?wallet='+W,'GET'],['connect','POST'],['tick','POST']]){
    const r=await worker.fetch(new Request('https://test/'+path,{method}),{ADMIN_TOKEN:'a'.repeat(64)});
    assert.equal(r.status,401);
  }}finally{globalThis.fetch=oldFetch;}
});
test('preflight validates provider data without initializing or funding a book',async()=>{
  const oldFetch=globalThis.fetch;globalThis.fetch=async(url)=>{
    const u=new URL(url);if(u.hostname==='mainnet.helius-rpc.com')return Response.json({result:{context:{slot:123},value:{data:{parsed:{info:{decimals:6}}}}}});
    return Response.json({inputMint:USDC,outputMint:SOL,inAmount:'200000000',outAmount:'1000000000',swapMode:'ExactIn',routePlan:[{}]});
  };
  try{const r=await worker.fetch(new Request('https://test/preflight',{method:'POST',headers:{Authorization:'Bearer '+'a'.repeat(64)}}),{ADMIN_TOKEN:'a'.repeat(64),HELIUS_API_KEY:'test',JUPITER_API_KEY:'test'});
    const body=await r.json();assert.equal(body.checks.helius.ok,true);assert.equal(body.checks.jupiter.ok,true);
  }finally{globalThis.fetch=oldFetch;}
});

test('real Solana v1 fixture decodes exact sold balance and uses v1 RPC opt-in',async()=>{
 const {readFile}=await import('node:fs/promises');
 const f=JSON.parse(await readFile(new URL('./fixtures/solana-v1-sell.json',import.meta.url),'utf8'));
 assert.equal(f.tx.version,1);
 const parsed=normalize(f.tx,f.signal.wallet,f.signal.signature,f.signal.receivedAt);
 assert.equal(parsed.side,'SELL');assert.equal(parsed.qty,'23390914675952');assert.equal(parsed.baseQty,'3023224962');
 const oldFetch=globalThis.fetch;globalThis.fetch=async(_url,opts)=>{
   const req=JSON.parse(opts.body);assert.equal(req.params[1].maxSupportedTransactionVersion,1);return Response.json({result:f.tx});
 };
 try{const r=await worker.fetch(new Request('https://test/inspect?wallet='+f.signal.wallet+'&signature='+f.signal.signature,{headers:{Authorization:'Bearer '+'a'.repeat(64)}}),{ADMIN_TOKEN:'a'.repeat(64),HELIUS_API_KEY:'test'});
   assert.equal((await r.json()).signal.side,'SELL');
 }finally{globalThis.fetch=oldFetch;}
});
test('diagnostic and recovery endpoints require admin authentication',async()=>{
 for(const [path,method] of [['audit','GET'],['connection','GET'],['resume-flat','POST']])assert.equal((await worker.fetch(new Request('https://x/'+path,{method}),{})).status,401);
});
test('recovery only clears overflow on a flat idle book and preserves balances',async()=>{
 const db=new Store(),env={ENABLED:'true',WALLETS:JSON.stringify([W]),HELIUS_API_KEY:'x',JUPITER_API_KEY:'y'},book=new PaperBook({storage:db,blockConcurrencyWhile:fn=>fn()},env);
 const state=initial(T);await db.put('state',state);await db.put('health',{entryBlocked:true,error:'reconciliation overflow: feed gap; new buys blocked'});
 const req=()=>new Request('https://internal/resume-flat',{method:'POST'});
 await db.put('pending:x',{});assert.equal((await book.fetch(req())).status,409);await db.delete('pending:x');
 state.positions.x={qty:'1'};await db.put('state',state);assert.equal((await book.fetch(req())).status,409);
 state.positions={};await db.put('state',state);assert.equal((await book.fetch(req())).status,200);assert.deepEqual(await db.get('state'),state);assert.equal(await db.get('health'),undefined);assert.equal((await db.list({prefix:'audit:'})).size,1);
});
test('100 row burst no longer falsely overflows the 1000 row recovery window',async()=>{
 const db=new Store(),env={ENABLED:'true',WALLETS:JSON.stringify([W]),HELIUS_API_KEY:'x',JUPITER_API_KEY:'y'},book=new PaperBook({storage:db,blockConcurrencyWhile:fn=>fn()},env);
 await db.put('state',initial(T));await db.put('cursor:'+W,'old');
 const run=n=>book.fetch(new Request('https://i/reconcile',{method:'POST',body:JSON.stringify({wallet:W,receivedAt:T+1000,rows:Array.from({length:n},(_,i)=>({signature:'s'+i,blockTime:T/1000,err:null}))})}));
 await run(100);assert.equal(await db.get('health'),undefined);
 await db.put('cursor:'+W,'old');await run(1000);assert.equal((await db.get('health')).entryBlocked,true);
});

test('metadata-only Token-2022 accepted; economic extensions and authorities rejected',()=>{
 const v={owner:'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb',data:{parsed:{info:{mintAuthority:null,freezeAuthority:null,decimals:6,extensions:[{extension:'metadataPointer',state:{authority:null}},{extension:'tokenMetadata',state:{updateAuthority:null}}]}}}};
 assert.equal(supportedMint(v,6),true);
 for(const name of ['transferFeeConfig','transferHook','permanentDelegate','defaultAccountState','pausable','unknown']){
  const x=structuredClone(v);x.data.parsed.info.extensions.push({extension:name});assert.equal(supportedMint(x,6),false);
 }
 for(const key of ['mintAuthority','freezeAuthority']){const x=structuredClone(v);x.data.parsed.info[key]='active';assert.equal(supportedMint(x,6),false);}
 const x=structuredClone(v);x.data.parsed.info.extensions[0].state.authority='active';assert.equal(supportedMint(x,6),false);
 assert.equal(supportedMint(v,9),false);assert.equal(supportedMint(null,6),false);
});

test('tight chase rejects a price accepted by standard without changing baseline accounting',()=>{
 const st=initial(T-1),s=signal(),p=plan(st,s,T+100),q=qt(p,{outAmount:'930000000'});
 assert.equal(fill(st,s,p,q,T+150,T+400,200000000n).state.fills,1);
 assert.throws(()=>fill(st,s,p,q,T+150,T+400,200000000n,{...POLICY,chaseBps:500n}),/chase/);
 assert.equal(st.fills,0);assert.equal(st.cash,'10000000000');
});
test('five experiments initialize independent books and preserve data after restart',async()=>{
 const {ScharoStandard,ScharoTight,MattStandard,MattTight,ThreeGjStandard}=await import('./worker.mjs');
 const env={ENABLED:'true',LABS_ENABLED:'true',HELIUS_API_KEY:'fixture',JUPITER_API_KEY:'fixture'};
 const stores=[];for(const C of [ScharoStandard,ScharoTight,MattStandard,MattTight,ThreeGjStandard]){const storage=new Store();stores.push(storage);const ctx={storage,blockConcurrencyWhile:fn=>fn()};const b=new C(ctx,env);await b.fetch(new Request('https://i/sweep',{method:'POST'}));await b.process({id:'mark',mark:true});const r=await new C(ctx,env).fetch(new Request('https://i/history')).then(r=>r.json());assert.equal(r.points.length,1);assert.equal(r.points[0].nav,'10000000000');}
 const changed=await stores[0].get('state');changed.cash='1';await stores[0].put('state',changed);
 for(const s of stores.slice(1))assert.equal((await s.get('state')).cash,'10000000000');
});
test('experiment refuses swap not paid by watched wallet',async()=>{
 const {MattStandard,LABS}=await import('./worker.mjs');const wallet=LABS.find(l=>l.id==='matt-standard').wallet;
 const storage=new Store(),ctx={storage,blockConcurrencyWhile:fn=>fn()},b=new MattStandard(ctx,{LABS_ENABLED:'true',HELIUS_API_KEY:'f',JUPITER_API_KEY:'f'});
 await storage.put('state',initial(Date.now()-10000));await storage.put('verified-v2:'+SIG,{type:'SWAP',tx:transaction()});
 await b.process({id:SIG+':'+wallet,signature:SIG,wallet,receivedAt:Date.now()});
 assert.equal((await storage.get('state')).fills,0);const rows=[...(await storage.list({prefix:'event:'})).values()];assert.equal(rows[0].reason,'wallet not fee payer');
});
test('history and comparison endpoints reject anonymous access',async()=>{
 for(const p of ['/history','/lab'])assert.equal((await worker.fetch(new Request('https://i'+p),{})).status,401);
});
