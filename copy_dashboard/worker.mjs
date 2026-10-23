import {HTML} from './view.mjs';
const ENGINE='https://ken-copy-paper.kenchan-528.workers.dev';
const COOKIE='__Host-paper_view';
const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"};
const reply=(v,status=200,extra={})=>Response.json(v,{status,headers:{...headers,...extra}});
const hex=b=>Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,'0')).join('');
async function equal(a,b){const hash=s=>crypto.subtle.digest('SHA-256',new TextEncoder().encode(s));const x=new Uint8Array(await hash(a)),y=new Uint8Array(await hash(b));let n=0;for(let i=0;i<x.length;i++)n|=x[i]^y[i];return n===0;}
async function mac(value,secret){const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);return hex(await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(value)));}
async function signedIn(request,env){
 const raw=(request.headers.get('Cookie')||'').split(';').map(x=>x.trim()).find(x=>x.startsWith(COOKIE+'='))?.slice(COOKIE.length+1)||'';
 const [expiry,sig]=raw.split('.');if(!/^\d{13}$/.test(expiry||'')||!sig||Number(expiry)<=Date.now()||Number(expiry)>Date.now()+7*86400000)return false;
 return equal(sig,await mac(expiry,env.SESSION_SECRET));
}
const atoms=x=>typeof x==='string'&&/^-?\d+$/.test(x)?x:null;
const finite=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
async function readEngine(env){
 const get=async route=>{const r=await fetch(ENGINE+route,{headers:{Authorization:`Bearer ${env.ENGINE_ADMIN_TOKEN}`},signal:AbortSignal.timeout(15000)});if(!r.ok)throw Error('upstream');return r.json();};
 const s=await get('/status');let rows=[],auditAvailable=true;try{rows=(await get('/audit')).rows||[];}catch{auditAvailable=false;}
 return {...project(s,rows),auditAvailable};
}
export class ViewHistory {
 constructor(ctx,env){this.ctx=ctx;this.env=env;}
 async fetch(request){
  const db=this.ctx.storage;
  if(new URL(request.url).pathname==='/collect')return this.ctx.blockConcurrencyWhile(async()=>{
   try{const latest=await readEngine(this.env);const bucket=Math.floor(latest.markedAt/300000)*300000;
    await db.put('latest',latest);
    if(latest.nav!==null&&latest.markedAt&&Date.now()-latest.markedAt<180000)await db.put('point:'+bucket,{at:latest.markedAt,nav:latest.nav});
    const old=await db.list({prefix:'point:',end:'point:'+String(Date.now()-7*86400000),limit:100});
    if(old.size)await db.delete([...old.keys()]);return reply({ok:true});
   }catch{return reply({error:'collection unavailable'},502);}
  });
  const latest=await db.get('latest');if(!latest)return reply({error:'等待首筆觀測'},503);
  const history=await db.list({prefix:'point:',reverse:true,limit:2016});
  return reply({...latest,history:[...history.values()].reverse(),historyScope:'server-observed 5-minute samples, last 7 days; no historical backfill'});
 }
}
export function project(s,rows=[],now=Date.now()){
 if(!s?.state||!atoms(s.state.cash)||!Number.isSafeInteger(s.state.fills))throw Error('invalid upstream');
 const st=s.state,m=s.marks,ps=Object.entries(st.positions||{});
 const coherent=m?.cash===st.cash&&Object.keys(m.positions||{}).length===ps.length&&ps.every(([k])=>Object.hasOwn(m.positions||{},k))&&m.at>=st.lastAt;
 const positions=ps.map(([k,p])=>({mint:p.mint,wallet:p.wallet,qty:atoms(p.qty),decimals:p.decimals,cost:atoms(p.cost),openedAt:finite(p.openedAt),exitPending:!!p.exitPending,net:coherent?atoms(m.positions[k]?.net):null,markedAt:coherent?finite(m.positions[k]?.at):null}));
 const nav=coherent&&m.complete&&positions.every(p=>p.net!==null)?atoms(m.nav):null;
 const events=[...rows,...(s.recent||[])].filter(x=>x.status!=='MARK').map(x=>({at:finite(x.at)||Number(x.id?.split(':')[1])||null,status:x.status,side:x.receipt?.side||x.signal?.side||null,mint:x.signal?.mint||null,signature:x.signal?.signature||null,reason:typeof x.reason==='string'?x.reason.slice(0,160):null,input:atoms(x.receipt?.input),output:atoms(x.receipt?.output),fee:atoms(x.receipt?.fee),realized:atoms(x.receipt?.realized),latencyMs:finite(x.receipt?.latencyMs),simulation:x.receipt?.simulation===true}));
 const unique=new Map();for(const e of events)unique.set([e.at,e.signature,e.status,e.side].join(':'),e);
 return {schema:1,paperOnly:true,observedAt:now,startedAt:finite(st.startedAt),initial:'10000000000',cash:st.cash,nav,markedAt:finite(m?.at),marksCoherent:!!coherent,nonSimultaneous:true,realized:atoms(st.realized),fees:atoms(st.fees),fills:st.fills,positions,queue:finite(s.queued),health:s.health?{at:finite(s.health.at),entryBlocked:!!s.health.entryBlocked,error:typeof s.health.error==='string'?s.health.error.slice(0,180):'診斷異常'}:null,events:[...unique.values()].sort((a,b)=>(b.at||0)-(a.at||0)).slice(0,200),historyScope:'recent bounded audit; not full ledger'};
}
export default {
 async scheduled(_event,env,ctx){if(env.HISTORY&&env.ENGINE_ADMIN_TOKEN)ctx.waitUntil(env.HISTORY.get(env.HISTORY.idFromName('paper-view-v1')).fetch('https://internal/collect',{method:'POST'}));},
 async fetch(request,env){
  const u=new URL(request.url),path=u.pathname;
  if(path==='/'&&request.method==='GET')return new Response(HTML,{headers:{...headers,'Content-Type':'text/html; charset=utf-8'}});
  if(!env.SESSION_SECRET||env.SESSION_SECRET.length<32||!env.VIEWER_PASSWORD||env.VIEWER_PASSWORD.length<16||!env.ENGINE_ADMIN_TOKEN)return reply({error:'看板尚未完成設定'},503);
  if(path==='/login'&&request.method==='POST'){
   if(request.headers.get('Origin')!==u.origin)return reply({error:'invalid origin'},403);
   if(!request.headers.get('Content-Type')?.startsWith('application/json'))return reply({error:'invalid content'},415);
   const reader=request.body?.getReader();let bytes=0,parts=[];if(!reader)return reply({error:'missing body'},400);
   while(true){const r=await reader.read();if(r.done)break;bytes+=r.value.length;if(bytes>1024){await reader.cancel();return reply({error:'too large'},413);}parts.push(r.value);}
   let password;try{const b=new Uint8Array(bytes);let at=0;for(const p of parts){b.set(p,at);at+=p.length;}password=JSON.parse(new TextDecoder().decode(b)).password;}catch{return reply({error:'invalid body'},400);}
   if(typeof password!=='string'||!await equal(password,env.VIEWER_PASSWORD))return reply({error:'登入資料不符'},401);
   const expiry=String(Date.now()+7*86400000),token=expiry+'.'+await mac(expiry,env.SESSION_SECRET);
   return reply({ok:true},200,{'Set-Cookie':`${COOKIE}=${token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=604800`});
  }
  if(!['/api','/logout'].includes(path))return reply({error:'not found'},404);
  if(!await signedIn(request,env))return reply({error:'請先登入只讀看板'},401);
  if(path==='/logout'&&request.method==='POST'){
   if(request.headers.get('Origin')!==u.origin)return reply({error:'invalid origin'},403);
   return reply({ok:true},200,{'Set-Cookie':`${COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0`});
  }
  if(path!=='/api'||request.method!=='GET')return reply({error:'method not allowed'},405);
  try{
   if(env.HISTORY)return env.HISTORY.get(env.HISTORY.idFromName('paper-view-v1')).fetch('https://internal/view');
   return reply(await readEngine(env));
  }catch{return reply({error:'暫時讀取唔到引擎，保留上次資料'},502);}
 }
};
