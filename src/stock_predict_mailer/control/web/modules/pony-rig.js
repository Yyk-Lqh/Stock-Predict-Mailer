/* World-space desk contacts and fixed-length two-link forelegs. No DOM or tasks. */
globalThis.PonyRig = (() => {
  const scale = .88;
  const desk = Object.freeze({keyboard: {left:{x:-29,y:-2},right:{x:12,y:-2}}, mouse:{x:48,y:-2}, seatY:70});
  const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  const smooth = x => { x=clamp(x,0,1); return x*x*(3-2*x); };
  const mix = (a,b,t) => a+(b-a)*t;
  const point = (a,b,t) => ({x:mix(a.x,b.x,t),y:mix(a.y,b.y,t)});
  function solve(shoulder, target, bend = 1, upper = 26, lower = 25) {
    const dx=target.x-shoulder.x, dy=target.y-shoulder.y, raw=Math.hypot(dx,dy);
    const d=clamp(raw,Math.abs(upper-lower)+.001,upper+lower-.001);
    const ux=raw ? dx/raw : 0, uy=raw ? dy/raw : -1;
    const along=(upper*upper-lower*lower+d*d)/(2*d);
    const height=Math.sqrt(Math.max(0,upper*upper-along*along));
    return {shoulder, elbow:{x:shoulder.x+ux*along-uy*height*bend,y:shoulder.y+uy*along+ux*height*bend},
      hoof:{x:shoulder.x+ux*d,y:shoulder.y+uy*d}, reachable:raw<=upper+lower, upper,lower};
  }
  function operation(actor, time, mode, reduced=false) {
    const clock=actor.state==='running' ? time + actor.seed*3.71 : actor.idleClock || 0;
    const cycle=((clock%11)+11)%11;
    const prefersMouse=['扫雷','绘图','打砖块'].includes(mode);
    // Reach, settle, use, return. Continuous weights prevent keyboard/mouse jumps.
    const start=prefersMouse ? .8 : 5.2, end=prefersMouse ? 8.8 : 8.2;
    const intended=smooth((cycle-start)/.85)*(1-smooth((cycle-end)/.8));
    const mouse=Number.isFinite(actor.deviceBlend)?actor.deviceBlend:intended;
    const input=cycle<9.5 && actor.pose==='seated';
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
    const stride=actor.pose==='walking' ? Math.sin(actor.phase)*11 : 0;
    const standingLeft={x:-25+stride*.5,y:-22+stride*.35}, standingRight={x:25-stride*.5,y:-22-stride*.35};
    return {left:solve({x:-20,y:-54},point(standingLeft,left,amount),-1),
      right:solve({x:20,y:-54},point(standingRight,right,amount),1), operation:op,
      contacts:{left, right, mouse}, amount};
  }
  const path = arm => `M${arm.shoulder.x} ${arm.shoulder.y}L${arm.elbow.x.toFixed(3)} ${arm.elbow.y.toFixed(3)}L${arm.hoof.x.toFixed(3)} ${arm.hoof.y.toFixed(3)}`;
  function markup(role,index) {
    const mane=['#615469','#466a58','#655280','#496782','#427c7a','#857347','#825a43'][index];
    const coat=['#222831','#252e2a','#292631','#232c37','#233132','#302d25','#302824'][index];
    const tuft=['M-24-91Q-9-116 10-103L2-93L-9-99L-16-84Z','M-24-91Q-19-112-4-106L8-105L1-94L-13-89Z','M-25-90L-20-108L-10-102L1-113L10-100L-7-94Z'][index%3];
    const arm=side=>`<g class="pony-arm-${side}"><path class="pony-arm-line" d="M0 0" fill="none" stroke="${coat}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/><circle class="pony-elbow" r="4.5" fill="${coat}"/><ellipse class="pony-hoof" rx="6" ry="4" fill="#48515c" stroke="#727d88" stroke-width=".6"/></g>`;
    return `<title>${role.name}</title><ellipse class="pony-ground" cy="1" rx="28" ry="6" fill="#101820" opacity=".13"/>
      <g class="pony-rig">
      <path class="pony-tail" d="M-20-33Q-46-48-38-23Q-32-16-25-26Q-38-28-30-35" fill="${mane}"/>
      <g class="pony-leg-left"><path d="M-12-28Q-19-17-14-6L-23-3L-22 2H-7L-2-25" fill="${coat}"/><path d="M-22-3H-7V2H-22Z" fill="#46515c"/></g>
      <g class="pony-leg-right"><path d="M5-28Q17-19 15-6L23-3V2H7L1-25" fill="${coat}"/><path d="M7-3H23V2H7Z" fill="#46515c"/></g>
      <path d="M-20-56Q0-67 22-54L24-27Q1-12-23-27Z" fill="${coat}"/>
      <path d="M-15-48Q-4-56 10-50" fill="none" stroke="#626b77" stroke-width="1" opacity=".4"/>
      ${arm('left')}${arm('right')}
      <g class="pony-head">
      <path class="pony-ear" d="M-14-98L-20-119Q-5-117-3-101Z" fill="${coat}"/><path d="M-14-106L-16-115L-8-108Z" fill="#8a7378"/>
      <path d="M8-101L11-116Q23-111 19-95Z" fill="${coat}"/>
      <path d="M-23-69Q-29-92-13-103Q8-115 23-94L33-84L29-67L12-61Q-7-58-23-69Z" fill="${coat}"/>
      <path class="pony-mane" d="${tuft}" fill="${mane}"/>
      <path class="pony-muzzle" d="M14-79Q27-87 34-77L31-67Q16-62 12-70Z" fill="#515963"/>
      <g class="pony-eyes"><ellipse cx="7" cy="-87" rx="6" ry="8" fill="#f4f3ee"/><ellipse cx="23" cy="-84" rx="4.8" ry="7" fill="#f4f3ee"/><ellipse class="pony-pupil" cx="9" cy="-87" rx="2.5" ry="4.5" fill="#17222c"/><ellipse class="pony-pupil" cx="24" cy="-84" rx="2" ry="4" fill="#17222c"/></g>
      <ellipse cx="30" cy="-75" rx="1.2" ry="1.8" fill="#242c35"/><path class="pony-expression" d="M20-69Q24-66 28-69" stroke="#aeb3ba" stroke-width="1" fill="none"/>
      </g>
      <g class="pony-seated-head" opacity="0">
      <path class="pony-back-ear" d="M-15-97L-20-115Q-9-117-5-101M9-101L16-116Q25-113 21-96" fill="${coat}"/>
      <path d="M-23-73Q-29-96-11-104Q9-113 23-96L26-76Q22-59 1-61Q-14-61-23-73Z" fill="${coat}"/>
      <path d="M-15-99Q-4-111 8-103L13-93L5-96L10-82L2-83L5-65L-7-63L-12-80L-18-77L-15-91L-22-89Z" fill="${mane}"/>
      <path d="M20-85Q31-87 30-75L23-71Z" fill="#515963"/>
      <g class="pony-back-eye"><ellipse cx="21" cy="-89" rx="3.2" ry="5.5" fill="#f4f3ee"/><ellipse cx="21.5" cy="-90.5" rx="1.4" ry="2.8" fill="#17222c"/></g>
      </g>
      <path d="M-23-64Q0-55 23-64L24-56Q0-46-24-56Z" fill="${role.color}"/>
      <path class="pony-scarf" d="M-14-54L-16-34L-5-36L-4-53Z" fill="${role.color}"/>
      </g>`;
  }
  return {scale,desk,solve,arms,operation,path,smooth,markup};
})();
