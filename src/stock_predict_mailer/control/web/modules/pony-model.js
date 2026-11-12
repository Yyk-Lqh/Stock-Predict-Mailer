/* Deterministic floor navigation; independent of DOM and backend timing. */
globalThis.PonyFloor = (() => {
  const roles = [
    ['main', '主 Agent', '#df5353', 230, 160, true],
    ['prediction', '预测分析', '#4eac70', 515, 160, false],
    ['risk', '风险分析', '#9570d6', 800, 160, false],
    ['mail', '邮件投递', '#4098df', 230, 390, true],
    ['charts', '图表生成', '#23afb0', 515, 390, false],
    ['advice', '建议生成', '#dab32b', 800, 390, false],
    ['assistant', '分析助理', '#e58b36', 900, 500, true]
  ].map(([id, name, color, x, y, resident]) => ({id, name, color, x, y, resident, station: id !== 'assistant'}));
  const gate = {x: 35, y: 550}, radius = 30;
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  class Floor {
    constructor() { this.reset(); }
    reset() {
      this.jobs = new Map(); this.gateOwner = null; this.time = 0; this.door = 0; this.doorDirection = null; this.doorHoldUntil = 0; this.transit = null; this.queue = []; this.serial = 0; this.nextRoam = 5;
      this.actors = roles.map((role, index) => ({...role, x: role.x, y: role.y + 70, deskX: role.x, deskY: role.y,
        present: role.resident, pose: role.id === 'assistant' ? 'idle' : role.resident ? 'seated' : 'absent', state: 'idle', phase: index * 2.37, seed: index, nextVisit: 8 + index * 11, feedbackUntil: 0, activity: index % 5, elapsed: 0, completedSteps: 0, speed: 0, heading: 1, last: '', summoned: false}));
    }
    motion(id) { return this.jobs.get(id) || null; }
    // One direction owns the full door cycle; gateOwner still admits only one body at a time.
    doorDirectionFor(job) {
      if (job.exit) return 'exit';
      if (job.entry && ['open','enter'].includes(job.stage)) return 'enter';
      if (!('stage' in job) && !job.roam) return 'enter';
      return null;
    }
    hasDoorWork(direction, exceptId = null) {
      return this.queue.some(job => this.doorDirectionFor(job) === direction) ||
        [...this.jobs.values()].some(job => job.id !== exceptId && this.doorDirectionFor(job) === direction);
    }
    random(actor) {
      actor.randomState=(Math.imul(actor.randomState ?? actor.seed+1,1664525)+1013904223)>>>0;
      return actor.randomState/4294967296;
    }
    blocked(point, actor, dock = false) {
      const portal = (this.motion(actor.id)?.stage === 'open' && point.x >= -65 && point.x <= 0) || (this.door === 1 && ['enter', 'cross'].includes(this.motion(actor.id)?.stage) && point.x >= -30 && point.x <= 95);
      if (portal && Math.abs(point.y-gate.y)<1) return this.actors.some(other=>other!==actor && other.present && distance(point,other)<radius*2+3);
      if (point.x < 25 || point.x > 935 || point.y < 30 || point.y > 590) return true;
      for (const role of roles) {
        if (!role.station) continue;
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
      const closed = new Set();
      while (open.length && closed.size < 6000) {
        open.sort((a, b) => costs.get(key(a)) + distance(a, last) - costs.get(key(b)) - distance(b, last));
        const p = open.shift(); if (closed.has(key(p))) continue;
        closed.add(key(p));
        if (key(p) === key(last)) { found = p; break; }
        for (const [dx, dy] of [[10, 0], [-10, 0], [0, 10], [0, -10]]) {
          const next = {x: p.x + dx, y: p.y + dy}, k = key(next), cost = costs.get(key(p)) + 10;
          if (closed.has(k) || this.blocked(next, actor) || this.blocked({x: p.x + dx / 2, y: p.y + dy / 2}, actor) || cost >= (costs.get(k) ?? Infinity)) continue;
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
      if (actor.state !== state && state !== 'running') actor.feedbackUntil = this.time + 6;
      actor.state = state; if (label) actor.last = label;
      if (state === 'running') {
        actor.summoned = true;
        this.queue = this.queue.filter(job => !(job.id === id && job.roam));
        if (this.motion(id)?.roam) this.motion(id).recall = true;
        if (this.motion(id)?.exit) this.motion(id).recall = true;
        this.queue = this.queue.filter(job => !(job.id === id && job.exit));
        if (!actor.present && !this.queue.some(job => job.id === id) && !this.jobs.has(id)) this.queue.push({id, exit: false});
      }
    }
    finish(state) {
      for (const actor of this.actors) if (actor.state === 'running') this.set(actor.id, state);
    }
    tick(dt, reduced = false, idle = false) {
      dt = Math.max(0, Math.min(dt, .05)); this.time += dt;
      if (idle && !reduced && this.time > this.nextRoam && this.jobs.size < 3 && !this.queue.length) {
        const candidates = this.actors.filter(a => a.present && !this.jobs.has(a.id) && a.state !== 'running' && this.time > a.feedbackUntil);
        const resident = candidates[this.serial++ % Math.max(1, candidates.length)];
        if (resident) { this.queue.push({id: resident.id, roam: true}); this.nextRoam=this.time+14+this.random(resident)*18; }
        else this.nextRoam=this.time+3;
      }
      for (const actor of this.actors) {
        if (['completed','failed','canceled','simulated','submitted'].includes(actor.state) && this.time>actor.feedbackUntil) { actor.lastResult={state:actor.state,label:actor.last,taskId:actor.taskId}; actor.state='idle'; }
        actor.phase += dt * (actor.pose === 'walking' ? actor.speed / 16 : 1.2 + actor.seed * .07);
        if (actor.state === 'running') actor.elapsed += dt;
        if (idle && !reduced && !actor.resident && !actor.present && this.time > actor.nextVisit && !this.queue.some(j => j.id === actor.id) && !this.jobs.has(actor.id)) {
          this.queue.push({id: actor.id, visit: true}); actor.nextVisit = this.time + 70 + this.random(actor)*50;
        }
        if (actor.present && !actor.resident && actor.state !== 'running' && this.time > actor.feedbackUntil && this.time > (actor.stayUntil || 0) && !this.queue.some(job => job.id === actor.id) && !this.jobs.has(actor.id)) this.queue.push({id: actor.id, exit: true});
      }
      const priority=job=>this.actors.find(a=>a.id===job.id).state==='running'?0:job.exit?1:2;
      this.queue.sort((a,b)=>priority(a)-priority(b));
      for (const job of [...this.queue]) {
        if (this.jobs.size >= 3) break;
        if (this.jobs.has(job.id)) continue;
        const actor = this.actors.find(a => a.id === job.id);
        const entry = !job.exit && !job.roam;
        const direction=entry?'enter':job.exit?'exit':null;
        if (direction && this.doorDirection && direction !== this.doorDirection) continue;
        if (direction && this.gateOwner && this.gateOwner !== job.id) continue;
        this.queue.splice(this.queue.indexOf(job),1);
        if (entry && !job.visit && actor.state !== 'running') continue;
        if (direction && !this.doorDirection) this.doorDirection=direction;
        if (job.visit) actor.stayUntil = this.time + 48 + this.random(actor)*28;
        const motion = {...job,entry,stage:entry?'open':'rise',elapsed:0,path:null,index:0};
        this.jobs.set(job.id,motion);
        if (job.exit) this.gateOwner=job.id;
        if (entry) { this.gateOwner=job.id; actor.present=true; actor.x=-60; actor.y=gate.y; actor.heading=1; }
        else actor.pose='rising';
        if (job.roam && !actor.station) { motion.stage='stroll'; motion.path=this.path(actor,{x:actor.deskX-80,y:actor.deskY+70},actor); actor.pose='walking'; }
      }
      for (const job of [...this.jobs.values()]) {
        this.transit=job;
        this.advance(dt,reduced,idle);
        if (!this.transit) { this.jobs.delete(job.id); if(this.gateOwner===job.id) this.gateOwner=null; }
      }
      if (!this.gateOwner) {
        if (this.doorDirection && this.time > this.doorHoldUntil && !this.hasDoorWork(this.doorDirection)) this.door=Math.max(0,this.door-dt*4);
        if (!this.door && (!this.doorDirection || !this.hasDoorWork(this.doorDirection))) { this.doorDirection=null; this.doorHoldUntil=0; }
      }
      this.transit=this.jobs.values().next().value || null;
    }
    advance(dt, reduced, idle) {
      const job = this.transit, actor = this.actors.find(a => a.id === job.id);
      job.elapsed += dt;
      if (job.exit && actor.x < 155 && actor.y > 515) {
        if(this.gateOwner && this.gateOwner!==actor.id) { actor.pose='waiting'; actor.speed=0; return; }
        this.gateOwner=actor.id;
      }
      const transition = stage => { job.stage = stage; job.elapsed = 0; };
      if (job.roam && (job.waitTotal || 0) > 3) {
        job.roam=false; job.waitTotal=0;
        job.path=this.path(actor,{x:actor.deskX,y:actor.deskY+(actor.station?120:70)},actor);
        transition('return');
      }
      if (job.recall && ['walk', 'stroll', 'linger'].includes(job.stage) && actor.present && distance(actor, gate) > 65) {
        job.exit = false; job.roam = false; job.recall = false; job.path = this.path(actor, {x: actor.deskX, y: actor.deskY + 120}, actor); transition('walk');
      }
      if (job.stage === 'open') {
        if (job.elapsed < .5 && !reduced) { actor.x = -60 + job.elapsed * 60; actor.pose = 'walking'; actor.speed = 60; return; }
        actor.x = -30;
        if (this.door < 1) {
          actor.pose = 'opening';
          if (job.elapsed < .85 && !reduced) return;
          this.doorDirection='enter';
          this.door = Math.min(1, this.door + dt * 4);
        }
        if (this.door === 1) {
          actor.present = true; actor.x = -30; actor.y = gate.y; actor.pose = 'walking';
          job.path = [{x: 95, y: gate.y}]; transition('enter');
        }
      } else if (job.stage === 'rise') {
        if (job.elapsed > (reduced ? 0 : .55)) {
          actor.pose = 'walking';
          job.path = [{x: actor.deskX, y: actor.deskY + 120}]; transition('undock');
        }
      } else if (job.stage === 'sit') {
        actor.pose = 'sitting';
        if (job.elapsed > (reduced ? 0 : .7)) { actor.pose = 'seated'; this.transit = null; }
      } else if (job.stage === 'turn') {
        actor.pose = 'turning';
        if (job.elapsed > (reduced ? 0 : .25)) { job.path = [{x: actor.deskX, y: actor.deskY + 70}]; transition('dock'); }
      } else if (job.stage === 'linger') {
        actor.pose = 'idle';
        if (job.recall || actor.state === 'running' || !idle || job.elapsed > 3 + actor.seed % 4) { job.path = this.path(actor, {x: actor.deskX, y: actor.deskY + (actor.station ? 120 : 70)}, actor); transition('return'); }
      } else if (job.stage === 'close') {
        this.door = Math.max(0, this.door - dt * 4);
        if (!this.door) { if(!this.hasDoorWork('exit',actor.id)){this.doorDirection=null;this.doorHoldUntil=0;} this.transit = null; if (actor.state === 'running') this.queue.unshift({id: actor.id}); }
      } else {
        if (!job.path) {
          job.waitTotal=(job.waitTotal||0)+dt;
          actor.pose='waiting'; actor.speed=0;
          if (this.time < (job.retryAt || 0)) return;
          job.retryAt=this.time+1.2+actor.seed*.07;
          job.path = this.path(actor, job.exit ? gate : job.stage === 'stroll' ? {x: actor.deskX + 80, y: actor.deskY + 120} : {x: actor.deskX, y: actor.deskY + 120}, actor);
          actor.pose = 'waiting'; return;
        }
        const target = job.path[0];
        if (!target) {
          actor.speed = 0;
          if (job.stage === 'undock') { job.path = this.path(actor, job.roam ? {x: actor.deskX + 80, y: actor.deskY + 120} : gate, actor); transition(job.roam ? 'stroll' : 'walk'); }
          else if (job.stage === 'enter') { job.path = this.path(actor, {x: actor.deskX, y: actor.deskY + 120}, actor); transition('walk'); }
          else if (job.stage === 'cross') {
            actor.present = false; actor.pose = 'absent'; actor.nextVisit = this.time + 40 + this.random(actor)*45;
            if (this.hasDoorWork('exit',actor.id)) {
              this.gateOwner=null; this.doorDirection='exit'; this.doorHoldUntil=this.time+2;
              if(actor.state==='running')this.queue.unshift({id:actor.id,exit:false});
              this.transit=null;
            } else transition('close');
          }
          else if (job.stage === 'stroll') { actor.pose = 'idle'; transition('linger'); }
          else if (job.stage === 'return' && !actor.station) { actor.pose = 'idle'; this.transit = null; }
          else if (job.exit) {
            this.doorDirection='exit';
            this.door = Math.min(1, this.door + dt * 4);
            actor.pose = 'waiting';
            if (this.door === 1) { job.path = [{x: -30, y: gate.y}]; transition('cross'); }
          } else if (job.stage === 'dock') { actor.pose = 'sitting'; transition('sit'); }
          else { actor.pose = 'turning'; transition('turn'); }
          return;
        }
        const d = distance(actor, target);
        const heading = target.x < actor.x - .1 ? -1 : target.x > actor.x + .1 ? 1 : actor.heading;
        if (!reduced && actor.heading !== heading) { actor.heading = heading; job.lookUntil = this.time + .22; }
        if (this.time < (job.lookUntil || 0)) { actor.pose = 'turning'; actor.speed = 0; return; }
        const speed = reduced ? 420 : Math.min(120 + actor.seed * 5, actor.speed + dt * 240, job.path.length === 1 ? Math.max(45, d * 6) : 160);
        const travel = Math.min(d, speed * dt), next = {x: actor.x + (target.x - actor.x) / (d || 1) * travel, y: actor.y + (target.y - actor.y) / (d || 1) * travel};
        if (job.exit && next.x < 85 && next.y > 515 && this.door < 1) {
          if (this.gateOwner && this.gateOwner !== actor.id) { actor.pose='waiting'; actor.speed=0; return; }
          this.gateOwner=actor.id;
          actor.heading = -1; actor.pose = 'door-handle'; actor.speed = 0;
          job.handleElapsed = (job.handleElapsed || 0) + dt;
          this.doorDirection='exit';
          if (reduced || job.handleElapsed > .4) this.door = Math.min(1,this.door+dt*2);
          return;
        }
        if (this.blocked(next, actor, ['dock', 'undock'].includes(job.stage))) { actor.pose = 'waiting'; actor.speed = 0; job.waitTotal=(job.waitTotal||0)+dt; job.blockedFor=(job.blockedFor||0)+dt; if(job.blockedFor>.7 && !['dock','undock','enter','cross'].includes(job.stage)) { const end=job.path[job.path.length-1]; job.path=this.path(actor,end,actor); job.blockedFor=0; } return; }
        job.waitTotal=0;
        actor.heading = target.x < actor.x ? -1 : target.x > actor.x ? 1 : actor.heading;
        actor.facing = target.y < actor.y - .1 ? 'back' : 'side';
        actor.x = next.x; actor.y = next.y; actor.speed = speed; actor.pose = 'walking';
        if (d <= travel + .01) job.path.shift();
        if (distance(actor,gate)>85 && !job.exit && job.stage!=='enter' && this.gateOwner===actor.id) {
          this.gateOwner=null;
          if(this.doorDirection==='enter')this.doorHoldUntil=Math.max(this.doorHoldUntil,this.time+2);
        }
      }
    }
  }
  return {Floor, roles, gate, radius, distance};
})();
