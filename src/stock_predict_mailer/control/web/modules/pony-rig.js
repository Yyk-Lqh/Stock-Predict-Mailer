/* World-space desk contacts and fixed-length two-link forelegs. No DOM or tasks. */
globalThis.PonyRig = (() => {
  const scale = .88;
  const desk = Object.freeze({keyboard: {left:{x:-38,y:-2},right:{x:31,y:-2}}, mouse:{x:48,y:-2}, seatY:70});
  const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  const smooth = x => { x=clamp(x,0,1); return x*x*(3-2*x); };
  const mix = (a,b,t) => a+(b-a)*t;
  const point = (a,b,t) => ({x:mix(a.x,b.x,t),y:mix(a.y,b.y,t)});
  function solve(shoulder, target, bend = 1, upper = 24, lower = 25) {
    const dx=target.x-shoulder.x, dy=target.y-shoulder.y, raw=Math.hypot(dx,dy);
    // Keep a visible elbow bend at full reach and prevent folding back onto the shoulder.
    const atAngle=degrees=>Math.sqrt(upper*upper+lower*lower-2*upper*lower*Math.cos(degrees*Math.PI/180));
    const min=atAngle(35),max=atAngle(165),d=clamp(raw,min,max);
    const ux=raw ? dx/raw : 0, uy=raw ? dy/raw : -1;
    const along=(upper*upper-lower*lower+d*d)/(2*d);
    const height=Math.sqrt(Math.max(0,upper*upper-along*along));
    return {shoulder, elbow:{x:shoulder.x+ux*along-uy*height*bend,y:shoulder.y+uy*along+ux*height*bend},
      hoof:{x:shoulder.x+ux*d,y:shoulder.y+uy*d}, reachable:raw>=min&&raw<=max, upper,lower};
  }
  function operation(actor, time, mode, reduced=false) {
    const clock=actor.state==='running' ? time + actor.seed*3.71 : actor.idleClock || 0;
    const cycle=((clock%11)+11)%11;
    const prefersMouse=['扫雷','绘图','打砖块'].includes(mode);
    // Reach, settle, use, return. Continuous weights prevent keyboard/mouse jumps.
    const start=prefersMouse ? .8 : 5.2, end=prefersMouse ? 8.8 : 8.2;
    const intended=smooth((cycle-start)/.85)*(1-smooth((cycle-end)/.8));
    const mouse=Number.isFinite(actor.deviceBlend)?actor.deviceBlend:intended;
    const input=cycle<9.5 && actor.pose==='seated' && expression(actor,time,mode,reduced).sleep<.05;
    const taps=input && !reduced ? Math.max(0,Math.sin(clock*7.8))*.95 : 0;
    const rightTaps=input && !reduced ? Math.max(0,Math.sin(clock*7.8+Math.PI))*.95 : 0;
    return {clock,mouse,input, leftLift:taps, rightLift:rightTaps*(1-mouse),
      mouseX:reduced ? 0 : Math.sin(clock*.9)*1.4*mouse,
      mouseY:reduced ? 0 : Math.cos(clock*.7)*.7*mouse,
      click:input && mouse>.98 && !reduced && Math.sin(clock*4)> .9,
      label:!input?'观察屏幕':mouse>.9?'操作鼠标':mouse>.1?'移动前蹄':'交替输入'};
  }
  function arms(actor, origin, sit, time, mode, reduced=false) {
    const op=operation(actor,time,mode,reduced), amount=smooth(sit);
    const toLocal = p => ({x:(actor.deskX+p.x-origin.x)/scale,y:(actor.deskY+p.y-origin.y)/scale});
    const left=toLocal({...desk.keyboard.left,y:desk.keyboard.left.y-op.leftLift});
    const mouse=toLocal({x:desk.mouse.x+op.mouseX,y:desk.mouse.y+op.mouseY+(op.click ? .35 : 0)});
    const right=point(toLocal({...desk.keyboard.right,y:desk.keyboard.right.y-op.rightLift}),mouse,op.mouse);
    // A small arc lifts the hoof between devices, rather than sweeping through them.
    right.y-=Math.sin(op.mouse*Math.PI)*4;
    const stride=actor.pose==='walking' && !reduced ? Math.sin(actor.phase)*3 : 0;
    const standingLeft={x:-17+stride*.35,y:-20+stride}, standingRight={x:17-stride*.35,y:-20-stride};
    const shoulderY=mix(-50,-55,amount);
    return {left:solve({x:-mix(18,23,amount),y:shoulderY},point(standingLeft,left,amount),-1),
      right:solve({x:mix(18,23,amount),y:shoulderY},point(standingRight,right,amount),1), operation:op,
      contacts:{left, right, mouse}, amount};
  }
  const path = arm => `M${arm.shoulder.x} ${arm.shoulder.y}L${arm.elbow.x.toFixed(3)} ${arm.elbow.y.toFixed(3)}L${arm.hoof.x.toFixed(3)} ${arm.hoof.y.toFixed(3)}`;
  function doorArm(actor,origin,scaleX,arm,open) {
    const action=actor.doorAction;
    if(!action) return arm;
    const contact=PonyDoor.geometry(open).handle(action.side);
    const goal={x:(contact.x-origin.x)/(scale*scaleX),y:(contact.y-origin.y)/scale};
    const target=point(arm.hoof,goal,action.contact);
    target.y-=Math.sin(action.contact*Math.PI)*3;
    return solve(arm.shoulder,target,1,arm.upper,arm.lower);
  }
  function expression(actor,time,mode,reduced=false) {
    const resting=actor.pose==='seated' && actor.state==='idle';
    const cycle=((time+(actor.seed||0)*9.13)%47+47)%47;
    const sleep=!reduced&&resting?(actor.id==='mail'?1:actor.id?0:smooth((cycle-35)/2)*(1-smooth((cycle-43)/2))):0;
    // The source walk keeps both eyes open; sleep has separate white eyelids.
    return {blink:1-sleep,look:0,tilt:0,nod:0,sleep,ear:0,breath:0};
  }
  function legs(actor,sit,reduced=false) {
    const moving=actor.pose==='walking'&&!reduced;
    return Object.fromEntries([['left',-1],['right',1]].map(([name,side])=>{
      const angle=moving?Math.sin(actor.phase+(side<0?0:Math.PI))*38:side*sit*12;
      const hip={x:side*10,y:-34},radians=angle*Math.PI/180;
      return [name,{hip,angle,length:34,hoof:{x:hip.x-Math.sin(radians)*34,y:hip.y+Math.cos(radians)*34}}];
    }));
  }
  function contour(points) {
    if(!points?.length)return '';
    const count=points.length/2,at=i=>{i=(i+count)%count;return{x:points[i*2],y:points[i*2+1]};};
    const pair=p=>`${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
    let d=`M${pair(at(0))}`;
    for(let i=0;i<count;i++){
      const a=at(i-1),b=at(i),c=at(i+1),e=at(i+2);
      d+=`C${pair({x:b.x+(c.x-a.x)*.12,y:b.y+(c.y-a.y)*.12})} ${pair({x:c.x-(e.x-b.x)*.12,y:c.y-(e.y-b.y)*.12})} ${pair(c)}`;
    }
    return d+'Z';
  }
  const compound = shapes => (shapes||[]).map(contour).join('');
  const tween = (a,b,t) => a.length===b.length?a.map((n,i)=>mix(n,b[i],t)):(t<.5?a:b);
  const tweenShapes=(a,b,t)=>a.length===b.length?a.map((p,i)=>tween(p,b[i],t)):(t<.5?a:b);
  const wrap=n=>(n%1+1)%1;
  function sampleWalk(phase) {
    const frames=PonyReference.walk,raw=wrap(phase/(Math.PI*2))*frames.length;
    const p=Math.abs(raw-Math.round(raw))<1e-8?Math.round(raw)%frames.length:raw,i=Math.floor(p),t=p-i;
    const a=frames[i],b=frames[(i+1)%frames.length];
    return {frame:a.frame,fraction:t,origin:tween(a.origin,b.origin,t),pixelScale:a.pixelScale,head:tween(a.head,b.head,t),body:tween(a.body,b.body,t),
      scarf:tween(a.scarf,b.scarf,t),eyes:tweenShapes(a.eyes,b.eyes,t),
      pupils:tweenShapes(a.pupils,b.pupils,t),fringe:tweenShapes(a.fringe,b.fringe,t),bodyIslands:tweenShapes(a.bodyIslands,b.bodyIslands,t),bodyHoles:tweenShapes(a.bodyHoles,b.bodyHoles,t)};
  }
  function seated(actor,time,sleep,reduced=false) {
    const key=sleep>.01?'mail':actor.id==='mail'?'charts':actor.id;
    const frames=PonyReference.seated[key]||PonyReference.seated.main;
    // A head turn changes viewpoint; vertex morphs fold the horn and muzzle.
    // Play complete native poses together, returning along the same source
    // sequence so opposite profiles never collide at the loop boundary.
    const last=frames.length-1,position=reduced?0:wrap(time*PonyReference.seatedFPS/(last*2))*last*2;
    const at=position>last?last*2-position:position;
    const pose=frames[Math.min(last,Math.floor(at+.5+1e-8))];
    return {head:pose.head,collar:pose.collar,lids:pose.lids};
  }
  function solidArm(arm,width=8) {
    const {shoulder:s,elbow:e,hoof:h}=arm;
    const unit=(a,b)=>{const d=Math.hypot(b.x-a.x,b.y-a.y)||1;return{x:(b.x-a.x)/d,y:(b.y-a.y)/d};};
    const u=unit(s,e),v=unit(e,h),n={x:-u.y,y:u.x},m={x:-v.y,y:v.x};
    const sum=Math.hypot(n.x+m.x,n.y+m.y)||1,k={x:(n.x+m.x)/sum,y:(n.y+m.y)/sum};
    const p=(a,b,w)=>`${(a.x+b.x*w).toFixed(3)} ${(a.y+b.y*w).toFixed(3)}`;
    return `M${p(s,n,width*.9)}Q${p(e,k,width*1.15)} ${p(h,m,width)}Q${p(h,v,width*.7)} ${p(h,m,-width)}Q${p(e,k,-width*1.15)} ${p(s,n,-width*.9)}Q${p(s,u,-width*.7)} ${p(s,n,width*.9)}Z`;
  }
  function shade(hex,amount) {
    const rgb=hex.replace('#','').match(/../g).map(n=>parseInt(n,16));
    return '#'+rgb.map(n=>Math.round(clamp(amount>0?mix(n,255,amount):n*(1+amount),0,255)).toString(16).padStart(2,'0')).join('');
  }
  function markup(role,index=0) {
    const key=`pony-${role.id}-${index}`.replace(/[^a-zA-Z0-9-]/g,'');
    const arm=side=>`<g class="pony-arm-${side}"><path class="pony-arm-shape" fill="#000"/><circle class="pony-elbow" r="0" fill="none"/><ellipse class="pony-hoof" rx="6.2" ry="4.7" fill="none" pointer-events="none"/></g>`;
    const leg=side=>`<g class="pony-leg-${side}"><path d="M-10-3Q0-7 10-3L12 25Q13 33 6 34H-8Q-13 32-12 26Z" fill="#000"/></g>`;
    return `<title>${role.name}</title><defs>
      <linearGradient id="${key}-cloth" x1="0" y1="0" x2=".15" y2="1"><stop stop-color="${shade(role.color,.12)}"/><stop offset=".35" stop-color="${role.color}"/><stop offset="1" stop-color="${shade(role.color,-.18)}"/></linearGradient>
      <pattern id="${key}-weave" width=".6" height=".7" patternUnits="userSpaceOnUse"><path d="M0 .12H.6M.16 0V.7" stroke="#fff" stroke-opacity=".08" stroke-width=".1"/><path d="M0 .45H.6M.46 0V.7" stroke="#000" stroke-opacity=".09" stroke-width=".1"/></pattern>
      <filter id="${key}-fabric" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB"><feTurbulence type="fractalNoise" baseFrequency="1.2" numOctaves="3" seed="7" result="grain"/><feColorMatrix in="grain" type="saturate" values="0"/><feComponentTransfer result="fiber"><feFuncR type="linear" slope=".6" intercept=".65"/><feFuncG type="linear" slope=".6" intercept=".65"/><feFuncB type="linear" slope=".6" intercept=".65"/><feFuncA type="table" tableValues="1 1"/></feComponentTransfer><feBlend in="SourceGraphic" in2="fiber" mode="multiply"/><feComposite in2="SourceGraphic" operator="in"/></filter>
      <mask id="${key}-cloth-mask" maskUnits="userSpaceOnUse" x="-90" y="-160" width="180" height="180"><path class="pony-cloth-mask" fill="#fff" stroke="#fff" stroke-width=".5"/><path class="pony-fringe-cuts" fill="#000"/></mask>
      <mask id="${key}-neck-mask" maskUnits="userSpaceOnUse" x="-90" y="-160" width="180" height="180"><rect x="-20" y="-82" width="40" height="34" fill="#fff"/><path class="pony-neck-anatomy" fill="#fff" stroke="#fff" stroke-width="3.2" stroke-linejoin="round"/></mask>
      <clipPath id="${key}-eye-clip"><path class="pony-eye-clip"/></clipPath>
      <filter id="${key}-soft-shadow" x="-50%" y="-150%" width="200%" height="400%"><feGaussianBlur stdDeviation="3"/></filter>
      </defs><ellipse class="pony-ground" cy="2" rx="32" ry="5" fill="#343434" opacity=".15" filter="url(#${key}-soft-shadow)"/>
      <g class="pony-rig">
        <path class="pony-neck-backing" fill="#000" stroke="#000" stroke-width="3.2" stroke-linejoin="round" mask="url(#${key}-neck-mask)"/>
        <g class="pony-rest-body"><g class="pony-rest-legs">${leg('left')}${leg('right')}</g><path class="pony-torso" d="M-22-67Q0-72 22-65L28-36Q26-22 0-22Q-26-22-28-36Z" fill="#000"/></g>
        <path class="pony-reference-body" fill="#000" fill-rule="evenodd"/>
        <g class="pony-arms">${arm('left')}${arm('right')}</g>
        <g class="pony-head"><path class="pony-head-shape" fill="#000"/><path class="pony-eyes" fill="#fff"/><path class="pony-pupil" fill="#000" clip-path="url(#${key}-eye-clip)"/></g>
        <g class="pony-front-head" opacity="0" transform="scale(.9 1)"><path class="pony-front-profile" fill="#000"/><g class="pony-front-eyes"><path class="pony-front-white" fill="#fff"/><path class="pony-front-pupil" fill="#000" clip-path="url(#${key}-eye-clip)"/></g></g>
        <g class="pony-seated-head" opacity="0"><path class="pony-seated-profile" fill="#000"/><path class="pony-sleep-lids" fill="#fff"/></g>
        <path class="pony-fringe-backing" fill="#050505" stroke="#050505" stroke-width=".2"/>
        <g class="pony-collar" filter="url(#${key}-fabric)" mask="url(#${key}-cloth-mask)"><path class="pony-cloth-shape" fill="url(#${key}-cloth)" stroke="${role.color}" stroke-width=".5" stroke-linejoin="round"/><path class="pony-cloth-weave" fill="url(#${key}-weave)"/></g>
        <g class="pony-sleep-symbols" opacity="0" fill="#515151" font-family="sans-serif"><text x="32" y="-106" font-size="7">z</text><text x="40" y="-111" font-size="9">Z</text><text x="50" y="-117" font-size="11">Z</text></g>
      </g>`;
  }
  function bind(pony) {
    const names=['rig','ground','head','head-shape','eyes','pupil','eye-clip','front-head','front-eyes','front-profile','front-white','front-pupil','seated-head','seated-profile','sleep-lids','sleep-symbols','collar','cloth-shape','cloth-weave','cloth-mask','fringe-cuts','fringe-backing','neck-backing','neck-anatomy','rest-body','rest-legs','reference-body','torso','leg-left','leg-right','arms'];
    const rig=Object.fromEntries(names.map(name=>[name,pony.querySelector('.pony-'+name)]));
    rig.armsLayer=rig.arms;
    rig.arms=Object.fromEntries(['left','right'].map(side=>[side,{
      node:pony.querySelector('.pony-arm-'+side),line:pony.querySelector('.pony-arm-'+side+' path'),
      elbow:pony.querySelector('.pony-arm-'+side+' circle'),hoof:pony.querySelector('.pony-arm-'+side+' ellipse')
    }]));
    return rig;
  }
  const attr=(node,name,value)=>node.setAttribute(name,String(value));
  function paintPose(rig,pose) {
    // Reconstruct the neck hidden by the scarf. Constrain overlap to nearby
    // anatomy so cloth edges against open background retain their silhouette.
    attr(rig['neck-backing'],'d',contour(pose.scarf));
    attr(rig['neck-anatomy'],'d',contour(pose.head)+contour(pose.body)+compound(pose.bodyIslands));
    attr(rig['reference-body'],'d',contour(pose.body)+compound(pose.bodyIslands)+compound(pose.bodyHoles));
    attr(rig['head-shape'],'d',contour(pose.head));
    const eyes=compound(pose.eyes);attr(rig.eyes,'d',eyes);attr(rig['eye-clip'],'d',eyes);
    attr(rig.pupil,'d',compound(pose.pupils));
    // Unseen approach directions retain the source three-quarter face and eyes.
    attr(rig['front-profile'],'d',contour(pose.head));attr(rig['front-white'],'d',eyes);attr(rig['front-pupil'],'d',compound(pose.pupils));
    attr(rig['cloth-shape'],'d',contour(pose.scarf));attr(rig['cloth-weave'],'d',contour(pose.scarf));
    attr(rig['cloth-mask'],'d',contour(pose.scarf));attr(rig['fringe-cuts'],'d',compound(pose.fringe));
    attr(rig['fringe-backing'],'d',compound(pose.fringe));
  }
  function paintReference(pony,pose=PonyReference.still) {
    const rig=bind(pony);paintPose(rig,pose);
    attr(rig['rest-body'],'display','none');attr(rig.armsLayer,'display','none');
    attr(rig['reference-body'],'display','inline');
    return rig;
  }
  function render(rig,actor,time,sit,origin,scaleX,mode,reduced=false) {
    const moving=actor.pose==='walking'&&!reduced,action=actor.doorAction;
    const face=expression(actor,time,mode,reduced),sample=moving?sampleWalk(actor.phase):PonyReference.still;
    paintPose(rig,sample);
    attr(rig['reference-body'],'display',moving?'inline':'none');
    attr(rig['rest-body'],'display',moving?'none':'inline');
    attr(rig.armsLayer,'display',moving?'none':'inline');
    const rear=moving&&actor.facing==='back',front=!rear&&moving&&actor.facing==='front';
    attr(rig.head,'opacity',(1-sit)*(rear||front?0:1));
    attr(rig['front-head'],'opacity',front?1:0);
    attr(rig['seated-head'],'opacity',rear?1:sit);
    attr(rig['front-eyes'],'opacity',1-face.sleep);
    const head=seated(actor,time,face.sleep,reduced);
    if(!moving)attr(rig['neck-anatomy'],'d',contour(sample.head)+rig.torso.getAttribute('d'));
    attr(rig['seated-profile'],'d',contour(head.head));
    attr(rig['sleep-lids'],'d',face.sleep>0?compound(head.lids):'');
    attr(rig['sleep-lids'],'opacity',face.sleep);
    attr(rig['sleep-symbols'],'opacity',face.sleep);
    attr(rig.armsLayer,'opacity',1-face.sleep);
    if(sit>0||rear) {
      attr(rig['cloth-shape'],'d',contour(head.collar));attr(rig['cloth-weave'],'d',contour(head.collar));
      attr(rig['cloth-mask'],'d',contour(head.collar));attr(rig['fringe-cuts'],'d','');
      attr(rig['fringe-backing'],'d','');
      attr(rig['neck-backing'],'d',contour(head.collar));
      attr(rig['neck-anatomy'],'d',contour(head.head)+(moving?contour(sample.body)+compound(sample.bodyIslands):rig.torso.getAttribute('d')));
    }
    const tilt=action?action.look*4:0;
    attr(rig.head,'transform',`rotate(${tilt} 0 -65)`);
    const legPose=legs(actor,sit,reduced),lean=action?actor.heading*action.lean:0;
    // A sitting turn can pass through scaleX=0. With no door lean there is
    // no world-space offset to undo; avoid the undefined 0/0 at that instant.
    const legOffset=lean?lean/(scale*scaleX):0;
    for(const side of ['left','right']) {
      const leg=legPose[side];
      attr(rig['leg-'+side],'transform',`translate(${leg.hip.x-legOffset} ${leg.hip.y-sit*5}) rotate(${leg.angle})`);
    }
    attr(rig['rest-legs'],'opacity',1-sit);
    // Solid swept contours conceal the fixed-length contact skeleton.
    const joints=arms(actor,origin,sit,time,mode,reduced);
    for(const side of ['left','right']) {
      let arm=joints[side];
      if(action&&side==='right') arm=doorArm(actor,origin,scaleX,arm,action.open);
      const nodes=rig.arms[side];
      attr(nodes.line,'d',solidArm(arm));
      attr(nodes.elbow,'cx',arm.elbow.x);attr(nodes.elbow,'cy',arm.elbow.y);
      attr(nodes.hoof,'cx',arm.hoof.x);attr(nodes.hoof,'cy',arm.hoof.y);
      joints[side]=arm;
    }
    const anchor=sit>.1||action?rig.head:rig.torso.parentNode;
    if(rig.armsLayer.nextSibling!==anchor) rig.rig.insertBefore(rig.armsLayer,anchor);
    return {face,joints,moving,sourceFrame:moving?sample.frame:null};
  }
  return {scale,desk,solve,arms,operation,path,smooth,expression,legs,doorArm,markup,
    contour,compound,sampleWalk,seated,solidArm,bind,paintPose,paintReference,render};
})();
