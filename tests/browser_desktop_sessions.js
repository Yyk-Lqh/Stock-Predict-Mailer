/* Actual private conversation APIs; disposable console :8768 only. No model calls. */
(async()=>{
  const $=id=>document.getElementById(id),checks=[],realFetch=window.fetch,realConfirm=window.confirm,releases=[];
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<160;i++){if(fn())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timeout: '+label);};
  const rows=()=>[...$('sidebar-sessions').querySelectorAll('.session-item')],row=id=>$('sidebar-sessions').querySelector(`[data-conversation="${id}"]`);
  const query=value=>{$('desktop-session-query').value=value;$('desktop-session-query').dispatchEvent(new Event('input',{bubbles:true}));};
  const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
  try{
    assert(location.port==='8768'&&innerWidth>760&&window.DesktopSessions,'Use desktop fixture');
    const access=await api('memory/access','POST',{});await useMemoryKey(access.key);await wait(()=>!$('sessions-refresh').disabled,'empty owner');
    assert(!$('sidebar-sessions').textContent.includes('正在读取')&&rows().length===0,'Empty catalog stayed in loading state');
    for(let i=0;i<35;i++)await api('conversations','POST',{},undefined,AnalysisMode.capture());
    await Workbench.sessions();assert(rows().length===30&&!$('sessions-more').hidden,'Actual first session page missing');
    await Workbench.sessions(true);assert(rows().length===35&&$('sessions-more').hidden,'Actual older page not appended/exhausted');
    $('session-menu').open=true;const oldest=rows().at(-1),oldestId=oldest.dataset.conversation;oldest.focus();await Workbench.sessions();
    assert(rows().length===35&&row(oldestId)===oldest&&document.activeElement===oldest,'Refresh discarded loaded sessions, identity or focus');
    assert(rows()[0].querySelector('time').dateTime.includes('T')&&rows()[0].textContent.includes('更新于'),'Session timestamp missing actual metadata');
    checks.push('Actual 30/35 session pagination, exhausted cursor, full update timestamps, stable buttons and keyboard focus survive refresh');

    query('no matching session');assert(rows().every(node=>node.hidden)&&!$('desktop-session-no-match').hidden&&$('desktop-session-scope').textContent.includes('0 / 35'),'Loaded-only search scope is incorrect');
    query('新分析');assert(rows().every(node=>!node.hidden),'Loaded-name match not restored');
    window.fetch=async(url,options)=>String(url).startsWith('/api/conversations?limit=30')?json({error:{code:'fixture',message:'合成会话刷新失败'}},503):realFetch(url,options);
    await Workbench.sessions();assert($('desktop-session-feedback').dataset.state==='failed'&&rows().length===35&&$('desktop-session-query').value==='新分析','Failed refresh discarded catalog or query');
    window.fetch=realFetch;$('desktop-session-feedback').querySelector('button').click();await wait(()=>!$('sessions-refresh').disabled&&$('desktop-session-feedback').hidden,'persistent retry');
    assert(rows().length===35&&row(oldestId)===oldest,'Retry replaced retained session row');query('');
    checks.push('Loaded-name search is scoped honestly; persistent refresh failure retains catalog/query and explicit retry recovers');

    const first=rows()[0].dataset.conversation,second=rows()[1].dataset.conversation;
    row(first).click();await wait(()=>$('conversation-id').value===first&&!$('task-form').inert,'select first');$('conversation-message').value='会话甲未提交草稿';$('conversation-message').dispatchEvent(new Event('input',{bubbles:true}));
    row(second).click();await wait(()=>$('conversation-id').value===second&&!$('task-form').inert,'select second');$('conversation-message').value='会话乙未提交草稿';$('conversation-message').dispatchEvent(new Event('input',{bubbles:true}));
    row(first).click();await wait(()=>$('conversation-id').value===first&&!$('task-form').inert,'return first');
    assert($('conversation-message').value==='会话甲未提交草稿'&&row(first).getAttribute('aria-current')==='true','Session UI bypassed original draft selection logic');
    window.confirm=()=>true;[...$('conversation-tools').querySelectorAll('button')].find(node=>node.textContent==='删除会话').click();
    await wait(()=>$('conversation-id').value===''&&!row(first)&&!$('sessions-refresh').disabled,'delete selected conversation');
    assert(!(await api('conversations')).some(item=>item.id===first)&&rows().length===34,'Deleted conversation reappeared in retained catalog');window.confirm=realConfirm;
    checks.push('Session selection preserves independent original drafts; actual deletion removes the retained row and server conversation');

    const temporary=(await api('conversations','POST',{},undefined,AnalysisMode.capture())).id;await refreshMemory();await Workbench.sessions();
    row(temporary).click();await wait(()=>$('conversation-id').value===temporary&&!$('task-form').inert,'select deletion-race conversation');await Workbench.sessions();
    let deletionHeld=false,releaseDeletion;
    window.fetch=async(url,options)=>{const response=await realFetch(url,options);if(String(url).startsWith('/api/conversations?limit=30')){deletionHeld=true;await new Promise(resolve=>{releaseDeletion=resolve;releases.push(resolve);});}return response;};
    const beforeDeletion=Workbench.sessions();await wait(()=>deletionHeld,'held pre-deletion catalog');
    window.confirm=()=>true;[...$('conversation-tools').querySelectorAll('button')].find(node=>node.textContent==='删除会话').click();
    await wait(()=>$('conversation-id').value===''&&!row(temporary),'delete while catalog refresh is held');
    assert(!(await api('conversations')).some(item=>item.id===temporary),'Temporary conversation was not deleted on server');
    releaseDeletion();await beforeDeletion;window.fetch=realFetch;window.confirm=realConfirm;
    assert(!row(temporary)&&rows().length===34,'Late pre-deletion catalog restored the deleted conversation');
    await Workbench.sessions();assert(!row(temporary)&&rows().length===34,'Subsequent refresh retained a deleted conversation');
    checks.push('Actual deletion during a held catalog refresh survives the late response and a subsequent authoritative refresh');

    const literal='<img src=x onerror=alert(1)>',existing=rows()[0],id=existing.dataset.conversation;
    window.fetch=async(url,options)=>{const response=await realFetch(url,options);if(String(url).startsWith('/api/conversations?limit=30')){const data=await response.json();data.items[0].subject=literal;return json(data);}return response;};await Workbench.sessions();window.fetch=realFetch;
    assert(row(id)===existing&&existing.textContent.includes(literal)&&!$('sidebar-sessions').querySelector('img'),'Session subject was interpreted as HTML or replaced stable button');await Workbench.sessions();
    checks.push('Updated session metadata stays literal and updates the existing button');

    const oldKey=memoryKey;let held=false,release;window.fetch=async(url,options)=>{const response=await realFetch(url,options);if(String(url).startsWith('/api/conversations?limit=30')&&options?.headers?.['X-Memory-Key']===oldKey){held=true;await new Promise(resolve=>{release=resolve;});}return response;};
    const pending=Workbench.sessions();await wait(()=>held,'held old owner catalog');const next=await api('memory/access','POST',{});await useMemoryKey(next.key);await wait(()=>!$('sessions-refresh').disabled,'new owner empty catalog');release();await pending;window.fetch=realFetch;
    assert(rows().length===0&&!$('sidebar-sessions').textContent.includes(literal)&&$('desktop-session-query').value===''&&$('sessions-more').hidden,'Old catalog leaked after access-key switch');
    checks.push('Actual access-key switch clears catalog/filter/cursor and late old-owner response cannot restore them');
    document.body.dataset.desktopSessionsTest=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopSessionsTest=JSON.stringify({checks,error:error.stack});}
  finally{window.fetch=realFetch;window.confirm=realConfirm;for(const release of releases)release();}
})();
