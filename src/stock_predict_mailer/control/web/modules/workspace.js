/* Conversation workbench. Uses the existing task, memory and report contracts. */
window.Workbench = (() => {
  let selected = '', displayed = null, targetTask = null, sessionCursor = null, turnCursor = null;
  let turns = [], selectionEpoch = 0, sessionEpoch = 0, ready = false;
  const revisions = new Map();
  const revision = mode => revisions.get(mode) || 0;
  const changeSelection = () => {
    const mode = AnalysisMode.active();
    revisions.set(mode, revision(mode) + 1);
    submitErrors.delete(mode);
    AnalysisMode.write('pending-run', null, mode);
  };
  const safe = fn => async (...args) => {
    const scope = AnalysisMode.capture();
    try { return await fn(...args); } catch (error) { if (AnalysisMode.current(scope)) notice(error.message, true); }
  };
  const rememberPosition = () => {
    AnalysisMode.write('position', {conversation: selected, task: displayed?.id || targetTask});
  };
  const details = () => [...$('task-form').querySelectorAll('details'), execution];
  function saveUI() {
    AnalysisMode.write('ui', {
      details: details().map(item => item.open),
      panel: window.AnalysisInput?.pane(),
      report: document.body.classList.contains('inspector-visible'),
      reader: window.DesktopReport?.snapshot(),
      dismissed: document.body.classList.contains('report-dismissed'),
      expanded: document.body.classList.contains('inspector-expanded'),
      history: $('analysis-composer').classList.contains('desktop-history-open'),
      sidebar: document.body.classList.contains('sidebar-open'),
      sessions: $('session-menu').open
    });
  }
  function restoreUI(ui) {
    if (!ui) return;
    details().forEach((item, index) => { item.open = Boolean(ui.details?.[index]); });
    if (ui.panel) window.AnalysisInput?.open(ui.panel, false);
    inspector(Boolean(ui.report));
    document.body.classList.toggle('report-dismissed', Boolean(ui.dismissed) || !ui.report);
    expandReport(Boolean(ui.expanded));
    window.DesktopWorkbench?.historyOpen(Boolean(ui.history));
    document.body.classList.toggle('sidebar-open', Boolean(ui.sidebar));
    $('sidebar-toggle').setAttribute('aria-expanded', String(Boolean(ui.sidebar)));
    $('session-menu').open = Boolean(ui.sessions);
  }
  function inspector(open) {
    if (open && matchMedia('(min-width: 761px)').matches && document.body.dataset.view && document.body.dataset.view !== 'analysis') open = false;
    $('report-inspector').hidden = !open;
    document.body.classList.toggle('inspector-visible', open);
    $('report-open').setAttribute('aria-expanded', String(open));
    window.AnalysisInput?.layout();
    window.DesktopReport?.visibility(open);
  }
  function clearTask() {
    window.DesktopPoll?.stop();
    window.AnalysisInput?.reset();
    window.PonyOffice?.reset();
    currentTask = null;
    displayed = null;
    targetTask = null;
    $('task-status').hidden = true;
    $('task-progress').hidden = true;
    for (const id of ['execution-plan', 'execution-events', 'chart-preview', 'analysis-preview']) $(id).replaceChildren();
    $('effective-effort').textContent = '';
    $('task-cancel').hidden = true;
    $('task-delete').hidden = true;
    $('report').replaceChildren();
    $('inspector-actions').replaceChildren();
    $('mail-live').replaceChildren();
    $('knowledge-report-evidence')?.remove();
    $('report-open').disabled = true;
    $('task-output').textContent = '尚无任务';
    $('result-summary').textContent = '提交后可查看执行进度与报告';
    inspector(false);
    window.DesktopReport?.clear();
    window.DesktopWorkbench?.clearRuntime();
  }
  function clearFollowup() {
    window.ForecastUI?.reset();
    taskControlsDirty = false;
    for (const id of ['task-complexity', 'task-goal', 'task-effort']) $(id).value = PREDICTION_TEMPLATE_DEFAULTS[id];
    $('task-notify').checked = false;
    for (const id of ['conversation-message', 'conversation-constraints', 'remember-text', 'remember-format',
      'conversation-format', 'task-recipient']) $(id).value = '';
    window.KnowledgeUI?.reset();
  }
  function saveDraft() {
    clearTimeout(draftTimer);
    if (ready && AnalysisMode.active() !== 'legacy' && !$('task-form').inert && !window.DesktopInteractions?.draftBlocked()) draftWrite(draftSnapshot());
  }
  function heading(title) {
    $('analysis-title').textContent = title;
    $('workspace-title').textContent = title;
  }
  async function sessions(append = false) {
    if (window.DesktopSessions?.active()) return window.DesktopSessions.load(append,id=>select(id));
    const epoch = ++sessionEpoch;
    const host = $('sidebar-sessions');
    if (!memoryKey) {
      host.replaceChildren();
      text(host, 'p', '点击「新建分析」打开本机的会话空间。', 'hint');
      $('sessions-more').hidden = true;
      return;
    }
    const scope = AnalysisMode.capture();
    const page = await api(`conversations?limit=30${append && sessionCursor ? '&before=' + sessionCursor : ''}`, 'GET', undefined, undefined, scope);
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
    removeConversation.hidden = AnalysisMode.active() === 'legacy';
    for (const [index, turn] of turns.entries()) {
      const article = document.createElement('article');
      article.className = 'conversation-turn';
      text(article, 'span', `分析轮次 ${turn.seq ?? index + 1}`, 'eyebrow');
      text(article, 'p', turn.message || '解读这份预测，核对依据与风险。', 'turn-message');
      const p = turn.prediction || {};
      text(article, 'p', `${p.subject || '预测'} · ${horizonText(p.horizon)} · 有效期 ${fmt(p.valid_until)}`, 'hint');
      if (turn.constraints?.length) text(article, 'p', '约束：' + turn.constraints.join('；'), 'hint');
      if (turn.task) article.append(action('查看本轮报告与执行过程', async () => {
        const epoch = selectionEpoch;
        const scope = AnalysisMode.active() === 'legacy' ? undefined : AnalysisMode.capture();
        const task = await api('tasks/' + turn.task, 'GET', undefined, undefined, scope);
        if (epoch === selectionEpoch) openRecord(task);
      }));
      host.append(article);
    }
  }
  async function historyPage(append = false) {
    if (!selected) return;
    const id = selected, epoch = selectionEpoch;
    const data = await api(`conversations/${id}?limit=20${append && turnCursor ? '&before=' + turnCursor : ''}`,
      'GET', undefined, undefined, AnalysisMode.capture());
    if (epoch !== selectionEpoch || id !== selected) return;
    turns = append ? [...data.messages, ...turns] : data.messages;
    turnCursor = data.next_before;
    renderTurns();
    return data;
  }
  async function select(id, {save = true, taskId = null, prefetched = null} = {}) {
    if (save) saveDraft();
    changeSelection();
    const scope = AnalysisMode.capture();
    const epoch = ++selectionEpoch;
    $('task-form').inert = true;
    window.DesktopInteractions?.begin();
    try {
      document.body.classList.remove('report-dismissed');
      selected = id;
      clearTask();
      clearFollowup();
      turnCursor = null;
      if (![...$('conversation-id').options].some(option => option.value === id)) $('conversation-id').add(new Option('分析会话', id));
      $('conversation-id').value = id;
      turns = [];
      renderTurns();
      showView('analysis');
      const state = prefetched || await historyPage();
      if (epoch !== selectionEpoch) return;
      if (prefetched) { turns = state.messages; turnCursor = state.next_before; renderTurns(); }
      const last = turns.at(-1);
      window.AnalysisInput?.restorePrediction(last?.prediction);
      heading(last?.prediction?.subject ? `${last.prediction.subject} · 分析会话` : scope.mode === 'legacy' ? '历史会话' : '新建分析');
      $('conversation-summary').textContent = scope.mode === 'legacy' ? '旧会话历史' : last
        ? '继续提问将沿用最近一轮预测与约束，并重新校验有效期。' : '填写首次预测后提交。';
      if (last) {
        $('task-data').value = JSON.stringify({prediction: last.prediction});
        syncForm(true);
        $('task-data').value = '{}';
      } else { resetPredictionInput(); }
      $('prediction-editor').open = !last;
      if (scope.mode !== 'legacy') {
        AnalysisMode.importLegacy(draftKey(id), scope.mode, DRAFT_KEY + '.' + id);
        draftRestore();
      }
      $('prediction-summary').textContent = last ? `${last.prediction.subject} · 沿用上轮预测（点击更新）` : '预测 · 填写标的、方向和周期';
      const latest = taskId || state?.task;
      if (latest) {
        const task = await api('tasks/' + latest, 'GET', undefined, undefined, scope.mode === 'legacy' ? undefined : scope);
        if (epoch !== selectionEpoch) return;
        displayTask(task);
      }
      await sessions();
      rememberPosition();
    } catch(error) {
      if(epoch===selectionEpoch&&window.DesktopInteractions?.active()){
        const denied=/FORBIDDEN|NOT_FOUND/.test(error.message);
        if(!denied)draftRestore();
        $('task-notify').checked=false;
        window.DesktopInteractions.failed(id,error.message,()=>select(id,{save:!denied,taskId}),denied);
      }
      throw error;
    } finally { if (epoch === selectionEpoch) { $('task-form').inert = scope.mode === 'legacy';window.DesktopInteractions?.finish(id); } }
  }
  async function newAnalysis() {
    if (AnalysisMode.active() === 'legacy') await switchMode('standard');
    saveDraft();
    const start = AnalysisMode.capture();
    await ensureBrowserMemory();
    if (!AnalysisMode.current({...start, key: memoryKey})) return;
    const scope = AnalysisMode.capture(), expected = revision(scope.mode);
    const item = await api('conversations', 'POST', {}, undefined, scope);
    if (!AnalysisMode.current(scope) || expected !== revision(scope.mode)) return;
    await select(item.id, {save: false});
    if (!AnalysisMode.current(scope)) return;
    heading('新建分析');
    $('conversation-message').focus();
  }
  function attachConversation(id) {
    selected = id;
    if (![...$('conversation-id').options].some(option => option.value === id)) $('conversation-id').add(new Option('分析会话', id));
    $('conversation-id').value = id;
    renderTurns();
  }
  async function submitted(resetDraft) {
    const epoch = selectionEpoch;
    window.DesktopInteractions?.reset();
    document.body.classList.remove('report-dismissed');
    if (resetDraft) {
      $('task-notify').checked = false;
      taskControlsDirty = false;
      window.KnowledgeUI?.reset();
      for (const id of ['conversation-message', 'remember-format', 'remember-text']) $(id).value = '';
      $('prediction-editor').open = false;
      $('task-data').value = '{}';
      window.ForecastUI?.restore({});
      saveDraft();
      draftBanner(null);
    }
    await historyPage();
    if (epoch !== selectionEpoch) return;
    await sessions();
    if (epoch === selectionEpoch) heading(`${turns.at(-1)?.prediction?.subject || '预测'} · 分析会话`);
  }
  function task(value) {
    window.AnalysisInput?.observe(value);
    if (displayed?.id !== value.id) {
      $('mail-live').replaceChildren();
      $('knowledge-report-evidence')?.remove();
    }
    displayed = value;
    targetTask = value.id;
    rememberPosition();
    const state = TASK_STATE[value.status.state] || value.status.state;
    const result = value.artifacts?.[0]?.parts?.[0]?.data;
    $('report-open').disabled = false;
    if (['submitted', 'working'].includes(value.status.state) && !document.body.classList.contains('report-dismissed')) inspector(true);
    $('result-summary').textContent = result?.workflow_debug ? state + ' · 单节点调试' : result?.analysis
      ? `${state} · ${result.analysis?.status === 'degraded' ? '分析已降级' : '报告已生成'} · ${MAIL_STATE[result.mail?.status || 'not_requested'] || result.mail?.status}`
      : state;
    $('workbench-intro').hidden = true;
    if (result || value.status.state === 'failed') {
      if (!document.body.classList.contains('report-dismissed')) inspector(true);
      const host = $('inspector-actions');
      host.replaceChildren();
      if (result?.analysis) {
        if (result.analysis?.report_renderer) host.append(action('预览渲染页面', () => previewPage(value.id)));
        host.append(action('下载 HTML 报告', () => download('report', 'html')), action('下载分析 JSON', () => download('analysis', 'json')));
        if (result.knowledge) host.append(action('查看知识证据', () => window.KnowledgeUI.evidence(result.knowledge)));
        host.append(action('刷新投递状态', async () => {
          const scope = AnalysisMode.capture();
          const status = await api(`tasks/${value.id}/mail`, 'GET', undefined, undefined, {...scope, mode: taskMode(value)});
          if (!AnalysisMode.current(scope) || displayed?.id !== value.id) return;
          const panel = $('mail-live');
          panel.replaceChildren();
          text(panel, 'h3', '最新投递状态');
          text(panel, 'p', MAIL_STATE[status.status] || status.status);
          text(panel, 'p', MAIL_NOTE[status.status] || '请按实际回执核对。', 'hint');
          if (status.attempts != null) text(panel, 'p', `尝试次数 ${status.attempts} · 下次重试 ${status.next_attempt ? fmt(status.next_attempt) : '—'}`, 'hint');
        }));
      }
    }
    $('task-delete').hidden = taskMode(value) === 'legacy' || !['completed', 'failed', 'canceled'].includes(value.status.state);
  }
  async function previewPage(id) {
    const scope = AnalysisMode.capture();
    const response=await fetch(`/api/tasks/${id}/report`,{headers:{'X-Memory-Key':scope.key, 'X-Analysis-Mode': displayedTaskMode()}});
    if(!response.ok)throw new Error('无法读取本次渲染页面。');
    const html=await response.text();
    if(displayed?.id!==id||!AnalysisMode.current(scope)||document.querySelector('.report-page-preview[open]'))return;
    const dialog=document.createElement('dialog');dialog.className='plugin-dialog report-page-preview';
    dialog.setAttribute('aria-label','渲染页面预览');
    const frame=document.createElement('iframe');frame.title='渲染页面';frame.setAttribute('sandbox','');
    frame.srcdoc=html.replace(/<style>[\s\S]*?<\/style>/,'<link rel="stylesheet" href="/style.css">');
    const close=action('关闭预览',()=>dialog.close());
    dialog.append(close,frame);dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    document.body.append(dialog);dialog.showModal();
  }
  async function download(kind, extension) {
    const scope = AnalysisMode.capture(), id = displayed.id;
    const response = await fetch(`/api/tasks/${id}/${kind}`, {headers: {'X-Memory-Key': scope.key, 'X-Analysis-Mode': displayedTaskMode()}});
    if (!response.ok) { const error = await response.json(); throw new Error(error.error?.message || '下载失败'); }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = `analysis-${id}.${extension}`;
    if (AnalysisMode.current(scope) && displayed?.id === id) link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function record(value) {
    const mode = taskMode(value);
    if (mode !== AnalysisMode.active()) {
      if (window.DesktopWorkbench) window.DesktopWorkbench.setMode(mode === 'professional' ? 'focus' : mode === 'legacy' ? 'legacy' : 'hall', {read: false});
      else switchMode(mode, {read: false});
    }
    changeSelection();
    const scope = AnalysisMode.capture(), epoch = ++selectionEpoch;
    const cid = taskBrief(value).conversation_id;
    try {
      if (cid && cid !== selected && memoryKey) {
        const data = await api('conversations/' + cid, 'GET', undefined, undefined, scope).catch(error => {
          if (!/NOT_FOUND|FORBIDDEN/.test(error.message)) throw error;
        });
        if (!AnalysisMode.current(scope) || epoch !== selectionEpoch) return;
        if (data) {
          await select(cid, {taskId: value.id, prefetched: data});
          if (AnalysisMode.current(scope) && currentTask === value.id && mode === 'professional') window.DesktopWorkbench?.acceptWorkflow(value);
          return;
        }
      }
      document.body.classList.remove('report-dismissed');
      showView('analysis');
      displayTask(value);
      if (mode === 'professional') window.DesktopWorkbench?.acceptWorkflow(value);
      if (value.artifacts?.length || value.status.state === 'failed') inspector(true);
      await historyPage();
    } catch (error) {
      if (AnalysisMode.current(scope)) notice(error.message, true);
    }
  }
  function view(name) {
    const previous = document.body.dataset.view;
    if (previous === 'analysis' && name !== 'analysis') saveUI();
    if (name !== 'analysis') document.body.classList.remove('analysis-composer-visible');
    else document.body.classList.add('analysis-composer-visible');
    document.body.classList.toggle('dify-knowledge-view', name === 'knowledge');
    if (name === 'knowledge') document.body.classList.remove('desktop-nav-collapsed');
    $('session-menu').open = false;
    window.PonyOffice?.view(name);
    document.body.dataset.view = name;
    window.DesktopPoll?.view(name);
    document.body.classList.remove('sidebar-open');
    $('sidebar-toggle').setAttribute('aria-expanded', 'false');
    if (name !== 'analysis') inspector(false);
    else if (previous !== 'analysis' && AnalysisMode.read('ui')) restoreUI(AnalysisMode.read('ui'));
    else if (displayed && !document.body.classList.contains('report-dismissed') && !$('report-open').disabled) inspector(true);
    if (name === 'knowledge') window.KnowledgeUI?.load();
    const titles = {records: '任务记录', settings: '设置', memory: '记忆', knowledge: '知识库', overview: '使用引导', tools: '工具中心'};
    $('workspace-title').textContent = titles[name] || $('analysis-title').textContent;
  }
  function saveFile(value, filename) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function switchMode(mode, {initial = false, read = true} = {}) {
    if (!ready || (!initial && mode === AnalysisMode.active())) return;
    if (!initial) {
      window.ComposerControls?.close();
      saveDraft();
      if (document.body.dataset.view === 'analysis') saveUI();
      rememberPosition();
      window.MailRecipients?.close();
      window.DesktopWorkbench?.closeDialogs();
    }
    window.DesktopPoll?.stop();
    clearTimeout(noticeTimer); $('notice').hidden = true;
    AnalysisMode.activate(mode);
    ++sessionEpoch;
    const epoch = ++selectionEpoch, scope = AnalysisMode.capture();
    window.DesktopSessions?.identityChanged();
    window.DesktopInteractions?.reset();
    clearTask(); clearFollowup(); clearTimeout(draftTimer);
    turns = []; turnCursor = sessionCursor = null;
    $('conversation-id').replaceChildren(new Option('独立任务', ''));
    const position = AnalysisMode.read('position') || {};
    const ui = AnalysisMode.read('ui');
    attachConversation(memoryKey ? (position.conversation || '') : '');
    targetTask = position.task || null;
    resetPredictionInput();
    if (selected && mode !== 'legacy') AnalysisMode.importLegacy(draftKey(selected), mode, DRAFT_KEY + '.' + selected);
    const hasDraft = mode !== 'legacy' && draftRestore();
    $('task-form').inert = mode === 'legacy';
    $('analysis-send').disabled = pendingSubmissions.has(mode);
    heading(mode === 'legacy' ? '历史会话' : '新建分析');
    $('conversation-summary').textContent = '';
    document.body.classList.remove('report-dismissed');
    if (!ui) {
      details().forEach(item => { item.open = false; });
      window.AnalysisInput?.open('progress', false);
      expandReport(false);
      window.DesktopWorkbench?.historyOpen(false);
    }
    restoreUI(ui);
    if (submitErrors.has(mode)) notice(submitErrors.get(mode), true);
    window.ComposerControls?.update();
    refreshMemory().catch(error => { if (AnalysisMode.current(scope)) notice(error.message, true); });
    if (!read) return;
    try {
      const session = await historyPage();
      if (epoch !== selectionEpoch) return;
      const last = turns.at(-1);
      window.AnalysisInput?.restorePrediction(last?.prediction);
      if (last?.prediction?.subject) {
        heading(`${last.prediction.subject} · 分析会话`);
        if (!hasDraft && !$('p-subject').value && !$('conversation-message').value) {
          $('task-data').value = JSON.stringify({prediction:last.prediction});
          syncForm(true);
          $('task-data').value = '{}';
        }
      }
      const pending = AnalysisMode.read('pending-run');
      const id = pending?.conversation === selected ? session?.task || targetTask : targetTask || session?.task;
      if (ui?.history) window.DesktopWorkbench?.historyOpen(true);
      if (!id) return;
      const value = await api('tasks/' + id, 'GET', undefined, undefined, mode === 'legacy' ? undefined : scope);
      if (epoch !== selectionEpoch || !AnalysisMode.current(scope) || currentTask) return;
      displayTask(value);
      window.DesktopReport?.restore(ui?.reader);
    } catch (error) {
      if (epoch === selectionEpoch && AnalysisMode.current(scope)) {
        if (/NOT_FOUND|FORBIDDEN/.test(error.message)) {
          if (!displayed) targetTask = null;
          rememberPosition();
        }
        notice('未能恢复上次位置 · ' + error.message, true);
      }
    }
  }
  async function init() {
    ready = true;
    $('workspace-health').textContent = settings?.default_model_id ? '模型已配置' : '尚未选择分析模型';
    AnalysisMode.importLegacy(draftKey(''), 'standard', [DRAFT_KEY, 'spm.console.draft.v1']);
    AnalysisMode.importLegacy('template', 'standard', PREDICTION_TEMPLATE_KEY);
    if (AnalysisMode.canImportLegacy() && !AnalysisMode.read('position-imported', 'shared')) {
      try {
        const old = JSON.parse(sessionStorage.getItem('stock_predict_mailer.workbench.position') || 'null');
        if (old) {
          const [conversation, task] = await Promise.all([
            old.conversation && api('conversations/' + old.conversation).catch(() => null),
            old.task && api('tasks/' + old.task).catch(() => null)
          ]);
          const mode = task && taskMode(task);
          if (conversation && !AnalysisMode.read('position', conversation.mode)) {
            AnalysisMode.write('position', {conversation:conversation.id, task:mode === conversation.mode ? task.id : null}, conversation.mode);
          }
          if (mode && !AnalysisMode.read('position', mode)) AnalysisMode.write('position', {task:task.id}, mode);
        }
      } catch (_) { /* The old position may belong to a different workspace. */ }
      AnalysisMode.write('position-imported', true, 'shared');
    }
    await switchMode(AnalysisMode.active(), {initial: true});
    window.DesktopWorkbench?.resumeWorkspace();
    window.KnowledgeUI?.init();
  }
  function identityChanged() {
    if (!ready) return;
    window.DesktopSessions?.identityChanged();
    window.DesktopRecords?.identityChanged();
    ++selectionEpoch; selected = ''; turns = []; clearTask(); clearFollowup(); renderTurns();
    resetPredictionInput();
    $('task-form').inert = false;
    window.DesktopInteractions?.reset();
    window.KnowledgeUI?.identityReset();
    $('conversation-id').value = '';
    $('knowledge-detail').hidden = true;
    $('knowledge-results').replaceChildren();
    $('knowledge-configs').replaceChildren();
    $('knowledge-indexes').replaceChildren();
    heading('新建分析');
    AnalysisMode.write('position', null);
    sessions().catch(error => notice(error.message, true));
  }
  // Keep the existing form and report renderers; relocate them without replacing their IDs.
  $('inspector-content').append($('report'));
  const live = document.createElement('section'); live.id = 'mail-live'; $('inspector-content').append(live);
  $('workbench-runtime').append($('task-status'), $('task-progress'));
  const tools = document.createElement('div'); tools.id = 'conversation-tools'; tools.className = 'actions conversation-tools'; tools.hidden = true;
  const removeConversation = action('删除会话', async () => {
    if (!confirm('删除会话消息和摘要？长期记忆及历史任务报告会保留。运行中的会话需先取消任务。')) return;
    const id = selected, scope = AnalysisMode.capture();
    await api('conversations/' + id, 'DELETE', undefined, undefined, scope);
    draftWrite(null, id, scope.mode);
    const position = AnalysisMode.read('position', scope.mode);
    if (position?.conversation === id) AnalysisMode.write('position', null, scope.mode);
    if (!AnalysisMode.current(scope)) return;
    window.DesktopSessions?.removed(id);
    if (selected !== id) { await refreshMemory(); return; }
    changeSelection();
    clearTimeout(draftTimer); ++selectionEpoch; selected = ''; turns = []; $('conversation-id').value = '';
    clearTask(); clearFollowup(); resetPredictionInput(); renderTurns(); heading('新建分析');
    window.DesktopInteractions?.reset();
    await refreshMemory(); rememberPosition();
    window.DesktopInteractions?.afterDelete();
  });
  tools.append(action('导出会话', async () => {
    const id = selected, scope = AnalysisMode.capture();
    const data = await api(`conversations/${id}/export`, 'GET', undefined, undefined, scope);
    if (AnalysisMode.current(scope)) saveFile(data, `conversation-${id}.json`);
  }), removeConversation);
  $('analysis-title').closest('.page-head').after(tools);
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
  const form = $('task-form');
  const cards = [...form.querySelectorAll(':scope > .card')].filter(card => !card.classList.contains('forecast-editor'));
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
  function expandReport(expanded) {
    document.body.classList.toggle('inspector-expanded', expanded);
    $('report-expand').setAttribute('aria-pressed', String(expanded)); $('report-expand').textContent = expanded ? '收起' : '展开';
  }
  $('report-expand').onclick = () => expandReport(!document.body.classList.contains('inspector-expanded'));
  $('sidebar-toggle').onclick = () => $('sidebar-toggle').setAttribute('aria-expanded', String(document.body.classList.toggle('sidebar-open')));
  $('conversation-id').onchange = safe(() => {
    const id = $('conversation-id').value;
    $('conversation-id').value = selected;
    return id ? select(id) : newAnalysis();
  });
  for (const id of ['task-complexity', 'task-goal', 'task-effort']) $(id).addEventListener('change', () => { taskControlsDirty = true; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { inspector(false); document.body.classList.add('report-dismissed'); document.body.classList.remove('sidebar-open'); $('sidebar-toggle').setAttribute('aria-expanded', 'false'); } });
  document.addEventListener('click', event => {
    if (!event.target.closest?.('[data-desktop-mode]') && !$('session-menu').contains(event.target)) $('session-menu').open = false;
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') $('session-menu').open = false; });
  function persist() {
    if (!ready) return;
    saveDraft(); rememberPosition();
    if (document.body.dataset.view === 'analysis') saveUI();
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') persist(); });
  window.addEventListener('pagehide', persist);
  const legacyHistory = action('历史会话', () => {
    if (AnalysisMode.active() !== 'legacy') {
      if (window.DesktopWorkbench) window.DesktopWorkbench.setMode('legacy');
      else switchMode('legacy');
    }
    $('session-menu').open = true;
  });
  $('sessions-more').after(legacyHistory);
  async function removedTask(id, scope) {
    forgetRecord(id);
    const position = AnalysisMode.read('position', scope.mode);
    if (position?.task === id) AnalysisMode.write('position', {...position, task: null}, scope.mode);
    if (!AnalysisMode.current(scope) || displayed?.id !== id) return;
    clearTask(); rememberPosition(); await historyPage();
  }
  const deleteTask = action('删除任务记录', async () => {
    const value = displayed, scope = AnalysisMode.capture();
    if (!value || !confirm('删除此任务记录、进度和报告？')) return;
    await api('tasks/' + value.id, 'DELETE', undefined, undefined, {...scope, mode: taskMode(value)});
    await removedTask(value.id, scope);
  });
  deleteTask.id = 'task-delete'; deleteTask.hidden = true;
  $('report-expand').before(deleteTask);
  return {init, view, task, submitted: safe(submitted), attachConversation, record, removedTask, sessions, identityChanged, inspector, switchMode,
    revision, result: () => displayed, resultMode: () => displayed && taskMode(displayed)};
})();
