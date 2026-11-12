// Run with node tests/test_pony_floor.cjs. No browser or model service required.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const context = vm.createContext({});
vm.runInContext(readFileSync('src/stock_predict_mailer/control/web/modules/pony-model.js', 'utf8'), context);
const {Floor, distance, radius, gate} = context.PonyFloor;
const floor = new Floor();
assert.equal(floor.actors.filter(a => a.present).length, 3);
for (const actor of floor.actors) floor.set(actor.id, 'running');
let samples = 0;
function advance(seconds) {
  for (let i = 0; i < seconds * 60; i++) {
    floor.tick(1 / 60);
    const visible = floor.actors.filter(a => a.present);
    for (let x = 0; x < visible.length; x++) for (let y = x + 1; y < visible.length; y++) assert.ok(distance(visible[x], visible[y]) >= radius * 2 + 3 - .01, 'actor collision');
    for (const actor of visible) if (actor.pose === 'walking') {
      const docking = ['dock', 'undock'].includes(floor.motion(actor.id)?.stage);
      assert.equal(floor.blocked(actor, actor, docking), false, `static collision: ${actor.id}`);
      samples++;
    }
  }
}
advance(100);
assert.ok(floor.actors.every(a => a.present && (!a.station || a.pose === 'seated')), 'every summoned role must arrive without deadlock');
floor.finish('completed'); advance(100);
assert.equal(floor.actors.filter(a => a.present).length, 3, 'only residents remain after departure');
assert.equal(floor.door, 0, 'door closed after final exit');
floor.reset(); floor.set('risk', 'running'); floor.set('risk', 'completed'); advance(3);
assert.equal(floor.actors.find(a => a.id === 'risk').present, false, 'fast completed task must not fake work');
floor.reset(); for (const a of floor.actors) floor.set(a.id, 'running');
for (let i = 0; i < 4000; i++) floor.tick(1 / 60, true);
assert.ok(floor.actors.every(a => !a.station || a.pose === 'seated'), 'reduced motion keeps correct arrival');
floor.reset(); let roamed = false;
for (let i = 0; i < 4000; i++) {
  floor.tick(1 / 60, false, true);
  if (floor.actors.some(a => a.resident && a.pose === 'walking')) roamed = true;
  const visible = floor.actors.filter(a => a.present);
  for (let a = 0; a < visible.length; a++) for (let b = a + 1; b < visible.length; b++) assert.ok(distance(visible[a], visible[b]) >= radius * 2 + 3 - .01, 'idle collision');
}
assert.ok(roamed, 'idle residents stroll');
floor.set('main', 'running');
for (let i = 0; i < 1500; i++) floor.tick(1 / 60, false, false);
assert.equal(floor.actors.find(a => a.id === 'main').pose, 'seated', 'running task recalls roaming resident');
floor.reset(); for (let i = 0; i < 3000; i++) floor.tick(1 / 60, true, true);
assert.equal(floor.transit, null, 'reduced motion suppresses idle stroll');

// Same-direction agents share one open interval; an opposite-direction visitor waits for it to close.
const shared = new Floor(), arrivals = ['prediction','risk','charts'];
for (const id of arrivals) shared.set(id,'running');
shared.actors.find(a=>a.id==='main').resident=false;
let previousOpen=false,openCycles=0,oppositeAdmitted=false;
for(let i=0;i<30000;i++){
  shared.tick(1/60,false,false);
  const open=shared.door===1;
  if(open&&!previousOpen)openCycles++;
  previousOpen=open;
  const mainMotion=shared.motion('main');
  if(mainMotion?.exit&&!oppositeAdmitted){oppositeAdmitted=true;assert.equal(shared.door,0,'opposite direction waits until the current door cycle closes');}
  const visible=shared.actors.filter(a=>a.present);
  for(let a=0;a<visible.length;a++)for(let b=a+1;b<visible.length;b++)assert.ok(distance(visible[a],visible[b])>=radius*2+3-.01,'no overlap during shared gate transit');
  for(const actor of visible)if(actor.x>-30&&actor.x<25&&Math.abs(actor.y-gate.y)<1)assert.equal(shared.door,1,'door stays open until the full body clears the threshold');
  if(arrivals.every(id=>{const a=shared.actors.find(actor=>actor.id===id);return a.present&&a.pose==='seated';})&&!shared.actors.find(a=>a.id==='main').present&&shared.jobs.size===0&&shared.queue.length===0&&shared.door===0)break;
}
assert.ok(oppositeAdmitted,'queued opposite direction eventually receives the doorway');
assert.equal(openCycles,2,'three arrivals share one opening and the opposite departure uses the next opening');
assert.ok(arrivals.every(id=>{const a=shared.actors.find(actor=>actor.id===id);return a.present&&a.pose==='seated';}),'batched arrivals all reach their stations');
assert.equal(shared.actors.find(a=>a.id==='main').present,false,'opposite departure completes after the arrival batch');

// Three departures queue in order and reuse one open doorway interval.
const leaving=new Floor(),departures=['prediction','risk','charts'];
for(const id of departures){const a=leaving.actors.find(actor=>actor.id===id);a.present=true;a.pose='idle';a.x=a.deskX;a.y=a.deskY+120;a.stayUntil=0;}
previousOpen=false;openCycles=0;
for(let i=0;i<30000;i++){
  leaving.tick(1/60,false,false);
  const open=leaving.door===1;
  if(open&&!previousOpen)openCycles++;
  previousOpen=open;
  const visible=leaving.actors.filter(a=>a.present);
  for(let a=0;a<visible.length;a++)for(let b=a+1;b<visible.length;b++)assert.ok(distance(visible[a],visible[b])>=radius*2+3-.01,'no overlap during grouped departures');
  for(const actor of visible)if(actor.x>-30&&actor.x<25&&Math.abs(actor.y-gate.y)<1)assert.equal(leaving.door,1,'departure threshold remains open');
  if(departures.every(id=>!leaving.actors.find(actor=>actor.id===id).present)&&leaving.jobs.size===0&&leaving.queue.length===0&&leaving.door===0)break;
}
assert.equal(openCycles,1,'three departures share one opening and one closing');
assert.ok(departures.every(id=>!leaving.actors.find(actor=>actor.id===id).present),'all batched departures clear the office');
console.log(`Pony navigation passed: ${samples} swept-motion samples; arrivals, exits, collisions, fast completion, reduced motion.`);
