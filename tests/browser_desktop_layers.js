/* Desktop overlay order and original conversation actions. Disposable :8768 only. */
(async()=>{
  const $=id=>document.getElementById(id),checks=[],realConfirm=window.confirm;
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<160;i++){if(fn())return;await new Promise(resolve=>setTimeout(resolve,80));}throw Error('Timeout: '+label);};
  const key=value=>document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true}));
  const openModels=()=>{$('composer-effort').click();$('composer-effort-model').click();};
  try{
    assert(innerWidth>760&&location.port==='8768','Use desktop fixture');$('new-analysis').click();await wait(()=>!$('new-analysis').disabled&&$('conversation-id').value,'conversation');const cid=$('conversation-id').value;
    $('try-sample').click();await wait(()=>!$('try-sample').disabled&&$('task-data').value.includes('console-mock'),'sample');$('conversation-message').value='桌面键盘层级验收';$('conversation-message').dispatchEvent(new Event('input',{bubbles:true}));$('analysis-send').click();await wait(()=>$('result-summary').textContent.includes('报告已生成'),'real Mock report');
    $('desktop-data').focus();$('desktop-data').click();openModels();assert($('composer-popover').contains(document.activeElement),'Model menu should focus an option');key('Escape');
    assert($('composer-popover').hidden&&!$('report-inspector').hidden&&document.activeElement===$('composer-effort'),'Popup Escape closed underlying inspector or lost trigger focus');
    $('session-menu').open=true;$('desktop-session-query').value='DEMO';$('desktop-session-query').focus();key('Escape');
    assert(!$('session-menu').open&&!$('report-inspector').hidden&&document.activeElement===$('session-menu').querySelector('summary')&&$('desktop-session-query').value==='DEMO','Session Escape lost query/background/focus');$('desktop-session-query').value='';$('desktop-session-query').dispatchEvent(new Event('input',{bubbles:true}));
    checks.push('Popup and session Escape close one layer, retain background inspector/query and restore visible trigger focus');

    $('desktop-history').click();openModels();key('Escape');assert($('analysis-composer').classList.contains('desktop-history-open')&&!$('report-inspector').hidden,'Nested popup Escape closed history');key('Escape');
    assert(!$('analysis-composer').classList.contains('desktop-history-open')&&!$('report-inspector').hidden&&document.activeElement===$('desktop-history'),'History Escape closed inspector or lost focus');key('Escape');assert($('report-inspector').hidden&&document.activeElement.getClientRects().length,'Inspector Escape left hidden focus');
    checks.push('Nested popup, history and inspector close in order without hiding the next layer');

    $('desktop-feedback-action').focus();$('desktop-feedback-action').click();$('report-expand').click();assert(document.body.classList.contains('desktop-report-reading'),'Reading mode');key('Escape');
    assert(!document.body.classList.contains('desktop-report-reading')&&!$('report-inspector').hidden,'Reading Escape must exit full reading before closing report');key('Escape');assert($('report-inspector').hidden&&document.activeElement===$('desktop-feedback-action'),'Report close lost visible origin');
    checks.push('Focused reading exits first; second Escape closes report and returns to its visible origin');

    $('desktop-data').click();const subject=$('p-subject').value;$('analysis-tab-input').focus();key('End');assert(document.activeElement===$('analysis-tab-report')&&!$('analysis-pane-report').hidden,'End does not reach final tab');key('Home');assert(document.activeElement===$('analysis-tab-input')&&!$('analysis-pane-input').hidden,'Home does not reach first tab');key('ArrowRight');assert(document.activeElement===$('analysis-tab-progress'),'Original ArrowRight changed');
    assert($('p-subject').value===subject,'Tab keyboard navigation changed input');$('report-close').click();
    assert(getComputedStyle($('workbench-intro')).display==='none'&&$('session-menu').contains($('conversation-tools')),'Duplicate guide/actions overlap workspace');
    checks.push('Home/End and existing arrow tabs retain input; original current-conversation actions live in the session menu');

    let blob,download;const create=URL.createObjectURL,click=HTMLAnchorElement.prototype.click;
    try{URL.createObjectURL=value=>{blob=value;return 'blob:desktop-export-fixture';};HTMLAnchorElement.prototype.click=function(){download=this.download;};await [...$('conversation-tools').querySelectorAll('button')].find(node=>node.textContent==='导出会话').onclick();}
    finally{URL.createObjectURL=create;HTMLAnchorElement.prototype.click=click;}
    assert(download===`conversation-${cid}.json`&&(await blob.text()).includes(cid),'Moved export did not use original selected conversation');
    $('session-menu').open=true;const remove=[...$('conversation-tools').querySelectorAll('button')].find(node=>node.textContent==='删除会话');remove.focus();window.confirm=()=>true;await remove.onclick();window.confirm=realConfirm;
    assert(!$('conversation-id').value&&document.activeElement===$('desktop-session-query')&&!(await api('conversations')).some(item=>item.id===cid),'Moved delete lost original behavior or focus');
    checks.push('Moved export uses actual selected conversation; actual deletion returns focus to visible session search');
    document.body.dataset.desktopLayersTest=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopLayersTest=JSON.stringify({checks,error:error.stack});}finally{window.confirm=realConfirm;}
})();
