/* gstack browse eval on prototype/character-check.html. Checks source-solid
 * scarf boundaries at 4x resolution; excludes the outer silhouette by erosion. */
(async()=>{
  const NS='http://www.w3.org/2000/svg',rows=[];
  window.__scarfSeams={state:'running'};
  for(const index of [-1,...Array.from({length:36},(_,i)=>i/2)]){
    const pose=index<0?PonyReference.still:PonyRig.sampleWalk(index/18*Math.PI*2),scale=pose.pixelScale;
    const sourcePose=index<0?PonyReference.still:PonyReference.walk[Math.floor(index)];
    const xs=pose.scarf.filter((_,i)=>i%2===0),ys=pose.scarf.filter((_,i)=>i%2);
    const x=Math.floor(sourcePose.origin[0]+Math.min(...xs)/scale)-5,y=Math.floor(sourcePose.origin[1]+Math.min(...ys)/scale)-5;
    const width=Math.ceil((Math.max(...xs)-Math.min(...xs))/scale)+11,height=Math.ceil((Math.max(...ys)-Math.min(...ys))/scale)+11;
    const source=new Image();source.src=index<0?'../docs/superpowers/specs/assets/2026-11-12-character-reference/reference-still.png':`../.tmp/character-reference-review/video-b/frame-${String(pose.frame+1).padStart(4,'0')}.png`;await source.decode();
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d',{willReadFrequently:true});
    ctx.drawImage(source,-x,-y);const reference=ctx.getImageData(0,0,width,height).data,cloth=[],solid=[];
    for(let p=0;p<width*height;p++){const k=p*4,r=reference[k],g=reference[k+1],b=reference[k+2];cloth[p]=r>80&&r>g*1.8&&r>b*1.8;solid[p]=Math.max(r,g,b)<80||cloth[p];}
    if(index%1>0){
      // At a half-frame, only require anatomy that is opaque in BOTH adjacent
      // source poses, with camera translation removed. Exterior motion differs.
      const next=PonyReference.walk[(Math.floor(index)+1)%18],second=new Image();
      second.src=`../.tmp/character-reference-review/video-b/frame-${String(next.frame+1).padStart(4,'0')}.png`;await second.decode();
      ctx.fillStyle='white';ctx.fillRect(0,0,width,height);ctx.drawImage(second,sourcePose.origin[0]-next.origin[0]-x,sourcePose.origin[1]-next.origin[1]-y);
      const b=ctx.getImageData(0,0,width,height).data;
      for(let p=0;p<width*height;p++){const k=p*4,red=b[k]>80&&b[k]>b[k+1]*1.8&&b[k]>b[k+2]*1.8;solid[p]=solid[p]&&(Math.max(b[k],b[k+1],b[k+2])<80||red);cloth[p]=cloth[p]||red;}
    }
    const svg=document.createElementNS(NS,'svg');svg.setAttribute('xmlns',NS);svg.setAttribute('viewBox',`${(x-sourcePose.origin[0])*scale} ${(y-sourcePose.origin[1])*scale} ${width*scale} ${height*scale}`);svg.setAttribute('width',width*4);svg.setAttribute('height',height*4);
    const pony=document.createElementNS(NS,'g');pony.innerHTML=PonyRig.markup({id:'seam-probe',name:'seam',color:'#ed2f31'},index+1);svg.append(pony);PonyRig.paintReference(pony,pose);pony.querySelector('.pony-ground').remove();
    const picture=new Image();picture.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));await picture.decode();
    canvas.width=width*4;canvas.height=height*4;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(picture,0,0);const actual=ctx.getImageData(0,0,canvas.width,canvas.height).data;
    let samples=0,gaps=0;const points=[];
    for(let yy=2;yy<height-2;yy++)for(let xx=2;xx<width-2;xx++){
      let inside=true,red=false,other=false;
      for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++){const p=(yy+dy)*width+xx+dx;if(!solid[p])inside=false;if(Math.abs(dx)<=1&&Math.abs(dy)<=1){if(cloth[p])red=true;else other=true;}}
      if(!inside||!red||!other)continue;
      // Allow under 6% antialias coverage loss at individual fringe edge
      // subpixels; transparent hairlines and holes remain a test failure.
      for(let sy=0;sy<4;sy++)for(let sx=0;sx<4;sx++){const alpha=actual[((yy*4+sy)*canvas.width+xx*4+sx)*4+3];samples++;if(alpha<240){gaps++;if(points.length<5)points.push({x:x+xx+sx/4,y:y+yy+sy/4,alpha});}}
    }
    rows.push({frame:index<0?'still':12+index,samples,gaps,points});
  }
  const totalGaps=rows.reduce((n,r)=>n+r.gaps,0);
  window.__scarfSeams={state:totalGaps?'failed':'done',totalGaps,rows};
  if(totalGaps)window.__scarfSeams.error='Transparent scarf/anatomy seams remain';
})().catch(e=>{window.__scarfSeams={state:'failed',error:e.message};});
