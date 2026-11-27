/* gstack browser acceptance using a disposable console with --mock-delay 4. */
(() => {
  if (location.hostname !== '127.0.0.1' || location.port !== '18773') throw Error('Use the workflow chat fixture');
  const assert = (value, message) => { if (!value) throw Error(message); };
  const ui = suffix => $('workflow-chat-' + suffix);
  const wait = async (check, message) => {
    const deadline = Date.now() + 22000;
    do {
      const value = check();
      if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 70));
    } while (Date.now() < deadline);
    throw Error(message + ' · ' + (ui('feedback')?.textContent || ''));
  };
  const context = () => ({...AnalysisMode.capture(), mode:'professional'});
  const req = (path, method = 'GET', body) => api('workflows/definitions' + path, method, body, undefined, context());
  const input = (node, value) => { node.value = value; node.dispatchEvent(new Event('input', {bubbles:true})); };
  const dialog = () => document.querySelector('dialog.workflow-chat-dialog[open]');
  const click = (host,label) => {
    const button = [...host.querySelectorAll('button')].find(node => node.textContent === label && !node.disabled);
    assert(button, 'Missing action ' + label);
    button.click();
  };
  const choose = async name => {
    ui('choose').click();
    const row = await wait(() => [...(dialog()?.querySelectorAll('.wfchat-choice') || [])].find(node => node.querySelector('strong').textContent === name),
      'Missing flow ' + name);
    row.click();
    await wait(() => ui('title').textContent === name, 'Selected flow did not appear');
  };
  const stage = async (name, extra) => {
    window.workflowChatQA = {stage:name, ...extra};
    await wait(() => window.workflowChatContinue === name, 'Browser verification gate timed out: ' + name);
  };
  const last = () => ui('messages').querySelector('.wfchat-run:last-child');
  const id = () => last()?.dataset.run;
  const status = () => last()?.querySelector('.wfchat-run-head strong')?.textContent;
  const trace = step => last()?.querySelector('details[data-step="' + step + '"]');
  const send = () => ui('form').requestSubmit();
  const see = async run => {
    const row = await wait(() => [...ui('history').querySelectorAll('button')].find(node => node.dataset.run === run), 'History row missing');
    row.click();
    await wait(() => id() === run && trace('report'), 'Historical events were not restored');
  };
  const key = 'workflow-chat-qa';
  window.workflowChatQA = {stage:'starting'};
  (async () => {
    await wait(() => ui('nav') && memoryKey && document.body.dataset.view === 'analysis', 'Workbench did not mount');
    const reset = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (reset) {
      await wait(() => ! $('workflow-chat').hidden && ui('title').textContent === reset.name && id() === reset.running,
        'Refresh did not restore selected flow and run');
      await wait(() => status() === '已完成' && trace('report'), 'Restored run did not complete');
      input(ui('message'),'刷新后保留这条待办');
      await see(reset.old);
      assert(ui('messages').textContent.includes(reset.version) && ui('messages').textContent.includes(reset.prompt),
        'Original execution version or input missing');
      assert(ui('form').hidden && !last().textContent.includes('取消运行'), 'History was not read-only');
      await stage('history', {run:reset.old});
      click(last(), '打开报告');
      await wait(() => dialog()?.querySelector('iframe')?.srcdoc.includes('DEMO.SZ'), 'Report renderer did not open');
      dialog().close();
      ui('live').click();
      assert(ui('message').value === '刷新后保留这条待办', 'Returning from history lost the draft');
      window.DesktopWorkbench.setMode('hall');
      await wait(() => $('workflow-chat').hidden && $('conversation-message').value === '普通模式独立问题', 'Standard draft did not restore');
      window.DesktopWorkbench.setMode('focus');
      await wait(() => !$('workflow-chat').hidden && ui('title').textContent === reset.name, 'Professional surface did not restore');
      assert(ui('message').value === '刷新后保留这条待办', 'Changing mode lost workflow chat draft');
      sessionStorage.removeItem(key);
      window.workflowChatNarrow = async () => {
        await wait(() => innerWidth <= 780 && !ui('aside').open, 'Narrow panel did not collapse');
        assert(ui('send').getBoundingClientRect().bottom <= innerHeight && !ui('send').disabled, 'Narrow composer is inaccessible');
        ui('aside').querySelector('summary').click();
        click(ui('definition'),'查看流程');
        assert(dialog()?.querySelector('.wfchat-graph-list'), 'Narrow flow viewer did not open');
        dialog().close();
        await see(reset.old);
        click(last(), '打开报告');
        await wait(() => dialog()?.querySelector('iframe')?.srcdoc.includes('DEMO.SZ'), 'Narrow report did not open');
        dialog().close(); ui('live').click();
        assert(ui('message').value === '刷新后保留这条待办', 'Narrow history lost the composer draft');
        send();
        await wait(() => id() !== reset.running && status() === '运行中', 'Narrow composer did not submit');
        return {viewport:innerWidth, sent:id(), flow:true, history:true, report:true};
      };
      window.workflowChatQA = {stage:'ready-narrow', run:reset.old};
      return;
    }

    window.DesktopWorkbench.setMode('hall');
    input($('conversation-message'),'普通模式独立问题');
    window.DesktopWorkbench.setMode('focus');
    const model = await api('models', 'POST', {name:'Mock Workflow Chat', provider:'mock'});
    await api('settings', 'PUT', {...settings, default_model_id:model.id});
    await refresh();
    $('workspace-health').textContent = '模型已配置';
    AnalysisMode.write('model', model.id, 'professional');
    const graph = (withTool = false) => {
      const items = [
        ['input','input','读取预测资料',{}], ['validate','validation','核验预测与事实',{}],
        ...(withTool ? [['audit','tool','盘点事实来源',{tool:'facts_audit', required:true}]] : []),
        ['main','analysis',withTool ? '聚焦证据复核' : '生成风险分析',{}], ['report','report','生成分析报告',{}]];
      return {version:2,nodes:items.map(([id,type,label,config], i) =>
        ({id, position:{x:40+(i%3)*246, y:110+Math.floor(i/3)*230}, data:{type,label,config}})),
      edges:items.slice(1).map(([target], index) => ({source:items[index][0],target,condition:'always'}))};
    };
    const a = await req('', 'POST', {name:'预测风险核对', description:'核验上游预测与客观事实，生成可回看的风险报告。',
      graph:graph(), inputs:{prediction:true,context:false,constraints:true}, model_id:model.id});
    const b = await req('', 'POST', {name:'资料来源复核', description:'先盘点有来源的事实，再汇总核对结果。',
      graph:graph(true), inputs:{prediction:true,context:false}, model_id:model.id});
    const prompt = '核对这份预测的主要风险，说明哪些结论有资料支持。';
    const data = sample();
    const fill = (facts = true) => {
      input(ui('message'),prompt);
      input(ui('input-prediction'), JSON.stringify(data.prediction));
      input(ui('input-context'), facts ? JSON.stringify(data.context) : '');
    };
    applyTheme('dark', false);
    ui('nav').click();
    await choose(a.name);
    fill();
    send();
    await wait(() => ui('feedback').textContent.includes('分析约束'), 'Required input was not validated');
    assert(ui('message').value === prompt && !id(), 'Validation lost the draft or created a run');
    input(ui('input-constraints'),'优先核对有时间和来源的事实');
    ui('inputs').open = false;
    await stage('conversation', {flow:a.id});
    send(); send();
    await wait(() => status() === '运行中' && trace('main')?.closest('[data-state="running"]'), 'A did not start');
    const first = id();
    await stage('running', {run:first});
    await choose(b.name);
    assert(!ui('history').querySelector('[data-run="'+first+'"]'), 'A appeared in B history');
    fill(); send();
    await wait(() => status() === '已完成' && trace('audit'), 'B did not run its distinct graph');
    const other = id();
    assert(other !== first && !trace('main')?.textContent.includes('生成风险分析'), 'B used A graph');
    await choose(a.name);
    await wait(() => id() === first && trace('report') && status() === '已完成', 'A was not restored');
    assert(!trace('audit'), 'B nodes appeared in A');
    assert((await req('/'+a.id+'/runs')).items.length === 1, 'Double-click created a second run');

    await choose(b.name);
    fill(false); send();
    await wait(() => id() !== other && status() === '失败' && trace('audit'), 'Failed node did not reach the timeline');
    const failed = id();
    assert(last().textContent.includes('没有已校验事实'), 'Failure reason missing');
    await choose(a.name);
    click(ui('definition'), '画布编辑');
    await wait(() => $('workflow-chat').hidden && document.querySelector('[data-workflow-node="main"]'), 'Canvas edit did not open');
    document.querySelector('[data-workflow-node="main"]').click();
    input(document.querySelector('#desktop-workflow-inspector [name="label"]'), '新版风险分析');
    click($('desktop-workflow-inspector'), '保存节点');
    $('desktop-workflow-save').click();
    await wait(() => $('desktop-workflow-message').textContent.includes('已保存流程版本'), 'Canvas did not publish a revision');
    ui('nav').click();
    await wait(() => ui('definition').textContent.includes('可运行版本') && !ui('definition').textContent.includes(a.revision.slice(0,10)),
      'Published revision did not update the sidebar');
    await see(first);
    assert(trace('main').textContent.includes('生成风险分析'), 'Old run graph was overwritten by the edit');
    ui('live').click();

    const realFetch = window.fetch;
    let interrupted = null;
    window.fetch = async (url, options) => {
      const response = await realFetch(url, options);
      if (typeof url === 'string' && url.endsWith('/'+a.id+'/runs') && options?.method === 'POST' && response.ok && !interrupted) {
        interrupted = (await response.clone().json()).id;
        throw TypeError('模拟提交回执中断');
      }
      return response;
    };
    fill(); send();
    await wait(() => interrupted && !ui('resume').hidden, 'Interrupted submission was not recoverable');
    assert(ui('message').value === prompt, 'Interrupted submission cleared the draft');
    window.fetch = realFetch;
    ui('resume').click();
    await wait(() => id() === interrupted && status() === '运行中', 'Replayed request did not recover the same task');
    let lateRead = false, releaseLate;
    const delayRead = new Promise(resolve => { releaseLate = resolve; });
    window.fetch = async (url, options) => {
      const response = await realFetch(url, options);
      if (String(url).includes('/'+interrupted+'/events?') && !lateRead) { lateRead = true; await delayRead; }
      return response;
    };
    await wait(() => lateRead, 'Live event read did not start');
    await choose(b.name); releaseLate();
    await wait(() => id() === failed, 'B did not restore its own view');
    assert(!ui('messages').querySelector('[data-run="'+interrupted+'"]'), 'Late A event changed B');
    window.fetch = realFetch;
    await choose(a.name);
    click(last(),'取消运行');
    await wait(() => status() === '已取消', 'Cancel did not reach terminal state');
    click(last(),'重试此版本');
    await wait(() => id() !== interrupted && status() === '运行中', 'Retry did not create a new running task');
    const running = id();
    assert((await req('/'+a.id+'/runs')).items.length === 3, 'Submission replay duplicated a run');
    sessionStorage.setItem(key, JSON.stringify({name:a.name, old:first, running, version:a.revision.slice(0,10), prompt}));
    window.workflowChatQA = {stage:'reload', running};
  })().catch(error => { window.workflowChatQA = {stage:'failed', error:error.message, stack:error.stack}; });
  return 'Workflow chat checks started';
})()
