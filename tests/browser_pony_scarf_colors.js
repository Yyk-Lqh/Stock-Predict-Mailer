/* Run through gstack on the disposable office. Samples opaque scarf interiors. */
(async()=>{
  window.__scarfColors={state:'running'};
  const NS='http://www.w3.org/2000/svg',canvas=document.createElement('canvas');canvas.width=280;canvas.height=300;
  const ctx=canvas.getContext('2d',{willReadFrequently:true}),rows=[];
  const hue=rgb=>{const [r,g,b]=rgb.map(v=>v/255),max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;let h=d?(max===r?(g-b)/d:max===g?(b-r)/d+2:(r-g)/d+4)/6:0;return{h:(h+1)%1,s:max?d/max:0};};
  const raster=async svg=>{const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));await image.decode();ctx.clearRect(0,0,280,300);ctx.drawImage(image,0,0);return ctx.getImageData(0,0,280,300).data;};
  for(const role of PonyFloor.roles)for(const mirror of [1,-1])for(const phase of [...Array.from({length:18},(_,i)=>i), 'seated','sitting','rising','door','idle']){
    const svg=document.createElementNS(NS,'svg');svg.setAttribute('xmlns',NS);svg.setAttribute('width',280);svg.setAttribute('height',300);svg.setAttribute('viewBox','-70 -150 140 150');
    const pony=document.createElementNS(NS,'g');pony.setAttribute('transform',`scale(${mirror} 1)`);pony.innerHTML=PonyRig.markup(role,'hue');svg.append(pony);
    const walk=typeof phase==='number',sit=phase==='seated'?1:['sitting','rising'].includes(phase)?.5:0;
    const actor={...role,deskX:0,deskY:-61.6,seed:0,state:'running',pose:walk?'walking':phase,phase:walk?phase/18*Math.PI*2:0,heading:mirror,facing:walk&&phase%3===0?'back':'side'};
    if(phase==='door')actor.doorAction={...PonyDoor.sample(.9,false,0),side:'inside'};
    PonyRig.render(PonyRig.bind(pony),actor,1.4,sit,{x:0,y:0},mirror,'task');
    const actual=await raster(svg),mask=svg.cloneNode(true),g=mask.querySelector('g');
    for(const child of [...g.children])if(child.tagName.toLowerCase()!=='defs'&&!child.classList.contains('pony-rig'))child.remove();
    const rig=g.querySelector('.pony-rig');for(const child of [...rig.children])if(!child.classList.contains('pony-collar'))child.remove();
    for(const path of rig.querySelectorAll('.pony-collar path')){path.setAttribute('fill','#fff');path.setAttribute('stroke','#fff');}
    const expected=await raster(mask);
    // Parse hex without including the leading '#'.
    const wanted=hue(role.color.slice(1).match(/../g).map(v=>parseInt(v,16)));let samples=0,bad=0,maxHue=0;
    for(let y=1;y<299;y++)for(let x=1;x<279;x++){
      let inside=true;for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++)if(expected[((y+dy)*280+x+dx)*4+3]<250)inside=false;
      if(!inside)continue;const at=(y*280+x)*4,v=hue([actual[at],actual[at+1],actual[at+2]]),diff=Math.min(Math.abs(v.h-wanted.h),1-Math.abs(v.h-wanted.h));
      samples++;maxHue=Math.max(maxHue,diff);if(v.s<.25||diff>.015||actual[at+3]<240)bad++;
    }
    rows.push({id:role.id,mirror,phase,samples,bad,maxHue});
  }
  const failures=rows.filter(r=>!r.samples||r.bad);
  window.__scarfColors={state:failures.length?'failed':'done',poses:rows.length,samples:rows.reduce((n,r)=>n+r.samples,0),maxHue:Math.max(...rows.map(r=>r.maxHue)),failures:failures.slice(0,12)};
})().catch(error=>{window.__scarfColors={state:'failed',error:error.stack};});
