import {USDC,SOL,SPL,POLICY,initial,integer,normalize,plan,fill,checkQuote,keyOf} from './core.mjs';
const THREE_GJ='3eGj9qx6D4CADVzunDN8MLcGsP3BXQabZ8xReEdgML6a';
const SCHARO='4sAUSQFdvWRBxR8UoLBYbw8CcXuwXWxnN8pXa4mtm5nU',MATT='3bzaJd5yZG73EVDz8xosQb7gfZm2LN5auFGh6wnP1n1f';
export const LABS=[{id:'3egj-standard',binding:'THREE_GJ_STANDARD',wallet:THREE_GJ,chaseBps:'1500'},{id:'scharo-standard',binding:'SCHARO_STANDARD',wallet:SCHARO,chaseBps:'1500'},{id:'scharo-tight',binding:'SCHARO_TIGHT',wallet:SCHARO,chaseBps:'500'},{id:'matt-standard',binding:'MATT_STANDARD',wallet:MATT,chaseBps:'1500'},{id:'matt-tight',binding:'MATT_TIGHT',wallet:MATT,chaseBps:'500'}];
const labStub=(env,l)=>env[l.binding].get(env[l.binding].idFromName('forward-v1'));
const registryStub=env=>env.DYNAMIC_REGISTRY.get(env.DYNAMIC_REGISTRY.idFromName('registry-v1'));
const dynamicStub=(env,id)=>env.DYNAMIC_BOOK.get(env.DYNAMIC_BOOK.idFromName(id));
const registryJson=async(env,path,opts={})=>{
  const r=await registryStub(env).fetch('https://internal'+path,opts);
  const body=await r.json(); if(!r.ok)throw Object.assign(Error(body.error||'dynamic registry unavailable'),{status:r.status,body});
  return body;
};
const dynamicAccounts=async env=>(await registryJson(env,'/list')).accounts;
const watchWallets=async env=>[...new Set([...wallets(env),...(env.LABS_ENABLED==='true'?LABS.map(l=>l.wallet):[]),
  ...(await dynamicAccounts(env)).filter(x=>x.status!=='archived').map(x=>x.wallet)])];
const accountIdFor=async wallet=>{
  const bytes=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(wallet)));
  return 'dyn-'+[...bytes].slice(0,6).map(x=>x.toString(16).padStart(2,'0')).join('');
};
async function ensureWebhook(env){
  if(!env.WEBHOOK_SECRET)throw Error('webhook secret unavailable');
  const endpoint=`https://api-mainnet.helius-rpc.com/v0/webhooks?api-key=${encodeURIComponent(env.HELIUS_API_KEY)}`;
  const webhookURL='https://ken-copy-paper.kenchan-528.workers.dev/webhook';
  const accounts=await watchWallets(env), existing=await remote(endpoint), match=existing.find(x=>x.webhookURL===webhookURL);
  if(match&&JSON.stringify(match.accountAddresses)===JSON.stringify(accounts)&&JSON.stringify(match.transactionTypes)===JSON.stringify(['ANY']))
    return {webhookID:match.webhookID,webhookURL,existing:true,accounts};
  const target=match?`https://api-mainnet.helius-rpc.com/v0/webhooks/${encodeURIComponent(match.webhookID)}?api-key=${encodeURIComponent(env.HELIUS_API_KEY)}`:endpoint;
  const r=await remote(target,{method:match?'PUT':'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({webhookURL,transactionTypes:['ANY'],accountAddresses:accounts,webhookType:'enhanced',authHeader:`Bearer ${env.WEBHOOK_SECRET}`})});
  return {webhookID:r.webhookID||match?.webhookID,webhookURL,created:!match,updated:Boolean(match),accounts};
}
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
  if(r.error)throw Error('RPC error '+Number(r.error.code));if(r.result===null)throw Error('RPC result null');return r.result;
}
export async function quote(env,p) {
  if(env.QUOTE_GATE){const r=await env.QUOTE_GATE.get(env.QUOTE_GATE.idFromName("global")).fetch("https://internal/quote",{method:"POST",body:JSON.stringify(p)});if(!r.ok)throw Error("quote unavailable");return r.json();}
  // Single serialized book; leave headroom below the free-key 1 request/second limit.
  await new Promise(resolve=>setTimeout(resolve,1100));
  const u=new URL('https://api.jup.ag/swap/v2/order');
  for(const [k,v] of Object.entries({inputMint:p.inputMint,outputMint:p.outputMint,amount:p.amount,swapMode:'ExactIn',slippageBps:100}))u.searchParams.set(k,String(v));
  const requestedAt=Date.now();
  const q=await remote(u,{headers:{'x-api-key':env.JUPITER_API_KEY}});
  return {...q,requestedAt,receivedAt:Date.now()}; // No taker, signing, /execute or /swap POST.
}
export function supportedMint(value,decimals) {
  const info=value?.data?.parsed?.info;
  if(!info||info.mintAuthority!==null||info.freezeAuthority!==null||info.decimals!==decimals)return false;
  if(value.owner===SPL)return !info.extensions?.length;
  if(value.owner!=='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'||!Array.isArray(info.extensions))return false;
  return info.extensions.every(e=>e.extension==='metadataPointer'?e.state?.authority===null:e.extension==='tokenMetadata'?e.state?.updateAuthority===null:false);
}
function configured(env) {return env.ENABLED==='true'&&env.HELIUS_API_KEY&&env.JUPITER_API_KEY&&wallets(env).length;}
function stub(env){return env.BOOK.get(env.BOOK.idFromName('copy-paper-v1'));}
export default {
  async fetch(request,env) {
    const path=new URL(request.url).pathname;
    if(path==='/lab'||path==='/history'){
      if(request.method!=='GET'||!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      if(path==='/history')return stub(env).fetch('https://internal/history');
      const books=[];for(const l of LABS){const s=await labStub(env,l).fetch('https://internal/status').then(r=>r.json());const h=await labStub(env,l).fetch('https://internal/history').then(r=>r.json());books.push({...l,...s,history:h.points});}
      for(const c of (await dynamicAccounts(env)).filter(x=>x.status!=='archived')){const s=await dynamicStub(env,c.id).fetch('https://internal/status').then(r=>r.json());const h=await dynamicStub(env,c.id).fetch('https://internal/history').then(r=>r.json());books.push({id:c.id,binding:'DYNAMIC_BOOK',wallet:c.wallet,chaseBps:String(c.chaseBps),label:c.label,dynamic:true,status:c.status,...s,history:h.points});}
      return json({paperOnly:true,experimental:true,dynamicAccounts:true,observedAt:Date.now(),books});
    }
    if(path==='/dynamic'&&request.method==='GET'){
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      return json({paperOnly:true,accounts:await dynamicAccounts(env)});
    }
    if(path==='/dynamic/create'&&request.method==='POST'){
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      if(!env.HELIUS_API_KEY||!env.JUPITER_API_KEY)return json({error:'not configured'},503);
      let data;try{data=await request.json();}catch{return json({error:'invalid JSON'},400);}
      const wallet=data.wallet, chaseBps=data.chaseBps??1500, label=String(data.label||'').trim().slice(0,64);
      if(!address(wallet)||!Number.isSafeInteger(chaseBps)||chaseBps<0||chaseBps>5000)return json({error:'invalid dynamic account'},400);
      const id=await accountIdFor(wallet), now=Date.now();
      const cfg={id,wallet,label:label||wallet.slice(0,6)+'…'+wallet.slice(-4),chaseBps,status:'paused',createdAt:now,startedAt:now};
      try{
        const created=await registryJson(env,'/create',{method:'POST',body:JSON.stringify(cfg)});
        await dynamicStub(env,id).fetch('https://internal/configure',{method:'POST',body:JSON.stringify(created.account)});
        let hook;try{hook=await ensureWebhook(env);}catch(e){return json({paperOnly:true,account:created.account,activated:false,error:'webhook sync failed; account remains paused'},502);}
        const active=await registryJson(env,'/update',{method:'POST',body:JSON.stringify({id,status:'active'})});
        await dynamicStub(env,id).fetch('https://internal/configure',{method:'POST',body:JSON.stringify(active.account)});
        return json({paperOnly:true,account:active.account,activated:true,webhook:hook},201);
      }catch(e){return json(e.body||{error:e.message},e.status||409);}
    }
    if(path==='/dynamic/status'&&request.method==='GET'){
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      const id=new URL(request.url).searchParams.get('id'); if(!/^dyn-[a-f0-9]{12}$/.test(id||''))return json({error:'invalid id'},400);
      try{const account=(await registryJson(env,'/get?id='+encodeURIComponent(id))).account;const status=await dynamicStub(env,id).fetch('https://internal/status').then(r=>r.json());const history=await dynamicStub(env,id).fetch('https://internal/history').then(r=>r.json());return json({paperOnly:true,account,status,history:history.points});}
      catch(e){return json(e.body||{error:e.message},e.status||404);}
    }
    if((path==='/dynamic/pause'||path==='/dynamic/resume')&&request.method==='POST'){
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      const id=new URL(request.url).searchParams.get('id'); if(!/^dyn-[a-f0-9]{12}$/.test(id||''))return json({error:'invalid id'},400);
      try{const next=path.endsWith('pause')?'paused':'active';const updated=await registryJson(env,'/update',{method:'POST',body:JSON.stringify({id,status:next})});await dynamicStub(env,id).fetch('https://internal/configure',{method:'POST',body:JSON.stringify(updated.account)});if(next==='active')await ensureWebhook(env);return json({paperOnly:true,account:updated.account});}
      catch(e){return json(e.body||{error:e.message},e.status||409);}
    }
    if(path==='/health'&&request.method==='GET')return json({paperOnly:true,configured:Boolean(configured(env))});
    if(path==='/resume-flat'&&request.method==='POST') {
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      return stub(env).fetch('https://internal/resume-flat',{method:'POST'});
    }
    if(path==='/audit'&&request.method==='GET') {
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      const before=new URL(request.url).searchParams.get('before');
      if(before&&!/^audit:[0-9]{13}:[A-Za-z0-9:_-]+$/.test(before))return json({error:'invalid cursor'},400);
      return stub(env).fetch('https://internal/audit'+(before?'?before='+encodeURIComponent(before):''));
    }
    if(path==='/connection'&&request.method==='GET') {
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      try {
        const all=await remote(`https://api-mainnet.helius-rpc.com/v0/webhooks?api-key=${encodeURIComponent(env.HELIUS_API_KEY)}`);
        return json({wallets:wallets(env),webhooks:all.filter(x=>x.webhookURL==='https://ken-copy-paper.kenchan-528.workers.dev/webhook').map(x=>({id:x.webhookID,accounts:x.accountAddresses,type:x.webhookType,transactions:x.transactionTypes,authMatches:x.authHeader===`Bearer ${env.WEBHOOK_SECRET}`}))});
      }catch{return json({error:'webhook inspection unavailable'},502);}
    }
    if(path==='/connect'&&request.method==='POST') {
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      if(!configured(env)||!env.WEBHOOK_SECRET)return json({error:'not configured'},503);
      try {return json(await ensureWebhook(env));}
      catch(e){return json({error:e.message.startsWith('upstream')?e.message:'webhook setup unavailable'},502);}
    }
    if(path==='/tick'&&request.method==='POST') {
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      if(!configured(env))return json({error:'not configured'},503);
      const work=[];await this.scheduled({},env,{waitUntil:p=>work.push(p)});await Promise.all(work);
      return stub(env).fetch('https://internal/status');
    }
    if(path==='/inspect'&&request.method==='GET') {
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      const u=new URL(request.url);
      const mint=u.searchParams.get('mint');
      if(mint){if(!address(mint))return json({error:'invalid mint'},400);return json(await rpc(env,'getAccountInfo',[mint,{encoding:'jsonParsed',commitment:'confirmed'}]));}
      const wallet=u.searchParams.get('wallet'),sig=u.searchParams.get('signature'),before=u.searchParams.get('before');
      if(!address(wallet)||[sig,before].some(x=>x&&!/^[1-9A-HJ-NP-Za-km-z]{64,88}$/.test(x)))return json({error:'invalid query'},400);
      try {
        if(sig){const tx=await rpc(env,'getTransaction',[sig,{encoding:'jsonParsed',commitment:'confirmed',maxSupportedTransactionVersion:1}]);
          let signal;try{signal=normalize(tx,wallet,sig,Date.now());}catch(e){signal={unsupported:e.message};}
          return json({signal,tx});}
        const endpoint=new URL(`https://api-mainnet.helius-rpc.com/v0/addresses/${wallet}/transactions`);
        endpoint.searchParams.set('api-key',env.HELIUS_API_KEY);endpoint.searchParams.set('limit','100');
        if(before)endpoint.searchParams.set('before',before);
        return json({wallet,observedAt:Date.now(),rows:await remote(endpoint)});
      }catch(e){return json({error:/^(RPC error -?[0-9]+|RPC result null|upstream HTTP [0-9]+)$/.test(e.message)?e.message:'source unavailable'},502);}
    }
    if(path==='/preflight'&&request.method==='POST') {
      if(!await auth(request,env.ADMIN_TOKEN))return json({error:'unauthorized'},401);
      const target=new URL(request.url).searchParams.get('mint')||SOL;
      if(!address(target))return json({error:'invalid mint'},400);
      const checks={};
      try { const r=await rpc(env,'getAccountInfo',[USDC,{encoding:'jsonParsed',commitment:'confirmed'}]);
        checks.helius={ok:r.value?.data?.parsed?.info?.decimals===6,slot:r.context?.slot};
      }catch {checks.helius={ok:false,error:'RPC authentication or availability failed'};}
      try { const at=Date.now(),p={inputMint:USDC,outputMint:target,amount:'200000000'},q=await quote(env,p);
        checkQuote(q,p,at,Date.now());checks.jupiter={ok:true,inputMint:q.inputMint,outputMint:q.outputMint,inAmount:q.inAmount,outAmount:q.outAmount,requestedAt:q.requestedAt,receivedAt:q.receivedAt};
      }catch(e) {checks.jupiter={ok:false,error:e.message.startsWith('upstream')?e.message:'quote schema or route validation failed'};}
      return json({paperOnly:true,checkedAt:Date.now(),checks});
    }
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
    const receivedAt=Date.now();
    const send=async(target,allowed)=>{const selected=webhookSignatures(events,allowed);if(!selected.length)return;
      await target.fetch('https://internal/enqueue',{method:'POST',body:JSON.stringify({signatures:selected,receivedAt})});};
    await send(stub(env),wallets(env));
    if(env.LABS_ENABLED==='true')for(const l of LABS)await send(labStub(env,l),[l.wallet]);
    for(const c of (await dynamicAccounts(env)).filter(x=>x.status==='active'))await send(dynamicStub(env,c.id),[c.wallet]);
    return json({accepted:true});
  },
  async scheduled(_event,env,ctx) {
    if(!configured(env))return;
    ctx.waitUntil((async()=>{
      // Recovery feed: recent confirmed signatures, deduplicated by the ledger.
      // Overflow is surfaced; historical gaps are not silently filled at old prices.
      for(const w of wallets(env)){
        const rows=await rpc(env,'getSignaturesForAddress',[w,{limit:1000,commitment:'confirmed'}]);
        await stub(env).fetch('https://internal/reconcile',{method:'POST',body:JSON.stringify({wallet:w,rows,receivedAt:Date.now()})});
      }
      await stub(env).fetch('https://internal/sweep',{method:'POST'});
      if(env.LABS_ENABLED==='true'){
        for(const wallet of [...new Set(LABS.map(l=>l.wallet))]){
          const rows=await rpc(env,'getSignaturesForAddress',[wallet,{limit:1000,commitment:'confirmed'}]);
          for(const l of LABS.filter(l=>l.wallet===wallet)){await labStub(env,l).fetch('https://internal/reconcile',{method:'POST',body:JSON.stringify({wallet,rows,receivedAt:Date.now()})});await labStub(env,l).fetch('https://internal/sweep',{method:'POST'});}
        }
      }
      for(const c of (await dynamicAccounts(env)).filter(x=>x.status==='active')){
        const rows=await rpc(env,'getSignaturesForAddress',[c.wallet,{limit:1000,commitment:'confirmed'}]);
        await dynamicStub(env,c.id).fetch('https://internal/reconcile',{method:'POST',body:JSON.stringify({wallet:c.wallet,rows,receivedAt:Date.now()})});
        await dynamicStub(env,c.id).fetch('https://internal/sweep',{method:'POST'});
      }
    })());
  }
};
export class PaperBook {
  constructor(ctx,env){this.ctx=ctx;this.env=env;this.policy=POLICY;this.experimental=false;this.walletOverride=null;this.enabledOverride=null;}
  sourceWallets(){return this.walletOverride||wallets(this.env);}
  isConfigured(){return (this.enabledOverride??(this.env.ENABLED==='true'))&&this.env.HELIUS_API_KEY&&this.env.JUPITER_API_KEY&&this.sourceWallets().length>0;}
  async fetch(request) {
    return this.ctx.blockConcurrencyWhile(async()=>{
      const path=new URL(request.url).pathname, db=this.ctx.storage;
      if(path==='/history'){const points=[...(await db.list({prefix:'nav:',reverse:true,limit:2016})).values()].reverse();return json({points,scope:'5-minute observed marks, up to 7 days; no backfill'});}
      if(path==='/resume-flat') {
        const s=await db.get('state'),h=await db.get('health');
        if(!this.isConfigured()||!s||Object.keys(s.positions).length||(await db.list({prefix:'pending:',limit:1})).size)return json({error:'requires enabled flat book and empty queue'},409);
        if(!h?.entryBlocked)return json({error:'not a reconciliation block'},409);
        const at=Date.now();
        await db.transaction(async t=>{await t.put(`audit:${at}:recovery`,{status:'RECOVERY',reason:'operator reviewed flat book; resume future entries only',previousHealth:h});await t.delete('health');});
        return json({resumed:true,at});
      }
      if(path==='/audit') {
        const before=new URL(request.url).searchParams.get('before');
        const page=await db.list({prefix:'audit:',reverse:true,limit:200,...(before?{end:before}:{})});
        return json({rows:[...page].filter(([,v])=>v.status!=='MARK').map(([id,v])=>({id,...v})),next:page.size===200?[...page.keys()].at(-1):null});
      }
      if(path==='/status') {
        const s=await db.get('state');
        return json({paperOnly:true,configured:Boolean(this.isConfigured()),state:s||null,
          marks:await db.get('marks')||null,health:await db.get('health')||null,
          queued:(await db.list({prefix:'pending:',limit:1000})).size,
          recent:[...(await db.list({prefix:'event:',reverse:true,limit:20})).values()]});
      }
      if(!this.isConfigured())return json({error:'not configured'},503);
      let s=await db.get('state');if(!s){s=initial(Date.now());await db.put('state',s);}
      if(path==='/enqueue'||path==='/reconcile') {
        const data=await request.json(), ws=this.sourceWallets();
        let signatures=data.signatures;
        if(path==='/reconcile'){
          if(!ws.includes(data.wallet)||!Array.isArray(data.rows))return json({error:'invalid reconciliation'},400);
          const cursor=await db.get(`cursor:${data.wallet}`);
          if(cursor&&!data.rows.some(x=>x.signature===cursor)&&data.rows.length>=1000)
            await db.put('health',{at:Date.now(),error:'reconciliation overflow: feed gap; new buys blocked',entryBlocked:true,wallet:data.wallet,previousCursor:cursor});
          signatures=data.rows.filter(x=>!x.err&&x.blockTime*1000>=s.startedAt).map(x=>x.signature).reverse();
          if(data.rows[0])await db.put(`cursor:${data.wallet}`,data.rows[0].signature);
        }
        for(const sig of signatures)for(const wallet of ws){
          const id=`${sig}:${wallet}`;
          if(!await db.get(`done:${id}`)&&!await db.get(`pending:${id}`))
            await db.put(`pending:${id}`,{id,signature:sig,wallet,receivedAt:data.receivedAt,attempts:0,nextAt:0});
        }
      } else if(path==='/sweep') {
        // A failed leader sell keeps its original proportional retry. Only age
        // can create a full-lot fallback; exitPending is an entry risk gate.
        for(const [k,p] of Object.entries(s.positions))if(Date.now()-p.openedAt>=this.policy.maxHoldMs){
          const id=`expiry:${k}:${p.openedAt}`;
          if(!await db.get(`pending:${id}`))await db.put(`pending:${id}`,{id,expiry:true,wallet:p.wallet,mint:p.mint,openedAt:p.openedAt,receivedAt:Date.now(),attempts:0,nextAt:0});
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
      if(!this.isConfigured())return;
      const pending=await db.list({prefix:'pending:',limit:1000});
      const ready=[...pending.values()].filter(x=>x.nextAt<=Date.now()).sort((a,b)=>Number(Boolean(a.mark))-Number(Boolean(b.mark))||(a.receivedAt||0)-(b.receivedAt||0));
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
      if(!job.mark){await t.put(`done:${job.id}`,{at:now,status:result.status});await t.put(`event:${String(now).padStart(13,'0')}:${job.id}`,{at:now,...result});}
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
          job.values[key]={net:String(checkQuote(q,spec,at,Date.now(),this.policy)-this.policy.fee),at:q.receivedAt};
        }catch{job.values[key]={net:null,at:Date.now(),error:'no usable liquidation quote'};}
        job.index=index+1;await db.put('pending:mark',job);return;
      }
      const complete=Object.keys(job.values).length===positions.length&&positions.every(([k])=>job.values[k]?.net!==null);
      const nav=complete?String(integer(state.cash)+Object.values(job.values).reduce((v,x)=>v+BigInt(x.net),0n)):null;
      await db.put('marks',{at:Date.now(),cash:state.cash,positions:job.values,nav,complete,nonSimultaneous:true});
      const at=Date.now(),bucket=Math.floor(at/300000)*300000;
      await db.put('nav:'+bucket,{at,nav,cash:state.cash,realized:state.realized,fills:state.fills,complete});
      const old=await db.list({prefix:'nav:',end:'nav:'+String(at-7*86400000),limit:100});if(old.size)await db.delete([...old.keys()]);
      await this.finish(job,{status:'MARK',nav,complete});return;
    }
    // Recheck every expiry attempt, including jobs with a cached signal from
    // older deployments. The ID retains the lot timestamp for legacy jobs.
    if(job.expiry){
      const p=state.positions[`${job.wallet}:${job.mint}`];
      if(!p){await this.finish(job,{status:'SKIP',reason:'position already closed'});return;}
      if(job.id!==`expiry:${job.wallet}:${job.mint}:${p.openedAt}`||
        (job.openedAt!==undefined&&job.openedAt!==p.openedAt)){
        await this.finish(job,{status:'SKIP',reason:'expiry belongs to an earlier position'});return;
      }
      if(!Number.isSafeInteger(p.openedAt)||Date.now()-p.openedAt<this.policy.maxHoldMs){
        await this.finish(job,{status:'SKIP',reason:'position not due for expiry'});return;
      }
      // A valid expiry closes the current remainder of this same lot. Do not
      // reuse a cached quantity after a proportional leader sell has completed.
      job.signal={id:job.id,wallet:job.wallet,mint:job.mint,side:'SELL',qty:p.qty,leaderPre:p.qty,
        chainAt:state.startedAt,receivedAt:job.receivedAt,expiry:true};
      await db.put(`pending:${job.id}`,job);
    }
    let s=job.signal;
    if(!s){
      let verified=await db.get(`verified-v2:${job.signature}`);
      if(!verified){
        if(env.QUOTE_GATE){const r=await env.QUOTE_GATE.get(env.QUOTE_GATE.idFromName('source-v2:'+job.signature)).fetch('https://internal/source',{method:'POST',body:JSON.stringify({signature:job.signature})});if(!r.ok)throw Error('source unavailable');verified=await r.json();}
        else verified=await verifySource(env,job.signature);
        await db.put(`verified-v2:${job.signature}`,verified);
      }
      if(verified.type!=='SWAP'){await this.finish(job,{status:'SKIP',reason:'not a supported swap'});return;}
      const tx=verified.tx;
      if(this.experimental&&tx.transaction.message.accountKeys[0]?.pubkey!==job.wallet){await this.finish(job,{status:'SKIP',reason:'wallet not fee payer'});return;}
      try{s=normalize(tx,job.wallet,job.signature,job.receivedAt);}catch(e){await this.finish(job,{status:'SKIP',reason:e.message});return;}
      await db.put(`source:${job.id}`,tx);
      job.signal=s;await db.put(`pending:${job.id}`,job);
    }
    let p;
    try{
      if(s.side==='BUY'&&(await db.get('health'))?.entryBlocked)throw Error('health gate; manual review required');
      if(s.side==='BUY'&&[...(await db.list({prefix:'pending:',limit:1000})).values()].some(j=>j.id!==job.id&&j.attempts>0&&!j.mark))throw Error('unresolved prior event');
      const last=await db.get(`last:${keyOf(s)}`);
      if(!s.expiry&&last&&s.slot<last.slot)throw Error('out-of-order leader event');
      p=plan(state,s,Date.now(),this.policy);
    }catch(e){await this.finish(job,{status:'SKIP',reason:e.message,signal:s});return;}
    if(s.side==='BUY'){
      const mint=await rpc(env,'getAccountInfo',[s.mint,{encoding:'jsonParsed',commitment:'confirmed'}]);
      const info=mint.value?.data?.parsed?.info;
      if(!supportedMint(mint.value,s.decimals)){
        await this.finish(job,{status:'SKIP',reason:'mint authority/freeze/extension/decimals gate',mintChecks:{owner:mint.value?.owner||null,classic:mint.value?.owner===SPL,parsed:Boolean(info),mintAuthorityRevoked:info?.mintAuthority===null,freezeAuthorityRevoked:info?.freezeAuthority===null,decimalsMatch:info?.decimals===s.decimals},signal:s});return;
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
          checkQuote(fx,fp,decisionAt,Date.now(),this.policy);leaderUsdc=integer(fx.outAmount);
          await db.put(`fx:${job.id}:${job.attempts}`,fx);
        }
      }
      // A reverse route is required before buying. This is not a guarantee of future liquidity.
      if(s.side==='BUY'){
        const preview=await quote(env,p),previewOut=checkQuote(preview,p,decisionAt,Date.now(),this.policy);
        const reverse={inputMint:s.mint,outputMint:USDC,amount:String(previewOut)},rq=await quote(env,reverse);
        const net=checkQuote(rq,reverse,decisionAt,Date.now(),this.policy);
        if(net*100n<this.policy.ticket*90n)throw Error('roundtrip loss gate');
        await db.put(`reverse:${job.id}`,rq);
      }
      // Use a NEW quote after all gates; never choose an older fill using newer information.
      q=await quote(env,p);
      const result=fill(state,s,p,q,decisionAt,Date.now(),leaderUsdc,this.policy);
      if(!s.expiry)await db.put(`last:${keyOf(s)}`,{slot:s.slot});
      await this.finish(job,{status:'FILLED',signal:s,plan:p,quote:q,receipt:result.receipt},result.state);
    }catch(e){
      if(s.side==='BUY'){await this.finish(job,{status:'SKIP',reason:e.message.startsWith('upstream')?'quote unavailable':e.message,signal:s});return;}
      const pos=state.positions[keyOf(s)];if(pos){pos.exitPending=true;await db.put('state',state);}throw e;
    }
  }
}

export class DynamicRegistry {
  constructor(ctx,env){this.ctx=ctx;this.env=env;}
  async fetch(request){
    return this.ctx.blockConcurrencyWhile(async()=>{
      const db=this.ctx.storage,u=new URL(request.url),path=u.pathname;
      if(path==='/list'){const rows=[...(await db.list({prefix:'acct:'})).values()].sort((a,b)=>a.createdAt-b.createdAt);return json({accounts:rows});}
      if(path==='/get'){const id=u.searchParams.get('id'),a=await db.get('acct:'+id);return a?json({account:a}):json({error:'dynamic account not found'},404);}
      let data;try{data=await request.json();}catch{return json({error:'invalid JSON'},400);}
      if(path==='/create'){
        if(!/^dyn-[a-f0-9]{12}$/.test(data.id)||!address(data.wallet)||!Number.isSafeInteger(data.chaseBps)||data.chaseBps<0||data.chaseBps>5000||data.status!=='paused')return json({error:'invalid dynamic account'},400);
        const byWallet=await db.get('wallet:'+data.wallet),byId=await db.get('acct:'+data.id);
        if(byWallet||byId)return json({error:'dynamic account already exists',existingId:byWallet||data.id},409);
        const account={id:data.id,wallet:data.wallet,label:String(data.label||'').slice(0,64),chaseBps:data.chaseBps,status:'paused',createdAt:data.createdAt,startedAt:data.startedAt};
        await db.transaction(async t=>{await t.put('acct:'+account.id,account);await t.put('wallet:'+account.wallet,account.id);});
        return json({account},201);
      }
      if(path==='/update'){
        if(!/^dyn-[a-f0-9]{12}$/.test(data.id)||!['active','paused','archived'].includes(data.status))return json({error:'invalid update'},400);
        const old=await db.get('acct:'+data.id);if(!old)return json({error:'dynamic account not found'},404);
        const account={...old,status:data.status,updatedAt:Date.now()};await db.put('acct:'+data.id,account);return json({account});
      }
      return json({error:'not found'},404);
    });
  }
}
export class DynamicPaperBook extends PaperBook {
  async loadConfig(){
    const c=await this.ctx.storage.get('config');
    if(c){this.walletOverride=[c.wallet];this.enabledOverride=c.status==='active';this.policy={...POLICY,chaseBps:BigInt(c.chaseBps)};}
    return c;
  }
  async fetch(request){
    const path=new URL(request.url).pathname;
    if(path==='/configure'&&request.method==='POST')return this.ctx.blockConcurrencyWhile(async()=>{
      let c;try{c=await request.json();}catch{return json({error:'invalid JSON'},400);}
      if(!/^dyn-[a-f0-9]{12}$/.test(c.id)||!address(c.wallet)||!['active','paused','archived'].includes(c.status)||!Number.isSafeInteger(c.chaseBps)||c.chaseBps<0||c.chaseBps>5000)return json({error:'invalid config'},400);
      const old=await this.ctx.storage.get('config');if(old&&old.wallet!==c.wallet)return json({error:'wallet is immutable'},409);
      await this.ctx.storage.put('config',c);if(!await this.ctx.storage.get('state'))await this.ctx.storage.put('state',initial(c.startedAt));
      await this.loadConfig();return json({configured:true,id:c.id,status:c.status,startedAt:c.startedAt});
    });
    await this.loadConfig();return super.fetch(request);
  }
  async alarm(){await this.loadConfig();return super.alarm();}
}

// Independent experimental books. No state copy, replay fills, or shared cash.
class ExperimentalBook extends PaperBook {
 constructor(ctx,env,wallet,chaseBps){super(ctx,{...env,WALLETS:JSON.stringify([wallet]),ENABLED:env.LABS_ENABLED});this.experimental=true;this.policy={...POLICY,chaseBps};}
}
export class ScharoStandard extends ExperimentalBook{constructor(c,e){super(c,e,SCHARO,1500n);}}
export class ScharoTight extends ExperimentalBook{constructor(c,e){super(c,e,SCHARO,500n);}}
export class MattStandard extends ExperimentalBook{constructor(c,e){super(c,e,MATT,1500n);}}
export class MattTight extends ExperimentalBook{constructor(c,e){super(c,e,MATT,500n);}}
export function webhookSignatures(events,allowed){
 return [...new Set(events.filter(e=>!e.feePayer||allowed.includes(e.feePayer)).map(e=>e.signature))];
}
const DEX_PROGRAMS=new Set(['6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P','pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA','JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4','whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc','675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8','CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK']);
export function hasSwapInstruction(tx){
 if(!tx||tx.meta?.err)return false;
 const stack=[];let found=false;
 for(const line of tx.meta.logMessages||[]){
  const invoke=line.match(/^Program ([1-9A-HJ-NP-Za-km-z]+) invoke \[(\d+)\]$/);
  if(invoke){stack.length=Number(invoke[2])-1;stack.push(invoke[1]);continue;}
  if(/^Program [1-9A-HJ-NP-Za-km-z]+ (success|failed:)/.test(line)){stack.pop();continue;}
  if(DEX_PROGRAMS.has(stack.at(-1))&&/^Program log: Instruction: (Buy|Sell|Swap|Route|SharedAccountsRoute)[A-Za-z0-9_]*$/.test(line))found=true;
 }
 return found;
}
export async function verifySource(env,signature){
 const tx=await rpc(env,'getTransaction',[signature,{encoding:'jsonParsed',commitment:'confirmed',maxSupportedTransactionVersion:1}]);
 if(!tx.transaction?.signatures?.includes(signature))throw Error('transaction not available');
 return {type:hasSwapInstruction(tx)?'SWAP':'NON_SWAP',tx,observedAt:Date.now(),parserVersion:2};
}
export class QuoteGate {
 constructor(ctx,env){this.ctx=ctx;this.env=env;}
 async fetch(request){return this.ctx.blockConcurrencyWhile(async()=>{try{
  const p=await request.json();
  if(new URL(request.url).pathname==='/source'){
   const k='tx:'+p.signature,old=await this.ctx.storage.get(k);if(old)return json(old);
   const v=await verifySource(this.env,p.signature);await this.ctx.storage.put(k,v);return json(v);
  }
  const q=await quote({...this.env,QUOTE_GATE:null},p);return json(q);
 }catch{return json({error:'provider unavailable'},502);}});}
}

export class ThreeGjStandard extends ExperimentalBook{constructor(c,e){super(c,e,THREE_GJ,1500n);}}
