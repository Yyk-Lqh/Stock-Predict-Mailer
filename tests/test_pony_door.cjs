const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({});
for(const name of ['pony-door','pony-model','pony-rig']) vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),context);
const {PonyDoor:door,PonyRig:rig}=context;
const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
let contacts=0;
for(const side of ['outside','inside'])for(const closing of [false,true]) {
  const heading=side==='outside'?1:-1;
  let visualHeading=closing?-heading:heading,previous;
  const phases=new Set();
  for(let frame=0;frame<220;frame++) {
    const t=frame/60,action={...door.sample(t,closing),side,closing};
    phases.add(action.phase);
    const actor={seed:0,phase:t,state:'idle',pose:closing?'door-close':'door-handle',heading,deskX:230,deskY:160,doorAction:action};
    visualHeading+=(heading-visualHeading)*.14;
    const scaleX=Math.sign(visualHeading||1)*(.78+.22*Math.abs(visualHeading));
    const origin={x:(side==='outside'?-30:door.frame.insideX)+heading*action.lean,y:550};
    const base=rig.arms(actor,origin,0,t,'screensaver').right;
    const arm=rig.doorArm(actor,origin,scaleX,base,action.open);
    assert.ok(Math.abs(distance(arm.shoulder,arm.elbow)-24)<1e-8,'upper arm never stretches');
    assert.ok(Math.abs(distance(arm.elbow,arm.hoof)-25)<1e-8,'forearm never stretches');
    const elbowAngle=Math.acos((24*24+25*25-distance(arm.shoulder,arm.hoof)**2)/(2*24*25))*180/Math.PI;
    assert.ok(elbowAngle>=35-1e-5&&elbowAngle<=165+1e-5,'elbow stays within its safe range');
    const hoof={x:origin.x+arm.hoof.x*rig.scale*scaleX,y:origin.y+arm.hoof.y*rig.scale};
    if(action.contact===1&&side==='inside') {
      assert.ok(arm.reachable,`${side} ${closing?'close':'open'} handle is reachable at ${t}`);
      assert.ok(distance(hoof,door.geometry(action.open).handle(side))<1e-5,'grip tracks the actual moving handle');contacts++;
    }
    if(side==='inside'&&previous&&t>.35) assert.ok(distance(hoof,previous)<1.8,`${side} ${closing?'close':'open'} ${action.phase} has no hoof jump at ${t}: ${distance(hoof,previous)}`);
    previous=hoof;
    if(action.phase==='align'||action.phase==='reach'||action.phase==='grip') assert.equal(action.open,closing?1:0,'door waits for the hand to grip');
    if(action.done) { assert.equal(action.contact,0);assert.equal(action.open,closing?0:1); }
  }
  for(const phase of ['align','reach','grip','swing','release','settle'])assert.ok(phases.has(phase));
}
console.log(`Door contact passed: ${contacts} visible interior grip samples; elbow limits, fixed lengths and continuous release.`);
const floor=new context.PonyFloor.Floor();floor.set('prediction','running');
const cycles=new Set();let finished=false;
for(let i=0;i<6000;i++) {
  floor.tick(1/60);
  const actor=floor.actors.find(a=>a.id==='prediction'),action=actor.doorAction;
  if(actor.pose==='seated'&&!finished){finished=true;floor.finish('completed');}
  if(action&&['grip','swing'].includes(action.phase)) {
    assert.equal(actor.y,550,'floor navigation aligns the pony vertically before gripping');
    const origin={x:actor.x+actor.heading*action.lean,y:actor.y};
    const base=rig.arms(actor,origin,0,floor.time,'screensaver').right;
    const arm=rig.doorArm(actor,origin,actor.heading,base,floor.door);
    const view=door.portal(actor,floor.motion(actor.id),floor.door);
    if(action.side==='inside')assert.ok(arm.reachable,'visible interior action keeps the handle within reach');
    else assert.equal(view.visible,false,'exterior operator remains hidden behind the doorway');
    cycles.add(`${action.side}-${action.closing?'close':'open'}`);
  }
  if(finished&&!actor.present&&!floor.motion(actor.id))break;
}
assert.equal(cycles.size,4,'actual floor flow covers opening and closing from both sides');
for(const stage of ['open','close']) {
  const actor={present:true,x:-30,y:550};
  assert.equal(door.portal(actor,{stage,entry:stage==='open',exit:stage==='close'},1).visible,false,'outside body and shadow are hidden');
}
for(const stage of ['enter','cross'])for(let x=-30;x<=door.frame.insideX;x+=1){
  const actor={present:true,x,y:550},view=door.portal(actor,{stage},1);
  assert.equal(view.clipped,true,'the whole threshold transit uses the aperture mask');
  if(x+39*.88<=door.frame.left)assert.equal(view.visible,false,'nothing appears to the left of the aperture');
  assert.equal(door.portal(actor,{stage},0).visible,false,'closed door never reveals a crossing pony');
}
