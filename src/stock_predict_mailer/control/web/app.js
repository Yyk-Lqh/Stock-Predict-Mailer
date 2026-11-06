const $ = id => document.getElementById(id);
let csrf = '', profiles = [], servers = [], endpoints = [], settings = null, currentTask = null;
let memoryKey = sessionStorage.getItem('spm_memory_key') || '';
const roles = {main:'主 Agent',prediction:'预测分析',risk:'风险分析',advice:'建议生成'};
function notice(message, error=false){const el=$('notice');el.textContent=message;el.classList.toggle('error',error);el.hidden=false;}
async function api(path,method='GET',body){const response=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,'X-Memory-Key':memoryKey},body:body===undefined?undefined:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(`${data.error?.code||response.status} · ${data.error?.message||'请求失败'}`);return data;}
function action(label,fn){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){notice(e.message,true);}finally{b.disabled=false;}};return b;}
function text(parent,tag,value,cls){const el=document.createElement(tag);el.textContent=value;if(cls)el.className=cls;parent.append(el);return el;}
const csv=value=>value.split(',').map(s=>s.trim()).filter(Boolean);
const lines=value=>value.split('\n').map(s=>s.trim()).filter(Boolean);
const num=(id)=>Number($(id).value);
function options(select,items,value,empty='继承默认'){select.replaceChildren();let op=document.createElement('option');op.value='';op.textContent=empty;select.append(op);for(const item of items){op=document.createElement('option');op.value=item.id;op.textContent=item.name+(!item.enabled?'（停用）':'');select.append(op);}select.value=value||'';}
function tab(id){document.querySelectorAll('.panel').forEach(el=>el.hidden=el.id!==id);document.querySelectorAll('nav button').forEach(el=>el.classList.toggle('active',el.dataset.tab===id));}
document.querySelectorAll('[data-tab]').forEach(el=>el.onclick=()=>tab(el.dataset.tab));
async function refresh(){[profiles,servers,endpoints,settings]=await Promise.all([api('models'),api('mcp'),api('agents'),api('settings')]);renderModels();renderServers();renderSettings();}
function record(container,title,description){const el=document.createElement('article');el.className='record';text(el,'h3',title);text(el,'p',description);const actions=document.createElement('div');actions.className='record-actions';el.append(actions);container.append(el);return actions;}
function empty(container,message){container.replaceChildren();if(message)text(container,'p',message,'empty muted');}
function renderModels(){empty($('model-list'),profiles.length?'':'尚未配置模型。先添加 Mock 模型，即可独立验证分析流程。');for(const p of profiles){const a=record($('model-list'),p.name+(settings.default_model_id===p.id?' · 默认':''),`${p.provider} / ${p.model}\n${p.enabled?'已启用':'已停用'} · 密钥${p.has_secret?'已保存（脱敏）':'未设置'} · ${p.supported_parameters.includes('temperature')?`温度 ${p.temperature_min}–${p.temperature_max}`:'不支持温度'}`);a.append(action('编辑',()=>editModel(p)),action('测试连接',async()=>notice((await api(`models/${p.id}/test`,'POST',{})).message)),action('设为默认',async()=>{await api('settings','PUT',{...settings,default_model_id:p.id});await refresh();notice('默认模型已更新');}),action(p.enabled?'停用':'启用',async()=>{await api(`models/${p.id}`,'PUT',{...p,enabled:!p.enabled});await refresh();}),action('清除密钥',async()=>{await api(`models/${p.id}`,'PUT',{...p,clear_secrets:['api_key']});await refresh();notice('模型密钥已清除');}),action('删除',async()=>{await api(`models/${p.id}`,'DELETE');await refresh();}));}}
function editModel(p){$('model-id').value=p.id;$('model-heading').textContent='编辑模型';for(const [id,key] of Object.entries({'model-name':'name','model-provider':'provider','model-url':'base_url','model-model':'model','model-timeout':'timeout_seconds','model-retries':'retries','model-temp-min':'temperature_min','model-temp-max':'temperature_max','model-price-in':'input_usd_per_million','model-price-out':'output_usd_per_million'}))$(id).value=p[key]??'';$('model-key').value='';$('model-temperature').checked=p.supported_parameters.includes('temperature');$('model-supported').value=p.supported_parameters.filter(k=>k!=='temperature').join(',');$('model-params').value=JSON.stringify(p.parameters,null,2);$('model-effort-map').value=JSON.stringify(p.reasoning_effort_map||{},null,2);}
$('model-new').onclick=()=>{$('model-form').reset();$('model-id').value='';$('model-heading').textContent='添加模型';};
$('model-form').onsubmit=async e=>{e.preventDefault();try{const id=$('model-id').value;const old=profiles.find(p=>p.id===id);const supported=csv($('model-supported').value).filter(k=>k!=='temperature');if($('model-temperature').checked)supported.push('temperature');const body={name:$('model-name').value,provider:$('model-provider').value,base_url:$('model-url').value,model:$('model-model').value,timeout_seconds:num('model-timeout'),retries:num('model-retries'),supported_parameters:supported,temperature_min:num('model-temp-min'),temperature_max:num('model-temp-max'),parameters:JSON.parse($('model-params').value),reasoning_effort_map:JSON.parse($('model-effort-map').value),input_usd_per_million:$('model-price-in').value===''?null:num('model-price-in'),output_usd_per_million:$('model-price-out').value===''?null:num('model-price-out'),api_key:$('model-key').value,enabled:old?.enabled??true};await api('models'+(id?'/'+id:''),id?'PUT':'POST',body);$('model-key').value='';await refresh();notice('模型已保存，密钥不会回显。');}catch(err){notice(err.message,true);}};
function renderServers(){empty($('mcp-list'),servers.length?'':'尚未添加 MCP 服务。连接测试可发现工具与资源。');for(const s of servers){const a=record($('mcp-list'),s.name,`${s.transport} · ${s.enabled?'已启用':'已停用'} · ${s.allowed_tools.length} 个已授权工具\n${s.transport==='stdio'?s.command:s.url}`);a.append(action('编辑',()=>editServer(s)),action('测试与发现',async()=>renderDiscovery(await api(`mcp/${s.id}/test`,'POST',{}),s)),action(s.enabled?'停用':'启用',async()=>{await api(`mcp/${s.id}`,'PUT',{...s,enabled:!s.enabled});await refresh();}),action('清除凭据',async()=>{await api(`mcp/${s.id}`,'PUT',{...s,clear_secrets:['auth_token','env']});await refresh();notice('服务凭据已清除');}),action('删除',async()=>{await api(`mcp/${s.id}`,'DELETE');await refresh();}));}}
function editServer(s){$('mcp-id').value=s.id;for(const [id,key] of Object.entries({'mcp-name':'name','mcp-transport':'transport','mcp-url':'url','mcp-command':'command','mcp-timeout':'timeout_seconds'}))$(id).value=s[key];$('mcp-token').value='';$('mcp-env').value='';$('mcp-args').value=JSON.stringify(s.args);$('mcp-tools').value=s.allowed_tools.join(',');$('mcp-effects').value=JSON.stringify(s.effects,null,2);$('mcp-resources').value=s.allowed_resources.join('\n');connectionFields();}
function connectionFields(){$('mcp-http').hidden=$('mcp-transport').value!=='streamable_http';$('mcp-stdio').hidden=$('mcp-transport').value!=='stdio';}
$('mcp-transport').onchange=connectionFields;
$('mcp-new').onclick=()=>{$('mcp-form').reset();$('mcp-id').value='';connectionFields();};
$('mcp-form').onsubmit=async e=>{e.preventDefault();try{const id=$('mcp-id').value;const old=servers.find(s=>s.id===id);const body={name:$('mcp-name').value,transport:$('mcp-transport').value,url:$('mcp-url').value,command:$('mcp-command').value,args:JSON.parse($('mcp-args').value),timeout_seconds:num('mcp-timeout'),allowed_tools:csv($('mcp-tools').value),effects:JSON.parse($('mcp-effects').value),allowed_resources:lines($('mcp-resources').value),auth_token:$('mcp-token').value,enabled:old?.enabled??true};if($('mcp-env').value.trim())body.env=JSON.parse($('mcp-env').value);await api('mcp'+(id?'/'+id:''),id?'PUT':'POST',body);$('mcp-token').value='';$('mcp-env').value='';await refresh();notice('MCP 服务已保存；可测试连接并发现工具。');}catch(err){notice(err.message,true);}};
function renderDiscovery(data,s){const parent=$('discovery');parent.replaceChildren();text(parent,'h3',`${s.name} · ${data.protocol_version}`);for(const t of data.tools){text(parent,'p',`${t.name} · ${s.allowed_tools.includes(t.name)?'已授权':'未授权'}`);const d=document.createElement('details');text(d,'summary','输入 / 输出 Schema');text(d,'pre',JSON.stringify({input:t.inputSchema,output:t.outputSchema},null,2));parent.append(d);}for(const r of data.resources){text(parent,'p',`${r.name} · ${r.uri}`);if(s.allowed_resources.includes(r.uri))parent.append(action('读取资源',async()=>{const result=await api(`mcp/${s.id}/read`,'POST',{uri:r.uri});text(parent,'pre',JSON.stringify(result,null,2));}));}notice(`发现 ${data.tools.length} 个工具、${data.resources.length} 个资源。`);}
function renderSettings(){options($('default-model'),profiles,settings.default_model_id,'请选择默认模型');$('global-temperature').value=settings.global_temperature;$('default-effort').value=settings.default_reasoning_effort;$('chart-delivery').value=settings.mail.chart_delivery;const container=$('role-settings');container.replaceChildren();for(const [role,title] of Object.entries(roles)){const r=document.createElement('div');r.className='role-row';text(r,'h3',title);for(const [field,label,items] of [['model_id','使用模型',profiles],['endpoint_id','A2A 对端',endpoints]]){const l=text(r,'label',label);const s=document.createElement('select');s.id=`role-${role}-${field}`;options(s,items,settings.agents[role][field],field==='model_id'?'继承默认模型':'本机运行');if(role==='main'&&field==='endpoint_id')s.disabled=true;l.append(s);}const l=text(r,'label','温度覆盖');const input=document.createElement('input');input.type='number';input.min='0';input.max='2';input.step='.1';input.placeholder='继承';input.id=`role-${role}-temperature`;input.value=settings.agents[role].temperature??'';l.append(input);const tools=text(r,'label','主 Agent 读取工具（服务 ID:工具名，逗号分隔）','role-tools');const ti=document.createElement('input');ti.id=`role-${role}-tools`;ti.value=settings.agents[role].tools.join(',');ti.disabled=role!=='main';ti.placeholder=servers[0]?`${servers[0].id}:get_context`:'先添加 MCP 服务并授权工具';tools.append(ti);container.append(r);const update=()=>{const m=profiles.find(p=>p.id===(r.querySelector('select').value||settings.default_model_id));input.disabled=!!m&&!m.supported_parameters.includes('temperature');input.title=input.disabled?'此模型不支持温度；清除旧覆盖后保存。':'留空继承';if(m){input.min=m.temperature_min;input.max=m.temperature_max;}};r.querySelector('select').onchange=update;update();}for(const [key,value] of Object.entries(settings.limits))$('limit-'+key).value=value;const m=settings.mail;for(const key of ['transport','sender','host','port','tls'])$('mail-'+key).value=m[key];$('mail-allowlist').value=m.recipient_allowlist.join('\n');$('mail-synthetic').checked=m.allow_synthetic;options($('mail-mcp-server'),servers,m.mcp_server_id,'请选择邮件服务');$('mail-mcp-tool').value=m.mcp_tool||'';empty($('endpoint-list'));for(const ep of endpoints){const a=record($('endpoint-list'),ep.name,ep.url);a.append(action('编辑',()=>{$('endpoint-id').value=ep.id;$('endpoint-name').value=ep.name;$('endpoint-url').value=ep.url;$('endpoint-cost').value=ep.cost_ceiling_usd;$('endpoint-token').value='';}),action(ep.enabled?'停用':'启用',async()=>{await api(`agents/${ep.id}`,'PUT',{...ep,enabled:!ep.enabled});await refresh();}),action('删除',async()=>{await api(`agents/${ep.id}`,'DELETE');await refresh();}));}}
$('endpoint-save').onclick=async()=>{try{const id=$('endpoint-id').value;const old=endpoints.find(e=>e.id===id);await api('agents'+(id?'/'+id:''),id?'PUT':'POST',{name:$('endpoint-name').value,url:$('endpoint-url').value,cost_ceiling_usd:num('endpoint-cost'),auth_token:$('endpoint-token').value,enabled:old?.enabled??true});$('endpoint-id').value='';$('endpoint-token').value='';await refresh();notice('A2A 对端已保存');}catch(e){notice(e.message,true);}};
$('settings-form').onsubmit=async e=>{e.preventDefault();try{const value=structuredClone(settings);value.default_model_id=$('default-model').value||null;value.global_temperature=num('global-temperature');value.default_reasoning_effort=$('default-effort').value;value.mail.chart_delivery=$('chart-delivery').value;for(const role of Object.keys(roles)){const temp=$(`role-${role}-temperature`);value.agents[role]={model_id:$(`role-${role}-model_id`).value||null,endpoint_id:role==='main'?null:$(`role-${role}-endpoint_id`).value||null,temperature:temp.disabled||temp.value===''?null:Number(temp.value),tools:role==='main'?csv($(`role-${role}-tools`).value):[]};}for(const key of Object.keys(value.limits))value.limits[key]=num('limit-'+key);const m=value.mail;for(const key of ['transport','sender','host','tls'])m[key]=$('mail-'+key).value;m.port=num('mail-port');m.recipient_allowlist=lines($('mail-allowlist').value);m.allow_synthetic=$('mail-synthetic').checked;m.mcp_server_id=$('mail-mcp-server').value||null;m.mcp_tool=$('mail-mcp-tool').value||null;await api('settings','PUT',value);await refresh();notice('协作边界与邮件授权已保存');}catch(err){notice(err.message,true);}};
$('reset-temperature').onclick=async()=>{try{await api('settings/reset-temperature','POST',{});await refresh();notice('全局温度已恢复为 0.2，角色覆盖已清空；模型生成参数中的显式温度可在模型配置中清除。');}catch(e){notice(e.message,true);}};
function mockInput() {
  const now = new Date();
  now.setUTCMinutes(0, 0, 0);
  const time = now.toISOString();
  const day = 86400000;
  const at = offset => {
    let time = now.getTime();
    let remaining = Math.abs(offset);
    while (remaining) {
      time += Math.sign(offset) * day;
      const weekday = new Date(time).getUTCDay();
      if (weekday !== 0 && weekday !== 6) remaining--;
    }
    return new Date(time).toISOString();
  };
  const prediction = {schema_version:'1', prediction_id:'console-mock-'+time, subject:'DEMO.SZ',
    generated_at:time, valid_until:at(1), horizon:{value:5,unit:'trading_days'},
    direction:'up', value:11.2, value_unit:'CNY', confidence:null, model_version:'mock-v1', synthetic:true, metrics:{}};
  const observed = Array.from({length:12}, (_, i) => ({at:at(i-12), value:9.4+i*.09}));
  const forecast = [1, 3, 5].map((offset, i) => ({at:at(offset), value:[10.6,10.9,11.2][i], lower:10+i*.15, upper:11.3+i*.2}));
  const backtest = observed.slice(-6).map((point, i) => ({at:point.at, issued_at:at(i-7), value:point.value+.08}));
  const chart_data = {unit:'CNY', series:{
    observed:{source:'Mock 历史数据',points:observed},
    forecast:{source:'Mock 上游模型',points:forecast},
    backtest:{source:'Mock 历史预测',points:backtest}
  }};
  $('task-data').value = JSON.stringify({prediction, context:null, chart_data}, null, 2);
}
$('load-mock').onclick=mockInput;
function showTask(task){$('task-output').textContent=JSON.stringify(task,null,2);const el=$('task-summary');el.replaceChildren();text(el,'h3',`任务 ${task.status.state}`);text(el,'p',task.id);if(task.metadata?.error)text(el,'p',`${task.metadata.error.code} · ${task.metadata.error.message||''}`);const result=task.artifacts?.[0]?.parts?.[0]?.data;if(result){text(el,'p',`分析：${result.analysis.status} · 调用 ${result.usage.calls} 次 · 费用预留 $${result.usage.reserved_usd}`);for(const child of result.children)text(el,'p',`${roles[child.role]} · ${child.status}${child.error?' / '+child.error:''}`);for(const [label,values] of [['推断',result.analysis.inferences.map(i=>i.text)],['限制',result.analysis.limitations],['风险',result.analysis.risks],['建议',result.analysis.recommendations]]){text(el,'h3',label);const ul=document.createElement('ul');for(const v of values)text(ul,'li',v);el.append(ul);}if(result.mail)text(el,'p',`邮件：${result.mail.status} · ${result.mail.id}`);}const finished=['completed','failed','canceled'].includes(task.status.state);$('task-cancel').hidden=finished;return finished;}
let eventCursor = 0;
const stepRows = new Map();
const progressStates = {pending:'待执行', running:'运行中', completed:'已完成', failed:'失败'};
function addPlanStep(step) {
  if (stepRows.has(step.id)) return;
  const row = document.createElement('li');
  const marker = stepRows.get('charts');
  if (marker && ['prediction','risk','advice','merge'].includes(step.id)) marker.before(row);
  else $('execution-plan').append(row);
  row.textContent = `${roles[step.label] || step.label} · 待执行`;
  row.dataset.status = 'pending';
  stepRows.set(step.id, row);
}
function showEvent(event) {
  for (const step of event.steps || []) addPlanStep(step);
  if (event.execution) {
    const {label, limits, native_reasoning_effort: native, model} = event.execution;
    $('effective-effort').textContent = `${label} · ${model || '确定性分析'} · 原生推理 ${native || '未配置'} · ${limits.max_steps} 步 / ${limits.max_tool_calls} 次工具 / ${limits.max_calls} 次调用 / ${limits.timeout_seconds} 秒 / ${limits.max_subagents} 个子 Agent / $${limits.budget_usd}`;
  }
  if (event.kind === 'step' && stepRows.has(event.step)) {
    const row = stepRows.get(event.step);
    row.dataset.status = event.status;
    row.textContent = `${event.label} · ${progressStates[event.status] || event.status}`;
  }
  const localTime = new Date(event.timestamp).toLocaleTimeString('zh-CN');
  const row = text($('execution-events'), 'li', `${localTime} · ${event.label}${event.code ? ' · '+event.code : ''}`);
  row.dataset.status = event.status || event.kind;
  if (event.summary?.length) text(row, 'small', event.summary.join(' / '));
  if (event.kind === 'model') {
    text(row, 'small', `温度 ${event.temperature ?? '由服务决定'} · 原生推理 ${event.native_reasoning_effort || '未配置'}`);
  }
  if (event.preview) {
    const preview = $('analysis-preview');
    preview.replaceChildren();
    text(preview, 'h3', event.kind === 'report' ? '报告摘要' : '阶段分析');
    for (const item of event.preview.inferences) text(preview, 'p', item.text);
    for (const note of event.preview.limitations || []) text(preview, 'p', note);
  }
  if (event.kind === 'chart') {
    const figure = document.createElement('figure');
    const image = document.createElement('img');
    image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(event.svg);
    image.alt = event.label;
    figure.append(image);
    text(figure, 'figcaption', event.caption);
    $('chart-preview').append(figure);
  }
}
async function poll(id) {
  if (currentTask !== id) return;
  try {
    const task = await api('tasks/'+id);
    const progress = await api(`tasks/${id}/events?after=${eventCursor}`);
    if (currentTask !== id) return;
    for (const event of progress.events) {
      showEvent(event);
      eventCursor = event.seq;
    }
    if (!showTask(task) || progress.events.length === 100) setTimeout(() => poll(id), 600);
    else if (memoryKey) refreshMemory().catch(error => notice(error.message, true));
  } catch (error) {
    notice(error.message, true);
  }
}
$('task-form').onsubmit = async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('[type=submit]');
  button.disabled = true;
  try {
    const input = JSON.parse($('task-data').value);
    const conversationId = $('conversation-id').value;
    const controls = {complexity:$('task-complexity').value, goal:$('task-goal').value, reasoning_effort:$('task-effort').value || null};
    const request = conversationId && !input.prediction ? {...input} : {...input, ...controls};
    if (conversationId) {
      request.conversation_id = conversationId;
      request.message = $('conversation-message').value;
      if ($('conversation-constraints').value.trim()) request.constraints = lines($('conversation-constraints').value);
      if ($('conversation-format').value) request.report_format = $('conversation-format').value;
      const remember = [];
      const format = $('remember-format').value;
      if (format) remember.push({kind:'preference', tags:['报告格式'], content:format === 'brief' ? '偏好简版报告' : '偏好标准版报告', report_format:format});
      if ($('remember-text').value.trim()) remember.push({kind:'user_statement', tags:['用户明确要求'], content:$('remember-text').value});
      if (remember.length) request.remember = remember;
    }
    const task = await api('tasks', 'POST', {...request,
      notify:$('task-notify').checked, recipient:$('task-recipient').value || null});
    currentTask = task.id;
    $('remember-format').value = '';
    $('remember-text').value = '';
    eventCursor = 0;
    stepRows.clear();
    for (const id of ['execution-plan','execution-events','chart-preview','analysis-preview']) $(id).replaceChildren();
    $('effective-effort').textContent = '正在读取生效配置';
    $('task-progress').hidden = false;
    showTask(task);
    poll(task.id);
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
};
$('task-cancel').onclick=async()=>{try{showTask(await api(`tasks/${currentTask}/cancel`,'POST',{}));}catch(e){notice(e.message,true);}};
(async()=>{try{csrf=(await api('session')).csrf_token;await refresh();mockInput();}catch(e){notice(e.message,true);}})();
