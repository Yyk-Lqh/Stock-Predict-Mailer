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
    const stored=()=>AnalysisMode.read('workflow-draft', 'professional').graph.edges[0];
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
      const x=near?bounds.right+14:bounds.x+bounds.width/2,y=near?bounds.bottom-8:bounds.y+bounds.height/2;
      if(!near)assert(document.elementFromPoint(x,y)?.closest('[data-workflow-node]')?.dataset.workflowNode===to,'Drop target is covered');
      send(stroke,'pointerdown',start.x,start.y);
      send(canvas,'pointermove',x,y);
      const preview=document.querySelector('.desktop-flow-edge-preview');
      assert(preview.hasAttribute('d'),'Drag preview missing when starting '+(fromPlus?'on the midpoint':'from the line'));
      const snapping=preview.classList.contains('snapped');
      send(canvas,'pointerup',x,y);
      return snapping;
    };
    assert(rewire('target','next',{fromPlus:true,near:true}),'Drop near the target card did not snap');
    assert(stored().target==='next'&&stored().condition==='has_facts'&&stored().id==='sample-link','Target did not reconnect');
    assert(rewire('target','first',{port:'out'}),'The explicit output port did not select the source endpoint');
    assert(stored().source==='first'&&stored().target==='next','Source did not reconnect');
    assert(!rewire('target','report'),'Incompatible drop was marked compatible');
    assert(stored().target==='report' && edge().hasAttribute('data-invalid'),'Incompatible drop was not kept and marked in the draft');
    document.getElementById('desktop-workflow-undo').click();
    assert(stored().target==='next','Undo did not restore the compatible destination');
    document.getElementById('desktop-workflow-undo').click();
    assert(stored().source==='start'&&stored().target==='next','Undo did not restore previous endpoints');
    window.edgeRewireCheck={state:'passed',source:true,target:true,midpoint:true,nearCard:true,condition:true,invalidDraft:true,undo:true};
  })().catch(error=>{window.edgeRewireCheck={state:'failed',error:error.message};});
})()
