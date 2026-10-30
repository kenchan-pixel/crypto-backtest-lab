import test from 'node:test';
import assert from 'node:assert/strict';
import {DynamicRegistry,DynamicPaperBook} from './worker.mjs';

const WALLET='Nsgx8SAf9jSmwqewSttpXbEKAHSPZPae2gFLfj6Yu44';
class Store{
  constructor(){this.rows=new Map();}
  async get(k){return structuredClone(this.rows.get(k));}
  async put(k,v){this.rows.set(k,structuredClone(v));}
  async delete(k){this.rows.delete(k);}
  async list({prefix='',limit=1000}={}){return new Map([...this.rows].filter(([k])=>k.startsWith(prefix)).slice(0,limit).map(([k,v])=>[k,structuredClone(v)]));}
  async transaction(fn){return fn(this);}
  async setAlarm(at){this.alarm=at;}
}
const ctx=()=>({storage:new Store(),blockConcurrencyWhile:fn=>fn()});

test('dynamic registry rejects duplicate wallet and preserves stable account',async()=>{
  const c=ctx(),r=new DynamicRegistry(c,{});
  const account={id:'dyn-0123456789ab',wallet:WALLET,label:'candidate',chaseBps:1500,status:'paused',createdAt:1000,startedAt:1000};
  let res=await r.fetch(new Request('https://internal/create',{method:'POST',body:JSON.stringify(account)}));
  assert.equal(res.status,201);
  res=await r.fetch(new Request('https://internal/create',{method:'POST',body:JSON.stringify({...account,id:'dyn-abcdef123456'})}));
  assert.equal(res.status,409);
  const listed=await (await r.fetch(new Request('https://internal/list'))).json();
  assert.equal(listed.accounts.length,1);assert.equal(listed.accounts[0].id,account.id);
});

test('dynamic book starts exactly at promotion time and pause retains state',async()=>{
  const c=ctx(), env={HELIUS_API_KEY:'fixture',JUPITER_API_KEY:'fixture',ENABLED:'true',WALLETS:'[]'};
  const b=new DynamicPaperBook(c,env);
  const cfg={id:'dyn-0123456789ab',wallet:WALLET,label:'candidate',chaseBps:500,status:'active',createdAt:1000,startedAt:1234567890};
  let res=await b.fetch(new Request('https://internal/configure',{method:'POST',body:JSON.stringify(cfg)}));assert.equal(res.status,200);
  let status=await (await b.fetch(new Request('https://internal/status'))).json();
  assert.equal(status.configured,true);assert.equal(status.state.startedAt,cfg.startedAt);assert.equal(status.state.fills,0);
  res=await b.fetch(new Request('https://internal/configure',{method:'POST',body:JSON.stringify({...cfg,status:'paused'})}));assert.equal(res.status,200);
  status=await (await b.fetch(new Request('https://internal/status'))).json();
  assert.equal(status.configured,false);assert.equal(status.state.startedAt,cfg.startedAt);assert.equal(status.state.fills,0);
});
