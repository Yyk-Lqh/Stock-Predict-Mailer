/* gstack /browse against the disposable :18852 fixture with records, forecasts and a Mock delay. */
(() => {
  if(location.origin!=='http://127.0.0.1:18852')throw Error('Use the console journey fixture');
  const el=id=>document.getElementById(id);
  const assert=(value,label)=>{if(!value)throw Error(label);};
  async function wait(check,label){
    for(let turn=0;turn<220;turn++){
      const result=check();
      if(result)return result;
      await new Promise(resolve=>setTimeout(resolve,70));
    }
    throw Error(label+' · '+el('notice').textContent);
  }
  function press(host,label){
    const control=[...host.querySelectorAll('button')].find(item=>item.textContent.trim()===label&&!item.disabled);
    assert(control,'Missing action: '+label);control.click();return control;
  }
  function set(id,value,event='input'){
    const control=el(id);control.value=value;control.dispatchEvent(new Event(event,{bubbles:true}));
  }
  const pane=name=>document.querySelector('[data-view-pane="'+name+'"]');
  const settingsPane=()=>pane('settings');
  const context=mode=>({...AnalysisMode.capture(),mode});
  const taskOutput=()=>{try{return JSON.parse(el('task-output').textContent);}catch(_){return null;}};
  const eventuallyLoaded=()=>recordLoaded&&!recordBusy;
  const recordRow=id=>el('record-list').querySelector('[data-task-id="'+id+'"]');
  const rowFor=name=>[...el('model-list').querySelectorAll('.record')].find(item=>item.querySelector('h3').textContent.includes(name));
  const setTheme=theme=>document.querySelector('[data-theme-choice="'+theme+'"]').click();
  const setup=()=>wait(()=>window.ConsoleGuide&&window.Workbench&&el('workflow-chat-nav')&&memoryKey,'Workbench did not initialize');
  async function saveSettings(){
    el('settings-form').requestSubmit();
    await wait(()=>el('settings-receipt').textContent.includes('已保存')&&!el('settings-form').querySelector('[type=submit]').disabled,'Settings save not acknowledged');
  }
  const runPrefix='验收流程 '+crypto.randomUUID().slice(0,6);
  const modelName='引导 Mock '+crypto.randomUUID().slice(0,6);
  let modelId, standardTask, professionalTask, flow;
  window.consoleJourney={
    async guide(){
      await setup();
      showView('overview');
      await wait(()=>el('guide-readiness').textContent.includes('默认模型'),'Guide readiness did not load');
      assert(el('vitals').textContent.includes('知识库')&&el('steps').textContent.includes('专业模式'),'Guide missing optional services or professional path');
      const real=window.fetch;
      window.fetch=(url,...options)=>String(url)==='/api/knowledge/queue'?Promise.resolve(new Response('{"error":{"message":"读取中断"}}',
        {status:503,headers:{'Content-Type':'application/json'}})):real(url,...options);
      try{await window.ConsoleGuide.load();assert(!el('guide-retry').hidden&&el('vitals').textContent.includes('暂未读取'),'Guide did not expose retry');}
      finally{window.fetch=real;}
      el('guide-retry').click();
      await wait(()=>el('guide-retry').hidden,'Guide retry did not recover');
      return 'guide loaded';
    },
    async model(){
      press(el('steps'),'模型服务');
      assert(!pane('settings').hidden&&!el('models').hidden,'Guide model route not active');
      el('model-new').click();set('model-name',modelName);
      assert(el('model-url').disabled&&el('model-key').disabled,'Mock form exposed remote requirements');
      el('model-form').requestSubmit();
      const row=await wait(()=>rowFor(modelName),'Saved model missing');
      modelId=profiles.find(p=>p.name===modelName).id;
      press(row,'测试连接');
      await wait(()=>rowFor(modelName).textContent.includes('本页测试通过'),'Real Mock test receipt missing');
      return 'model saved then tested';
    },
    async collaboration(){
      press(settingsPane(),'协作与邮箱');
      set('default-model',modelId,'change');
      await saveSettings();
      assert((await api('settings')).default_model_id===modelId,'Settings did not make model default');
      press(el('settings-form'),'邮件与授权');
      set('mail-transport','smtp','change');
      assert(!el('mail-host').closest('label').hidden&&el('mail-mcp-tool').closest('label').hidden,'SMTP fields not scoped');
      set('mail-host','smtp.fixture.invalid');set('mail-allowlist','invalid-fixture');
      el('settings-form').requestSubmit();
      assert(el('mail-allowlist').getAttribute('aria-invalid')==='true','Invalid recipient not located');
      set('mail-allowlist','qa@example.invalid');
      const real=window.fetch;
      window.fetch=(url,...options)=>String(url)==='/api/settings'&&options[0]?.method==='PUT'?Promise.resolve(new Response(
        '{"error":{"message":"测试保存失败"}}',{status:503,headers:{'Content-Type':'application/json'}})):real(url,...options);
      try{
        el('settings-form').requestSubmit();
        await wait(()=>el('settings-receipt').textContent.includes('保存失败'),'Setting failure not shown');
        assert(el('mail-host').value==='smtp.fixture.invalid'&&settingsDirty,'Failed save discarded changes');
      }finally{window.fetch=real;}
      await saveSettings();
      assert((await api('settings')).mail.host==='smtp.fixture.invalid','SMTP form was not saved');
      const tool=await api('mcp','POST',{name:'测试邮件工具',transport:'streamable_http',url:'http://127.0.0.1:9/mcp',
        allowed_tools:['send_mail'],effects:{send_mail:'email'}});
      await refresh();
      set('mail-transport','mcp','change');set('mail-mcp-server',tool.id,'change');set('mail-mcp-tool','send_mail');
      assert(el('mail-host').closest('label').hidden&&!el('mail-mcp-tool').closest('label').hidden,'MCP fields not scoped');
      await saveSettings();
      assert((await api('settings')).mail.mcp_tool==='send_mail','MCP config was not saved');
      set('mail-transport','file','change');
      if(!el('mail-synthetic').checked)el('mail-synthetic').click();
      await saveSettings();
      assert((await api('settings')).mail.transport==='file','File simulation was not selected');
      scrollTo(0,0);
      return 'SMTP and MCP config saved, file simulation selected';
    },
    async appearance(){
      press(settingsPane(),'界面');
      for(const theme of ['dark','light','system']){
        setTheme(theme);assert(document.documentElement.dataset.themeMode===theme,'Theme did not apply: '+theme);
      }
      setTheme('dark');
      assert(el('theme-effective').textContent.includes('深色'),'Resolved theme not shown');
      return 'three choices applied, dark stored';
    },
    async example(){
      await window.DesktopWorkbench.setMode('hall');
      showView('analysis');
      const previous=await Workbench.newAnalysis();
      set('conversation-message','保留此普通模式草稿');
      showView('overview');
      await wait(()=>el('guide-readiness').textContent.includes(modelName),'Guide did not show saved defaults');
      const realConfirm=window.confirm;window.confirm=()=>true;
      try{el('try-sample').click();await wait(()=>$('p-subject').value==='DEMO.SZ'&&el('conversation-id').value!==previous,'Sample did not open a separate conversation');}
      finally{window.confirm=realConfirm;}
      assert(AnalysisMode.read(draftKey(previous),'standard').message==='保留此普通模式草稿','Sample overwrote previous draft');
      set('conversation-message','使用引导流程验收');
      el('task-notify').checked=true;
      set('task-recipient','qa@example.invalid');
      el('analysis-send').click();
      const task=await wait(()=>taskOutput()?.status.state==='completed'&&taskOutput(),'Sample analysis did not complete');
      standardTask=task.id;
      assert(task.artifacts[0].parts[0].data.mail?.status==='simulated','File simulation receipt missing');
      return {standardTask};
    },
    async professional(){
      const node=(id,type,config)=>({id,position:{x:80,y:80},data:{type,label:id,config}});
      const graph={version:2,nodes:[
        node('start','input',{fields:[]}),node('reply','output',{source:'start.message',format:'text'}),
      ],edges:[{source:'start',target:'reply'}]};
      flow=await api('workflows/definitions','POST',{name:runPrefix,graph},undefined,context('professional'));
      showView('overview');
      press(el('steps'),'打开流程对话');
      await wait(()=>!el('workflow-chat').hidden,'Guide did not open flow chat');
      el('workflow-chat-choose').click();
      const item=await wait(()=>[...document.querySelectorAll('dialog[open] .wfchat-choice')].find(row=>row.textContent.includes(runPrefix)),'Saved flow missing from chooser');
      item.click();set('workflow-chat-message','专业任务验收');
      el('workflow-chat-form').requestSubmit();
      const run=await wait(()=>el('workflow-chat-messages').querySelector('.wfchat-output')?.closest('.wfchat-run'),'Professional flow output missing');
      professionalTask=run.dataset.run;
      return {professionalTask};
    },
    async records(){
      showView('records');window.DesktopRecords.selectTab('tasks');
      await wait(eventuallyLoaded,'Tasks did not load');
      set('record-mode','professional','change');set('record-query',runPrefix);
      (await wait(()=>recordRow(professionalTask),'Professional match missing')).click();
      await wait(()=>el('record-detail').querySelector('.record-events li'),'Professional execution events missing');
      assert(el('record-detail').textContent.includes(flow.revision)&&el('record-detail').textContent.includes('专业任务验收'),'Stored flow output/version missing');
      press(el('record-detail'),'返回任务列表');
      assert(el('record-query').value===runPrefix&&el('record-mode').value==='professional','Returning reset filters');
      set('record-mode','standard','change');set('record-query','DEMO.SZ');
      await wait(()=>recordRow(standardTask),'Standard record missing after filtering');
      return 'two modes and detail return verified';
    },
    async detail(){
      recordRow(standardTask).click();
      await wait(()=>el('record-detail').querySelector('.record-events li')&&el('record-detail').textContent.includes('模拟投递'),'Standard execution and mail receipt missing');
      press(el('record-detail'),'查看报告与证据');
      const frame=await wait(()=>document.querySelector('dialog[open] iframe'),'Report frame missing');
      assert(frame.srcdoc.includes('DEMO.SZ'),'Wrong report body');
      frame.closest('dialog').close();
      return 'source report is readable';
    },
    async recordActions(){
      press(el('record-detail'),'返回任务列表');
      set('record-mode','all','change');set('record-query','');
      await wait(eventuallyLoaded,'First page did not reset');
      const before=records.length;
      assert(recordCursor!=null,'Missing first-page cursor');
      await loadRecords();assert(records.length>before,'Second page did not load');
      const count=records.length, query=el('record-query').value, realFetch=window.fetch;
      window.fetch=(url,...options)=>String(url).startsWith('/api/tasks/records?')?Promise.resolve(new Response(
        JSON.stringify({error:{code:'FIXTURE',message:'读取中断'}}),{status:503,headers:{'Content-Type':'application/json'}})):realFetch(url,...options);
      try{
        await loadRecords(true);
        assert(records.length===count&&el('record-query').value===query&&el('desktop-record-feedback').dataset.state==='failed','Failure discarded loaded records or filters');
      }finally{window.fetch=realFetch;}
      await loadRecords(true);
      assert(records.length>=count&&el('desktop-record-feedback').dataset.state==='ready','Refresh did not recover');
      const {id:conversation_id}=await api('conversations','POST',{},undefined,context('standard'));
      const active=await api('tasks','POST',{...sample(),conversation_id,model_id:modelId,message:'取消测试'},undefined,context('standard'));
      await loadRecords(true);
      (await wait(()=>recordRow(active.id),'Active task missing')).click();
      press(el('record-detail'),'取消运行');
      await wait(()=>el('record-detail').querySelector('.tag')?.textContent==='已取消','Cancel response not rendered');
      const realConfirm=window.confirm;let confirmed=0;window.confirm=()=>{confirmed++;return true;};
      try{
        await new Promise(resolve=>setTimeout(resolve,700));
        press(el('record-detail'),'删除记录');
        await wait(()=>el('record-detail').hidden,'Delete did not close task details');
      }finally{window.confirm=realConfirm;}
      assert(confirmed===1&&!records.some(item=>item.id===active.id),'Delete did not use one confirmation and actual result');
      set('record-mode','standard','change');set('record-query','DEMO.SZ');
      await wait(eventuallyLoaded,'Task filter not restored after actions');
      return 'pagination, failure recovery, cancellation and deletion verified';
    },
    async forecast(){
      window.DesktopRecords.selectTab('forecasts');
      set('forecast-state','due','change');
      await wait(()=>!el('forecast-refresh').disabled,'Archive list did not load');
      const path='tasks/browser-due/forecast';
      const {record}=await api(path);
      for(let page=0;page<8&&!el('forecast-list').querySelector('[data-forecast="'+record.forecast_id+'"]');page++){
        assert(!el('forecast-more').hidden,'No more archive pages');
        await window.ForecastUI.load();
      }
      const row=await wait(()=>el('forecast-list').querySelector('[data-forecast="'+record.forecast_id+'"]'),'Due archive not found');
      press(row,'查看预测详情');
      await wait(()=>el('observation-content'),'Observation form missing');
      document.querySelector('.observation-preview').open=true;
      const d=record.definition;
      set('observation-content',JSON.stringify({schema_version:'1',subject:record.prediction.subject,
        metric:d.metric,unit:d.unit,value:112,observed_at:d.target_at,available_at:d.target_at,source:'隔离工作区测试观测',synthetic:true}));
      el('observation-preview').click();
      await wait(()=>el('observation-save'),'Verified preview did not permit explicit save');
      assert((await api(path)).evaluations.length===0,'Preview wrote a receipt');
      el('observation-save').click();
      await wait(()=>[...el('forecast-detail').querySelectorAll('.forecast-receipt')].some(
        item=>item.textContent.includes('绝对误差：2 CNY')),'Saved receipt did not display');
      assert((await api(path)).state==='evaluated','Archive state was not updated');
      press(el('forecast-detail'),'返回预测列表');
      window.DesktopRecords.selectTab('tasks');
      assert(el('record-mode').value==='standard'&&el('record-query').value==='DEMO.SZ','Archive tab lost task filter state');
      return 'observation validated, previewed and explicitly saved';
    },
    async narrow(){
      await setup();
      assert(innerWidth===390&&document.documentElement.dataset.themeMode==='dark','Responsive view or theme restore missing');
      for(const name of ['overview','settings','records']){
        showView(name);assert(!pane(name).hidden&&document.documentElement.scrollWidth<=innerWidth,'Overflow on '+name);
      }
      showView('settings');press(settingsPane(),'协作与邮箱');press(el('settings-form'),'邮件与授权');
      assert(!el('mail-allowlist').closest('details').hidden&&el('mail-allowlist').closest('details').open,'Mobile settings group could not open');
      return 'three narrow pages and persisted dark theme verified';
    },
  };
})();
