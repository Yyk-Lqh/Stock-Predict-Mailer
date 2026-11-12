/* Run using gstack browse eval; results in document.body.dataset.ponyContacts. */
(async()=>{
  const assert=(ok,label)=>{if(!ok)throw Error(label);};
  const bounds=node=>node.getBoundingClientRect();
  const inside=(point,box,pad=2)=>point.x>=box.left-pad&&point.x<=box.right+pad&&point.y>=box.top-pad&&point.y<=box.bottom+pad;
  const center=node=>{const p=new DOMPoint(Number(node.getAttribute('cx')),Number(node.getAttribute('cy')));return p.matrixTransform(node.getScreenCTM());};
  let keyboard=0,mouse=0,maxNodes=0,minNodes=Infinity;
  for(let i=0;i<220;i++){
    const snap=window.PonyOffice.snapshot();
    for(const a of snap.actors.filter(a=>a.present&&a.pose==='seated'&&a.id!=='assistant')){
      const pony=document.querySelector(`[data-pony="${a.id}"]`);
      if(pony.dataset.mood==='打瞌睡')continue;
      const desk=[...document.querySelectorAll('.office-stage .office-desk-name')].find(n=>n.textContent===({'main':'主 Agent','mail':'邮件投递','prediction':'预测分析','risk':'风险分析','charts':'图表生成','advice':'建议生成'}[a.id])).parentNode;
      assert(inside(center(pony.querySelector('.pony-arm-left .pony-hoof')),bounds(desk.querySelector('.office-keyboard'))),a.id+' left hoof must contact keyboard'); keyboard++;
      if(pony.dataset.operation==='操作鼠标'){
        assert(inside(center(pony.querySelector('.pony-arm-right .pony-hoof')),bounds(desk.querySelector('.office-mouse'))),a.id+' right hoof must contact mouse'); mouse++;
      }
      assert(pony.querySelector('.pony-seated-head').getAttribute('opacity')==='1','seated avatar faces monitor');
    }
    const count=document.querySelectorAll('.pony-office *').length;
    maxNodes=Math.max(maxNodes,count);minNodes=Math.min(minNodes,count);
    await new Promise(r=>setTimeout(r,100));
  }
  assert(keyboard>20&&mouse>5,'device operation coverage');
  const result={keyboardSamples:keyboard,mouseSamples:mouse,DOMNodes:[minNodes,maxNodes],note:'actual SVG screen coordinates; no synthetic limb placement'};
  document.body.dataset.ponyContacts=JSON.stringify(result);
})().catch(error=>{document.body.dataset.ponyContacts=JSON.stringify({error:error.message});});
