/* World-space desk contacts and fixed-length two-link forelegs. No DOM or tasks. */
globalThis.PonyRig = (() => {
  const scale = .88;
  const desk = Object.freeze({keyboard: {left:{x:-29,y:-2},right:{x:12,y:-2}}, mouse:{x:48,y:-2}, seatY:70});
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
    return {left:solve({x:-18,y:shoulderY},point(standingLeft,left,amount),-1),
      right:solve({x:18,y:shoulderY},point(standingRight,right,amount),1), operation:op,
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
    if(reduced) return {blink:1,look:0,tilt:0,nod:0,sleep:0,ear:0,breath:0};
    const clock=time+actor.seed*9.13, cycle=clock%47;
    const resting=actor.pose==='seated' && actor.state==='idle';
    const sleep=resting?smooth((cycle-35)/2)*(1-smooth((cycle-43)/2)):0;
    const blinkPhase=(clock%(4.8+actor.seed*.19));
    const blink=1-Math.sin(clamp(blinkPhase/.18,0,1)*Math.PI)*.94;
    const look=resting?Math.sin(clock*.39)*smooth(Math.sin(clock*.23)*.5+.5):.12;
    return {blink:Math.max(.06,blink*(1-sleep)),look, sleep,
      tilt:Math.sin(clock*.43)*(mode==='task'?.6:1.8),
      nod:sleep*(4+Math.sin(clock*1.3)*2),
      ear:Math.sin(clock*.71)*2.5+Math.max(0,Math.sin(clock*.17))**12*7,
      breath:Math.sin(clock*1.8)*.45};
  }
  function legs(actor,sit,reduced=false) {
    const moving=actor.pose==='walking'&&!reduced;
    const leg=(side,offset)=>{
      const cycle=((actor.phase/(2*Math.PI)+offset)%1+1)%1;
      const stance=cycle<.62;
      const swing=smooth((cycle-.62)/.38);
      const step=moving?(stance?1-cycle/.62*2:-1+swing*2):0;
      const lift=moving&&!stance?Math.sin(swing*Math.PI)*4:0;
      const angle=step*13*(1-sit)-side*sit*12;
      const hip={x:side*8,y:-29-lift-sit*10},radians=angle*Math.PI/180;
      return {hip,angle,length:29,hoof:{x:hip.x-Math.sin(radians)*29,y:hip.y+Math.cos(radians)*29}};
    };
    return {left:leg(-1,0),right:leg(1,.5)};
  }
  function markup(role,index) {
    const mane='#101113', coat='#191a1d';
    const tuft=['M-28-96Q-31-112-17-114Q-13-127 1-123Q-9-113 1-109Q11-104 16-114Q22-100 7-95Z',
      'M-29-97Q-29-111-16-114Q-10-126 4-120Q-6-111 3-106Q14-106 17-113Q22-98 6-95Z',
      'M-28-96Q-30-111-18-113Q-15-122-3-124Q-9-110 2-108Q12-105 16-116Q25-100 7-95Z'][index%3];
    const arm=side=>`<g class="pony-arm-${side}"><path class="pony-arm-line" d="M0 0" fill="none" stroke="${coat}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/><circle class="pony-elbow" r="4.5" fill="${coat}"/><ellipse class="pony-hoof" rx="6.2" ry="4.7" fill="#151619"/></g>`;
    const leg=side=>`<g class="pony-leg-${side}"><path class="pony-leg-shape" d="M-6-2Q0-5 6-2L7 21Q8 25 5 28Q0 30-6 28Q-9 26-7 21Z" fill="${coat}"/></g>`;
    return `<title>${role.name}</title><ellipse class="pony-ground" cy="1" rx="28" ry="6" fill="#101820" opacity=".13"/>
      <g class="pony-rig">
      <path class="pony-tail" d="M-20-34Q-29-30-25-16Q-18-22-18-31Z" fill="${mane}"/>
      ${leg('left')}${leg('right')}
      <g class="pony-arms">${arm('left')}${arm('right')}</g>
      <g class="pony-torso"><path d="M-24-57Q0-70 25-56L28-31Q26-17 2-16Q-24-16-28-30Z" fill="${coat}"/>
      <path d="M-19-48Q-25-35-18-28" fill="none" stroke="#424349" stroke-width="1.4" opacity=".45"/></g>
      <g class="pony-head">
      <g class="pony-ear"><path d="M-22-101L-25-121Q-11-122-9-106Z" fill="${coat}"/><path d="M-21-109L-22-116L-15-110Z" fill="#514448"/></g>
      <path d="M13-105L20-122Q32-118 26-100Z" fill="${coat}"/>
      <path d="M-29-73Q-37-99-18-110Q7-124 27-102L39-89L35-70Q19-58-6-62Q-23-63-29-73Z" fill="${coat}"/>
      <path class="pony-mane" d="${tuft}" fill="${mane}"/>
      <path class="pony-muzzle" d="M14-83Q31-90 39-80L35-70Q21-62 12-71Z" fill="#202125"/>
      <g class="pony-eyes"><ellipse cx="2" cy="-94" rx="8" ry="10.5" fill="#fffdf7"/><ellipse cx="23" cy="-90" rx="7" ry="9.5" fill="#fffdf7"/><ellipse class="pony-pupil" cx="4" cy="-93" rx="3.7" ry="6" fill="#101114"/><ellipse class="pony-pupil" cx="25" cy="-89" rx="3.2" ry="5.5" fill="#101114"/></g>
      <ellipse cx="34" cy="-78" rx="1.4" ry="1.6" fill="#0b0c0e"/><path class="pony-expression" d="M20-69Q24-66 28-69" stroke="#626169" stroke-width="1" stroke-linecap="round" fill="none"/>
      </g>
      <g class="pony-front-head" opacity="0">
      <path d="M-23-104L-26-121Q-12-126-9-106M12-106L23-122Q31-121 27-102" fill="${coat}"/>
      <path d="M-30-80Q-36-108-13-115Q14-124 29-104Q36-86 27-73Q0-53-25-72Z" fill="${coat}"/>
      <path d="${tuft}" fill="${mane}"/>
      <g class="pony-front-eyes"><ellipse cx="-12" cy="-94" rx="8" ry="11" fill="#fffdf7"/><ellipse cx="12" cy="-94" rx="8" ry="11" fill="#fffdf7"/><ellipse class="pony-pupil" cx="-11" cy="-93" rx="3.8" ry="6" fill="#101114"/><ellipse class="pony-pupil" cx="11" cy="-93" rx="3.8" ry="6" fill="#101114"/></g>
      <path d="M-18-79Q0-86 19-79L18-70Q0-61-18-70Z" fill="#202125"/>
      <ellipse cx="-10" cy="-74" rx="1.3" ry="1.7" fill="#0c0d0f"/><ellipse cx="10" cy="-74" rx="1.3" ry="1.7" fill="#0c0d0f"/>
      </g>
      <g class="pony-seated-head" opacity="0">
      <path class="pony-back-ear" d="M-20-104L-24-122Q-10-124-7-107M12-107L20-123Q32-121 26-102" fill="${coat}"/>
      <path d="M-28-76Q-37-102-16-112Q9-125 28-103L32-80Q27-59 2-61Q-19-60-28-76Z" fill="${coat}"/>
      <path d="${tuft}M-14-103Q-5-112 5-105L13-91L6-95L12-80L4-82L8-64L-5-62L-12-80L-20-77L-16-92L-25-89Z" fill="${mane}"/>
      <path d="M25-89Q38-91 38-78L29-71Z" fill="#202125"/>
      <g class="pony-back-eye"><ellipse cx="27" cy="-94" rx="4.2" ry="7" fill="#fffdf7"/><ellipse cx="28" cy="-94" rx="1.9" ry="4" fill="#101114"/></g>
      </g>
      <g class="pony-collar"><path d="M-28-65Q0-57 29-65L30-54Q0-45-29-54Z" fill="${role.color}"/><path d="M-24-62Q0-56 26-62" stroke="#fff" stroke-opacity=".18" stroke-width="1.6" fill="none"/></g>
      <g class="pony-scarf"><path d="M-18-55L-22-30L-10-27L-7-53Z" fill="${role.color}"/><path d="M-19-32L-20-26M-16-31L-17-25M-12-30L-13-24" stroke="${role.color}" stroke-width="2"/><path d="M-14-51L-17-33" stroke="#fff" stroke-opacity=".15" fill="none"/></g>
      </g>`;
  }
  return {scale,desk,solve,arms,operation,path,smooth,expression,legs,doorArm,markup};
})();
