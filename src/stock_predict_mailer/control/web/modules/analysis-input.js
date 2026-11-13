/* One structured request: a persistent composer and three inspector tabs. */
window.AnalysisInput = (() => {
  const form = $('task-form'), inspector = $('report-inspector'), content = $('inspector-content');
  let lastPrediction = null, mode = 'progress', composing = false;
  const tabs = document.createElement('div'); tabs.className = 'analysis-tabs'; tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '分析工作区面板');
  const panes = {};
  for (const [id, label] of [['input', '分析资料'], ['progress', '工作进度'], ['report', '报告与证据']]) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.id = 'analysis-tab-' + id; button.dataset.analysisTab = id;
    button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', 'analysis-pane-' + id); button.onclick = () => open(id);
    const pane = document.createElement('section'); pane.id = 'analysis-pane-' + id; pane.setAttribute('role', 'tabpanel'); pane.setAttribute('aria-labelledby', button.id);
    panes[id] = pane; tabs.append(button); content.append(pane);
  }
  inspector.querySelector('.inspector-head').after(tabs);
  const status = document.createElement('p'); status.id = 'analysis-data-status'; status.className = 'analysis-data-status'; status.setAttribute('role', 'status'); panes.input.append(status);
  panes.input.append(action('使用示例跑通', () => $('try-sample').click()));
  const composer = document.querySelector('.composer'), bar = document.querySelector('#task-form .submit-bar');
  const message = $('conversation-message');
  // Move existing controls rather than clone them: IDs, event handlers and values survive.
  const preferences = composer.querySelector('details');
  form.append(preferences);
  form.append($('task-data').closest('details'));
  panes.input.append(form);
  panes.progress.append($('office-progress'));
  panes.report.append($('report'), $('mail-live'));
  panes.report.append($('task-output').closest('details'));
  const dock = document.createElement('section'); dock.id = 'analysis-composer'; dock.setAttribute('aria-label', 'AI 分析对话栏');
  const controls = document.createElement('div'); controls.className = 'analysis-composer-controls';
  const data = document.createElement('button'); data.id = 'analysis-data-open'; data.type = 'button'; data.className = 'btn'; data.onclick = () => open('input');
  const session = document.createElement('span'); session.id = 'analysis-session-label'; session.className = 'hint';
  controls.append(data, session);
  const send = bar.querySelector('[type=submit]'); send.id = 'analysis-send'; send.textContent = '发送'; send.setAttribute('form', form.id);
  controls.append($('task-cancel'), send);
  dock.append($('conversation-thread'), composer, controls);
  document.querySelector('.pony-office').append(dock);
  new MutationObserver(() => { dock.inert = form.inert; }).observe(form, {attributes:true, attributeFilter:['inert']});
  bar.remove();
  // Keep a form-owned submit target for native form semantics and existing automation.
  const hiddenSubmit = document.createElement('button'); hiddenSubmit.type = 'submit'; hiddenSubmit.hidden = true; form.append(hiddenSubmit);
  message.setAttribute('form', form.id); message.rows = 2; message.placeholder = '输入你的分析问题，例如：这份预测有哪些风险？';
  message.closest('label').querySelector('span').textContent = '分析问题';
  const autoSize = () => { message.style.height = 'auto'; message.style.height = Math.min(160, Math.max(52, message.scrollHeight)) + 'px'; layout(); };
  message.addEventListener('input', () => { autoSize(); draftSchedule(); });
  message.addEventListener('compositionstart', () => { composing = true; }); message.addEventListener('compositionend', () => { composing = false; });
  message.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing && event.keyCode !== 229) { event.preventDefault(); if (!send.disabled) form.requestSubmit(send); }
  });
  function viewport() {
    const view = window.visualViewport;
    const inset = innerWidth <= 760 ? 8 : 20;
    dock.style.bottom = Math.max(0, view ? innerHeight - view.height - view.offsetTop : 0) + inset + 'px';
    window.PonyOffice?.layout();
  }
  window.visualViewport?.addEventListener('resize', viewport); window.visualViewport?.addEventListener('scroll', viewport);
  const invalid = (id, message) => {
    const field = $(id); field.setAttribute('aria-invalid', 'true'); field.setCustomValidity?.(message);
    open('input'); let parent = field.parentElement;
    while (parent && parent !== form) { if (parent.tagName === 'DETAILS') parent.open = true; parent = parent.parentElement; }
    field.focus(); field.scrollIntoView({block: 'nearest'}); field.reportValidity?.();
    throw new Error(message);
  };
  function validate() {
    form.querySelectorAll('[aria-invalid]').forEach(field => { field.removeAttribute('aria-invalid'); field.setCustomValidity?.(''); });
    let input;
    try { input = JSON.parse($('task-data').value); } catch (_) { return invalid('task-data', '原始 JSON 无法解析，请检查格式。'); }
    const prediction = input.prediction || lastPrediction;
    if (!prediction?.subject?.trim()) return invalid('p-subject', '请先填写本轮分析的标的代码。');
    if (!prediction.model_version?.trim()) return invalid('p-model-version', '请填写上游模型版本。');
    if (!(prediction.horizon?.value > 0)) return invalid('p-horizon-value', '预测周期必须大于零。');
    if (!prediction.valid_until || !(Date.parse(prediction.valid_until) > Date.now())) return invalid('p-valid-until', '预测已过期或有效期无效，请核对并更新预测。');
    if (prediction.confidence != null && !(prediction.confidence >= 0 && prediction.confidence <= 1)) return invalid('p-confidence', '置信度须在 0 到 1 之间，也可以留空。');
    for (const fact of input.context?.facts || []) if (!fact.source?.trim() || !Number.isFinite(Date.parse(fact.observed_at))) {
      $('facts-editor').open = true; open('input'); throw new Error('每条客观事实都需要来源和有效的观测时间。');
    }
    if ($('task-notify').checked && (!$('task-recipient').value.trim() || !$('task-recipient').checkValidity())) return invalid('task-recipient', $('task-recipient').multiple?'请填写有效的收件地址，多个邮箱用逗号分隔。':'请填写有效的收件地址。');
    lastPrediction = prediction;
    window.PonyOffice?.hall?.capture(input);
  }
  function update() {
    let prediction;
    try { prediction = JSON.parse($('task-data').value).prediction || lastPrediction; } catch (_) { /* show invalid state */ }
    const ready = Boolean(prediction?.subject && prediction.model_version && Date.parse(prediction.valid_until) > Date.now());
    const label = ready ? '资料已准备' : prediction?.subject ? '有信息需要修正' : '填写分析资料';
    data.textContent = label; status.textContent = ready ? '已填写 · 可随时修改，发送时会再次校验。' : prediction?.subject ? '待修正 · 请核对预测与有效期。' : '未配置 · 首次分析需要填写预测信息。';
    session.textContent = $('conversation-id').value ? '当前分析会话' : '新分析会话';
    window.ComposerControls?.update();
    autoSize();
  }
  function open(id = 'input') {
    mode = id;
    for (const [name, pane] of Object.entries(panes)) {
      pane.hidden = name !== id;
      const button = $('analysis-tab-' + name); button.setAttribute('aria-selected', String(name === id)); button.tabIndex = name === id ? 0 : -1;
    }
    $('inspector-actions').hidden = id !== 'report';
    window.Workbench.inspector(true); update();
  }
  function layout() {
    const root=document.documentElement, stage=document.querySelector('.office-stage');
    root.style.setProperty('--composer-height',dock.offsetHeight+'px');
    if(stage && document.body.dataset.view==='analysis') {
      const top=stage.getBoundingClientRect().top;
      root.style.setProperty('--office-height',Math.max(0,innerHeight-top)+'px');
    }
    viewport();
  }
  function observe(task) {
    const prediction = task.artifacts?.[0]?.parts?.[0]?.data?.analysis?.prediction;
    if (prediction) lastPrediction = prediction;
    if (['working', 'submitted'].includes(task.status.state) && mode !== 'input') open('progress');
    update();
  }
  function reset() { lastPrediction = null; update(); }
  form.addEventListener('input', update); form.addEventListener('change', update);
  form.addEventListener('input', event => { if (event.target.hasAttribute('aria-invalid')) { event.target.removeAttribute('aria-invalid'); event.target.setCustomValidity?.(''); } });
  tabs.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault(); const names = Object.keys(panes); open(names[(names.indexOf(mode) + (event.key === 'ArrowRight' ? 1 : 2)) % 3]); $('analysis-tab-' + mode).focus();
  });
  $('report-open').onclick = () => open('report'); $('office-show-output').onclick = () => open('progress');
  $('inspector-content').querySelector('#analysis-pane-progress').hidden = false;
  for (const [name, pane] of Object.entries(panes)) { pane.hidden = name !== mode; $('analysis-tab-' + name).setAttribute('aria-selected', String(name === mode)); }
  document.querySelectorAll('.office-heading, .office-footnote, .office-floor-line, .office-floor-caption, .office-legend, .office-welcome').forEach(node => { node.hidden = true; node.setAttribute('display', 'none'); });
  document.querySelector('[data-view-pane="analysis"] .page-head').hidden = true;
  document.querySelector('.inspector-launch').hidden = true;
  $('inspector-actions').hidden = true;
  const layoutObserver=new ResizeObserver(layout);
  layoutObserver.observe(dock);layoutObserver.observe($('tasks'));
  window.addEventListener('resize', layout);
  document.body.classList.toggle('analysis-composer-visible', document.body.dataset.view === 'analysis');
  update();
  return {open, validate, observe, reset, update, layout};
})();
