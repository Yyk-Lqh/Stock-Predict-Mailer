/* Desktop workflow enhancement. Mobile keeps the original shell and controls. */
window.DesktopWorkbench = (() => {
  const desktop = matchMedia('(min-width: 761px)');
  const preference = 'stock_predict_mailer.desktop.view.v1';
  const office = document.querySelector('.pony-office');
  const inspectorTitle = document.querySelector('.inspector-head h2');
  const originalTitle = inspectorTitle.textContent;
  const statusParent = $('task-status').parentElement, statusNext = $('task-status').nextSibling;
  let root = null, focus = null, feedback = null, task = null, pane = 'progress';
  let origin = null, mode = 'focus', expiry = null, expiresAt = 0, disconnected = false, sampling = false, selection = {state:'idle'};
  try { if (localStorage.getItem(preference) === 'hall') mode = 'hall'; } catch (_) { /* Optional preference. */ }

  const put = (id, value) => {
    const node = $(id);
    if (node.textContent !== value) node.textContent = value;
  };
  function inputState() {
    let raw;
    try {
      raw = JSON.parse($('task-data').value);
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw Error();
    } catch (_) { return {state: 'invalid', field: 'task-data', label: '请修正原始 JSON', detail: '原始输入无法解析，请打开资料检查格式。'}; }
    const prediction = window.AnalysisInput.currentPrediction();
    if (typeof prediction?.subject !== 'string' || !prediction.subject.trim()) return {state: 'empty', label: '填写分析资料', detail: '先填写标的、预测周期和上游模型版本。'};
    const result = {prediction, facts: Array.isArray(raw.context?.facts) ? raw.context.facts.length : 0};
    if (typeof prediction.model_version !== 'string' || !prediction.model_version.trim()) return {...result, state: 'invalid', field: 'p-model-version', label: '补充模型版本', detail: '请填写这份预测的上游模型版本。'};
    if (!(Number.isFinite(prediction.horizon?.value) && prediction.horizon.value > 0)) return {...result, state: 'invalid', field: 'p-horizon-value', label: '核对预测周期', detail: '预测周期需要大于零。'};
    if (!(Date.parse(prediction.valid_until) > Date.now())) return {...result, state: 'expired', field: 'p-valid-until', label: '更新过期预测', detail: '预测已过期或缺少有效期，请核对原始资料后更新。'};
    if (prediction.confidence != null && !(Number.isFinite(prediction.confidence) && prediction.confidence >= 0 && prediction.confidence <= 1)) return {...result, state: 'invalid', field: 'p-confidence', label: '核对置信度', detail: '置信度须在 0 到 1 之间；上游未提供时可留空。'};
    if (raw.context?.facts && (!Array.isArray(raw.context.facts) || raw.context.facts.some(fact => typeof fact?.source !== 'string' || !fact.source.trim() || !Number.isFinite(Date.parse(fact.observed_at))))) {
      return {...result, state: 'invalid', label: '补充事实来源', detail: '每条客观事实都需要来源和有效的观测时间。'};
    }
    return {...result, state: 'ready', label: prediction.subject, detail: '主要资料已填写；发送时会再次校验资料、归档和授权。'};
  }
  function openData() {
    origin = document.activeElement;
    $('prediction-editor').open = true;
    window.AnalysisInput.open('input');
    const target = $('task-form').querySelector('[aria-invalid="true"]') || $(inputState().field || 'p-subject');
    for (let parent = target.parentElement; parent && parent !== $('task-form'); parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
    target.focus(); target.scrollIntoView({block: 'nearest'});
  }
  function openResult() {
    if (!task) return;
    origin = document.activeElement;
    window.AnalysisInput.open(['submitted', 'working'].includes(task.status.state) ? 'progress' : 'report');
    $('analysis-tab-' + pane).focus();
  }
  function chooseModel() {
    origin = document.activeElement;
    if (profiles.some(item => item.enabled && item.id === settings?.default_model_id)) $('composer-model').click();
    else { showView('settings'); showPanel('models'); $('model-name').focus(); }
  }
  async function sample(event) {
    if(selection.state==='loading'||sampling)return;
    const button = event.currentTarget;
    const current = profiles.find(item => item.id === settings?.default_model_id);
    if (current?.provider !== 'mock' && current && !confirm('准备示例会将工作台默认模型切换为 Mock，并替换当前预测与事实。不会自动提交分析。继续？')) return;
    if (window.AnalysisInput.currentPrediction()?.subject && (!current || current.provider === 'mock') && !confirm('用合成示例替换当前预测与事实？当前问题会保留，不会自动提交。')) return;
    sampling=true;button.disabled = true;
    try {
      await $('try-sample').onclick();
      if (settings?.default_model_id && $('task-data').value.includes('console-mock')) {
        update();
        $('conversation-message').focus();
        notice('离线示例已准备：默认模型为 Mock，资料为合成示例。输入问题后点击发送。');
      }
    } finally { sampling=false;button.disabled = selection.state==='loading'; }
  }
  function setMode(value) {
    mode = value;
    if (!root || !desktop.matches) return;
    document.body.classList.toggle('desktop-focus-view', mode === 'focus');
    office.querySelector('.office-stage').inert = mode === 'focus';
    if (office.querySelector('.market-wall')) office.querySelector('.market-wall').inert = mode === 'focus';
    for (const button of root.querySelectorAll('[data-desktop-mode]')) button.setAttribute('aria-pressed', String(button.dataset.desktopMode === mode));
    try { localStorage.setItem(preference, mode); } catch (_) { /* Optional preference. */ }
    window.AnalysisInput.layout();
  }
  function panel(value) {
    pane = value;
    if (!desktop.matches || !root) return;
    if (document.activeElement instanceof HTMLElement && !document.activeElement.closest('#report-inspector') && document.activeElement !== document.body) origin = document.activeElement;
    inspectorTitle.textContent = {input: '分析资料', progress: '工作进度', report: '报告与证据'}[pane];
  }
  function returnFocus() {
    if (!desktop.matches || !root) return;
    const target = origin?.isConnected && origin.getClientRects().length ? origin : $('desktop-data');
    target.focus();
  }
  function history(open = $('analysis-composer').classList.contains('desktop-history-open')) {
    if (!root || !desktop.matches) return;
    const count = $('conversation-turns').childElementCount;
    const expanded = Boolean(open && count);
    $('desktop-history').hidden = !count;
    put('desktop-history', `会话记录 · ${count} 轮`);
    $('desktop-history').setAttribute('aria-expanded', String(expanded));
    $('analysis-composer').classList.toggle('desktop-history-open', expanded);
  }
  function update() {
    if (!root || !desktop.matches) return;
    const input = inputState();
    const model = profiles.find(item => item.enabled && item.id === settings?.default_model_id);
    const prediction = input.prediction;
    const until = Date.parse(prediction?.valid_until) || 0;
    if (until !== expiresAt) {
      clearTimeout(expiry); expiresAt = until;
      if (until > Date.now()) expiry = setTimeout(() => { expiresAt = 0; update(); }, Math.min(until - Date.now() + 50, 2147483647));
    }
    const active = task && ['submitted', 'working'].includes(task.status.state);
    const result = task?.artifacts?.[0]?.parts?.[0]?.data;
    const failed = task?.status.state === 'failed';
    const canceled = task?.status.state === 'canceled';
    const switching=selection.state==='loading',selectionFailed=selection.state==='failed';
    put('desktop-title', prediction?.subject ? `${prediction.subject} · 分析工作台` : '从一份预测开始');
    put('desktop-subtitle', switching?'正在切换会话，读取完成后恢复输入。':selectionFailed?'会话尚未读取完成，可重试或选择其他会话。':active && disconnected ? '进度暂未更新，可打开工作进度重试读取。' : active ? '任务正在执行，可随时查看真实工作进度。' : '准备资料，核对依据，再继续追问。');
    for(const id of ['desktop-model','desktop-data','desktop-focus-data'])$(id).disabled=switching;
    $('desktop-sample').disabled=switching||sampling;
    put('desktop-model-value', model?.name || '选择模型');
    $('desktop-model').dataset.state = model ? 'ready' : 'empty';
    $('desktop-model').title = model ? `工作台默认模型：${model.name}；切换将影响后续分析。` : '先添加或选择一个默认模型，也可使用离线示例。';
    put('desktop-data-value', input.label);
    $('desktop-data').dataset.state = input.state;
    $('desktop-data').title = input.detail;
    $('desktop-result').disabled = switching||!task;
    put('desktop-result-value', active ? '查看工作进度' : failed ? '查看失败原因' : canceled ? '查看已取消任务' : result ? '查看报告与证据' : '等待分析报告');
    $('desktop-result').dataset.state = failed ? 'invalid' : result ? 'ready' : active ? 'working' : 'empty';
    put('desktop-focus-title', prediction?.subject || '准备你的第一份分析');
    put('desktop-focus-copy', prediction ? input.detail : '导入上游预测，或填写标的与周期。准备好资料后，在下方输入想重点分析的问题。');
    put('desktop-summary-model', model ? `${model.name}${model.provider === 'mock' ? ' · 离线模拟' : ''}` : '尚未选择默认模型');
    put('desktop-summary-prediction', prediction ? `${horizonText(prediction.horizon)} · ${prediction.synthetic ? '合成数据' : '上游声明数据'}` : '尚未提供预测');
    put('desktop-summary-facts', input.facts ? `${input.facts} 条来源声明` : '本轮未附新增事实');
    put('desktop-summary-mail', $('task-notify').checked ? '本轮启用邮件 · 仍需核对授权收件人' : '仅分析 · 本轮不发送邮件');
    $('desktop-sample').hidden = Boolean(task);
    focus.querySelector('.desktop-sample-note').hidden = Boolean(task);
    history();
    let message = active ? '分析进行中，工作进度来自实际任务事件。'
      : !model ? '先选择分析模型，或准备一个离线示例。'
      : input.state !== 'ready' ? input.detail
      : failed ? '上一轮分析失败；请查看原因，修改后再提交。'
      : canceled ? '上一轮任务已取消。确认资料后可重新发送。'
      : result ? `上一轮报告已生成${result.analysis?.status === 'degraded' ? '，分析存在降级' : ''}；可继续提问。`
      : input.detail;
    if (!active && input.state === 'ready' && $('task-notify').checked && !$('task-recipient').value.trim()) message = '本轮启用了邮件，请先填写授权收件地址。';
    if (active && disconnected) message = '进度读取中断；任务可能仍在服务端运行，可打开工作进度重试。';
    if(switching)message='正在切换会话，请稍候；已保存的草稿会在读取后恢复。';
    else if(selectionFailed)message=selection.message;
    put('desktop-feedback-text', message);
    feedback.dataset.state = selectionFailed||failed || (active && disconnected) || ['invalid', 'expired'].includes(input.state) ? 'invalid' : switching||active ? 'working' : 'normal';
    put('desktop-feedback-action', switching?'正在读取':selectionFailed?'重新读取会话':active ? '查看进度' : failed ? '查看原因' : result ? '查看报告' : !model ? '选择模型' : '检查资料');
    $('desktop-feedback-action').disabled=switching;
    $('desktop-feedback-action').onclick = selectionFailed?selection.retry:active || failed || result ? openResult : !model ? chooseModel : openData;
    for (const button of document.querySelectorAll('.nav [data-view]')) {
      if (button.dataset.view === document.body.dataset.view) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
  }
  function install() {
    if (!desktop.matches) {
      if (root) {
        root.hidden = focus.hidden = feedback.hidden = true;
        document.body.classList.remove('desktop-workbench', 'desktop-focus-view');
        office.querySelector('.office-stage').inert = false;
        if (office.querySelector('.market-wall')) office.querySelector('.market-wall').inert = false;
        clearTimeout(expiry); expiresAt = 0;
        statusParent.insertBefore($('task-status'), statusNext);
        $('analysis-composer').classList.remove('desktop-history-open');
        inspectorTitle.textContent = originalTitle;
        document.querySelectorAll('.nav [aria-current]').forEach(button => button.removeAttribute('aria-current'));
        window.AnalysisInput.layout();
      }
      return;
    }
    if (!root) {
      root = document.createElement('section'); root.id = 'desktop-workflow'; root.setAttribute('aria-label', '分析流程');
      root.innerHTML = `<div class="desktop-workflow-heading"><div><h1 id="desktop-title"></h1><p id="desktop-subtitle"></p></div><div class="desktop-view-switch" role="group" aria-label="工作台视图"><button type="button" data-desktop-mode="focus">专注分析</button><button type="button" data-desktop-mode="hall">小马大厅</button></div></div>
        <div class="desktop-workflow-actions"><button type="button" id="desktop-model"><span class="desktop-step">1 · 模型</span><strong id="desktop-model-value"></strong></button><button type="button" id="desktop-data"><span class="desktop-step">2 · 资料</span><strong id="desktop-data-value"></strong></button><button type="button" id="desktop-result"><span class="desktop-step">3 · 结果</span><strong id="desktop-result-value"></strong></button></div>`;
      focus = document.createElement('section'); focus.id = 'desktop-focus'; focus.setAttribute('aria-label', '本轮分析摘要');
      focus.innerHTML = `<div class="desktop-focus-intro"><p class="eyebrow">本轮分析</p><h2 id="desktop-focus-title"></h2><p id="desktop-focus-copy"></p><div class="desktop-focus-actions"><button type="button" id="desktop-focus-data" class="btn primary">填写 / 修改资料</button><button type="button" id="desktop-sample" class="btn">准备离线示例</button></div><p class="hint desktop-sample-note">离线示例会将默认模型设为 Mock 并填入合成资料，准备后仍需手动发送。</p></div><dl class="desktop-summary"><div><dt>分析模型</dt><dd id="desktop-summary-model"></dd></div><div><dt>预测周期</dt><dd id="desktop-summary-prediction"></dd></div><div><dt>客观事实</dt><dd id="desktop-summary-facts"></dd></div><div><dt>本轮通知</dt><dd id="desktop-summary-mail"></dd></div></dl>`;
      feedback = document.createElement('div'); feedback.id = 'desktop-feedback';
      feedback.innerHTML = '<span id="desktop-feedback-text" role="status" aria-live="polite"></span><button type="button" id="desktop-feedback-action"></button><button type="button" id="desktop-history" aria-controls="conversation-thread" aria-expanded="false" hidden></button><span class="desktop-send-hint">Enter 发送 · Shift+Enter 换行</span>';
      office.prepend(root, focus);
      $('analysis-composer').prepend(feedback);
      $('desktop-data').onclick = $('desktop-focus-data').onclick = openData;
      $('desktop-model').onclick = chooseModel;
      $('desktop-result').onclick = openResult;
      $('desktop-sample').onclick = sample;
      $('desktop-history').onclick = () => history(!$('analysis-composer').classList.contains('desktop-history-open'));
      new MutationObserver(() => history()).observe($('conversation-turns'), {childList: true});
      document.addEventListener('pointerdown', event => { if (desktop.matches && !$('analysis-composer').contains(event.target)) history(false); });
      document.addEventListener('keydown', event => {
        if(window.DesktopInteractions?.active())return;
        if (desktop.matches && event.key === 'Escape' && $('analysis-composer').classList.contains('desktop-history-open')) {
          event.preventDefault(); event.stopImmediatePropagation(); history(false); $('desktop-history').focus();
        }
      }, true);
      $('task-form').addEventListener('submit', () => history(false));
      root.querySelectorAll('[data-desktop-mode]').forEach(button => { button.onclick = () => setMode(button.dataset.desktopMode); });
      $('report-close').addEventListener('click', returnFocus);
      const resize = new ResizeObserver(() => {
        if (!desktop.matches) return;
        const height = root.offsetHeight + 'px';
        if (office.style.getPropertyValue('--desktop-workflow-height') !== height) {
          office.style.setProperty('--desktop-workflow-height', height);
          document.documentElement.style.setProperty('--desktop-workflow-height', height);
          window.AnalysisInput.layout();
        }
      });
      resize.observe(root);
    }
    root.hidden = focus.hidden = feedback.hidden = false;
    $('analysis-pane-progress').prepend($('task-status'));
    document.body.classList.add('desktop-workbench');
    setMode(mode); panel(pane); update();
  }
  desktop.addEventListener('change', install);
  new MutationObserver(update).observe(document.body, {attributes: true, attributeFilter: ['data-view']});
  document.addEventListener('visibilitychange', () => { if (!document.hidden) update(); });
  window.addEventListener('focus', update);
  install();
  return {update, panel, observe(value) { task = value; update(); }, connectionLost(value){disconnected=value;update();},selectionState(value){selection=value;update();}, reset() { task = null; disconnected=false;update(); }};
})();
