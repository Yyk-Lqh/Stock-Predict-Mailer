/* Loopback market relay client. Display only: no quote here reaches a task, a
   prediction or a model, and nothing is invented when the relay stays silent. */
globalThis.PonyMarketFeed=(()=>{
  const subscribers=new Set();let latest=null,timer=null,busy=false,failures=0,interval=10000,state='idle',enabled=true;
  const emit=(kind,value)=>{for(const handler of [...subscribers]){const fn=handler[kind];if(typeof fn!=='function')continue;try{fn(value);}catch{}};};
  const schedule=()=>{if(!enabled||document.hidden)return;clearTimeout(timer);timer=setTimeout(pull,interval);};
  async function pull(){
    if(busy||!enabled)return;
    busy=true;const control=new AbortController(),expiry=setTimeout(()=>control.abort(),8000);
    try{
      const response=await fetch('/api/market/snapshot',{signal:control.signal,cache:'no-store',credentials:'same-origin',headers:{Accept:'application/json'}});
      if(response.status===404||response.status===403){enabled=false;clearTimeout(timer);return;}
      if(!response.ok)throw new Error(String(response.status));
      const body=await response.json();
      if(Number.isFinite(body.refresh_seconds))interval=Math.min(60000,Math.max(5000,body.refresh_seconds*1000));
      failures=0;
      if(body.status==='unavailable'||!body.snapshot){state='unavailable';emit('down');return;}
      latest=body.snapshot;
      if(body.status==='stale'){state='stale';emit('stale',typeof body.detail==='string'?body.detail:'');return;}
      state=body.status==='live'?'live':'delayed';emit('snapshot',latest);
    }catch{
      failures+=1;if(failures>=2){state='down';emit('down');}
    }finally{clearTimeout(expiry);busy=false;if(enabled)schedule();}
  }
  function attach(handler){
    subscribers.add(handler);
    if(latest&&(state==='live'||state==='delayed')){try{handler.snapshot?.(latest);}catch{}}
    else if(state==='stale'||state==='down'){try{handler.stale?.();}catch{}}
    return()=>subscribers.delete(handler);
  }
  window.addEventListener('offline',()=>{state='down';emit('down');});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else pull();});
  pull();
  return{attach,pull,current:()=>({snapshot:latest,status:state,interval})};
})();
