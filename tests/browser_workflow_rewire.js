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
    window.DesktopWorkbench.setMode('focus');
    const node = (id,x,y,type='retrieval') => ({id,position:{x,y},data:{label:id,type,detail:'Browser fixture'}});
    const graph={version:2,nodes:[node('start',0,0),node('first',320,0),node('next',640,0),node('report',320,250,'report')],
      edges:[{id:'sample-link',source:'start',target:'first',condition:'has_facts'}]};
    const file=document.getElementById('desktop-workflow-file'), transfer=new DataTransfer();
    transfer.items.add(new File([JSON.stringify(graph)],'edges.json',{type:'application/json'}));
    file.files=transfer.files;file.dispatchEvent(new Event('change',{bubbles:true}));
    const edge=()=>document.querySelector('[data-edge-id=sample-link]');
    await wait(edge);
    document.querySelector('[data-viewport-action=fit]').click();
    const canvas=document.getElementById('desktop-workflow-canvas');
    const send=(target,name,x,y)=>target.dispatchEvent(new PointerEvent(name,{bubbles:true,cancelable:true,pointerId:1,button:0,clientX:x,clientY:y}));
    canvas.setPointerCapture=()=>{}; // The fixture dispatches pointer events without a native pointer.
    const stored=()=>JSON.parse(localStorage.getItem('stock_predict_mailer.desktop.workflow.v1.draft')).graph.edges[0];
    const rewire=(end,to)=>{
      edge().dispatchEvent(new MouseEvent('click',{bubbles:true}));
      const handle=document.querySelector(`[data-edge-end=${end}]`);
      assert(handle,'Expected handle for '+end);
      const bounds=handle.getBoundingClientRect();
      assert(document.elementFromPoint(bounds.x+bounds.width/2,bounds.y+bounds.height/2)===handle,'Handle cannot receive mouse input');
      const nodeBounds=document.querySelector(`[data-workflow-node=${to}]`).getBoundingClientRect();
      const x=nodeBounds.x+nodeBounds.width/2,y=nodeBounds.y+nodeBounds.height/2;
      assert(document.elementFromPoint(x,y)?.closest('[data-workflow-node]')?.dataset.workflowNode===to,'Drop target is covered');
      send(handle,'pointerdown',bounds.x+bounds.width/2,bounds.y+bounds.height/2);
      send(canvas,'pointermove',x,y);
      assert(document.querySelector('.desktop-flow-edge-preview').hasAttribute('d'),'Drag preview missing');
      send(canvas,'pointerup',x,y);
    };
    rewire('target','next');
    assert(stored().target==='next'&&stored().condition==='has_facts'&&stored().id==='sample-link','Target did not reconnect');
    rewire('source','first');
    assert(stored().source==='first'&&stored().target==='next','Source did not reconnect');
    rewire('target','report');
    assert(stored().target==='next','Incompatible target replaced the connection');
    document.getElementById('desktop-workflow-undo').click();
    assert(stored().source==='start'&&stored().target==='next','Undo did not restore previous endpoints');
    window.edgeRewireCheck={state:'passed',source:true,target:true,condition:true,rejectedIncompatible:true,undo:true};
  })().catch(error=>{window.edgeRewireCheck={state:'failed',error:error.message};});
})()
