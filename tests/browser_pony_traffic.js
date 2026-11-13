/* Controlled routes on the REAL office floor/render loop. Disposable :8768 only. */
(() => {
  if(location.port!=='8768')throw Error('Use the disposable visual fixture');
  const base=PonyFloor.Floor.prototype.tick,plan=PonyFloor.Floor.prototype.path,plans=[],frameTimes=[];
  let initialized=false,previous=0;
  PonyFloor.Floor.prototype.path=function(...args){const start=performance.now();const result=plan.apply(this,args);plans.push(performance.now()-start);return result;};
  PonyFloor.Floor.prototype.tick=function(dt,reduced){
    if(!initialized){
      initialized=true;window.__trafficFloor=this;this.jobs.clear();this.queue=[];this.gateOwner=null;this.doorDirection=null;this.door=0;this.nextRoam=Infinity;
      this.actors.forEach(a=>{a.present=true;a.state='running';a.pose=a.station?'seated':'idle';a.x=a.deskX;a.y=a.deskY+70;});
      const risk=this.actors.find(a=>a.id==='risk');risk.state='idle';risk.pose='waiting';risk.resident=true;
      for(const [id,x,end,heading]of [['main',300,700,1],['prediction',700,300,-1]]){
        const actor=this.actors.find(a=>a.id===id);Object.assign(actor,{x,y:325,pose:'walking',speed:0,heading});
        this.jobs.set(id,{id,stage:'stroll',elapsed:0,path:[{x:end,y:325}],entry:false,exit:false});
      }
    }
    const now=performance.now();if(previous)frameTimes.push(now-previous);previous=now;
    return base.call(this,dt,reduced,false);
  };
  const canvas=document.createElement('canvas');canvas.width=800;canvas.height=600;const ctx=canvas.getContext('2d');
  const stream=canvas.captureStream(0),recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8',videoBitsPerSecond:2200000}),chunks=[];
  const started=performance.now(),headings=new Map(),passed=new Set();let minimum=Infinity,turns=0,frames=0;
  const css='.office-desk-name{fill:#556367;font:12px sans-serif}.office-floor{fill:url(#pony-daylight)}.office-door-frame{fill:#aeb9c3}.office-door-leaf{fill:#e0e5e9;stroke:#a3afb9}.office-floor-caption,.office-floor-line{display:none}';
  window.__trafficRecord={state:'recording'};
  recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
  recorder.onstop=async()=>{
    stream.getTracks().forEach(t=>t.stop());
    const reader=new FileReader();reader.onload=()=>{window.__trafficVideo=reader.result;};reader.readAsDataURL(new Blob(chunks,{type:'video/webm'}));
    const floor=window.__trafficFloor,stats=values=>{const sorted=values.slice().sort((a,b)=>a-b);return{count:values.length,median:sorted[Math.floor(sorted.length*.5)],p95:sorted[Math.floor(sorted.length*.95)],max:sorted.at(-1)};};
    const target=document.querySelector('[data-office-desk="risk"] .office-wall-clock');
    const before=target?.dataset.clock;PonyOffice.view('paused');await new Promise(resolve=>setTimeout(resolve,1150));PonyOffice.view('analysis');
    const actual=document.querySelector('[data-office-desk="risk"] .office-wall-clock')?.dataset.clock,expected=PonyScreen.clock().time;
    const actor=floor.actors.find(a=>a.id==='risk');actor.state='running';PonyOffice.view('analysis');
    const taskPriority=document.querySelector('[data-office-desk="risk"] .office-screen').dataset.mode==='task';
    actor.state='idle';PonyOffice.view('analysis');
    const errors=[];if(passed.size!==2)errors.push('Both directions did not pass');if(minimum<PonyFloor.radius*2+3-.01)errors.push('Actor overlap');if(!turns)errors.push('No heading changes');if(actual!==expected)errors.push('Restored wall clock stale');if(!taskPriority)errors.push('Clock did not yield to task');
    window.__trafficRecord={state:errors.length?'failed':'done',frames,seconds:(performance.now()-started)/1000,passed:[...passed],minimum,turns,metrics:{...floor.metrics},planningMs:stats(plans),frameMs:stats(frameTimes),clock:{before,actual,expected,taskPriority},errors,note:'Synthetic routes injected only on disposable fixture; actual Floor.tick and PonyRig render, continuous wall time. Frame timing includes video serialization overhead.'};
    PonyFloor.Floor.prototype.tick=base;PonyFloor.Floor.prototype.path=plan;
  };
  recorder.start();
  async function draw(){
    const floor=window.__trafficFloor;if(floor){
      const actors=floor.actors.filter(a=>a.present);
      for(let a=0;a<actors.length;a++)for(let b=a+1;b<actors.length;b++)minimum=Math.min(minimum,PonyFloor.distance(actors[a],actors[b]));
      for(const actor of actors){if(headings.has(actor.id)&&headings.get(actor.id)!==actor.heading)turns++;headings.set(actor.id,actor.heading);}
      if(actors.find(a=>a.id==='main').x>690)passed.add('main');if(actors.find(a=>a.id==='prediction').x<310)passed.add('prediction');
    }
    const source=document.querySelector('.office-stage>svg').cloneNode(true);source.setAttribute('xmlns','http://www.w3.org/2000/svg');source.setAttribute('width',800);source.setAttribute('height',547);source.setAttribute('data-theme','light');source.classList.add('office-stage');
    const style=document.createElementNS(source.namespaceURI,'style');style.textContent=css;source.prepend(style);
    const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(source));await image.decode();
    ctx.fillStyle='#eff2f0';ctx.fillRect(0,0,800,600);ctx.drawImage(image,0,32);
    ctx.fillStyle='#283c41';ctx.font='17px sans-serif';ctx.fillText('相向通行 · 桌间绕行 · 转身与归位',22,24);
    ctx.font='12px sans-serif';ctx.fillText('隔离验收路线 · 原场景模型与渲染 · 未调用外部模型或邮件服务',22,592);frames++;stream.getVideoTracks()[0].requestFrame();
    if(performance.now()-started>=32000){recorder.stop();return;}requestAnimationFrame(draw);
  }
  draw().catch(error=>{window.__trafficRecord={state:'failed',error:error.stack};recorder.stop();});
})();
