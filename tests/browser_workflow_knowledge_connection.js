/* Regression for dragging from the analysis input to a knowledge node. */
(() => {
  if(location.hostname!=='127.0.0.1' || location.port!=='18798')throw Error('Use the disposable workflow fixture');
  const assert=(value,message)=>{if(!value)throw Error(message);};
  const wait=async (read,message)=>{
    for(let attempt=0;attempt<180;attempt++) {
      const result=await read();if(result)return result;
      await new Promise(resolve=>setTimeout(resolve,70));
    }
    throw Error(message);
  };
  const card=id=>document.querySelector('[data-workflow-node="'+id+'"]');
  const canvas=()=>$('desktop-workflow-canvas');
  const graph=()=>DesktopWorkbench.canvasSnapshot().graph;
  const hint=()=>$('desktop-workflow-message').textContent;
  const node=(id,type,label,x,y)=>({id,position:{x,y},data:{type,label,config:{}}});
  const edge=(id,source,target)=>({id,source,target,condition:'always'});
  const center=element=>{
    const rect=element.getBoundingClientRect();
    return {clientX:rect.x+rect.width/2,clientY:rect.y+rect.height/2};
  };
  const send=(host,type,point)=>host.dispatchEvent(new PointerEvent(type,{...point,pointerId:1,button:0,bubbles:true,cancelable:true}));
  async function load(withValidation) {
    const nodes=[node('prediction','input','资料输入',50,95),node('knowledge','knowledge','知识检索',575,285),
      node('analysis','analysis','Agent',875,295),node('result','report','报告',1120,305)];
    const edges=[edge('knowledge-analysis','knowledge','analysis'),edge('analysis-report','analysis','result')];
    if(withValidation) {
      nodes.push(node('evidence','validation','资料校验',338,50));
      edges.push(edge('original-validation','prediction','evidence'));
    }
    const field=$('desktop-workflow-file'), upload=new DataTransfer(), before=DesktopWorkbench.canvasSnapshot().source;
    upload.items.add(new File([JSON.stringify({version:2,nodes,edges})],'knowledge-connection.json',{type:'application/json'}));
    field.files=upload.files;field.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>card('knowledge') && before!==DesktopWorkbench.canvasSnapshot().source,'Fixture did not import');
    document.querySelector('[data-viewport-action=fit]').click();
    return {nodes,edges};
  }
  function drag(expectedHint) {
    const output=card('prediction').querySelector('.desktop-flow-port.out');
    const input=card('knowledge').querySelector('.desktop-flow-port.in'), target=center(input);
    assert(document.elementFromPoint(target.clientX,target.clientY)===input,'The knowledge input is not hittable');
    const capture=canvas().setPointerCapture;
    canvas().setPointerCapture=()=>{}; // Constructed events do not own a native pointer.
    try {
      send(output,'pointerdown',center(output));send(canvas(),'pointermove',target);
      assert(input.classList.contains('edge-drop-target'),'Knowledge input did not snap to the browser drag');
      assert(hint().includes(expectedHint),'The drag did not identify the validation route');
      send(canvas(),'pointerup',target);
    } finally {canvas().setPointerCapture=capture;}
  }
  window.knowledgeConnectionQA={state:'running'};
  (async()=>{
    await wait(()=>memoryKey && $('workflow-node-library'),'Console did not load');
    DesktopWorkbench.setMode('focus');DesktopWorkbench.useDefinition(null);WorkflowChat.showCanvas();
    await $('try-sample').onclick();
    await wait(()=>JSON.parse($('task-data').value).prediction && AnalysisMode.model(),'Synthetic prediction or mock model did not load');
    const base=await load(true);
    drag('松手后经资料校验');
    assert(graph().nodes.length===base.nodes.length,'The existing validator was duplicated');
    assert(graph().edges.some(item=>item.id==='original-validation'&&item.target==='evidence'),'The existing input route was replaced');
    assert(graph().edges.some(item=>item.source==='evidence'&&item.target==='knowledge'),'The validation output was not connected');
    drag('松手后经资料校验');
    assert(graph().edges.length===base.edges.length+1,'Repeated drag duplicated the connection');
    $('desktop-workflow-undo').click();
    assert(graph().edges.length===base.edges.length,'Undo did not remove only the new connection');
    $('desktop-workflow-redo').click();
    const scope={...AnalysisMode.capture(),knowledgeScope:'local'};
    const workflow={mode:'custom',key:crypto.randomUUID(),graph:graph()};
    const sample=JSON.parse($('task-data').value);
    const result=await api('tasks','POST',{prediction:sample.prediction,context:sample.context,chart_data:sample.chart_data,
      knowledge_query:'校验浏览器验收资料',model_id:AnalysisMode.model(),notify:false,workflow},undefined,scope);
    const terminal=await wait(async()=>{
      const task=await api('tasks/'+result.id,'GET',undefined,undefined,scope);
      return ['completed','failed','canceled'].includes(task.status.state)&&task;
    },'Workflow run did not finish');
    assert(terminal.status.state==='completed','Workflow run failed: '+terminal.metadata?.error?.message);
    const response=await api('tasks/'+result.id+'/events','GET',undefined,undefined,scope);
    for(const id of ['evidence','knowledge','result']) {
      assert(response.events.some(event=>event.step===id&&event.kind==='step'&&event.status==='completed'),id+' did not execute');
    }
    assert(response.events.some(event=>event.step==='knowledge'&&event.kind==='branch'&&event.selected.includes('evidence')),
      'Knowledge did not use the validation output');
    const without=await load(false);
    drag('松手后添加资料校验');
    const added=graph().nodes.find(item=>item.data.type==='validation');
    assert(added && graph().edges.some(item=>item.source==='prediction'&&item.target===added.id) &&
      graph().edges.some(item=>item.source===added.id&&item.target==='knowledge'),'A missing validator was not inserted');
    $('desktop-workflow-undo').click();
    assert(graph().nodes.length===without.nodes.length && graph().edges.length===without.edges.length,
      'Undo did not remove the inserted validator and both links');
    window.knowledgeConnectionQA={state:'passed',existingValidator:true,newValidator:true,undo:true,executed:true};
  })().catch(error=>{window.knowledgeConnectionQA={state:'failed',error:error.message,stack:error.stack,hint:hint()};});
})()
