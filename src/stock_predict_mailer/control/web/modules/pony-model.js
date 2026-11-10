/* Deterministic floor navigation; independent of DOM and backend timing. */
globalThis.PonyFloor = (() => {
  const roles = [
    ['main', '主 Agent', '#df5353', 230, 160, true],
    ['prediction', '预测分析', '#4eac70', 515, 160, false],
    ['risk', '风险分析', '#9570d6', 800, 160, false],
    ['mail', '邮件投递', '#4098df', 230, 390, true],
    ['charts', '图表生成', '#23afb0', 515, 390, false],
    ['advice', '建议生成', '#dab32b', 800, 390, false]
  ].map(([id, name, color, x, y, resident]) => ({id, name, color, x, y, resident}));
  const gate = {x: 35, y: 550}, radius = 30;
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  class Floor {
    constructor() { this.reset(); }
    reset() {
      this.time = 0; this.door = 0; this.transit = null; this.queue = []; this.serial = 0;
      this.actors = roles.map(role => ({...role, x: role.x, y: role.y + 70, deskX: role.x, deskY: role.y,
        present: role.resident, pose: role.resident ? 'seated' : 'absent', state: 'idle', phase: 0, speed: 0, heading: 1, last: '', summoned: false}));
    }
    blocked(point, actor, dock = false) {
      if (point.x < 25 || point.x > 935 || point.y < 30 || point.y > 590) return true;
      for (const role of roles) {
        if (point.x > role.x - 100 - radius && point.x < role.x + 100 + radius && point.y > role.y - 65 - radius && point.y < role.y + 25 + radius) return true;
        if (!(dock && role.id === actor.id) && point.x > role.x - 32 - radius && point.x < role.x + 32 + radius && point.y > role.y + 35 - radius && point.y < role.y + 88 + radius) return true;
      }
      return this.actors.some(other => other !== actor && other.present && distance(point, other) < radius * 2 + 3);
    }
    path(start, end, actor) {
      // Four-neighbour A*: swept edges are sampled too, so no corner cutting.
      const key = p => `${p.x},${p.y}`, snap = p => ({x: Math.round(p.x / 10) * 10, y: Math.round(p.y / 10) * 10});
      const first = snap(start), last = snap(end), open = [first], costs = new Map([[key(first), 0]]), prev = new Map();
      let found = null;
      while (open.length) {
        open.sort((a, b) => costs.get(key(a)) + distance(a, last) - costs.get(key(b)) - distance(b, last));
        const p = open.shift(); if (key(p) === key(last)) { found = p; break; }
        for (const [dx, dy] of [[10, 0], [-10, 0], [0, 10], [0, -10]]) {
          const next = {x: p.x + dx, y: p.y + dy}, k = key(next), cost = costs.get(key(p)) + 10;
          if (this.blocked(next, actor) || this.blocked({x: p.x + dx / 2, y: p.y + dy / 2}, actor) || cost >= (costs.get(k) ?? Infinity)) continue;
          costs.set(k, cost); prev.set(k, p); open.push(next);
        }
      }
      if (!found) return null;
      const route = [end]; let p = found;
      while (prev.has(key(p))) { route.unshift(p); p = prev.get(key(p)); }
      return route;
    }
    set(id, state, label = '') {
      const actor = this.actors.find(a => a.id === id); if (!actor) return;
      actor.state = state; if (label) actor.last = label;
      if (state === 'running') {
        actor.summoned = true;
        this.queue = this.queue.filter(job => !(job.id === id && job.exit));
        if (!actor.present && !this.queue.some(job => job.id === id) && this.transit?.id !== id) this.queue.push({id, exit: false});
      }
    }
    finish(state) {
      for (const actor of this.actors) if (actor.state === 'running') actor.state = state === 'completed' ? 'completed' : state;
    }
    tick(dt, reduced = false) {
      dt = Math.max(0, Math.min(dt, .05)); this.time += dt;
      for (const actor of this.actors) {
        actor.phase += dt * (actor.pose === 'walking' ? 9 : 1.5);
        if (actor.present && !actor.resident && actor.state !== 'running' && !this.queue.some(job => job.id === actor.id) && this.transit?.id !== actor.id) this.queue.push({id: actor.id, exit: true});
      }
      if (!this.transit && this.queue.length) {
        const job = this.queue.shift(), actor = this.actors.find(a => a.id === job.id);
        // Completed-before-entry jobs are coalesced; never invent work for fast tasks.
        if (!job.exit && actor.state !== 'running') return;
        this.transit = {...job, stage: job.exit ? 'rise' : 'open', elapsed: 0, path: null, index: 0};
        if (job.exit) actor.pose = 'rising';
      }
      if (!this.transit) { this.door = Math.max(0, this.door - dt * 4); return; }
      const job = this.transit, actor = this.actors.find(a => a.id === job.id);
      job.elapsed += dt;
      const transition = stage => { job.stage = stage; job.elapsed = 0; };
      if (job.stage === 'open') {
        this.door = Math.min(1, this.door + dt * 4);
        if (this.door === 1) {
          actor.present = true; actor.x = gate.x; actor.y = gate.y; actor.pose = 'walking';
          job.path = this.path(gate, {x: actor.deskX, y: actor.deskY + 120}, actor);
          transition('walk');
        }
      } else if (job.stage === 'rise') {
        if (job.elapsed > (reduced ? 0 : .35)) {
          actor.pose = 'walking';
          job.path = [{x: actor.deskX, y: actor.deskY + 120}]; transition('undock');
        }
      } else if (job.stage === 'sit') {
        actor.pose = 'sitting';
        if (job.elapsed > (reduced ? 0 : .45)) { actor.pose = 'seated'; this.transit = null; }
      } else if (job.stage === 'turn') {
        actor.pose = 'turning';
        if (job.elapsed > (reduced ? 0 : .25)) { job.path = [{x: actor.deskX, y: actor.deskY + 70}]; transition('dock'); }
      } else if (job.stage === 'close') {
        this.door = Math.max(0, this.door - dt * 4);
        if (!this.door) this.transit = null;
      } else {
        if (!job.path) {
          job.path = this.path(actor, job.exit ? gate : {x: actor.deskX, y: actor.deskY + 120}, actor);
          actor.pose = 'waiting'; return;
        }
        const target = job.path[0];
        if (!target) {
          actor.speed = 0;
          if (job.stage === 'undock') { job.path = this.path(actor, gate, actor); transition('walk'); }
          else if (job.exit) {
            this.door = Math.min(1, this.door + dt * 4);
            actor.pose = 'waiting';
            if (this.door === 1) { actor.present = false; actor.pose = 'absent'; transition('close'); }
          } else if (job.stage === 'dock') { actor.pose = 'sitting'; transition('sit'); }
          else { actor.pose = 'turning'; transition('turn'); }
          return;
        }
        const d = distance(actor, target);
        const speed = reduced ? 420 : Math.min(160, actor.speed + dt * 400);
        const travel = Math.min(d, speed * dt), next = {x: actor.x + (target.x - actor.x) / (d || 1) * travel, y: actor.y + (target.y - actor.y) / (d || 1) * travel};
        if (job.exit && next.x < 85 && next.y > 515 && this.door < 1) { this.door = Math.min(1, this.door + dt * 4); actor.pose = 'waiting'; return; }
        if (this.blocked(next, actor, ['dock', 'undock'].includes(job.stage))) { actor.pose = 'waiting'; actor.speed = 0; return; }
        actor.heading = target.x < actor.x ? -1 : target.x > actor.x ? 1 : actor.heading;
        actor.x = next.x; actor.y = next.y; actor.speed = speed; actor.pose = 'walking';
        if (d <= travel + .01) job.path.shift();
        if (distance(actor, gate) > 70 && !job.exit) this.door = Math.max(0, this.door - dt * 4);
      }
    }
  }
  return {Floor, roles, gate, radius, distance};
})();
