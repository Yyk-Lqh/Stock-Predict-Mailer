/* Shared projected door geometry and contact timing, independent of the DOM. */
globalThis.PonyDoor = (() => {
  const clamp = x => Math.max(0,Math.min(1,x));
  const ease = x => { x=clamp(x); return x*x*x*(x*(x*6-15)+10); };
  const frame=Object.freeze({y:430,width:80,height:128,left:8,right:74,top:436,bottom:552,insideX:115});
  function geometry(open) {
    const angle=clamp(open)*1.23;
    const width=Math.cos(angle), depth=Math.sin(angle)*10;
    const project=(x,y)=>({x:frame.right-(frame.right-x)*width,y:y-depth*(frame.right-x)/(frame.right-frame.left)});
    const handle=side=>{
      const p=project(side==='outside'?18:65,80);
      return {x:p.x,y:p.y+frame.y};
    };
    return {project,handle,angle};
  }
  function sample(elapsed,closing=false,from=closing?1:0) {
    const orient=closing?.45:.35, reach=.75, grip=.18, swing=closing?1.2:1.1, release=.8, settle=.2;
    const touchAt=orient+reach, swingAt=touchAt+grip, releaseAt=swingAt+swing, finishAt=releaseAt+release+settle;
    const contact=elapsed<touchAt?ease((elapsed-orient)/reach):elapsed<releaseAt?1:1-ease((elapsed-releaseAt)/release);
    const phase=elapsed<orient?'align':elapsed<touchAt?'reach':elapsed<swingAt?'grip':elapsed<releaseAt?'swing':elapsed<releaseAt+release?'release':'settle';
    const target=closing?0:1, open=from+(target-from)*ease((elapsed-swingAt)/swing);
    return {phase,contact,open,pressed:elapsed>=touchAt&&elapsed<releaseAt,
      look:ease(elapsed/.25)*(1-ease((elapsed-releaseAt)/release)),
      lean:2.5*contact,done:elapsed>=finishAt};
  }
  function portal(actor,motion,open) {
    if(!actor.present || (motion?.entry&&motion.stage==='open') || (motion?.exit&&motion.stage==='close')) {
      return {visible:false,clipped:false,state:'outside'};
    }
    const crossing=['enter','cross'].includes(motion?.stage) ||
      (motion?.exit&&motion.stage==='walk'&&actor.x<=frame.insideX&&actor.y>=549.99&&open===1);
    if(crossing) return {visible:open===1&&actor.x+39*.88>frame.left,clipped:true,state:'threshold'};
    return {visible:true,clipped:false,state:'room'};
  }
  return {ease,geometry,sample,portal,frame};
})();
