const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c=vm.createContext({});
for(const name of ['pony-door','pony-model','pony-screen'])vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),c);
const {Floor,roles,furniture:g,radius,distance}=c.PonyFloor;
const stations=roles.filter(r=>r.station);
assert.equal(stations.length,6);
for(const members of [stations.slice(0,3),stations.slice(3)]){
  const row=members.slice().sort((a,b)=>a.x-b.x);
  assert.ok(row.every(r=>r.y===row[0].y),'row alignment');
  for(let i=1;i<3;i++)assert.ok(row[i].x-row[i-1].x-g.halfWidth*2>125,'wide furniture gaps');
}
assert.ok(stations[3].y-143-(stations[0].y+g.chairBottom)>18,'next-row label clears front chair');
const geometry=new Floor(),main=geometry.actors[0];
assert.equal(geometry.blocked({x:372.5,y:100},main),true,'upper route keeps the character head inside the canvas');
assert.equal(geometry.blocked({x:main.deskX+g.halfWidth+radius-1,y:main.deskY},main),true,'visible desktop footprint blocks navigation');
assert.equal(geometry.blocked({x:main.deskX,y:main.deskY+g.approach},main),false,'approach is beyond actual chair footprint');
let minimum=Infinity,totalYields=0;
for(const y of [325,620]){
  const f=new Floor();f.nextRoam=Infinity;
  f.actors.forEach(a=>{a.present=false;});
  const a=f.actors[0],b=f.actors[1];
  for(const [actor,x,end]of [[a,300,700],[b,700,300]]){
    Object.assign(actor,{x,y,present:true,state:'running',pose:'walking',speed:0});
    f.jobs.set(actor.id,{id:actor.id,stage:'stroll',elapsed:0,path:[{x:end,y}],entry:false,exit:false});
  }
  let firstPassed=false,secondPassed=false;
  for(let i=0;i<3600;i++){
    f.tick(1/60,false,false);
    const d=distance(a,b);minimum=Math.min(minimum,d);assert.ok(d>=radius*2+3-1e-5,'opposing actors never overlap');
    for(const actor of [a,b])if(actor.pose==='walking')assert.equal(f.blocked(actor,actor,['dock','undock'].includes(f.motion(actor.id)?.stage)),false,'whole movement stays outside furniture');
    if(a.x>690)firstPassed=true;if(b.x<310)secondPassed=true;
    if(firstPassed&&secondPassed)break;
  }
  assert.ok(firstPassed&&secondPassed,`head-on pair passes in aisle y=${y}`);totalYields+=f.metrics.yields;
}
assert.ok(totalYields>0,'traffic exercises deterministic pull-out yielding');
// A route may leave a touching safety boundary, but may never cut into it.
const touching=new Floor();touching.actors.forEach(a=>{a.present=false;});
const a=touching.actors[0],b=touching.actors[1];Object.assign(a,{x:400,y:620,present:true});Object.assign(b,{x:400+radius*2+3,y:620,present:true});
assert.ok(touching.clear(a,{x:400,y:660},a,false,true,1),'touching actor can retreat');
assert.equal(touching.clear(a,{x:420,y:620},a),false,'touching actor cannot move into its neighbor');
const door=new Floor();door.actors.forEach(a=>{a.present=false;});
const exiting=door.actors[1],occupant=door.actors[5];
Object.assign(exiting,{x:40,y:500,present:true,state:'running',pose:'walking'});
Object.assign(occupant,{x:115,y:550,present:true,state:'running',pose:'waiting'});
door.jobs.set(exiting.id,{id:exiting.id,exit:true,stage:'walk',elapsed:0,path:[{x:35,y:550}]});
for(let i=0;i<90;i++){
  door.tick(1/60);assert.ok(distance(exiting,occupant)>=radius*2+3-1e-5,'occupied door handle cannot be approached through another actor');
  assert.notEqual(door.motion(exiting.id)?.stage,'exit-open','door approach waits for its destination to clear');
}
const screen=c.PonyScreen,now=new Date(2026,10,13,9,7,5),actor={present:true,pose:'walking',state:'idle',seed:0};
assert.equal(screen.clock(now).time,'09:07:05');assert.equal(screen.clock(now).date,'2026-11-13');
for(const animationTime of [0,50,3600,999999])assert.ok(screen.render(actor,animationTime,true,now).markup.includes('data-clock="09:07:05"'),'wall clock ignores animation elapsed time');
const later=new Date(now.getTime()+86403000);
assert.ok(screen.render(actor,0,true,later).markup.includes('data-clock="09:07:08"'),'restored screen reads the supplied current date immediately');
assert.equal(screen.render({...actor,state:'running'},0,true,now).mode,'task','task progress overrides clock');
console.log(`Office refinement passed: six shared footprints, two head-on corridors, ${totalYields} pull-outs, minimum separation ${minimum.toFixed(3)}, wall date/time and task priority.`);
