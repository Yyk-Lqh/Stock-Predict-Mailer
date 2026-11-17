/* One desktop read chain per selected task. Backend execution is independent of visibility. */
window.DesktopPoll=(()=>{
  const desktop=matchMedia('(min-width: 761px)');if(!desktop.matches)return;
  let job=null,epoch=0,suspended=false,canceling=null;
  const feedback=document.createElement('div');feedback.id='desktop-poll-feedback';feedback.className='desktop-poll-feedback';feedback.hidden=true;
  const status=document.createElement('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const retry=document.createElement('button');retry.type='button';retry.className='btn tiny';retry.textContent='重新读取进度';retry.onclick=()=>resume();feedback.append(status,retry);$('analysis-pane-progress').prepend(feedback);
  const same=value=>job===value&&currentTask===value.id&&memoryKey===value.key;
  const visible=()=>!suspended&&!document.hidden&&document.body.dataset.view==='analysis';
  function stop(){++epoch;if(job){clearTimeout(job.timer);job.control?.abort();}job=null;canceling=null;$('task-cancel').disabled=false;feedback.hidden=true;window.DesktopWorkbench?.connectionLost(false);}
  function pause(){if(!job)return;clearTimeout(job.timer);job.timer=null;job.control?.abort();}
  function schedule(value,delay){clearTimeout(value.timer);if(same(value)&&visible()&&!value.done)value.timer=setTimeout(()=>request(value.id),delay);}
  function request(id){
    if(!id||id!==currentTask)return Promise.resolve();
    if(!job||job.id!==id||job.key!==memoryKey){stop();job={id,key:memoryKey,timer:null,promise:null,control:null,done:false,urgent:false};}
    const value=job;if(value.done||!visible())return value.promise||Promise.resolve();
    clearTimeout(value.timer);value.timer=null;
    if(value.promise){if(value.control?.signal.aborted)value.urgent=true;return value.promise;}
    const control=new AbortController();value.control=control;let timeout=false,delay=700;
    const expiry=setTimeout(()=>{timeout=true;control.abort();},8000);retry.disabled=true;feedback.setAttribute('aria-busy','true');
    value.promise=(async()=>{
      try{
        const task=await api('tasks/'+id,'GET',undefined,control.signal);
        if(!same(value)||!visible()||control.signal.aborted)return;
        const progress=await api(`tasks/${id}/events?after=${eventCursor}`,'GET',undefined,control.signal);
        if(!same(value)||!visible()||control.signal.aborted)return;
        for(const event of progress.events){if(event.seq<=eventCursor)continue;showEvent(event);eventCursor=event.seq;}
        runvizSample();PonyOffice.sync(task,progress.events);const terminal=showTask(task);
        feedback.hidden=true;window.DesktopWorkbench?.connectionLost(false);
        if(terminal&&progress.events.length<100){value.done=true;overviewTask=task;renderSteps();if(memoryKey)refreshMemory().catch(error=>{if(same(value))notice(error.message,true);});}
      }catch(error){
        if(!same(value)||!visible()||(control.signal.aborted&&!timeout))return;
        delay=2500;PonyOffice.disconnected();feedback.hidden=false;window.DesktopWorkbench?.connectionLost(true);
        const message=`进度读取${timeout?'超时':'中断'}：${timeout?'本次读取超过 8 秒':error.message}。任务可能仍在服务端运行；稍后自动重试，也可手动读取。`;
        if(status.textContent!==message)status.textContent=message;
      }finally{
        clearTimeout(expiry);
        if(same(value)){value.promise=null;value.control=null;retry.disabled=false;feedback.setAttribute('aria-busy','false');const next=value.urgent?0:delay;value.urgent=false;schedule(value,next);}
      }
    })();
    return value.promise;
  }
  function resume(){return request(currentTask);}
  function ticket(){return {id:currentTask,key:memoryKey,epoch};}
  const valid=token=>Boolean(token&&token.epoch===epoch&&token.id===currentTask&&token.key===memoryKey);
  function beginCancel(){if(!currentTask||valid(canceling))return null;canceling=ticket();$('task-cancel').disabled=true;return canceling;}
  function cancelled(task,token){if(!valid(token)||task.id!==token.id)return Promise.resolve();stop();PonyOffice.sync(task,[]);showTask(task);return request(task.id);}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();else resume();});
  window.addEventListener('pagehide',()=>{suspended=true;pause();});window.addEventListener('pageshow',()=>{suspended=false;resume();});
  return {active:()=>desktop.matches,request,resume,stop,beginCancel,valid,cancelled,endCancel(token){if(canceling===token){canceling=null;$('task-cancel').disabled=false;}},view(name){if(name==='analysis')resume();else pause();}};
})();
