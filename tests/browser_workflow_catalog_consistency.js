/* gstack browse. Use a fresh browser draft to check catalog version and insertion. */
window.checkWorkflowCatalog = async ({stale=false}={}) => {
  const wait=async (check,message)=>{
    for(let i=0;i<120;i++){
      const value=check();if(value)return value;
      await new Promise(resolve=>setTimeout(resolve,70));
    }
    throw Error(message);
  };
  const assert=(condition,message)=>{if(!condition)throw Error(message);};
  await wait(()=>window.DesktopWorkbench&&$('workflow-canvas-nav'),'Console did not initialize');
  DesktopWorkbench.setMode('focus');$('workflow-canvas-nav').click();
  await wait(()=>$('wfcat-new')&&!$('wfcat-new').closest('.workflow-catalog').hidden,'Directory did not open');
  $('wfcat-new').click();
  const entry=await wait(()=>$('workflow-canvas-empty')&&!$('workflow-canvas-empty').hidden&&$('workflow-canvas-empty'),'New canvas did not open');
  entry.click();
  const library=$('workflow-node-library');
  const status=()=>library.querySelector('[role=status]').textContent;
  const row=kind=>library.querySelector(`[data-node-type="${kind}"]`);
  const retry=library.querySelector('[data-catalog-retry]');
  await wait(()=>!row('input').hidden&&!row('input').disabled,'Catalog did not return the existing user input node');
  if(stale){
    assert(row('llm').disabled && row('llm').textContent.includes('版本不一致'),'Unregistered node was not marked as a version mismatch');
    assert(status().includes('前后端版本不一致')&&!retry.hidden,'Version mismatch should show retry');
    const original=window.fetch;
    try {
      window.fetch=(path,...args)=>path==='/api/workflows/catalog'?Promise.reject(Error('模拟断线')):original(path,...args);
      retry.click();await wait(()=>status().includes('读取失败')&&!retry.hidden,'Network failure should offer retry');
      window.fetch=original;
      retry.click();await wait(()=>status().includes('版本不一致'),'Retry did not read the authoritative catalog');
    } finally { window.fetch=original; }
    return {staleCatalogExplained:true,retryWorks:true};
  }
  row('input').click();
  const kinds=['llm','output','classifier','branch','human','iteration','loop','code','template','aggregate','document','assign','extract','http','list'];
  for(const kind of kinds){
    if(library.hidden)$('workflow-library-toggle').click();
    const button=row(kind);
    assert(!button.hidden&&!button.disabled,`${kind} is not available`);
    button.click();
    const node=DesktopWorkbench.canvasSnapshot().graph.nodes.find(item=>item.data.type===kind);
    assert(node&&document.querySelector(`[data-workflow-node="${node.id}"]`),`${kind} was not added to the canvas`);
  }
  assert(!library.textContent.includes('待接入')&&retry.hidden,'Unexpected disconnected catalog state');
  return {nodesAdded:kinds.length,registered:true};
};
