/* gstack browse eval on prototype/character-check.html. Rasterize every native
 * seated pose through the actual renderer and compare it with its source head. */
(async()=>{
  const assert=(ok,label)=>{if(!ok)throw Error(label);};
  assert(location.pathname.endsWith('/prototype/character-check.html'),'Use the source comparison page');
  window.__seatedVerification={state:'running',frames:0};
  const NS='http://www.w3.org/2000/svg',specifications=[
    ['prediction',[132,48,268,140],[204,232]],['main',[608,48,746,140],[669,232]],
    ['risk',[1048,48,1193,140],[1132,232]],['mail',[108,410,258,524],[194,589]],
    ['advice',[608,394,752,480],[669,574]],['charts',[1045,394,1195,480],[1132,574]]
  ];
  const turning=document.createElementNS(NS,'g');turning.innerHTML=PonyRig.markup({id:'main',name:'turning',color:'#ed2f31'},'zero-width');
  PonyRig.render(PonyRig.bind(turning),{id:'main',seed:0,pose:'sitting',state:'idle',phase:0,heading:-1,deskX:0,deskY:-61.6},0,.5,{x:0,y:0},0,'idle');
  assert([...turning.querySelectorAll('[transform]')].every(node=>! /NaN|Infinity/.test(node.getAttribute('transform'))),'turning at zero horizontal scale must retain finite leg transforms');
  const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d',{willReadFrequently:true}),rows=[];
  const largestInk=(rgba,width,height)=>{
    const visited=new Uint8Array(width*height),queue=new Int32Array(width*height);
    const ink=i=>Math.max(rgba[i*4],rgba[i*4+1],rgba[i*4+2])<25;
    let best=[];
    for(let p=0;p<visited.length;p++){
      if(visited[p]||!ink(p))continue;
      let read=0,end=1;queue[0]=p;visited[p]=1;
      while(read<end){
        const at=queue[read++],x=at%width;
        for(const next of [x?at-1:-1,x<width-1?at+1:-1,at-width,at+width]){
          if(next<0||next>=visited.length||visited[next]||!ink(next))continue;
          visited[next]=1;queue[end++]=next;
        }
      }
      if(end>best.length)best=Array.from(queue.subarray(0,end));
    }
    const mask=new Uint8Array(width*height);for(const p of best)mask[p]=1;return mask;
  };
  const probes=specifications.map(([id,box,origin],index)=>{
    const svg=document.createElementNS(NS,'svg');svg.setAttribute('xmlns',NS);
    const pony=document.createElementNS(NS,'g');pony.innerHTML=PonyRig.markup({id,name:id,color:'#ed2f31'},`seated-probe-${index}`);svg.append(pony);
    return {id,box,origin,pony,rig:PonyRig.bind(pony)};
  });
  for(let frame=0;frame<168;frame++){
    const source=new Image();source.src=`../.tmp/character-reference-review/video-a/frame-${String(frame+1).padStart(4,'0')}.png`;await source.decode();
    for(const {id,box:[x0,y0,x1,y1],origin,pony,rig}of probes){
      const width=x1-x0,height=y1-y0;canvas.width=width;canvas.height=height;
      ctx.drawImage(source,-x0,-y0);const expected=largestInk(ctx.getImageData(0,0,width,height).data,width,height);
      const actor={id,seed:0,pose:'seated',state:'idle',phase:0,heading:1,deskX:0,deskY:-61.6};
      PonyRig.render(rig,actor,frame/30,1,{x:0,y:0},1,'idle');
      const svg=document.createElementNS(NS,'svg');svg.setAttribute('xmlns',NS);svg.setAttribute('width',width);svg.setAttribute('height',height);
      svg.setAttribute('viewBox',`${(x0-origin[0])*.72} ${(y0-origin[1])*.72} ${width*.72} ${height*.72}`);
      svg.append(pony.querySelector('.pony-seated-head').cloneNode(true));
      const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));await image.decode();
      ctx.fillStyle='white';ctx.fillRect(0,0,width,height);ctx.drawImage(image,0,0);
      const actual=ctx.getImageData(0,0,width,height).data;let intersection=0,union=0;
      for(let p=0;p<expected.length;p++){
        const black=Math.max(actual[p*4],actual[p*4+1],actual[p*4+2])<25;
        if(black&&expected[p])intersection++;if(black||expected[p])union++;
      }
      rows.push({id,frame,iou:intersection/union});
    }
    window.__seatedVerification.frames=frame+1;
  }
  const worst=rows.reduce((a,b)=>a.iou<b.iou?a:b),mean=rows.reduce((sum,row)=>sum+row.iou,0)/rows.length;
  window.__seatedVerification={state:worst.iou>.94?'done':'failed',samples:rows.length,min:worst,mean,roles:specifications.map(([id])=>({id,min:Math.min(...rows.filter(r=>r.id===id).map(r=>r.iou))})),note:'All 168 native frames × six roles. Source black component excludes background monitors and disconnected arms.'};
})().catch(error=>{window.__seatedVerification={state:'failed',error:error.message};});
