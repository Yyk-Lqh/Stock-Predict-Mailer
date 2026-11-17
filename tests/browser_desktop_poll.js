/* Polling boundaries on disposable :8768. Real Mock workflows are verified separately. */
(async()=>{
  const $=id=>document.getElementById(id),checks=[],realFetch=window.fetch,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const originalHidden=Object.getOwnPropertyDescriptor(document,'hidden');const releases=[];
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<130;i++){if(fn())return;await sleep(100);}throw Error('Timeout: '+label);};
  const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
  const task=(id,state='working')=>({id,status:{state,timestamp:'2026-11-17T08:00:00+00:00'},metadata:{request:{subject:'POLL-TEST'}}});
  const start=id=>{DesktopPoll.stop();currentTask=id;eventCursor=0;runvizReset();showTask(task(id));showView('analysis');};
  const hidden=value=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>value});document.dispatchEvent(new Event('visibilitychange'));};
  try{
    assert(location.port==='8768'&&innerWidth>760&&window.DesktopPoll,'Use desktop fixture');
    let calls=0,events=0,active=0,maximum=0;
    window.fetch=async(url,options)=>{if(String(url).startsWith('/api/tasks/poll-coalesce')){active++;maximum=Math.max(maximum,active);try{await sleep(50);if(String(url).includes('/events?')){events++;return json({events:[]});}calls++;return json(task('poll-coalesce'));}finally{active--;}}return realFetch(url,options);};
    start('poll-coalesce');await Promise.all(Array.from({length:5},()=>poll('poll-coalesce')));assert(calls===1&&events===1&&maximum===1,'Concurrent reads were not coalesced');
    showView('settings');const paused=calls;await sleep(850);assert(calls===paused,'Leaving analysis retained polling timer');showView('analysis');await wait(()=>calls>paused,'return to analysis');
    hidden(true);await sleep(180);const hiddenCalls=calls;await sleep(800);assert(calls===hiddenCalls,'Hidden document kept polling');hidden(false);await wait(()=>calls>hiddenCalls,'visible resume');
    window.dispatchEvent(new PageTransitionEvent('pagehide'));await sleep(150);const parked=calls;await sleep(800);assert(calls===parked,'Pagehide kept polling');window.dispatchEvent(new PageTransitionEvent('pageshow'));await wait(()=>calls>parked,'pageshow resume');assert(maximum===1,'Resume created overlapping reads');
    checks.push('Concurrent task/events reads share one chain; leaving analysis, hidden document and page lifecycle pause/resume without overlap');

    const cursors=[];calls=0;window.fetch=async(url,options)=>{if(String(url).startsWith('/api/tasks/poll-pages')){if(!String(url).includes('/events?')){calls++;return json(task('poll-pages','completed'));}const after=Number(new URL(String(url),location.origin).searchParams.get('after'));cursors.push(after);return json({events:Array.from({length:after?2:100},(_,index)=>({seq:after+index+1,kind:'step',step:'main',status:'completed',label:'分页边界',timestamp:'2026-11-17T08:00:00Z'}))});}return realFetch(url,options);};
    start('poll-pages');await wait(()=>eventCursor===102,'drain second event page');assert(cursors.join(',')==='0,100'&&runviz.events===102,'Events skipped, replayed or used wrong cursor');const terminalCalls=calls;
    await Promise.all(Array.from({length:5},()=>poll('poll-pages')));document.dispatchEvent(new Event('visibilitychange'));await sleep(800);assert(calls===terminalCalls,'Terminal task restarted after events drained');
    checks.push('Terminal task drains 100+2 events exactly once, then repeated refresh/resume stops reading');

    let oldHeld=false,releaseOld;window.fetch=async(url,options)=>{if(String(url)==='/api/tasks/poll-old'){oldHeld=true;await new Promise(resolve=>{releaseOld=resolve;releases.push(resolve);});return json(task('poll-old'));}if(String(url).startsWith('/api/tasks/poll-new'))return json(String(url).includes('/events?')?{events:[]}:task('poll-new','completed'));return realFetch(url,options);};
    start('poll-old');const old=poll('poll-old');await wait(()=>oldHeld,'held old task');start('poll-new');await poll('poll-new');releaseOld();await old;assert(JSON.parse($('task-output').textContent).id==='poll-new','Old task response overwrote current task');
    checks.push('Late previous-task response cannot overwrite the selected task');

    let held=false,releaseCancel,releaseCommand,commands=0,reads=0;window.fetch=async(url,options)=>{const path=String(url);if(path==='/api/tasks/poll-cancel/cancel'){commands++;await new Promise(resolve=>{releaseCommand=resolve;releases.push(resolve);});return json(task('poll-cancel','canceled'));}if(path==='/api/tasks/poll-cancel'){reads++;if(reads===1){held=true;await new Promise(resolve=>{releaseCancel=resolve;releases.push(resolve);});return json(task('poll-cancel'));}return json(task('poll-cancel','canceled'));}if(path.startsWith('/api/tasks/poll-cancel/events?'))return json({events:[]});return realFetch(url,options);};
    start('poll-cancel');const inFlight=poll('poll-cancel');await wait(()=>held,'held pre-cancel read');const command=$('task-cancel').onclick();await wait(()=>commands===1,'cancel command');await $('task-cancel').onclick();assert(commands===1&&$('task-cancel').disabled,'Pending cancellation allowed duplicate command');releaseCommand();await command;releaseCancel();await inFlight;
    assert(JSON.parse($('task-output').textContent).status.state==='canceled'&&$('task-cancel').hidden,'Pre-cancel read replaced cancellation receipt');
    checks.push('Cancellation invalidates in-flight reads and keeps the canceled receipt after stale working response arrives');

    let broken=true;window.fetch=async(url,options)=>{if(String(url).startsWith('/api/tasks/poll-retry')){if(broken)return json({error:{code:'fixture',message:'合成断线'}},503);return json(String(url).includes('/events?')?{events:[]}:task('poll-retry','completed'));}return realFetch(url,options);};
    start('poll-retry');await poll('poll-retry');assert(!$('desktop-poll-feedback').hidden&&$('desktop-feedback-text').textContent.includes('读取中断'),'Persistent and focus-view connection feedback missing');
    assert(JSON.parse($('task-output').textContent).status.state==='working','Read failure fabricated task failure');broken=false;$('desktop-poll-feedback').querySelector('button').click();await wait(()=>$('desktop-poll-feedback').hidden&&JSON.parse($('task-output').textContent).status.state==='completed','retry recovery');
    checks.push('Read failure retains last task state, shows persistent retry and honest focus feedback, then recovers');

    let identityHeld=false,releaseIdentity;window.fetch=async(url,options)=>{if(String(url)==='/api/tasks/poll-owner'){identityHeld=true;await new Promise(resolve=>{releaseIdentity=resolve;releases.push(resolve);});return json(task('poll-owner'));}return realFetch(url,options);};
    start('poll-owner');const ownerRead=poll('poll-owner');await wait(()=>identityHeld,'held owner task');const access=await api('memory/access','POST',{});await useMemoryKey(access.key);releaseIdentity();await ownerRead;
    assert(currentTask===null&&$('task-output').textContent==='尚无任务'&&$('desktop-poll-feedback').hidden,'Old owner read repopulated cleared task');
    checks.push('Actual access-key switch aborts and rejects a late old-owner task response');
    document.body.dataset.desktopPollTest=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopPollTest=JSON.stringify({checks,error:error.stack});}
  finally{DesktopPoll.stop();currentTask=null;window.fetch=realFetch;for(const release of releases)release();if(originalHidden)Object.defineProperty(document,'hidden',originalHidden);else delete document.hidden;}
})();
