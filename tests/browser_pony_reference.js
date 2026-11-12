/* Run via gstack browse eval on prototype/character-check.html. Source pixels
 * are compared against the same PonyRig used by the actual office renderer. */
(async()=>{
  const assert=(ok,label)=>{if(!ok)throw Error(label);};
  assert(location.pathname.endsWith('/prototype/character-check.html'),'Use the local source comparison harness');
  window.__referenceVerification={state:'running'};
  document.getElementById('mode').value='still';window.__characterCheck.paint();
  const still=await window.__characterCheck.measureStill();
  assert(still.silhouetteIoU>.975,'static silhouette overlap');
  const results=[];
  const canvas=document.createElement('canvas');canvas.width=854;canvas.height=620;
  const ctx=canvas.getContext('2d',{willReadFrequently:true});
  for(let index=0;index<18;index++){
    const pose=PonyRig.sampleWalk(index/18*Math.PI*2),source=new Image();
    source.src=`../.tmp/character-reference-review/video-b/frame-${String(pose.frame+1).padStart(4,'0')}.png`;
    await source.decode();ctx.fillStyle='white';ctx.fillRect(0,0,854,620);ctx.drawImage(source,0,0);
    const original=ctx.getImageData(0,0,854,620).data;
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('xmlns','http://www.w3.org/2000/svg');
    const scale=pose.pixelScale;svg.setAttribute('viewBox',`${-pose.origin[0]*scale} ${-pose.origin[1]*scale} ${854*scale} ${620*scale}`);
    svg.setAttribute('width',854);svg.setAttribute('height',620);
    const pony=document.createElementNS(svg.namespaceURI,'g');pony.innerHTML=PonyRig.markup({id:'reference',name:'source',color:'#ed2f31'},index);
    svg.append(pony);PonyRig.paintReference(pony,pose);pony.querySelector('.pony-ground').remove();
    const actual=new Image();actual.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));
    await actual.decode();ctx.fillRect(0,0,854,620);ctx.drawImage(actual,0,0);
    const rendered=ctx.getImageData(0,0,854,620).data;let intersection=0,union=0;
    for(let pixel=0;pixel<854*590;pixel++){
      const p=pixel*4,a=Math.max(original[p],original[p+1],original[p+2])<45,b=Math.max(rendered[p],rendered[p+1],rendered[p+2])<45;
      if(a&&b)intersection++;if(a||b)union++;
    }
    const iou=intersection/union;results.push({frame:pose.frame,iou});assert(iou>.96,`walk f${pose.frame} silhouette ${iou}`);
  }
  window.__referenceVerification={state:'done',still,walk:results,minWalkIoU:Math.min(...results.map(x=>x.iou)),meanWalkIoU:results.reduce((n,x)=>n+x.iou,0)/results.length,note:'black silhouettes at source size, no ground shadow; material and unseen angles are not measured'};
})().catch(error=>{window.__referenceVerification={state:'failed',error:error.message};});
