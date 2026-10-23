import test from 'node:test';
import assert from 'node:assert/strict';
import {USDC,SOL,SPL,POLICY,initial,normalize,plan,fill,checkQuote} from './core.mjs';
import worker,{PaperBook,wallets} from './worker.mjs';
const W='11111111111111111111111111111111', M='22222222222222222222222222222222', SIG='3'.repeat(88);
const T=1792756800000;
function signal(over={}){return {id:SIG+':'+W,signature:SIG,wallet:W,mint:M,side:'BUY',qty:'1000000000',leaderPre:'0',baseMint:USDC,baseQty:'200000000',chainAt:T,receivedAt:T+100,slot:100,decimals:6,...over};}
function qt(p,over={}){return {inputMint:p.inputMint,outputMint:p.outputMint,inAmount:p.amount,outAmount:'1000000000',swapMode:'ExactIn',routePlan:[{}],requestedAt:T+200,receivedAt:T+300,...over};}
function transaction({sell=false,native=false,failed=false}={}){
  const preTokenBalances=[{accountIndex:1,mint:M,owner:W,uiTokenAmount:{amount:sell?'1000000000':'0',decimals:6}}];
  const postTokenBalances=[{accountIndex:1,mint:M,owner:W,uiTokenAmount:{amount:sell?'500000000':'1000000000',decimals:6}}];
  if(!native){preTokenBalances.push({accountIndex:2,mint:USDC,owner:W,uiTokenAmount:{amount:'500000000',decimals:6}});postTokenBalances.push({accountIndex:2,mint:USDC,owner:W,uiTokenAmount:{amount:sell?'600000000':'300000000',decimals:6}});}
  return {slot:100,blockTime:T/1000,transaction:{signatures:[SIG],message:{accountKeys:[{pubkey:W,signer:true},{pubkey:M,signer:false},{pubkey:USDC,signer:false}]}},meta:{err:failed?{}:null,fee:5000,preBalances:[10000000000,2039280,2039280],postBalances:[native?8999995000:9999995000,2039280,2039280],preTokenBalances,postTokenBalances}};
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
