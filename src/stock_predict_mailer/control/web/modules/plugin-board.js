/* Plugin cards and workspace-local GitHub imports for both console views. */
globalThis.PonyPluginBoard=(()=>{
  const KEY='stock_predict_mailer.plugin.board.v1';
  const KINDS={market_source:'行情源',report_renderer:'报告渲染',notifier:'通知渠道',exporter:'数据导出'};
  let cache=null,pending=null,observer=null,hallMounted=false,focusMounted=false;

  async function load(force){
    if(cache&&!force)return cache;
    if(pending)return pending;
    pending=api('plugins').then(body=>{cache=body;return body;}).finally(()=>{pending=null;});
    return pending;
  }
  const saved=()=>{try{return JSON.parse(localStorage.getItem(KEY))||{};}catch{return{};}};
  const remember=map=>{try{localStorage.setItem(KEY,JSON.stringify(map));}catch{}};

  function card(plugin,container){
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
    const meta=node.querySelector('.plugin-meta');
    if(plugin.github_url){
      const source=document.createElement('a');
      source.href=plugin.github_url;
      source.target='_blank';
      source.rel='noopener noreferrer';
      source.textContent='GitHub';
      source.title=plugin.github_url;
      const remove=document.createElement('button');
      remove.type='button';
      remove.textContent='移除';
      remove.setAttribute('aria-label',`移除插件 ${plugin.label}`);
      remove.onclick=()=>mutate(container,remove,`plugins/github/${encodeURIComponent(plugin.id)}`,'DELETE',undefined,'插件已移除');
      meta.append(source,` · ${plugin.manifest_sha256.slice(0,8)} `,remove);
    }else{
      const signature=plugin.module_digest?.slice(0,8)||'—';
      meta.textContent=`${plugin.available?'可用':'缺依赖'}${missing} · 模块 ${signature}`;
      node.title=`${plugin.id}\n${plugin.module}`;
    }
    return node;
  }

  async function mutate(container,button,path,method,body,success){
    let status=container.querySelector('[role="status"]');
    button.disabled=true;
    status.textContent=method==='POST'?'正在从 GitHub 获取插件…':'正在移除插件…';
    try{
      await api(path,method,body);
      status.textContent=success;
      await refresh();
      status=container.querySelector('[role="status"]');
      status.textContent=success;
    }catch(error){
      const message=status.textContent===success?`${success}，列表刷新失败`:'操作失败';
      status.textContent=`${message}。 ${error.message}`;
    }finally{
      button.disabled=false;
    }
  }

  async function refresh(){
    if(pending)await pending.catch(()=>{});
    const body=await load(true);
    document.querySelectorAll('.plugin-board[data-draggable]').forEach(board=>fill(board,body,board.dataset.draggable==='true'));
  }

  function githubForm(container){
    const details=document.createElement('details');
    details.className='plugin-github';
    details.innerHTML='<summary>从 GitHub 添加</summary><form>'+
      '<label>GitHub 仓库地址 <input name="url" type="url" required maxlength="256" placeholder="https://github.com/owner/repo"></label>'+
      '<button type="submit">添加插件</button></form>'+
      '<p class="plugin-board-hint">仓库默认分支的根目录需包含 stock-predict-mailer-plugin.json。</p>';
    const form=details.querySelector('form');
    form.onsubmit=event=>{
      event.preventDefault();
      mutate(container,form.querySelector('button'),'plugins/github','POST',{url:form.elements.url.value},'插件已添加');
    };
    return details;
  }

  function head(body,container){
    const line=document.createElement('div');
    line.className='plugin-board-head';
    line.innerHTML='<strong>插件</strong><span></span><button type="button">刷新</button>';
    const chain=body.source_chain.join(' → ')||'—';
    const text=body.problems.length?body.problems.join('；'):`默认链 ${chain} · 日线 ${body.candles_from||'无'}`;
    line.querySelector('span').textContent=text;
    line.dataset.state=body.ok?'ok':'warn';
    line.querySelector('button').onclick=()=>refresh().catch(error=>{
      container.querySelector('[role="status"]').textContent=`刷新失败。 ${error.message}`;
    });
    return line;
  }

  function fill(container,body,draggable){
    container.replaceChildren();
    container.dataset.draggable=String(Boolean(draggable));
    const status=document.createElement('p');
    status.className='plugin-feedback';
    status.setAttribute('role','status');
    container.append(head(body,container),githubForm(container),status);
    const grid=document.createElement('div');
    grid.className='plugin-cards';
    container.append(grid);
    const spots=draggable?saved():{};
    body.plugins.forEach((plugin,index)=>{
      const node=card(plugin,container);
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
    if(event.button!==0||!node.parentElement||event.target.closest('a,button'))return;
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

  function mountDialog(toolbar,draggable){
    const button=document.createElement('button');
    button.type='button';
    button.textContent='插件';
    button.setAttribute('aria-haspopup','dialog');
    button.setAttribute('aria-label',draggable?'打开插件画布':'打开插件面板');
    toolbar.prepend(button);
    const dialog=document.createElement('dialog');
    dialog.className='plugin-dialog';
    dialog.setAttribute('aria-labelledby',draggable?'plugin-title-focus':'plugin-title-hall');
    dialog.innerHTML='<div class="plugin-dialog-head"><strong></strong><button type="button" data-close>关闭</button></div>'+
      (draggable?'<p class="hint">拖动卡片可调整本机画布布局。</p>':'')+
      '<div class="plugin-board"></div>';
    const title=dialog.querySelector('strong');
    title.id=dialog.getAttribute('aria-labelledby');
    title.textContent=draggable?'插件画布':'插件面板';
    const board=dialog.querySelector('.plugin-board');
    board.id=draggable?'plugin-board-focus':'plugin-board-hall';
    document.body.append(dialog);
    const close=dialog.querySelector('[data-close]');
    close.onclick=()=>dialog.close();
    dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
    button.onclick=()=>{
      dialog.showModal();
      load().then(body=>fill(board,body,draggable)).catch(error=>{
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
      const toolbar=document.querySelector('.market-wall-actions');
      if(toolbar){mountDialog(toolbar,false);hallMounted=true;}
    }
    if(!focusMounted&&matchMedia('(min-width: 761px)').matches){
      const toolbar=document.querySelector('#desktop-focus .desktop-flow-toolbar-actions');
      if(toolbar){mountDialog(toolbar,true);focusMounted=true;}
    }
    if(hallMounted&&(focusMounted||!matchMedia('(min-width: 761px)').matches)&&observer){observer.disconnect();observer=null;}
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});
  install();
  observer=new MutationObserver(()=>{try{install();}catch{}});
  observer.observe(document.body,{childList:true,subtree:true});
  return{install};
})();
