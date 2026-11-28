/* Desktop reading layer over the original report. No new report generation. */
window.DesktopReport = (() => {
  const desktop = matchMedia('(min-width: 761px)'), report = $('report');
  const inspector = $('report-inspector'), heading = inspector.querySelector('.inspector-head'), tabs = inspector.querySelector('.analysis-tabs');
  const focusAttributes = new Map();
  let task = null, tools = null, header = null, pane = 'progress', overview = false;
  let source = null, selected = [], originRecord = null, overridesExpand = false, officeInert = null;
  const analysis = () => ['failed', 'canceled'].includes(task?.status.state) ? null : task?.artifacts?.[0]?.parts?.[0]?.data?.analysis;
  const result = () => task?.artifacts?.[0]?.parts?.[0]?.data;
  const factId = ref => String(ref).replace(/^fact:/, '');
  const visible = () => desktop.matches && pane === 'report' && !$('report-inspector').hidden && Boolean(analysis());
  const make = (tag, value, className) => {
    const node = document.createElement(tag);
    if (value != null) node.textContent = value;
    if (className) node.className = className;
    return node;
  };
  const button = (label, callback, className = '') => {
    const node = make('button', label, className); node.type = 'button'; node.onclick = callback; return node;
  };
  function markFocus(node) {
    if (!focusAttributes.has(node)) focusAttributes.set(node, node.getAttribute('tabindex'));
    node.tabIndex = -1;
    node.focus({preventScroll: true});
    node.scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  }
  function clearSelection() {
    for (const node of selected) node.classList.remove('desktop-evidence-selected');
    selected = []; source = null;
    if (tools) tools.querySelector('.desktop-evidence-trail').hidden = true;
  }
  function restoreOriginal() {
    clearSelection();
    report.querySelectorAll('.desktop-report-added').forEach(node => node.remove());
    for (const [node, value] of focusAttributes) {
      if (value === null) node.removeAttribute('tabindex'); else node.setAttribute('tabindex', value);
    }
    focusAttributes.clear();
  }
  function setReading(open) {
    const next = Boolean(open && visible());
    const changed = document.body.classList.contains('desktop-report-reading') !== next;
    document.body.classList.toggle('desktop-report-reading', next);
    const office = document.querySelector('.pony-office');
    if (next && officeInert === null) { officeInert = office.inert; office.inert = true; }
    else if (!next && officeInert !== null) { office.inert = officeInert; officeInert = null; }
    syncExpand();
    if (changed) window.AnalysisInput.layout();
  }
  function syncExpand() {
    const expand = $('report-expand');
    if (visible()) {
      expand.textContent = document.body.classList.contains('desktop-report-reading') ? '退出阅读' : '专注阅读';
      expand.setAttribute('aria-pressed', String(document.body.classList.contains('desktop-report-reading')));
      overridesExpand = true;
    } else if (overridesExpand) {
      const expanded = document.body.classList.contains('inspector-expanded');
      expand.textContent = expanded ? '收起' : '展开'; expand.setAttribute('aria-pressed', String(expanded)); overridesExpand = false;
    }
  }
  function setOverview(value) {
    overview = Boolean(value && analysis());
    document.body.classList.toggle('desktop-report-overview', desktop.matches && overview);
    if (tools) for (const node of tools.querySelectorAll('[data-report-mode]')) node.setAttribute('aria-pressed', String((node.dataset.reportMode === 'overview') === overview));
  }
  function reveal(node) {
    if (!node?.isConnected) return;
    setOverview(false); markFocus(node);
  }
  function target(ref) {
    if (String(ref).startsWith('prediction:')) return $('sec-prediction');
    return [...report.querySelectorAll('.fact-list li')].find(node => node.dataset.id === factId(ref));
  }
  function claimsFor(id) {
    const nodes = [...report.querySelectorAll('#sec-inferences .claim')];
    return (analysis()?.inferences || []).flatMap((item, index) => (item.evidence_ids || []).some(ref => factId(ref) === id) && nodes[index] ? [nodes[index]] : []);
  }
  function selectEvidence(destination, from, related, label) {
    clearSelection(); source = from;
    selected = [...new Set([destination, ...related])].filter(Boolean);
    selected.forEach(node => node.classList.add('desktop-evidence-selected'));
    tools.querySelector('.desktop-evidence-trail').hidden = false;
    tools.querySelector('.desktop-evidence-label').textContent = label;
    reveal(destination);
  }
  function follow(ref, from) {
    const destination = target(ref);
    if (!destination) return;
    const related = String(ref).startsWith('prediction:') ? [] : claimsFor(factId(ref));
    selectEvidence(destination, from, related, String(ref).startsWith('prediction:') ? '已定位本报告的上游预测' : `已定位 ${factId(ref)} · ${related.length} 条推断引用`);
  }
  function reference(ref) {
    const node = button(String(ref).replace(/^fact:/, ''), () => follow(ref, node), 'desktop-summary-ref');
    if (!target(ref)) { node.disabled = true; node.title = '此引用未在当前事实列表中展开，请对照完整报告核查。'; }
    return node;
  }
  function overviewText() {
    const data = analysis();
    if (!data) return '';
    const lines = [`${data.prediction?.subject || '预测'} · 报告阅读重点`, '摘自当前报告，未生成新结论。',
      `任务：${TASK_STATE[task.status.state] || task.status.state}；分析：${data.status === 'degraded' ? '降级' : data.status === 'ok' ? '正常' : data.status}`,
      data.prediction?.synthetic ? '合成数据，不代表真实验证。' : '数据来源为上游声明，未独立核实。'];
    for (const [title, items] of [['Agent 推断', data.inferences], ['风险', data.risks], ['限制与未知', data.limitations]]) {
      if (!items?.length) continue;
      lines.push(title);
      for (const item of items.slice(0, 2)) lines.push(typeof item === 'string' ? item : `${item.text}${item.evidence_ids?.length ? ' [依据 ' + item.evidence_ids.join('、') + ']' : ''}`);
      if (items.length > 2) lines.push(`其余 ${items.length - 2} 条请查看完整报告。`);
    }
    const mail = result()?.mail;
    lines.push(`邮件：${mail ? MAIL_STATE[mail.status] || mail.status : '未请求通知'}`, mail ? MAIL_NOTE[mail.status] || '未知状态，请按原始回执核对，不假定成功。' : '本轮未请求投递。');
    return lines.join('\n');
  }
  async function copyOverview() {
    const content = overviewText();
    const copiedTask = task?.id;
    if (!content) return;
    try { await navigator.clipboard.writeText(content); notice('报告重点已复制。'); }
    catch (_) {
      if (!visible() || task?.id !== copiedTask || !$('desktop-report-overview')) return;
      let field = report.querySelector('.desktop-copy-fallback');
      if (!field) { field = make('textarea', null, 'desktop-report-added desktop-copy-fallback'); field.readOnly = true; field.rows = 7; field.setAttribute('aria-label', '报告重点纯文本，可手动复制'); $('desktop-report-overview').append(field); }
      field.value = content; field.focus(); field.select(); notice('请复制已选中的报告重点。');
    }
  }
  function renderOverview() {
    const data = analysis();
    const brief = make('section', null, 'desktop-report-added desktop-report-brief'); brief.id = 'desktop-report-overview';
    brief.append(make('h3', '阅读重点'), make('p', '摘自本报告，未生成新结论。事实来源与 Agent 推断需分别核对。', 'hint'));
    const states = make('div', null, 'desktop-report-states');
    for (const value of [`任务 · ${TASK_STATE[task.status.state] || task.status.state}`, `分析 · ${data.status === 'degraded' ? '降级' : data.status === 'ok' ? '正常' : data.status}`, data.prediction?.synthetic ? '合成数据' : '上游声明数据']) states.append(make('span', value));
    brief.append(states);
    if (data.status === 'degraded') brief.append(make('p', '分析已降级，请核对限制与执行过程。', 'note warn'));
    for (const [title, items] of [['Agent 推断', data.inferences], ['风险', data.risks], ['限制与未知', data.limitations]]) {
      if (!items?.length) continue;
      const section = make('div', null, 'desktop-brief-section');
      section.append(make('h4', `${title} · ${items.length > 2 ? '前 2 条，共 ' + items.length + ' 条' : items.length + ' 条'}`));
      const list = make('ul');
      for (const item of items.slice(0, 2)) {
        const row = make('li'); row.append(make('span', typeof item === 'string' ? item : item.text));
        for (const ref of item.evidence_ids || []) row.append(document.createTextNode(' '), reference(ref));
        list.append(row);
      }
      section.append(list); brief.append(section);
    }
    const mail = result()?.mail;
    brief.append(make('p', `邮件 · ${mail ? MAIL_STATE[mail.status] || mail.status : '未请求通知'}。${mail ? MAIL_NOTE[mail.status] || '未知状态，请按原始回执核对，不假定成功。' : '本轮未请求投递。'}`, 'desktop-report-mail hint'));
    const destinations = make('div', null, 'desktop-report-jumps');
    for (const [id, label] of [['inferences', '完整推断'], ['risks', '全部风险'], ['limits', '限制与未知'], ['facts', '来源事实']]) if ($('sec-' + id)) destinations.append(button(label, () => reveal($('sec-' + id))));
    brief.append(destinations);
    (report.querySelector('.report-head') || report.firstElementChild).after(brief);
    for (const fact of report.querySelectorAll('.fact-list li')) {
      const related = claimsFor(fact.dataset.id);
      if (!related.length) continue;
      const back = button(`查看引用推断 · ${related.length} 条`, () => selectEvidence(related[0], back, [fact, ...related], `${fact.dataset.id} 被 ${related.length} 条推断引用`), 'desktop-report-added desktop-fact-return');
      fact.append(back);
    }
  }
  function backToRecords() {
    if (!originRecord || originRecord.task !== task?.id) return;
    const saved = originRecord;
    setReading(false); showView('records'); window.DesktopRecords?.returnToTasks();
    requestAnimationFrame(() => {
      const row = [...$('record-list').querySelectorAll('.task-row')].find(node => node.dataset.taskId === saved.task);
      row?.focus({preventScroll: true}); window.scrollTo({top: saved.scroll, behavior: 'auto'});
    });
  }
  function ensureTools() {
    if (tools) return;
    tools = make('section', null, 'desktop-report-tools'); tools.setAttribute('aria-label', '报告阅读工具');
    const modes = make('div', null, 'desktop-report-modes'); modes.setAttribute('role', 'group'); modes.setAttribute('aria-label', '报告内容范围');
    for (const [key, label] of [['full', '完整报告'], ['overview', '只看重点']]) {
      const node = button(label, () => setOverview(key === 'overview')); node.dataset.reportMode = key; modes.append(node);
    }
    tools.append(modes, button('复制重点', copyOverview, 'desktop-report-copy'), button('返回任务记录', backToRecords, 'desktop-report-back'));
    const trail = make('div', null, 'desktop-evidence-trail'); trail.hidden = true;
    const label = make('span', null, 'desktop-evidence-label'); label.setAttribute('role', 'status');
    trail.append(label, button('返回引用处', () => { const from = source; clearSelection(); reveal(from); }), button('清除定位', clearSelection)); tools.append(trail);
    $('analysis-pane-report').prepend(tools);
  }
  function render(value) {
    const changed = task?.id !== value.id;
    if (changed) { setReading(false); overview = false; }
    restoreOriginal(); task = value;
    if (!desktop.matches) return;
    ensureTools();
    tools.hidden = !analysis() && !(task.status.state === 'failed' && originRecord?.task === task.id);
    tools.querySelector('.desktop-report-modes').hidden = !analysis();
    tools.querySelector('.desktop-report-copy').hidden = !analysis();
    tools.querySelector('.desktop-report-back').hidden = originRecord?.task !== task.id;
    if (analysis()) renderOverview();
    setOverview(overview); syncExpand();
  }
  function install() {
    if (!desktop.matches) {
      setReading(false); restoreOriginal(); overview = false;
      document.body.classList.remove('desktop-report-overview');
      if (tools) tools.hidden = true;
      if (header?.isConnected) { header.before(heading, tabs); header.remove(); }
      syncExpand(); return;
    }
    if (!header) {
      header = make('div', null, 'desktop-inspector-header');
      const resize = new ResizeObserver(() => {
        if (!desktop.matches || !header.isConnected) return;
        const height = Math.max(0, header.offsetHeight - 24) + 'px';
        if (inspector.style.getPropertyValue('--desktop-report-header') !== height) inspector.style.setProperty('--desktop-report-header', height);
      });
      resize.observe(header);
    }
    if (!header.isConnected) { inspector.prepend(header); header.append(heading, tabs); }
    if (task) render(task);
  }
  $('record-list').addEventListener('click', event => {
    const row = event.target.closest('.task-row');
    if (desktop.matches && row) originRecord = {task: row.dataset.taskId, scroll: window.scrollY};
  }, true);
  report.addEventListener('click', event => {
    if (!desktop.matches) return;
    const ref = event.target.closest('#sec-inferences a.ref');
    if (ref) {
      const claim = ref.closest('.claim');
      const index = [...report.querySelectorAll('#sec-inferences .claim')].indexOf(claim);
      const refs = [...claim.querySelectorAll('a.ref')];
      const id = analysis()?.inferences?.[index]?.evidence_ids?.[refs.indexOf(ref)];
      if (id && target(id)) { event.preventDefault(); event.stopImmediatePropagation(); follow(id, ref); }
    } else if (event.target.closest('.report-toc button')) setOverview(false);
  }, true);
  $('report-expand').addEventListener('click', event => {
    if (visible()) { event.preventDefault(); event.stopImmediatePropagation(); setReading(!document.body.classList.contains('desktop-report-reading')); }
  }, true);
  desktop.addEventListener('change', install);
  install();
  return {
    render,
    snapshot() { return {id:task?.id, overview, reading:document.body.classList.contains('desktop-report-reading')}; },
    restore(value) {
      if (!value?.id || value.id !== task?.id) return;
      setOverview(value.overview);
      setReading(value.reading);
    },
    panel(value) { pane = value; if (value !== 'report') setReading(false); syncExpand(); },
    visibility(open) { if (!open) setReading(false); else syncExpand(); },
    clear() { setReading(false); restoreOriginal(); task = null; overview = false; document.body.classList.remove('desktop-report-overview'); if (tools) tools.hidden = true; syncExpand(); }
  };
})();
