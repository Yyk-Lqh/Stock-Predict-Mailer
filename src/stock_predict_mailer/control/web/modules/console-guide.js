/* The guide shows the same configuration, tasks and entry points as the console. */
window.ConsoleGuide = (() => {
  let request = 0, owner, loading = false, configError, knowledge, taskError, tasks = [];
  const model = () => profiles.find(profile => profile.id === settings?.default_model_id);
  const modelReady = () => Boolean(model()?.enabled && modelConfigured(model()));
  const configured = () => Boolean(settings && !configError);
  const guideVisible = () => document.body.dataset.view === 'overview';
  const normal = () => window.DesktopWorkbench.setMode('hall');
  const route = (view, panel) => { showView(view); if(panel)showPanel(panel); };
  function modelSettings() {
    const selected=model();
    if(selected?.enabled&&!modelConfigured(selected)){route('settings','models');editModel(selected);}
    else if(profiles.some(profile=>profile.enabled&&modelConfigured(profile))) {
      route('settings','settings');window.DesktopSettings.focusGroup('默认模型与生成参数');
    } else route('settings','models');
  }
  function records(tab='tasks') { showView('records');window.DesktopRecords.selectTab(tab); }
  async function professional(chat) {
    await window.DesktopWorkbench.setMode('focus',{read:false});
    if(!guideVisible()||AnalysisMode.active()!=='professional')return;
    showView('analysis');
    if(chat)$('workflow-chat-nav').click();else window.WorkflowChat.showDirectory();
  }
  function draftReady() {
    const active=AnalysisMode.active()==='standard';
    const cid=active?$('conversation-id').value:AnalysisMode.read('position','standard')?.conversation;
    const draft=active?draftSnapshot():AnalysisMode.read(draftKey(cid || ''),'standard');
    return {existing:Boolean(draft?.form?.['p-subject']||draft?.message||draft?.constraints||draft?.facts?.length),
      prediction:Boolean(draft?.form?.['p-subject']&&Date.parse(draft.form['p-valid-until'])>Date.now())};
  }
  function render() {
    if(owner!==memoryKey){owner=memoryKey;tasks=[];knowledge=null;taskError=null;}
    const defaultModel=model(), ready=configured()&&modelReady();
    $('guide-readiness').textContent=ready?`可开始分析 · 默认模型 ${defaultModel.name}`:configured()
      ? defaultModel?(defaultModel.enabled?'默认模型缺少报价，请补全模型配置。':'默认模型已停用，请选择已启用的模型。'):'先选择默认模型，再开始分析。'
      : loading?'正在读取运行配置…':'运行配置暂未读取。';
    $('guide-retry').hidden=!(configError||taskError||knowledge?.error);
    $('start-analysis').textContent=configured()&&!ready?'配置分析模型':'开始一次分析';
    const draft=draftReady(), latest=tasks[0], finished=tasks.find(task=>task.status.state==='completed');
    const pro=tasks.find(task=>taskMode(task)==='professional');
    const taskLine=latest?`${taskBrief(latest).subject || latest.metadata?.workflow?.flow?.name || '分析任务'} · ${TASK_STATE[latest.status.state]||latest.status.state} · ${shortTime(latest.status.timestamp)}`
      : taskError?'任务状态暂未读取。':loading?'正在读取任务状态…':'提交后，在任务详情查看进度、报告、证据与失败原因。';
    const steps=[
      ['检查运行配置', ready?'默认模型可用。知识库、工具和邮件可按需配置。':'启用模型并在协作与邮箱选择默认模型。', ready,
        [['模型服务',()=>route('settings','models')],['协作与邮箱',()=>{route('settings','settings');window.DesktopSettings.focusGroup('默认模型与生成参数');}]]],
      ['在普通模式提供预测与问题',draft.prediction?'预测草稿已就绪，可以继续补充问题或约束。':'填写或导入上游预测，再输入问题与约束。示例使用合成数据。',draft.prediction,
        [[draft.existing?'继续普通模式草稿':'打开分析工作台',async()=>{await normal();if(guideVisible())showView('analysis');}]]],
      ['在专业模式编排并运行流程',pro?'已有专业模式运行记录。':'在画布新建或打开流程，保存并校验后，在流程对话中选择该流程并提交。',Boolean(pro),
        [['打开画布',()=>professional(false)],['打开流程对话',()=>professional(true)]]],
      ['查看执行与结果',taskLine,Boolean(finished),
        [['任务记录',()=>records()],...(latest?[['查看最近任务',()=>window.DesktopRecords.openDetail(latest)]]:[]),
          ['预测归档',()=>records('forecasts')],['邮件设置',()=>{route('settings','settings');window.DesktopSettings.focusGroup('邮件与授权');}]]],
    ];
    $('steps-count').textContent=`${steps.filter(step=>step[2]).length} / ${steps.length} 已完成`;
    const host=$('steps'); host.replaceChildren();
    steps.forEach(([title,detail,done,actions], index)=>{
      const row=document.createElement('li');host.append(row);
      if(done)row.dataset.done='true';
      text(row,'span',done?'✓':String(index+1),'mark').setAttribute('aria-hidden','true');
      const body=text(row,'div','','body');text(body,'b',title);text(body,'span',detail,'meta');
      const links=text(row,'div','','go actions');
      for(const [label,callback]of actions)links.append(action(label,callback));
    });
    const tools=servers.reduce((total,item)=>total+(item.enabled===false?0:item.allowed_tools.length),0);
    const mail=settings?.mail;
    const mailLabel={file:'本地文件模拟',smtp:'SMTP',mcp:'MCP 邮件工具'}[mail?.transport];
    const vitals=$('vitals');vitals.replaceChildren();
    const unavailable=loading?'正在读取…':'暂未读取';
    for(const [title,value,type,callback]of [
      ['默认模型',configured()?(defaultModel?defaultModel.name+(defaultModel.enabled?' · 已启用':' · 已停用'):'未选择'):unavailable,'必需',modelSettings],
      ['知识库',knowledge?.data?`${knowledge.data.counts.ready||0} 份可检索 · ${knowledge.data.waiting||0} 份待处理`:unavailable,'可选',()=>route('knowledge')],
      ['工具中心',configured()?`${tools} 个已授权工具`:unavailable,'可选',()=>route('tools')],
      ['邮件',configured()?`${mailLabel} · ${mail.recipient_allowlist.length} 个授权地址`:unavailable,'可选',
        ()=>{route('settings','settings');window.DesktopSettings.focusGroup('邮件与授权');}],
    ]){
      const row=text(vitals,'div','','vital');
      text(row,'span',title,'label');text(row,'span',value,'value');
      const cell=text(row,'div',type,'flag');cell.append(action('打开',callback));
      cell.lastChild.setAttribute('aria-label','打开'+title);
    }
  }
  async function load() {
    const generation=++request, context=AnalysisMode.capture();
    loading=true;render();
    const [config,recent,kb]=await Promise.allSettled([
      refresh(),api('tasks?order=desc&limit=30','GET',undefined,undefined,{key:context.key}),
      api('knowledge/queue','GET',undefined,undefined,{key:context.key,knowledgeScope:window.KnowledgeUI?.scope()||'local'}),
    ]);
    if(generation!==request||context.key!==memoryKey)return;
    loading=false;configError=config.status==='rejected';taskError=recent.status==='rejected';
    if(!taskError)tasks=recent.value.items.filter(topLevel);
    knowledge=kb.status==='fulfilled'?{data:kb.value}:{error:true};
    if(guideVisible())render();
  }
  $('guide-retry').onclick=load;
  $('start-analysis').onclick=async()=>{
    if(configured()&&!modelReady())return modelSettings();
    await normal();if(guideVisible())showView('analysis');
  };
  $('try-sample').onclick=async()=>{
    const button=$('try-sample');
    if(draftReady().existing&&!confirm('保留当前普通模式草稿，并另开一个示例会话？'))return;
    button.disabled=true;
    try{
      await normal();
      if(!guideVisible()||AnalysisMode.active()!=='standard')return;
      const scope=AnalysisMode.capture();
      const preferred=model();
      let mock=preferred?.enabled&&preferred.provider==='mock'?preferred:profiles.find(profile=>profile.enabled&&profile.provider==='mock');
      if(!mock){mock=await api('models','POST',{name:'Mock 分析模型',provider:'mock'});await refresh();}
      if(!guideVisible()||!AnalysisMode.current(scope))return;
      const cid=await window.Workbench.newAnalysis();
      if(!cid||!AnalysisMode.current(scope)||$('conversation-id').value!==cid)return;
      AnalysisMode.write('model',mock.id);
      applySample();window.AnalysisInput?.update();draftSchedule();
      notice('已准备合成预测和 Mock 模型。提交后查看进度与报告。');
    }catch(error){notice(error.message,true);}
    finally{button.disabled=false;}
  };
  return {load,render,task(value){
    if(owner!==memoryKey)return;
    tasks=[value,...tasks.filter(task=>task.id!==value.id)];
    if(guideVisible())render();
  }};
})();
