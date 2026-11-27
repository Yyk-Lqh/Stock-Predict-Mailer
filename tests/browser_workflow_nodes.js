/* gstack acceptance on the disposable console at 127.0.0.1:18794. */
(() => {
  if (location.origin !== 'http://127.0.0.1:18794') throw Error('Use the workflow node fixture');
  const wait = async (get, message) => {
    for (let i=0; i<210; i++) {
      const value=get();
      if(value)return value;
      await new Promise(resolve=>setTimeout(resolve,60));
    }
    throw Error(message);
  };
  const assert=(condition,message)=>{if(!condition)throw Error(message);};
  const press=(host,label)=>[...host.querySelectorAll('button')].find(node=>node.textContent.trim()===label&&!node.hidden&&!node.disabled);
  const set=(node,value)=>{if(!node)throw Error('Missing input for '+value);node.value=value;node.dispatchEvent(new Event('input',{bubbles:true}));};
  const config=()=>$('desktop-node-config');
  const graph=()=>DesktopWorkbench.canvasSnapshot().graph;
  const getNode=(kind,index=0)=>graph().nodes.filter(node=>node.data.type===kind)[index];
  const card=id=>document.querySelector('[data-workflow-node="'+id+'"]');
  const library=()=>$('workflow-node-library');
  const pick=(name,keyboard=false)=>{
    const search=library().querySelector('input');
    set(search,name);
    const row=[...library().querySelectorAll('[data-node-type]')].find(item=>!item.disabled&&!item.hidden);
    assert(row,'No available node: '+name);
    if(keyboard) {
      search.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
      assert(document.activeElement===row,'Arrow did not focus the node');
      search.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
    } else row.click();
    set(search,'');
  };
  const add=(node,port,label)=>{
    card(node.id).querySelector('.out[data-port="'+port+'"]').click();
    pick(label);
  };
  const field=(label,host=config())=>[...host.querySelectorAll('label')].find(el=>[...el.childNodes]
    .some(child=>child.nodeType===Node.TEXT_NODE&&child.textContent.trim()===label))?.querySelector('input, select, textarea');
  const click=(host,label)=>{
    const button=press(host,label);
    assert(button,'Missing action '+label+' · '+host.textContent.slice(0,200));
    button.click();
  };
  const save=()=>click(config(),'保存节点');
  const stage=async name=>{
    window.workflowNodesQA={stage:name};
    await wait(()=>window.workflowNodesContinue===name,'Screenshot gate timed out: '+name);
  };
  const ui=suffix=>$('workflow-chat-'+suffix);
  window.workflowNodesQA={stage:'starting'};
  (async()=>{
    await wait(()=>memoryKey&&window.WorkflowChat&&$('workflow-canvas-nav'),'Console did not initialize');
    const restored=sessionStorage.getItem('workflow-nodes-refresh');
    if(restored) {
      await wait(()=>!document.querySelector('.workflow-catalog').hidden,'Directory did not restore');
      const saved=await wait(()=>[...document.querySelectorAll('.wfcat-card')].find(el=>el.textContent.includes('行情与财报分流')),
        'Saved workflow card did not reload');
      press(saved,'打开画布').click();
      await wait(()=>getNode('classifier'),'Saved topology did not restore');
      assert(graph().edges.length===5,'Saved edges did not restore');
      assert(getNode('classifier').data.config.cases.map(item=>item.label).join(',')==='财报,行情','Stable branch order was lost');
      const classifier=getNode('classifier');
      card(classifier.id).click();
      document.querySelector('[data-node-view="runtime"]').click();
      await wait(()=>$('desktop-node-runtime').textContent.includes('查看此运行')&&
        $('desktop-node-runtime').textContent.includes('财报'),'The last-run inspector did not load the selected flow');
      const quote=getNode('template');
      card(quote.id).click();
      await wait(()=>$('desktop-node-runtime').textContent.includes('行情输出 3'),'Last run did not skip the execution that omitted the selected node');
      const fetchRun=window.fetch;
      let delayed=false, finish;
      const gate=new Promise(resolve=>{finish=resolve;});
      window.fetch=async (url,...args)=>{
        const response=await fetchRun(url,...args);
        if(String(url).includes('node='+classifier.id)){delayed=true;await gate;}
        return response;
      };
      try {
        card(classifier.id).click();
        await wait(()=>delayed,'The classifier request was not delayed');
        card(quote.id).click();
        await wait(()=>$('desktop-node-runtime').textContent.includes('行情输出 3'),'Latest response did not reach the active node');
        finish();
        await new Promise(resolve=>setTimeout(resolve,120));
        assert($('desktop-node-runtime').textContent.includes('行情输出 3'),'A late response replaced a different node’s run');
      } finally { finish(); window.fetch=fetchRun; }
      card(classifier.id).click();
      document.querySelector('[data-node-view="config"]').click();
      for(let index=2;index<8;index++){
        click(config(),'添加分类出口');
        const row=config().querySelector('.workflow-config-row:last-child');
        set(field('出口名称',row),'补充场景 '+index);
        set(field('关键词（逗号分隔）',row),'场景'+index);
      }
      save();
      const outlets=[...card(classifier.id).querySelectorAll('.workflow-card-outlet button')];
      assert(outlets.length===8&&new Set(outlets.map(el=>el.getBoundingClientRect().top)).size===8,
        'Eight branches did not create distinct aligned ports');
      $('desktop-workflow-undo').click();
      window.workflowNodesNarrow=()=>{
        const canvas=$('desktop-focus'), toggle=$('workflow-library-toggle');
        if(toggle.getAttribute('aria-expanded')==='false')toggle.click();
        const panel=library().getBoundingClientRect(), view=canvas.getBoundingClientRect();
        assert(view.width>0 && panel.width>0 && panel.right<=innerWidth,'Narrow canvas or library is inaccessible');
        const search=library().querySelector('input');
        set(search,'分类器');assert(library().querySelector('[data-node-type="classifier"]:not([hidden])'),'Narrow library search failed');
        set(search,'');
        $('workflow-inspector-toggle').click();
        config().scrollTop=0;
        const settings=$('desktop-workflow-inspector').getBoundingClientRect();
        assert(settings.width>0&&settings.right<=innerWidth,'Narrow settings panel is inaccessible');
        const inner=config().getBoundingClientRect(), header=$('desktop-node-heading').getBoundingClientRect();
        assert(inner.height>0 && header.height>0, 'Narrow drawer did not expose header and settings');
        return {width:innerWidth,panelFits:true};
      };
      sessionStorage.removeItem('workflow-nodes-refresh');
      window.workflowNodesQA={stage:'restored'};
      return;
    }
    applyTheme('light',false);
    DesktopWorkbench.setMode('hall');set($('conversation-message'),'普通模式独立草稿');
    DesktopWorkbench.setMode('focus');$('workflow-canvas-nav').click();
    await wait(()=>!document.querySelector('.workflow-catalog').hidden,'Workflow directory did not open');
    click(document.querySelector('.wfcat-header'),'分析模板');
    await wait(()=>card('report'),'Analysis template did not load');
    click($('desktop-focus'),'添加节点');
    await wait(()=>library().querySelector('[data-node-type="classifier"]:not(:disabled)'),'New nodes are disabled in the analysis library');
    pick('问题分类器');
    assert(getNode('input')?.data.config.fields && getNode('classifier') && graph().edges.length===1,
      'Picking a variable node did not open a variable canvas with an entry');
    $('desktop-workflow-undo').click();
    WorkflowChat.showDirectory();
    click(document.querySelector('.wfcat-header'),'分析模板');
    assert(card('report'),'Adding a variable node changed the old canvas');
    WorkflowChat.showDirectory();
    $('wfcat-new').click();
    await wait(()=>$('workflow-canvas-empty')&&!$('workflow-canvas-empty').hidden,'Empty canvas did not open');
    $('workflow-canvas-empty').click();
    await wait(()=>library().querySelector('[data-node-type="input"]:not(:disabled)'),'Library not initialized');
    assert([...library().querySelectorAll('h4')].map(row=>row.textContent).join()=== '基础节点,问题理解,逻辑节点,转换节点,工具节点','Groups are wrong');
    assert(library().querySelector('[data-node-type="code"]').disabled,'Unavailable code node is enabled');
    pick('用户输入',true);
    await stage('library');
    const start=getNode('input');
    press(config(),'添加字段').click();
    set(field('变量名'),'count');
    set(field('显示名称或说明'),'数量');
    set(field('值类型'),'number');
    set(field('默认值（JSON，可留空）'),'3');
    save();
    add(start,'value','问题分类器');
    const classifier=getNode('classifier'), cid=classifier.id;
    set(field('上游变量'),start.id+'.message');
    const row=()=>[...config().querySelectorAll('.workflow-config-row')];
    set(field('出口名称',row()[0]),'行情');set(field('关键词（逗号分隔）',row()[0]),'行情');
    click(config(),'添加分类出口');
    set(field('出口名称',row()[1]),'财报');set(field('关键词（逗号分隔）',row()[1]),'财报');
    field('启用默认出口').click();
    save();
    const [quote,filing]=getNode('classifier').data.config.cases;
    add(classifier,quote.id,'模板转换');
    const a=getNode('template');
    set(field('节点名称'),'核对行情与历史交易量的详细流程');
    set(field('模板'),'行情输出 {{'+start.id+'.count}}');save();
    add(classifier,filing.id,'模板转换');
    const b=getNode('template',1);
    set(field('节点名称'),'财报路径');set(field('模板'),'财报输出 {{'+start.id+'.message}}');save();
    for(const [index,node] of [a,b].entries()) {
      add(node,'value','输出');
      set(field('节点名称',config()),index?'财报结果':'行情结果');
      set(field('上游变量',config()),node.id+'.value');save();
    }
    assert(graph().edges.length===5,'Port add did not create connections');
    card(cid).click();
    click(row()[0],'下移');save();
    assert(graph().edges.find(edge=>edge.target===a.id).output===quote.id,'Reorder changed a stable port');
    const original=window.confirm;
    let warning='';
    window.confirm=message=>{warning=message;return true;};
    click(row()[1],'删除');save();window.confirm=original;
    assert(warning.includes('1 条连线')&&graph().edges.length===4,'Deleting branch did not warn and remove the edge');
    $('desktop-workflow-undo').click();assert(graph().edges.length===5,'Undo failed to restore the edge');
    $('desktop-workflow-redo').click();assert(graph().edges.length===4,'Redo failed to remove the edge');
    $('desktop-workflow-undo').click();
    card(start.id).click();warning='';window.confirm=message=>{warning=message;return true;};
    click(row()[0],'删除');save();window.confirm=original;
    const consumer=graph().nodes.find(item=>item.id===a.id);
    assert(warning.includes(consumer.data.label)&&graph().edges.length===5,'Removing a referenced variable did not identify its consumer');
    $('desktop-workflow-undo').click();
    card(a.id).click();set(field('模板'),'{{missing.value}}');save();
    press($('desktop-focus'),'校验流程').click();
    const problem=await wait(()=>[...document.querySelectorAll('dialog.workflow-issues[open] button')]
      .find(item=>item.textContent.includes('变量引用无效')),'Bad variable did not surface a validation error');
    problem.click();
    assert($('desktop-workflow-inspector').dataset.node===a.id,'Validation did not locate failing node');
    assert(document.activeElement===field('模板') && field('模板').getAttribute('aria-invalid')==='true',
      'Validation did not focus the failing field');
    set(field('模板'),'行情输出 {{'+start.id+'.count}}');save();
    card(cid).click();
    document.querySelector('[data-viewport-action="fit"]').click();
    await stage('config');
    $('workflow-inspector-toggle').click();document.querySelector('[data-viewport-action="fit"]').click();
    await stage('canvas');
    const link=graph().edges.find(edge=>edge.source===cid&&edge.target===a.id);
    const path=document.querySelector('[data-edge-id="'+link.id+'"]'), board=$('desktop-workflow-canvas');
    const capture=board.setPointerCapture;
    const pointer=(el,name,{x,y})=>el.dispatchEvent(new PointerEvent(name,{clientX:x,clientY:y,pointerId:1,button:0,bubbles:true}));
    const origin=path.getPointAtLength(path.getTotalLength()*.24).matrixTransform(path.getScreenCTM());
    const otherOutlet=card(cid).querySelector('.out[data-port="'+filing.id+'"]');
    const bounds=otherOutlet.getBoundingClientRect(), target={x:bounds.x+bounds.width/2,y:bounds.y+bounds.height/2};
    board.setPointerCapture=()=>{};
    pointer(path,'pointerdown',origin);pointer(board,'pointermove',target);pointer(board,'pointerup',target);
    board.setPointerCapture=capture;
    assert(graph().edges.find(edge=>edge.id===link.id)?.output===filing.id,'Dragging did not attach the selected outlet');
    $('desktop-workflow-undo').click();
    assert(graph().edges.find(edge=>edge.id===link.id)?.output===quote.id,'Undo did not restore the original outlet');
    click($('desktop-focus'),'运行流程');
    const runForm=await wait(()=>document.querySelector('[data-workflow-run-form][open] form'),'Running an unsaved graph did not open input');
    set(runForm.elements.message,'行情');
    runForm.requestSubmit();
    await wait(()=>$('desktop-node-runtime').textContent.includes('行情输出 3'),'The unsaved graph did not run from the canvas');
    await stage('draft-run');
    document.querySelector('[data-workflow-surface="edit"]').click();
    $('desktop-workflow-save').click();
    const dialog=await wait(()=>document.querySelector('dialog.workflow-chat-dialog[open]'),'Workflow save dialog did not open');
    set(dialog.querySelector('[name=name]'),'行情与财报分流');dialog.querySelector('form').requestSubmit();
    const saved=await wait(()=>[...document.querySelectorAll('.wfcat-card')].find(el=>el.textContent.includes('行情与财报分流')),'Saved flow not listed');
    press(saved,'在对话中使用').click();
    await wait(()=>ui('title').textContent==='行情与财报分流'&&!ui('send').disabled,'Workflow not selected in chat');
    for(const [message,answer,skipped] of [['行情','行情输出 3',b.id],['财报','财报输出 财报',a.id]]) {
      set(ui('message'),message);ui('form').requestSubmit();
      await wait(()=>ui('messages').querySelector('.wfchat-run:last-child .wfchat-output')?.textContent.includes(answer),'Chat output missing: '+answer);
      assert(ui('messages').querySelector('.wfchat-run:last-child details[data-step="'+skipped+'"]')?.textContent.includes('已跳过'),'Skipped branch absent');
      await wait(()=>!ui('send').disabled,'Run did not settle');
    }
    const latest=ui('messages').querySelector('.wfchat-run:last-child');
    press(latest,'在画布查看本次运行').click();
    await wait(()=>card(a.id)?.dataset.status==='skipped'&&card(b.id)?.dataset.status==='completed','Canvas run diverged from chat timeline');
    card(cid).click();applyTheme('dark',false);
    await stage('execution');
    ui('nav').click();
    DesktopWorkbench.setMode('hall');
    await wait(()=>$('conversation-message').value==='普通模式独立草稿','Mode switch lost standard draft');
    DesktopWorkbench.setMode('focus');$('workflow-canvas-nav').click();
    await wait(()=>!document.querySelector('.workflow-catalog').hidden,'Directory should be visible');
    sessionStorage.setItem('workflow-nodes-refresh','1');
    window.workflowNodesQA={stage:'reload'};
  })().catch(error=>{window.workflowNodesQA={stage:'failed',message:error.message,stack:error.stack,
    feedback:ui('feedback')?.textContent,thread:ui('messages')?.textContent.slice(0,700),config:config()?.textContent.slice(0,450)};});
  return 'Workflow nodes acceptance started';
})()
