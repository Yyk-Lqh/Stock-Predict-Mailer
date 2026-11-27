(() => {
  window.workflowMigrationResult = {state:'running'};
  (async()=>{
  const assert=(value,message)=>{if(!value)throw Error(message);};
  const checkpoint=JSON.parse(sessionStorage.getItem('workflow-browser-reload')||'null');
  assert(innerWidth===900 && checkpoint,'Narrow desktop fixture state is missing');
  const entry=document.querySelector('[data-workflow-node=prediction]');
  assert(parseFloat(entry?.style.left)===checkpoint.position,'Unsaved keyboard movement did not survive reload');
  const library=document.getElementById('workflow-library-toggle');
  if(library.getAttribute('aria-expanded')==='false')library.click();
  assert(document.querySelector('.desktop-flow-palette input').getClientRects().length,'Node search not visible');
  const file=document.getElementById('desktop-workflow-file'), transfer=new DataTransfer();
  const old={version:1,nodes:[
    {id:'entry',position:{x:30,y:200},data:{type:'input',label:'旧资料输入',detail:'原资料入口'}},
    {id:'legacy-node',position:{x:330,y:200},data:{type:'unknown_step',label:'旧策略',detail:'原说明',condition:'旧文本条件',config:{api_key:'test-secret'}}}
  ],edges:[{id:'entry-legacy',source:'entry',target:'legacy-node'}]};
  transfer.items.add(new File([JSON.stringify(old)],'legacy.json',{type:'application/json'}));file.files=transfer.files;
  file.dispatchEvent(new Event('change',{bubbles:true}));
  for(let i=0;i<40 && !document.querySelector('[data-workflow-node=legacy-node][data-draft]');i++)await new Promise(resolve=>setTimeout(resolve,50));
  const node=document.querySelector('[data-workflow-node=legacy-node]');
  assert(node?.textContent.includes('草稿'),'Unknown version 1 node was lost');
  node.click();
  const text=document.getElementById('desktop-workflow-inspector').textContent;
  assert(text.includes('旧文本条件') && !text.includes('test-secret'),'Legacy config or credential filtering failed');
  const saved=AnalysisMode.read('workflow', 'professional');
  assert(saved.nodes.some(node=>node.id==='report'),'Import changed previously saved graph');
  window.workflowMigrationResult={state:'passed',width:innerWidth,recovered:true,legacyDraft:true,legacySecretFiltered:true};
  })().catch(error=>{window.workflowMigrationResult={state:'failed',error:error.message};});
  return 'workflow migration check started';
})()
