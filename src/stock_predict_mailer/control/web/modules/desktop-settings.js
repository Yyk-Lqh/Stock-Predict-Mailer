/* Desktop configuration guidance. All writes use the original form handlers. */
window.DesktopSettings = (() => {
  if (!matchMedia('(min-width: 761px)').matches) return;
  const tests = new Map(), pane = document.querySelector('[data-view-pane="settings"]');
  const pending = new Set();
  let lastDiscovery = null;
  const make = (tag, value, cls) => { const node=document.createElement(tag); if(value!=null)node.textContent=value; if(cls)node.className=cls; return node; };
  const button = (label, callback, cls='btn tiny') => { const node=make('button',label,cls); node.type='button'; node.onclick=callback; return node; };
  const status = (id,message,error=false) => { $(id).textContent=message; $(id).classList.toggle('error-text',error); };
  const feedback = (id,parent) => { const node=make('p',null,'hint desktop-config-feedback'); node.id=id; node.setAttribute('role','status'); parent.prepend(node); return node; };
  const label = id => $(id).closest('label');
  const signature = p => JSON.stringify([p.name,p.provider,p.base_url,p.model,p.parameters,p.supported_parameters,p.temperature_min,p.temperature_max,p.reasoning_effort_map,p.timeout_seconds,p.retries,p.has_secret,p.enabled,p.input_usd_per_million,p.output_usd_per_million]);
  const overview=make('section',null,'desktop-settings-overview'); overview.setAttribute('aria-label','已保存配置');
  overview.append(make('h2','已保存的工作区配置'),make('p','保存、测试连接和设为默认分别生效。下面的摘要只显示已保存状态。','hint'));
  const summary=make('dl',null,'desktop-config-summary');
  for(const [id,title] of [['model','默认模型'],['tools','外部能力'],['mail','邮件通道']]) { const row=make('div'); row.append(make('dt',title)); const value=make('dd'); value.id='desktop-saved-'+id; row.append(value); summary.append(row); }
  overview.append(summary); pane.querySelector('.page-head').after(overview);

  const form=$('model-form'), basic=make('div',null,'grid-3 desktop-model-basic'), remote=make('div',null,'grid-2 desktop-model-remote');
  const advanced=make('details',null,'input-editor desktop-model-advanced'); advanced.append(make('summary','高级参数 · 超时、温度与生成设置'));
  const advancedGrid=make('div',null,'grid-2 desktop-model-advanced-fields'); advanced.append(advancedGrid);
  const prior=[...form.children];
  for(const id of ['model-name','model-provider','model-model']) basic.append(label(id));
  for(const id of ['model-url','model-key','model-price-in']) remote.append(label(id));
  for(const id of ['model-timeout','model-retries','model-temperature','model-temp-min','model-temp-max','model-supported','model-effort-map','model-params']) advancedGrid.append(label(id));
  const submit=form.querySelector('.submit-bar'); submit.before(basic,remote,advanced);
  for(const node of prior) if(node.tagName==='DIV' && !node.classList.contains('section-head') && !node.classList.contains('submit-bar') && !node.querySelector('input,select,textarea,button')) node.hidden=true;
  const modelInfo=feedback('desktop-model-feedback',form);
  const remoteHint=make('p','测试真实服务会发起推理请求并可能计费。密钥留空保留已保存值；保存不会自动测试。','hint'); remote.append(remoteHint);
  const mcpInfo=feedback('desktop-mcp-feedback',$('mcp-form'));

  function reveal(field,message) {
    for(let parent=field.parentElement;parent;parent=parent.parentElement) { if(parent.tagName==='DETAILS')parent.open=true; if(parent.dataset.desktopConditional)parent.hidden=false; }
    field.setAttribute('aria-invalid','true'); field.focus(); field.scrollIntoView({block:'center'});
    if(message)status(field.closest('form')===form?'desktop-model-feedback':'desktop-mcp-feedback',message,true);
  }
  function validateObject(field, empty=false) {
    if(empty&&!field.value.trim())return;
    try { const value=JSON.parse(field.value); if(!value||typeof value!=='object'||Array.isArray(value))throw Error(); }
    catch(_) { throw {field,message:'请填写有效的 JSON 对象，当前输入已保留。'}; }
  }
  form.addEventListener('submit',event=>{
    try { validateObject($('model-params')); validateObject($('model-effort-map')); if($('model-temperature').checked&&Number($('model-temp-min').value)>Number($('model-temp-max').value))throw {field:$('model-temp-min'),message:'温度最小值不能大于最大值。'}; }
    catch(error) { event.preventDefault();event.stopImmediatePropagation();reveal(error.field,error.message); }
  },true);
  form.addEventListener('invalid',event=>reveal(event.target,'请修正标记字段后保存。'),true);
  form.addEventListener('input',event=>{event.target.removeAttribute('aria-invalid');status('desktop-model-feedback','表单有未保存的修改。');});
  $('model-provider').addEventListener('change',modelFields);
  function modelFields() {
    const mock=$('model-provider').value==='mock'; remote.hidden=mock;
    for(const id of ['model-url','model-key','model-price-in','model-price-out'])$(id).disabled=mock;
    $('model-price-in').required=$('model-price-out').required=!mock;
    status('desktop-model-feedback',mock?'Mock 离线模拟，无需远程地址、密钥或报价。保存后仍需单独设为默认。':'填写远程连接与手动报价；保存后可按需测试，再设为默认。');
  }
  function paintTests() {
    for(const [index,node] of [...$('model-list').querySelectorAll('.record')].entries()) {
      node.querySelector('.desktop-model-test-state')?.remove();
      const profile=profiles[index]; if(!profile)continue;
      const cached=tests.get(profile.id), valid=cached?.signature===signature(profile);
      node.append(make('p',valid?`${cached.error?'本页测试失败':'本页测试通过'} · ${cached.message}`:'本页尚未测试当前配置。','hint desktop-model-test-state'));
    }
  }
  function modelSaved(profile) {
    tests.delete(profile.id); editModel(profile,true); advanced.open=false;
    status('desktop-model-feedback','模型已保存；继续保存会更新同一配置。测试与设为默认可在模型列表单独操作。');
  }

  const groups=[...$('settings-form').querySelectorAll(':scope > details')];
  const nav=make('nav',null,'desktop-settings-groups'); nav.setAttribute('aria-label','协作设置分组');
  for(const group of groups)nav.append(button(group.querySelector('summary').textContent,()=>{group.open=true;group.scrollIntoView({block:'start'});group.querySelector('input:not(:disabled):not([type="hidden"]),select:not(:disabled)')?.focus({preventScroll:true});}));
  const edits=make('p',null,'hint'); edits.id='desktop-settings-edits'; edits.setAttribute('role','status'); nav.append(edits); $('settings-form').prepend(nav);
  const draft=make('div',null,'desktop-settings-draft'); draft.append(make('h3','当前表单预览'),make('p','修改后需保存才生效；运行上限还需以具体任务回执为准。','hint')); const draftText=make('p'); draftText.id='desktop-settings-draft-values'; draft.append(draftText); nav.after(draft);
  const mailFields=[['smtp',['mail-host','mail-port','mail-tls']],['mcp',['mail-mcp-server','mail-mcp-tool']]];
  for(const [type,ids]of mailFields)for(const id of ids)label(id).dataset.desktopConditional=type;
  $('settings-form').addEventListener('input',preview); $('settings-form').addEventListener('change',preview);
  $('settings-form').addEventListener('invalid',event=>{for(let parent=event.target.parentElement;parent&&parent!==$('settings-form');parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;if(parent.dataset.desktopConditional)parent.hidden=false;}},true);
  function preview() {
    if(!settings)return;
    status('desktop-settings-edits',settingsDirty?`未保存修改 · ${settingsEdits.size} 项字段`:'当前协作设置已保存。');
    const defaultId=$('default-model').value, model=profiles.find(p=>p.id===defaultId);
    $('desktop-settings-draft-values').textContent=`默认模型：${model?.name||'未选择'}；最多 ${$('limit-max_calls').value} 次调用 / ${$('limit-timeout_seconds').value} 秒 / $${$('limit-budget_usd').value} 费用预算；邮件：${{file:'本地文件模拟',smtp:'SMTP',mcp:'MCP 工具'}[$('mail-transport').value]}。`;
    for(const row of $('role-settings').querySelectorAll('.role-row')) {
      row.querySelector('.desktop-role-effective')?.remove();
      const select=row.querySelector('select'), role=select.id.replace(/^role-/,'').replace(/-model_id$/,'');
      const chosen=profiles.find(p=>p.id===(select.value||defaultId)), temp=$(`role-${role}-temperature`), endpoint=$(`role-${role}-endpoint_id`);
      temp.disabled=Boolean(chosen&&!chosen.supported_parameters.includes('temperature'));
      temp.title=temp.disabled?'当前表单所选模型不支持温度；保存时不提交角色温度覆盖。':'留空继承模型或全局温度';
      if(chosen){temp.min=chosen.temperature_min;temp.max=chosen.temperature_max;}
      const temperature=chosen&&!chosen.supported_parameters.includes('temperature')?'模型不支持温度':temp.value!==''?'角色温度 '+temp.value:chosen?.parameters.temperature!=null?'模型温度 '+chosen.parameters.temperature:'全局温度 '+$('global-temperature').value;
      row.append(make('p',`${select.value?'角色指定':'继承默认'}：${chosen?.name||'未选择模型'}${chosen&&!chosen.enabled?'（已停用）':''} · ${temperature} · ${endpoint.value?'外部 Agent':'本机运行'}`,'hint desktop-role-effective'));
    }
    for(const[type,ids]of mailFields)for(const id of ids)label(id).hidden=$('mail-transport').value!==type;
  }
  function refresh() {
    if(!settings)return;
    const model=profiles.find(p=>p.id===settings.default_model_id);
    $('desktop-saved-model').textContent=model?`${model.name} · ${model.enabled?'已启用':'已停用'}${model.provider==='mock'?' · 离线模拟':''}`:'尚未选择默认模型';
    $('desktop-saved-tools').textContent=`${servers.length} 个 MCP 服务 · ${servers.reduce((sum,s)=>sum+s.allowed_tools.length,0)} 个工具在白名单 · ${endpoints.length} 个 A2A 配置`;
    $('desktop-saved-mail').textContent=`${{file:'本地文件模拟，不代表邮箱收到',smtp:'SMTP，尚需按投递回执核对',mcp:'MCP 邮件工具，仍须逐轮授权'}[settings.mail.transport]} · ${settings.mail.recipient_allowlist.length} 个清单地址`;
    paintTests(); preview();
  }

  function mcpFields() { status('desktop-mcp-feedback','保存连接配置后，再按需测试与发现。发现工具不会自动授权。'); if(lastDiscovery)discovery(lastDiscovery.data,lastDiscovery.server); }
  function saveState(kind,active) {
    const editor=$(kind+'-form');editor.inert=active;editor.setAttribute('aria-busy',String(active));
    editor.querySelector('button[type="submit"]').disabled=active;$(kind+'-new').disabled=active;
    if(active)pending.add(kind);else pending.delete(kind);
  }
  function discovery(data,server) {
    lastDiscovery={data,server}; $('discovery').querySelector('.desktop-permission-editor')?.remove();
    const root=make('section',null,'desktop-permission-editor'); root.append(make('h3','待保存的工具权限'),make('p','工具白名单与权限类型需要同时满足；下面的修改只更新表单，点击保存 MCP 服务后才生效。','hint'));
    if($('mcp-id').value!==server.id)root.append(button('编辑该服务权限',()=>{editServer(server);discovery(data,server);}));
    else {
      let allowed,effects;
      try {allowed=new Set(csv($('mcp-tools').value));effects=JSON.parse($('mcp-effects').value||'{}');if(!effects||typeof effects!=='object'||Array.isArray(effects))throw Error();}
      catch(_){root.append(make('p','权限 JSON 无法解析，请先修正高级字段。','error-text'));$('discovery').append(root);return;}
      for(const tool of data.tools) {
        const row=make('div',null,'desktop-permission-row'), check=make('input');check.type='checkbox';check.checked=allowed.has(tool.name);check.setAttribute('aria-label',`允许工具 ${tool.name}`);
        const text=make('span',tool.name),effect=make('select'); effect.setAttribute('aria-label',`${tool.name} 权限类型`);
        for(const[value,title]of [['deny','拒绝'],['read','只读'],['email','邮件（另需授权）']])effect.add(new Option(title,value));effect.value=effects[tool.name]||'deny';
        const update=()=>{try{const current=new Set(csv($('mcp-tools').value)), map=JSON.parse($('mcp-effects').value||'{}');if(!map||typeof map!=='object'||Array.isArray(map))throw Error();if(check.checked)current.add(tool.name);else current.delete(tool.name);$('mcp-tools').value=[...current].join(',');$('mcp-effects').value=JSON.stringify({...map,[tool.name]:effect.value},null,2);status('desktop-mcp-feedback','权限已更新到表单，尚未保存。');}catch(_){status('desktop-mcp-feedback','权限 JSON 无法解析，现有输入已保留。',true);}};
        check.onchange=effect.onchange=update;row.append(check,text,effect);root.append(row);
      }
    }
    $('discovery').append(root);
  }
  $('mcp-form').addEventListener('input',()=>status('desktop-mcp-feedback','连接或权限表单有未保存修改。'));
  $('mcp-form').addEventListener('submit',event=>{try{validateObject($('mcp-effects'));validateObject($('mcp-env'),true);const args=JSON.parse($('mcp-args').value);if(!Array.isArray(args))throw {field:$('mcp-args'),message:'启动参数需要 JSON 数组。'};}catch(error){event.preventDefault();event.stopImmediatePropagation();reveal(error.field||$('mcp-args'),error.message||'请修正启动参数 JSON。');}},true);
  modelFields();mcpFields();refresh();
  return {refresh,modelFields,modelSaved,mockMode:()=>$('model-provider').value==='mock',modelError:message=>status('desktop-model-feedback','保存失败：'+message+'。当前输入已保留。',true),
    modelTest(profile,value,error) {tests.set(profile.id,{signature:signature(profile),error:Boolean(error),message:error||value?.message||'测试完成'});paintTests();},
    saving:kind=>pending.has(kind),beginSave(kind){if(pending.has(kind))return false;saveState(kind,true);return true;},endSave(kind){saveState(kind,false);},
    mcpError:message=>status('desktop-mcp-feedback','保存失败：'+message+'。当前输入已保留。',true),
    mcpFields,discovery,mcpSaved(server){editServer(server,true);status('desktop-mcp-feedback','服务已保存；测试发现与授权状态分别生效。');if(lastDiscovery?.server.id===server.id)renderDiscovery(lastDiscovery.data,server);}
  };
})();
