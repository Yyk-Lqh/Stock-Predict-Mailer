/* Exercise draft editing, revision restoration and both execution entry points. */
(() => {
  if(location.hostname!=='127.0.0.1' || location.port!=='18799')throw Error('Use the workflow validation fixture');
  const assert=(condition,message)=>{if(!condition)throw Error(message);};
  const wait=async (get,message)=>{
    for(let attempt=0;attempt<240;attempt++) {
      const value=await get();if(value)return value;
      await new Promise(resolve=>setTimeout(resolve,65));
    }
    throw Error(message);
  };
  const stage=async name=>{
    window.validationQA={stage:name};
    await wait(()=>window.validationContinue===name,'Screenshot gate timed out: '+name);
  };
  const click=(host,name)=>{
    const button=[...host.querySelectorAll('button')].find(item=>item.textContent.trim()===name);
    assert(button,'Missing action: '+name);button.click();
  };
  const set=(node,value,event='input')=>{
    node.value=value;node.dispatchEvent(new Event(event,{bubbles:true}));
  };
  const board=()=>$('desktop-focus');
  const card=id=>document.querySelector('[data-workflow-node="'+id+'"]');
  const graph=()=>DesktopWorkbench.canvasSnapshot().graph;
  const check=()=>click(board(),'校验流程');
  const problems=()=>document.querySelector('dialog.workflow-issues[open]');
  const fixture='并行摘要与明细';
  const savedCard=()=>[...document.querySelectorAll('.wfcat-card')].find(item=>item.querySelector('h3')?.textContent===fixture);
  const node=(id,type,label,x,y,config)=>({id,position:{x,y},data:{type,label,config}});
  const fields=(...names)=>names.map(name=>({name,type:'text',required:true}));
  const key='workflow-validation-refresh';
  const edgeIds=()=>graph().edges.map(edge=>[edge.source,edge.output||'value',edge.target,edge.input||'value'].join('.'));
  function connect(source,target,output='value',input='value') {
    card(source).click();
    const form=$('desktop-node-config').querySelector('.desktop-flow-connect');
    form.closest('details').open=true;
    set(form.elements.target,target,'change');
    set(form.elements.output,output);
    set(form.elements.input,input);
    assert(form.elements.output.value===output && form.elements.input.value===input,'Port selection missing');
    form.requestSubmit();
  }
  async function save(creating) {
    $('desktop-workflow-save').click();
    if(creating) {
      const layer=await wait(()=>document.querySelector('dialog.workflow-chat-dialog[open]'),'Workflow save did not open');
      set(layer.querySelector('[name=name]'),fixture);
      layer.querySelector('form').requestSubmit();
    }
    return wait(()=>savedCard() && !savedCard().closest('.workflow-catalog').hidden,'Workflow card was not saved');
  }
  const fit=()=>board().querySelector('[data-viewport-action=fit]').click();
  window.validationQA={stage:'starting'};
  (async()=>{
    await wait(()=>memoryKey && $('workflow-canvas-nav'),'Console did not initialize');
    const restored=JSON.parse(sessionStorage.getItem(key)||'null');
    if(!restored) {
      applyTheme('light',false);
      DesktopWorkbench.setMode('hall');set($('conversation-message'),'普通模式独立的验收草稿');
      DesktopWorkbench.setMode('focus');await $('try-sample').onclick();
      DesktopWorkbench.useDefinition(null,{empty:true});WorkflowChat.showCanvas();
      const nodes=[
        node('start','input','用户输入',55,105,{fields:[{name:'count',type:'number',required:true,default:2}]}),
        node('model','llm','生成摘要',345,70,{template:'摘要 {{start.message}}',format:'text'}),
        node('detail','template','整理明细',345,310,{template:'数量 {{start.count}}'}),
        node('reply','output','汇合结果',740,65,{format:'json',fields:fields('summary','detail')}),
        node('audit','output','复核结果',740,325,{format:'json',fields:fields('summary','detail')}),
      ];
      const file=$('desktop-workflow-file'), transfer=new DataTransfer();
      transfer.items.add(new File([JSON.stringify({version:2,nodes,edges:[]})],'validation.json',{type:'application/json'}));
      file.files=transfer.files;file.dispatchEvent(new Event('change',{bubbles:true}));
      await wait(()=>card('audit'),'Graph import failed');
      connect('start','model');connect('start','detail');
      for(const target of ['reply','audit']) {
        connect('model',target,'value','summary');connect('detail',target,'value','detail');
      }
      assert(graph().edges.length===6,'Fan-out or distinct field connections missing');
      assert(await DesktopWorkbench.checkWorkflow(),'Valid many-to-many graph failed validation');
      connect('detail','model');connect('model','detail');
      assert(graph().edges.length===8 && document.querySelector('path[data-edge-id][data-invalid]'),'Cycle was discarded or not marked');
      $('desktop-workflow-undo').click();$('desktop-workflow-undo').click();
      assert(graph().edges.length===6 && await DesktopWorkbench.checkWorkflow(),'Undo did not restore the acyclic flow');
      $('desktop-node-close').click();
      if(!$('workflow-node-library').hidden)$('workflow-library-toggle').click();
      fit();await stage('many');
      connect('start','reply','count','summary');
      assert(edgeIds().includes('start.count.reply.summary'),'Incompatible edge was discarded');
      check();
      const problem=await wait(problems,'Issue list did not open');
      const issue=await wait(()=>[...problem.querySelectorAll('.desktop-flow-issue')].find(item=>item.textContent.includes('summary')),
        'Typed port issue is missing');
      issue.click();
      assert($('desktop-workflow-inspector').dataset.node==='reply','Issue did not locate the target');
      assert(card('reply').hasAttribute('data-invalid') && document.querySelector('path[data-edge-id][data-invalid]'),'Graph did not mark the error');
      await stage('issue');
      click(board(),'运行流程');
      await wait(problems,'Trying to run an invalid draft did not open issues');
      click(problems(),'关闭');
      await save(true);
      assert(savedCard().textContent.includes('草稿'),'Invalid graph was not stored as a draft');
      sessionStorage.setItem(key,JSON.stringify({edges:edgeIds()}));
      window.validationQA={stage:'reload'};
      return;
    }
    DesktopWorkbench.setMode('focus');WorkflowChat.showDirectory();
    const stored=await wait(savedCard,'Saved draft did not load after refresh');
    click(stored,'打开画布');
    await wait(()=>card('reply'),'Draft canvas did not open');
    assert(JSON.stringify(edgeIds())===JSON.stringify(restored.edges),'Port bindings did not survive refresh');
    card('reply').click();
    const invalid=graph().edges.find(edge=>edge.source==='start'&&edge.target==='reply');
    const row=$('desktop-node-config').querySelector('[data-connection-id="'+invalid.id+'"]');
    assert(row,'Target inspector did not show the incoming link');click(row,'×');
    assert(await DesktopWorkbench.checkWorkflow(),'Repaired graph did not pass');
    $('desktop-workflow-undo').click();assert(graph().edges.length===7,'Undo did not restore the removed wire');
    $('desktop-workflow-redo').click();assert(graph().edges.length===6,'Redo did not remove the wire');
    await save(false);
    assert(savedCard().textContent.includes('可运行'),'Repaired version did not become runnable');
    click(savedCard(),'打开画布');
    await wait(()=>card('reply'),'Repaired canvas did not open');
    const definition=DesktopWorkbench.canvasSnapshot().definition;
    click(board(),'运行流程');
    const form=await wait(()=>document.querySelector('[data-workflow-run-form][open] form'),'Run inputs did not open');
    set(form.elements.message,'画布验收');form.requestSubmit();
    await wait(()=>$('desktop-node-runtime').textContent.includes('摘要 画布验收'),'Canvas run did not display the result');
    card('reply').click();
    await stage('run');
    WorkflowChat.showDirectory();
    click(await wait(savedCard,'Flow card disappeared'),'在对话中使用');
    await wait(()=>$('workflow-chat-title').textContent===fixture&&!$('workflow-chat-send').disabled,'Repaired flow cannot run from chat');
    set($('workflow-chat-message'),'对话验收');$('workflow-chat-form').requestSubmit();
    await wait(()=>$('workflow-chat-messages').textContent.includes('摘要 对话验收'),'Chat run did not return the named fields');
    const history=await api('workflows/definitions/'+definition.id+'/runs','GET',undefined,undefined,AnalysisMode.capture());
    assert(history.items.length===2 && history.items.every(item=>item.version===definition.revision),
      'Canvas and chat did not use the same saved revision');
    DesktopWorkbench.setMode('hall');
    await wait(()=>$('conversation-message').value==='普通模式独立的验收草稿','Standard mode draft changed');
    sessionStorage.removeItem(key);
    window.validationQA={stage:'passed',draft:true,run:true,chat:true,edges:edgeIds().length};
  })().catch(error=>{window.validationQA={stage:'failed',message:error.message,stack:error.stack,
    status:$('desktop-workflow-message')?.textContent,issues:problems()?.textContent};});
  return 'Workflow validation started';
})()
