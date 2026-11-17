/* Disposable fixture with FakeCleaner only; never use on a real workspace. */
(async () => {
  const $ = id => document.getElementById(id), checks = [], realFetch = window.fetch, realConfirm = window.confirm;
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const wait = async (fn, label) => { for (let i=0;i<160;i++) { if(fn())return; await new Promise(resolve=>setTimeout(resolve,100)); } throw Error('Timeout: '+label); };
  const set = (id,value) => { $(id).value=value; $(id).dispatchEvent(new Event('input',{bubbles:true})); };
  const relation='自2026年1月1日起，乙公司是甲公司的供应商。', logical='桌面知识验收-'+Date.now();
  let previousKey;
  try {
    assert(innerWidth>760,'Use desktop viewport');
    $('new-analysis').click(); await wait(()=>!$('new-analysis').disabled && $('conversation-id').value,'conversation'); previousKey=memoryKey;
    await api('knowledge/cleaner/config','PUT',{provider:'ollama',base_url:'http://127.0.0.1:11434',model:'fixture-cleaner',version:'test-v1'});
    document.querySelector('[data-view="knowledge"]').click(); await wait(()=>!$('knowledge-body').hidden,'knowledge access');
    await upload(relation,'phase2b-v1.txt');
    const first=await waitDocument('review');
    await window.KnowledgeUI.filter('review');
    assert($('knowledge-list').querySelector(`[data-document-id="${first.id}"]`),'Server review filter omitted document');
    assert(document.querySelector('[data-knowledge-status="review"]').getAttribute('aria-pressed')==='true','Status choice not reflected');
    set('desktop-knowledge-query','not-a-matching-name');
    assert($('knowledge-list').querySelector('.document-row').hidden && !$('desktop-knowledge-no-match').hidden,'Loaded-name filter not applied');
    set('desktop-knowledge-query','');
    checks.push('real upload queues for review; server state filter and loaded-name scope are explicit');

    // Inject one invalid candidate into the UI response only; approval still uses original digest.
    window.fetch=async(url,options)=>{
      const response=await realFetch(url,options);
      if(String(url).endsWith(`/documents/${first.id}/review`) && (!options?.method || options.method==='GET')) {
        const data=await response.json(); data.extraction.candidates.push({...data.extraction.candidates[0],id:'invalid-ui-boundary',validated:false,validation_errors:['合成校验失败样本']});
        return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
      }
      return response;
    };
    await window.KnowledgeUI.open(first.id); window.fetch=realFetch;
    const group=$('knowledge-detail').querySelector('.review-group');
    assert(group.querySelector('input[value="invalid-ui-boundary"]').disabled,'Invalid candidate became approvable');
    const valid=group.querySelector('input:not(:disabled)'); document.querySelector('.desktop-review-jump').click();
    assert(document.activeElement===valid && !valid.checked,'Review shortcut must focus without approving/selecting'); valid.click();
    assert($('desktop-review-selection').textContent.includes('已选 1 条'),'Selection summary not updated');
    document.querySelector('.desktop-compare-toggle').click();
    assert($('knowledge-detail').classList.contains('desktop-source-compare') && group.querySelector('details').open,'Source comparison not available');
    window.confirm=()=>true;
    [...group.querySelectorAll('button')].find(node=>node.textContent==='批准所选并继续处理').click();
    await waitDocument('ready');
    window.confirm=realConfirm;
    checks.push('invalid candidates remain disabled; selection/source comparison and real approval publish correctly');

    await upload(relation+'\n第二版合成备注。','phase2b-v2.txt');
    const second=await waitDocument('review');
    assert(second.id!==first.id,'Version not created');
    await window.KnowledgeUI.open(second.id);
    assert($('knowledge-detail').querySelectorAll('[data-version-id]').length>=2,'Version navigation missing');
    document.querySelector(`[data-version-id="${first.id}"]`).click();
    await wait(()=>$('knowledge-detail').querySelector('.desktop-document-workflow')?.dataset.documentId===first.id,'version selection');
    let release;
    window.fetch=(url,...args)=>String(url).endsWith('/documents/'+first.id)?new Promise((resolve,reject)=>realFetch(url,...args).then(response=>{release=()=>resolve(response);},reject)):realFetch(url,...args);
    const old=window.KnowledgeUI.open(first.id); await wait(()=>release,'held version response');
    await window.KnowledgeUI.open(second.id); release(); await old; window.fetch=realFetch;
    assert($('knowledge-detail').querySelector('.desktop-document-workflow').dataset.documentId===second.id,'Late old version overwrote selection');
    checks.push('actual versions are navigable; slower old version cannot overwrite newer selection');

    document.querySelector('[data-kb-tab="search"]').click(); set('knowledge-query','供应商');
    $('knowledge-search').requestSubmit(); await wait(()=>!$('knowledge-search').querySelector('[type="submit"]').disabled,'search');
    assert($('knowledge-results').textContent.includes('供应商'),'Published source not searchable');
    let releaseSearch;
    window.fetch=(url,...args)=>String(url).endsWith('/knowledge/search')?new Promise((resolve,reject)=>realFetch(url,...args).then(response=>{releaseSearch=()=>resolve(response);},reject)):realFetch(url,...args);
    $('knowledge-search').requestSubmit(); await wait(()=>releaseSearch,'held search'); set('knowledge-query','新的检索条件'); releaseSearch();
    await wait(()=>!$('knowledge-search').querySelector('[type="submit"]').disabled,'search completion'); window.fetch=realFetch;
    assert(document.querySelector('.desktop-search-state').textContent.includes('上次结果'),'Changed query response presented as current');
    checks.push('published evidence search works and changed conditions keep stale results labelled');

    set('knowledge-query','供应商');
    window.fetch=(url,...args)=>String(url).endsWith('/knowledge/search')?Promise.resolve(new Response(JSON.stringify({error:{code:'UI_FIXTURE_UNAVAILABLE',message:'synthetic retrieval failure'}}),{status:503,headers:{'Content-Type':'application/json'}})):realFetch(url,...args);
    $('knowledge-search').requestSubmit(); await wait(()=>!$('knowledge-search').querySelector('[type="submit"]').disabled,'search error');
    assert(document.querySelector('.desktop-search-state').textContent.includes('读取失败') && $('knowledge-query').value==='供应商','Search failure lost context');
    window.fetch=realFetch; $('knowledge-search').requestSubmit(); await wait(()=>!$('knowledge-search').querySelector('[type="submit"]').disabled,'search retry');
    assert(document.querySelector('.desktop-search-state').textContent.includes('结果已更新'),'Search retry did not recover');
    checks.push('search loading/error remain explicit, inputs preserved and retry recovers');

    const other=await api('memory/access','POST',{}); await useMemoryKey(other.key);
    assert(!$('knowledge-detail').querySelector('.desktop-document-added') && !$('knowledge-list').children.length,'Identity change retained private detail/list');
    assert(!$('desktop-knowledge-query').value && !document.querySelector('.desktop-search-state').textContent,'Identity change retained query metadata');
    await useMemoryKey(previousKey); previousKey=null;
    checks.push('identity switch clears new private metadata and restores independently');
    document.body.dataset.desktopLibraryCheck=JSON.stringify({checks});
  } finally { window.fetch=realFetch; window.confirm=realConfirm; }
  async function waitDocument(status) {
    let found;
    for(let i=0;i<100;i++) { const data=await api('knowledge/documents?limit=50'); found=data.items.find(item=>item.logical===logical && item.status===status); if(found)return found; await new Promise(resolve=>setTimeout(resolve,100)); }
    throw Error('Document did not reach '+status);
  }
  async function upload(content,name) {
    document.querySelector('[data-kb-tab="documents"]').click();
    const transfer=new DataTransfer(); transfer.items.add(new File([content],name,{type:'text/plain'})); $('knowledge-file').files=transfer.files;
    set('knowledge-logical',logical); set('knowledge-date','2026-01-01'); set('knowledge-available','2026-01-02'); set('knowledge-source','合成验收来源');
    $('knowledge-upload').requestSubmit(); await wait(()=>!$('knowledge-upload').querySelector('[type="submit"]').disabled,'upload');
  }
})().catch(error=>{document.body.dataset.desktopLibraryCheck=JSON.stringify({error:error.message});});
