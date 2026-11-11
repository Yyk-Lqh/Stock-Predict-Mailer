/* Conversation workbench. Uses the existing task, memory and report contracts. */
window.Workbench = (() => {
  let selected = '', displayed = null, sessionCursor = null, turnCursor = null;
  let turns = [], selectionEpoch = 0, sessionEpoch = 0, ready = false;
  const POSITION = 'stock_predict_mailer.workbench.position';
  const safe = fn => async (...args) => { try { return await fn(...args); } catch (error) { notice(error.message, true); } };
  const rememberPosition = () => {
    try { sessionStorage.setItem(POSITION, JSON.stringify({conversation: selected, task: displayed?.id})); } catch (_) { /* optional */ }
  };
  function inspector(open) {
    $('report-inspector').hidden = !open;
    document.body.classList.toggle('inspector-visible', open);
    $('report-open').setAttribute('aria-expanded', String(open));
    window.AnalysisInput?.layout();
  }
  function clearTask() {
    window.AnalysisInput?.reset();
    window.PonyOffice?.reset();
    currentTask = null;
    displayed = null;
    $('task-status').hidden = true;
    $('task-progress').hidden = true;
    $('task-cancel').hidden = true;
    $('report').replaceChildren();
    $('inspector-actions').replaceChildren();
    $('mail-live').replaceChildren();
    $('knowledge-report-evidence')?.remove();
    $('report-open').disabled = true;
    $('task-output').textContent = '尚无任务';
    $('result-summary').textContent = '提交后可查看执行进度与报告';
    inspector(false);
  }
  function clearFollowup() {
    taskControlsDirty = false;
    $('task-notify').checked = false;
    for (const id of ['conversation-message', 'conversation-constraints', 'remember-text', 'remember-format', 'conversation-format']) $(id).value = '';
    window.KnowledgeUI?.reset();
  }
  function saveDraft() { clearTimeout(draftTimer); draftWrite(draftSnapshot()); }
  function heading(title) {
    $('analysis-title').textContent = title;
    $('workspace-title').textContent = title;
  }
  async function sessions(append = false) {
    const epoch = ++sessionEpoch;
    const host = $('sidebar-sessions');
    if (!memoryKey) {
      host.replaceChildren();
      text(host, 'p', '新建分析时创建会话空间，也可在「记忆与访问」恢复已有密钥。', 'hint');
      $('sessions-more').hidden = true;
      return;
    }
    const page = await api(`conversations?limit=30${append && sessionCursor ? '&before=' + sessionCursor : ''}`);
    if (epoch !== sessionEpoch) return;
    if (!append) host.replaceChildren();
    sessionCursor = page.next_before;
    for (const item of page.items) {
      const button = action(item.subject || '新分析会话', () => select(item.id));
      button.className = 'session-item';
      button.dataset.conversation = item.id;
      button.classList.toggle('active', item.id === selected);
      text(button, 'span', shortTime(item.updated), 'hint');
      host.append(button);
    }
    if (!host.childElementCount) text(host, 'p', '还没有会话，开始你的第一次分析。', 'hint');
    $('sessions-more').hidden = !sessionCursor;
  }
  function renderTurns() {
    const host = $('conversation-turns');
    host.replaceChildren();
    $('conversation-thread').hidden = !turns.length;
    $('workbench-intro').hidden = Boolean(turns.length || displayed);
    $('turns-more').hidden = !turnCursor;
    $('conversation-tools').hidden = !selected;
    for (const [index, turn] of turns.entries()) {
      const article = document.createElement('article');
      article.className = 'conversation-turn';
      text(article, 'span', `分析轮次 ${turn.seq ?? index + 1}`, 'eyebrow');
      text(article, 'p', turn.message || '解读这份预测，核对依据与风险。', 'turn-message');
      const p = turn.prediction || {};
      text(article, 'p', `${p.subject || '预测'} · ${horizonText(p.horizon)} · 有效期 ${fmt(p.valid_until)}`, 'hint');
      if (turn.constraints?.length) text(article, 'p', '约束：' + turn.constraints.join('；'), 'hint');
      article.append(action('查看本轮报告与执行过程', async () => {
        const epoch = selectionEpoch;
        const task = await api('tasks/' + turn.task);
        if (epoch === selectionEpoch) openRecord(task);
      }));
      host.append(article);
    }
  }
  async function historyPage(append = false) {
    if (!selected) return;
    const id = selected, epoch = selectionEpoch;
    const data = await api(`conversations/${id}?limit=20${append && turnCursor ? '&before=' + turnCursor : ''}`);
    if (epoch !== selectionEpoch || id !== selected) return;
    turns = append ? [...data.messages, ...turns] : data.messages;
    turnCursor = data.next_before;
    renderTurns();
    return data;
  }
  async function select(id, {save = true, taskId = null} = {}) {
    if (save) saveDraft();
    const epoch = ++selectionEpoch;
    $('task-form').inert = true;
    try {
      selected = id;
      clearTask();
      clearFollowup();
      if (![...$('conversation-id').options].some(option => option.value === id)) $('conversation-id').add(new Option('分析会话', id));
      $('conversation-id').value = id;
      turns = [];
      renderTurns();
      showView('analysis');
      const state = await historyPage();
      if (epoch !== selectionEpoch) return;
      const last = turns.at(-1);
      heading(last?.prediction?.subject ? `${last.prediction.subject} · 分析会话` : '新建分析');
      $('conversation-summary').textContent = last ? '继续提问将沿用最近一轮预测与约束，并重新校验有效期。' : '填写首次预测后提交。';
      if (last) {
        $('task-data').value = JSON.stringify({prediction: last.prediction});
        syncForm(true);
        $('task-data').value = '{}';
      } else { blankPrediction(); }
      draftRestore();
      $('task-notify').checked = false;
      $('prediction-editor').open = !last;
      $('prediction-summary').textContent = last ? `${last.prediction.subject} · 沿用上轮预测（点击更新）` : '预测 · 填写标的、方向和周期';
      const latest = taskId || state?.task;
      if (latest) {
        const task = await api('tasks/' + latest);
        if (epoch !== selectionEpoch) return;
        openRecord(task);
      }
      await sessions();
      rememberPosition();
    } finally { if (epoch === selectionEpoch) $('task-form').inert = false; }
  }
  function blankPrediction() {
    setNumericPrediction(null);
    $('p-subject').value = ''; $('p-model-version').value = '';
    $('p-confidence').value = ''; $('p-synthetic').checked = false;
    facts = []; renderFacts(); resetTiming();
    $('task-data').value = '{}'; syncJSON();
  }
  async function ensureAccess() {
    if (memoryKey) return;
    const access = await api('memory/access', 'POST', {});
    await useMemoryKey(access.key);
    $('memory-key').value = access.key;
    $('access-recovery').hidden = false;
  }
  async function newAnalysis() {
    saveDraft();
    await ensureAccess();
    const item = await api('conversations', 'POST', {});
    await refreshMemory();
    await select(item.id, {save: false});
    heading('新建分析');
    $('conversation-message').focus();
  }
  async function prepare() {
    if (!$('conversation-id').value) {
      const snapshot = draftSnapshot();
      const knowledge = window.KnowledgeUI?.selection();
      await ensureAccess();
      const item = await api('conversations', 'POST', {});
      await refreshMemory();
      $('conversation-id').add(new Option('新分析会话', item.id));
      $('conversation-id').value = item.id;
      selected = item.id;
      draftWrite(snapshot);
      draftRestore();
      if (knowledge) window.KnowledgeUI.restore(knowledge);
      await sessions();
    } else selected = $('conversation-id').value;
  }
  async function submitted() {
    document.body.classList.remove('report-dismissed');
    $('task-notify').checked = false;
    taskControlsDirty = false;
    window.KnowledgeUI?.reset();
    $('conversation-message').value = '';
    $('prediction-editor').open = false;
    $('task-data').value = '{}';
    saveDraft();
    await historyPage();
    await sessions();
    heading(`${turns.at(-1)?.prediction?.subject || '预测'} · 分析会话`);
  }
  function task(value) {
    window.AnalysisInput?.observe(value);
    if (displayed?.id !== value.id) {
      $('mail-live').replaceChildren();
      $('knowledge-report-evidence')?.remove();
    }
    displayed = value;
    rememberPosition();
    const state = TASK_STATE[value.status.state] || value.status.state;
    const result = value.artifacts?.[0]?.parts?.[0]?.data;
    $('report-open').disabled = false;
    if (['submitted', 'working'].includes(value.status.state) && !document.body.classList.contains('report-dismissed')) inspector(true);
    $('result-summary').textContent = result
      ? `${state} · ${result.analysis?.status === 'degraded' ? '分析已降级' : '报告已生成'} · ${MAIL_STATE[result.mail?.status || 'not_requested'] || result.mail?.status}`
      : state;
    $('workbench-intro').hidden = true;
    if (result || value.status.state === 'failed') {
      if (!document.body.classList.contains('report-dismissed')) inspector(true);
      const host = $('inspector-actions');
      host.replaceChildren();
      if (result) {
        host.append(action('下载 HTML 报告', () => download('report', 'html')), action('下载分析 JSON', () => download('analysis', 'json')));
        if (result.knowledge) host.append(action('查看知识证据', () => window.KnowledgeUI.evidence(result.knowledge)));
        host.append(action('刷新投递状态', async () => {
          const status = await api(`tasks/${value.id}/mail`);
          const panel = $('mail-live');
          panel.replaceChildren();
          text(panel, 'h3', '最新投递状态');
          text(panel, 'p', MAIL_STATE[status.status] || status.status);
          text(panel, 'p', MAIL_NOTE[status.status] || '请按实际回执核对。', 'hint');
          if (status.attempts != null) text(panel, 'p', `尝试次数 ${status.attempts} · 下次重试 ${status.next_attempt ? fmt(status.next_attempt) : '—'}`, 'hint');
        }));
      }
    }
  }
  async function download(kind, extension) {
    const response = await fetch(`/api/tasks/${displayed.id}/${kind}`, {headers: {'X-Memory-Key': memoryKey}});
    if (!response.ok) { const error = await response.json(); throw new Error(error.error?.message || '下载失败'); }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = `analysis-${displayed.id}.${extension}`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function record(value) {
    document.body.classList.remove('report-dismissed');
    const cid = taskBrief(value).conversation_id || (turns.some(turn => turn.task === value.id) ? selected : '');
    if (cid && cid !== selected) { select(cid, {taskId: value.id}).catch(error => notice(error.message, true)); return; }
    if (!cid && selected) {
      saveDraft(); ++selectionEpoch; selected = ''; turns = [];
      $('conversation-id').value = ''; clearFollowup(); renderTurns(); heading('独立任务');
    }
    if (value.artifacts?.length || value.status.state === 'failed') inspector(true);
    rememberPosition();
  }
  function view(name) {
    if (name !== 'analysis') document.body.classList.remove('analysis-composer-visible');
    else document.body.classList.add('analysis-composer-visible');
    $('session-menu').open = false;
    window.PonyOffice?.view(name);
    document.body.dataset.view = name;
    document.body.classList.remove('sidebar-open');
    $('sidebar-toggle').setAttribute('aria-expanded', 'false');
    if (name !== 'analysis') inspector(false);
    else if (displayed && !document.body.classList.contains('report-dismissed') && !$('report-open').disabled) inspector(true);
    if (name === 'knowledge') window.KnowledgeUI?.load();
    const titles = {records: '任务记录', settings: '设置', memory: '记忆与访问', knowledge: '知识库', overview: '使用引导'};
    $('workspace-title').textContent = titles[name] || $('analysis-title').textContent;
  }
  function saveFile(value, filename) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function init() {
    ready = true;
    $('workspace-health').textContent = settings?.default_model_id ? '模型已配置' : '尚未选择分析模型';
    if (!draftRead()) blankPrediction();
    await sessions();
    let position;
    try { position = JSON.parse(sessionStorage.getItem(POSITION) || 'null'); } catch (_) { /* optional */ }
    if (position?.conversation && memoryKey) {
      try { await select(position.conversation, {save: false, taskId: position.task}); }
      catch (error) { selected = ''; $('conversation-id').value = ''; clearTask(); notice('未能恢复上次位置：' + error.message, true); }
    } else if (position?.task) {
      try { openRecord(await api('tasks/' + position.task)); } catch (_) { clearTask(); }
    }
    window.KnowledgeUI?.init();
  }
  function identityChanged() {
    if (!ready) return;
    ++selectionEpoch; selected = ''; turns = []; clearTask(); clearFollowup(); renderTurns();
    blankPrediction();
    $('task-form').inert = false;
    window.KnowledgeUI?.identityReset();
    $('conversation-id').value = '';
    $('knowledge-detail').hidden = true;
    $('knowledge-results').replaceChildren();
    $('knowledge-configs').replaceChildren();
    $('knowledge-indexes').replaceChildren();
    heading('新建分析');
    sessionStorage.removeItem(POSITION);
    sessions().catch(error => notice(error.message, true));
  }
  // Keep the existing form and report renderers; relocate them without replacing their IDs.
  $('inspector-content').append($('report'));
  const live = document.createElement('section'); live.id = 'mail-live'; $('inspector-content').append(live);
  $('workbench-runtime').append($('task-status'), $('task-progress'));
  const tools = document.createElement('div'); tools.id = 'conversation-tools'; tools.className = 'actions conversation-tools'; tools.hidden = true;
  tools.append(action('导出会话', async () => { saveFile(await api(`conversations/${selected}/export`), `conversation-${selected}.json`); }), action('删除会话', async () => {
    if (!confirm('删除会话消息和摘要？长期记忆及历史任务报告会保留。运行中的会话需先取消任务。')) return;
    const id = selected;
    await api('conversations/' + id, 'DELETE');
    try { localStorage.removeItem(DRAFT_KEY + '.' + id); } catch (_) { /* optional */ }
    clearTimeout(draftTimer); ++selectionEpoch; selected = ''; turns = []; $('conversation-id').value = '';
    clearTask(); clearFollowup(); blankPrediction(); renderTurns(); heading('新建分析');
    await refreshMemory(); rememberPosition();
  }));
  $('analysis-title').closest('.page-head').after(tools);
  $('memory-access-actions').append(action('复制当前访问密钥', async () => {
    if (!memoryKey) throw new Error('请先创建或使用已有访问密钥');
    $('memory-key').value = memoryKey;
    try { await navigator.clipboard.writeText(memoryKey); notice('访问密钥已复制，请保存在安全位置。'); }
    catch (_) { $('memory-key').type = 'text'; $('memory-key').select(); notice('请复制已选中的访问密钥并妥善保存。'); }
  }), action('撤销当前访问密钥', async () => {
    if (!memoryKey) throw new Error('当前没有访问密钥');
    if (!confirm('撤销后无法用此密钥恢复资料。请先完成导出或清理；此操作不会删除已有资料。继续？')) return;
    await api('memory/access', 'DELETE');
    memoryKey = ''; sessionStorage.removeItem('spm_memory_key'); $('memory-key').value = '';
    identityChanged(); await refreshMemory(); notice('访问密钥已撤销。');
  }));
  const execution = document.createElement('details'); execution.className = 'advanced execution-details';
  const executionTitle = document.createElement('summary'); executionTitle.textContent = '执行详情 · 阶段、调用与事件';
  execution.append(executionTitle, $('execution-plan'), $('execution-events'));
  $('runviz').after(execution);
  // Settings remain one form, with the existing complete-object save behavior.
  document.querySelectorAll('#settings-form > .setting-group').forEach(card => {
    const title = card.querySelector('h2'); if (!title) return;
    const details = document.createElement('details'); details.className = 'input-editor';
    text(details, 'summary', title.textContent); card.before(details); details.append(card);
  });
  const settingsNav = document.querySelector('[data-view-pane="settings"] .subnav');
  settingsNav.append(action('记忆与访问', () => showView('memory')), action('知识处理与索引', () => { showView('knowledge'); window.KnowledgeUI?.processing(); }));
  const form = $('task-form');
  const cards = [...form.querySelectorAll(':scope > .card')];
  for (const [index, card] of cards.entries()) {
    if (index > 1) continue;
    const details = document.createElement('details');
    details.className = 'input-editor'; details.id = index ? 'facts-editor' : 'prediction-editor'; details.open = !index;
    const summary = document.createElement('summary');
    summary.textContent = index ? '客观事实 · 添加来源与观测时间' : '预测 · 填写标的、方向和周期';
    if (!index) summary.id = 'prediction-summary';
    card.before(details); details.append(summary, card);
  }
  const conversation = $('conversation-fields');
  const message = $('conversation-message').closest('label');
  const composer = document.createElement('div'); composer.className = 'composer';
  message.querySelector('span').textContent = '你想重点分析什么？';
  $('conversation-message').placeholder = '例如：这份预测有哪些风险？有哪些依据还需要核对？';
  const contextOptions = document.createElement('details'); contextOptions.className = 'advanced';
  contextOptions.innerHTML = '<summary>会话约束与记忆偏好</summary>';
  conversation.before(composer); composer.append(message, contextOptions); contextOptions.append(conversation);
  const runOptions = document.createElement('details'); runOptions.className = 'input-editor';
  text(runOptions, 'summary', '运行与通知 · 分析目标、预算档位与邮件');
  const optionsBody = document.createElement('div'); optionsBody.className = 'card';
  const runCard = composer.parentElement;
  while (runCard.firstElementChild && runCard.firstElementChild !== composer) optionsBody.append(runCard.firstElementChild);
  runCard.prepend(runOptions); runOptions.append(optionsBody);
  $('prediction-editor').open = false;
  const recovery = document.createElement('div'); recovery.id = 'access-recovery'; recovery.className = 'note warn'; recovery.hidden = true;
  text(recovery, 'p', '已创建私有会话空间。访问密钥仅在当前标签页保留，请到「记忆与访问」复制并妥善保存，以便重新打开后恢复。');
  recovery.append(action('保存访问密钥', () => showView('memory')));
  $('tasks').prepend(recovery);
  $('new-analysis').onclick = safe(async () => {
    $('new-analysis').disabled = true;
    try { await newAnalysis(); } finally { $('new-analysis').disabled = false; }
  });
  $('sessions-refresh').onclick = safe(() => sessions());
  $('sessions-more').onclick = safe(() => sessions(true));
  $('turns-more').onclick = safe(() => historyPage(true));
  $('workbench-sample').onclick = () => $('try-sample').click();
  $('report-open').onclick = () => { document.body.classList.remove('report-dismissed'); inspector(true); };
  $('report-close').onclick = () => { inspector(false); document.body.classList.add('report-dismissed'); $('report-open').focus(); };
  $('report-expand').onclick = () => {
    const expanded = document.body.classList.toggle('inspector-expanded');
    $('report-expand').setAttribute('aria-pressed', String(expanded)); $('report-expand').textContent = expanded ? '收起' : '展开';
  };
  $('sidebar-toggle').onclick = () => $('sidebar-toggle').setAttribute('aria-expanded', String(document.body.classList.toggle('sidebar-open')));
  $('conversation-id').onchange = safe(() => $('conversation-id').value ? select($('conversation-id').value, {save: false}) : newAnalysis());
  for (const id of ['task-complexity', 'task-goal', 'task-effort']) $(id).addEventListener('change', () => { taskControlsDirty = true; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { inspector(false); document.body.classList.add('report-dismissed'); document.body.classList.remove('sidebar-open'); $('sidebar-toggle').setAttribute('aria-expanded', 'false'); } });
  document.addEventListener('click', event => { if (!$('session-menu').contains(event.target)) $('session-menu').open = false; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') $('session-menu').open = false; });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') saveDraft(); });
  return {init, view, task, prepare, submitted: value => { submitted(value).catch(error => notice(error.message, true)); }, record, sessions, identityChanged, inspector};
})();
