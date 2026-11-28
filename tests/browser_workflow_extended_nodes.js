/* gstack browse acceptance on a disposable console with the GET target demo_QUOTES. */
(() => {
  const wait = async (predicate, message) => {
    for (let i=0; i<150; i++) {
      const value=predicate();
      if(value)return value;
      await new Promise(resolve=>setTimeout(resolve,80));
    }
    throw Error(message);
  };
  const assert=(condition,message)=>{if(!condition)throw Error(message);};
  const button=(root,label)=>[...root.querySelectorAll('button')].find(el=>el.textContent.trim()===label&&!el.hidden&&!el.disabled);
  const press=(root,label)=>{
    const el=button(root,label);assert(el,'Missing action: '+label);el.click();
  };
  const set=(field,value)=>{assert(field,'Missing field for '+value);field.value=value;field.dispatchEvent(new Event('input',{bubbles:true}));};
  const config=()=>$('desktop-node-config');
  const field=(label,host=config())=>[...host.querySelectorAll('label')].find(el=>[...el.childNodes]
    .some(child=>child.nodeType===Node.TEXT_NODE&&child.textContent.trim()===label))?.querySelector('input, select, textarea');
  const graph=()=>DesktopWorkbench.canvasSnapshot().graph;
  const node=kind=>graph().nodes.find(item=>item.data.type===kind);
  const card=id=>document.querySelector(`[data-workflow-node="${id}"]`);
  const library=()=>$('workflow-node-library');
  const input=prefix=>$('workflow-chat-'+prefix);
  const pick=kind=>{
    const row=library().querySelector(`[data-node-type="${kind}"]:not(:disabled):not([hidden])`);
    assert(row,'Node not available: '+kind);row.click();
    assert(node(kind),'Node not added to the canvas: '+kind);return node(kind);
  };
  const add=(from,kind)=>{card(from.id).querySelector('.out[data-port="value"]').click();return pick(kind);};
  const save=()=>press(config(),'保存节点');
  const runName='计算与复核验收';
  const latest=()=>input('messages').querySelector('.wfchat-run:last-child');
  const waiting=()=>latest()?.querySelector('.workflow-human-action');
  const open=async()=>{
    await wait(()=>memoryKey&&$('workflow-canvas-nav'),'Console did not initialize');
    if(sessionStorage.getItem('extended-workflow-await-reload')) {
      await wait(waiting,'Pending human approval did not restore after refresh');
      window.extendedWorkflowQA={phase:'waiting_restored'};
      return;
    }
    DesktopWorkbench.setMode('focus');$('workflow-canvas-nav').click();
    await wait(()=>$('wfcat-new')&&!$('wfcat-new').closest('.workflow-catalog').hidden,'Canvas directory did not open');
    $('wfcat-new').click();
    await wait(()=>$('workflow-canvas-empty')&&!$('workflow-canvas-empty').hidden,'New canvas did not open');
    $('workflow-canvas-empty').click();
    await wait(()=>library().querySelector('[data-node-type="input"]:not(:disabled)'),'Node library did not initialize');
    for(const kind of ['iteration','code','loop','human','http']) {
      assert(library().querySelector(`[data-node-type="${kind}"]:not(:disabled)`),kind+' was not available');
    }
    const start=pick('input');
    press(config(),'添加字段');set(field('变量名'),'items');set(field('值类型'),'list');set(field('默认值（JSON，可留空）'),'[2,3]');save();
    const iter=add(start,'iteration');set(field('上游变量'),start.id+'.items');set(field('逐项计算'),'item * 2');save();
    const code=add(iter,'code');set(field('上游变量'),iter.id+'.value');set(field('计算表达式'),'value[0] + value[1]');
    set(field('输出类型'),'number');save();
    const loop=add(code,'loop');set(field('上游变量'),code.id+'.value');set(field('更新状态'),'state + 1');
    set(field('停止条件（布尔值）'),'state >= 12');save();
    const human=add(loop,'human');set(field('处理说明'),'请填写复核人后继续。');press(config(),'添加字段');
    set(field('变量名'),'reviewer');set(field('显示名称或说明'),'复核人');save();
    const http=add(human,'http');set(field('授权目标'),'demo_QUOTES');save();
    const template=add(http,'template');
    set(field('模板'),`计算结果 {{${loop.id}.value}}，复核人 {{${human.id}.reviewer}}，行情 {{${http.id}.value}}`);save();
    add(template,'output');set(field('上游变量'),template.id+'.value');save();
    assert(graph().edges.length===7,'Connections were not persisted on the draft');
    $('desktop-workflow-save').click();
    const dialog=await wait(()=>document.querySelector('dialog.workflow-chat-dialog[open]'),'Save dialog did not open');
    set(dialog.querySelector('[name=name]'),runName);dialog.querySelector('form').requestSubmit();
    const entry=await wait(()=>[...document.querySelectorAll('.wfcat-card')].find(el=>el.textContent.includes(runName)),'Flow was not saved');
    press(entry,'在对话中使用');
    await wait(()=>input('title').textContent===runName&&!input('send').disabled,'Saved flow did not open in chat');
    set(input('message'),'确认计算并读取测试行情');input('form').requestSubmit();
    const form=await wait(waiting,'Human input form did not appear');
    assert(form.textContent.includes('请填写复核人')&&latest().textContent.includes('等待用户处理'),'Approval is missing from the timeline');
    assert(!field('复核人',form).validity.valid,'Missing required value did not fail form validation');
    sessionStorage.setItem('extended-workflow-await-reload','1');
    window.extendedWorkflowQA={phase:'waiting'};
  };
  window.resumeExtendedWorkflow=async()=>{
    const form=await wait(waiting,'Human input unavailable');
    set(field('复核人',form),'浏览器复核');form.requestSubmit();
    const output=await wait(()=>latest()?.querySelector('.wfchat-output'),'Resumed run did not return an output');
    assert(output.textContent.includes('计算结果 12，复核人 浏览器复核，行情 {"quote": 27}'),output.textContent);
    assert(latest().querySelectorAll('.wfchat-step[data-state="completed"]').length===8,'Not all eight nodes completed');
    sessionStorage.removeItem('extended-workflow-await-reload');
    return {phase:'completed',output:output.textContent};
  };
  window.extendedWorkflowQA={phase:'starting'};
  open().catch(error=>{window.extendedWorkflowQA={phase:'failed',error:error.stack};});
})();
