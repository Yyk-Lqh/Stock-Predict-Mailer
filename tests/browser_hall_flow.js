/* Real Mock task + presentation contracts, disposable :8768 only. No video. */
(async()=>{
  const assert=(ok,label)=>{if(!ok)throw Error(label);};
  assert(location.port==='8768','Use disposable fixture');window.__hallFlow={state:'running'};
  const wait=async fn=>{for(let i=0;i<220;i++){if(await fn())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timed out');};
  await wait(()=>window.PonyOffice?.hall&&window.AnalysisInput);document.querySelector('.nav [data-view=analysis]').click();
  const hall=PonyOffice.hall;
  assert(hall.data.market.demo&&document.querySelector('.market-mode').textContent.includes('演示'),'unconnected wall identifies demo');
  document.querySelector('.market-ticker-toggle').click();assert(document.querySelector('.market-wall').classList.contains('ticker-paused'),'ticker pause');
  document.querySelector('.market-ticker-toggle').click();
  document.querySelector('.market-palette').click();assert(document.querySelector('.securities-hall').dataset.marketPalette==='international','alternate price palette');document.querySelector('.market-palette').click();
  const live={source:'隔离验收数据源',as_of:new Date().toISOString(),timezone:'Asia/Shanghai',quotes:[{symbol:'FIXTURE',name:'仅用于验收',last:20,change_pct:1.5,industry:'测试行业'}],history:[{at:'2026-11-12',value:19},{at:'2026-11-13',value:20}]};
  hall.receive(live);const snapshot=hall.data.market;
  hall.data.receivedAt-=91000;hall.tick(performance.now(),true);assert(document.querySelector('.market-mode').textContent.includes('暂未更新'),'stale snapshot has a visible age warning');
  hall.disconnect();assert(hall.data.market===snapshot&&document.querySelector('.market-mode').textContent.includes('中断'),'disconnect retains snapshot and warns');
  assert(document.querySelector('.market-provenance').textContent.includes('隔离验收数据源'),'source and timestamp retained');
  assert(!document.querySelector('.market-chart-image').innerHTML.includes('<script'),'chart remains data-only');
  const oldTask=PonyOffice.snapshot().taskId;
  $('new-analysis').click();await wait(()=>!$('new-analysis').disabled&&$('conversation-id').value);
  $('try-sample').click();await wait(()=>!$('try-sample').disabled&&$('task-data').value.includes('console-mock'));
  $('task-complexity').value='complex';$('task-complexity').dispatchEvent(new Event('change',{bubbles:true}));
  $('conversation-message').value='核对数据缺失、风险与预测条件，不额外发送邮件。';$('conversation-message').dispatchEvent(new Event('input',{bubbles:true}));
  $('task-notify').checked=false;$('analysis-send').click();
  await wait(()=>/^[a-f0-9]{32}$/.test(PonyOffice.snapshot().taskId||'')&&PonyOffice.snapshot().taskId!==oldTask);
  const id=PonyOffice.snapshot().taskId;await wait(()=>PonyOffice.snapshot().taskState==='completed');
  const result=await api('tasks/'+id);window.__hallActualTask=result;
  assert(hall.data.task.id===id,'wall bound to actual backend task');
  assert(document.querySelector('.market-subject').textContent.includes('DEMO.SZ'),'subject reflects analysis');
  assert(hall.data.summary().mail==null,'notification disabled never reports mail sent');
  document.querySelector('.market-chart-head select').value='subject';document.querySelector('.market-chart-head select').dispatchEvent(new Event('change'));
  assert(hall.data.chart||document.querySelector('.market-chart-image svg'),'task chart mapped');
  document.querySelector('[data-office-desk=prediction]').dispatchEvent(new MouseEvent('click',{bubbles:true}));assert(!$('report-inspector').hidden&&$('analysis-tab-progress').getAttribute('aria-selected')==='true','seat opens real progress detail');
  if(innerWidth>=1100)assert(document.querySelector('.market-wall').getBoundingClientRect().right<=$('report-inspector').getBoundingClientRect().left,'task panel does not cover market wall');
  Workbench.inspector(false);PonyOffice.disconnected();assert(document.querySelector('.market-stage').textContent.includes('任务连接中断'),'task disconnect has separate status');
  PonyOffice.sync(result,[]);assert(!document.querySelector('.market-stage').textContent.includes('连接中断'),'task reconnect restores status');
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  const composer=$('analysis-composer').getBoundingClientRect(),wall=document.querySelector('.market-wall').getBoundingClientRect();
  for(const desk of document.querySelectorAll('[data-office-desk][role=button]')){
    const box=desk.getBoundingClientRect();assert(box.top>=wall.bottom&&box.bottom<composer.top,'all six desks remain clear of market wall and conversation history');
  }
  window.__hallFlow={state:'done',taskId:id,taskState:result.status.state,children:result.artifacts?.[0]?.parts?.[0]?.data?.children?.length,chart:!!hall.data.chart,marketStalePreserved:true,note:'Actual Mock backend task; only injected quote feed is synthetic. No live market/model/SMTP request or video.'};
})().catch(error=>{window.__hallFlow={state:'failed',error:error.stack};});
