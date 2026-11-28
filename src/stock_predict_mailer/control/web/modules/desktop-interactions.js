/* Desktop closing behavior and conversation loading. Original controls keep their handlers. */
window.DesktopInteractions=(()=>{
  const desktop=matchMedia('(min-width: 761px)');if(!desktop.matches)return;
  const dock=$('analysis-composer'),message=$('conversation-message'),toolbar=dock.querySelector('.analysis-composer-controls'),menu=$('session-menu'),summary=menu.querySelector('summary');
  let lock=null,failure=null,focusEpoch=0;
  const visible=node=>{if(!(node instanceof HTMLElement)||!node.isConnected||!node.getClientRects().length||node.closest('[hidden],[inert]'))return false;for(let parent=node.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS'&&!parent.open&&!parent.querySelector(':scope > summary')?.contains(node))return false;return getComputedStyle(node).visibility!=='hidden';};
  function restoreIfLost(target){const focused=document.activeElement;if(document.querySelector('dialog[open]'))return;if(focused===document.body||!visible(focused))target?.focus({preventScroll:true});}
  function unlock(){if(!lock)return;message.readOnly=lock.readOnly;toolbar.inert=lock.toolbarInert;if(lock.busy==null)dock.removeAttribute('aria-busy');else dock.setAttribute('aria-busy',lock.busy);lock=null;}
  function begin(){++focusEpoch;const origin=document.activeElement;window.ComposerControls?.close();if(!lock)lock={readOnly:message.readOnly,toolbarInert:toolbar.inert,busy:dock.getAttribute('aria-busy'),origin};else lock.origin=origin;failure=null;message.readOnly=true;toolbar.inert=true;dock.setAttribute('aria-busy','true');window.DesktopWorkbench?.selectionState({state:'loading'});}
  function finish(id){const origin=lock?.origin;window.AnalysisInput?.resize();unlock();window.ComposerControls?.update();window.DesktopWorkbench?.selectionState(failure||{state:'idle'});
    if($('conversation-id').value!==id||document.body.dataset.view!=='analysis')return;
    const key=memoryKey,generation=focusEpoch,target=failure?$('desktop-feedback-action'):message;
    requestAnimationFrame(()=>{if(generation===focusEpoch&&!lock&&key===memoryKey&&$('conversation-id').value===id&&document.body.dataset.view==='analysis'){const focused=document.activeElement;if(focused===origin||focused===document.body||!visible(focused))restoreIfLost(target);}});
  }
  function failed(id,error,retry,denied=false){const key=memoryKey;failure={state:'failed',denied,message:'会话读取失败：'+error+(denied?'。未恢复或改写本地草稿，请重新读取或选择其他会话。':'。可重新读取或选择其他会话；已保存的草稿仍保留。'),retry:()=>{if(key===memoryKey&&$('conversation-id').value===id)Promise.resolve(retry()).catch(value=>notice(value.message,true));}};}
  function reset(){++focusEpoch;unlock();failure=null;window.AnalysisInput?.resize();window.DesktopWorkbench?.selectionState({state:'idle'});}
  const tools=$('conversation-tools'),caption=document.createElement('span');caption.textContent='当前会话操作';caption.className='hint desktop-current-session-label';tools.prepend(caption);menu.querySelector('.desktop-session-tools').after(tools);
  $('report-close').addEventListener('click',()=>restoreIfLost(visible($('desktop-data'))&&!$('desktop-data').disabled?$('desktop-data'):summary));
  menu.addEventListener('toggle',()=>{if(desktop.matches&&menu.open&&document.activeElement===summary)$('desktop-session-query').focus();});
  document.addEventListener('keydown',event=>{
    if(!desktop.matches)return;
    if(['Home','End'].includes(event.key)&&event.target.closest('.analysis-tabs [role="tab"]')){event.preventDefault();event.stopImmediatePropagation();const pane=event.key==='Home'?'input':'report';AnalysisInput.open(pane);$('analysis-tab-'+pane).focus();return;}
    if(event.key!=='Escape' || event.target.closest('#desktop-focus'))return;
    event.stopImmediatePropagation();
    if(document.querySelector('dialog[open]'))return; // Keep native cancel and its saving guard.
    const popup=$('composer-popover');
    if(popup&&!popup.hidden){event.preventDefault();ComposerControls.close(true);return;}
    if(menu.open){event.preventDefault();menu.open=false;summary.focus();return;}
    if(dock.classList.contains('desktop-history-open')){event.preventDefault();$('desktop-history').click();$('desktop-history').focus();return;}
    if(document.body.classList.contains('desktop-report-reading')){event.preventDefault();$('report-expand').click();$('report-expand').focus();return;}
    if(!$('report-inspector').hidden){event.preventDefault();$('report-close').click();}
  },true);
  return {active:()=>desktop.matches,blocked:()=>Boolean(lock),draftBlocked:()=>Boolean(lock||failure?.denied),begin,finish,failed,reset,afterDelete(){restoreIfLost(menu.open?$('desktop-session-query'):summary);}};
})();
