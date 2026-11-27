/* Run with gstack browse eval on the disposable fixture with --mock-delay 2. Run again after reload. */
(() => {
  if (location.hostname !== '127.0.0.1' || !['18768', '18769', '18770'].includes(location.port)) throw Error('Use the disposable console fixture');
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function wait(test, message) {
    const deadline = Date.now() + 15000;
    do {
      const value = test();
      if (value) return value;
      await sleep(50);
    } while (Date.now() < deadline);
    throw Error(message + ' · ' + $('notice').textContent);
  }
  const mode = value => document.querySelector(`[data-desktop-mode="${value}"]`).click();
  const draft = (id, value) => { $(id).value = value; $(id).dispatchEvent(new Event('input', {bubbles:true})); };
  const task = () => { try { return JSON.parse($('task-output').textContent); } catch (_) { return null; } };
  const node = (id = 'prediction') => document.querySelector(`[data-workflow-node="${id}"]`);
  const canvas = () => $('desktop-workflow-surface').style.transform;
  const surface = name => document.querySelector(`[data-workflow-surface="${name}"]`).click();
  function debugInput() {
    surface('debug');
    node('main').click();
    [...document.querySelectorAll('#desktop-workflow-inspector button')].find(button => button.textContent === '单测所选节点').click();
    return document.querySelector('dialog.workflow-run-dialog[open]');
  }
  const submit = () => $('task-form').requestSubmit();
  const receipt = (mode, id, state) => {
    const value = task();
    return value?.metadata?.mode === mode && (!id || value.id === id) && (!state || value.status.state === state) && value;
  };
  const checkpoint = 'spm-mode-isolation-browser';
  window.modeIsolation = {state:'running'};
  (async () => {
    await wait(() => csrf && window.Workbench && document.querySelector('[data-desktop-mode="hall"]') &&
      document.body.dataset.view === 'analysis' && memoryKey, 'Control console not ready');
    const previous = JSON.parse(sessionStorage.getItem(checkpoint) || 'null');
    if (!previous) {
      mode('hall');
      await $('try-sample').onclick();
      draft('p-subject', 'STANDARD.SZ');
      draft('conversation-message', '普通草稿');
      draft('task-knowledge-query', '普通选定资料');
      draft('task-knowledge-scope', 'local');
      draft('task-recipient', 'normal@example.invalid');
      $('facts-editor').open = true;
      const model = AnalysisMode.model();
      mode('focus');
      await $('try-sample').onclick();
      const professionalModel = await api('models', 'POST', {name:'Professional Mock ' + Date.now(), provider:'mock'});
      await refresh();
      window.ComposerControls.openModels();
      [...document.querySelectorAll('#composer-popover button')].find(button => button.textContent === professionalModel.name).click();
      draft('p-subject', 'PROFESSIONAL.SZ');
      draft('conversation-message', '专业草稿');
      draft('task-knowledge-query', '专业选定资料');
      draft('task-knowledge-scope', 'private');
      assert(!$('task-recipient').value, 'Standard recipient leaked into the professional draft');
      const debug = debugInput(), raw = debug.querySelector('textarea');
      const testInput = JSON.parse(raw.value);
      testInput.prediction.subject = 'DEBUG.SZ'; testInput.context = null;
      raw.value = JSON.stringify(testInput, null, 2);
      raw.dispatchEvent(new Event('input', {bubbles:true}));
      debug.close(); surface('edit');
      node().click();
      const nodeLabel = document.querySelector('#desktop-workflow-inspector [name="label"]');
      nodeLabel.value = '独立节点草稿'; nodeLabel.dispatchEvent(new Event('input', {bubbles:true}));
      const pre = parseFloat(node().style.left);
      node().dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true, cancelable:true}));
      assert(parseFloat(node().style.left) === pre + 8, 'Professional graph edit did not apply');
      document.querySelector('[data-viewport-action="zoom-in"]').click();
      const snapshot = {model, professionalModel:professionalModel.id, x:node().style.left, viewport:canvas()};
      for (let count = 0; count < 3; count++) {
        mode('hall');
        assert($('conversation-message').value === '普通草稿' && $('facts-editor').open, 'Standard draft or expanded panel lost');
        assert($('task-knowledge-query').value === '普通选定资料' && $('task-knowledge-scope').value === 'local' &&
          $('task-recipient').value === 'normal@example.invalid' && AnalysisMode.model() === model, 'Standard model or source selection changed');
        mode('focus');
        assert($('conversation-message').value === '专业草稿' && node().style.left === snapshot.x && canvas() === snapshot.viewport,
          'Professional draft or viewport lost');
        assert($('task-knowledge-query').value === '专业选定资料' && $('task-knowledge-scope').value === 'private' && AnalysisMode.model() === snapshot.professionalModel,
          'Professional model or knowledge selection changed');
      }
      sessionStorage.setItem(checkpoint, JSON.stringify(snapshot));
      window.modeIsolation = {state:'reload', draft:true, viewport:true};
      return;
    }
    assert(AnalysisMode.active() === 'professional' && node().style.left === previous.x && canvas() === previous.viewport,
      'Professional graph or viewport missing after reload');
    assert($('conversation-message').value === '专业草稿' && AnalysisMode.model() === previous.professionalModel, 'Professional input missing on reload');
    assert(document.querySelector('#desktop-workflow-inspector [name="label"]').value === '独立节点草稿', 'Unsaved node configuration did not restore');
    const debug = debugInput();
    assert(JSON.parse(debug.querySelector('textarea').value).prediction.subject === 'DEBUG.SZ', 'Professional debug input did not restore');
    debug.close(); surface('edit');
    mode('hall');
    assert($('conversation-message').value === '普通草稿' && $('p-subject').value === 'STANDARD.SZ' && $('facts-editor').open,
      'Standard work missing on reload');
    draft('task-knowledge-query', '');
    const fetchNormally = window.fetch;
    let release, releaseProgress, standardId, heldProgress = false;
    const hold = new Promise(resolve => { release = resolve; });
    const holdProgress = new Promise(resolve => { releaseProgress = resolve; });
    window.fetch = async (url, init) => {
      if (standardId && String(url).startsWith('/api/tasks/' + standardId + '/events?') && !heldProgress) {
        heldProgress = true;
        await holdProgress;
        throw Error('stale standard progress response');
      }
      const response = await fetchNormally(url, init);
      if (url === '/api/tasks' && init?.method === 'POST' && init.headers['X-Analysis-Mode'] === 'standard' && response.ok) {
        standardId = (await response.clone().json()).id;
        await hold;
      }
      return response;
    };
    let pro;
    try {
      submit();
      await wait(() => standardId, 'Standard task did not reach the server');
      mode('focus');
      draft('task-knowledge-query', '');
      submit();
      pro = await wait(() => receipt('professional'), 'Professional run did not start during delayed standard submit');
      release();
      await wait(() => !pendingSubmissions.has('standard'), 'Delayed standard submit did not resolve');
      assert(task().id === pro.id && AnalysisMode.active() === 'professional', 'Delayed result replaced professional task');
      mode('hall');
      await wait(() => heldProgress, 'Standard task progress did not start');
      mode('focus');
      releaseProgress();
      await wait(() => receipt('professional', pro.id), 'Professional result lost during delayed standard progress');
      assert(!$('notice').textContent.includes('stale standard progress response'), 'A stale polling error surfaced in professional mode');
      mode('hall'); mode('focus'); mode('hall');
      const normal = await wait(() => receipt('standard', standardId, 'completed'), 'Standard report was not restored');
      assert(normal.artifacts[0].parts[0].data.analysis.prediction.subject === 'STANDARD.SZ', 'Wrong standard report');
      mode('focus');
      const professional = await wait(() => receipt('professional', pro.id, 'completed'), 'Professional report was not restored');
      assert(professional.artifacts[0].parts[0].data.analysis.prediction.subject === 'PROFESSIONAL.SZ', 'Wrong professional report');
      assert(professional.metadata.request.model_id === previous.professionalModel && normal.metadata.request.model_id === previous.model,
        'The server did not receive the models chosen by each mode');
      await wait(() => $('execution-events').childElementCount > 0, 'Run events not restored');
    } finally {
      release();
      releaseProgress();
      window.fetch = fetchNormally;
    }
    mode('hall');
    await wait(() => receipt('standard', standardId), 'Standard run missing');
    $('draft-clear').click();
    assert(!$('conversation-message').value && !$('p-subject').value, 'Standard reset failed');
    mode('focus');
    await wait(() => receipt('professional', pro.id), 'Professional run lost after standard reset');
    assert(canvas() === previous.viewport && AnalysisMode.model() === previous.professionalModel, 'Standard reset affected professional canvas or model');
    showView('records');
    const normalRow = await wait(() => document.querySelector(`[data-task-id="${standardId}"]`), 'Standard record missing');
    normalRow.click();
    await wait(() => receipt('standard', standardId, 'completed'), 'Global record did not open the standard mode');
    const confirm = window.confirm;
    window.confirm = () => true;
    try { await $('task-delete').onclick(); } finally { window.confirm = confirm; }
    assert(!task(), 'Standard result still displayed after deletion');
    const live = await api('tasks?order=desc&limit=100');
    assert(live.items.some(item => item.id === pro.id) && !live.items.some(item => item.id === standardId), 'Task delete crossed modes');
    mode('focus');
    await wait(() => receipt('professional', pro.id), 'Professional result lost after standard deletion');
    submit();
    const pending = await wait(() => task()?.id !== pro.id && receipt('professional'), 'Second professional run missing');
    await $('task-cancel').onclick();
    await wait(() => receipt('professional', pending.id, 'canceled'), 'Professional cancel did not apply');
    mode('hall');
    assert(!$('p-subject').value && !task(), 'Professional cancel changed standard workspace');
    const legacy = (await api('tasks?order=desc&limit=100')).items.find(item => item.metadata.mode === 'legacy');
    if (legacy) {
      await openRecord(legacy);
      assert(AnalysisMode.active() === 'legacy' && task()?.id === legacy.id && $('task-form').inert && $('task-delete').hidden,
        'Unclassified history did not remain readable');
      mode('hall');
      assert(!$('p-subject').value && !task(), 'Reading legacy history changed the standard workspace');
    }
    for (const name of ['tools', 'knowledge', 'settings']) {
      showView(name);
      assert(document.body.dataset.view === name, 'Shared navigation unavailable: ' + name);
    }
    assert(Array.isArray(await api('mcp')) && (await api('workflows/catalog')).system &&
      Array.isArray((await api('knowledge/documents')).items), 'Shared tools or knowledge API unavailable');
    showView('analysis');
    sessionStorage.removeItem(checkpoint);
    window.modeIsolation = {state:'passed', standard:standardId, professional:pro.id, canceled:pending.id};
  })().catch(error => { window.modeIsolation = {state:'failed', error:error.message, stack:error.stack}; });
  return 'Mode isolation checks started';
})()
