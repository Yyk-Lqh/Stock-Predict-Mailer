/* Private documents, evidence and review. Source text is always rendered as text. */
window.KnowledgeUI = (() => {
  let timer = null, epoch = 0, documents = [];
  const STATE = {pending: '已排队', processing: '处理中', ready: '已发布', review: '待审阅', failed: '处理失败', rejected: '已拒绝', deleting: '等待删除'};
  const STEP = {received: '已接收', parsed: '已解析', chunked: '已切分', extracted: '已提取', reviewed: '已审阅', published: '已发布'};
  const safe = fn => async event => { try { await fn(event); } catch (error) { notice(error.message, true); } };
  const section = document.createElement('section');
  section.className = 'view'; section.dataset.viewPane = 'knowledge'; section.hidden = true;
  section.innerHTML = `
    <div class="page-head"><p class="eyebrow">私有资料</p><h1>知识库</h1><p class="lede">整理来源，核对提取结果，让每条分析都有据可查。</p></div>
    <div id="knowledge-access" class="note"><p>知识库使用你的私有访问密钥，与会话共享访问身份。</p><button type="button" data-goto="memory" class="btn">创建或恢复访问密钥</button></div>
    <div id="knowledge-body" hidden>
      <div class="subnav"><button type="button" data-kb-tab="documents" class="active">资料与版本</button><button type="button" data-kb-tab="search">检索证据</button><button type="button" data-kb-tab="processing">处理与索引设置</button></div>
      <div data-kb-pane="documents">
        <div class="section-head"><h2>资料</h2><span id="knowledge-count" class="hint"></span><button type="button" id="knowledge-refresh" class="btn tiny">刷新</button></div>
        <details class="input-editor"><summary>上传资料 / 更新版本</summary><form id="knowledge-upload" class="card stack">
          <label class="field"><span>文件 · 最大 10 MiB</span><input id="knowledge-file" type="file" accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.json" required></label>
          <label class="field"><span>资料名称 <em>更新时使用相同名称</em></span><input id="knowledge-logical" maxlength="200" placeholder="留空时使用文件名"></label>
          <div class="grid-3"><label class="field"><span>来源</span><input id="knowledge-source" value="用户上传" maxlength="200"></label><label class="field"><span>文档日期</span><input type="date" id="knowledge-date"></label><label class="field"><span>实际可用日期</span><input type="date" id="knowledge-available" required></label></div>
          <p class="hint">支持 PDF、DOCX、TXT、Markdown、CSV、XLSX、JSON。上传后进入队列，由独立清洗进程处理。扫描件 OCR 暂不支持。</p>
          <div><button type="submit" class="btn primary">上传并排队</button></div>
        </form></details>
        <p class="hint worker-note">排队不代表入库完成。清洗进程须在本机单独启动，当前页面无法确认它是否在线。</p>
        <div id="knowledge-list"></div><div id="knowledge-detail" class="knowledge-detail" hidden></div>
      </div>
      <div data-kb-pane="search" hidden><form id="knowledge-search" class="stack"><label class="field"><span>查找证据</span><input id="knowledge-query" required maxlength="4000" placeholder="例如：营业收入、客户关系、供应链风险"></label><div class="grid-3"><label class="field"><span>截止日期</span><input id="knowledge-asof" type="date"></label><label class="field"><span>股票代码</span><input id="knowledge-stock" placeholder="600000.SH"></label><label class="field"><span>主体名称</span><input id="knowledge-entity" maxlength="200"></label></div><div><button type="submit" class="btn primary">检索证据</button></div></form><div id="knowledge-results" class="mt-26"></div></div>
      <div data-kb-pane="processing" hidden><p class="hint">规则清洗和关键词检索无需模型。语义清洗模型与向量模型独立配置；保存配置不会自动执行资料处理。</p><div id="knowledge-configs"></div><div class="section-head mt-26"><h2>索引版本</h2><button id="knowledge-rebuild" type="button" class="btn">重建索引</button></div><div id="knowledge-indexes"></div></div>
    </div>`;
  document.querySelector('main').append(section);
  const selectionEditor = document.createElement('details'); selectionEditor.className = 'input-editor';
  selectionEditor.innerHTML = `<summary>知识资料 · 为本轮检索证据</summary><div class="card stack"><label class="field"><span>检索问题</span><input id="task-knowledge-query" maxlength="4000" placeholder="留空时不使用知识库"></label><label class="check"><input type="checkbox" id="task-knowledge-consent"> 允许将本轮检索资料发送给已配置的分析模型</label><p class="hint">从当前私有空间的已发布资料检索，截止时间采用预测生成日期。只有明确勾选后，证据才会进入模型输入。</p><button type="button" class="btn tiny" data-goto="knowledge">管理资料与版本</button></div>`;
  $('facts-editor').after(selectionEditor);
  function tab(name) {
    section.querySelectorAll('[data-kb-pane]').forEach(el => { el.hidden = el.dataset.kbPane !== name; });
    section.querySelectorAll('[data-kb-tab]').forEach(el => el.classList.toggle('active', el.dataset.kbTab === name));
  }
  section.querySelectorAll('[data-kb-tab]').forEach(el => { el.onclick = safe(async () => { tab(el.dataset.kbTab); if (el.dataset.kbTab === 'processing') await configs(); }); });
  function reset() { $('task-knowledge-query').value = ''; $('task-knowledge-consent').checked = false; }
  function identityReset() {
    ++epoch; clearTimeout(timer); documents = [];
    for (const id of ['knowledge-list', 'knowledge-results', 'knowledge-configs', 'knowledge-indexes', 'knowledge-detail']) $(id).replaceChildren();
    $('knowledge-detail').hidden = true; reset();
  }
  function selection() { return {knowledge_query: $('task-knowledge-query').value.trim(), knowledge_to_model: $('task-knowledge-consent').checked}; }
  function restore(value) { $('task-knowledge-query').value = value.knowledge_query || ''; $('task-knowledge-consent').checked = Boolean(value.knowledge_to_model); }
  async function load() {
    clearTimeout(timer);
    const requestEpoch = ++epoch;
    const key = memoryKey;
    $('knowledge-access').hidden = Boolean(key); $('knowledge-body').hidden = !key;
    if (!key) { documents = []; $('knowledge-list').replaceChildren(); $('knowledge-detail').hidden = true; return; }
    try {
      const data = await api('knowledge/documents');
      if (requestEpoch !== epoch || key !== memoryKey) return;
      documents = data;
      const host = $('knowledge-list'); host.replaceChildren();
      $('knowledge-count').textContent = `${data.length} 个版本 · ${data.filter(item => item.status === 'review').length} 待审阅`;
      if (!data.length) text(host, 'p', '上传第一份资料，建立可追溯的证据库。', 'empty');
      for (const item of data) {
        const row = document.createElement('article'); row.className = 'document-row';
        const name = document.createElement('div');
        text(name, 'h3', item.logical);
        text(name, 'p', `${item.filename} · ${fmt(item.uploaded)} · ${item.id.slice(0, 8)}`, 'hint');
        row.append(name);
        const status = document.createElement('div');
        text(status, 'p', `${STATE[item.status] || item.status}${item.active ? ' · 活动版本' : ''}`);
        text(status, 'p', item.error_message || STEP[item.step] || item.step, item.error ? 'error-text' : 'hint');
        row.append(status, action(item.status === 'review' ? '审阅候选' : '查看资料', () => detail(item.id)));
        host.append(row);
      }
      if (!section.hidden && data.some(item => ['pending', 'processing'].includes(item.status))) timer = setTimeout(load, 4000);
    } catch (error) { if (requestEpoch === epoch) notice(error.message, true); }
  }
  function chunkText(host, chunks) {
    for (const chunk of chunks || []) {
      const article = document.createElement('article'); article.className = 'source-excerpt';
      text(article, 'span', `片段 ${chunk.ordinal ?? chunk.index ?? '—'} · ${JSON.stringify(chunk.location || chunk.locator || chunk.loc || {})}`, 'hint');
      text(article, 'p', chunk.text || chunk.original || '', 'source-text');
      if (chunk.original) { const original = document.createElement('details'); text(original, 'summary', '对照清洗前原文'); text(original, 'p', chunk.original, 'source-text'); article.append(original); }
      if (chunk.fields?.length || chunk.normalized_fields) {
        const details = document.createElement('details'); text(details, 'summary', '结构化字段');
        text(details, 'pre', JSON.stringify({fields: chunk.fields, normalized_fields: chunk.normalized_fields}, null, 2), 'mono'); article.append(details);
      }
      host.append(article);
    }
  }
  async function detail(id) {
    const key = memoryKey;
    const item = await api('knowledge/documents/' + id);
    if (key !== memoryKey) return;
    const host = $('knowledge-detail'); host.replaceChildren(); host.hidden = false;
    text(host, 'h2', item.logical);
    text(host, 'p', `${STATE[item.status] || item.status} · ${item.active ? '活动版本' : '非活动版本'} · ${item.id}`, 'hint');
    text(host, 'p', `来源：${item.metadata.source} · 文档日期 ${item.metadata.document_date || '未知'} · 可用日期 ${item.metadata.available_date}`, 'hint');
    for (const warning of item.warnings || []) text(host, 'p', typeof warning === 'string' ? warning : JSON.stringify(warning), 'note warn');
    const actions = document.createElement('div'); actions.className = 'actions mt-16';
    actions.append(action('下载原件', async () => {
      const original = await api(`knowledge/documents/${id}/original`);
      const raw = Uint8Array.from(atob(original.data), char => char.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([raw], {type: 'application/octet-stream'}));
      const link = document.createElement('a'); link.href = url; link.download = original.filename; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }));
    if (item.status === 'failed') actions.append(action('重试处理', async () => { await api(`knowledge/documents/${id}/retry`, 'POST', {}); await load(); await detail(id); }));
    if (!item.active && ['failed', 'review', 'rejected'].includes(item.status)) actions.append(action('重新提取', async () => {
      if (!confirm('重新提取会清除这个未发布版本的提取和审批检查点，保留原文件。继续？')) return;
      await api(`knowledge/documents/${id}/reextract`, 'POST', {}); await load(); await detail(id);
    }));
    actions.append(action('删除此版本', async () => {
      if (!confirm('删除此版本的原件与索引？已有历史分析报告会保留，旧版本不会自动恢复。')) return;
      await api('knowledge/documents/' + id, 'DELETE'); host.hidden = true; await load();
    }));
    host.append(actions);
    const excerpts = document.createElement('details'); excerpts.open = true; text(excerpts, 'summary', '清洗后的来源片段与定位');
    chunkText(excerpts, item.chunks); host.append(excerpts);
    if (!item.chunks?.length) text(excerpts, 'p', '尚未生成可查看的清洗片段。', 'hint');
    if (item.status === 'review') await review(id, host, item);
    host.scrollIntoView({block: 'start', behavior: 'smooth'});
  }
  async function review(id, host, sourceDocument) {
    const key = memoryKey;
    const batch = await api(`knowledge/documents/${id}/review`);
    if (key !== memoryKey) return;
    if (!batch.extraction?.complete) { text(host, 'p', '当前资料需要人工处理原件或补充字段，尚无完整的模型候选可批准。请核对警告，修正后上传新版本。', 'note warn'); return; }
    const group = document.createElement('section'); group.className = 'review-group';
    text(group, 'h3', '逐项核对模型候选');
    text(group, 'p', '只勾选有原文依据且校验通过的候选。未勾选的候选不会发布；批准空列表表示仅发布清洗资料。', 'hint');
    for (const candidate of batch.extraction.candidates || []) {
      const card = document.createElement('article'); card.className = 'source-excerpt';
      const label = document.createElement('label'); label.className = 'check';
      const check = document.createElement('input'); check.type = 'checkbox'; check.value = candidate.id; check.disabled = !candidate.validated;
      label.append(check, document.createTextNode(`${candidate.kind} · ${candidate.subject} · ${candidate.predicate || ''} ${candidate.object || candidate.value || ''} ${candidate.unit || ''}`));
      card.append(label); text(card, 'blockquote', candidate.quote || '', 'source-text');
      text(card, 'p', `${candidate.validated ? '校验通过，仍须核对' : '校验未通过，不可批准'} · 声明 ${candidate.assertion} · 片段 ${candidate.chunk} · 原文字符 ${candidate.start}–${candidate.end} · 有效期 ${candidate.valid_from || '未知'} 至 ${candidate.valid_to || '未知'}`, 'hint');
      if (candidate.validation_errors?.length) text(card, 'p', candidate.validation_errors.join('；'), 'error-text');
      const source = sourceDocument.chunks?.find(chunk => chunk.ordinal === candidate.chunk) || sourceDocument.chunks?.[candidate.chunk];
      if (source) { const original = window.document.createElement('details'); text(original, 'summary', '查看完整来源片段'); text(original, 'p', source.text, 'source-text'); card.append(original); }
      group.append(card);
    }
    const actions = window.document.createElement('div'); actions.className = 'actions';
    for (const [label, decision] of [['批准所选并继续处理', 'approve'], ['拒绝本批候选', 'reject']]) actions.append(action(label, async () => {
      const ids = decision === 'approve' ? [...group.querySelectorAll('input:checked')].map(input => input.value) : [];
      if (!confirm(decision === 'approve' ? `批准 ${ids.length} 条候选并继续处理？` : '拒绝本批候选并保留旧活动版本？')) return;
      await api(`knowledge/documents/${id}/review`, 'POST', {decision, digest: batch.digest, approved_ids: ids});
      await load(); await detail(id);
    }));
    group.append(actions); host.append(group);
  }
  function renderEvidence(host, data) {
    host.replaceChildren();
    const found = data.citations || data.results || [];
    text(host, 'h3', `来源证据 · ${found.length} 条`);
    text(host, 'p', '来源声明与模型推断需要分别核对；日期未知、证据不足与冲突不代表事实已被确认。', 'hint');
    if (!found.length) text(host, 'p', '没有找到满足权限与截止时间的证据。', 'empty');
    for (const item of found) {
      const article = document.createElement('article'); article.className = 'source-excerpt';
      text(article, 'h4', item.filename || item.citation_id);
      text(article, 'p', item.text || item.quote || '', 'source-text');
      text(article, 'p', `${item.citation_id} · 文档日期 ${item.metadata?.document_date || '未知'} · ${JSON.stringify(item.location || {})}`, 'hint');
      for (const warning of item.warnings || []) text(article, 'p', warning, 'note warn');
      article.append(action('查看来源定位', async () => {
        const cite = await api('knowledge/citations/' + item.citation_id);
        const source = document.createElement('div');
        text(source, 'p', `${cite.document.filename} · 版本 ${cite.document.id}`, 'hint');
        chunkText(source, [cite.chunk]); article.append(source);
      })); host.append(article);
    }
    for (const warning of data.warnings || []) text(host, 'p', typeof warning === 'string' ? warning : JSON.stringify(warning), 'note warn');
    if (data.conflicts?.length) { const d = document.createElement('details'); text(d, 'summary', `冲突候选 ${data.conflicts.length} 项`); text(d, 'pre', JSON.stringify(data.conflicts, null, 2), 'mono'); host.append(d); }
  }
  function evidence(data) {
    let host = $('knowledge-report-evidence');
    if (!host) { host = document.createElement('section'); host.id = 'knowledge-report-evidence'; ($('analysis-pane-report') || $('inspector-content')).append(host); }
    renderEvidence(host, data); host.scrollIntoView({block: 'start'});
  }
  const CONFIG_LABELS = {provider: '服务类型', base_url: '服务地址', model: '模型名称', version: '模型版本', timeout_seconds: '单次超时（秒）', allow_external: '允许向远程服务发送资料与查询', mode: '处理范围', document_timeout_seconds: '每份资料总超时（秒）', max_calls: '每份资料最大调用次数', max_input_chars: '单次输入字符上限', max_output_tokens: '单次输出 Token 上限', budget_usd: '每份资料预算（美元）', input_usd_per_million: '每百万输入 Token 单价（美元）', output_usd_per_million: '每百万输出 Token 单价（美元）'};
  async function configs() {
    const key = memoryKey;
    const [embedding, cleaner, indexes] = await Promise.all([api('knowledge/config'), api('knowledge/cleaner/config'), api('knowledge/indexes')]);
    if (key !== memoryKey) return;
    const host = $('knowledge-configs'); host.replaceChildren();
    for (const [title, path, cfg] of [['语义检索 · Embedding', 'knowledge/config', embedding], ['语义清洗 · 候选提取', 'knowledge/cleaner/config', cleaner]]) {
      const details = document.createElement('details'); details.className = 'input-editor'; text(details, 'summary', title);
      const form = document.createElement('form'); form.className = 'card stack'; const fields = {};
      form.onsubmit = event => event.preventDefault();
      const grid = document.createElement('div'); grid.className = 'grid-2';
      for (const [name, label] of Object.entries(CONFIG_LABELS)) {
        if (!(name in cfg)) continue;
        const field = document.createElement('label'); field.className = 'field'; text(field, 'span', label);
        let input;
        if (name === 'provider' || name === 'mode') {
          input = document.createElement('select');
          const choices = name === 'provider' ? [['none', '规则处理 / 不使用模型'], ['ollama', 'Ollama'], ['openai_compatible', 'OpenAI 兼容接口']] : [['unstructured', '仅非结构化资料'], ['always', '全部资料']];
          choices.forEach(([value, label]) => input.add(new Option(label, value)));
          input.value = cfg[name];
        } else { input = document.createElement('input'); input.type = typeof cfg[name] === 'boolean' ? 'checkbox' : typeof cfg[name] === 'number' ? 'number' : 'text'; if (input.type === 'checkbox') input.checked = cfg[name]; else input.value = cfg[name]; if (input.type === 'number') input.step = 'any'; }
        fields[name] = input; field.append(input); grid.append(field);
      }
      form.append(grid);
      const secretField = document.createElement('label'); secretField.className = 'field'; text(secretField, 'span', `API Key · ${cfg.has_secret ? '已保存，留空保留' : '尚未设置'}`);
      const secret = document.createElement('input'); secret.type = 'password'; secret.autocomplete = 'new-password'; secretField.append(secret); form.append(secretField);
      const buttons = document.createElement('div'); buttons.className = 'actions';
      buttons.append(action('保存配置', async () => {
        const body = {};
        for (const [name, input] of Object.entries(fields)) body[name] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
        if (secret.value) body.api_key = secret.value;
        await api(path, 'PUT', body); secret.value = ''; notice('配置已保存。'); await configs();
      }), action('测试连接', async () => { if (!confirm('测试将使用已保存的配置发起模型请求，远程服务可能计费。继续？')) return; const result = await api(path === 'knowledge/config' ? 'knowledge/test' : 'knowledge/cleaner/test', 'POST', {}); notice(result.message || (result.status === 'lexical_only' ? '使用关键词检索，无需模型。' : '测试已完成')); }));
      if (path === 'knowledge/cleaner/config') buttons.append(action('清除已保存密钥', async () => {
        if (!confirm('清除此模型已保存的 API Key？')) return;
        const body = Object.fromEntries(Object.keys(CONFIG_LABELS).filter(name => name in cfg).map(name => [name, cfg[name]]));
        await api(path, 'PUT', {...body, clear_secret: true}); secret.value = ''; await configs();
      })); form.append(buttons); details.append(form); host.append(details);
    }
    const target = $('knowledge-indexes'); target.replaceChildren();
    const generations = Array.isArray(indexes) ? indexes : indexes.items || indexes.generations || [];
    if (!generations.length) text(target, 'p', '尚无向量索引；规则检索仍可使用。', 'hint');
    for (const item of generations) text(target, 'p', `${item.status} · ${item.model || '规则检索'} · 维度 ${item.dimension ?? '—'} · ${item.id}`, 'source-excerpt');
  }
  function init() {
    const today = localInput(new Date()).slice(0, 10);
    $('knowledge-available').value = today; $('knowledge-asof').value = today;
  }
  $('knowledge-refresh').onclick = safe(load);
  $('knowledge-upload').onsubmit = safe(async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('[type=submit]'); button.disabled = true;
    try {
      const file = $('knowledge-file').files[0];
      if (!file || !file.size || file.size > 10 * 1024 * 1024) throw new Error('请选择 1 字节至 10 MiB 的受支持文件');
      const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
      for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const metadata = {source: $('knowledge-source').value || '用户上传', available_date: $('knowledge-available').value};
      if ($('knowledge-date').value) metadata.document_date = $('knowledge-date').value;
      await api('knowledge/documents', 'POST', {filename: file.name, data: btoa(binary), logical: $('knowledge-logical').value || file.name, metadata});
      $('knowledge-file').value = ''; notice('资料已排队，等待独立清洗进程处理。'); await load();
    } finally { button.disabled = false; }
  });
  $('knowledge-search').onsubmit = safe(async event => {
    event.preventDefault(); const button = event.currentTarget.querySelector('[type=submit]'); button.disabled = true;
    try {
      const key = memoryKey, body = {query: $('knowledge-query').value, limit: 8};
      for (const [name, id] of [['as_of', 'knowledge-asof'], ['stock_code', 'knowledge-stock'], ['entity', 'knowledge-entity']]) if ($(id).value) body[name] = $(id).value;
      const data = await api('knowledge/search', 'POST', body);
      if (key === memoryKey) renderEvidence($('knowledge-results'), data);
    } finally { button.disabled = false; }
  });
  $('knowledge-rebuild').onclick = safe(async () => {
    if (!confirm('按已保存的配置重建索引？启用远程 Embedding 时会发送资料并可能计费，失败时保留旧索引。')) return;
    const button = $('knowledge-rebuild'); button.disabled = true;
    try { await api('knowledge/rebuild', 'POST', {}); notice('索引重建完成。'); await configs(); } finally { button.disabled = false; }
  });
  return {init, load, reset, identityReset, restore, selection, evidence, processing: () => { tab('processing'); configs().catch(error => notice(error.message, true)); }};
})();
