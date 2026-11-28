/* gstack browse acceptance using a disposable console at 127.0.0.1:18851. */
(() => {
  if (location.origin !== 'http://127.0.0.1:18851') throw Error('Use the workflow revisions fixture');
  const stateKey = 'workflow-revisions-refresh';
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async (check, message) => {
    for (let index = 0; index < 180; index++) {
      const result = check();
      if (result) return result;
      await new Promise(resolve => setTimeout(resolve, 60));
    }
    throw Error(message);
  };
  const dialog = () => document.querySelector('dialog.workflow-chat-dialog[open]');
  const card = name => [...document.querySelectorAll('.wfcat-card')].find(row => row.querySelector('h3')?.textContent === name);
  const press = (host, label) => {
    const control = [...host.querySelectorAll('button')].find(row => row.textContent.startsWith(label) && !row.disabled);
    assert(control, 'Missing action: ' + label);
    control.click();
  };
  const req = (url, method = 'GET', body) => api('workflows/definitions' + url, method, body, undefined,
    {...AnalysisMode.capture(), mode:'professional'});
  function graph(marker, edited = false) {
    const middle = edited ? 'audit' : 'archive';
    const nodes = [
      ['start', 'input', '用户输入', {fields:[]}],
      ['template', 'template', marker, {template:marker + ' {{start.message}}'}],
      [middle, 'template', edited ? '新版核查' : '原版归档', {template:'{{template.value}}'}],
      ['reply', 'output', '输出', {source:middle + '.value', format:'text'}],
    ];
    return {
      version:2,
      nodes:nodes.map(([id, type, label, config], index) => ({
        id, position:{x:50+230*index, y:edited && id === 'template' ? 120 : 80}, data:{type, label, config},
      })),
      edges:[{source:'start', target:'template'}, {source:'template', target:middle}, {source:middle, target:'reply'}],
      ...(!edited ? {canvas:{notes:[{id:'note', x:20, y:20, width:260, height:150, font:16, color:'green', body:'原版说明'}]}} : {}),
    };
  }
  const seeRevision = async (revision, label) => {
    const layer = dialog();
    const prefix = '版本 · ' + revision.slice(0,8);
    await wait(() => [...layer.querySelectorAll('button')].find(row => row.textContent.startsWith(prefix)), 'Missing prior revision');
    press(layer, prefix);
    await wait(() => layer.querySelector('.wfchat-graph-list')?.textContent.includes(label), 'Version preview missing');
    return layer;
  };
  async function compare(layer, message) {
    const details = layer.querySelector('.wfcat-revision-diff');
    assert(details, 'Historical version comparison missing');
    details.querySelector('summary').click();
    await wait(() => details.textContent.includes(message), 'Comparison result missing: ' + message);
    return details;
  }

  window.workflowRevisionsQA = {phase:'starting'};
  async function run() {
    await wait(() => memoryKey && window.WorkflowChat && $('workflow-canvas-nav'), 'Console did not initialize');
    const previous = JSON.parse(sessionStorage.getItem(stateKey) || 'null');
    const name = previous?.name || '风险核对流程 ' + crypto.randomUUID().slice(0, 4);
    const laterName = name + ' · 第二版';
    if (previous) {
      const entry = await wait(() => !document.querySelector('.workflow-catalog').hidden && card(name), 'Restored card did not survive refresh');
      press(entry, '版本记录');
      const layer = await seeRevision(previous.source, '原版摘要');
      const bounds = layer.getBoundingClientRect();
      assert(bounds.left >= 0 && bounds.right <= innerWidth, 'Revision dialog overflowed the viewport');
      assert(layer.textContent.includes('恢复自 ' + previous.source.slice(0,8)), 'Current revision attribution missing');
      await compare(layer, '流程内容一致');
      sessionStorage.removeItem(stateKey);
      window.workflowRevisionsQA = {phase:'passed-refresh', viewport:innerWidth};
      return;
    }

    DesktopWorkbench.setMode('focus');
    const source = await req('', 'POST', {name, graph:graph('原版摘要'), description:'保留原始报告口径'});
    const submitted = await req('/' + source.id + '/runs', 'POST', {
      revision:source.revision, key:crypto.randomUUID(), message:'核对测试样本', parameters:{},
    });
    const update = (base, label) => req('/' + source.id, 'PUT', {
      name:laterName, graph:graph(label, true), base_revision:base.revision, description:'更新报告口径',
    });
    const current = await update(source, '第二版摘要');
    $('workflow-canvas-nav').click();
    let entry = await wait(() => card(laterName), 'Updated flow missing from directory');
    press(entry, '版本记录');
    let layer = dialog();
    const oldLabel = '版本 · ' + source.revision.slice(0, 8);
    await wait(() => layer.textContent.includes(oldLabel), 'Version listing missing');
    const fetchVersion = window.fetch;
    let release, delayed = false;
    const gate = new Promise(resolve => { release = resolve; });
    window.fetch = async (url, ...options) => {
      const response = await fetchVersion(url, ...options);
      if (String(url).endsWith('/revisions/' + source.revision)) { delayed = true; await gate; }
      return response;
    };
    try {
      press(layer, oldLabel);
      await wait(() => delayed, 'Old selection was not delayed');
      press(layer, '当前 · ');
      const preview = () => layer.querySelector('.wfchat-graph-list')?.textContent;
      await wait(() => preview()?.includes('第二版摘要'), 'Current version did not render');
      release();
      await new Promise(resolve => setTimeout(resolve, 100));
      assert(preview()?.includes('第二版摘要'), 'Late response replaced the current selection');
    } finally {
      release();
      window.fetch = fetchVersion;
    }
    layer = await seeRevision(source.revision, '原版摘要');
    const original = await compare(layer, '已保存内容的差异');
    for (const phrase of [
      '更新节点 · 第二版摘要 → 原版摘要 · 名称、配置、画布位置',
      '新增节点 · 原版归档', '移除节点 · 新版核查',
      '新增连线 · 原版归档.value → 输出.value', '移除连线 · 新版核查.value → 输出.value',
      '更新流程名称', '更新流程描述', '更新画布注释',
    ]) assert(original.textContent.includes(phrase), 'Missing revision change: ' + phrase);
    press(layer, '恢复此版本');
    await update(current, '并发更新摘要');
    press(layer, '确认恢复');
    await wait(() => layer.textContent.includes('流程已有更新'), 'Concurrent edit did not block restore');
    layer.close();
    press(entry, '版本记录');
    layer = await seeRevision(source.revision, '原版摘要');
    const currentLabel = '当前 · ';
    const restoredComparison = await compare(layer, '并发更新摘要 → 原版摘要');
    assert(!restoredComparison.textContent.includes('第二版摘要'), 'Reopening reused an outdated comparison baseline');
    press(layer, currentLabel);
    await wait(() => layer.querySelector('.wfchat-graph-list')?.textContent.includes('并发更新摘要'), 'Current preview missing');
    assert(!layer.querySelector('.wfcat-revision-diff'), 'Current version should not compare with itself');
    layer = await seeRevision(source.revision, '原版摘要');
    await compare(layer, '并发更新摘要 → 原版摘要');
    window.finishWorkflowRevisionQA = async () => {
      press(layer, '恢复此版本');
      press(layer, '确认恢复');
      entry = await wait(() => !dialog() && card(name), 'Restored card did not appear');
      assert(!card(laterName), 'Restore duplicated the workflow card');
      press(entry, '打开画布');
      await wait(() => DesktopWorkbench.canvasSnapshot().graph.nodes.some(node => node.data.label === '原版摘要'), 'Restored canvas not loaded');
      $('workflow-canvas-nav').click();
      press(card(name), '在对话中使用');
      const history = await wait(() => $('workflow-chat-history').querySelector('[data-run="' + submitted.id + '"]'), 'Original run missing');
      history.click();
      await wait(() => $('workflow-chat-messages').querySelector('.wfchat-output')?.textContent.includes('原版摘要 核对测试样本'),
        'Original output missing after restore');
      assert($('workflow-chat-messages').textContent.includes(source.revision.slice(0,8)), 'Original run version missing');
      $('workflow-canvas-nav').click();
      sessionStorage.setItem(stateKey, JSON.stringify({name, source:source.revision}));
      return {phase:'passed', originalRun:submitted.id};
    };
    window.workflowRevisionsQA = {phase:'preview', source:source.revision};
  }
  run().catch(error => { window.workflowRevisionsQA = {phase:'failed', error:error.stack}; });
})();
