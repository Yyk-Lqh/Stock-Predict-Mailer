/* Configuration guidance and effective values over the existing settings form. */
window.DesktopSettings = (() => {
  const tests = new Map();
  const pending = new Set();
  const make = (tag, value, cls) => { const node=document.createElement(tag); if(value!=null)node.textContent=value; if(cls)node.className=cls; return node; };
  const button = (label, callback, cls='btn tiny') => { const node=make('button',label,cls); node.type='button'; node.onclick=callback; return node; };
  const status = (id,message,error=false) => { $(id).textContent=message; $(id).classList.toggle('error-text',error); };
  const feedback = (id,parent) => { const node=make('p',null,'hint desktop-config-feedback'); node.id=id; node.setAttribute('role','status'); parent.prepend(node); return node; };
  const label = id => $(id).closest('label');
  const signature = p => p.config_revision || JSON.stringify(p);
  const overview=make('section',null,'desktop-settings-overview'); overview.setAttribute('aria-label','已保存配置');
  overview.append(make('h2','已保存配置'));
  const summary=make('dl',null,'desktop-config-summary');
  for(const [id,title] of [['model','默认模型'],['mail','邮件通道']]) { const row=make('div'); row.append(make('dt',title)); const value=make('dd'); value.id='desktop-saved-'+id; row.append(value); summary.append(row); }
  overview.append(summary); $('settings').prepend(overview);

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

  function reveal(field,message) {
    for(let parent=field.parentElement;parent;parent=parent.parentElement) { if(parent.tagName==='DETAILS')parent.open=true; if(parent.dataset.desktopConditional)parent.hidden=false; }
    field.setAttribute('aria-invalid','true'); field.focus(); field.scrollIntoView({block:'center'});
    if(message)status('desktop-model-feedback',message,true);
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
    const saved=profiles.find(profile=>profile.id===$('model-id').value);
    $('model-key').placeholder=saved?.has_secret?'已配置，留空保留，输入可替换':'尚未配置';
    status('desktop-model-feedback',mock?'Mock 离线模拟，无需远程地址、密钥或报价。保存后仍需单独设为默认。':'填写远程连接与手动报价；保存后可按需测试，再设为默认。');
  }
  function paintTests() {
    for(const [index,node] of [...$('model-list').querySelectorAll('.record')].entries()) {
      node.querySelector('.desktop-model-test-state')?.remove();
      const profile=profiles[index]; if(!profile)continue;
      const cached=tests.get(profile.id), valid=cached?.signature===signature(profile);
      node.append(make('p',valid?`${cached.error?'本页测试失败':'本页测试通过'} · ${cached.at} · ${cached.message}`:'本页尚未测试当前配置。','hint desktop-model-test-state'));
    }
  }
  function modelSaved(profile) {
    tests.delete(profile.id); editModel(profile,true); advanced.open=false;
    status('desktop-model-feedback','模型已保存；继续保存会更新同一配置。测试与设为默认可在模型列表单独操作。');
  }

  const groups=[...$('settings-form').querySelectorAll(':scope > details')];
  if(groups.length)groups[0].open=true;
  const nav=make('nav',null,'desktop-settings-groups'); nav.setAttribute('aria-label','协作设置分组');
  function focusGroup(title){
    const group=groups.find(item=>item.querySelector('summary').textContent===title);
    if(!group)return;
    group.open=true;group.scrollIntoView({block:'start'});
    group.querySelector('input:not(:disabled):not([type="hidden"]),select:not(:disabled)')?.focus({preventScroll:true});
  }
  for(const group of groups){const title=group.querySelector('summary').textContent;nav.append(button(title,()=>focusGroup(title)));}
  const edits=make('p',null,'hint'); edits.id='desktop-settings-edits'; edits.setAttribute('role','status'); nav.append(edits); $('settings-form').prepend(nav);
  const draft=make('div',null,'desktop-settings-draft'); draft.append(make('h3','当前表单预览'),make('p','修改后需保存才生效；运行上限还需以具体任务回执为准。','hint')); const draftText=make('p'); draftText.id='desktop-settings-draft-values'; draft.append(draftText); nav.after(draft);
  const mailFields=[['smtp',['mail-host','mail-port','mail-tls']],['mcp',['mail-mcp-server','mail-mcp-tool']]];
  for(const [type,ids]of mailFields)for(const id of ids)label(id).dataset.desktopConditional=type;
  function edited(event){
    event.target.removeAttribute('aria-invalid');
    event.target.closest('label')?.querySelector('.settings-field-error')?.remove();preview();
  }
  $('settings-form').addEventListener('input',edited); $('settings-form').addEventListener('change',edited);
  $('settings-form').addEventListener('invalid',event=>{if(event.target.closest('details'))event.target.closest('details').open=true;},true);
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
      const remote=endpoints.find(item=>item.id===endpoint.value);
      row.append(make('p',`${select.value?'角色指定':'继承默认'} · ${chosen?.name||'未选择模型'}${chosen&&!chosen.enabled?'（已停用）':''} · ${temperature} · ${remote?remote.name+(remote.enabled?'':'（已停用）'):'本机运行'}`,'hint desktop-role-effective'));
    }
    for(const[type,ids]of mailFields)for(const id of ids) {
      const inactive=$('mail-transport').value!==type;
      label(id).hidden=$(id).disabled=inactive;
    }
    $('mail-smtp-note').hidden=$('mail-transport').value!=='smtp';
    $('mail-channel-note').textContent={file:'本地文件模拟会生成投递回执。',smtp:'使用服务端配置的 SMTP 凭据。',mcp:'请选择已授权为邮件投递的 MCP 工具。'}[$('mail-transport').value];
  }
  function refresh() {
    if(!settings)return;
    const model=profiles.find(p=>p.id===settings.default_model_id);
    $('desktop-saved-model').textContent=model?`${model.name} · ${model.enabled?'已启用':'已停用'}${model.provider==='mock'?' · 离线模拟':''}`:'尚未选择默认模型';
    $('desktop-saved-mail').textContent=`${{file:'本地文件模拟，不代表邮箱收到',smtp:'SMTP，尚需按投递回执核对',mcp:'MCP 邮件工具，仍须逐轮授权'}[settings.mail.transport]} · ${settings.mail.recipient_allowlist.length} 个清单地址`;
    paintTests(); preview();
  }

  function saveState(kind,active) {
    const editor=$(kind+'-form');editor.inert=active;editor.setAttribute('aria-busy',String(active));
    editor.querySelector('button[type="submit"]').disabled=active;$(kind+'-new').disabled=active;
    if(active)pending.add(kind);else pending.delete(kind);
  }
  modelFields();refresh();
  return {refresh,modelFields,modelSaved,focusGroup,mockMode:()=>$('model-provider').value==='mock',modelError:message=>status('desktop-model-feedback','保存失败：'+message+'。当前输入已保留。',true),
    modelTest(profile,value,error) {
      if(value?.config_revision!=null&&value.config_revision!==profile.config_revision)return;
      tests.set(profile.id,{signature:signature(profile),error:Boolean(error),message:error||value?.message||'测试完成',at:fmt(new Date())});paintTests();
    },
    settingsIssue(field,message){
      if(!field){status('settings-receipt',message,true);return;}
      const container=field.closest('label');
      container?.querySelector('.settings-field-error')?.remove();
      container?.append(make('small',message,'settings-field-error error-text'));
      reveal(field);status('settings-receipt',message,true);
    },
    settingsSaved(message,error=false){status('settings-receipt',message,error);},
    saving:kind=>pending.has(kind),beginSave(kind){if(pending.has(kind))return false;saveState(kind,true);return true;},endSave(kind){saveState(kind,false);}
  };
})();
