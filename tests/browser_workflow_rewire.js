/* Run via gstack browse eval on the disposable desktop console. */
(() => {
  window.edgeRewireCheck = {state:'running'};
  (async () => {
    const assert = (value,message) => {if(!value) throw Error(message);};
    const wait = async (predicate) => {
      for(let n=0;n<100;n++) {
        if(predicate())return;
        await new Promise(resolve=>setTimeout(resolve,50));
      }
      throw Error('Canvas fixture did not load');
    };
    await wait(()=>memoryKey && window.WorkflowChat && window.DesktopWorkbench);
    DesktopWorkbench.setMode('focus');
    DesktopWorkbench.useDefinition({id:'rewire-check-'+crypto.randomUUID(),revision:'fixture',name:'连线验收',mode:'custom',
      graph:{version:2,nodes:[],edges:[]}});
    WorkflowChat.showCanvas();
    const node = (id,x,y,type='retrieval') => ({id,position:{x,y},data:{label:id,type,detail:'Browser fixture'}});
    const graph={version:2,nodes:[node('start',0,0),node('first',320,0),node('next',640,0),node('report',320,250,'report')],
      edges:[{id:'sample-link',source:'start',target:'first',condition:'has_facts'}]};
    const file=document.getElementById('desktop-workflow-file'), transfer=new DataTransfer();
    transfer.items.add(new File([JSON.stringify(graph)],'edges.json',{type:'application/json'}));
    file.files=transfer.files;file.dispatchEvent(new Event('change',{bubbles:true}));
    const edge=()=>document.querySelector('[data-edge-id=sample-link]');
    await wait(edge);
    if(!$('desktop-workflow-inspector').hidden)$('desktop-node-close').click();
    if(!$('workflow-node-library').hidden)$('workflow-library-toggle').click();
    document.querySelector('[data-viewport-action=fit]').click();
    const canvas=document.getElementById('desktop-workflow-canvas');
    const send=(target,name,x,y)=>target.dispatchEvent(new PointerEvent(name,{bubbles:true,cancelable:true,pointerId:1,button:0,clientX:x,clientY:y}));
    canvas.setPointerCapture=()=>{}; // The fixture dispatches pointer events without a native pointer.
    const current=()=>DesktopWorkbench.canvasSnapshot().graph;
    const stored=()=>current().edges.find(item=>item.id==='sample-link');
    const undo=()=>$('desktop-workflow-undo').click();
    edge().dispatchEvent(new MouseEvent('click',{bubbles:true}));
    assert(edge().classList.contains('selected'),'Click did not select the connection');
    const circles=[...canvas.querySelectorAll('#desktop-workflow-edge-paths circle')];
    assert(circles.length===1 && circles[0].closest('[data-edge-insert="sample-link"]'),
      'A selected connection should only show the insertion control');
    const rewire=(end,to,{fromPlus=false,port=null,near=false}={})=>{
      const path=edge(), fraction=end==='source'?.23:.77;
      const point=path.getPointAtLength(path.getTotalLength()*fraction).matrixTransform(path.getScreenCTM());
      const plus=document.querySelector('[data-edge-insert="sample-link"] circle')?.getBoundingClientRect();
      const start=fromPlus?{x:plus.x+plus.width/2,y:plus.y+plus.height/2}:{x:point.x,y:point.y+6};
      const stroke=document.elementFromPoint(start.x,start.y);
      assert(fromPlus?stroke?.closest('[data-edge-insert]'):stroke?.dataset.edgeHit==='sample-link',
        'The connection cannot receive mouse input');
      const node=document.querySelector(`[data-workflow-node=${to}]`);
      const bounds=(port?node.querySelector('.desktop-flow-port.'+port):node).getBoundingClientRect();
      const x=near==='right'?bounds.right+14:near==='left'?bounds.left-14:bounds.x+bounds.width/2,y=bounds.y+bounds.height/2;
      if(!near)assert(document.elementFromPoint(x,y)?.closest('[data-workflow-node]')?.dataset.workflowNode===to,'Drop target is covered');
      send(stroke,'pointerdown',start.x,start.y);
      send(canvas,'pointermove',x,y);
      const preview=document.querySelector('.desktop-flow-edge-preview');
      assert(preview.hasAttribute('d'),'Drag preview missing when starting '+(fromPlus?'on the midpoint':'from the line'));
      const snapping=preview.classList.contains('snapped');
      send(canvas,'pointerup',x,y);
      return snapping;
    };
    assert(rewire('target','next',{port:'out'}),'Direct right port did not snap');
    assert(stored().source==='next'&&stored().target==='first','Right port did not change the source when dragging from the target side');
    undo();
    assert(rewire('source','next',{port:'in'}),'Direct left port did not snap');
    assert(stored().source==='start'&&stored().target==='next','Left port did not change the target when dragging from the source side');
    undo();
    assert(rewire('target','next',{fromPlus:true,near:'left'}),'Drop near the left edge did not snap');
    assert(stored().target==='next'&&stored().condition==='has_facts'&&stored().id==='sample-link','Target did not reconnect');
    assert(rewire('target','first',{near:'right'}),'Drop near the right edge did not snap');
    assert(stored().source==='first'&&stored().target==='next','Source did not reconnect');
    assert(!rewire('target','report',{port:'in'}),'Incompatible drop was marked compatible');
    assert(stored().target==='report' && edge().hasAttribute('data-invalid'),'Incompatible drop was not kept and marked in the draft');
    undo();
    assert(stored().target==='next','Undo did not restore the compatible destination');
    undo();
    assert(stored().source==='start'&&stored().target==='next','Undo did not restore previous endpoints');

    document.querySelector('[data-workflow-node="first"] .desktop-flow-port.out').click();
    document.querySelector('[data-workflow-node="next"] .desktop-flow-port.in').click();
    const snapshot=JSON.stringify(current());
    assert(current().edges.length===2,'Could not add the second link');
    assert(!rewire('source','first',{port:'out'}),'Duplicate connection appeared valid');
    assert(JSON.stringify(current())===snapshot && $('desktop-workflow-message').textContent.includes('已有连线'),
      'Blocked right port silently reconnected to a different port');

    window.openRewireMenu=()=>{
      const path=edge(), point=path.getPointAtLength(path.getTotalLength()*.10).matrixTransform(path.getScreenCTM());
      const hit=document.elementFromPoint(point.x,point.y+6);
      assert(hit?.dataset.edgeHit==='sample-link','The cable hit area is missing');
      hit.dispatchEvent(new MouseEvent('contextmenu',{button:2,bubbles:true,cancelable:true,clientX:point.x,clientY:point.y+6}));
      const menu=canvas.querySelector('.canvas-context-menu[data-edge-menu]:not([hidden])');
      assert(menu && menu.querySelectorAll('[role=menuitem]').length===1,'Wire did not open its own context menu');
      return menu;
    };
    const menu=window.openRewireMenu();
    assert(menu.textContent.trim()==='删除','Wire menu should display only the delete label');
    menu.querySelector('button').click();
    assert(!stored()&&current().edges.length===1&&current().nodes.length===4,'Deleting one wire affected other wires or nodes');
    undo();assert(JSON.stringify(current())===snapshot,'Undo did not restore the removed wire');
    $('desktop-workflow-redo').click();assert(!stored(),'Redo did not remove the wire again');
    undo();
    const keyboard=window.openRewireMenu();
    keyboard.querySelector('button').dispatchEvent(new KeyboardEvent('keydown',{key:'Delete',bubbles:true,cancelable:true}));
    assert(keyboard.hidden&&!stored()&&current().nodes.length===4,'Delete shortcut did not target the clicked wire');
    undo();
    window.edgeRewireCheck={state:'passed',source:true,target:true,midpoint:true,nearCard:true,condition:true,invalidDraft:true,duplicateBlocked:true,deleteMenu:true,undo:true};
  })().catch(error=>{window.edgeRewireCheck={state:'failed',error:error.message};});
})()
