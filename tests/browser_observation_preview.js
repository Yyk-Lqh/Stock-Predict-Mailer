/* Run through gstack browse against the disposable --forecast-fixtures server. */
(async () => {
  const $=id=>document.getElementById(id), checks=[];
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async fn=>{for(let i=0;i<150;i++){if(fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('timed out: '+String(fn));};
  const set=(id,value)=>{$(id).value=value;$(id).dispatchEvent(new Event('input',{bubbles:true}));};
  const run=async()=>{$('observation-preview').click();await wait(()=>!$('observation-preview').disabled);};
  const real=window.fetch;
  try {
    await wait(()=>window.ObservationPreview && window.ForecastUI);
    document.querySelector('[data-view=records]').click();await wait(()=>!$('forecast-refresh').disabled);
    $('forecast-state').value='due';$('forecast-state').dispatchEvent(new Event('change'));await wait(()=>!$('forecast-refresh').disabled);
    $('forecast-list').querySelector('button').click();await wait(()=>$('observation-content'));
    document.querySelector('.observation-preview').open=true;
    assert($('observation-preview').checkVisibility(),'preview action hidden');
    const view=await api('tasks/browser-due/forecast'), r=view.record, d=r.definition;
    const observation={schema_version:'1',subject:r.prediction.subject,metric:d.metric,unit:d.unit,value:112,
      observed_at:d.target_at,available_at:d.target_at,source:'<img src=x onerror=alert(1)> preview-only-sensitive-marker',synthetic:true};
    set('observation-content',JSON.stringify(observation));await run();
    assert($('observation-result').textContent.includes('绝对误差：2 CNY'),'ready preview missing score/units');
    assert($('observation-result').textContent.includes('未保存'),'preview appears persisted');
    assert(!$('observation-result').querySelector('img'),'untrusted source executed');
    assert($('observation-result').textContent.includes('<img src=x'),'source text not preserved');
    assert((await api('tasks/browser-due/forecast')).evaluations.length===0,'preview wrote receipt');
    checks.push('visible action, matched JSON score, safe source and no persisted receipt');
    set('observation-content',JSON.stringify({...observation,unit:'USD'}));
    assert($('observation-result').hidden,'editing left old score visible');await run();
    assert($('observation-status').textContent.includes('预览失败'),'mismatched unit not reported');
    assert($('observation-content').value.includes('USD'),'error erased input');
    set('observation-content',JSON.stringify(observation));await run();
    assert(!$('observation-result').hidden,'correction failed to recover');checks.push('input invalidation, mismatch error and correction recovery');
    set('observation-as-of',new Date(Date.parse(d.target_at)-1).toISOString());await run();
    assert($('observation-result').textContent.includes('尚未到期，未评分')&&!$('observation-result').textContent.includes('绝对误差'),'cutoff gate scored future observation');
    set('observation-as-of','');set('observation-content',JSON.stringify({...observation,available_at:new Date(Date.now()+86400000).toISOString()}));await run();
    assert($('observation-result').textContent.includes('尚不可用，未评分')&&!$('observation-result').textContent.includes('绝对误差'),'unavailable data scored');checks.push('maturity and availability gates show no metrics');
    const header=['schema_version','subject','metric','unit','value','observed_at','available_at','source','synthetic'];
    const quote=value=>'"'+String(value).replaceAll('"','""')+'"';
    const csv='\ufeff'+header.join(',')+'\r\n'+header.map(k=>quote(observation[k])).join(',')+'\r\n';
    const transfer=new DataTransfer();transfer.items.add(new File([csv],'actual.csv',{type:'text/csv'}));
    $('observation-file').files=transfer.files;$('observation-file').dispatchEvent(new Event('change'));
    await wait(()=>$('observation-format').value==='csv');
    assert($('observation-content').value.charCodeAt(0)===0xfeff,'file BOM lost before hashing');await run();
    assert($('observation-result').textContent.includes('绝对误差：2 CNY'),'CSV not scored');
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(csv))),b=>b.toString(16).padStart(2,'0')).join('');
    assert($('observation-result').textContent.includes(digest),'import hash differs from file bytes');checks.push('CSV file import with BOM and exact input hash');
    set('observation-content',csv+header.map(k=>quote(observation[k])).join(',')+'\r\n');await run();
    assert($('observation-status').textContent.includes('预览失败')&&$('observation-result').hidden,'multi-row CSV selected a sample');checks.push('multiple rows rejected');
    const readBuffer=File.prototype.arrayBuffer;let releaseFile;
    try {
      File.prototype.arrayBuffer=function(){return this.name==='slow.csv'?new Promise(resolve=>{releaseFile=()=>readBuffer.call(this).then(resolve);}):readBuffer.call(this);};
      const slow=new DataTransfer();slow.items.add(new File([csv],'slow.csv',{type:'text/csv'}));
      $('observation-file').files=slow.files;$('observation-file').dispatchEvent(new Event('change'));await wait(()=>releaseFile);
      assert($('observation-preview').disabled,'preview enabled while replacement file is loading');
      set('observation-content','manual replacement');releaseFile();await wait(()=>!$('observation-preview').disabled);
      assert($('observation-content').value==='manual replacement','slow file overwrote edited raw text');checks.push('file loading disables preview and cannot overwrite newer edits');
    } finally {File.prototype.arrayBuffer=readBuffer;}
    set('observation-format','json');set('observation-content',JSON.stringify(observation));
    let held;
    window.fetch=(url,...args)=>String(url).includes('/forecast/preview')?new Promise((resolve,reject)=>real(url,...args).then(response=>{held=()=>resolve(response);},reject)):real(url,...args);
    $('observation-preview').click();await wait(()=>held);
    set('observation-content',JSON.stringify({...observation,value:113}));held();await wait(()=>!$('observation-preview').disabled);
    assert($('observation-result').hidden,'stale response restored old score');
    window.fetch=real;await run();assert($('observation-result').textContent.includes('绝对误差：3 CNY'),'new edit not used');checks.push('slow preview cannot overwrite edited observation');
    held=null;window.fetch=(url,...args)=>String(url).includes('/forecast/preview')?new Promise((resolve,reject)=>real(url,...args).then(response=>{held=()=>resolve(response);},reject)):real(url,...args);
    $('observation-preview').click();await wait(()=>held);
    await window.ForecastUI.openTask('browser-pending',false);held();await new Promise(resolve=>setTimeout(resolve,200));
    assert($('observation-result').hidden && $('observation-content').value==='','task switch leaked prior observation/score');
    window.fetch=real;window.ForecastUI.identityChanged();assert(!$('observation-content'),'identity change retained observation form');checks.push('task and identity change discard pending preview and imported text');
    await window.ForecastUI.openTask('browser-due',false);document.querySelector('.observation-preview').open=true;
    assert($('observation-content').value==='','reopening restored sensitive source');
    assert(!Object.values(localStorage).some(value=>value.includes('preview-only-sensitive-marker')),'observation saved in browser draft');checks.push('reopen is empty and no browser observation draft');
    document.body.dataset.observationCheck=JSON.stringify({checks,forecast_id:r.forecast_id});
  } finally {window.fetch=real;}
})().catch(error=>{document.body.dataset.observationCheck=JSON.stringify({error:error.message});});
