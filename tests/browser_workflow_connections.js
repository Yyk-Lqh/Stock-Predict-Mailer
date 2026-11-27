/* Exercise the real canvas with the disposable gstack console. */
(() => {
  if(location.hostname!=='127.0.0.1' || location.port!=='18798')throw Error('Use the workflow connections fixture');
  const assert=(condition,message)=>{if(!condition)throw Error(message);};
  const wait=async (get,message)=>{
    for(let attempt=0;attempt<220;attempt++){
      const value=get();if(value)return value;
      await new Promise(resolve=>setTimeout(resolve,65));
    }
    throw Error(message);
  };
  const stage=async name=>{
    window.wiringQA={stage:name};
    await wait(()=>window.wiringContinue===name,'Screenshot wait timed out: '+name);
  };
  const graph=()=>DesktopWorkbench.canvasSnapshot().graph;
  const canvas=()=>$('desktop-workflow-canvas');
  const library=()=>$('workflow-node-library');
  const card=id=>document.querySelector('[data-workflow-node="'+id+'"]');
  const port=(id,direction,name='value')=>card(id).querySelector('.'+direction+'[data-port="'+name+'"]');
  const edge=id=>graph().edges.find(item=>item.id===id);
  const fit=()=>document.querySelector('[data-viewport-action="fit"]').click();
  const center=node=>{const box=node.getBoundingClientRect();return {x:box.left+box.width/2,y:box.top+box.height/2};};
  const pointer=(node,type,{x,y})=>node.dispatchEvent(new PointerEvent(type,{clientX:x,clientY:y,
    pointerId:1,button:0,bubbles:true,cancelable:true}));
  const begin=node=>pointer(node,'pointerdown',center(node));
  const move=point=>pointer(canvas(),'pointermove',point);
  const stop=point=>pointer(canvas(),'pointerup',point);
  const button=kind=>library().querySelector('[data-node-type="'+kind+'"]');
  function picker() {
    const area=library().getBoundingClientRect(), dialog=library().getAttribute('role');
    assert(dialog==='dialog' && !library().hidden && area.width>0,'Contextual picker is not visible');
    assert(area.left>=0 && area.right<=innerWidth && area.top>=0 && area.bottom<=innerHeight,'Picker escaped the viewport');
  }
  window.wiringQA={stage:'starting'};
  (async()=>{
    await wait(()=>memoryKey && button('template') && !button('template').disabled,'Catalog did not load');
    applyTheme('light',false);
    DesktopWorkbench.setMode('focus');DesktopWorkbench.useDefinition(null,{empty:true});WorkflowChat.showCanvas();
    const node=(id,type,label,x,y,config)=>({id,position:{x,y},data:{type,label,config}});
    const nodes=[
      node('entry','input','用户输入',45,120,{fields:[]}),
      node('route','classifier','问题分类器',340,92,{source:'entry.message',fallback:true,
        cases:[{id:'market',label:'行情',description:'查询走势和交易量',match:'行情'}]}),
      node('brief','template','分析摘要',795,85,{template:'{{entry.message}}'}),
      node('reply','output','输出',1090,133,{source:'brief.value',format:'text'}),
      node('notes','template','补充整理',790,340,{template:'{{entry.message}}'})
    ];
    const link=(id,source,target,output)=>({id,source,target,output,condition:'always'});
    const edges=[link('entry-route','entry','route','value'),link('market-brief','route','brief','market'),link('brief-reply','brief','reply','value')];
    const pickerField=$('desktop-workflow-file'), upload=new DataTransfer();
    upload.items.add(new File([JSON.stringify({version:2,mode:'custom',nodes,edges})],'connections.json',{type:'application/json'}));
    pickerField.files=upload.files;pickerField.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>card('notes'),'Canvas graph did not import');
    if(!$('desktop-workflow-inspector').hidden)$('desktop-node-close').click();
    if(!library().hidden)$('workflow-library-toggle').click();
    fit();
    const enhance=document.querySelector('[data-edge-insert="market-brief"]');
    enhance.focus();
    await stage('midpoint');
    if(!library().hasAttribute('data-context'))enhance.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
    picker();
    assert(button('output').hidden && !button('template').disabled,'Picker did not filter by both endpoints');
    assert(library().textContent.includes('问题分类器 → 分析摘要'),'Picker did not identify the selected connection');
    await stage('picker');
    button('llm').click();
    const inserted=graph().nodes.find(item=>item.data.type==='llm');
    assert(edge('market-brief').source==='route' && edge('market-brief').output==='market' &&
      edge('market-brief').target===inserted.id,'Insert changed the original branch identity');
    assert(graph().edges.some(item=>item.source===inserted.id && item.target==='brief'),'Insert did not reconnect the original target');
    assert(graph().nodes.length===6 && graph().edges.length===4,'Insert created an incorrect number of records');
    assert(Math.abs(inserted.position.y-nodes[1].position.y)<30,'Insertion left the available lane');
    await stage('inserted');
    $('desktop-workflow-undo').click();
    assert(edge('market-brief').target==='brief' && graph().nodes.length===5,'Undo did not restore the pre-insertion graph');
    $('desktop-workflow-redo').click();
    assert(edge('market-brief').target===inserted.id,'Redo did not restore the insertion');
    $('desktop-workflow-undo').click();

    const capture=canvas().setPointerCapture;
    canvas().setPointerCapture=()=>{}; // Constructed pointer events do not own a native pointer.
    const start=port('route','out','default');
    const target=center(port('notes','in'));
    assert(document.elementFromPoint(target.x,target.y)?.closest('[data-workflow-node]')?.dataset.workflowNode==='notes',
      'The input did not receive the pointer');
    begin(start);move(target);
    const preview=document.querySelector('.desktop-flow-edge-preview');
    assert(preview.classList.contains('snapped') && port('notes','in').classList.contains('edge-drop-target'),'Preview did not snap');
    applyTheme('dark',false);await stage('drag');
    stop(target);
    assert(graph().edges.some(item=>item.source==='route' && item.output==='default' && item.target==='notes'),'Port drag did not connect');
    assert(!preview.hasAttribute('d'),'Preview continued after drop');
    $('desktop-workflow-undo').click();
    const upstream=center(port('route','out','default'));
    begin(port('notes','in'));move(upstream);stop(upstream);
    assert(graph().edges.some(item=>item.output==='default' && item.target==='notes'),'Dragging from input did not connect');
    $('desktop-workflow-undo').click();
    const invalid=center(port('route','in'));
    begin(port('brief','out'));move(invalid);stop(invalid);
    const cycle=graph().edges.find(item=>item.source==='brief'&&item.target==='route');
    assert(cycle && document.querySelector('[data-edge-id="'+cycle.id+'"][data-invalid]') &&
      !library().hasAttribute('data-context'),'Cyclic draft edge was discarded or not marked');
    $('desktop-workflow-undo').click();

    const board=canvas().getBoundingClientRect(), blank={x:board.left+board.width*.56,y:board.bottom-100};
    assert(!document.elementFromPoint(blank.x,blank.y).closest('[data-workflow-node]'),'Blank drop point is covered');
    begin(port('route','out','default'));move(blank);stop(blank);picker();
    assert(!button('template').disabled,'Blank drop did not offer a compatible node');
    button('template').click();
    assert(graph().edges.length===4 && graph().edges.some(item=>item.source==='route' && item.output==='default' &&
      !nodes.some(original=>original.id===item.target)),'Blank drop did not add a connected node');
    canvas().setPointerCapture=capture;
    $('desktop-workflow-undo').click();
    applyTheme('light',false);
    window.openNarrowWiring=()=>{
      fit();port('route','out','market').click();picker();
      return {width:innerWidth,pickerVisible:true};
    };
    window.wiringQA={stage:'passed',insert:true,undoRedo:true,dragForward:true,dragReverse:true,blank:true};
  })().catch(error=>{window.wiringQA={stage:'failed',message:error.message,stack:error.stack};});
  return 'Connection acceptance started';
})()
