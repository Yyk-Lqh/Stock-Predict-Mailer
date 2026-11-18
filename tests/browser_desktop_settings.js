/* Run only on browser_console_fixture.py; Mock calls and synthetic discovery only. */
(async () => {
  const $=id=>document.getElementById(id),checks=[],realFetch=window.fetch;
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<160;i++){if(fn())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timeout: '+label);};
  const set=(id,value,event='input')=>{$(id).value=value;$(id).dispatchEvent(new Event(event,{bubbles:true}));};
  const record=name=>[...$('model-list').querySelectorAll('.record')].find(node=>node.querySelector('h3').textContent.startsWith(name));
  const click=(root,title)=>[...root.querySelectorAll('button')].find(node=>node.textContent===title).click();
  const prefix='桌面配置-'+Date.now();
  try {
    assert(innerWidth>760&&window.DesktopSettings,'Desktop settings not initialized');
    document.querySelector('[data-view="settings"]').click();
    await wait(()=>!document.querySelector('[data-view-pane="settings"]').hidden,'settings view');
    const defaultBefore=settings.default_model_id,modelsBefore=profiles.length;
    $('model-new').click();set('model-name',prefix);set('model-provider','mock','change');set('model-url','not-an-endpoint');
    set('model-params','[invalid');$('model-form').requestSubmit();
    assert($('model-params').closest('details').open&&document.activeElement===$('model-params'),'Invalid JSON must reveal advanced field');
    assert(profiles.length===modelsBefore&&$('model-params').value==='[invalid','Validation lost input or saved');
    let releaseSave,saveHeld=false,saveCalls=0;
    window.fetch=async(url,options)=>{if(String(url)==='/api/models'&&options?.method==='POST'){saveCalls++;const response=await realFetch(url,options);saveHeld=true;await new Promise(resolve=>{releaseSave=resolve;});return response;}return realFetch(url,options);};
    set('model-params','{"max_tokens":512,"temperature":0.6}');$('model-form').requestSubmit();
    await wait(()=>saveHeld,'held model save');assert($('model-form').inert&&$('model-new').disabled,'Saving did not lock the editor');
    $('model-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));assert(saveCalls===1,'Duplicate submit sent a second creation request');releaseSave();
    await wait(()=>profiles.some(p=>p.name===prefix),'save Mock');const profile=profiles.find(p=>p.name===prefix),id=profile.id;
    window.fetch=realFetch;
    assert($('model-id').value===id&&settings.default_model_id===defaultBefore,'Save must retain edit identity and separate default action');
    assert($('model-url').disabled&&document.querySelector('.desktop-model-remote').hidden,'Mock must not require a remote endpoint');
    set('model-name',prefix+'-更新');$('model-form').requestSubmit();
    await wait(()=>profiles.find(p=>p.id===id)?.name===prefix+'-更新','update same model');
    assert(profiles.length===modelsBefore+1,'Repeated save created a duplicate');
    checks.push('Mock saves without remote fields; invalid JSON retains input; pending and repeated saves cannot create duplicate models');

    const modelRecord=()=>record(prefix+'-更新');click(modelRecord(),'测试连接');
    await wait(()=>modelRecord()?.textContent.includes('本页测试通过'),'actual Mock test');
    assert(settings.default_model_id===defaultBefore,'Testing changed default model');
    click(modelRecord(),'设为默认');await wait(()=>settings.default_model_id===id,'explicit default');
    assert($('desktop-saved-model').textContent.includes(prefix+'-更新'),'Saved summary not updated');
    checks.push('Mock connection test has a real per-page receipt; setting default remains an explicit separate write');

    document.querySelector('[data-panel="settings"]').click();
    assert(document.querySelectorAll('.desktop-settings-groups > button').length===5,'Settings group navigation is incomplete');
    document.querySelectorAll('.desktop-settings-groups > button')[1].click();
    assert($('role-settings').closest('details').open,'Group navigation did not reveal role settings');
    const saved=await api('settings');saved.mail.user_env='BROWSER_SMTP_USER';saved.mail.password_env='BROWSER_SMTP_PASSWORD';
    await api('settings','PUT',saved);await refresh();
    set('global-temperature','0.4');set('role-main-temperature','0.8');
    assert($('role-main-temperature').closest('.role-row').querySelector('.desktop-role-effective').textContent.includes('角色温度 0.8'),'Role temperature preview mismatch');
    assert($('desktop-settings-edits').textContent.includes('未保存修改'),'Dirty state missing');
    await refresh();assert($('role-main-temperature').value==='0.8'&&$('global-temperature').value==='0.4','Refresh discarded draft edits');
    const noTemperature=await api('models','POST',{name:prefix+' 无温度',provider:'mock',supported_parameters:['max_tokens','response_format']});
    await refresh();set('default-model',noTemperature.id,'change');
    assert($('role-main-temperature').disabled&&$('role-main-temperature').closest('.role-row').textContent.includes('模型不支持温度'),'Draft default selection did not update inherited temperature capability');
    set('default-model',id,'change');assert(!$('role-main-temperature').disabled&&$('role-main-temperature').value==='0.8','Switching supported model lost temperature draft');
    set('mail-transport','smtp','change');assert(!$('mail-host').closest('label').hidden&&$('mail-mcp-tool').closest('label').hidden,'SMTP conditional fields mismatch');
    set('mail-host','smtp.fixture.invalid');set('mail-transport','file','change');
    $('settings-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
    await wait(()=>!settingsDirty&&settings.global_temperature===0.4,'settings save');
    const after=await api('settings');assert(after.mail.user_env==='BROWSER_SMTP_USER'&&after.mail.password_env==='BROWSER_SMTP_PASSWORD'&&after.mail.host==='smtp.fixture.invalid','Complete PUT lost hidden fields');
    assert(after.agents.main.temperature===0.8,'Role override not saved');
    checks.push('Role preview, draft preservation and mail conditionals agree with a complete settings PUT preserving environment names');

    const server=await api('mcp','POST',{name:prefix+' MCP',transport:'streamable_http',url:'http://127.0.0.1:9/mcp',allowed_tools:['legacy'],effects:{legacy:'read'},allowed_resources:['fixture://kept']});
    await refresh();document.querySelector('[data-panel="mcp"]').click();editServer(server);
    const data={protocol_version:'fixture',tools:[{name:'inspect',inputSchema:{description:'<img src=x onerror=alert(1)>'}},{name:'send_mail'}],resources:[]};
    renderDiscovery(data,server);
    const row=document.querySelector('.desktop-permission-row'),check=row.querySelector('input'),effect=row.querySelector('select');
    assert(!check.checked&&effect.value==='deny','Discovered tools gained implicit permission');
    assert(!(await api('mcp')).find(item=>item.id===server.id).allowed_tools.includes('inspect'),'Discovery saved permissions');
    effect.value='read';effect.dispatchEvent(new Event('change'));check.click();
    const draft=JSON.parse($('mcp-effects').value);assert(draft.legacy==='read'&&draft.inspect==='read'&&$('mcp-tools').value.includes('inspect'),'Permission editor lost original effects');
    assert((await api('mcp')).find(item=>item.id===server.id).allowed_tools.length===1,'Permission edit autosaved');
    $('mcp-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
    await wait(()=>servers.find(item=>item.id===server.id)?.allowed_tools.includes('inspect'),'save permissions');
    const persisted=(await api('mcp')).find(item=>item.id===server.id);
    assert(persisted.effects.legacy==='read'&&persisted.effects.inspect==='read'&&persisted.allowed_resources[0]==='fixture://kept','Permission save lost existing grants/resources');
    assert(!$('discovery').querySelector('img'),'Discovery content interpreted as HTML');
    set('mcp-name',prefix+' retained draft');
    window.fetch=async(url,options)=>String(url)===`/api/mcp/${server.id}`&&options?.method==='PUT'?new Response(JSON.stringify({error:{code:'fixture',message:'合成保存失败'}}),{status:400,headers:{'Content-Type':'application/json'}}):realFetch(url,options);
    $('mcp-form').requestSubmit();await wait(()=>!$('mcp-form').inert&&$('desktop-mcp-feedback').textContent.includes('保存失败'),'persistent save failure');window.fetch=realFetch;
    assert($('mcp-name').value===prefix+' retained draft','Failed save discarded user input');
    $('mcp-new').click();assert(!document.querySelector('.desktop-permission-row'),'New form retained editable discovery for another service');
    checks.push('Synthetic discovery defaults to deny; permission edits require save and preserve unrelated grants, resources and literal schemas');

    document.querySelector('[data-panel="models"]').click();editModel(profiles.find(p=>p.id===id));set('model-provider','openai_compatible','change');
    assert($('model-price-in').required&&$('model-price-out').required&&!$('model-url').disabled,'Real service fields must be required');
    set('model-provider','mock','change');set('model-params','{"max_tokens":512}');$('model-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
    await wait(()=>profiles.find(p=>p.id===id)?.parameters.temperature===undefined,'save changed model');
    assert(modelRecord().textContent.includes('本页尚未测试当前配置'),'Changed config reused a stale test receipt');
    const retained=await api('models','POST',{name:prefix+' 隐藏连接',provider:'mock',base_url:'https://retained.fixture.invalid/v1',input_usd_per_million:0.1,output_usd_per_million:0.2});
    await refresh();editModel(retained);set('model-name',retained.name+' 更新');$('model-form').requestSubmit();
    await wait(()=>!$('model-form').inert&&profiles.find(p=>p.id===retained.id)?.name.endsWith('更新'),'preserve hidden Mock connection');
    const preserved=profiles.find(p=>p.id===retained.id);assert(preserved.base_url===retained.base_url&&preserved.input_usd_per_million===0.1&&preserved.output_usd_per_million===0.2,'Saving Mock reset previously saved hidden connection fields');
    assert(!Object.values(localStorage).some(value=>value.includes('BROWSER_SMTP_PASSWORD')),'Sensitive setting metadata entered localStorage');
    checks.push('Real-service pricing is explicit; changed model clears old test receipt; config data stays out of browser preferences');
    document.body.dataset.desktopSettingsTest=JSON.stringify({checks});
  } catch(error){document.body.dataset.desktopSettingsTest=JSON.stringify({checks,error:error.stack});}
  finally{window.fetch=realFetch;}
})();
