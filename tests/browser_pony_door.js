/* Run through gstack browse on the disposable :8768 fixture. Records live SVG frames. */
(() => {
  if(location.hostname!=='127.0.0.1'||location.port!=='8768') throw Error('Use the disposable browser fixture on port 8768');
  const office=window.PonyOffice;
  office.reset('door-motion-fixture',false);
  office.sync({id:'door-motion-fixture',status:{state:'working'}},[
    {seq:1,kind:'step',step:'prediction',status:'running',label:'动作验收 · 模拟任务'}
  ]);
  const canvas=document.createElement('canvas');canvas.width=960;canvas.height=720;
  const ctx=canvas.getContext('2d'),stream=canvas.captureStream(20);
  const recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8',videoBitsPerSecond:1800000});
  const chunks=[],started=performance.now(),phases=new Set(),cycles=new Set(),errors=[];
  let finishedTask=false,contacts=0,maxError=0,frames=0,done=false,hiddenSamples=0,thresholdSamples=0;
  const labels={align:'停稳并看向把手',reach:'抬起前蹄',grip:'握住把手',swing:'随门扇推拉',release:'松开并收回前蹄',settle:'调整姿势准备行走'};
  window.__doorRecord={state:'recording'};
  recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
  recorder.onstop=()=>{
    stream.getTracks().forEach(track=>track.stop());
    const reader=new FileReader();
    reader.onload=()=>{
      window.__doorVideo=reader.result;
      if(cycles.size!==4)errors.push('Missing an interior/exterior opening or closing cycle');
      if(!contacts)errors.push('No live handle contact was sampled');
      if(!hiddenSamples||!thresholdSamples)errors.push('Missing hidden or clipped doorway samples');
      window.__doorRecord={state:errors.length?'failed':'done',contacts,maxError,frames,hiddenSamples,thresholdSamples,cycles:[...cycles],phases:[...phases],errors};
    };
    reader.readAsDataURL(new Blob(chunks,{type:'video/webm'}));
  };
  recorder.start();
  async function draw() {
    if(done)return;
    try {
      const snap=office.snapshot(),actor=snap.actors.find(a=>a.id==='prediction');
      if(actor.pose==='seated'&&!finishedTask) {
        finishedTask=true;office.sync({id:'door-motion-fixture',status:{state:'completed'}},[]);
      }
      let caption=actor.pose==='walking'?'迈步通过门口':actor.pose==='seated'?'到达工位，随后展示离室':'前往门口';
      for(const pony of document.querySelectorAll('[data-door-phase]')) {
        const phase=pony.dataset.doorPhase,side=pony.dataset.doorSide;
        phases.add(phase);
        const model=snap.actors.find(a=>a.id===pony.dataset.pony);
        const closing=model.pose==='door-close';
        if(pony.dataset.pony==='prediction') {
          caption=`${closing?'关门':'开门'} · ${labels[phase]}`;
          if(phase==='swing')cycles.add(`${side}-${closing?'close':'open'}`);
        }
        if(pony.dataset.portalState==='outside') {
          hiddenSamples++;
          if(pony.getAttribute('display')!=='none'&&errors.length<8)errors.push('Outside pony is visible');
          if((pony.getAttribute('tabindex')!=='-1'||pony.getAttribute('aria-hidden')!=='true')&&errors.length<8)errors.push('Hidden pony remains interactive');
        }
        if((phase==='grip'||phase==='swing')&&pony.getAttribute('display')!=='none') {
          const hoof=pony.querySelector('.pony-arm-right .pony-hoof');
          const point=new DOMPoint(Number(hoof.getAttribute('cx')),Number(hoof.getAttribute('cy'))).matrixTransform(hoof.getScreenCTM());
          const handle=document.querySelector(`[data-door-side="${side}"]`);
          const target=new DOMPoint(0,0).matrixTransform(handle.getScreenCTM());
          const error=Math.hypot(point.x-target.x,point.y-target.y);
          maxError=Math.max(maxError,error);contacts++;
          if(error>.15&&errors.length<8)errors.push(`${side} ${phase} ${error.toFixed(3)}px`);
        }
      }
      for(const pony of document.querySelectorAll('[data-portal-state="threshold"]')) {
        thresholdSamples++;
        if(pony.parentNode.getAttribute('clip-path')!=='url(#pony-portal-clip)'&&errors.length<8)errors.push('Crossing pony has no aperture clip');
        if(snap.door!==1&&errors.length<8)errors.push('Door closed before full transit');
      }
      const source=document.querySelector('.office-stage>svg').cloneNode(true);
      source.setAttribute('viewBox','-105 395 280 215');source.setAttribute('width','960');source.setAttribute('height','720');
      source.querySelector('.office-floor').setAttribute('fill','#f3f5f2');
      source.querySelector('.office-door-frame').setAttribute('fill','#aeb9c3');
      source.querySelector('.office-door-leaf').setAttribute('stroke','#a3afb9');
      const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(source));
      await image.decode();
      ctx.fillStyle='#f3f5f2';ctx.fillRect(0,0,960,720);ctx.drawImage(image,0,0);
      ctx.fillStyle='#26373e';ctx.font='22px sans-serif';ctx.fillText(caption,30,42);
      ctx.fillStyle='#64767b';ctx.font='15px sans-serif';ctx.fillText('实际办公室动画 · 模拟任务驱动 · 开关门双侧接触检查',30,690);
      frames++;
      const elapsed=(performance.now()-started)/1000;
      if((finishedTask&&!actor.present&&cycles.size===4)||elapsed>55) {
        done=true;recorder.stop();return;
      }
      setTimeout(draw,45);
    } catch(error) {
      errors.push(String(error));done=true;recorder.stop();
    }
  }
  draw();
})();
