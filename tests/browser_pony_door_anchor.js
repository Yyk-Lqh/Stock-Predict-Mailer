/* Screenshot/geometry verification only; deliberately creates no video. */
(async()=>{
  if(location.port!=='8768')throw Error('Use the disposable fixture');
  window.__doorAnchorCheck={state:'running'};
  document.querySelector('.nav [data-view="analysis"]').click();
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  PonyOffice.reset('door-anchor-check',false);
  PonyOffice.sync({id:'door-anchor-check',status:{state:'working'}},[{seq:1,kind:'step',step:'prediction',status:'running',label:'门口位置验收 · 模拟任务'}]);
  let completed=false,contacts=0,maxError=0;
  for(let i=0;i<800;i++){
    const snapshot=PonyOffice.snapshot(),actor=snapshot.actors.find(a=>a.id==='prediction');
    if(actor.pose==='seated'&&!completed){completed=true;PonyOffice.sync({id:'door-anchor-check',status:{state:'completed'}},[]);}
    for(const pony of document.querySelectorAll('[data-door-phase]')){
      if(!['grip','swing'].includes(pony.dataset.doorPhase)||pony.getAttribute('display')==='none')continue;
      const hoof=pony.querySelector('.pony-arm-right .pony-hoof'),handle=document.querySelector(`.office-door-handle[data-door-side="${pony.dataset.doorSide}"]`);
      const a=new DOMPoint(Number(hoof.getAttribute('cx')),Number(hoof.getAttribute('cy'))).matrixTransform(hoof.getScreenCTM());
      const b=new DOMPoint(0,0).matrixTransform(handle.getScreenCTM());
      maxError=Math.max(maxError,Math.hypot(a.x-b.x,a.y-b.y));contacts++;
    }
    if(completed&&!actor.present&&snapshot.door===0){
      const door=document.querySelector('.office-door-frame').getBoundingClientRect(),composer=document.getElementById('analysis-composer').getBoundingClientRect();
      const valid=contacts>0&&maxError<.2&&door.right<composer.left&&Math.abs(door.bottom-composer.bottom)<1;
      window.__doorAnchorCheck={state:valid?'done':'failed',contacts,maxError,arrivedAndExited:true,doorLeft:door.left,doorBottom:door.bottom,composerLeft:composer.left,composerBottom:composer.bottom};return;
    }
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  window.__doorAnchorCheck={state:'failed',reason:'arrival/exit timeout',contacts,maxError,snapshot:PonyOffice.snapshot()};
})().catch(error=>{window.__doorAnchorCheck={state:'failed',error:error.stack};});
