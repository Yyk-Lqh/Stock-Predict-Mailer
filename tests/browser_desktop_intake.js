/* Run only on browser_intake_fixture.py; all files and snapshots are temporary synthetic samples. */
(async () => {
  const $=id=>document.getElementById(id),checks=[],realFetch=window.fetch;
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<180;i++){if(fn())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timeout: '+label);};
  const set=(id,value,event='input')=>{$(id).value=value;$(id).dispatchEvent(new Event(event,{bubbles:true}));};
  const stamp=Date.now(),validName=`bars-${stamp}.csv`,retryName=`retry-${stamp}.txt`,issueName=`issues-${stamp}.csv`;
  const csv=`日期,股票代码,开盘,最高,最低,收盘,成交量\n2026/10/23,603278.SH,10,11,9,10.5,${stamp}\n`;
  const good=new File([csv],validName,{type:'text/csv'}),retryFile=new File(['合成桌面验收资料 '+stamp],retryName,{type:'text/plain'}),bad=new File([csv+'2026/10/22,000001.SZ,10,8,9,10,100\n'],issueName,{type:'text/csv'});
  let failedOnce=false;
  const selectFile=async id=>{$('file-list').querySelector(`[data-upload-id="${id}"]`).click();await wait(()=>current?.upload_id===id,'select '+id);};
  try {
    assert(innerWidth>760&&window.DesktopIntake,'Desktop intake not initialized');
    window.fetch=async(url,options)=>{if(String(url).includes('/api/upload?')&&String(url).includes(encodeURIComponent(retryName))&&!failedOnce){failedOnce=true;return new Response(JSON.stringify({error:'合成单次网络失败，供显式重试验证'}),{status:503,headers:{'Content-Type':'application/json'}});}return realFetch(url,options);};
    await uploadFiles([good,retryFile,bad]);window.fetch=realFetch;
    assert(!DesktopIntake.busy&&$('intake-batch').textContent.includes('已完成 3 / 3'),'Batch did not complete real file count');
    assert($('intake-batch').textContent.includes('未完成')&&$('intake-batch').textContent.includes(retryName),'Per-file failure missing');
    const retryButton=$('intake-batch').querySelector(':scope > button');assert(!retryButton.hidden,'Explicit retry unavailable');retryButton.click();
    await wait(()=>!DesktopIntake.busy&&$('intake-batch').textContent.includes('已完成 1 / 1'),'explicit failed-only retry');
    assert(retryButton.hidden&&$('intake-batch').querySelector('li').textContent.includes(retryName),'Retry included already processed files');
    const all=(await api('/api/uploads')).uploads,goodSummary=all.find(file=>file.filename===validName),issueSummary=all.find(file=>file.filename===issueName),retrySummary=all.find(file=>file.filename===retryName);
    assert(goodSummary&&issueSummary&&retrySummary,'Real uploads missing from archive');
    checks.push('Real sequential uploads report each file; a simulated single network failure is retried only by an explicit failed-item action');

    set('intake-file-search',validName);assert([...$('file-list').querySelectorAll('.file-row')].filter(node=>!node.hidden).length===1,'Loaded-name filter mismatch');
    set('intake-file-search','');document.querySelector('.intake-filters [data-filter="needs_attention"]').click();
    assert([...$('file-list').querySelectorAll('.file-row')].filter(node=>!node.hidden).every(node=>node.dataset.fileState==='needs_attention'),'Status filter mismatch');
    document.querySelector('.intake-filters [data-filter="all"]').click();await selectFile(goodSummary.upload_id);
    assert($('intake-next').textContent.includes('输入 1 行')&&$('tables').querySelector('[data-intake-publish]').disabled,'Missing metadata must keep publishing blocked');
    checks.push('Loaded status/name filters reflect archive records; summary counts agree with real tables and publishing remains gated');
    const stableRow=$('file-list').querySelector(`[data-upload-id="${goodSummary.upload_id}"]`);stableRow.focus();await refresh();
    assert($('file-list').querySelector(`[data-upload-id="${goodSummary.upload_id}"]`)===stableRow&&document.activeElement===stableRow,'Unchanged archive refresh replaced selected file button or lost focus');
    checks.push('Unchanged file-list refresh reuses the selected button and preserves keyboard focus');

    set('column-map','[malformed');$('options-form').requestSubmit();
    assert($('column-map').value==='[malformed'&&document.activeElement===$('column-map')&&!DesktopIntake.busy,'Invalid mapping lost input or started processing');
    set('column-map','{"security_id":"股票代码"}');set('intake-map-target','date');set('intake-map-source','日期');
    $('options-form').requestSubmit();assert(document.querySelector('.intake-mapping [role="status"]').textContent.includes('未应用'),'Unapplied helper input was silently ignored');
    document.querySelector('.intake-mapping-row button').click();
    const mapping=JSON.parse($('column-map').value);assert(mapping.date==='日期'&&mapping.security_id==='股票代码','Mapping helper replaced unrelated entries');
    set('source','browser synthetic fixture');set('price-basis','unadjusted','change');set('volume-unit','shares','change');set('available-at','2026-10-24T08:00:00+08:00');
    const oldJob=current.job_id;$('options-form').requestSubmit();await wait(()=>!DesktopIntake.busy&&current.job_id!==oldJob,'real reprocess');
    assert(current.status==='ready','Complete metadata did not pass real cleaning');
    assert($('file-list').querySelector(`[data-upload-id="${goodSummary.upload_id}"]`)===stableRow&&stableRow.dataset.fileState==='ready','Changed file metadata did not update the existing list button');
    const publish=$('tables').querySelector('[data-intake-publish]');assert(!publish.disabled,'Ready table cannot publish');publish.click();
    await wait(()=>!DesktopIntake.busy&&$('intake-next').textContent.includes('本页发布回执'),'real publish receipt');
    assert(publish.disabled&&publish.textContent.includes('回执'),'Publish receipt must stop accidental repeated clicks on this page');
    await selectFile(issueSummary.upload_id);await selectFile(goodSummary.upload_id);
    assert($('tables').querySelector('[data-intake-publish]').disabled&&$('intake-next').textContent.includes('本页发布回执'),'Revisiting lost same-job receipt');
    checks.push('Mapping errors retain input, helper merges explicit mappings, complete metadata cleans successfully and real snapshot receipt survives revisiting');

    await selectFile(issueSummary.upload_id);assert(current.issue_count>0&&!document.querySelector('.intake-issue-tools').hidden,'Real issue record not visible');
    const issueFields=[...$('intake-issue-field').options];assert(issueFields.length>1,'Issue field selector missing');
    set('intake-issue-field',issueFields[1].value,'change');
    assert([...$('issues').querySelectorAll('.issue')].filter(node=>!node.hidden).every(node=>node.dataset.issueField===issueFields[1].value),'Issue field filter mismatch');
    const literal='<img src=x onerror=alert(1)>';render({...current,issues:[{table:literal,row:1,field:literal,code:'fixture',message:literal}],issue_count:1});
    assert(!$('issues').querySelector('img')&&$('issues').textContent.includes(literal),'Issue content interpreted as HTML');
    checks.push('Real issues can be filtered by field; issue text and field names stay literal at the UI boundary');

    // Hold a detail response while a later selection succeeds.
    let releaseDetail,detailHeld=false;
    window.fetch=async(url,options)=>{if(String(url)==='/api/uploads/'+goodSummary.upload_id&&!options?.method){const response=await realFetch(url,options);detailHeld=true;await new Promise(resolve=>{releaseDetail=resolve;});return response;}return realFetch(url,options);};
    $('file-list').querySelector(`[data-upload-id="${goodSummary.upload_id}"]`).click();await wait(()=>detailHeld,'held detail');
    await selectFile(retrySummary.upload_id);releaseDetail();await new Promise(resolve=>setTimeout(resolve,160));window.fetch=realFetch;
    assert(current.upload_id===retrySummary.upload_id,'Late detail replaced newer selection');
    checks.push('Late file-detail response cannot overwrite a newer selection');

    await selectFile(goodSummary.upload_id);let releaseProcess,processHeld=false;
    window.fetch=async(url,options)=>{if(String(url)==='/api/process'){const response=await realFetch(url,options);processHeld=true;await new Promise(resolve=>{releaseProcess=resolve;});return response;}return realFetch(url,options);};
    $('options-form').requestSubmit();await wait(()=>processHeld,'held process');assert(DesktopIntake.busy&&$('files').disabled&&$('scan').disabled,'Active mutation did not lock upload/scan');
    await selectFile(retrySummary.upload_id);releaseProcess();await wait(()=>!DesktopIntake.busy,'finish held process');window.fetch=realFetch;
    assert(current.upload_id===retrySummary.upload_id&&$('notice').textContent.includes('该文件的信息已保存'),'Late process changed newer selection or hid receipt');
    await selectFile(goodSummary.upload_id);assert(!$('tables').querySelector('[data-intake-publish]').disabled,'New processing job reused old publish receipt');
    checks.push('Late reprocessing preserves current selection; writes lock conflicting actions; new processing job requires its own publish receipt');
    set('intake-theme','light','change');assert(document.documentElement.dataset.intakeTheme==='light','Light theme did not apply');
    set('intake-theme','dark','change');assert(document.documentElement.dataset.intakeTheme==='dark','Dark theme did not apply');
    assert(!Object.values(localStorage).some(value=>value.includes(validName)),'File data stored as a browser preference');
    checks.push('Desktop theme preference applies without storing file contents or session data');
    document.body.dataset.desktopIntakeTest=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopIntakeTest=JSON.stringify({checks,error:error.stack});}
  finally{window.fetch=realFetch;}
})();
