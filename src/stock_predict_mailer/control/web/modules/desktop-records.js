/* Task records with stable pagination, an owner-scoped detail and a separate archive view. */
window.DesktopRecords = (() => {
  const host=$('record-list'),cache=new Map(),dates=new Map(),headings=new Map();
  let stage='idle',epoch=0,counts=null,filterTimer;
  let tab='tasks', selected=null, lastRow=null;
  const scrolls={tasks:0, forecasts:0};
  const detailHost=$('record-detail'), taskPanel=$('task-records'), archivePanel=$('forecast-records');
  const viewing=()=>document.body.dataset.view==='records';
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
  const matchesState=task=>recordFilter==='all'||task.status.state===recordFilter||
    recordFilter==='active'&&['submitted','working'].includes(task.status.state);
  function render(){
    const shown=[],ids=new Set(),timestamps=new Set();
    for(const task of records){
      const brief=taskBrief(task),meta=task.metadata,flow=meta?.workflow?.flow;
      ids.add(task.id);timestamps.add(task.status.timestamp||'');
      if(!matchesState(task))continue;
      const signature=JSON.stringify([task.status,brief,meta?.error,taskMode(task),meta?.request?.name,flow?.name,flow?.revision,meta?.workflow?.version]);
      let entry=cache.get(task.id);
      if(!entry){entry={node:recordRow(task)};cache.set(task.id,entry);}
      else if(entry.signature!==signature){const fresh=recordRow(task);entry.node.replaceChildren(...fresh.childNodes);Object.assign(entry.node.dataset,fresh.dataset);}
      entry.signature=signature;entry.node.onclick=()=>openDetail(task,entry.node);
      shown.push(entry.node);
    }
    for(const[id]of cache)if(!ids.has(id))cache.delete(id);
    for(const[timestamp]of dates)if(!timestamps.has(timestamp))dates.delete(timestamp);
    for(const chip of $('record-chips').querySelectorAll('[data-filter]')){
      const key=chip.dataset.filter,selected=key===recordFilter;
      put(chip, counts ? `${RECORD_FILTER[key]} ${counts[key]??0}` : RECORD_FILTER[key]);
      chip.classList.toggle('active',selected);chip.classList.toggle('is-empty',counts?.[key]===0);
      chip.setAttribute('aria-pressed',String(selected));
    }
    const nodes=[],usedHeadings=new Set();let prior='',index=0;
    const order=[...shown].sort((a,b)=>(Date.parse(b.dataset.recordedAt)||0)-(Date.parse(a.dataset.recordedAt)||0));
    for(const row of order){const label=dateLabel(row.dataset.recordedAt);if(label&&label!==prior){const key=index+++'|'+label;usedHeadings.add(key);if(!headings.has(key)){const heading=document.createElement('h3');heading.className='desktop-record-date';heading.textContent=label;headings.set(key,heading);}nodes.push(headings.get(key));}nodes.push(row);prior=label;}
    for(const[key]of headings)if(!usedHeadings.has(key))headings.delete(key);
    if(!shown.length){
      const filtered=Boolean(recordQuery||recordFilter!=='all'||$('record-mode').value!=='all');
      const empty=document.createElement('p');empty.className='empty';
      empty.textContent=stage==='loading'?'正在读取任务记录…':stage==='failed'?'本次记录尚未读取成功，请重试。':
        filtered?'没有匹配的任务。可调整搜索词或筛选条件。':'暂无任务记录。';
      nodes.push(empty);
      if(!filtered&&!recordCursor&&!['loading','failed'].includes(stage))
        nodes.push(action('开始分析',()=>showView('analysis')));
    }
    reconcile(nodes);
    if(tab==='tasks')put($('record-count'),counts?`${counts[recordFilter]??0} 条匹配 · 已载入 ${shown.length} 条`:'尚未读取');
    $('record-more-wrap').hidden=!recordCursor;
  }
  const merge=(existing,fresh,prepend)=>{const incoming=new Map(fresh.map(task=>[task.id,task]));if(prepend)return [...incoming.values(),...existing.filter(task=>!incoming.has(task.id))];const known=new Set(existing.map(task=>task.id));return [...existing.map(task=>incoming.get(task.id)||task),...[...incoming.values()].filter(task=>!known.has(task.id))];};
  async function page({existing,fresh,cursor,pageCursor,reset,key}){
    if(reset&&pageCursor==null)return {items:fresh,cursor:null,warning:''};
    const known=new Set(existing.map(task=>task.id)),overlap=fresh.some(task=>known.has(task.id));
    let items=merge(existing,fresh,reset),next=reset&&existing.length&&(overlap||pageCursor==null)?cursor:pageCursor,failures=0;
    if(reset){const latest=new Set(fresh.map(task=>task.id)),older=items.filter(task=>!latest.has(task.id)&&recordGroup(task.status.state)==='active'),updates=[];
      for(let index=0;index<older.length;index+=4){const results=await Promise.allSettled(older.slice(index,index+4).map(task=>api('tasks/'+encodeURIComponent(task.id),'GET',undefined,undefined,{key,mode:taskMode(task)})));for(const result of results)if(result.status==='fulfilled')updates.push(result.value);else failures++;}
      items=merge(items,updates,false);
    }
    return {items:items.filter(matchesState),cursor:next,warning:failures?`${failures} 条较早的进行中记录未更新；保留原状态，可重新读取。`:''};
  }
  function loading(){
    clearTimeout(filterTimer);
    receipt('loading',records.length?`正在更新记录，保留当前已加载的 ${records.length} 条…`:'正在读取任务记录…');
    if(tab==='tasks')$('record-refresh').disabled=true;
    $('record-more').disabled=true;
  }
  function filterChanged(delay=0){
    ++epoch;clearTimeout(filterTimer);clearTimeout(recordTimer);
    records=[];recordCursor=null;recordLoaded=recordBusy=false;counts=null;
    loading();render();
    if(delay)filterTimer=setTimeout(()=>loadRecords(true),delay);else loadRecords(true);
  }
  function remember(){ if(selected&&tab==='tasks')selected.scroll=scrollY;else scrolls[tab]=scrollY;clearTimeout(recordTimer); }
  function restoreScroll(){const y=tab==='tasks'&&selected?selected.scroll:scrolls[tab];requestAnimationFrame(()=>{if(viewing())scrollTo(0,y||0);});}
  function selectTab(value,restore=true){
    if(value!==tab){remember();tab=value;}
    taskPanel.hidden=tab!=='tasks'||Boolean(selected);
    detailHost.hidden=tab!=='tasks'||!selected;
    archivePanel.hidden=tab!=='forecasts';
    for(const control of $('records-tabs').querySelectorAll('button'))control.setAttribute('aria-pressed',String(control.dataset.recordTab===tab));
    $('record-refresh').disabled=tab==='tasks'?recordBusy:false;
    if(tab==='forecasts')window.ForecastUI?.enter();
    else if(!recordLoaded)loadRecords(true);else{renderRecords();schedule();}
    if(restore)restoreScroll();
  }
  function view(restore){selectTab(tab,restore);}
  function schedule(){
    clearTimeout(recordTimer);
    if(viewing()&&tab==='tasks'&&(records.some(task=>recordGroup(task.status.state)==='active')|| selected && recordGroup(selected.task.status.state)==='active'))
      recordTimer=setTimeout(()=>{ if(viewing()&&tab==='tasks')refresh(); },3000);
  }
  function refresh(){
    if(tab==='forecasts')return window.ForecastUI?.refresh();
    if(selected)loadDetail(selected);
    return loadRecords(true);
  }
  function closeDetail(){
    const focus=lastRow;lastRow=null;selected=null;detailHost.replaceChildren();
    selectTab('tasks');
    focus?.focus({preventScroll:true});
  }
  function openDetail(task,row){
    if(!viewing())showView('records');
    if(!selected&&tab==='tasks')scrolls.tasks=scrollY;
    lastRow=row;
    const entry={task,ctx:{...AnalysisMode.capture(),mode:taskMode(task)},events:new Map(),more:false,scroll:0};
    selected=entry;selectTab('tasks',false);
    drawDetail(entry,'正在读取任务详情…');
    detailHost.focus({preventScroll:true});scrollTo(0,0);loadDetail(entry);
  }
  const owns=entry=>entry===selected&&entry.ctx.key===memoryKey;
  const request=(entry,suffix='',method='GET',body)=>api('tasks/'+encodeURIComponent(entry.task.id)+suffix,method,body,undefined,entry.ctx);
  async function loadDetail(entry,append=false){
    if(entry.loading||!owns(entry))return;
    const read=entry.loading=Symbol();
    const current=()=>owns(entry)&&entry.loading===read;
    const after=entry.cursor||0;
    try{
      const result=await Promise.allSettled([request(entry),request(entry,'/events?after='+after)]);
      if(!current())return;
      const [value,history]=result;
      if(value.status==='fulfilled')entry.task=value.value;
      let message=value.status==='rejected'?'任务读取失败 · '+value.reason.message:'';
      if(history.status==='fulfilled'){
        for(const event of history.value.events){entry.events.set(event.seq,event);entry.cursor=event.seq;}
        entry.more=history.value.events.length===100;
      } else message += (message?' · ':'')+'执行过程读取失败 · '+history.reason.message;
      if(entry.task.status.state==='completed'&&entry.task.artifacts?.length){
        try{entry.mail=await request(entry,'/mail');}
        catch(error){message+=(message?' · ':'')+'邮件回执读取失败 · '+error.message;}
      }
      if(current()){drawDetail(entry,message);if(append)detailHost.querySelector('.record-events')?.focus({preventScroll:true});schedule();}
    } finally {if(entry.loading===read)entry.loading=null;}
  }
  function drawDetail(entry,message=''){
    const task=entry.task, info=taskBrief(task), mode=entry.ctx.mode, state=task.status.state, workflow=task.metadata?.workflow, flow=workflow?.flow;
    const result=task.artifacts?.[0]?.parts?.[0]?.data;
    const header=document.createElement('div');header.className='section-head record-detail-head';
    header.append(action('返回任务列表',closeDetail));text(header,'h2',info.subject||task.metadata?.request?.name||flow?.name||'分析任务');
    text(header,'span',TASK_STATE[state]||state,'tag');
    detailHost.replaceChildren(header);
    const meta=document.createElement('dl');meta.className='kv';detailHost.append(meta);
    for(const [label,value] of [['分析模式',RECORD_MODE[mode]],['更新时间',fmt(task.status.timestamp)],['任务 ID',task.id],['流程',flow?.name],['执行版本',flow?.revision||workflow?.version]]){
      if(value){text(meta,'dt',label);text(meta,'dd',value);}
    }
    if(task.metadata?.error){text(detailHost,'h3','失败原因');text(detailHost,'p',[task.metadata.error.code,task.metadata.error.message].filter(Boolean).join(' · '),'warn');}
    const operations=document.createElement('div');operations.className='actions mt-16';detailHost.append(operations);
    if(result?.analysis)operations.append(action('查看报告与证据',()=>window.WorkflowChat?.showTaskReport(task.id,entry.ctx,()=>owns(entry)&&viewing())));
    if(result?.analysis?.forecast_evidence)operations.append(action('查看预测归档',()=>window.ForecastUI?.openTask(task.id)));
    if(flow?.id||info.conversation_id||workflow||result?.analysis)
      operations.append(action(flow?.id?'打开流程运行':info.conversation_id?'打开分析会话':workflow?'打开画布运行':'打开分析记录',()=>openRecord(task)));
    if(mode!=='legacy'&&['submitted','working'].includes(state))operations.append(action('取消运行',()=>mutate(entry,false)));
    if(mode!=='legacy'&&['completed','failed','canceled'].includes(state))operations.append(action('删除记录',()=>mutate(entry,true)));
    const feedback=text(detailHost,'p',message,'hint');feedback.role='status';
    if(message.includes('失败'))operations.append(action('重新读取详情',()=>loadDetail(entry)));
    const mail=entry.mail||info.mail;
    text(detailHost,'h3','邮件回执','mt-16');
    text(detailHost,'p',mail?[MAIL_STATE[mail.status]||mail.status,mail.id,mail.error?.message].filter(Boolean).join(' · '):info.notify?'当前没有投递回执。':'本轮未请求邮件。','hint');
    text(detailHost,'h3','执行过程','mt-16');
    const timeline=document.createElement('ol');timeline.className='record-events';timeline.tabIndex=-1;detailHost.append(timeline);
    for(const event of entry.events.values()){
      const item=document.createElement('li');timeline.append(item);
      text(item,'time',shortTime(event.timestamp),'hint');
      text(item,'strong',event.label||event.step||event.kind);
      if(event.status)text(item,'span',progressStates[event.status]||MAIL_STATE[event.status]||(event.status==='needs_input'?'等待用户处理':event.status),'tag');
      const details=[event.code, ...(Array.isArray(event.summary)?event.summary:[]), event.duration_ms!=null?event.duration_ms+' ms':''].filter(Boolean);
      if(details.length)text(item,'p',details.join(' · '),'hint');
    }
    if(!entry.events.size)text(detailHost,'p','暂无执行事件。','hint');
    if(entry.more)detailHost.append(action('载入更多事件',()=>loadDetail(entry,true)));
    if(result?.workflow_outputs)for(const output of result.workflow_outputs){
      text(detailHost,'h3',output.label||'流程输出','mt-16');
      text(detailHost,'pre',typeof output.value==='string'?output.value:JSON.stringify(output.value,null,2),'record-output');
    }
  }
  async function mutate(entry,remove){
    if(entry.mutating||!owns(entry)||remove&&!confirm('删除这条任务及对应的进度和报告？'))return;
    entry.mutating=true;
    try{
      const value=await request(entry,remove?'':'/cancel',remove?'DELETE':'POST',remove?undefined:{});
      if(entry.ctx.key!==memoryKey)return;
      if(remove){
        await window.Workbench?.removedTask(entry.task.id,entry.ctx);
        renderRecords();if(owns(entry))closeDetail();
      }else{
        records=records.map(task=>task.id===value.id?value:task);
        renderRecords();
        if(owns(entry)){entry.loading=null;entry.task=value;drawDetail(entry,'已取消运行。');await loadDetail(entry);}
        if(viewing()&&tab==='tasks')loadRecords(true);
      }
    }catch(error){if(owns(entry))drawDetail(entry,error.message+'。可刷新详情核对当前状态后重试。');}
    finally{entry.mutating=false;}
  }
  $('record-mode').onchange=()=>filterChanged();
  $('records-tabs').onclick=event=>{const value=event.target.closest('[data-record-tab]')?.dataset.recordTab;if(value)selectTab(value);};
  function identityChanged(){
    ++epoch;clearTimeout(filterTimer);clearTimeout(recordTimer);recordBusy=false;recordLoaded=false;recordCursor=null;
    records=[];recordFilter='all';recordQuery='';counts=null;
    $('record-mode').value='all';$('record-query').value='';cache.clear();dates.clear();headings.clear();deletedRecords.clear();
    selected=lastRow=null;scrolls.tasks=scrolls.forecasts=0;detailHost.hidden=true;detailHost.replaceChildren();
    taskPanel.hidden=tab!=='tasks';host.replaceChildren();$('record-count').textContent='尚未读取';$('record-more-wrap').hidden=true;
    receipt('idle');$('record-refresh').disabled=$('record-more').disabled=false;
  }
  return {active:()=>true,revision:()=>epoch,identityChanged,render,page,selectTab,view,remember,openDetail,refresh,schedule,filterChanged,
    returnToTasks(){if(selected)closeDetail();else selectTab('tasks');},
    forecastCount(count){if(tab==='forecasts')put($('record-count'),count);},
    loading,
    loaded(warning,values){counts=values;receipt(warning?'partial':'ready',warning||'记录已更新。');},
    failed(error){receipt('failed','记录读取失败：'+error+'。当前记录和筛选已保留。');render();},
    finished(){if(tab==='tasks')$('record-refresh').disabled=false;$('record-more').disabled=false;}
  };
})();
