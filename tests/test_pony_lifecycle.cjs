const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const context = vm.createContext({});
for (const name of ['pony-model','pony-screen']) vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),context);
const {Floor,distance,radius} = context.PonyFloor, screen = context.PonyScreen;
const floor = new Floor(), modes = new Set(), visitors = new Set();
const seconds=Number(process.env.PONY_SIM_SECONDS||600);
let crossings=0, concurrent=false;
for(let i=0;i<60*seconds;i++) {
  floor.tick(1/60,false,true);
  if(floor.actors.filter(a=>a.pose==='walking').length>1) concurrent=true;
  for(const job of floor.jobs.values()) assert.ok(job.elapsed<60,`no stranded ${job.id} in ${job.stage} at ${floor.time}: ${JSON.stringify(floor.actors.map(a=>[a.id,a.pose,a.x,a.y]))}`);
  for(const a of floor.actors) {
    if(a.present && !a.resident) visitors.add(a.id);
    if(a.present && a.pose==='seated') { a.idleClock=(a.idleClock||0)+1/60; a.activity=(a.seed+Math.floor(a.idleClock/32))%5; }
    modes.add(screen.state(a,floor.time));
    if(a.present) assert.notEqual(screen.state(a,floor.time),'off','inside monitor stays on');
    if(a.present && a.x>-30 && a.x<25) { assert.equal(floor.door,1,'full-body threshold passage needs open door'); crossings++; }
  }
  const visible=floor.actors.filter(a=>a.present);
  for(let x=0;x<visible.length;x++) for(let y=x+1;y<visible.length;y++) assert.ok(distance(visible[x],visible[y])>=radius*2+2.9,'no overlap during idle visits');
}
for(const game of screen.games) assert.ok(modes.has(game),`observable ${game}`);
assert.equal(visitors.size,4,'all idle subagent avatars may visit without execution');
assert.ok(crossings>0);
assert.ok(concurrent,'independent interior walking overlaps');
for(const terminal of ['completed','failed','canceled']) {
  const f=new Floor();
  f.set('risk','running');
  for(let i=0;i<500;i++) f.tick(1/60,false,true);
  f.set('risk',terminal,'真实事件反馈');
  const a=f.actors.find(a=>a.id==='risk');
  assert.equal(screen.state(a,f.time),'result');
  assert.ok(screen.render(a,f.time).markup.includes('真实事件反馈'));
  f.set('risk','running','调用工具');
  assert.equal(screen.state(a,f.time),'task','task preempts result');
  assert.equal(screen.state(a,f.time,false),'disconnected');
}
const malicious={...floor.actors[0],state:'running',last:'<script>alert(1)</script>'};
assert.ok(!screen.render(malicious,0).markup.includes('<script>'));
for(const stage of ['walk','cross','close']) {
  const f=new Floor(); f.set('risk','running');
  const a=f.actors.find(a=>a.id==='risk');
  for(let i=0;i<6000 && a.pose!=='seated';i++) f.tick(1/60);
  assert.equal(a.pose,'seated'); f.set('risk','completed');
  let reached=false;
  for(let i=0;i<6000;i++) { f.tick(1/60); if(f.transit?.exit && f.transit.stage===stage) {reached=true;break;} }
  assert.ok(reached,`exit reaches ${stage}`);
  f.set('risk','running','门口收到新任务');
  for(let i=0;i<6000;i++) f.tick(1/60);
  assert.ok(a.present && a.pose==='seated',`safe recall during ${stage}`);
}
console.log(`${seconds}s lifecycle passed: ${visitors.size} visitors, ${crossings} threshold frames, ${[...modes].join(', ')}; concurrent walking, no stalled jobs, terminal feedback and escaping.`);
