/* Desktop session catalog. Selection/drafts stay in the original workbench. */
window.DesktopSessions=(()=>{
  const desktop=matchMedia('(min-width: 761px)');if(!desktop.matches)return;
  const host=$('sidebar-sessions'),rows=new Map(),deleted=new Set();let owner=memoryKey,epoch=0,items=[],cursor=null,pending=null,control=null,appendPending=false,refreshQueued=false,choose=null;
  const tools=document.createElement('div');tools.className='desktop-session-tools';
  const label=document.createElement('label');label.className='field';label.textContent='查找已加载会话';const search=document.createElement('input');search.id='desktop-session-query';search.type='search';search.placeholder='按标的或会话名称筛选';label.append(search);
  const scope=document.createElement('p');scope.id='desktop-session-scope';scope.className='hint';
  const feedback=document.createElement('div');feedback.id='desktop-session-feedback';feedback.hidden=true;const status=document.createElement('p');status.className='hint';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const retry=document.createElement('button');retry.type='button';retry.className='btn tiny';retry.textContent='重新读取会话';retry.onclick=()=>load(false,choose);feedback.append(status,retry);tools.append(label,scope,feedback);host.before(tools);
  const noMatch=document.createElement('p');noMatch.className='hint';noMatch.id='desktop-session-no-match';noMatch.hidden=true;noMatch.textContent='当前已加载范围没有匹配会话。';host.after(noMatch);
  function receipt(state,message){feedback.hidden=!message;feedback.dataset.state=state;if(status.textContent!==message)status.textContent=message;retry.hidden=state!=='failed';}
  function busy(value){$('sessions-refresh').disabled=$('sessions-more').disabled=retry.disabled=value;feedback.setAttribute('aria-busy',String(value));}
  function paint(){
    const query=search.value.trim().toLocaleLowerCase(),selected=$('conversation-id').value,nodes=[],ids=new Set();let shown=0;
    for(const item of items){ids.add(item.id);let entry=rows.get(item.id);const title=item.subject||'新分析会话',signature=JSON.stringify([title,item.updated]);
      if(!entry){const node=document.createElement('button');node.type='button';node.className='session-item';node.dataset.conversation=item.id;node.onclick=()=>{const scope=AnalysisMode.capture();Promise.resolve(choose?.(item.id)).catch(error=>{if(AnalysisMode.current(scope))notice(error.message,true);});};entry={node};rows.set(item.id,entry);}
      if(entry.signature!==signature){entry.node.replaceChildren();const name=document.createElement('span');name.className='desktop-session-title';name.textContent=title;const time=document.createElement('time');time.className='hint';time.dateTime=item.updated||'';time.textContent='更新于 '+fmt(item.updated);entry.node.append(name,time);entry.signature=signature;entry.name=title.toLocaleLowerCase();}
      entry.node.classList.toggle('active',item.id===selected);if(item.id===selected)entry.node.setAttribute('aria-current','true');else entry.node.removeAttribute('aria-current');
      const hidden=!entry.name.includes(query);if(entry.node.hidden!==hidden)entry.node.hidden=hidden;if(!hidden)shown++;nodes.push(entry.node);
    }
    for(const[id]of rows)if(!ids.has(id))rows.delete(id);
    if(!items.length){const empty=document.createElement('p');empty.className='hint';empty.textContent=feedback.dataset.state==='failed'?'会话暂未读取成功，请重试。':feedback.dataset.state==='loading'?'正在读取会话…':'这里还没有会话，点击「新建分析」开始。';nodes.push(empty);}
    const focused=host.contains(document.activeElement)?document.activeElement:null;let position=host.firstChild;
    for(const node of nodes){if(position===node)position=position.nextSibling;else host.insertBefore(node,position);}while(position){const next=position.nextSibling;position.remove();position=next;}
    if(focused?.isConnected&&!focused.hidden&&document.activeElement!==focused)focused.focus({preventScroll:true});
    const text=`显示 ${shown} / ${items.length} 个已加载会话${cursor!=null?' · 仍有更早会话':''}`;if(scope.textContent!==text)scope.textContent=text;
    label.hidden=scope.hidden=!memoryKey;noMatch.hidden=!items.length||shown>0;$('sessions-more').hidden=cursor==null;
  }
  function identityChanged(){++epoch;control?.abort();owner=memoryKey;items=[];cursor=null;pending=null;control=null;refreshQueued=false;rows.clear();deleted.clear();search.value=AnalysisMode.read('session-filter')||'';receipt('idle','');busy(false);paint();}
  function load(append=false,select){
    if(select)choose=select;if(owner!==memoryKey)identityChanged();if(!memoryKey){paint();return Promise.resolve();}
    if(pending){if(!append&&appendPending)refreshQueued=true;return pending;}
    const generation=epoch,key=memoryKey,scope=AnalysisMode.capture(),existing=items,priorCursor=cursor,requestControl=new AbortController();control=requestControl;const signal=requestControl.signal;appendPending=append;let timeout=false;
    const expiry=setTimeout(()=>{timeout=true;requestControl.abort();},8000);
    receipt('loading',items.length?`正在更新，保留已加载的 ${items.length} 个会话…`:'正在读取会话…');busy(true);if(!items.length)paint();
    pending=(async()=>{
      try{
        const page=await api(`conversations?limit=30${append&&priorCursor!=null?'&before='+encodeURIComponent(priorCursor):''}`,'GET',undefined,signal,scope);
        if(generation!==epoch||key!==memoryKey||signal.aborted)return;
        const retained=existing.filter(item=>!deleted.has(item.id)),fresh=page.items.filter(item=>!deleted.has(item.id));
        const incoming=new Map(fresh.map(item=>[item.id,item])),known=new Set(retained.map(item=>item.id)),overlap=fresh.some(item=>known.has(item.id));
        items=append?[...retained.map(item=>incoming.get(item.id)||item),...[...incoming.values()].filter(item=>!known.has(item.id))]:[...incoming.values(),...retained.filter(item=>!incoming.has(item.id))];
        cursor=!append&&retained.length&&(overlap||page.next_before==null)?priorCursor:page.next_before;
        receipt('ready','');paint();
      }catch(error){if(generation!==epoch||key!==memoryKey||(signal.aborted&&!timeout))return;receipt('failed','会话读取失败：'+(timeout?'本次读取超过 8 秒':error.message)+'。当前列表与筛选已保留。');paint();}
      finally{clearTimeout(expiry);if(generation===epoch&&key===memoryKey){pending=null;control=null;busy(false);if(refreshQueued){refreshQueued=false;load(false,choose);}}}
    })();
    return pending;
  }
  search.oninput=()=>{AnalysisMode.write('session-filter',search.value);paint();};paint();
  return {active:()=>desktop.matches,load,identityChanged,removed(id){deleted.add(id);items=items.filter(item=>item.id!==id);rows.delete(id);paint();}};
})();
