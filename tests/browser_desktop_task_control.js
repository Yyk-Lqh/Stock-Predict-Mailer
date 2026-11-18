/* Actual Mock cancellation/background completion, fixture :8770 --mock-delay 1.5. */
(async()=>{
  const $=id=>document.getElementById(id),checks=[],realFetch=window.fetch;
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<200;i++){if(await fn())return;await new Promise(resolve=>setTimeout(resolve,80));}throw Error('Timeout: '+label);};
  async function prepare(message){$('new-analysis').click();await wait(()=>!$('new-analysis').disabled&&$('conversation-id').value,'conversation');$('try-sample').click();await wait(()=>!$('try-sample').disabled&&$('task-data').value.includes('console-mock'),'Mock sample');$('task-complexity').value='simple';$('conversation-message').value=message;$('conversation-message').dispatchEvent(new Event('input',{bubbles:true}));}
  try{
    assert(location.port==='8770'&&innerWidth>760,'Use delayed Mock fixture');showView('analysis');await prepare('实际取消桌面任务');
    let cancels=0;window.fetch=(url,options)=>{if(String(url).endsWith('/cancel')&&options?.method==='POST')cancels++;return realFetch(url,options);};
    $('analysis-send').click();await wait(()=>currentTask&&!$('task-cancel').hidden,'active task');const canceledId=currentTask;await $('task-cancel').onclick();
    const canceled=await api('tasks/'+canceledId);assert(canceled.status.state==='canceled'&&PonyOffice.snapshot().taskState==='canceled'&&cancels===1,'Actual cancellation did not reach backend and UI exactly once');await new Promise(resolve=>setTimeout(resolve,800));
    assert(JSON.parse($('task-output').textContent).status.state==='canceled','Delayed progress overwrote actual cancellation');
    checks.push('One actual cancel command stops a delayed Mock task; backend and desktop retain canceled state');
    await prepare('离开分析页仍在服务端完成任务');const previous=currentTask;let reads=0;
    window.fetch=(url,options)=>{if(options?.signal&&String(url).startsWith('/api/tasks/'))reads++;return realFetch(url,options);};
    $('analysis-send').click();await wait(()=>currentTask&&currentTask!==previous,'second task');const id=currentTask;showView('settings');await new Promise(resolve=>setTimeout(resolve,180));const paused=reads;
    await wait(async()=>(await api('tasks/'+id)).status.state==='completed','background backend completion');assert(reads===paused,'Desktop kept polling while away from analysis');showView('analysis');
    await wait(()=>$('result-summary').textContent.includes('报告已生成')&&PonyOffice.snapshot().taskState==='completed','resume actual report');
    assert(JSON.parse($('task-output').textContent).id===id&&reads>paused,'Returning did not read actual final report');
    checks.push('Backend completes actual Mock work while desktop reads pause; returning retrieves final report and events');
    document.body.dataset.desktopTaskControl=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopTaskControl=JSON.stringify({checks,error:error.stack});}
  finally{window.fetch=realFetch;}
})();
