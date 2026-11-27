/* Full node-inspector inventory on a disposable gstack console. */
(() => {
  if(location.hostname!=='127.0.0.1' || location.port!=='18797')throw Error('Use the inspector fixture');
  const assert=(valid,message)=>{if(!valid)throw Error(message);};
  const wait=async (check,message)=>{
    for(let index=0;index<200;index++) {
      const value=check();
      if(value)return value;
      await new Promise(resolve=>setTimeout(resolve,70));
    }
    throw Error(message);
  };
  const config=()=>$('desktop-node-config');
  const click=(node)=>{assert(node,'Missing action');node.click();};
  const set=(input,value)=>{
    assert(input,'Missing input');input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));
  };
  const card=id=>document.querySelector('[data-workflow-node="'+CSS.escape(id)+'"]');
  const select=id=>click(card(id));
  const node=(id,type,config,index)=>({id,position:{x:46+(index%4)*258,y:70+Math.floor(index/4)*176},
    data:{label:id==='legacy-model'?'旧版风控模型':WorkflowNodeUI.label(type)||type,type,config}});
  const edge=(source,target,output='value')=>({source,target,output});
  const load=(id,nodes,edges)=>{
    DesktopWorkbench.useDefinition({id,revision:'fixture',name:'配置面板验收',mode:'custom',graph:{version:2,nodes,edges}});
    WorkflowChat.showCanvas();
  };
  const press=(name,host=config())=>click([...host.querySelectorAll('button')].find(button=>button.textContent.trim()===name));
  const stage=async name=>{
    window.inspectorQA={stage:name};
    await wait(()=>window.inspectorContinue===name,'Screenshot timed out: '+name);
  };
  const legacySpecs={
    input:[{},'任务表单'],validation:[{},'任务契约'],forecast:[{},'预测归档'],
    knowledge:[{},'私有知识库'],retrieval:[{binding:'expired:context'},'授权 MCP 工具'],
    analysis:[{instruction:'核对证据',tools:['expired:context']},'授权工具'],merge:[{},'分析模型'],
    chart:[{},'渲染插件'],report:[{},'渲染插件'],delivery:[{},'邮件策略'],
    database:[{source:'tasks',query:'recent',scope:'same',limit:8},'数据来源'],tool:[{tool:'facts_audit'},'选择工具'],
    human:[{prompt:'核对来源'},'此类型保留在草稿中'],iteration:[{},'此类型保留在草稿中'],
    loop:[{},'此类型保留在草稿中'],code:[{},'此类型保留在草稿中'],http:[{},'此类型保留在草稿中'],
    model:[{label:'历史配置'},'旧版配置'],trained:[{},'模型版本'],review:[{},'风险复核'],
    custom:[{},'自定义'],archived_extension:[{label:'扩展参数'},'旧版配置']
  };
  const typedSpecs={
    input:[{fields:[{name:'items',type:'list',required:false,default:[1,2]}]},'items · 列表'],
    classifier:[{source:'input.message',fallback:true,cases:[{id:'value_case',label:'行情',match:'行情'}]},'分类出口'],
    branch:[{source:'input.message',fallback:true,cases:[{id:'value_case',label:'匹配项',operation:'equals',match:'内容'}]},'条件出口'],
    template:[{template:'{{input.message}}'},'插入上游变量'],
    aggregate:[{sources:['input.items'],empty:'omit'},'聚合来源'],
    assign:[{source:'input.message',name:'result',value_type:'text'},'目标变量名'],
    extract:[{source:'input.message',fields:[]},'添加字段'],
    document:[{source:'input.message'},'已处理的知识库文件'],
    knowledge:[{source:'input.message',limit:4},'检索条数'],
    list:[{source:'input.items',operation:'slice',start:0,end:5},'切片结束索引'],
    llm:[{template:'分析 {{input.message}}',format:'text'},'提示词'],
    output:[{source:'llm.value',format:'text'},'返回设置']
  };
  const inventory=(specs,nodes,displayed)=>{
    for(const item of nodes) {
      select(item.id);
      assert($('desktop-workflow-inspector').dataset.node===item.id,'Missing node: '+item.id);
      assert($('desktop-node-icon').textContent,'Missing icon: '+item.id);
      assert($('desktop-node-description').getAttribute('form')==='workflow-node-editor','Description is detached');
      assert($('workflow-node-config-tab').getAttribute('aria-selected')==='true','Settings tab changed');
      assert(config().textContent.includes(specs[item.data.type][1]),'Missing configuration: '+item.data.type);
      assert($('desktop-node-close').getClientRects().length,'Missing close control');
      displayed.add(item.data.type);
    }
  };
  window.inspectorQA={stage:'starting'};
  (async()=>{
    await wait(()=>memoryKey&&window.WorkflowChat&&$('workflow-canvas-nav'),'Console startup timed out');
    await wait(()=>document.querySelector('[data-node-type="report"]:not(:disabled)'),'Node catalog did not initialize');
    applyTheme('light',false);
    DesktopWorkbench.setMode('focus');
    const legacyNodes=Object.entries(legacySpecs).map(([type,[cfg]],index)=>{
      const item=node(type==='model'?'legacy-model':type,type,cfg,index);
      if(type==='model') item.data.legacy={name:'只读历史参数',lookback:30};
      if(type==='trained') item.data.modelVersion='old-2025';
      return item;
    });
    const displayed=new Set();
    load('inspector-legacy',legacyNodes,[edge('input','analysis')]);
    inventory(legacySpecs,legacyNodes,displayed);
    select('analysis');
    assert(config().querySelector('[name="agent_tools"]').selectedOptions[0].textContent.includes('已失去授权'),
      'Inactive tool selection was not labeled');
    assert(!config().querySelector('[name="required"]').getClientRects().length,'Agent exposed an unrelated tool option');
    click($('desktop-node-close'));
    assert($('desktop-workflow-inspector').hidden,'Closing did not hide the drawer');
    select('analysis');await stage('agent');
    const analysis=(await api('workflows/catalog')).system;
    analysis.nodes.find(item=>item.data.type==='retrieval').data.config.binding='expired:context';
    load('inspector-expired',analysis.nodes,analysis.edges);
    press('校验计划',$('desktop-focus'));
    await wait(()=>$('desktop-workflow-message').textContent.includes('未获此 MCP 工具授权'),'Revoked authorization was accepted');
    assert(document.activeElement===config().querySelector('[name="binding"]'),'Tool authorization error did not locate the binding');
    const typedNodes=Object.entries(typedSpecs).map(([type,[cfg]],index)=>node(type,type,cfg,index));
    const edges=[...typedNodes.slice(1).filter(item=>item.id!=='output').map(item=>edge('input',item.id)),edge('llm','output')];
    DesktopWorkbench.useDefinition(null,{empty:true});WorkflowChat.showCanvas();
    const files=new DataTransfer(), picker=$('desktop-workflow-file');
    files.items.add(new File([JSON.stringify({version:2,mode:'custom',nodes:typedNodes,edges})],'inspector.json',{type:'application/json'}));
    picker.files=files.files;picker.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>card('llm'),'Typed node fixture did not import');
    inventory(typedSpecs,typedNodes,displayed);
    select('llm');await stage('llm');
    set(config().querySelector('[data-config-key="template"]'),'长提示词\n'+('分析 {{input.message}}\n'.repeat(70)));
    set($('desktop-node-description'),'未保存的模型说明');
    select('input');
    config().querySelector('details.workflow-config-row').open=true;
    const malformed='[1,';
    set(config().querySelector('[data-config-key="default"]'),malformed);
    press('保存节点');
    assert(document.activeElement===config().querySelector('[data-config-key="default"]'),'Malformed JSON field did not receive focus');
    select('llm');
    assert($('desktop-node-description').value==='未保存的模型说明','Description draft leaked');
    assert(config().querySelector('textarea').value.includes('长提示词'),'Prompt draft lost across node switch');
    $('workflow-node-config-tab').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
    await wait(()=>$('desktop-node-runtime').textContent.includes('此节点尚无运行记录'),'Empty state did not appear');
    $('workflow-node-runtime-tab').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
    assert(config().querySelector('textarea').value.includes('长提示词'),'Prompt draft lost across tab switch');
    DesktopWorkbench.setMode('hall');DesktopWorkbench.setMode('focus');WorkflowChat.showCanvas();
    select('input');
    assert(config().querySelector('[data-config-key="default"]').value===malformed,'Invalid draft lost across modes');
    set(config().querySelector('[data-config-key="default"]'),'[1, 2]');
    config().querySelector('details.workflow-config-row').open=true;
    await stage('input');
    const next=[...config().querySelectorAll('.workflow-next-node')].find(button=>button.textContent.includes('LLM'));
    click(next);
    assert($('desktop-workflow-inspector').dataset.node==='llm','Downstream navigation did not select the connected node');
    window.inspectorQA={stage:'passed',types:[...displayed],count:displayed.size};
  })().catch(error=>{window.inspectorQA={stage:'failed',message:error.message,stack:error.stack,config:config()?.textContent.slice(0,800)};});
  return 'Node settings inventory started';
})()
