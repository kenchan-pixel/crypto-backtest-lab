import {USDC,SOL,SPL,POLICY,initial,integer,normalize,plan,fill,checkQuote,keyOf} from './core.mjs';
const json=(v,status=200)=>Response.json(v,{status,headers:{'Cache-Control':'no-store'}});
const address=x=>typeof x==='string'&&/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(x);
export function wallets(env) {
  const w=JSON.parse(env.WALLETS||'[]');
  if(!Array.isArray(w)||w.length>3||w.some(x=>!address(x))||new Set(w).size!==w.length)throw Error('invalid allowlist');
  return w;
}
async function auth(request,secret) {
  if(!secret||secret.length<32)return false;
  const digest=async s=>new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)));
  const a=await digest(request.headers.get('Authorization')||''),b=await digest(`Bearer ${secret}`);
  let diff=0;for(let i=0;i<a.length;i++)diff|=a[i]^b[i];return diff===0;
}
async function remote(url,opts={}) {
  const r=await fetch(url,{...opts,signal:AbortSignal.timeout(3000)});
  if(!r.ok)throw Error(`upstream HTTP ${r.status}`);
  return r.json(); // Never include credential-bearing URLs or raw upstream errors in logs.
}
export async function rpc(env,method,params) {
  if(!['getTransaction','getAccountInfo','getSignaturesForAddress'].includes(method))throw Error('RPC method forbidden');
  const r=await remote(`https://mainnet.helius-rpc.com/?api-key=${encodeURIComponent(env.HELIUS_API_KEY)}`,
    {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});
  if(r.error||r.result===null)throw Error('RPC unavailable');return r.result;
}
export async function quote(env,p) {
  // Single serialized book; leave headroom below the free-key 1 request/second limit.
  await new Promise(resolve=>setTimeout(resolve,1100));
  const u=new URL('https://api.jup.ag/swap/v2/order');
  for(const [k,v] of Object.entries({inputMint:p.inputMint,outputMint:p.outputMint,amount:p.amount,swapMode:'ExactIn',slippageBps:100}))u.searchParams.set(k,String(v));
  const requestedAt=Date.now();
  const q=await remote(u,{headers:{'x-api-key':env.JUPITER_API_KEY}});
  return {...q,requestedAt,receivedAt:Date.now()}; // No taker, signing, /execute or /swap POST.
}
function configured(env) {return env.ENABLED==='true'&&env.HELIUS_API_KEY&&env.JUPITER_API_KEY&&wallets(env).length;}
function stub(env){return env.BOOK.get(env.BOOK.idFromName('copy-paper-v1'));}
export default {
  async fetch(request,env) {
    const path=new URL(request.url).pathname;
    if(path==='/health'&&request.method==='GET')return json({paperOnly:true,configured:Boolean(configured(env))});
    if(path==='/status'&&request.method==='GET') {
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      return stub(env).fetch('https://internal/status');
    }
    if(path!='/webhook'||request.method!=='POST')return json({error:'not found'},404);
    if(!await auth(request,env.WEBHOOK_SECRET))return json({error:'unauthorized'},401);
    if(!configured(env))return json({error:'not configured'},503);
    // Read with a hard bound even if Content-Length is missing or false.
    const reader=request.body?.getReader(); if(!reader)return json({error:'body required'},400);
    let bytes=0,chunks=[];
    while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.length;if(bytes>262144){await reader.cancel();return json({error:'too large'},413);}chunks.push(value);}
    let events;try{const b=new Uint8Array(bytes);let i=0;for(const c of chunks){b.set(c,i);i+=c.length;}events=JSON.parse(new TextDecoder().decode(b));}catch{return json({error:'invalid JSON'},400);}
    if(!Array.isArray(events)||events.length>100)return json({error:'invalid batch'},400);
    const signatures=[...new Set(events.map(x=>x.signature))];
    if(signatures.some(x=>typeof x!=='string'||!/^[1-9A-HJ-NP-Za-km-z]{64,88}$/.test(x)))return json({error:'invalid signature'},400);
    return stub(env).fetch('https://internal/enqueue',{method:'POST',body:JSON.stringify({signatures,receivedAt:Date.now()})});
  },
  async scheduled(_event,env,ctx) {
    if(!configured(env))return;
    ctx.waitUntil((async()=>{
      // Recovery feed: recent confirmed signatures, deduplicated by the ledger.
      // Overflow is surfaced; historical gaps are not silently filled at old prices.
      for(const w of wallets(env)){
        const rows=await rpc(env,'getSignaturesForAddress',[w,{limit:100,commitment:'confirmed'}]);
        await stub(env).fetch('https://internal/reconcile',{method:'POST',body:JSON.stringify({wallet:w,rows,receivedAt:Date.now()})});
      }
      await stub(env).fetch('https://internal/sweep',{method:'POST'});
    })());
  }
};
export class PaperBook {
  constructor(ctx,env){this.ctx=ctx;this.env=env;}
  async fetch(request) {
    return this.ctx.blockConcurrencyWhile(async()=>{
      const path=new URL(request.url).pathname, db=this.ctx.storage;
      if(path==='/status') {
        const s=await db.get('state');
        return json({paperOnly:true,configured:Boolean(configured(this.env)),state:s||null,
          marks:await db.get('marks')||null,health:await db.get('health')||null,
          queued:(await db.list({prefix:'pending:',limit:1000})).size,
          recent:[...(await db.list({prefix:'audit:',reverse:true,limit:20})).values()]});
      }
      if(!configured(this.env))return json({error:'not configured'},503);
      let s=await db.get('state');if(!s){s=initial(Date.now());await db.put('state',s);}
      if(path==='/enqueue'||path==='/reconcile') {
        const data=await request.json(), ws=wallets(this.env);
        let signatures=data.signatures;
        if(path==='/reconcile'){
          if(!ws.includes(data.wallet)||!Array.isArray(data.rows))return json({error:'invalid reconciliation'},400);
          const cursor=await db.get(`cursor:${data.wallet}`);
          if(cursor&&!data.rows.some(x=>x.signature===cursor)&&data.rows.length===100)
            await db.put('health',{at:Date.now(),error:'reconciliation overflow: feed gap; new buys blocked',entryBlocked:true});
          signatures=data.rows.filter(x=>!x.err&&x.blockTime*1000>=s.startedAt).map(x=>x.signature).reverse();
          if(data.rows[0])await db.put(`cursor:${data.wallet}`,data.rows[0].signature);
        }
        for(const sig of signatures)for(const wallet of ws){
          const id=`${sig}:${wallet}`;
          if(!await db.get(`done:${id}`)&&!await db.get(`pending:${id}`))
            await db.put(`pending:${id}`,{id,signature:sig,wallet,receivedAt:data.receivedAt,attempts:0,nextAt:0});
        }
      } else if(path==='/sweep') {
        for(const [k,p] of Object.entries(s.positions))if(p.exitPending||Date.now()-p.openedAt>=POLICY.maxHoldMs){
          const id=`expiry:${k}:${p.openedAt}`;
          if(!await db.get(`pending:${id}`))await db.put(`pending:${id}`,{id,expiry:true,wallet:p.wallet,mint:p.mint,receivedAt:Date.now(),attempts:0,nextAt:0});
        }
        // Marking is a separate alarm item; never invent a price when a route disappears.
        if(!await db.get('pending:mark'))await db.put('pending:mark',{id:'mark',mark:true,nextAt:0,attempts:0});
      } else return json({error:'not found'},404);
      await db.setAlarm(Date.now()+100);return json({accepted:true});
    });
  }
  async alarm(){
    return this.ctx.blockConcurrencyWhile(async()=>{
      const db=this.ctx.storage;
      if(!configured(this.env))return;
      const pending=await db.list({prefix:'pending:',limit:1000});
      const ready=[...pending.values()].filter(x=>x.nextAt<=Date.now()).sort((a,b)=>(a.receivedAt||0)-(b.receivedAt||0));
      const job=ready[0];
      if(job)try{await this.process(job);}catch{
        job.attempts++;job.nextAt=Date.now()+Math.min(60000,1000*2**Math.min(job.attempts,6));
        await db.put(`pending:${job.id}`,job);
        const health=await db.get('health')||{};
        await db.put('health',{...health,at:Date.now(),error:'processing unavailable; retry pending'});
      }
      const left=await db.list({prefix:'pending:',limit:1000});
      if(left.size)await db.setAlarm(Math.max(Date.now()+100,Math.min(...[...left.values()].map(x=>x.nextAt))));
    });
  }
  async finish(job,result,state) {
    const db=this.ctx.storage, now=Date.now();
    await db.transaction(async t=>{
      if(state)await t.put('state',state);
      await t.put(`audit:${String(now).padStart(13,'0')}:${job.id}`,result);
      if(!job.mark)await t.put(`done:${job.id}`,{at:now,status:result.status});
      await t.delete(`pending:${job.id}`);
    });
  }
  async process(job) {
    const db=this.ctx.storage, env=this.env, state=await db.get('state');
    if(job.mark){
      // One position per alarm to keep network work below the concurrency timeout.
      const fingerprint=JSON.stringify(state);
      if(job.fingerprint!==fingerprint){job.index=0;job.fingerprint=fingerprint;}
      const positions=Object.entries(state.positions), index=job.index||0;
      if(index===0)job.values={};
      if(index<positions.length){
        const [key,p]=positions[index];
        try{const spec={inputMint:p.mint,outputMint:USDC,amount:p.qty},at=Date.now(),q=await quote(env,spec);
          job.values[key]={net:String(checkQuote(q,spec,at,Date.now())-POLICY.fee),at:q.receivedAt};
        }catch{job.values[key]={net:null,at:Date.now(),error:'no usable liquidation quote'};}
        job.index=index+1;await db.put('pending:mark',job);return;
      }
      const complete=Object.keys(job.values).length===positions.length&&positions.every(([k])=>job.values[k]?.net!==null);
      const nav=complete?String(integer(state.cash)+Object.values(job.values).reduce((v,x)=>v+BigInt(x.net),0n)):null;
      await db.put('marks',{at:Date.now(),cash:state.cash,positions:job.values,nav,complete,nonSimultaneous:true});
      await this.finish(job,{status:'MARK',nav,complete});return;
    }
    let s=job.signal;
    if(!s){
      if(job.expiry){
        const p=state.positions[`${job.wallet}:${job.mint}`];
        if(!p){await this.finish(job,{status:'SKIP',reason:'position already closed'});return;}
        s={id:job.id,wallet:job.wallet,mint:job.mint,side:'SELL',qty:p.qty,leaderPre:p.qty,
          chainAt:state.startedAt,receivedAt:job.receivedAt,expiry:true};
      }else{
        let verified=await db.get(`verified:${job.signature}`);
        if(!verified){
          await new Promise(resolve=>setTimeout(resolve,550)); // Helius free Enhanced API rate.
          const enhanced=await remote(`https://api-mainnet.helius-rpc.com/v0/transactions?api-key=${encodeURIComponent(env.HELIUS_API_KEY)}`,
            {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({transactions:[job.signature]})});
          if(enhanced[0]?.signature!==job.signature)throw Error('transaction not available');
          verified={type:enhanced[0].type,observedAt:Date.now()};
          if(verified.type==='SWAP')verified.tx=await rpc(env,'getTransaction',[job.signature,{encoding:'jsonParsed',commitment:'confirmed',maxSupportedTransactionVersion:0}]);
          await db.put(`verified:${job.signature}`,verified);
        }
        if(verified.type!=='SWAP'){await this.finish(job,{status:'SKIP',reason:'not a supported swap'});return;}
        const tx=verified.tx;
        try{s=normalize(tx,job.wallet,job.signature,job.receivedAt);}catch(e){await this.finish(job,{status:'SKIP',reason:e.message});return;}
        await db.put(`source:${job.id}`,tx);
      }
      job.signal=s;await db.put(`pending:${job.id}`,job);
    }
    let p;
    try{
      if(s.side==='BUY'&&(await db.get('health'))?.entryBlocked)throw Error('health gate; manual review required');
      if(s.side==='BUY'&&[...(await db.list({prefix:'pending:',limit:1000})).values()].some(j=>j.id!==job.id&&j.attempts>0&&!j.mark))throw Error('unresolved prior event');
      const last=await db.get(`last:${keyOf(s)}`);
      if(!s.expiry&&last&&s.slot<last.slot)throw Error('out-of-order leader event');
      p=plan(state,s,Date.now());
    }catch(e){await this.finish(job,{status:'SKIP',reason:e.message,signal:s});return;}
    if(s.side==='BUY'){
      const mint=await rpc(env,'getAccountInfo',[s.mint,{encoding:'jsonParsed',commitment:'confirmed'}]);
      const info=mint.value?.data?.parsed?.info;
      if(mint.value?.owner!==SPL||!info||info.mintAuthority!==null||info.freezeAuthority!==null||info.decimals!==s.decimals){
        await this.finish(job,{status:'SKIP',reason:'mint authority/freeze/extension/decimals gate',signal:s});return;
      }
    }
    const decisionAt=Date.now();
    await db.put(`decision:${job.id}:${job.attempts}`,{signal:s,plan:p,at:decisionAt});
    let leaderUsdc=0n, q;
    try{
      if(s.side==='BUY'){
        if(s.baseMint===USDC)leaderUsdc=integer(s.baseQty);
        else {
          const fp={inputMint:SOL,outputMint:USDC,amount:s.baseQty},fx=await quote(env,fp);
          checkQuote(fx,fp,decisionAt,Date.now());leaderUsdc=integer(fx.outAmount);
          await db.put(`fx:${job.id}:${job.attempts}`,fx);
        }
      }
      // A reverse route is required before buying. This is not a guarantee of future liquidity.
      if(s.side==='BUY'){
        const preview=await quote(env,p),previewOut=checkQuote(preview,p,decisionAt,Date.now());
        const reverse={inputMint:s.mint,outputMint:USDC,amount:String(previewOut)},rq=await quote(env,reverse);
        const net=checkQuote(rq,reverse,decisionAt,Date.now());
        if(net*100n<POLICY.ticket*90n)throw Error('roundtrip loss gate');
        await db.put(`reverse:${job.id}`,rq);
      }
      // Use a NEW quote after all gates; never choose an older fill using newer information.
      q=await quote(env,p);
      const result=fill(state,s,p,q,decisionAt,Date.now(),leaderUsdc);
      if(!s.expiry)await db.put(`last:${keyOf(s)}`,{slot:s.slot});
      await this.finish(job,{status:'FILLED',signal:s,plan:p,quote:q,receipt:result.receipt},result.state);
    }catch(e){
      if(s.side==='BUY'){await this.finish(job,{status:'SKIP',reason:e.message.startsWith('upstream')?'quote unavailable':e.message,signal:s});return;}
      const pos=state.positions[keyOf(s)];if(pos){pos.exitPending=true;await db.put('state',state);}throw e;
    }
  }
}
