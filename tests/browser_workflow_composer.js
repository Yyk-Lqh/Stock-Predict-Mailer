/* Run with gstack browse eval on the disposable console at 127.0.0.1:18793. */
(() => {
  if (location.origin !== 'http://127.0.0.1:18793') throw Error('Use the disposable workflow composer console');
  const ui = suffix => $('workflow-chat-' + suffix);
  const check = (assertion, message) => { if (!assertion) throw Error(message); };
  const wait = async (read, message) => {
    for (let attempt = 0; attempt < 180; attempt++) {
      const value = read();
      if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 45));
    }
    throw Error(message + ' · ' + (ui('feedback')?.textContent || ''));
  };
  const fill = (node, value) => { node.value = value; node.dispatchEvent(new Event('input', {bubbles:true})); };
  const find = (root, selector, name) => [...root.querySelectorAll(selector)].find(node => node.textContent === name);
  const choose = async name => {
    ui('choose').click();
    const option = await wait(() => find(document, '.wfchat-choice strong', name), 'Missing flow ' + name);
    option.closest('button').click();
    await wait(() => ui('title').textContent === name && !ui('send').disabled, 'Flow did not become runnable');
  };
  const compactToolbar = () => {
    const buttons = [...ui('form').querySelectorAll('.composer-tools-right button')];
    check(!ui('effort') && !ui('options'), 'Model or effort controls are still mounted');
    check(buttons.map(button => button.id).join(',') === 'workflow-chat-voice,workflow-chat-send',
      'Voice and send controls were not preserved');
  };
  const saved = 'workflow-composer-qa';
  window.workflowComposerQA = {stage:'starting'};
  (async () => {
    await wait(() => ui('nav') && memoryKey, 'Composer did not mount');
    if (sessionStorage.getItem(saved)) {
      await wait(() => !$('workflow-chat').hidden && ui('title').textContent === '系统分析流程', 'Flow did not restore');
      await wait(() => ui('message').value === '刷新后继续核对', 'Draft did not restore');
      compactToolbar();
      const narrow = () => {
        const form = ui('form').getBoundingClientRect(), send = ui('send').getBoundingClientRect();
        check(form.left >= 0 && form.right <= innerWidth && send.right <= form.right && send.bottom <= innerHeight,
          'Narrow toolbar overflowed the viewport');
        compactToolbar();
        return {width:innerWidth, sendVisible:true};
      };
      window.workflowComposerNarrow = narrow;
      window.workflowComposerQA = {stage:'restored'};
      sessionStorage.removeItem(saved);
      return;
    }
    const defaultModel = await api('models', 'POST', {name:'基础分析', provider:'mock'});
    const otherModel = await api('models', 'POST', {name:'离线复核', provider:'mock'});
    await api('settings', 'PUT', {...settings, default_model_id:defaultModel.id, default_reasoning_effort:'extreme'});
    await refresh();
    applyTheme('dark', true);
    window.DesktopWorkbench.setMode('hall');
    AnalysisMode.write('model', defaultModel.id);
    fill($('conversation-message'), '普通模式保留草稿');
    window.DesktopWorkbench.setMode('focus');
    AnalysisMode.write('model', otherModel.id, 'professional');
    ui('nav').click();
    await choose('系统分析流程');
    compactToolbar();
    const context = AnalysisMode.capture(), endpoint = 'workflows/definitions';
    const kinds = ['input','validation','analysis','report'];
    const graph = {version:2, nodes:kinds.map(type => ({id:type, data:{type, label:type, config:{}}})),
      edges:kinds.slice(1).map((target,index) => ({source:kinds[index],target,condition:'always'}))};
    const second = await api(endpoint, 'POST', {name:'轻量复核', graph}, undefined, context);
    fill(ui('message'), '对照预测，核对主要风险与来源。');
    const prepare = () => fill(ui('input-prediction'), JSON.stringify(sample().prediction));
    prepare();
    await choose(second.name);
    compactToolbar();
    await choose('系统分析流程');
    check(ui('message').value.startsWith('对照预测'), 'Switching flows lost composer state');
    ui('form').requestSubmit();
    const run = await wait(() => ui('messages').querySelector('[data-run]')?.dataset.run, 'Run did not appear');
    const detail = await api(endpoint + '/system/runs/' + run, 'GET', undefined, undefined, context);
    check(detail.choices.model_id === otherModel.id && detail.choices.reasoning_effort === 'extreme', 'Run did not use existing workflow settings');
    await wait(() => ui('messages').textContent.includes('报告已生成'), 'Run did not produce a report');
    window.DesktopWorkbench.setMode('hall');
    await wait(() => $('conversation-message').value === '普通模式保留草稿', 'Professional changes affected standard draft');
    check(AnalysisMode.model() === defaultModel.id, 'Professional model leaked into standard mode');
    $('composer-effort').click();
    const standardSlider = $('composer-popover').querySelector('input[type=range]');
    check(standardSlider?.getAttribute('aria-valuetext') === '极高', 'Professional effort leaked into standard mode');
    standardSlider.dispatchEvent(new KeyboardEvent('keydown', {key:'Home', bubbles:true}));
    check($('task-effort').value === 'light', 'Standard slider no longer updates its form');
    window.ComposerControls.close();
    window.DesktopWorkbench.setMode('focus');
    await wait(() => !$('workflow-chat').hidden, 'Professional chat did not restore');
    compactToolbar();
    fill(ui('message'), '刷新后继续核对');
    sessionStorage.setItem(saved, '1');
    window.workflowComposerQA = {stage:'reload', run};
  })().catch(error => { window.workflowComposerQA = {stage:'failed', error:error.message, stack:error.stack}; });
  return 'Workflow composer checks started';
})()
