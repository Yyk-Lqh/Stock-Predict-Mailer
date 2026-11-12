const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c=vm.createContext({});
for(const name of ['pony-reference','pony-rig'])vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),c);
const rig=c.PonyRig,dist=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
let contacts=0;
for(let seed=0;seed<7;seed++) for(const mode of ['task','贪吃蛇','扫雷','俄罗斯方块','打砖块','绘图']) {
  let previous;
  for(let i=0;i<1320;i++) {
    const a={seed,state:mode==='task'?'running':'idle',pose:'seated',phase:i*.025,idleClock:i/60,deskX:230,deskY:160};
    const arms=rig.arms(a,{x:230,y:230},1,i/60,mode);
    for(const side of ['left','right']) {
      const arm=arms[side];
      assert.ok(arm.reachable,`${mode} ${side} stays within reach`);
      assert.ok(Math.abs(dist(arm.shoulder,arm.elbow)-24)<1e-8,'fixed upper arm');
      assert.ok(Math.abs(dist(arm.elbow,arm.hoof)-25)<1e-8,'fixed forearm');
      if(previous) assert.ok(dist(arm.hoof,previous[side].hoof)<1.4,'no hoof teleport between devices');
    }
    const leftWorld={x:230+arms.left.hoof.x*rig.scale,y:230+arms.left.hoof.y*rig.scale};
    assert.ok(Math.abs(leftWorld.x-(230+rig.desk.keyboard.left.x))<.001);
    assert.ok(leftWorld.y>=160+rig.desk.keyboard.left.y-1 && leftWorld.y<=160+rig.desk.keyboard.left.y+.01,'typing contact height');
    if(arms.operation.mouse>.999) {
      const w={x:230+arms.right.hoof.x*rig.scale,y:230+arms.right.hoof.y*rig.scale};
      assert.ok(dist(w,{x:230+rig.desk.mouse.x,y:160+rig.desk.mouse.y})<2,'mouse hoof stays on mouse'); contacts++;
    }
    previous=arms;
  }
}
const unreachable=rig.solve({x:0,y:0},{x:1000,y:0});
assert.equal(unreachable.reachable,false); assert.ok(dist(unreachable.shoulder,unreachable.hoof)<49,'unreachable targets never stretch limb');
let slept=false,paused=false;
for(let i=0;i<47*60;i++) {
  const actor={seed:0,state:'idle',pose:'seated',phase:i/30,idleClock:i/60};
  const face=rig.expression(actor,i/60,'贪吃蛇');
  if(face.sleep>.9) { slept=true;assert.ok(face.blink<.11,'drowsy pony closes its eyes'); }
  if(face.sleep>.1) {paused=true;assert.equal(rig.operation(actor,i/60,'贪吃蛇').input,false,'resting pony pauses typing');}
  assert.equal(rig.expression({...actor,state:'running'},i/60,'task').sleep,0,'task wakes resting pony immediately');
  const legs=rig.legs({...actor,pose:'walking'},0);
  for(const side of ['left','right']) {
    const leg=legs[side];
    assert.equal(leg.elbow,undefined,'leg has a single continuous shape without a knee');
    assert.ok(Math.abs(dist(leg.hip,leg.hoof)-34)<1e-8,'whole leg keeps its length while swinging');
    assert.ok(leg.hoof.y<=.001,'walking hoof never goes beneath the floor');
    assert.ok(Math.abs(leg.hoof.x)<34,'reference stride has a wide, bounded foot envelope');
  }
  for(const pose of ['idle','walking']) {
    const arms=rig.arms({...actor,pose,deskX:230,deskY:160},{x:230,y:280},0,i/60,'screensaver');
    for(const arm of [arms.left,arms.right]) {
      assert.ok(Math.abs(arm.hoof.x)+6.2<25,'standing and walking hooves stay close to the torso');
      assert.ok(Math.abs(arm.elbow.x)<18,'relaxed elbows tuck behind the body');
    }
  }
}
assert.ok(slept&&paused,'idle lifecycle includes observable sleep and input pause');
assert.equal(rig.expression({seed:0,pose:'seated',state:'idle'},40,'贪吃蛇',true).nod,0,'reduced motion suppresses nodding');
console.log(`Foreleg geometry passed: 55,440 samples; ${contacts} mouse contacts, fixed lengths, alternating typing and continuous device transitions.`);
