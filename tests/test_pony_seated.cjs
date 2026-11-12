const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({});
for(const name of ['pony-reference','pony-rig'])vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),context);
const {PonyReference:reference,PonyRig:rig}=context;
const bounds=points=>{
  const x=points.filter((_,i)=>i%2===0),y=points.filter((_,i)=>i%2);
  return {left:Math.min(...x),right:Math.max(...x),top:Math.min(...y),bottom:Math.max(...y)};
};
for(const pose of reference.seated.mail){
  assert.ok(bounds(pose.head).top>-125,`sleep f${pose.frame}: monitor must not enter head silhouette`);
}
for(const [id,frame]of [['prediction',54],['main',60],['risk',84],['advice',138],['charts',150]]){
  const box=bounds(reference.seated[id].find(pose=>pose.frame===frame).head);
  assert.ok(box.right-box.left>55,`${id} f${frame}: profile muzzle must survive source crop`);
}
assert.equal(reference.seatedFPS,30,'use the native head animation cadence');
for(const [id,frames]of Object.entries(reference.seated)){
  assert.equal(frames.length,168,`${id}: no six-frame gaps through a viewpoint change`);
  const actor={id},sleep=id==='mail'?1:0,period=2*(frames.length-1)/reference.seatedFPS;
  // At every quarter-frame, the whole head assembly must be one source pose.
  // Vertex interpolation between opposite profiles folds the horn and muzzle.
  for(let quarter=0;quarter<=4*(frames.length-1);quarter++){
    const at=quarter/4/reference.seatedFPS;
    const expected=frames[Math.round(quarter/4)];
    const actual=rig.seated(actor,at,sleep);
    for(const key of ['head','collar','lids'])assert.deepEqual(actual[key],expected[key],`${id}: ${key} source pose at ${at}`);
    const reverse=rig.seated(actor,period-at,sleep);
    for(const key of ['head','collar','lids'])assert.deepEqual(reverse[key],expected[key],`${id}: ${key} return pose at ${at}`);
  }
  assert.deepEqual(rig.seated(actor,period,sleep),rig.seated(actor,0,sleep),`${id}: loop joins at the same source pose`);
  assert.deepEqual(rig.seated(actor,10,sleep,true),rig.seated(actor,0,sleep,true),'reduced motion remains still');
}
console.log('Seated heads passed: clean monitor separation, complete muzzles, native poses and a matching return loop for all six roles.');
