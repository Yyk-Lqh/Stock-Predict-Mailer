/* Loaded desktop task records: stable rows, retained pagination and visible refresh receipts. */
window.DesktopRecords = (() => {
  const desktop=matchMedia('(min-width: 761px)');if(!desktop.matches)return;
  const host=$('record-list'),cache=new Map(),dates=new Map(),headings=new Map();
  let stage='idle',epoch=0;
  const feedback=document.createElement('div');feedback.id='desktop-record-feedback';feedback.className='desktop-record-feedback';feedback.hidden=true;
  const status=document.createElement('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const retry=document.createElement('button');retry.type='button';retry.className='btn tiny';retry.textContent='重新读取记录';retry.onclick=()=>loadRecords(true);retry.hidden=true;
  feedback.append(status,retry);host.before(feedback);
  const put=(node,value)=>{if(node.textContent!==value)node.textContent=value;};
  function receipt(value,text=''){stage=value;feedback.hidden=!text;feedback.dataset.state=value;put(status,text);retry.hidden=!['failed','partial'].includes(value);}
  function reconcile(nodes){
    const focused=host.contains(document.activeElement)?document.activeElement:null;
    let cursor=host.firstChild;
    for(const node of nodes){if(node===cursor)cursor=cursor.nextSibling;else host.insertBefore(node,cursor);}
    while(cursor){const next=cursor.nextSibling;cursor.remove();cursor=next;}
    if(focused?.isConnected&&document.activeElement!==focused)focused.focus({preventScroll:true});
  }
  function dateLabel(timestamp){if(!dates.has(timestamp)){const value=new Date(timestamp);dates.set(timestamp,Number.isFinite(value.getTime())?value.toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'}):'');}return dates.get(timestamp);}
  function render({items,filter,query,cursor}){
    if(!desktop.matches)return false;
    const counts={all:items.length,active:0,completed:0,failed:0},shown=[],ids=new Set(),timestamps=new Set();
    for(const task of items){
      const brief=taskBrief(task),group=recordGroup(task.status.state);counts[group]++;ids.add(task.id);timestamps.add(task.status.timestamp||'');
      const signature=JSON.stringify([task.status.state,task.status.timestamp,brief.subject,brief.direction,brief.horizon,brief.notify,brief.mail?.status,task.metadata?.error]);
      let entry=cache.get(task.id);
      if(!entry){entry={node:recordRow(task)};cache.set(task.id,entry);}
      else if(entry.signature!==signature){const fresh=recordRow(task);entry.node.replaceChildren(...fresh.childNodes);Object.assign(entry.node.dataset,fresh.dataset);}
      entry.signature=signature;entry.node.onclick=()=>openRecord(task);
      const hay=[brief.subject,task.metadata?.error?.code,MAIL_STATE[brief.mail?.status],TASK_STATE[task.status.state]].filter(Boolean).join(' ').toLowerCase();
      if((filter==='all'||group===filter)&&(!query||hay.includes(query)))shown.push(entry.node);
    }
    for(const[id]of cache)if(!ids.has(id))cache.delete(id);
    for(const[timestamp]of dates)if(!timestamps.has(timestamp))dates.delete(timestamp);
    for(const chip of $('record-chips').querySelectorAll('[data-filter]')){const key=chip.dataset.filter;put(chip,counts[key]?`${RECORD_FILTER[key]} ${counts[key]}`:RECORD_FILTER[key]);chip.classList.toggle('active',key===filter);chip.classList.toggle('is-empty',counts[key]===0);chip.setAttribute('aria-pressed',String(key===filter));}
    const nodes=[],usedHeadings=new Set();let prior='',index=0;
    for(const row of shown){const label=dateLabel(row.dataset.recordedAt);if(label&&label!==prior){const key=index+++'|'+label;usedHeadings.add(key);if(!headings.has(key)){const heading=document.createElement('h3');heading.className='desktop-record-date';heading.textContent=label+' · 状态记录时间';headings.set(key,heading);}nodes.push(headings.get(key));}nodes.push(row);prior=label;}
    for(const[key]of headings)if(!usedHeadings.has(key))headings.delete(key);
    if(!shown.length){const empty=document.createElement('p');empty.className='empty';empty.textContent=items.length?`已载入的 ${items.length} 条里没有匹配。${cursor?'可以继续载入更早的记录，或':''}清空筛选再看。`:stage==='loading'?'正在读取任务记录…':stage==='failed'?'本次记录尚未读取成功，请重试。':cursor?'本页尚无主任务记录，可以继续载入更早的记录。':'暂无任务记录。';nodes.push(empty);
      if(!items.length&&!cursor&&!['loading','failed'].includes(stage)){const go=document.createElement('button');go.type='button';go.className='btn tiny mt-12';go.textContent='开始分析';go.onclick=()=>showView('analysis');nodes.push(go);}}
    reconcile(nodes);
    put($('record-count'),!items.length?'还没有已加载任务':shown.length===items.length?`已载入 ${items.length} 条${cursor?' · 还有更早的':''}`:`筛出 ${shown.length} 条 · 已载入 ${items.length} 条`);
    $('record-more-wrap').hidden=!cursor;return true;
  }
  const merge=(existing,fresh,prepend)=>{const incoming=new Map(fresh.map(task=>[task.id,task]));if(prepend)return [...incoming.values(),...existing.filter(task=>!incoming.has(task.id))];const known=new Set(existing.map(task=>task.id));return [...existing.map(task=>incoming.get(task.id)||task),...[...incoming.values()].filter(task=>!known.has(task.id))];};
  async function page({existing,fresh,cursor,pageCursor,reset}){
    const known=new Set(existing.map(task=>task.id)),overlap=fresh.some(task=>known.has(task.id));
    let items=merge(existing,fresh,reset),next=reset&&existing.length&&(overlap||pageCursor==null)?cursor:pageCursor,failures=0;
    if(reset){const latest=new Set(fresh.map(task=>task.id)),older=items.filter(task=>!latest.has(task.id)&&recordGroup(task.status.state)==='active'),updates=[];
      for(let index=0;index<older.length;index+=4){const results=await Promise.allSettled(older.slice(index,index+4).map(task=>api('tasks/'+task.id)));for(const result of results)if(result.status==='fulfilled')updates.push(result.value);else failures++;}
      items=merge(items,updates,false);
    }
    return {items,cursor:next,warning:failures?`${failures} 条较早的进行中记录未更新；保留原状态，可重新读取。`:''};
  }
  function identityChanged(){++epoch;clearTimeout(recordTimer);recordBusy=false;recordLoaded=false;recordCursor=null;records=[];recordFilter='all';recordQuery='';$('record-query').value='';cache.clear();dates.clear();headings.clear();host.replaceChildren();$('record-count').textContent='尚未读取';$('record-more-wrap').hidden=true;receipt('idle');$('record-refresh').disabled=$('record-more').disabled=false;}
  return {active:()=>desktop.matches,revision:()=>epoch,identityChanged,render,page,
    loading(){receipt('loading',records.length?`正在更新记录，保留当前已加载的 ${records.length} 条…`:'正在读取任务记录…');$('record-refresh').disabled=$('record-more').disabled=true;},
    loaded(warning){receipt(warning?'partial':'ready',warning||'记录已更新。');},
    failed(error){receipt('failed','记录读取失败：'+error+'。当前记录和筛选已保留。');render({items:records,filter:recordFilter,query:recordQuery,cursor:recordCursor});},
    finished(){$('record-refresh').disabled=$('record-more').disabled=false;}
  };
})();
