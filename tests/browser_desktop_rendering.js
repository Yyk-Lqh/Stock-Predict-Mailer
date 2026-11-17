/* Desktop scene suspension plus actual Mock task progress; disposable :8768 only. */
(async()=>{
  const $=id=>document.getElementById(id),checks=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<180;i++){if(fn())return;await sleep(100);}throw Error('Timeout: '+label);};
  const mode=value=>document.querySelector(`[data-desktop-mode="${value}"]`).click();
  async function mutations(){await sleep(160);let count=0;const observer=new MutationObserver(items=>count+=items.length);observer.observe(document.querySelector('.office-stage'),{attributes:true,childList:true,subtree:true});await sleep(400);observer.disconnect();return count;}
  try{
    assert(location.port==='8768'&&innerWidth>760,'Use disposable desktop console');showView('analysis');mode('focus');assert(await mutations()===0,'Hidden focus scene kept drawing');
    mode('hall');assert(await mutations()>0,'Hall did not resume drawing');showView('settings');assert(await mutations()===0,'Settings page kept drawing hidden scene');showView('analysis');assert(await mutations()>0,'Returning to hall did not resume');
    checks.push('Focus and settings suspend continuous scene DOM work; showing the hall resumes drawing');
    window.dispatchEvent(new PageTransitionEvent('pagehide'));assert(await mutations()===0,'Pagehide did not stop animation loop');
    window.dispatchEvent(new PageTransitionEvent('pageshow'));window.dispatchEvent(new PageTransitionEvent('pageshow'));assert(await mutations()>0,'Pageshow failed to restore the loop');
    mode('focus');assert(await mutations()===0,'Restored loop could not suspend again');
    checks.push('Page lifecycle stops/restores the scene and repeated resume remains suspendable');
    showView('records');await wait(()=>recordLoaded&&!recordBusy,'loaded records before submission');const retainedIds=records.map(task=>task.id),recordsOwner=memoryKey;showView('analysis');mode('focus');
    $('new-analysis').click();await wait(()=>!$('new-analysis').disabled&&$('conversation-id').value,'conversation');$('try-sample').click();await wait(()=>!$('try-sample').disabled&&$('task-data').value.includes('console-mock'),'Mock sample');
    $('task-complexity').value='simple';$('conversation-message').value='桌面隐藏场景仍核对真实任务进度';$('conversation-message').dispatchEvent(new Event('input',{bubbles:true}));$('analysis-send').click();
    await wait(()=>PonyOffice.snapshot().taskState==='completed'&&$('result-summary').textContent.includes('报告已生成'),'actual Mock report');
    const id=PonyOffice.snapshot().taskId,task=await api('tasks/'+id);assert(task.status.state==='completed'&&task.artifacts[0].parts[0].data.analysis,'No actual backend report');
    assert($('office-task-state').textContent.includes('已完成')&&await mutations()===0,'Progress UI was lost or idle scene kept drawing');
    showView('records');await wait(()=>recordLoaded&&!recordBusy,'new submission records');assert(records.some(item=>item.id===id),'Records invalidated by submission did not read newest page');
    if(recordsOwner===memoryKey)assert(retainedIds.filter(previous=>!previous.startsWith('boundary-')).every(previous=>records.some(item=>item.id===previous)),'New task refresh discarded previous records');showView('analysis');mode('hall');
    assert(PonyOffice.snapshot().actors.find(actor=>actor.id==='main').state==='completed'&&await mutations()>0,'Resumed hall lost final backend state');
    checks.push('Actual Mock task completes while scene is suspended; progress/report and resumed actors retain backend state');
    $('desktop-result').click();await wait(()=>!$('analysis-pane-report').hidden,'report tab');$('report-expand').click();await wait(()=>document.body.classList.contains('desktop-report-reading'),'focused reading');
    assert(await mutations()===0,'Scene behind focused reading kept drawing');$('report-expand').click();assert(await mutations()>0,'Exiting reading did not restore visible hall');$('report-close').click();mode('focus');
    checks.push('Focused report reading suspends the covered hall and restores it on exit');
    document.body.dataset.desktopRenderingTest=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopRenderingTest=JSON.stringify({checks,error:error.stack});}
})();
