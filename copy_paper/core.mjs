// Pure paper accounting. No signing, transaction submission or exchange SDK.
export const USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
export const SOL = 'So11111111111111111111111111111111111111112';
export const SPL = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA';
export const POLICY = Object.freeze({version:'copy-paper-v1', initial:10000000000n,
  ticket:200000000n, walletCap:1000000000n, totalCap:3000000000n,
  fee:1000000n, maxLagMs:60000, maxQuoteMs:10000, chaseBps:1500n,
  slippageBps:100n, maxHoldMs:86400000});
export const integer = x => { if(!/^[0-9]+$/.test(String(x))) throw Error('invalid integer'); return BigInt(x); };
const signed = x => { if(!/^-?[0-9]+$/.test(String(x))) throw Error('invalid signed integer'); return BigInt(x); };
export const initial = now => ({version:POLICY.version, startedAt:now, cash:String(POLICY.initial),
  positions:{}, realized:'0', fees:'0', fills:0, lastAt:now});
export const keyOf = s => `${s.wallet}:${s.mint}`;
export function normalize(tx,wallet,signature,receivedAt) {
  if(!tx || tx.meta?.err || !tx.transaction?.signatures?.includes(signature)) throw Error('invalid transaction');
  const keys=tx.transaction.message.accountKeys.map(k=>typeof k==='string'?k:k.pubkey);
  const wi=keys.indexOf(wallet);
  if(wi<0 || !tx.transaction.message.accountKeys[wi]?.signer) throw Error('wallet not signer');
  const chainAt=tx.blockTime*1000;
  if(!Number.isSafeInteger(chainAt) || chainAt<=0 || chainAt>receivedAt+5000) throw Error('invalid block time');
  const pre=tx.meta.preTokenBalances||[], post=tx.meta.postTokenBalances||[];
  const amounts=new Map(), owned=new Set();
  for(const [rows,side] of [[pre,-1n],[post,1n]]) for(const b of rows) {
    if(b.owner!==wallet) continue;
    owned.add(b.accountIndex);
    if(b.mint===SOL) continue; // Its account lamports are included in native SOL below.
    const a=amounts.get(b.mint)||{pre:0n,delta:0n,decimals:b.uiTokenAmount.decimals};
    if(a.decimals!==b.uiTokenAmount.decimals) throw Error('decimals mismatch');
    const n=integer(b.uiTokenAmount.amount); a.delta+=side*n;
    if(side<0n) a.pre+=n; amounts.set(b.mint,a);
  }
  const safeLamports=n=>{if(!Number.isSafeInteger(n)||n<0)throw Error('unsafe lamports');return BigInt(n);};
  // Include owned token-account rent so opening/closing ATAs does not look like spending SOL.
  let native=safeLamports(tx.meta.postBalances[wi])-safeLamports(tx.meta.preBalances[wi]);
  if(wi===0) native+=safeLamports(tx.meta.fee);
  for(const i of owned) native+=safeLamports(tx.meta.postBalances[i])-safeLamports(tx.meta.preBalances[i]);
  if(native!==0n) amounts.set(SOL,{pre:0n,delta:native,decimals:9});
  const changed=[...amounts].filter(([,a])=>a.delta!==0n);
  if(changed.length!==2) throw Error('ambiguous multi-asset transaction');
  const base=changed.find(([mint])=>mint===USDC||mint===SOL);
  const token=changed.find(([mint])=>mint!==USDC&&mint!==SOL);
  if(!base||!token||base[1].delta*token[1].delta>=0n) throw Error('unsupported swap legs');
  const [mint,a]=token;
  if(a.decimals<0||a.decimals>18)throw Error('unsupported decimals');
  const side=a.delta>0n?'BUY':'SELL';
  const qty=a.delta>0n?a.delta:-a.delta;
  if(side==='SELL'&&(a.pre===0n||qty>a.pre))throw Error('invalid leader sell fraction');
  return {id:`${signature}:${wallet}`,signature,wallet,mint,side,decimals:a.decimals,
    qty:String(qty),leaderPre:String(a.pre),baseMint:base[0],baseQty:String(base[1].delta<0n?-base[1].delta:base[1].delta),
    chainAt,receivedAt,slot:tx.slot};
}
export function plan(state,s,now,policy=POLICY) {
  if(now<state.startedAt || s.chainAt<state.startedAt) throw Error('pre-start event');
  const p=state.positions[keyOf(s)];
  if(s.side==='SELL') {
    if(!p)throw Error('no copied position');
    const amount=integer(p.qty)*integer(s.qty)/integer(s.leaderPre);
    if(amount<=0n)throw Error('dust sell');
    return {side:'SELL',amount:String(amount),inputMint:s.mint,outputMint:USDC};
  }
  if(now-s.chainAt>policy.maxLagMs)throw Error('late entry');
  if(Object.values(state.positions).some(p=>p.exitPending))throw Error('unresolved exit');
  const total=Object.values(state.positions).reduce((n,p)=>n+integer(p.cost),0n);
  const wallet=Object.values(state.positions).filter(p=>p.wallet===s.wallet).reduce((n,p)=>n+integer(p.cost),0n);
  if(integer(state.cash)<policy.ticket+policy.fee||total+policy.ticket+policy.fee>policy.totalCap||wallet+policy.ticket+policy.fee>policy.walletCap)throw Error('capital cap');
  if(p)throw Error('no averaging into copied position');
  return {side:'BUY',amount:String(policy.ticket),inputMint:USDC,outputMint:s.mint};
}
export function checkQuote(q,p,decisionAt,now,policy=POLICY) {
  if(!q||q.inputMint!==p.inputMint||q.outputMint!==p.outputMint||q.swapMode!=='ExactIn'||integer(q.inAmount)!==integer(p.amount))throw Error('quote mismatch');
  if(q.requestedAt<decisionAt||q.receivedAt<q.requestedAt||now<q.receivedAt||now-q.requestedAt>policy.maxQuoteMs)throw Error('stale quote');
  if(!q.routePlan?.length||q.error||q.errorCode||integer(q.outAmount)<=0n)throw Error('no route');
  // No taker is supplied: this endpoint must return a quote only, never a signable transaction.
  if(q.transaction)throw Error('unexpected transaction');
  return integer(q.outAmount)*(10000n-policy.slippageBps)/10000n;
}
export function fill(state,s,p,q,decisionAt,now,leaderUsdc,policy=POLICY) {
  const st=structuredClone(state), out=checkQuote(q,p,decisionAt,now,policy), k=keyOf(s);
  // Revalidate balances/caps at commit, not only before network calls.
  const current=plan(st,s,now,policy);
  if(current.amount!==p.amount||current.side!==p.side)throw Error('state changed');
  let pnl=0n;
  if(p.side==='BUY') {
    const reference=integer(leaderUsdc);
    if(reference===0n||policy.ticket*integer(s.qty)*10000n>reference*out*(10000n+policy.chaseBps))throw Error('chase limit');
    st.cash=String(integer(st.cash)-policy.ticket-policy.fee);
    st.positions[k]={wallet:s.wallet,mint:s.mint,qty:String(out),cost:String(policy.ticket+policy.fee),openedAt:now,decimals:s.decimals,exitPending:false};
  } else {
    const pos=st.positions[k], qty=integer(pos.qty), sold=integer(p.amount);
    if(sold>qty||out<policy.fee)throw Error('invalid sell proceeds');
    const cost=integer(pos.cost)*sold/qty;
    pnl=out-policy.fee-cost;
    st.cash=String(integer(st.cash)+out-policy.fee);
    st.realized=String(signed(st.realized)+pnl);
    if(sold===qty)delete st.positions[k];
    else {pos.qty=String(qty-sold);pos.cost=String(integer(pos.cost)-cost);pos.exitPending=false;}
  }
  st.fees=String(integer(st.fees)+policy.fee);st.fills++;st.lastAt=now;
  return {state:st,receipt:{eventId:s.id,side:p.side,at:now,input:p.amount,output:String(out),
    fee:String(policy.fee),realized:String(pnl),latencyMs:now-s.chainAt,quoteRequestedAt:q.requestedAt,
    quoteReceivedAt:q.receivedAt,leaderUsdc:String(leaderUsdc??0),simulation:true}};
}
