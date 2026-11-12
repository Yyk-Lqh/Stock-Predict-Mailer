const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c=vm.createContext({});
for(const name of ['pony-reference','pony-rig'])vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),c);
const {PonyRig:rig,PonyReference:reference}=c;
assert.equal(reference.walk.length,18);
assert.equal(reference.walk[0].frame,12);assert.equal(reference.walk.at(-1).frame,29);
assert.ok(reference.still.fringe.length>0&&reference.walk.some(pose=>pose.fringe.length>5),'source-derived fringe gaps survive tracing');
for(let i=0;i<18;i++)assert.equal(rig.sampleWalk(i/18*Math.PI*2).frame,12+i,'exact source phase retains its frame number');
let previous,maxDelta=0,minSpan=Infinity,maxSpan=0;
for(let sample=0;sample<=720;sample++){
  const pose=rig.sampleWalk(sample/720*Math.PI*2);
  for(const key of ['head','body','scarf']){
    assert.ok(pose[key].every(Number.isFinite));assert.equal(pose[key].length,reference.walk[0][key].length);
    if(previous)for(let i=0;i<pose[key].length;i++)maxDelta=Math.max(maxDelta,Math.abs(pose[key][i]-previous[key][i]));
  }
  const xs=pose.body.filter((_,i)=>i%2===0),span=Math.max(...xs)-Math.min(...xs);
  minSpan=Math.min(minSpan,span);maxSpan=Math.max(maxSpan,span);
  assert.equal(pose.eyes.length,2,'two open white eyes throughout reference walk');
  assert.equal(pose.pupils.length,2,'two contained pupils throughout reference walk');
  previous=pose;
}
assert.ok(maxDelta<4,`interpolated loop including seam stays continuous: ${maxDelta}`);
assert.ok(maxSpan-minSpan>18,'full silhouette visibly opens and contracts through a stride');
const start=rig.sampleWalk(0),end=rig.sampleWalk(Math.PI*2);
assert.deepEqual(start.body,end.body,'gait closes exactly at its loop boundary');
for(const key of Object.keys(reference.seated)){
  for(const sample of reference.seated[key])assert.ok(sample.head.every(Number.isFinite));
  if(key!=='mail')assert.ok(reference.seated[key].every(pose=>pose.lids.length===0),'rear head has no white eye holes');
}
const sleepActor={id:'mail',seed:3,state:'idle',pose:'seated',phase:0};
assert.equal(rig.expression(sleepActor,0,'idle').sleep,1);
assert.equal(rig.operation(sleepActor,0,'idle').input,false);
assert.equal(rig.expression({...sleepActor,state:'running'},0,'task').sleep,0,'a real task takes priority over sleep');
assert.equal(rig.expression(sleepActor,0,'idle',true).sleep,0,'reduced motion remains static');
assert.ok(reference.seated.mail.every(pose=>pose.lids.length===2),'source sleep is two separate white eyelids');
const markup=rig.markup({id:'main',name:'main',color:'#ed2f31'});
assert.ok(!/pony-(ear|tail|muzzle|expression)["\s]/.test(markup),'unobserved decorative anatomy removed');
assert.ok(!/stroke-linecap="round"/.test(markup),'visible limbs are closed fills');
assert.ok(rig.solidArm(rig.solve({x:0,y:0},{x:20,y:-30})).endsWith('Z'));
console.log(`Reference reconstruction passed: 721 phases, ${maxDelta.toFixed(3)} maximum coordinate delta, ${minSpan.toFixed(1)}–${maxSpan.toFixed(1)} stride width.`);
