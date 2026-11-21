/* Declared plugins as cards. Read-only by design: this surface reports what the
   server declared and never switches a source, edits market.json or runs a
   plugin. The professional-mode board lets the owner drag cards around; only the
   layout is stored, on this machine. */
globalThis.PonyPluginBoard=(()=>{
  const KEY='stock_predict_mailer.plugin.board.v1';
  const KINDS={market_source:'行情源',report_renderer:'报告渲染',notifier:'通知渠道'};
  let cache=null,pending=null,observer=null,hallMounted=false,focusMounted=false;

  async function load(force){
    if(cache&&!force)return cache;
    if(pending)return pending;
    pending=api('plugins').then(body=>{cache=body;return body;}).finally(()=>{pending=null;});
    return pending;
  }
  const saved=()=>{try{return JSON.parse(localStorage.getItem(KEY))||{};}catch{return{};}};
  const remember=map=>{try{localStorage.setItem(KEY,JSON.stringify(map));}catch{}};

  function card(plugin){
    const node=document.createElement('article');
    node.className='plugin-card';
    node.dataset.pluginId=plugin.id;
    node.dataset.state=plugin.available?'ok':'warn';
    node.innerHTML='<header><span class="plugin-dot" aria-hidden="true"></span><strong></strong><code></code></header>'+
      '<p class="plugin-kind"></p><ul class="plugin-caps"></ul><p class="plugin-meta"></p>';
    node.querySelector('strong').textContent=plugin.label;
    node.querySelector('code').textContent=plugin.id;
    node.querySelector('.plugin-kind').textContent=`${KINDS[plugin.kind]||plugin.kind}${plugin.default?' · 默认链':''}`;
    const caps=node.querySelector('.plugin-caps');
    for(const capability of plugin.capabilities){const item=document.createElement('li');item.textContent=capability;caps.append(item);}
    const missing=plugin.requires.length?` · 需 ${plugin.requires.join(', ')}`:'';
    node.querySelector('.plugin-meta').textContent=`${plugin.available?'可用':'缺依赖'}${missing} · 模块 ${plugin.module_digest.slice(0,8)}`;
    node.title=`${plugin.id}\n${plugin.module}`;
    return node;
  }

  function head(body,draggable){
    const line=document.createElement('div');
    line.className='plugin-board-head';
    line.innerHTML='<strong>插件</strong><span></span><button type="button">刷新</button>';
    const chain=body.source_chain.join(' → ')||'—';
    const text=body.problems.length?body.problems.join('；'):`默认链 ${chain} · 日线 ${body.candles_from||'无'}`;
    line.querySelector('span').textContent=text;
    line.dataset.state=body.ok?'ok':'warn';
    line.querySelector('button').onclick=()=>load(true).then(next=>fill(line.parentElement,next,draggable)).catch(()=>{});
    return line;
  }

  function fill(container,body,draggable){
    container.replaceChildren();
    container.dataset.draggable=String(Boolean(draggable));
    container.append(head(body,draggable));
    const grid=document.createElement('div');
    grid.className='plugin-cards';
    container.append(grid);
    const spots=draggable?saved():{};
    body.plugins.forEach((plugin,index)=>{
      const node=card(plugin);
      grid.append(node);
      if(!draggable)return;
      const fallback={x:12+(index%3)*232,y:12+Math.floor(index/3)*128};
      const spot=spots[plugin.id]||fallback;
      node.style.left=spot.x+'px';
      node.style.top=spot.y+'px';
      node.addEventListener('pointerdown',event=>drag(event,node,plugin.id));
    });
    container.dataset.state='ready';
  }

  function drag(event,node,id){
    if(event.button!==0||!node.parentElement)return;
    event.preventDefault();
    const origin={x:event.clientX,y:event.clientY,left:parseFloat(node.style.left)||0,top:parseFloat(node.style.top)||0};
    node.setPointerCapture(event.pointerId);
    node.dataset.dragging='true';
    const move=step=>{
      node.style.left=Math.max(0,origin.left+step.clientX-origin.x)+'px';
      node.style.top=Math.max(0,origin.top+step.clientY-origin.y)+'px';
    };
    const stop=()=>{
      node.removeEventListener('pointermove',move);
      node.removeEventListener('pointerup',stop);
      node.removeEventListener('pointercancel',stop);
      delete node.dataset.dragging;
      const map=saved();
      map[id]={x:parseFloat(node.style.left)||0,y:parseFloat(node.style.top)||0};
      remember(map);
    };
    node.addEventListener('pointermove',move);
    node.addEventListener('pointerup',stop);
    node.addEventListener('pointercancel',stop);
  }

  function mountHall(wall){
    const panel=document.createElement('section');
    panel.className='plugin-board plugin-hall';
    panel.setAttribute('aria-label','插件状态');
    panel.innerHTML='<p class="plugin-board-hint">只读展示服务端声明的插件；切换数据源请改 market.json。</p>';
    wall.parentElement.insertBefore(panel,wall.nextSibling);
    const follow=()=>{panel.inert=document.body.classList.contains('desktop-focus-view');};
    new MutationObserver(follow).observe(document.body,{attributes:true,attributeFilter:['class']});
    follow();
    load().then(body=>fill(panel,body,false)).catch(()=>panel.remove());
  }

  function mountFocus(focus){
    const toolbar=focus.querySelector('.desktop-flow-toolbar-actions');
    if(!toolbar)return;
    const button=document.createElement('button');
    button.type='button';
    button.textContent='插件';
    button.setAttribute('aria-label','打开插件画布');
    toolbar.prepend(button);
    const dialog=document.createElement('dialog');
    dialog.className='plugin-dialog';
    dialog.innerHTML='<div class="plugin-dialog-head"><strong>插件画布</strong><button type="button" data-close>关闭</button></div>'+
      '<p class="hint">拖动卡片自行排布，位置只存在本机。这里只展示声明：不切换数据源，也不执行插件。</p>'+
      '<div class="plugin-board" id="plugin-board-focus"></div>';
    document.body.append(dialog);
    const close=dialog.querySelector('[data-close]');
    close.onclick=()=>dialog.close();
    dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
    button.onclick=()=>{
      dialog.showModal();
      const board=dialog.querySelector('.plugin-board');
      load().then(body=>fill(board,body,true)).catch(error=>{
        board.replaceChildren();
        const note=document.createElement('p');
        note.className='plugin-board-hint';
        note.textContent=`插件状态读取失败：${error.message}`;
        board.append(note);
      });
    };
  }

  function install(){
    if(!hallMounted){
      const wall=document.querySelector('.market-wall');
      if(wall){mountHall(wall);hallMounted=true;}
    }
    if(!focusMounted&&matchMedia('(min-width: 761px)').matches){
      const focus=document.getElementById('desktop-focus');
      if(focus&&focus.querySelector('.desktop-flow-toolbar-actions')){mountFocus(focus);focusMounted=true;}
    }
    if(hallMounted&&(focusMounted||!matchMedia('(min-width: 761px)').matches)&&observer){observer.disconnect();observer=null;}
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});
  install();
  observer=new MutationObserver(()=>{try{install();}catch{}});
  observer.observe(document.body,{childList:true,subtree:true});
  return{install};
})();
