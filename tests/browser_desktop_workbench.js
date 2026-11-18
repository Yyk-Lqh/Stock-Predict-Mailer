/* Run via gstack browse only against tests/browser_console_fixture.py. */
(async () => {
  const $ = id => document.getElementById(id), checks = [];
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async (fn, label) => {
    for (let index = 0; index < 150; index++) {
      if (fn()) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw Error('Timeout: ' + label);
  };
  const set = (id, value) => {
    $(id).value = value;
    $(id).dispatchEvent(new Event('input', {bubbles: true}));
    $(id).dispatchEvent(new Event('change', {bubbles: true}));
  };
  assert(innerWidth > 760, 'Use desktop viewport');
  await wait(() => $('desktop-workflow') && $('workspace-health').textContent !== '正在连接', 'boot');
  $('new-analysis').click();
  await wait(() => $('conversation-id').value && !$('new-analysis').disabled, 'new conversation');
  assert($('desktop-result').disabled, 'Fresh workspace must not offer a report');
  const configured = $('desktop-model').dataset.state === 'ready';
  $('desktop-model').click();
  if (configured) {
    assert(!$('composer-popover').hidden && $('composer-popover').textContent.includes('选择模型'), 'Configured model must open selector');
    window.ComposerControls.close();
  } else assert(document.body.dataset.view === 'settings' && document.activeElement.id === 'model-name', 'Missing model must lead to editable configuration');
  document.querySelector('[data-view="analysis"]').click();
  checks.push('missing model leads to configuration; no fabricated report');

  document.querySelector('[data-desktop-mode="hall"]').click();
  assert(!document.querySelector('.office-stage').inert && getComputedStyle(document.querySelector('.market-wall')).display !== 'none', 'Hall must remain interactive');
  assert(localStorage.getItem('stock_predict_mailer.desktop.view.v1') === 'hall', 'Hall preference not saved');
  document.querySelector('[data-desktop-mode="focus"]').click();
  assert(document.querySelector('.office-stage').inert && getComputedStyle(document.querySelector('.market-wall')).display === 'none', 'Hidden hall must not remain interactive');
  checks.push('view choice persists and hidden scene has no interactive targets');

  $('desktop-data').focus(); $('desktop-data').click();
  assert($('prediction-editor').open && document.activeElement.id === 'p-subject', 'Data entry must open and focus required fields');
  assert(document.querySelector('.inspector-head h2').textContent === '分析资料', 'Incorrect input panel title');
  $('report-close').click();
  assert(document.activeElement.id === 'desktop-data', 'Close must return focus to visible data entry');
  checks.push('one-click required fields, contextual title and focus return');

  set('conversation-message', '桌面优化验收：核对风险，保留我的问题。');
  $('desktop-sample').click();
  await wait(() => !$('desktop-sample').disabled && $('task-data').value.includes('console-mock'), 'sample');
  assert($('conversation-message').value.includes('保留我的问题'), 'Preparing sample lost question');
  assert($('desktop-model').dataset.state === 'ready' && $('desktop-data').dataset.state === 'ready', 'Preparation state not refreshed');
  assert($('desktop-result').disabled, 'Preparing sample must not submit a task');
  checks.push('sample configures mock and data, preserves question and does not submit');

  set('p-valid-until', '2020-01-01T12:00');
  assert($('desktop-data').dataset.state === 'expired', 'Expired input presented as ready');
  $('analysis-send').click();
  await wait(() => $('p-valid-until').getAttribute('aria-invalid') === 'true', 'expired field');
  assert($('conversation-message').value.includes('保留我的问题') && $('desktop-result').disabled, 'Rejected submission lost draft or created task');
  set('p-valid-until', localDate(new Date(Date.now() + 86400000)));
  assert($('desktop-data').dataset.state === 'ready', 'Corrected input did not become ready');
  checks.push('expired input remains actionable and rejected submission preserves draft');

  $('analysis-send').click();
  await wait(() => $('result-summary').textContent.includes('报告已生成'), 'first report');
  await wait(() => $('desktop-result-value').textContent.includes('报告'), 'result action');
  assert($('desktop-title').textContent.includes('DEMO.SZ'), 'Follow-up input lost carried prediction summary');
  $('desktop-result').click();
  assert(!$('analysis-pane-report').hidden && document.querySelector('.inspector-head h2').textContent === '报告与证据', 'Report not reachable from workflow');
  assert($('report').textContent.length > 100, 'No actual rendered report');
  $('report-close').click();
  set('conversation-message', '继续分析风险，沿用这份预测。');
  $('analysis-send').click();
  await wait(() => $('conversation-turns').children.length === 2 && $('result-summary').textContent.includes('报告已生成'), 'followup');
  assert(!$('task-notify').checked, 'Followup inherited email authorization');
  checks.push('real mock report and followup reachable, prediction retained, email opt-in off');
  $('report-close').click();
  assert(getComputedStyle($('conversation-thread')).display === 'none', 'History must not crowd the composer by default');
  $('desktop-history').click();
  assert(getComputedStyle($('conversation-thread')).display !== 'none' && $('conversation-turns').textContent.includes('沿用这份预测'), 'Conversation history not reachable');
  $('desktop-history').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
  assert($('desktop-history').getAttribute('aria-expanded') === 'false', 'Escape must close history');
  checks.push('conversation history is accessible without crowding the input');

  const raw = $('task-data').value;
  $('task-data').value = '{'; window.AnalysisInput.update();
  assert($('desktop-data').dataset.state === 'invalid', 'Malformed JSON presented as ready');
  $('desktop-data').click();
  assert(document.activeElement.id === 'task-data' && !$('task-data').closest('details').hidden, 'Malformed JSON action must locate editor');
  $('task-data').value = raw; window.AnalysisInput.update();
  $('report-close').click();
  assert(document.documentElement.scrollWidth <= innerWidth, 'Desktop horizontal overflow');
  checks.push('malformed JSON locates original editor; no document horizontal overflow');
  document.body.dataset.desktopCheck = JSON.stringify({checks});

  function localDate(value) {
    const pad = number => String(number).padStart(2, '0');
    return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
  }
})().catch(error => { document.body.dataset.desktopCheck = JSON.stringify({error: error.message}); });
