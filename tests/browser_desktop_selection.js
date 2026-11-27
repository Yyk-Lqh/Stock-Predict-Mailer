/* Disposable :8768. Driver must type into readonly input at data-selection-typing-ready, then call __desktopSelectionContinue(). */
(async()=>{
  const $=id=>document.getElementById(id),checks=[],realFetch=window.fetch,releases=[];
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<160;i++){if(fn())return;await new Promise(resolve=>setTimeout(resolve,80));}throw Error('Timeout: '+label);};
  const row=id=>$('sidebar-sessions').querySelector(`[data-conversation="${id}"]`);
  async function select(id){$('session-menu').open=true;row(id).focus();row(id).click();await wait(()=>$('conversation-id').value===id&&!$('task-form').inert,'select '+id);}
  const input=value=>{$('conversation-message').value=value;$('conversation-message').dispatchEvent(new Event('input',{bubbles:true}));};
  async function hold(id){let held=false,release;window.fetch=async(url,options)=>{const response=await realFetch(url,options);if(String(url).startsWith('/api/conversations/'+id)&&(!options?.method||options.method==='GET')){held=true;await new Promise(resolve=>{release=resolve;releases.push(resolve);});}return response;};$('session-menu').open=true;row(id).focus();row(id).click();await wait(()=>held,'held history');return release;}
  try{
    assert(innerWidth>760&&location.port==='8768','Use desktop fixture');$('new-analysis').click();await wait(()=>!$('new-analysis').disabled&&$('conversation-id').value,'first conversation');const a=$('conversation-id').value,b=(await api('conversations','POST',{},undefined,AnalysisMode.capture())).id,c=(await api('conversations','POST',{},undefined,AnalysisMode.capture())).id;await refreshMemory();await Workbench.sessions();
    await select(b);input('乙会话原草稿');await select(a);input('甲会话原草稿');let release=await hold(b);
    assert($('conversation-message').readOnly&&document.querySelector('.analysis-composer-controls').inert&&$('desktop-sample').disabled&&$('desktop-feedback-text').textContent.includes('正在切换'),'Selection did not lock real composer and explain loading');
    $('conversation-message').focus();window.__desktopSelectionBefore=$('conversation-message').value;document.body.dataset.selectionTypingReady='true';
    await new Promise(resolve=>{window.__desktopSelectionContinue=()=>{release();resolve();};});await wait(()=>!$('task-form').inert,'first held finish');window.fetch=realFetch;await wait(()=>document.activeElement===$('conversation-message'),'visible composer focus');
    assert(window.__desktopNativeBlocked&&$('conversation-message').value==='乙会话原草稿'&&document.activeElement===$('conversation-message'),'Native input/draft/focus: '+JSON.stringify({blocked:window.__desktopNativeBlocked,value:$('conversation-message').value,active:document.activeElement.id,activeClass:document.activeElement.className,readOnly:$('conversation-message').readOnly}));
    checks.push('Held selection locks native typing/toolbar/shortcut, explains loading, restores saved draft and focuses the composer');

    await select(a);release=await hold(b);await select(c);release();window.fetch=realFetch;await new Promise(resolve=>setTimeout(resolve,100));await select(b);
    assert($('conversation-message').value==='乙会话原草稿'&&!$('conversation-message').readOnly&&!document.querySelector('.analysis-composer-controls').inert,'Rapid selection saved transient blank draft or left a stale lock');
    checks.push('Rapid second selection ignores stale response and never saves the transient empty target over its draft');

    await select(a);let broken=true;window.fetch=async(url,options)=>String(url).startsWith('/api/conversations/'+b)&&broken?new Response(JSON.stringify({error:{code:'fixture',message:'合成历史读取失败'}}),{status:503,headers:{'Content-Type':'application/json'}}):realFetch(url,options);
    await select(b);assert($('conversation-message').value==='乙会话原草稿'&&$('desktop-feedback-action').textContent==='重新读取会话'&&$('desktop-feedback-text').textContent.includes('读取失败'),'Failed selection did not retain local draft and retry');
    input('失败后继续编辑的乙草稿');broken=false;$('desktop-feedback-action').click();await wait(()=>!$('task-form').inert&&$('desktop-feedback-action').textContent!=='重新读取会话','selection retry');window.fetch=realFetch;
    assert($('conversation-message').value==='失败后继续编辑的乙草稿'&&!$('task-notify').checked,'Retry discarded edits or restored mail opt-in');
    checks.push('Transient history failure restores local draft and persistent retry; retry preserves later edits and leaves email off');

    await select(a);window.fetch=async(url,options)=>String(url).startsWith('/api/conversations/'+b)?new Response(JSON.stringify({error:{code:'FORBIDDEN',message:'合成权限拒绝'}}),{status:403,headers:{'Content-Type':'application/json'}}):realFetch(url,options);await select(b);
    assert($('conversation-message').value===''&&$('desktop-feedback-text').textContent.includes('FORBIDDEN'),'Denied history restored cached private content');await select(a);await select(b);window.fetch=realFetch;$('desktop-feedback-action').click();await wait(()=>!$('task-form').inert&&$('desktop-feedback-action').textContent!=='重新读取会话','permission retry');
    assert($('conversation-message').value==='失败后继续编辑的乙草稿','Denied retry overwrote preexisting draft');
    checks.push('Permission failure never restores cached content; leaving, returning and authorized retry preserve its saved draft');

    await select(a);release=await hold(b);Workbench.record({id:'desktop-independent-selection-boundary',status:{state:'completed'},metadata:{request:{subject:'独立任务边界'}}});release();window.fetch=realFetch;await new Promise(resolve=>setTimeout(resolve,100));
    assert(!$('conversation-id').value&&!$('conversation-message').readOnly&&!$('task-form').inert&&!document.querySelector('.analysis-composer-controls').inert,'Independent record retained pending conversation or input lock');await select(b);assert($('conversation-message').value==='失败后继续编辑的乙草稿','Independent record saved transient target over its draft');
    checks.push('Opening an independent record cancels pending selection without a stale lock or overwriting the target draft');

    await select(a);release=await hold(b);$('new-analysis').click();await wait(()=>!$('new-analysis').disabled&&$('conversation-id').value!==b&&!$('task-form').inert,'new analysis during selection');const fresh=$('conversation-id').value;release();window.fetch=realFetch;await new Promise(resolve=>setTimeout(resolve,100));
    assert($('conversation-id').value===fresh&&!$('conversation-message').readOnly&&!document.querySelector('.analysis-composer-controls').inert,'Old selection changed new analysis or retained lock');await select(b);assert($('conversation-message').value==='失败后继续编辑的乙草稿','Creating another analysis saved transient target over old draft');
    checks.push('New analysis supersedes a pending selection and restores normal input without damaging the previous target draft');

    await select(a);release=await hold(b);const access=await api('memory/access','POST',{});await useMemoryKey(access.key);release();window.fetch=realFetch;await new Promise(resolve=>setTimeout(resolve,100));
    assert(!$('conversation-id').value&&!$('conversation-message').value&&!$('conversation-message').readOnly&&!$('task-form').inert&&!document.querySelector('.analysis-composer-controls').inert,'Identity switch retained old input or loading lock');
    checks.push('Actual access-key change clears pending selection, old draft content and all input locks');
    document.body.dataset.desktopSelectionTest=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopSelectionTest=JSON.stringify({checks,error:error.stack});}finally{window.fetch=realFetch;for(const release of releases)release();}
})();
