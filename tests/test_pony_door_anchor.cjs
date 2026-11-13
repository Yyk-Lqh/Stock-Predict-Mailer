const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c=vm.createContext({});for(const name of ['pony-door','pony-model'])vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),c);
const {Floor,distance,radius}=c.PonyFloor,door=c.PonyDoor;
for(const [x,y]of [[-220,800],[-130,760],[-65,1000],[-60,950],[160,850],[-535,1172],[-1000,1600]]){
  door.position(x,y);const floor=new Floor();
  for(const a of floor.actors)floor.set(a.id,'running');
  const advance=seconds=>{for(let i=0;i<seconds*60;i++){
    floor.tick(1/60);const visible=floor.actors.filter(a=>a.present);
    for(let a=0;a<visible.length;a++)for(let b=a+1;b<visible.length;b++)assert.ok(distance(visible[a],visible[b])>=radius*2+3-.01,'no overlap at relocated entrance');
  }};
  advance(150);assert.ok(floor.actors.every(a=>!a.station||a.pose==='seated'),`all stations arrive through door at ${x},${y}`);
  floor.finish('completed');advance(150);assert.equal(floor.actors.filter(a=>a.present).length,3,'visitors leave through relocated door');assert.equal(floor.door,0);
}
door.position(-130,760);const moving=new Floor();moving.set('risk','running');
for(let i=0;i<1000&&!moving.actors.find(a=>a.id==='risk').doorAction;i++)moving.tick(1/60);
const actor=moving.actors.find(a=>a.id==='risk'),before={x:actor.x,y:actor.y},handle=door.geometry(moving.door).handle('outside');
moving.relocateDoor(-100,800);
assert.ok(Math.abs(actor.x-before.x-30)<1e-8&&Math.abs(actor.y-before.y-40)<1e-8,'in-flight operator follows resized entrance');
const after=door.geometry(moving.door).handle('outside');assert.ok(Math.abs(after.x-handle.x-30)<1e-8&&Math.abs(after.y-handle.y-40)<1e-8,'handle shares the same coordinate offset');
for(let i=0;i<9000;i++)moving.tick(1/60);
assert.equal(actor.pose,'seated','resizing during a door action does not strand the arrival');
door.position(0,430);
console.log('Viewport door anchor passed: seven translated entrances, all arrivals/exits, collision clearance and resize during a handle action.');
