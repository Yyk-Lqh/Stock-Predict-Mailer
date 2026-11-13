/* Real floor + render loop, controlled routes on disposable fixture. No media. */
(async()=>{
  if(location.port!=='8768')throw Error('Use disposable fixture');
  const prototype=PonyFloor.Floor.prototype,base=prototype.tick,plan=prototype.path;
  const timings=[],frames=[],headings=new Map(),passed=new Set();let initialized=false,minimum=Infinity,turns=0,last=0;
  window.__hallTraffic={state:'running'};
  prototype.path=function(...args){const start=performance.now(),result=plan.apply(this,args);timings.push(performance.now()-start);return result;};
  prototype.tick=function(dt,reduced){
    if(!initialized){
      initialized=true;window.__hallTrafficFloor=this;this.jobs.clear();this.queue=[];this.nextRoam=Infinity;this.gateOwner=null;this.doorDirection=null;this.door=0;
      this.actors.forEach(a=>{a.present=true;a.state='running';a.pose=a.station?'seated':'idle';a.x=a.deskX;a.y=a.deskY+70;});
      for(const [id,x,end,heading]of [['main',300,700,1],['prediction',700,300,-1]]){const a=this.actors.find(a=>a.id===id);Object.assign(a,{x,y:325,heading,speed:0,pose:'walking'});this.jobs.set(id,{id,stage:'stroll',elapsed:0,path:[{x:end,y:325}],entry:false,exit:false});}
    }
    const now=performance.now();if(last)frames.push(now-last);last=now;return base.call(this,dt,reduced,false);
  };
  const start=performance.now();let failure='';
  try{
    for(let i=0;i<500;i++){
      const f=window.__hallTrafficFloor;
      if(f){
        const actors=f.actors.filter(a=>a.present);
        for(let a=0;a<actors.length;a++)for(let b=a+1;b<actors.length;b++)minimum=Math.min(minimum,PonyFloor.distance(actors[a],actors[b]));
        if(minimum<PonyFloor.radius*2+3-.01)throw Error('Actor overlap');
        for(const a of actors){if(headings.has(a.id)&&headings.get(a.id)!==a.heading)turns++;headings.set(a.id,a.heading);if(a.pose==='walking'&&f.blocked(a,a,['dock','undock'].includes(f.motion(a.id)?.stage)))throw Error('Furniture collision');}
        const main=actors.find(a=>a.id==='main'),prediction=actors.find(a=>a.id==='prediction');
        if(main.x>690)passed.add('main');if(prediction.x<310)passed.add('prediction');
        if(passed.size===2&&main.pose==='seated'&&prediction.pose==='seated')break;
      }
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    if(passed.size!==2)throw Error('Opposing paths did not complete');
    const actor=window.__hallTrafficFloor.actors.find(a=>a.id==='risk');actor.state='idle';actor.pose='waiting';actor.resident=true;
    PonyOffice.view('paused');await new Promise(resolve=>setTimeout(resolve,1150));PonyOffice.view('analysis');
    const clock=document.querySelector('[data-office-desk=risk] .office-wall-clock')?.dataset.clock;
    if(clock!==PonyScreen.clock().time)throw Error('Wall-clock restoration stale');
  }catch(error){failure=error.message;}
  finally{prototype.tick=base;prototype.path=plan;}
  const stats=values=>{const sorted=values.slice().sort((a,b)=>a-b);return{count:values.length,median:sorted[Math.floor(sorted.length*.5)],p95:sorted[Math.floor(sorted.length*.95)],max:sorted.at(-1)};};
  window.__hallTraffic={state:failure?'failed':'done',failure,seconds:(performance.now()-start)/1000,minimum,turns,passed:[...passed],frameMs:stats(frames),planMs:stats(timings),note:'Synthetic paths, actual desktop hall Floor and PonyRig. No video or external requests.'};
})().catch(error=>{window.__hallTraffic={state:'failed',failure:error.stack};});
