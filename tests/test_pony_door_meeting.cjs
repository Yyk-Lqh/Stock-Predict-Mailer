const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c=vm.createContext({});for(const name of ['pony-door','pony-model'])vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),c);
let cases=0;
for(const [x,y]of [[-535,1172],[-1000,1600]])for(const incomingId of ['prediction','risk','charts','advice'])for(const outgoingId of ['prediction','risk','charts','advice']){
 if(incomingId===outgoingId)continue;
 c.PonyDoor.position(x,y);const f=new c.PonyFloor.Floor(),gate=c.PonyFloor.gate,inside=c.PonyDoor.frame.insideX;
 f.actors.forEach(a=>a.present=false);
 const incoming=f.actors.find(a=>a.id===incomingId),outgoing=f.actors.find(a=>a.id===outgoingId);
 Object.assign(incoming,{present:true,x:gate.x,y:gate.y,state:'running',pose:'walking'});
 Object.assign(outgoing,{present:true,x:gate.x+84,y:gate.y,state:'idle',pose:'walking'});
 f.jobs.set(incoming.id,{id:incoming.id,entry:true,stage:'enter',elapsed:0,path:[{x:inside,y:gate.y}]});
 f.jobs.set(outgoing.id,{id:outgoing.id,exit:true,stage:'walk',elapsed:0,path:[{x:gate.x,y:gate.y}]});
 f.gateOwner=incoming.id;f.doorDirection='enter';f.door=1;
 for(let i=0;i<120*60;i++){
  f.tick(1/60);
  if(incoming.present&&outgoing.present)assert.ok(c.PonyFloor.distance(incoming,outgoing)>=83-1e-6,'door yield never overlaps bodies');
  if(incoming.pose==='seated'&&!outgoing.present&&!f.jobs.size)break;
 }
 assert.equal(incoming.pose,'seated',`${incomingId} enters despite approaching ${outgoingId}`);
 assert.equal(outgoing.present,false,`${outgoingId} yields then exits`);
 assert.equal(f.jobs.size,0,'both routes finish');assert.equal(f.gateOwner,null,'door reservation released');cases++;
}
c.PonyDoor.position(0,430);
console.log(`Door meetings passed: ${cases} opposing pairs, both seed priorities, full arrival/exit and collision clearance.`);
