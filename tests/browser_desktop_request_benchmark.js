/* Fixed request burst benchmark. Disposable console :8768 only; no external calls. */
(async()=>{
  if(location.port!=='8768'||innerWidth<=760)throw Error('Use desktop disposable fixture');
  const realFetch=window.fetch,savedTask=currentTask,savedCursor=eventCursor,savedKey=memoryKey,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const result={viewport:[innerWidth,innerHeight]},id='desktop-request-benchmark';
  const response=value=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
  try{
    const nav=performance.getEntriesByType('navigation')[0];result.startup={load_ms:nav.loadEventEnd,interactive_ms:nav.domInteractive,paint:performance.getEntriesByType('paint').map(item=>({name:item.name,ms:item.startTime})),assets:performance.getEntriesByType('resource').filter(item=>['script','link'].includes(item.initiatorType)).map(item=>({path:new URL(item.name).pathname,bytes:item.encodedBodySize}))};
    let active=0,maximum=0,tasks=0,events=0;
    window.fetch=async(url,options)=>{const path=String(url);if(path.startsWith('/api/tasks/'+id)){active++;maximum=Math.max(maximum,active);try{await sleep(60);if(path.includes('/events?')){events++;return response({events:[]});}tasks++;return response({id,status:{state:'working'},metadata:{request:{subject:'BENCH'}}});}finally{active--;}}return realFetch(url,options);};
    currentTask=id;eventCursor=0;showView('analysis');
    await Promise.all(Array.from({length:5},()=>poll(id)));const burst={task_requests:tasks,event_requests:events,max_in_flight:maximum};await sleep(1000);
    result.polling={burst_calls:5,burst,after_1000ms:{task_requests:tasks,event_requests:events,max_in_flight:maximum}};
    currentTask=null;window.DesktopPoll?.stop();window.fetch=realFetch;await sleep(180);
    const access=await api('memory/access','POST',{});await useMemoryKey(access.key);await sleep(220);
    let sessionRequests=0,sessionActive=0,sessionMaximum=0;
    window.fetch=async(url,options)=>{if(String(url).startsWith('/api/conversations?limit=30')){sessionRequests++;sessionActive++;sessionMaximum=Math.max(sessionMaximum,sessionActive);try{await sleep(80);return response({items:Array.from({length:5},(_,index)=>({id:'benchmark-session-'+index,subject:'合成会话 '+index,updated:'2026-11-17T08:00:00+00:00'})),next_before:7});}finally{sessionActive--;}}return realFetch(url,options);};
    await Promise.all(Array.from({length:5},()=>Workbench.sessions()));result.sessions={burst_calls:5,requests:sessionRequests,max_in_flight:sessionMaximum};
    document.body.dataset.desktopRequestBenchmark=JSON.stringify(result);
  }catch(error){document.body.dataset.desktopRequestBenchmark=JSON.stringify({...result,error:error.stack});}
  finally{currentTask=memoryKey===savedKey?savedTask:null;eventCursor=memoryKey===savedKey?savedCursor:0;window.DesktopPoll?.stop();window.fetch=realFetch;window.DesktopSessions?.identityChanged();PonyOffice.reset();await Workbench.sessions();}
})();
