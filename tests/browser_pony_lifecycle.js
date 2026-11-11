/* gstack browse eval tests/browser_pony_lifecycle.js on a local Mock workspace. */
(async () => {
  const office = window.PonyOffice, checks = [];
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const wait = async fn => { for(let i=0;i<160;i++) { if(fn()) return; await new Promise(r=>setTimeout(r,100)); } throw Error('timeout'); };
  const $ = id => document.getElementById(id);
  document.querySelector('[data-view="analysis"]').click();
  await wait(()=>!$('try-sample').disabled);
  $('try-sample').click();
  await wait(()=>!$('try-sample').disabled && $('task-data').value.includes('console-mock'));
  $('task-notify').checked = false;
  $('task-form').requestSubmit();
  await wait(()=>office.snapshot().taskId);
  await wait(()=>['completed','failed','canceled'].includes(office.snapshot().taskState));
  const actual = office.snapshot();
  assert(actual.taskState==='completed','real Mock backend task completed');
  assert(actual.actors.some(a=>a.taskId===actual.taskId),'real task identity bound to actor');
  checks.push({realBackend:actual.taskId,state:actual.taskState});
  office.reset('visual-fixture',false);
  office.sync({id:'visual-fixture',status:{state:'working'}},[
    {seq:1,kind:'step',step:'main',status:'running',label:'主分析执行中'},
    {seq:2,kind:'step',step:'risk',status:'running',child_id:'fixture-child',label:'风险分析'}
  ]);
  let snap=office.snapshot();
  assert(snap.actors.find(a=>a.id==='risk').childId==='fixture-child','child identity');
  assert(snap.actors.find(a=>a.id==='main').screen==='task','immediate task display');
  office.disconnected();
  assert(office.snapshot().actors.find(a=>a.id==='main').screen==='disconnected','connection feedback');
  assert(document.querySelectorAll('.office-screen[data-mode="disconnected"]').length>=1,'actual disconnected screen updates immediately');
  office.sync({id:'visual-fixture',status:{state:'failed'}},[]);
  assert(office.snapshot().actors.find(a=>a.id==='main').screen==='result','failure feedback');
  checks.push('injected slow-task, child identity, connection loss, failure');
  office.reset();
  snap=office.snapshot();
  assert(snap.actors.filter(a=>a.present).every(a=>a.screen!=='off'),'all present monitors lit');
  checks.push('idle residency lighting');
  document.body.dataset.ponyCheck=JSON.stringify(checks);
  return JSON.stringify(checks);
})();
