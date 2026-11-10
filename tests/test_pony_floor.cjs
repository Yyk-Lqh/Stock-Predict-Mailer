// Run with node tests/test_pony_floor.cjs. No browser or model service required.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const context = vm.createContext({});
vm.runInContext(readFileSync('src/stock_predict_mailer/control/web/modules/pony-model.js', 'utf8'), context);
const {Floor, distance, radius} = context.PonyFloor;
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
      const docking = ['dock', 'undock'].includes(floor.transit?.stage);
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
console.log(`Pony navigation passed: ${samples} swept-motion samples; arrivals, exits, collisions, fast completion, reduced motion.`);
