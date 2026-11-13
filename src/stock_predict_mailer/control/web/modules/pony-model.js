/* Deterministic floor navigation; independent of DOM and backend timing. */
globalThis.PonyFloor = (() => {
  const roles = [
    ['main', '主 Agent', '#dc092a', 220, 160, true],
    ['prediction', '预测分析', '#74bc6d', 525, 160, false],
    ['risk', '风险分析', '#6900f1', 830, 160, false],
    ['mail', '邮件投递', '#1698eb', 220, 430, true],
    ['charts', '图表生成', '#19d8c4', 525, 430, false],
    ['advice', '建议生成', '#f0d415', 830, 430, false],
    ['assistant', '分析助理', '#e58b36', 900, 580, true]
  ].map(([id, name, color, x, y, resident]) => ({id, name, color, x, y, resident, station: id !== 'assistant'}));
  const hall=typeof matchMedia==='undefined'||matchMedia('(min-width: 761px)').matches;
  if(hall){const slots={prediction:[220,160],main:[525,160],risk:[830,160],charts:[220,430],advice:[525,430],mail:[830,430],assistant:[-20,580]};for(const role of roles)[role.x,role.y]=slots[role.id];}
  const gate = {get x(){return PonyDoor.frame.x+35;},get y(){return PonyDoor.frame.y+120;}}, radius = 40;
  // Shared ground footprint: table legs reach y=64, chair wheels y=106.
  const furniture=Object.freeze({scaleX:.78,scaleY:.86,halfWidth:110*.78,top:-53*.86,bottom:65*.86,chairHalfWidth:32,chairTop:35,chairBottom:106,seat:70,approach:150});
  const intersects=(a,b,box)=>{
    let low=0,high=1;
    for(const [axis,min,max]of [['x',box.left,box.right],['y',box.top,box.bottom]]){
      const d=b[axis]-a[axis];
      if(Math.abs(d)<1e-9){if(a[axis]<=min||a[axis]>=max)return false;continue;}
      const one=(min-a[axis])/d,two=(max-a[axis])/d;
      low=Math.max(low,Math.min(one,two));high=Math.min(high,Math.max(one,two));
      if(low>=high-1e-9)return false;
    }
    return high>0&&low<1;
  };
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  class Floor {
    constructor() { this.reset(); }
    reset() {
      this.jobs = new Map(); this.gateOwner = null; this.time = 0; this.door = 0; this.doorDirection = null; this.doorHoldUntil = 0; this.transit = null; this.queue = []; this.serial = 0; this.nextRoam = 5;
      this.metrics={plans:0,expanded:0,maxExpanded:0,yields:0};this.planBudget=Infinity;this.boxCache=new Map();
      this.actors = roles.map((role, index) => ({...role, x: role.x, y: role.y + furniture.seat, deskX: role.x, deskY: role.y,
        present: role.resident, pose: role.id === 'assistant' ? 'idle' : role.resident ? 'seated' : 'absent', state: 'idle', phase: index * 2.37, seed: index, nextVisit: 8 + index * 11, feedbackUntil: 0, activity: index % 5, elapsed: 0, completedSteps: 0, speed: 0, heading: 1, last: '', summoned: false}));
    }
    motion(id) { return this.jobs.get(id) || null; }
    relocateDoor(x,y){
      const dx=x-PonyDoor.frame.x,dy=y-PonyDoor.frame.y;
      if(Math.abs(dx)+Math.abs(dy)<.01)return;
      PonyDoor.position(x,y);
      for(const actor of this.actors){
        const job=this.motion(actor.id),atDoor=job&&['open','enter','cross','close','latch','exit-open'].includes(job.stage);
        if(atDoor||actor.present&&(actor.x<(hall?-80:25)||actor.y>670)){
          actor.x+=dx;actor.y+=dy;
          if(atDoor){job.path?.forEach(p=>{p.x+=dx;p.y+=dy;});if(Number.isFinite(job.approachX)){job.approachX+=dx;job.approachY+=dy;}}
          else if(job){job.path=null;delete job.resumeGoal;}
        }
        if(job?.exit&&!atDoor){job.path=null;job.goal={x:gate.x,y:gate.y};delete job.resumeGoal;}
      }
    }
    operateDoor(job,actor,dt,reduced,closing=false) {
      if(!job.doorAction) job.doorAction={elapsed:0,from:this.door,side:actor.x<gate.x?'outside':'inside'};
      const action=job.doorAction;
      action.elapsed+=reduced?dt*6:dt;
      const pose=PonyDoor.sample(action.elapsed,closing,action.from);
      this.door=pose.open;
      actor.heading=action.side==='outside'?1:-1;
      actor.facing='side'; actor.speed=0; actor.pose=closing?'door-close':'door-handle';
      actor.doorAction={...pose,side:action.side,closing};
      if(pose.done) { delete job.doorAction;actor.doorAction=null;actor.pose='waiting'; }
      return pose.done;
    }
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
    boxes(actor,dock=false){
      const key=dock||hall&&actor.id==='assistant'?actor.id:'all';if(this.boxCache.has(key))return this.boxCache.get(key);
      const boxes=roles.filter(r=>r.station&&!(dock&&r.id===actor.id)).flatMap(r=>[
        {left:r.x-furniture.halfWidth-radius,right:r.x+furniture.halfWidth+radius,top:r.y+furniture.top-radius,bottom:r.y+furniture.bottom+radius},
        ...dock&&r.id===actor.id?[]:[{left:r.x-furniture.chairHalfWidth-radius,right:r.x+furniture.chairHalfWidth+radius,top:r.y+furniture.chairTop-radius,bottom:r.y+furniture.chairBottom+radius}]
      ]);
      if(hall&&actor.id!=='assistant'){const r=roles.find(r=>r.id==='assistant');boxes.push({left:r.x-32-radius,right:r.x+32+radius,top:r.y+46-radius,bottom:r.y+80+radius});}
      this.boxCache.set(key,boxes);return boxes;
    }
    areas(){return [{left:hall?-80:25,right:hall?1030:935,top:130,bottom:670},{left:Math.min(25,PonyDoor.frame.x+8),right:Math.max(hall?100:25,PonyDoor.frame.insideX+40),top:130,bottom:Math.max(670,gate.y+10)}];}
    inside(a,b){
      const intervals=[];
      for(const box of this.areas()){
        let low=0,high=1;
        for(const [axis,min,max]of [['x',box.left,box.right],['y',box.top,box.bottom]]){
          const d=b[axis]-a[axis];
          if(Math.abs(d)<1e-9){if(a[axis]<min||a[axis]>max){high=-1;break;}}
          else{const one=(min-a[axis])/d,two=(max-a[axis])/d;low=Math.max(low,Math.min(one,two));high=Math.min(high,Math.max(one,two));}
        }
        if(low<=high)intervals.push([low,high]);
      }
      intervals.sort((a,b)=>a[0]-b[0]);let covered=0;
      for(const [low,high]of intervals){if(low>covered+1e-8)return false;covered=Math.max(covered,high);}
      return covered>=1-1e-8;
    }
    blocked(point, actor, dock = false, traffic=true) {
      const portal = (this.motion(actor.id)?.stage === 'open' && point.x >= PonyDoor.frame.x-65 && point.x <= PonyDoor.frame.x) || (this.door === 1 && ['enter', 'cross'].includes(this.motion(actor.id)?.stage) && point.x >= PonyDoor.frame.outsideWalkX && point.x <= PonyDoor.frame.insideX);
      if (portal && Math.abs(point.y-gate.y)<1) return this.actors.some(other=>other!==actor && other.present && distance(point,other)<radius*2+3);
      // Keep the whole 130-unit-tall character within the room at the top.
      if (!this.areas().some(b=>point.x>=b.left&&point.x<=b.right&&point.y>=b.top&&point.y<=b.bottom)) return true;
      if(this.boxes(actor,dock).some(b=>point.x>b.left&&point.x<b.right&&point.y>b.top&&point.y<b.bottom))return true;
      return traffic&&this.actors.some(other => other !== actor && other.present && distance(point, other) < radius * 2 + 3);
    }
    clear(a,b,actor,dock=false,traffic=true,margin=0){
      if(!this.inside(a,b)||this.blocked(b,actor,dock,false)||this.boxes(actor,dock).some(box=>intersects(a,b,box)))return false;
      if(!traffic)return true;
      const dx=b.x-a.x,dy=b.y-a.y,length=dx*dx+dy*dy;
      return !this.actors.some(other=>{
        if(other===actor||!other.present)return false;
        const t=length?Math.max(0,Math.min(1,((other.x-a.x)*dx+(other.y-a.y)*dy)/length)):0;
        // A stopped pair may already touch the safety boundary. Permit a
        // route away from that boundary instead of trapping its start node.
        const clearance=Math.min(radius*2+3+margin,distance(a,other));
        return distance(other,{x:a.x+dx*t,y:a.y+dy*t})<clearance-1e-7;
      });
    }
    path(start, end, actor) {
      if(this.planBudget<=0)return null;
      this.planBudget--;this.metrics.plans++;
      if(this.clear(start,end,actor,false,true,1))return [{...end}];
      // A viewport-anchored door can be far outside the camera's floor bounds.
      // Cross its empty approach in one checked segment; search the furnished
      // room rather than exhausting the bounded grid over that empty space.
      let prefix=[],suffix=[];
      if(hall&&distance(start,end)>800){
        const [room,corridor]=this.areas(),outside=p=>p.x<room.left||p.x>room.right||p.y>room.bottom;
        const fromOutside=outside(start),toOutside=outside(end);
        if(fromOutside!==toOutside){
          const outer=fromOutside?start:end,inner=fromOutside?end:start;
          const x=Math.max(room.left+10,Math.min(corridor.right-10,room.right-10));
          const candidates=[Math.min(room.bottom,Math.max(room.top+10,outer.y)),room.bottom-10,325,room.top+10].map(y=>({x,y}));
          candidates.sort((a,b)=>distance(outer,a)+distance(a,inner)-distance(outer,b)-distance(b,inner));
          const join=candidates.find(point=>!this.blocked(point,actor)&&this.clear(outer,point,actor,false,true,1));
          if(join){if(fromOutside){start=join;prefix=[join];}else{suffix=[end];end=join;}}
        }
      }
      if(this.clear(start,end,actor,false,true,1))return [...prefix,{...end},...suffix];
      const key=p=>`${p.x},${p.y}`,snap=p=>({x:Math.round(p.x/10)*10,y:Math.round(p.y/10)*10});
      const nearest=snap(start),candidates=[];
      for(const dx of [-10,0,10])for(const dy of [-10,0,10]){
        const p={x:nearest.x+dx,y:nearest.y+dy};
        if(!this.blocked(p,actor)&&this.clear(start,p,actor,false,true,1))candidates.push(p);
      }
      candidates.sort((a,b)=>distance(a,start)-distance(b,start));
      const first=candidates[0];if(!first)return null;
      const last=snap(end),costs=new Map([[key(first),0]]),prev=new Map(),closed=new Set(),heap=[];
      const push=node=>{heap.push(node);let i=heap.length-1;while(i){const parent=(i-1)>>1;if(heap[parent].score<=node.score)break;heap[i]=heap[parent];i=parent;}heap[i]=node;};
      const pop=()=>{const result=heap[0],tail=heap.pop();if(heap.length){let i=0;while(i*2+1<heap.length){let child=i*2+1;if(child+1<heap.length&&heap[child+1].score<heap[child].score)child++;if(heap[child].score>=tail.score)break;heap[i]=heap[child];i=child;}heap[i]=tail;}return result;};
      push({...first,score:distance(first,last)});let found=null;
      while(heap.length&&closed.size<6000){
        const p=pop(),pk=key(p);if(closed.has(pk))continue;closed.add(pk);
        if(pk===key(last)&&this.clear(p,end,actor,false,true,1)){found=p;break;}
        for(const [dx,dy]of [[10,0],[-10,0],[0,10],[0,-10],[10,10],[10,-10],[-10,10],[-10,-10]]){
          const next={x:p.x+dx,y:p.y+dy},k=key(next),cost=costs.get(pk)+Math.hypot(dx,dy);
          if(closed.has(k)||cost>=(costs.get(k)??Infinity)||this.blocked(next,actor)||!this.clear(p,next,actor,false,true,1))continue;
          costs.set(k,cost);prev.set(k,p);push({...next,score:cost+distance(next,last)});
        }
      }
      this.metrics.expanded+=closed.size;this.metrics.maxExpanded=Math.max(this.metrics.maxExpanded,closed.size);
      if(!found)return null;
      const route=[end];let p=found;
      while(prev.has(key(p))){route.unshift(p);p=prev.get(key(p));}route.unshift(first);
      const smooth=[];let anchor=start,index=0;
      while(index<route.length){
        let last=route.length-1;while(last>=index&&!this.clear(anchor,route[last],actor,false,true,1))last--;
        if(last<index)return null;
        smooth.push(route[last]);anchor=route[last];index=last+1;
      }
      return [...prefix,...smooth,...suffix];
    }
    yieldRoute(actor,other,job,doorPriority=false){
      const otherJob=this.motion(other.id);
      if(!otherJob||!doorPriority&&actor.seed<other.seed)return false;
      const goal=job.resumeGoal||job.path?.at(-1)||job.goal;if(!goal)return false;
      const dx=goal.x-actor.x,dy=goal.y-actor.y,d=Math.hypot(dx,dy)||1;
      const candidates=[1,-1].map(side=>({x:actor.x-dy/d*90*side,y:actor.y+dx/d*90*side}));
      if(doorPriority)candidates.push({x:actor.x+100,y:actor.y});
      for(const x of hall?[50,115,372.5,677.5,990]:[115,372.5,677.5,930])for(const side of [-1,1])candidates.push({x,y:actor.y+side*85});
      const cost=point=>distance(point,actor)-(doorPriority&&point.x>=actor.x+90?200:0);
      candidates.sort((a,b)=>cost(a)-cost(b));
      for(const point of candidates){
        if(this.blocked(point,actor)||distance(point,other)<85)continue;
        const route=this.path(actor,point,actor);if(!route)continue;
        job.resumeGoal=goal;job.path=route;job.yieldingTo=other.id;job.yieldStarted=this.time;job.blockedFor=0;this.metrics.yields++;return true;
      }
      return false;
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
      dt = Math.max(0, Math.min(dt, .05)); this.time += dt;this.planBudget=reduced?4:1;
      if (idle && !reduced && this.time > this.nextRoam && this.jobs.size < 3 && !this.queue.length) {
        const candidates = this.actors.filter(a => a.present && !this.jobs.has(a.id) && a.state !== 'running' && this.time > a.feedbackUntil);
        const resident = candidates[this.serial++ % Math.max(1, candidates.length)];
        if (resident) { this.queue.push({id: resident.id, roam: true}); this.nextRoam=this.time+14+this.random(resident)*18; }
        else this.nextRoam=this.time+3;
      }
      for (const actor of this.actors) {
        if (['completed','failed','canceled','simulated','submitted'].includes(actor.state) && this.time>actor.feedbackUntil) { actor.lastResult={state:actor.state,label:actor.last,taskId:actor.taskId}; actor.state='idle'; }
        // Advance source gait by distance, including its measured root translation.
        const stride=(globalThis.PonyReference?.strideDistance||143)*.88;
        if(actor.pose === 'walking') actor.phase += dt * actor.speed * Math.PI * 2 / stride;
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
        if (entry) { this.gateOwner=job.id; actor.present=true; actor.x=PonyDoor.frame.x-60; actor.y=gate.y; actor.heading=1; }
        else actor.pose='rising';
        if (job.roam && !actor.station) { motion.stage='stroll'; motion.path=this.path(actor,{x:actor.deskX-80,y:actor.deskY+furniture.seat},actor); actor.pose='walking'; }
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
      this.transit=this.jobs.values().next().value || null;this.planBudget=Infinity;
    }
    advance(dt, reduced, idle) {
      const job = this.transit, actor = this.actors.find(a => a.id === job.id);
      job.elapsed += dt;
      if (job.exit && actor.x < PonyDoor.frame.insideX+40 && actor.y > gate.y-35) {
        if(this.gateOwner && this.gateOwner!==actor.id) {
          if(!job.resumeGoal){
            const owner=this.actors.find(a=>a.id===this.gateOwner);
            if(owner&&distance(actor,owner)<180)this.yieldRoute(actor,owner,job,true);
            actor.pose='waiting'; actor.speed=0; return;
          }
        } else this.gateOwner=actor.id;
      }
      const transition = stage => { job.stage = stage; job.elapsed = 0;job.goal=null; };
      if (job.roam && ['stroll','linger'].includes(job.stage) && (job.waitTotal || 0) > 3) {
        job.roam=false; job.waitTotal=0;
        job.path=this.path(actor,{x:actor.deskX,y:actor.deskY+(actor.station?furniture.approach:furniture.seat)},actor);
        transition('return');
      }
      if (job.recall && ['walk', 'stroll', 'linger'].includes(job.stage) && actor.present && distance(actor, gate) > 65) {
        job.exit = false; job.roam = false; job.recall = false; job.path = this.path(actor, {x: actor.deskX, y: actor.deskY + (actor.station?furniture.approach:furniture.seat)}, actor); transition('walk');
      }
      if (job.stage === 'open') {
        if (job.elapsed < .7 && !reduced) {
          const t=job.elapsed/.7, before=actor.x;
          actor.x=PonyDoor.frame.x-60+PonyDoor.ease(t)*30;actor.pose='walking';actor.speed=(actor.x-before)/dt;return;
        }
        actor.x = PonyDoor.frame.x-30;
        if ((this.door===1&&!job.doorAction)||this.operateDoor(job,actor,dt,reduced)) {
          actor.present = true; actor.x = PonyDoor.frame.outsideWalkX; actor.y = gate.y; actor.pose = 'walking';
          job.path = [{x: PonyDoor.frame.insideX, y: gate.y}]; transition('enter');
        }
      } else if (job.stage==='exit-open') {
        if(job.elapsed<.45&&!reduced) {
          const before={x:actor.x,y:actor.y},t=PonyDoor.ease(job.elapsed/.45);
          const next={x:job.approachX+(PonyDoor.frame.insideX-job.approachX)*t,y:job.approachY+(gate.y-job.approachY)*t};
          if(this.actors.some(a=>a!==actor&&a.present&&distance(a,next)<radius*2+3)){job.elapsed-=dt;actor.pose='waiting';actor.speed=0;return;}
          actor.x=next.x;actor.y=next.y;
          actor.pose='walking';actor.speed=distance(actor,before)/dt;return;
        }
        actor.x=PonyDoor.frame.insideX;actor.y=gate.y;
        if(this.operateDoor(job,actor,dt,reduced)) {
          job.path=[{x:gate.x,y:gate.y}];transition('walk');
        }
      } else if (job.stage === 'rise') {
        if (job.elapsed > (reduced ? 0 : .55)) {
          actor.pose = 'walking';
          job.path = [{x: actor.deskX, y: actor.deskY + (actor.station?furniture.approach:furniture.seat)}]; transition('undock');
        }
      } else if (job.stage === 'sit') {
        actor.pose = 'sitting';
        if (job.elapsed > (reduced ? 0 : .7)) { actor.pose = 'seated'; this.transit = null; }
      } else if (job.stage === 'turn') {
        actor.pose = 'turning';
        if (job.elapsed > (reduced ? 0 : .25)) { job.path = [{x: actor.deskX, y: actor.deskY + furniture.seat}]; transition('dock'); }
      } else if (job.stage === 'linger') {
        actor.pose = 'idle';
        if (job.recall || actor.state === 'running' || !idle || job.elapsed > 3 + actor.seed % 4) { job.path = this.path(actor, {x: actor.deskX, y: actor.deskY + (actor.station ? furniture.approach : furniture.seat)}, actor); transition('return'); }
      } else if (job.stage === 'close' || job.stage === 'latch') {
        // The last pony in a batch remains beside the handle until the door closes.
        const entering=job.stage==='latch';
        if(!entering)actor.x=PonyDoor.frame.x-30; // Reposition only after the whole body is hidden outside.
        if (this.operateDoor(job,actor,dt,reduced,true)) {
          this.doorDirection=null;this.doorHoldUntil=0;
          if(entering) {
            actor.pose='waiting';
            job.path=this.path(actor,{x:actor.deskX,y:actor.deskY+(actor.station?furniture.approach:furniture.seat)},actor);transition('walk');
          } else {
            actor.present=false;actor.pose='absent';actor.nextVisit=this.time+40+this.random(actor)*45;
            this.transit=null;
            if(actor.state==='running')this.queue.unshift({id:actor.id});
          }
        }
      } else {
        if (!job.path) {
          job.waitTotal=(job.waitTotal||0)+dt;
          actor.pose='waiting'; actor.speed=0;
          if (this.time < (job.retryAt || 0)) return;
          const near=this.actors.find(a=>a!==actor&&a.present&&distance(a,actor)<90);
          if(near&&!job.resumeGoal&&this.yieldRoute(actor,near,job))return;
          job.retryAt=this.time+1.2+actor.seed*.07;
          job.goal=job.resumeGoal||(job.exit ? gate : job.stage === 'stroll' ? {x: actor.deskX + 80, y: actor.deskY + (actor.station?furniture.approach:furniture.seat)} : {x: actor.deskX, y: actor.deskY + (actor.station?furniture.approach:furniture.seat)});
          job.path = this.path(actor, job.goal, actor);
          actor.pose = 'waiting'; return;
        }
        const target = job.path[0];
        if(target&&!job.resumeGoal)job.goal=job.path.at(-1);
        if (!target) {
          actor.speed = 0;
          if(job.resumeGoal){
            const other=this.actors.find(a=>a.id===job.yieldingTo);
            if(other&&distance(actor,other)<100&&this.time-job.yieldStarted<3){actor.pose='waiting';return;}
            const goal=job.resumeGoal;job.path=this.path(actor,goal,actor);if(!job.path){actor.pose='waiting';return;}
            delete job.resumeGoal;delete job.yieldingTo;return;
          }
          if (job.stage === 'undock') { job.path = this.path(actor, job.roam ? {x: actor.deskX + 80, y: actor.deskY + (actor.station?furniture.approach:furniture.seat)} : gate, actor); transition(job.roam ? 'stroll' : 'walk'); }
          else if (job.stage === 'enter') {
            if(this.hasDoorWork('enter',actor.id)) { job.path = this.path(actor, {x: actor.deskX, y: actor.deskY + (actor.station?furniture.approach:furniture.seat)}, actor); transition('walk'); }
            else { actor.pose='door-close'; transition('latch'); }
          }
          else if (job.stage === 'cross') {
            if (this.hasDoorWork('exit',actor.id)) {
              actor.present = false; actor.pose = 'absent'; actor.nextVisit = this.time + 40 + this.random(actor)*45;
              this.gateOwner=null; this.doorDirection='exit'; this.doorHoldUntil=this.time+2;
              if(actor.state==='running')this.queue.unshift({id:actor.id,exit:false});
              this.transit=null;
            } else { actor.x=PonyDoor.frame.x-30; actor.pose='door-close'; transition('close'); }
          }
          else if (job.stage === 'stroll') { actor.pose = 'idle'; transition('linger'); }
          else if (job.stage === 'return' && !actor.station) { actor.pose = 'idle'; this.transit = null; }
          else if (job.exit) {
            this.doorDirection='exit';
            actor.pose = 'waiting';
            if (this.door === 1) { job.path = [{x: PonyDoor.frame.outsideWalkX, y: gate.y}]; transition('cross'); }
          } else if (job.stage === 'dock') { actor.pose = 'sitting'; transition('sit'); }
          else { actor.pose = 'turning'; transition('turn'); }
          return;
        }
        const d = distance(actor, target);
        const heading = target.x < actor.x - .1 ? -1 : target.x > actor.x + .1 ? 1 : actor.heading;
        actor.heading=heading;
        const speed = reduced ? 420 : Math.min(120 + actor.seed * 5, actor.speed + dt * 240, job.path.length === 1 ? Math.max(45, d * 6) : 160);
        const travel = Math.min(d, speed * dt), next = {x: actor.x + (target.x - actor.x) / (d || 1) * travel, y: actor.y + (target.y - actor.y) / (d || 1) * travel};
        if (job.exit && next.x < PonyDoor.frame.insideX && next.y > gate.y-35 && this.door < 1) {
          if (this.gateOwner && this.gateOwner !== actor.id) { actor.pose='waiting'; actor.speed=0; return; }
          if(this.actors.some(a=>a!==actor&&a.present&&distance(a,{x:PonyDoor.frame.insideX,y:gate.y})<radius*2+3)){actor.pose='waiting';actor.speed=0;return;}
          this.gateOwner=actor.id;
          actor.heading = -1; actor.pose = 'turning'; actor.speed = 0;
          job.approachX=actor.x;job.approachY=actor.y;transition('exit-open');
          this.doorDirection='exit';
          return;
        }
        const docking=['dock','undock'].includes(job.stage);
        const portal=['enter','cross'].includes(job.stage)||next.x<PonyDoor.frame.insideX;
        if (this.blocked(next, actor, docking)||!portal&&!this.clear(actor,next,actor,docking)) {
          actor.pose='waiting';actor.speed=0;job.waitTotal=(job.waitTotal||0)+dt;job.blockedFor=(job.blockedFor||0)+dt;
          const other=this.actors.find(a=>a!==actor&&a.present&&distance(next,a)<radius*2+3);
          if(other&&this.gateOwner===actor.id&&['enter','cross'].includes(job.stage)){
            const blockedJob=this.motion(other.id);
            if(blockedJob&&!blockedJob.resumeGoal&&!['open','enter','cross','close','latch','exit-open'].includes(blockedJob.stage))this.yieldRoute(other,actor,blockedJob,true);
          }
          // Stagger replanning so two ponies do not repeatedly choose mirrored detours.
          if(other&&job.blockedFor>.35&&!job.resumeGoal&&!docking&&!portal&&this.yieldRoute(actor,other,job))return;
          const patience=other&&this.motion(other.id)?1.8:.8;
          if(job.blockedFor>patience&&this.time>=(job.replanAt||0)&&!['dock','undock','enter','cross'].includes(job.stage)) {
            job.replanAt=this.time+1.2+actor.seed*.09;
            const end=job.path[job.path.length-1];job.path=this.path(actor,end,actor);job.blockedFor=0;
          }
          return;
        }
        job.waitTotal=0;job.blockedFor=0;
        actor.heading = target.x < actor.x ? -1 : target.x > actor.x ? 1 : actor.heading;
        actor.facing = target.y < actor.y - .1 ? 'back' : target.y > actor.y + .1 ? 'front' : 'side';
        actor.x = next.x; actor.y = next.y; actor.speed = speed; actor.pose = 'walking';
        if (d <= travel + .01) job.path.shift();
        if (distance(actor,gate)>85 && distance(actor,{x:PonyDoor.frame.insideX,y:gate.y})>radius*2+3 && !job.exit && job.stage!=='enter' && this.gateOwner===actor.id) {
          this.gateOwner=null;
          if(this.doorDirection==='enter')this.doorHoldUntil=Math.max(this.doorHoldUntil,this.time+2);
        }
      }
    }
  }
  return {Floor, roles, gate, radius, distance, furniture, hall};
})();
