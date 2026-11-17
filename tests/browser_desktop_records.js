/* Real pagination uses --record-fixtures on :8769. Failures/gaps are explicit UI-boundary responses. */
(async()=>{
  const $=id=>document.getElementById(id),checks=[],realFetch=window.fetch,realOpen=window.openRecord;
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<160;i++){if(fn())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timeout: '+label);};
  const setQuery=value=>{$('record-query').value=value;$('record-query').dispatchEvent(new Event('input',{bubbles:true}));};
  const row=id=>$('record-list').querySelector(`[data-task-id="${id}"]`);
  const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
  try{
    assert(location.port==='8769'&&innerWidth>760,'Use desktop record fixture');showView('records');
    await wait(()=>recordLoaded&&!recordBusy,'first real page');assert(records.length===30&&recordCursor!=null,'First page contract');
    await loadRecords();assert(records.length===60&&recordCursor!=null,'Older page not appended');
    const older=records.at(-1),node=row(older.id),cursor=recordCursor;node.focus();renderRecords();
    assert(row(older.id)===node&&document.activeElement===node,'Unchanged render replaced row or lost focus');
    await loadRecords(true);assert(records.length===60&&recordCursor===cursor&&row(older.id)===node&&document.activeElement===node,'Latest refresh lost loaded history, cursor, row or focus');
    await loadRecords();assert(records.length===70&&recordCursor==null&&new Set(records.map(task=>task.id)).size===70,'Final real page omitted or duplicated records');
    checks.push('Actual 30/60/70 HTTP pagination retains history, exhausted cursor, task button identity and keyboard focus across refresh');

    const old=records.at(-1);records=records.map(task=>task.id===old.id?{...task,status:{...task.status,state:'working'}}:task);renderRecords();
    let olderReads=0;window.fetch=async(url,options)=>{if(String(url)==='/api/tasks/'+old.id)olderReads++;return realFetch(url,options);};
    await loadRecords(true);window.fetch=realFetch;assert(olderReads===1&&records.find(task=>task.id===old.id).status.state==='completed','Older running task was not calibrated against actual detail');
    records=records.map(task=>task.id===old.id?{...task,status:{...task.status,state:'working'}}:task);renderRecords();
    window.fetch=async(url,options)=>String(url)==='/api/tasks/'+old.id?json({error:{code:'fixture',message:'合成旧记录读取失败'}},503):realFetch(url,options);
    await loadRecords(true);assert($('desktop-record-feedback').dataset.state==='partial'&&records.find(task=>task.id===old.id).status.state==='working','Failed calibration must preserve old state and mark partial refresh');
    window.fetch=realFetch;$('desktop-record-feedback').querySelector('button').click();await wait(()=>!recordBusy&&records.find(task=>task.id===old.id).status.state==='completed','retry old task');clearTimeout(recordTimer);
    checks.push('Loaded older active tasks refresh from actual detail; partial failure preserves prior state and explicit retry recovers');

    setQuery('PAGE-0');const before=records.map(task=>task.id).join(','),savedCursor=recordCursor,focused=row(old.id);focused.focus();
    window.fetch=async(url,options)=>String(url).startsWith('/api/tasks?order=desc')?json({error:{code:'fixture',message:'合成列表读取失败'}},503):realFetch(url,options);
    await loadRecords(true);assert(records.map(task=>task.id).join(',')===before&&recordCursor===savedCursor&&$('record-query').value==='PAGE-0','Failed refresh discarded loaded records, cursor or query');
    assert($('desktop-record-feedback').dataset.state==='failed'&&!$('desktop-record-feedback').querySelector('button').hidden&&row(old.id)===focused&&document.activeElement===focused,'Persistent failure/retry or stable focus missing');
    window.fetch=realFetch;$('desktop-record-feedback').querySelector('button').click();await wait(()=>!recordBusy&&$('desktop-record-feedback').dataset.state==='ready','retry latest page');
    checks.push('Failed latest-page refresh retains records, filter, exhausted cursor and focus, with persistent retry feedback');

    setQuery('');const first=records[0],button=row(first.id),literal='<img src=x onerror=alert(1)>';
    window.fetch=async(url,options)=>{const response=await realFetch(url,options);if(String(url).startsWith('/api/tasks?order=desc')&&!String(url).includes('before=')){const value=await response.json();value.items[0]={...value.items[0],status:{...value.items[0].status,state:'failed'},metadata:{request:{subject:literal},error:{code:'BOUNDARY',message:literal}}};return json(value);}return response;};
    await loadRecords(true);window.fetch=realFetch;assert(row(first.id)===button&&button.dataset.state==='failed'&&button.textContent.includes(literal)&&!button.querySelector('img'),'Changed task did not update stable row as literal text');
    let clicked;window.openRecord=task=>{clicked=task;};button.click();window.openRecord=realOpen;
    assert(clicked?.status.state==='failed'&&taskBrief(clicked).subject===literal,'Reused row click used an outdated task object');
    checks.push('Changed content updates the original button; click receives latest task data and untrusted labels remain literal');

    const existing=new Set(records.map(task=>task.id));const gap=Array.from({length:30},(_,index)=>({id:'boundary-gap-'+index,contextId:'boundary-gap-'+index,status:{state:'completed',timestamp:new Date().toISOString()},metadata:{request:{subject:'GAP-'+index}}}));
    window.fetch=async(url,options)=>String(url).startsWith('/api/tasks?order=desc')&&!String(url).includes('before=')?json({items:gap,next_before:70}):realFetch(url,options);
    await loadRecords(true);window.fetch=realFetch;assert(records.length===100&&recordCursor===70&&[...existing].every(id=>records.some(task=>task.id===id)),'Disjoint newest page lost older data or gap cursor');
    let requested='';window.fetch=async(url,options)=>{if(String(url).startsWith('/api/tasks?order=desc'))requested=String(url);return realFetch(url,options);};await loadRecords();window.fetch=realFetch;
    assert(requested.includes('before=70')&&records.length===100&&new Set(records.map(task=>task.id)).size===100,'Continuing gap cursor failed or repeated existing rows');
    checks.push('Disjoint newest page preserves loaded history and an explicit gap cursor; actual older-page continuation deduplicates rows');
    let releaseOld,oldHeld=false;
    window.fetch=async(url,options)=>{const response=await realFetch(url,options);if(String(url).startsWith('/api/tasks?order=desc')){const value=await response.json();value.items.unshift({...gap[0],id:'prior-owner-private',contextId:'prior-owner-private'});oldHeld=true;await new Promise(resolve=>{releaseOld=resolve;});return json(value);}return response;};
    const oldLoad=loadRecords(true);await wait(()=>oldHeld,'held prior identity list');
    const access=await api('memory/access','POST',{});await useMemoryKey(access.key);
    assert(!records.length&&!recordLoaded&&!$('record-list').childElementCount&&!recordBusy,'Identity switch retained cached tasks or busy state');
    let releaseNew,newHeld=false;window.fetch=async(url,options)=>{const response=await realFetch(url,options);if(String(url).startsWith('/api/tasks?order=desc')){newHeld=true;await new Promise(resolve=>{releaseNew=resolve;});}return response;};
    const newLoad=loadRecords(true);await wait(()=>newHeld,'new identity list');releaseOld();await oldLoad;
    assert(recordBusy&&$('record-refresh').disabled&&!records.length,'Old request completion unlocked or repopulated new identity');
    releaseNew();await newLoad;window.fetch=realFetch;
    assert(records.length===30&&!records.some(task=>task.id==='prior-owner-private')&&!recordBusy,'Old identity response leaked into new loaded list');
    checks.push('Actual access-key switch clears record caches and rejects late old responses without unlocking a newer request');
    document.body.dataset.desktopRecordsTest=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopRecordsTest=JSON.stringify({checks,error:error.stack});}
  finally{window.fetch=realFetch;window.openRecord=realOpen;clearTimeout(recordTimer);}
})();
