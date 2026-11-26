/* Desktop work lists over existing owner-scoped knowledge and forecast APIs. */
window.DesktopLibrary = (() => {
  const desktop = matchMedia('(min-width: 761px)');
  const states = {pending:'排队', processing:'处理中', review:'待审阅', failed:'失败', ready:'已发布', rejected:'已拒绝', deleting:'等待删除'};
  let knowledgeView = null, queueView = null, queueStale = false, listing = null, currentDocument = null;
  let forecastView = null, forecastItem = null, previewView = null, searchView = null, searchBusy = false;
  const openDetails = new Map();
  const make = (tag, value, cls) => { const node = document.createElement(tag); if (value != null) node.textContent = value; if (cls) node.className = cls; return node; };
  const button = (label, callback, cls = '') => { const node = make('button', label, cls); node.type = 'button'; node.onclick = callback; return node; };
  const safe = callback => async () => { try { await callback(); } catch (error) { notice(error.message, true); } };
  function compare(open) {
    const host = $('knowledge-detail');
    if (open) {
      for (const node of host.querySelectorAll('.review-group .source-excerpt details')) { if (!openDetails.has(node)) openDetails.set(node, node.open); node.open = true; }
    } else { for (const [node, previous] of openDetails) node.open = previous; openDetails.clear(); }
    host.classList.toggle('desktop-source-compare', desktop.matches && open);
    host.querySelector('.desktop-compare-toggle')?.setAttribute('aria-pressed', String(open));
  }
  function applyName() {
    if (!knowledgeView || !desktop.matches) return;
    if ($('desktop-knowledge-scope').dataset.loading === 'true') return;
    const query = $('desktop-knowledge-query').value.trim().toLowerCase(); let count = 0;
    for (const row of $('knowledge-list').querySelectorAll('.document-row')) {
      const item = listing?.items.find(value => value.id === row.dataset.documentId);
      row.hidden = Boolean(query && !`${item?.logical || ''} ${item?.filename || ''}`.toLowerCase().includes(query));
      if (!row.hidden) ++count;
    }
    const total = listing?.catalog.total;
    $('desktop-knowledge-scope').textContent = `名称筛选仅作用于已载入版本：显示 ${count} / ${listing?.items.length || 0}${total == null ? '' : `；当前状态共 ${total} 个版本`}。`;
    $('desktop-knowledge-no-match').hidden = !(query && count === 0 && listing?.items.length);
  }
  function paintKnowledge() {
    if (!knowledgeView || !desktop.matches) return;
    for (const node of knowledgeView.querySelectorAll('[data-knowledge-status]')) {
      const status = node.dataset.knowledgeStatus;
      const count = status ? queueView?.counts?.[status] : queueView?.total;
      node.textContent = `${states[status] || '全部'}${count == null ? '' : ' ' + count}`;
      node.setAttribute('aria-pressed', String(status === window.KnowledgeUI.filterStatus()));
    }
    const worker = queueView?.worker;
    $('desktop-knowledge-worker').textContent = queueStale ? '队列暂未更新，以下计数为上次读取结果。' : !worker ? '正在读取当前私有空间的队列状态…' : worker.online ? `清洗进程在线${worker.state === 'busy' ? ' · 正在处理' : ' · 空闲'}` : '清洗进程未在线；上传和批准后仍需等待处理。';
    applyName();
  }
  function reviewCount() {
    const group = $('knowledge-detail').querySelector('.review-group'), status = $('desktop-review-selection');
    if (!group || !status || !desktop.matches) return;
    const checks = [...group.querySelectorAll('input[type="checkbox"]')];
    status.textContent = `可核对 ${checks.filter(node => !node.disabled).length} 条 · 已选 ${checks.filter(node => node.checked && !node.disabled).length} 条 · 不可批准 ${checks.filter(node => node.disabled).length} 条。未勾选的候选不会发布。`;
  }
  function renderDocument() {
    if (!desktop.matches || !currentDocument || $('knowledge-detail').hidden) return;
    compare(false);
    const host = $('knowledge-detail'), {item, versions} = currentDocument;
    const review = host.querySelector('.review-group');
    host.querySelectorAll('.desktop-document-added').forEach(node => node.remove());
    const top = make('section', null, 'desktop-document-added desktop-document-workflow');
    top.dataset.documentId = item.id;
    const actions = make('div', null, 'actions');
    actions.append(make('strong', '版本与处理阶段'), button('返回资料列表', () => {
      window.KnowledgeUI.close();
      const row = [...$('knowledge-documents-list').querySelectorAll('[data-document-id]')].find(node => node.dataset.documentId === item.id);
      const target = row?.querySelector('button') || $('knowledge-documents-refresh');
      target.focus(); target.scrollIntoView({block:'center'});
    }, 'btn tiny'));
    if (review) actions.append(button('核对待审阅候选', () => {
      review.querySelector('input[type="checkbox"]:not(:disabled)')?.focus({preventScroll:true});
      review.scrollIntoView({block:'start',behavior:'smooth'});
    }, 'btn primary desktop-review-jump'));
    top.append(actions, make('p', `${states[item.status] || item.status} · ${item.active ? '当前活动版本，检索仍受截止日期控制' : '非活动版本，不代表当前检索版本'}`, 'hint'));
    const stages = [['received','接收'],['parsed','解析'],['chunked','切分'],['extracted','提取'],['reviewed','审阅'],['published','发布']];
    const list = make('ol', null, 'desktop-knowledge-stages');
    const step = item.status === 'review' ? 'reviewed' : item.step;
    for (const [key, label] of stages) { const node = make('li', label); if (key === step) node.setAttribute('aria-current', 'step'); list.append(node); }
    top.append(list, make('p', item.status === 'failed' ? `处理失败；最后记录在「${stages.find(([key]) => key === item.step)?.[1] || item.step}」阶段。` : '资料处理与发布分开进行；待审阅版本需要先核对候选。', 'hint'));
    if (versions.length > 1) {
      const nav = make('details', null, 'desktop-version-navigation'); nav.open = true; nav.append(make('summary', `切换资料版本 · ${versions.length} 个`));
      for (const version of versions) {
        const node = button(`${version.id.slice(0,8)} · ${states[version.status] || version.status}${version.active ? ' · 活动版本' : ''} · ${fmt(version.uploaded)}`, safe(() => window.KnowledgeUI.open(version.id)));
        node.dataset.versionId = version.id;
        node.disabled = version.id === item.id; if (node.disabled) node.setAttribute('aria-current', 'true'); nav.append(node);
      }
      top.append(nav);
    }
    if (review) {
      const controls = make('div', null, 'desktop-document-added desktop-review-controls');
      const selection = make('p', null, 'hint'); selection.id = 'desktop-review-selection'; selection.setAttribute('role','status');
      controls.append(selection, button('并排核对来源', () => compare(!host.classList.contains('desktop-source-compare')), 'btn tiny desktop-compare-toggle'));
      review.prepend(controls); reviewCount();
    }
    host.prepend(top);
  }
  function dirtySearch() {
    if (!desktop.matches || !searchView) return;
    if (searchBusy || $('knowledge-results').childElementCount || $('knowledge-answer-result').childElementCount) searchView.textContent = '检索条件已变化；下方如有内容仍为上次结果，请重新检索后使用。';
  }
  function paintForecasts() {
    if (!forecastView || !desktop.matches) return;
    for (const node of forecastView.querySelectorAll('[data-forecast-state]')) node.setAttribute('aria-pressed', String(node.dataset.forecastState === $('forecast-state').value));
    const rows = forecastItem?.list?.items;
    $('desktop-forecast-scope').textContent = rows ? `已载入 ${rows.length} 条预测，仅统计当前状态筛选范围${forecastItem.list.cursor != null ? '；仍有更早任务可读取' : ''}。到期不代表已验证。` : '等待本次预测列表读取完成。状态筛选会从服务重新读取。';
    const due = rows?.filter(item => item.state === 'due').sort((a,b) => Date.parse(a.target_at) - Date.parse(b.target_at))[0];
    $('desktop-forecast-next').disabled = !due;
    $('desktop-forecast-next').textContent = due ? `处理已载入待观测预测 · ${due.subject}` : '当前已载入范围没有待观测预测';
    $('desktop-forecast-next').onclick = due ? safe(async () => {
      await window.ForecastUI.openTask(due.task_id, false);
      if (desktop.matches && forecastItem?.tid === due.task_id && !$('forecast-detail').hidden) openObservation();
    }) : null;
  }
  function openObservation() {
    const details = $('forecast-detail').querySelector('.observation-preview');
    if (!details) return;
    details.open = true; $('observation-content').focus(); $('observation-content').scrollIntoView({block:'center'});
  }
  function renderForecastDetail() {
    if (!desktop.matches || !forecastItem?.view || $('forecast-detail').hidden) return;
    const host = $('forecast-detail'), {view} = forecastItem, p = view.record.prediction, d = view.record.definition;
    host.querySelectorAll('.desktop-forecast-added').forEach(node => node.remove());
    const top = make('section', null, 'desktop-forecast-added desktop-forecast-guide');
    top.append(make('h3', {pending:'待到期 · 先核对观测要求',due:'待观测 · 提供观测后可预览',evaluated:'已有正式回执 · 可单独预览其他观测'}[view.state] || String(view.state)));
    top.append(make('p', '只读预览 · 不保存评估回执，不覆盖已有档案或回执。来源与日历仍为提供方声明。', 'note'));
    const actions = make('div', null, 'actions');
    actions.append(button(view.state === 'due' ? '提供观测并预览' : '查看观测要求', openObservation, 'btn primary'), button('返回预测列表', () => { window.ForecastUI.close(); $('forecast-refresh').focus(); $('forecast-records').scrollIntoView({block:'start'}); }, 'btn'));
    top.append(actions);
    const format = make('details', null, 'desktop-observation-format');
    format.append(make('summary', 'JSON / CSV 格式参考（含占位符）'), make('p', '以下占位符不可直接预览。请从实际来源提供数值、可用时间和来源声明；本页不会把参考内容填入观测表单。', 'hint'));
    const template = {schema_version:'1',subject:p.subject,metric:d.metric,unit:d.unit,value:'<替换为 JSON 数字>',observed_at:d.target_at,available_at:'<实际可用时点，含时区>',source:'<实际来源声明>',synthetic:p.synthetic};
    format.append(make('h4','JSON 结构'), make('pre', JSON.stringify(template,null,2), 'mono'));
    const keys = Object.keys(template), quote = value => '"' + String(value).replaceAll('"','""') + '"';
    format.append(make('h4','CSV 固定字段，恰好一条观测'), make('pre', keys.join(',') + '\n' + keys.map(key => quote(template[key])).join(','), 'mono'));
    top.append(format); host.prepend(top);
  }
  function renderPreview() {
    if (!desktop.matches || !previewView?.output.isConnected || previewView.output.hidden || previewView.result.persisted !== false) return;
    const {result,view,output} = previewView, actual = result.observation, expected = view.record;
    output.querySelector('.desktop-observation-check')?.remove();
    const root = make('section', null, 'desktop-observation-check');
    root.append(make('h4','声明一致性核对 · 预览未保存'), make('p','这些检查核对字段一致性，不认证来源真实性；评分仍取决于到期与可用时点。','hint'));
    const checks = [
      ['标的',expected.prediction.subject,actual.subject], ['指标',expected.definition.metric,actual.metric], ['单位',expected.definition.unit,actual.unit],
      ['合成标记',expected.prediction.synthetic,actual.synthetic], ['目标观测时点',expected.definition.target_at,actual.observed_at]
    ];
    const list = make('dl',null,'desktop-match-list');
    for (const [label,wanted,value] of checks) {
      const matched = label === '目标观测时点' ? Date.parse(wanted) === Date.parse(value) : wanted === value;
      list.append(make('dt',label), make('dd',`${matched ? '一致' : '不一致'} · ${String(value)}`));
    }
    root.append(list); output.querySelector('h4').after(root);
  }
  function records() {
    const host = $('record-list'); host.querySelectorAll('.desktop-record-date').forEach(node => node.remove());
    if (!desktop.matches) return;
    let previous = '';
    for (const row of host.querySelectorAll('.task-row')) {
      const date = new Date(row.dataset.recordedAt);
      if (!Number.isFinite(date.getTime())) continue;
      const label = date.toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'});
      if (label !== previous) row.before(make('h3',`${label} · 状态记录时间`,'desktop-record-date'));
      previous = label;
    }
  }
  function resetKnowledge() {
    listing = null; queueView = null; queueStale = false; currentDocument = null; searchBusy = false; compare(false);
    $('knowledge-detail').querySelectorAll('.desktop-document-added').forEach(node => node.remove());
    if (knowledgeView) { $('desktop-knowledge-query').value = ''; $('desktop-knowledge-scope').textContent = ''; }
    if (searchView) searchView.textContent = '';
    paintKnowledge();
  }
  function forecastClosed() {
    if (forecastItem) { delete forecastItem.view; delete forecastItem.tid; }
    previewView = null; $('forecast-detail').querySelectorAll('.desktop-forecast-added,.desktop-observation-check').forEach(node => node.remove());
  }
  function install() {
    if (!desktop.matches) {
      document.body.classList.remove('desktop-library'); compare(false);
      if (knowledgeView) knowledgeView.hidden = true;
      if (forecastView) forecastView.hidden = true;
      if (searchView) searchView.hidden = true;
      $('knowledge-detail').querySelectorAll('.desktop-document-added').forEach(node => node.remove());
      $('knowledge-list').querySelectorAll('.document-row').forEach(node => { node.hidden = false; });
      $('forecast-detail').querySelectorAll('.desktop-forecast-added,.desktop-observation-check').forEach(node => node.remove());
      if (window.KnowledgeUI.filterStatus()) window.KnowledgeUI.filter('').catch(error => notice(error.message,true));
      records(); return;
    }
    if (!knowledgeView) {
      knowledgeView = make('section',null,'desktop-knowledge-worklist'); knowledgeView.setAttribute('aria-label','知识库处理清单');
      const actions = make('div',null,'section-head'); actions.append(make('h2','处理清单'),button('上传资料',() => { const form=$('knowledge-upload'); form.closest('details').open=true; $('knowledge-file').focus(); form.scrollIntoView({block:'start'}); },'btn primary'));
      const filters = make('div',null,'desktop-library-filters'); filters.setAttribute('role','group'); filters.setAttribute('aria-label','资料处理状态');
      for (const status of ['', 'review','pending','processing','failed','ready']) { const node = button(states[status] || '全部',safe(() => window.KnowledgeUI.filter(status))); node.dataset.knowledgeStatus=status; filters.append(node); }
      const worker = make('p',null,'hint'); worker.id='desktop-knowledge-worker'; worker.setAttribute('role','status');
      const field = make('label',null,'field'); field.append(make('span','按已载入资料名称筛选')); const input=make('input'); input.id='desktop-knowledge-query'; input.type='search'; input.placeholder='资料名称或文件名'; input.oninput=applyName; field.append(input);
      const scope=make('p',null,'hint'); scope.id='desktop-knowledge-scope'; scope.setAttribute('role','status');
      const empty=make('p','已载入版本中没有匹配名称；可清空名称或继续加载。','hint'); empty.id='desktop-knowledge-no-match'; empty.hidden=true;
      knowledgeView.append(actions,filters,worker,field,scope,empty); document.querySelector('[data-kb-pane="documents"]').prepend(knowledgeView);
      searchView=make('p','修改条件后重新检索，可核对截止日期与来源版本。','hint desktop-search-state'); searchView.setAttribute('role','status'); $('knowledge-search').after(searchView);
      $('knowledge-search').addEventListener('input',dirtySearch); $('knowledge-detail').addEventListener('change',reviewCount);
      forecastView=make('section',null,'desktop-forecast-worklist'); forecastView.setAttribute('aria-label','预测跟踪清单');
      const forecastFilters=make('div',null,'desktop-library-filters'); forecastFilters.setAttribute('role','group'); forecastFilters.setAttribute('aria-label','预测跟踪状态');
      for (const [state,label] of [['all','全部'],['pending','待到期'],['due','待观测'],['evaluated','已评估']]) { const node=button(label,()=>{ $('forecast-state').value=state; $('forecast-state').dispatchEvent(new Event('change')); }); node.dataset.forecastState=state; forecastFilters.append(node); }
      const caption=make('p',null,'hint'); caption.id='desktop-forecast-scope'; const next=button('',null,'btn'); next.id='desktop-forecast-next';
      forecastView.append(forecastFilters,caption,next); document.querySelector('.forecast-filter').before(forecastView);
    }
    document.body.classList.add('desktop-library'); knowledgeView.hidden=forecastView.hidden=searchView.hidden=false;
    paintKnowledge(); paintForecasts(); renderDocument(); renderForecastDetail(); renderPreview(); records();
  }
  desktop.addEventListener('change',install); install();
  return {
    knowledge(value) { listing=value; if (desktop.matches) { $('desktop-knowledge-scope').dataset.loading='false'; paintKnowledge(); } },
    knowledgeLoading() { if (desktop.matches && knowledgeView) { $('desktop-knowledge-scope').textContent='正在读取资料状态…'; $('desktop-knowledge-scope').dataset.loading='true'; paintKnowledge(); } },
    knowledgeError(message) { if (desktop.matches && knowledgeView) { $('desktop-knowledge-scope').textContent='资料读取失败：'+message+'。可使用原刷新按钮重试。'; $('desktop-knowledge-scope').dataset.loading='false'; } },
    queue(value) { queueView=value; queueStale=false; paintKnowledge(); }, queueError() { queueStale=true; paintKnowledge(); }, resetKnowledge,
    document(item,versions) { currentDocument={item,versions}; renderDocument(); },
    searchLoading(label) { searchBusy=true; if (desktop.matches && searchView) searchView.textContent=`正在${label}；下方如有内容仍为上次结果。`; },
    searchDiscarded() { searchBusy=false; dirtySearch(); },
    searchError(message) { searchBusy=false; if (desktop.matches && searchView) searchView.textContent=`读取失败：${message}。请重新检索；下方如有内容仍为上次结果。`; },
    searchRendered(host,data) { searchBusy=false; if (desktop.matches && searchView && ['knowledge-results','knowledge-answer-result'].includes(host.id)) searchView.textContent=`${host.id === 'knowledge-results' ? '检索' : '规则汇总'}结果已更新 · ${data.results?.length ?? data.citations?.length ?? 0} 段 · 截止 ${data.as_of || '今天'}。请对照来源声明核查。`; },
    forecasts(value) { forecastItem=value ? {...(forecastItem || {}),list:value} : null; paintForecasts(); },
    forecastDetail(tid,view) { forecastItem={...(forecastItem || {}),tid,view}; renderForecastDetail(); }, forecastClosed,
    preview(result,view,output) { previewView={result,view,output}; renderPreview(); }, records
  };
})();
