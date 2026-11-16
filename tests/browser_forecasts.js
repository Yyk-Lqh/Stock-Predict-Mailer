/* Use gstack browse eval against browser_console_fixture.py --forecast-fixtures. */
(async () => {
  const $ = id => document.getElementById(id), checks = [];
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const wait = async fn => { for (let i=0; i<150; i++) { if (fn()) return; await new Promise(r=>setTimeout(r,100)); } throw Error('timed out: '+String(fn)); };
  const set = (id, value) => { $(id).value=value; $(id).dispatchEvent(new Event('input',{bubbles:true})); };
  const filter = async value => { $('forecast-state').value=value; $('forecast-state').dispatchEvent(new Event('change')); await wait(()=>!$('forecast-refresh').disabled); };
  await wait(()=>window.ForecastUI && window.Workbench && !$('new-analysis').disabled);
  document.querySelector('[data-view="records"]').click(); await wait(()=>!$('forecast-refresh').disabled);
  await filter('all');
  assert($('forecast-list').children.length>=3,'three archive states missing'); checks.push('task-linked archive list');
  for (const state of ['pending','due','evaluated']) { await filter(state); assert($('forecast-list').children.length>0,'state filter '+state); }
  $('forecast-list').querySelector('button').click();
  await wait(()=>$('forecast-detail').textContent.includes('绝对误差'));
  assert($('forecast-detail').textContent.includes('2 CNY'),'evaluation units/metrics missing');
  assert(!$('forecast-detail').querySelector('img'),'source HTML executed');
  assert($('forecast-detail').textContent.includes('<img src=x'),'source text missing'); checks.push('three filters, evaluation details and escaped source');
  await filter('due'); $('forecast-list').querySelector('button').click();
  await wait(()=>$('forecast-detail').textContent.includes('到期不代表预测已验证'));
  checks.push('due status does not imply scored');
  const realFetch=window.fetch;
  window.fetch=(url,...args)=>String(url).includes('/api/forecasts?')?Promise.resolve(new Response(JSON.stringify({error:{code:'FORECAST_LIMIT',message:'synthetic read limit'}}),{status:400,headers:{'Content-Type':'application/json'}})):realFetch(url,...args);
  $('forecast-refresh').click(); await wait(()=>$('forecast-list-status').textContent.includes('读取失败'));
  window.fetch=realFetch; $('forecast-refresh').click(); await wait(()=>!$('forecast-refresh').disabled);
  assert($('forecast-list').children.length===1,'refresh failed to recover'); checks.push('visible query failure and refresh recovery');
  document.querySelector('[data-view="analysis"]').click(); $('new-analysis').click();
  await wait(()=>!$('new-analysis').disabled && $('conversation-id').value);
  window.AnalysisInput.open('input');
  assert(!$('facts-editor').contains($('evaluation-enabled')) && $('facts-editor').contains($('facts')), 'evaluation form displaced facts editor');
  assert($('evaluation-enabled').checkVisibility(), 'evaluation opt-in is hidden from users');
  const generated=new Date(Date.now()-60000).toISOString();
  const p={schema_version:'1',prediction_id:'browser-form-'+Date.now(),subject:'DEMO.SZ',generated_at:generated,
    valid_until:new Date(Date.now()+1800000).toISOString(),horizon:{value:1,unit:'hours'},model_version:'browser-form',
    synthetic:true,direction:'up',value:110,value_unit:'CNY',metrics:{fixture:1}};
  $('task-data').value=JSON.stringify({prediction:p,context:null}); $('json-to-form').click();
  assert(!$('evaluation-enabled').checked,'definition enabled by default');
  $('evaluation-enabled').click(); assert(!$('evaluation-fields').hidden,'definition fields not opened');
  const d={target_at:new Date(Date.parse(generated)+3600000).toISOString(),timezone:'Asia/Shanghai',metric:'close_unadjusted',unit:'CNY'};
  for (const [id,value] of Object.entries({target:d.target_at,timezone:d.timezone,metric:d.metric,unit:d.unit,reference:'100',observed:generated,available:generated,source:'browser synthetic reference'})) set('evaluation-'+id,value);
  assert(JSON.stringify(JSON.parse($('task-data').value).prediction)===JSON.stringify(p),'definition edits changed prediction');
  set('conversation-message','请核对这份合成预测的风险。'); $('analysis-send').click();
  await wait(()=>$('evaluation-tolerance').getAttribute('aria-invalid')==='true');
  assert($('conversation-message').value.includes('合成预测'),'invalid definition lost question');
  set('evaluation-tolerance','0.1'); $('analysis-send').click();
  await wait(()=>{try{return JSON.parse($('task-output').textContent).status.state==='completed';}catch(_){return false;}});
  const task=JSON.parse($('task-output').textContent), result=task.artifacts[0].parts[0].data;
  assert(result.analysis.prediction.value===110 && result.analysis.prediction.prediction_id===p.prediction_id,'prediction not preserved');
  assert(Date.parse(result.analysis.forecast_evidence.definition.target_at)===Date.parse(d.target_at),'form definition not sent');
  assert(!$('evaluation-enabled').checked && !JSON.parse($('task-data').value).evaluation_definition,'definition carried to next turn');
  checks.push('explicit form, validation preserves question, exact prediction binding and per-turn reset');
  $('analysis-tab-report').click();
  const link=Array.from($('report').querySelectorAll('button')).find(b=>b.textContent.includes('查看预测归档'));
  assert(link,'report archive link missing'); link.click();
  await wait(()=>$('forecast-detail').textContent.includes(result.analysis.forecast_evidence.forecast_id));
  checks.push('report opens authorized forecast details');
  document.querySelector('[data-view="analysis"]').click(); window.AnalysisInput.open('input');
  const mismatch=JSON.parse(JSON.stringify(result.analysis.forecast_evidence.definition)); mismatch.reference.synthetic=false;
  $('task-data').value=JSON.stringify({prediction:p,evaluation_definition:mismatch});$('json-to-form').click();set('evaluation-source','edited reference');
  assert(JSON.parse($('task-data').value).evaluation_definition.reference.synthetic===false,'editing coerced imported synthetic marker');
  let markerRejected=false;try{window.ForecastUI.validate();}catch(_){markerRejected=true;}
  assert(markerRejected,'mismatched synthetic marker accepted');checks.push('imported synthetic marker preserved and mismatch rejected');
  $('task-data').value=JSON.stringify({prediction:p,evaluation_definition:result.analysis.forecast_evidence.definition}); $('json-to-form').click();
  assert($('evaluation-enabled').checked,'raw JSON definition did not restore form');
  set('p-subject','OTHER.SZ');
  assert(!$('evaluation-enabled').checked && !JSON.parse($('task-data').value).evaluation_definition,'new prediction retained old definition');
  checks.push('raw JSON round-trip and prediction replacement reset');
  document.body.dataset.forecastCheck=JSON.stringify({checks,forecast_id:result.analysis.forecast_evidence.forecast_id});
})().catch(error=>{document.body.dataset.forecastCheck=JSON.stringify({error:error.message});});
