/* Run via gstack browse eval in a fresh disposable console at port 18768. */
(() => {
  if (location.hostname !== '127.0.0.1' || location.port !== '18768') throw Error('Use the disposable workflow fixture');
  const node = id => document.querySelector(`[data-workflow-node="${id}"]`);
  const button = label => [...document.querySelectorAll('#desktop-focus button')].find(b => b.textContent === label && b.getClientRects().length);
  const assert = (value,message) => { if (!value) throw Error(message); };
  const wait = async (test, message) => {
    const until = Date.now()+18000;
    do {
      const value=test();
      if(value) return value;
      await new Promise(resolve=>setTimeout(resolve,80));
    } while(Date.now()<until);
    throw Error(message);
  };
  const latest = () => {
    try{return JSON.parse(document.getElementById('task-output').textContent);}catch(_){return null;}
  };
  const events = async task => (await api(`tasks/${task.id}/events?after=0`)).events;
  const run = async () => {
    const old=latest()?.id;
    button('运行流程').click();
    return wait(()=>{
      const task=latest();
      return task?.id!==old && task?.status?.state==='completed' && task;
    },'Composer did not complete the workflow: '+(document.getElementById('notice').textContent||''));
  };
  window.workflowBrowserResult = {state:'running'};
  (async()=>{
    await wait(()=>window.DesktopWorkbench && document.querySelector('.desktop-nav-collapse'),'Workbench did not mount');
    await wait(()=>csrf,'Session not ready');
    window.DesktopWorkbench.setMode('focus');
    const nav=document.querySelector('.desktop-nav-collapse');
    nav.click();assert(nav.getAttribute('aria-expanded')==='false','Nav did not collapse');nav.click();
    window.DesktopWorkbench.setMode('hall');
    assert(!document.body.classList.contains('desktop-focus-view'),'Hall mode failed');
    window.DesktopWorkbench.setMode('focus');
    await document.getElementById('try-sample').onclick();
    await wait(()=>document.getElementById('task-data').value.includes('console-mock'),'Synthetic sample missing');
    const system=await run();
    const defaultEvents=await events(system);
    assert(system.metadata.workflow.mode==='system','Composer did not freeze system graph');
    assert(defaultEvents.some(e=>e.step==='report'&&e.status==='completed'),'Report did not produce a completion event');
    assert(!defaultEvents.some(e=>e.step==='mail'),'Unrequested email ran');

    button('编辑').click();document.querySelector('.workflow-file-menu summary').click();button('复制系统模板').click();
    const first=await run();
    const original=await events(first);
    assert(original.some(e=>e.step==='report'&&e.kind==='branch'&&e.selected.join() === 'charts'),'Baseline report did not consume charts');
    button('编辑').click();node('report').click();
    const condition=[...document.querySelectorAll('#desktop-workflow-inspector select')].find(el=>el.getAttribute('aria-label')?.includes('图表 → 报告'));
    assert(condition,'Editable typed branch is missing');
    condition.value='notify';condition.dispatchEvent(new Event('change',{bubbles:true}));
    const form=document.querySelector('.desktop-flow-connect');
    form.elements.source.value='main';form.elements.target.value='report';form.elements.condition.value='no_notify';form.requestSubmit();
    button('保存流程 *').click();
    const changed=await run();
    const changedEvents=await events(changed);
    assert(changedEvents.some(e=>e.step==='report'&&e.kind==='branch'&&e.selected.join()==='main'),'Changed branch did not feed the report');
    assert(first.metadata.workflow.version!==changed.metadata.workflow.version,'Version did not change');
    button('运行记录').click();
    const history=await wait(()=>[...document.querySelectorAll('dialog[open] .workflow-run-list button')].find(item=>
      item.textContent.includes(first.metadata.workflow.version.slice(0,8))),'Frozen run was not listed in history');
    history.click();
    await wait(()=>document.getElementById('desktop-workflow-inspector').textContent.includes(first.metadata.workflow.version),
      'Historical view did not show the original version');

    button('调试').click();node('main').click();button('单测所选节点').click();
    const debug=document.querySelector('dialog.workflow-run-dialog[open]');
    assert(debug,'Debug dialog did not open');
    debug.querySelector('form').requestSubmit();
    await wait(()=>!debug.open,'Single-node test did not close');
    assert(node('main').dataset.status==='completed','Debug node did not complete');
    button('编辑').click();
    const draftBefore=localStorage.getItem('stock_predict_mailer.desktop.workflow.v1');
    const file=document.getElementById('desktop-workflow-file'), transfer=new DataTransfer();
    transfer.items.add(new File(['{bad json'],'bad.json',{type:'application/json'}));file.files=transfer.files;
    file.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>document.getElementById('desktop-workflow-message').textContent.includes('导入失败'),'Missing invalid import error');
    assert(localStorage.getItem('stock_predict_mailer.desktop.workflow.v1')===draftBefore && node('report'),'Invalid import damaged saved graph');
    node('prediction').focus();
    const before=parseFloat(node('prediction').style.left);
    node('prediction').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));
    assert(parseFloat(node('prediction').style.left)===before+8,'Keyboard movement failed');
    sessionStorage.setItem('workflow-browser-reload',JSON.stringify({position:before+8,version:changed.metadata.workflow.version}));
    window.workflowBrowserResult={state:'passed',system:system.id,baseline:first.id,changed:changed.id,
      plan:defaultEvents.filter(e=>e.kind==='step'&&e.status==='completed').map(e=>e.step),
      reportBranches:['charts','main'],version:changed.metadata.workflow.version,debug:true};
  })().catch(error=>{window.workflowBrowserResult={state:'failed',error:error.message};});
  return 'workflow browser checks started';
})()
