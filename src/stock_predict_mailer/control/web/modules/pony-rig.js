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
  return {scale,desk,solve,arms,operation,path,smooth};
})();
