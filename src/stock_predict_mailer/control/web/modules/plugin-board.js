/* Plugin cards and workspace-local GitHub imports for both console views. */
globalThis.PonyPluginBoard=(()=>{
  const KEY='stock_predict_mailer.plugin.board.v1';
  const desktop=matchMedia('(min-width: 761px)');
  const KINDS={market_source:'行情源',chart_renderer:'图表绘制',report_renderer:'页面渲染',notifier:'通知渠道',exporter:'数据导出'};
  const CAPABILITIES={quotes:'行情报价',candles:'走势图',bars:'历史日线',html:'HTML 报告',text:'纯文本报告',send:'邮件投递',csv:'CSV',json:'JSON',parquet:'Parquet',line:'时间序列折线',bar:'同时间点分组对比'};
  const PAGE_DESCRIPTIONS={report_dashboard:'汇总上游模型、事实和图表',report_evidence:'按事实列出来源和观测时间'};
  const MARKS={market_source:'行',chart_renderer:'图',report_renderer:'页',notifier:'邮',exporter:'出'};
  let cache=null,pending=null,observer=null,hallMounted=false,focusMounted=false;
  let renderWorkspace;

  async function load(force){
    if(cache&&!force)return cache;
    if(pending)return pending;
    pending=api('plugins').then(body=>{cache=body;return body;}).finally(()=>{pending=null;});
    return pending;
  }
  const saved=()=>{try{return JSON.parse(localStorage.getItem(KEY))||{};}catch{return{};}};
  const remember=map=>{try{localStorage.setItem(KEY,JSON.stringify(map));}catch{}};

  function githubSource(plugin) {
    const source=document.createElement('a');
    source.href=plugin.github_url;source.target='_blank';source.rel='noopener noreferrer';
    source.textContent='GitHub ↗';source.title=plugin.github_url;
    return source;
  }

  function removePlugin(plugin,container) {
    const button=document.createElement('button');
    button.type='button';button.textContent='移除';
    button.setAttribute('aria-label',`移除插件 ${plugin.label}`);
    button.onclick=()=>mutate(container,button,`plugins/github/${encodeURIComponent(plugin.id)}`,'DELETE',undefined,'插件已移除');
    return button;
  }

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
      meta.append(githubSource(plugin),` · ${plugin.manifest_sha256.slice(0,8)} `,removePlugin(plugin,container));
    }else{
      const signature=plugin.module_digest?.slice(0,8)||'—';
      meta.textContent=`${plugin.available?'可用':'缺依赖'}${missing} · 模块 ${signature}`;
      node.title=`${plugin.id}\n${plugin.module}`;
    }
    return node;
  }

  function inventoryCard(plugin,container) {
    const node=document.createElement('article');
    node.className='plugin-entry';node.dataset.pluginId=plugin.id;node.dataset.kind=plugin.kind;
    const main=document.createElement('div');main.className='plugin-entry-main';
    const mark=text(main,'span',MARKS[plugin.kind]||'件','plugin-entry-mark');mark.setAttribute('aria-hidden','true');
    const copy=document.createElement('div');copy.className='plugin-entry-copy';
    text(copy,'h3',plugin.label);
    text(copy,'p',PAGE_DESCRIPTIONS[plugin.id]||plugin.capabilities.map(value=>CAPABILITIES[value]||value).join(' · '));
    if(plugin.requires.length) text(copy,'p',`依赖 ${plugin.requires.join('、')}`,'plugin-entry-deps');
    main.append(copy);
    const kind=text(main,'span',KINDS[plugin.kind]||plugin.kind,'plugin-entry-kind');
    kind.title=plugin.problems.join('；');
    const foot=document.createElement('footer');foot.className='plugin-entry-foot';
    const digest=(plugin.manifest_sha256||plugin.module_digest)?.slice(0,8);
    const identifier=text(foot,'code',plugin.id);identifier.title=digest?`${plugin.id} · ${digest}`:plugin.id;
    const meta=document.createElement('div');meta.className='plugin-entry-meta';
    if(plugin.default)text(meta,'span','默认行情链');
    const state=text(meta,'span',plugin.available?'可用':'缺依赖','plugin-entry-state');state.dataset.available=String(plugin.available);
    if(plugin.github_url)meta.append(githubSource(plugin),removePlugin(plugin,container));
    else text(meta,'span','内置');
    const kindForNode=plugin.kind==='chart_renderer'?'chart':plugin.kind==='report_renderer'&&plugin.capabilities.includes('html')?'report':null;
    if(kindForNode && plugin.available){
      const use=text(meta,'button','应用到流程');use.type='button';
      use.setAttribute('aria-label',`将${plugin.label}应用到流程`);
      use.onclick=()=>{
        if(window.DesktopWorkbench?.useRenderer(kindForNode,plugin.id))container.closest('dialog').close();
        else container.querySelector('.plugin-feedback').textContent='暂时无法应用，请检查工作流是否已加载及节点数量。';
      };
    }
    foot.append(meta);node.append(main,foot);return node;
  }

  async function mutate(container,button,path,method,body,success){
    let status=container.querySelector('.plugin-feedback'), changed=false;
    button.disabled=true;
    status.textContent=method==='POST'?'正在从 GitHub 获取插件…':'正在移除插件…';
    try{
      await api(path,method,body);
      changed=true;
      status.textContent=success;
      await refresh();
      status=container.querySelector('.plugin-feedback');
      status.textContent=success;
      return true;
    }catch(error){
      const message=changed?`${success}，列表刷新失败`:'操作失败';
      status.textContent=`${message}。 ${error.message}`;
    }finally{
      button.disabled=false;
    }
  }

  async function refresh(){
    if(pending)await pending.catch(()=>{});
    const body=await load(true);
    const hall=document.getElementById('plugin-board-hall');
    if(hall?.dataset.state==='ready')fill(hall,body);
    renderWorkspace?.(body);
  }

  function githubForm(container){
    const details=document.createElement('details');
    details.className='plugin-github';
    details.innerHTML='<summary>从 GitHub 添加</summary><form>'+
      '<label>GitHub 仓库地址 <input name="url" type="url" required maxlength="256" placeholder="https://github.com/owner/repo"></label>'+
      '<button type="submit">添加插件</button></form>'+
      '<p class="plugin-board-hint">仓库默认分支的根目录需包含 stock-predict-mailer-plugin.json。</p>';
    const form=details.querySelector('form');
    form.onsubmit=async event=>{
      event.preventDefault();
      if(await mutate(container,form.querySelector('button'),'plugins/github','POST',{url:form.elements.url.value},'插件已添加')){
        form.reset();details.open=false;
      }
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

  function fill(container,body){
    container.replaceChildren();
    const status=document.createElement('p');
    status.className='plugin-feedback';
    status.setAttribute('role','status');
    container.append(head(body,container),githubForm(container),status);
    const grid=document.createElement('div');
    grid.className='plugin-cards';
    grid.append(...body.plugins.map(plugin=>card(plugin,container)));
    container.append(grid);container.dataset.state='ready';
  }

  function fillLayout(grid,plugins,container) {
    const spots=saved();
    grid.replaceChildren(...plugins.map((plugin,index)=>{
      const node=card(plugin,container);
      const fallback={x:12+(index%3)*232,y:12+Math.floor(index/3)*128};
      const spot=spots[plugin.id]||fallback;
      node.style.left=spot.x+'px';
      node.style.top=spot.y+'px';
      node.addEventListener('pointerdown',event=>drag(event,node,plugin.id));
      return node;
    }));
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

  async function fillWorkflowTools(host,dialog){
    host.textContent='正在读取工作流工具…';
    try {
      const catalog=await api('workflows/catalog');
      host.replaceChildren();
      for (const [id,spec] of Object.entries(catalog.nodes.tool?.options||{})) {
        const tool=document.createElement('article');tool.className='plugin-tool-entry';
        const copy=document.createElement('div');
        text(copy,'h3',spec.label);text(copy,'p',spec.detail);
        const button=document.createElement('button');
        button.type='button';
        button.textContent='添加到画布';
        button.setAttribute('aria-label',`添加${spec.label}节点`);
        button.onclick=()=>{
          if (window.DesktopWorkbench?.addBuiltinTool?.(id)) dialog.close();
          else dialog.querySelector('.plugin-feedback').textContent='无法添加节点，请检查当前是否为可编辑流程及节点数量。';
        };
        tool.append(copy,button);host.append(tool);
      }
      if(!host.childElementCount) host.textContent='暂无可用的工作流工具。';
    } catch(error) {host.textContent=error.message;}
  }

  function workspace(dialog) {
    dialog.classList.add('plugin-workspace');
    dialog.innerHTML=`<div id="plugin-board-focus" class="plugin-board">
      <header class="plugin-workspace-head">
        <h2 id="plugin-title-focus">插件管理</h2>
        <div class="plugin-workspace-tabs" role="group" aria-label="插件管理视图">
          <button type="button" data-plugin-view="catalog" aria-controls="plugin-catalog">插件 <span data-plugin-count></span></button>
          <button type="button" data-plugin-view="tools" aria-controls="plugin-tools">工作流工具</button>
          <button type="button" data-plugin-view="layout" aria-controls="plugin-layout">卡片布局</button>
        </div>
        <div class="plugin-workspace-actions"><button type="button" data-plugin-refresh>刷新</button><button type="button" data-close>返回画布</button></div>
      </header>
      <p class="plugin-feedback" role="status"></p>
      <div class="plugin-workspace-content">
        <section id="plugin-catalog" data-plugin-pane="catalog" aria-label="插件列表">
          <div class="plugin-filters">
            <select aria-label="插件类别" data-plugin-kind><option value="">全部类别</option></select>
            <select aria-label="插件来源" data-plugin-source><option value="">全部来源</option><option value="builtin">内置</option><option value="github">GitHub</option></select>
            <input type="search" aria-label="搜索插件" placeholder="搜索名称、标识或能力" data-plugin-search>
            <span data-plugin-matches role="status"></span>
          </div>
          <div class="plugin-inventory" data-plugin-list></div>
          <p data-plugin-empty class="plugin-workspace-empty" hidden>没有符合当前筛选条件的插件。</p>
          <p data-plugin-diagnostics class="plugin-workspace-diagnostics"></p>
        </section>
        <section id="plugin-tools" data-plugin-pane="tools" aria-label="工作流工具" class="plugin-inventory" hidden></section>
        <section id="plugin-layout" data-plugin-pane="layout" aria-label="自定义卡片布局" data-draggable="true" hidden>
          <p class="hint">拖动卡片以调整位置，布局保存在当前浏览器。</p><div class="plugin-cards"></div>
        </section>
      </div></div>`;
    const board=dialog.querySelector('#plugin-board-focus');
    const kind=board.querySelector('[data-plugin-kind]'), source=board.querySelector('[data-plugin-source]'), search=board.querySelector('[data-plugin-search]');
    const list=board.querySelector('[data-plugin-list]'), tools=board.querySelector('#plugin-tools'), grid=board.querySelector('#plugin-layout .plugin-cards');
    const status=board.querySelector('.plugin-feedback');
    const importer=githubForm(board), refreshButton=board.querySelector('[data-plugin-refresh]');
    importer.querySelector('summary').textContent='＋ 从 GitHub 导入';
    const importFields=document.createElement('div');importFields.className='plugin-import-fields';
    importFields.append(importer.querySelector('form'),importer.querySelector('p'));importer.append(importFields);
    refreshButton.before(importer);
    for(const [value,label] of Object.entries(KINDS))kind.add(new Option(label,value));

    let plugins=[], view='catalog';
    function drawCatalog() {
      const query=search.value.trim().toLowerCase();
      const matches=plugins.filter(plugin=>{
        const origin=plugin.github_url?'github':'builtin';
        return (!kind.value||plugin.kind===kind.value)&&(!source.value||origin===source.value)&&
          [plugin.label,plugin.id,KINDS[plugin.kind],plugin.github_url,...plugin.capabilities.map(value=>CAPABILITIES[value]||value),...plugin.capabilities].join(' ').toLowerCase().includes(query);
      });
      list.replaceChildren(...matches.map(plugin=>inventoryCard(plugin,board)));
      board.querySelector('[data-plugin-matches]').textContent=matches.length===plugins.length?'':`${matches.length} 个匹配`;
      board.querySelector('[data-plugin-empty]').hidden=board.dataset.state!=='ready'||Boolean(matches.length);
    }
    function select(name) {
      view=name;
      for(const control of board.querySelectorAll('[data-plugin-view]')) control.setAttribute('aria-pressed',String(control.dataset.pluginView===name));
      for(const pane of board.querySelectorAll('[data-plugin-pane]')) pane.hidden=pane.dataset.pluginPane!==name;
      if(name==='tools')fillWorkflowTools(tools,dialog);
      if(name==='layout')fillLayout(grid,plugins,board);
    }
    kind.onchange=source.onchange=search.oninput=drawCatalog;
    for(const button of board.querySelectorAll('[data-plugin-view]')) button.onclick=()=>select(button.dataset.pluginView);
    refreshButton.onclick=async()=>{
      refreshButton.disabled=true;status.textContent='正在刷新插件…';
      try{await refresh();status.textContent='插件列表已刷新。';}
      catch(error){status.textContent=`刷新失败。 ${error.message}`;}
      finally{refreshButton.disabled=false;}
    };
    select('catalog');
    renderWorkspace=body=>{
      plugins=body.plugins;board.dataset.state='ready';
      board.querySelector('[data-plugin-count]').textContent=plugins.length;
      board.querySelector('[data-plugin-diagnostics]').textContent=body.problems.length?body.problems.join('；'):`当前行情链  ${body.source_chain.join(' → ')||'—'}`;
      drawCatalog();
      if(view==='layout')fillLayout(grid,plugins,board);
    };
    return board;
  }

  function mountDialog(toolbar,professional){
    const button=document.createElement('button');
    button.type='button';
    if(!professional)button.id='hall-plugins-open';
    button.textContent='插件';
    button.setAttribute('aria-haspopup','dialog');
    button.setAttribute('aria-label',professional?'打开插件管理':'打开插件面板');
    toolbar.prepend(button);
    const dialog=document.createElement('dialog');
    dialog.className='plugin-dialog';
    dialog.setAttribute('aria-labelledby',professional?'plugin-title-focus':'plugin-title-hall');
    if(!professional)dialog.innerHTML='<div class="plugin-dialog-head"><strong id="plugin-title-hall">插件面板</strong><button type="button" data-close>关闭</button></div><div id="plugin-board-hall" class="plugin-board"></div>';
    const board=professional?workspace(dialog):dialog.querySelector('.plugin-board');
    document.body.append(dialog);
    const close=dialog.querySelector('[data-close]');
    close.onclick=()=>dialog.close();
    dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
    if(professional)dialog.addEventListener('close',()=>{
      if(button.getClientRects().length)button.focus({preventScroll:true});
    });
    button.onclick=()=>{
      dialog.showModal();
      const status=board.querySelector('.plugin-feedback');
      if(professional&&!cache)status.textContent='正在读取插件…';
      load().then(body=>{
        if(professional){renderWorkspace(body);status.textContent='';}
        else fill(board,body);
      }).catch(error=>{
        if(professional){board.querySelector('.plugin-feedback').textContent=`插件状态读取失败。 ${error.message}`;return;}
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
    if(!focusMounted&&desktop.matches){
      const toolbar=document.querySelector('#desktop-focus .desktop-flow-toolbar-actions');
      if(toolbar){mountDialog(toolbar,true);focusMounted=true;}
    }
    if(hallMounted&&(focusMounted||!desktop.matches)&&observer){observer.disconnect();observer=null;}
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});
  install();
  observer=new MutationObserver(()=>{try{install();}catch{}});
  observer.observe(document.body,{childList:true,subtree:true});
  desktop.addEventListener('change',event=>{
    if(event.matches)requestAnimationFrame(install);
    else document.querySelector('.plugin-workspace[open]')?.close();
  });
  return{install};
})();
