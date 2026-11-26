/* Private documents, evidence and review. Source text is always rendered as text. */
window.KnowledgeUI = (() => {
  let timer = null, epoch = 0, documents = [], catalog = {total: 0, review: 0}, queueTimer = null, waiting = null;
  const PAGE = 50;
  const scopeKey = 'spm_knowledge_scope';
  let scope = memoryKey && sessionStorage.getItem(scopeKey) !== 'local' ? 'private' : 'local';
  const identity = () => scope === 'local' ? 'local' : (memoryKey ? 'private:' + memoryKey : '');
  sessionStorage.setItem(scopeKey, scope);
  let desktopStatus = '', detailRequest = 0, searchRequest = 0;
  const STATE = {pending: '已排队', processing: '处理中', ready: '已发布', review: '待审阅', failed: '处理失败', rejected: '已拒绝', deleting: '等待删除'};
  const STEP = {received: '已接收', parsed: '已解析', chunked: '已切分', extracted: '已提取', reviewed: '已审阅', published: '已发布'};
  // 与后端 metadata() 白名单一致：四类标签键与对应的表单字段。
  const TAGS = [['companies', 'knowledge-companies'], ['industries', 'knowledge-industries'], ['topics', 'knowledge-topics'], ['stock_codes', 'knowledge-codes']];
  const TAG_LABEL = {companies: '主体', industries: '行业', topics: '主题', stock_codes: '代码'};
  function tagValues(id) {
    const values = [...new Set(String($(id).value || '').split(/[,，、;；]/).map(value => value.trim()).filter(Boolean))];
    if (values.length > 40) throw new Error('单类标签最多 40 个');
    const long = values.find(value => value.length > 100);
    if (long) throw new Error(`标签「${long.slice(0, 12)}」超过 100 字符`);
    return values;
  }
  const safe = fn => async event => { try { await fn(event); } catch (error) { notice(error.message, true); } };
  const section = document.createElement('section');
  section.className = 'view knowledge-shell'; section.dataset.viewPane = 'knowledge'; section.hidden = true;
  section.innerHTML = `
    <label class="field"><span>资料库</span><select id="knowledge-scope"><option value="local">本机资料库</option><option value="private">旧版私有资料</option></select></label>
    <div id="knowledge-access" class="note" hidden><p>恢复原访问密钥后即可查看旧版私有资料。</p><button type="button" data-goto="memory" class="btn">恢复原访问密钥</button></div>
    <div id="knowledge-body" hidden>
      <div class="subnav"><button type="button" data-kb-tab="documents" class="active">资料与版本</button><button type="button" data-kb-tab="search">检索证据</button><button type="button" data-kb-tab="processing">处理与索引设置</button></div>
      <div data-kb-pane="documents">
        <div class="section-head"><h2>资料</h2><span id="knowledge-count" class="hint"></span><button type="button" id="knowledge-refresh" class="btn tiny">刷新</button></div>
        <details class="input-editor"><summary>上传资料 / 更新版本</summary><form id="knowledge-upload" class="card stack">
          <label class="field"><span>文件 · 最大 10 MiB</span><input id="knowledge-file" type="file" accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.json" required></label>
          <label class="field"><span>资料名称 <em>更新时使用相同名称</em></span><input id="knowledge-logical" maxlength="200" placeholder="留空时使用文件名"></label>
          <div class="grid-4"><label class="field"><span>来源</span><input id="knowledge-source" value="用户上传" maxlength="200"></label><label class="field"><span>文档日期</span><input type="date" id="knowledge-date"></label><label class="field"><span>实际可用日期</span><input type="date" id="knowledge-available" required></label><label class="field"><span>失效日期 <em>选填</em></span><input type="date" id="knowledge-valid"></label></div>
          <div class="grid-3"><label class="field"><span>主体名称 <em>逗号分隔</em></span><input id="knowledge-companies" maxlength="400" placeholder="例如：甲公司, 乙公司"></label><label class="field"><span>行业 <em>逗号分隔</em></span><input id="knowledge-industries" maxlength="400" placeholder="例如：汽车零部件"></label><label class="field"><span>主题 <em>逗号分隔</em></span><input id="knowledge-topics" maxlength="400" placeholder="例如：产能扩张, 供应链"></label></div>
          <label class="field"><span>股票代码 <em>逗号分隔，可写 600000.SH 或 600000</em></span><input id="knowledge-codes" maxlength="400" placeholder="例如：600000.SH, 000001.SZ"></label>
          <p class="hint">支持 PDF、DOCX、TXT、Markdown、CSV、XLSX、JSON。上传后进入队列，由独立清洗进程处理。扫描件 OCR 暂不支持。标签用于检索前过滤，单类最多 40 个、每个不超过 100 字符；留空表示不限定。</p>
          <div><button type="submit" class="btn primary">上传并排队</button></div>
        </form></details>
        <div id="knowledge-queue" class="queue-bar"></div>
        <div id="knowledge-list"></div>
      </div>
      <div data-kb-pane="search" hidden><form id="knowledge-search" class="stack"><label class="field"><span>查找证据</span><input id="knowledge-query" required maxlength="4000" placeholder="例如：营业收入、客户关系、供应链风险"></label><div class="grid-4"><label class="field"><span>截止日期</span><input id="knowledge-asof" type="date"></label><label class="field"><span>文档日期不早于</span><input id="knowledge-start" type="date"></label><label class="field"><span>股票代码</span><input id="knowledge-stock" placeholder="600000.SH"></label><label class="field"><span>主体名称</span><input id="knowledge-entity" maxlength="200"></label></div><div class="grid-2"><label class="field"><span>返回片段数</span><select id="knowledge-limit"><option value="5">5 段</option><option value="8" selected>8 段</option><option value="12">12 段</option><option value="20">20 段</option></select></label><div class="field"><span class="hint">汇总不是模型结论，只按「摘录 → 关系 → 推断」顺序拼接</span><div class="actions"><button type="submit" class="btn primary">检索证据</button><button type="button" id="knowledge-answer" class="btn">汇总并回答</button></div></div></div><p class="hint">截止日期决定「当时能看到什么」：晚于该日期才可用的资料不参与检索；「文档日期不早于」用于排除过旧资料，文档日期未知的条目会被一并排除。</p></form><div id="knowledge-results" class="mt-26"></div><div id="knowledge-answer-result" class="mt-26"></div></div>
      <div data-kb-pane="pipeline" hidden><div class="knowledge-pipeline-card"><div><p class="eyebrow">DOCUMENT PROCESSING</p><h2>转换为知识流水线</h2><p class="lede">将当前知识库交给可编辑的处理流程。新的处理方式会应用到后续添加的所有文档。</p><button type="button" class="btn primary" id="knowledge-pipeline-convert">转换</button><span class="hint">此操作无法撤销。</span></div><div class="knowledge-pipeline-preview"><div class="pipeline-node">文件上传</div><span>→</span><div class="pipeline-node">文档解析</div><span>→</span><div class="pipeline-node">通用切分</div></div></div></div>
      <div data-kb-pane="processing" hidden><div class="knowledge-settings-summary"><div><h2>知识库设置</h2><p class="hint">控制资料库名称、分段方式和检索策略。模型配置仍通过现有处理设置保存。</p></div><div class="knowledge-settings-grid"><div><span>名称和图标</span><strong>预测资料库</strong></div><div><span>可见权限</span><strong>只有我</strong></div><div><span>分段模式</span><strong>通用</strong></div><div><span>索引模式</span><strong>经济</strong></div><div><span>检索设置</span><strong>倒排索引 · Top K 2</strong></div><div><span>文档来源</span><strong>文件上传</strong></div></div></div><p class="hint">规则清洗和关键词检索无需模型。语义清洗模型与向量模型独立配置；保存配置不会自动执行资料处理。</p><div id="knowledge-configs"></div><div class="section-head mt-26"><h2>索引版本</h2><button id="knowledge-rebuild" type="button" class="btn">重建索引</button></div><div id="knowledge-indexes"></div></div>
    </div>`;
  const knowledgeContent = document.createElement('div');
  knowledgeContent.className = 'knowledge-dify-main';
  while (section.firstChild) knowledgeContent.append(section.firstChild);
  let surface = 'catalog';
  const knowledgeLanding = document.createElement('div');
  knowledgeLanding.className = 'knowledge-dify-main knowledge-landing-main';
  knowledgeLanding.innerHTML = `
    <div class="knowledge-catalog-toolbar">
      <div class="knowledge-header-actions">
        <button type="button" class="btn primary" id="knowledge-create-landing">＋ 创建知识库</button>
        <button type="button" class="btn" id="knowledge-connect-landing">⚙ 连接外部知识库</button>
      </div>
    </div>
    <div class="knowledge-catalog-grid">
      <aside class="knowledge-create-panel">
        <button type="button" id="knowledge-create-panel">＋ 创建知识库</button>
        <button type="button" id="knowledge-pipeline-panel">▦ 通过知识流水线创建知识库</button>
        <div class="knowledge-create-divider"></div>
        <button type="button" id="knowledge-external-panel">⚙ 连接外部知识库</button>
      </aside>
      <button type="button" class="knowledge-base-card" id="knowledge-open-card">
        <span class="knowledge-base-icon" aria-hidden="true">▣</span>
        <span class="knowledge-base-copy">
          <strong>预测资料库</strong>
          <small class="hint" id="knowledge-card-count">正在读取</small>
        </span>
      </button>
    </div>`;
  const knowledgeCreate = document.createElement('div');
  knowledgeCreate.className = 'knowledge-dify-main knowledge-create-main'; knowledgeCreate.hidden = true;
  knowledgeCreate.innerHTML = '<div class="knowledge-step-head"><button type="button" class="btn" data-knowledge-back>← 知识库</button><div class="knowledge-steps"><strong>上传文档</strong></div></div><div class="knowledge-create-body"><h1>选择数据源</h1><div class="knowledge-source-options"><button type="button" class="selected" data-knowledge-source="upload">▤ 导入已有文本</button><button type="button" data-knowledge-source="notion">▣ 同步自 Notion 内容</button><button type="button" data-knowledge-source="web">◉ 同步自 Web 站点</button></div><h2>上传文本文件</h2><div class="knowledge-dropzone">☁&nbsp; <button type="button" id="knowledge-upload-from-create">选择文件</button><input id="knowledge-create-file" type="file" accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.json" multiple hidden><p>选择后会直接上传到当前知识库。支持 PDF、DOCX、TXT、Markdown、CSV、XLSX、JSON，每次最多 5 个文件，每个不超过 10 MiB。</p><p id="knowledge-create-status" class="hint" aria-live="polite"></p></div><button type="button" class="btn primary knowledge-next-upload" id="knowledge-next-upload">选择文件并上传</button></div>';
  const knowledgeConnect = document.createElement('div');
  knowledgeConnect.className = 'knowledge-dify-main knowledge-connect-main'; knowledgeConnect.hidden = true;
  knowledgeConnect.innerHTML = '<div class="knowledge-connect-layout"><form id="knowledge-external-form" class="knowledge-connect-form"><button type="button" class="btn" data-knowledge-back>← 返回知识库</button><h1>连接外部知识库</h1><p class="lede">通过 API 和知识库 ID 连接外部知识库。目前仅支持检索功能。</p><label class="field"><span>外部知识库名称</span><input id="knowledge-external-name" placeholder="请输入外部知识库名称"></label><label class="field"><span>知识库描述</span><textarea id="knowledge-external-description" rows="3" placeholder="描述知识库内容（可选）"></textarea></label><label class="field"><span>外部知识库 API</span><input id="knowledge-external-api" placeholder="点击此处创建或选择 API"></label><label class="field"><span>外部知识库 ID</span><input id="knowledge-external-id" placeholder="请输入外部知识库 ID"></label><div class="knowledge-connect-actions"><button type="button" class="btn" data-knowledge-back>取消</button><button type="submit" class="btn primary">连接 →</button></div></form><aside class="knowledge-connect-help"><div class="knowledge-sidebar-icon">▣</div><h2>如何连接外部知识库</h2><p>需要先创建一个外部 API，再填写对应的知识库 ID。连接后可以直接进入召回测试。</p><a href="#knowledge" data-knowledge-help>了解更多</a></aside></div>';
  const knowledgeDocuments = document.createElement('div');
  knowledgeDocuments.className = 'knowledge-dify-main knowledge-documents-main'; knowledgeDocuments.hidden = true;
  knowledgeDocuments.innerHTML = `
    <div class="knowledge-documents-head">
      <h1>文档</h1>
      <button type="button" class="btn primary" id="knowledge-documents-add">＋ 添加文件</button>
    </div>
    <div class="knowledge-documents-toolbar">
      <button type="button" class="btn tiny" id="knowledge-documents-refresh">刷新</button>
    </div>
    <div id="knowledge-documents-list" class="knowledge-documents-list"></div>
    <section id="knowledge-detail" class="knowledge-detail" hidden></section>`;
  knowledgeLanding.querySelector('.knowledge-catalog-toolbar').prepend(knowledgeContent.querySelector('#knowledge-scope').closest('label'));
  knowledgeLanding.querySelector('.knowledge-catalog-grid').before(knowledgeContent.querySelector('#knowledge-access'));
  const knowledgeHeader = document.createElement('header');
  knowledgeHeader.className = 'knowledge-dify-header';
  knowledgeHeader.innerHTML = '<div class="knowledge-brand"><span class="knowledge-brand-mark">▣</span><span>知识库</span><span class="knowledge-brand-sep">/</span><strong>预测资料库</strong></div><div class="knowledge-header-actions"><button type="button" class="btn quiet" id="knowledge-api">◉ 服务 API</button><button type="button" class="btn quiet" id="knowledge-external">⚙ 外部知识库 API</button></div>';
  const knowledgeSidebar = document.createElement('aside');
  knowledgeSidebar.className = 'knowledge-dify-sidebar';
  knowledgeSidebar.innerHTML = `
    <button type="button" class="btn tiny" data-knowledge-back>← 返回知识库</button>
    <div class="knowledge-sidebar-card">
      <div class="knowledge-sidebar-icon" aria-hidden="true">▣</div><strong>预测资料库</strong>
    </div>
    <nav class="knowledge-sidebar-actions" aria-label="知识库导航">
      <button type="button" class="active" data-dify-kb-tab="documents">▤ 文档</button>
      <button type="button" data-dify-kb-tab="pipeline">⌘ 流水线</button>
      <button type="button" data-dify-kb-tab="search">◎ 召回测试</button>
      <button type="button" data-dify-kb-tab="processing">☷ 设置</button>
    </nav>
    <div class="knowledge-sidebar-foot"><span id="knowledge-sidebar-count"></span><small>文档版本</small></div>`;
  const knowledgeLayout = document.createElement('div');
  knowledgeLayout.className = 'knowledge-dify-layout';
  knowledgeLayout.append(knowledgeSidebar, knowledgeLanding, knowledgeCreate, knowledgeConnect, knowledgeDocuments, knowledgeContent);
  section.append(knowledgeHeader, knowledgeLayout);
  document.querySelector('main').append(section);
  function renderLanding() {
    $('knowledge-card-count').textContent = `${catalog.total || documents.length || 0} 个资料版本 · ${catalog.review || 0} 待审阅`;
    $('knowledge-sidebar-count').textContent = catalog.total;
  }
  function showSurface(name) {
    if (surface === 'documents' && name !== 'documents') closeDetail();
    surface = name;
    section.classList.toggle('knowledge-catalog-mode', name === 'catalog');
    section.classList.toggle('knowledge-create-mode', name === 'create');
    section.classList.toggle('knowledge-connect-mode', name === 'connect');
    knowledgeLanding.hidden = name !== 'catalog';
    knowledgeCreate.hidden = name !== 'create';
    knowledgeConnect.hidden = name !== 'connect';
    knowledgeDocuments.hidden = name !== 'documents';
    knowledgeContent.hidden = name !== 'tools';
    if (name === 'documents') renderDifyDocuments();
  }
  async function openDocuments(id = '') {
    if (surface !== 'documents') {
      selectTab('documents');
    }
    if (id) await detail(id);
  }
  const goCatalog = () => showSurface('catalog');
  const goCreate = () => showSurface('create');
  const goConnect = () => showSurface('connect');
  $('knowledge-create-landing').onclick = goCreate;
  $('knowledge-create-panel').onclick = goCreate;
  $('knowledge-pipeline-panel').onclick = goCreate;
  $('knowledge-connect-landing').onclick = goConnect;
  $('knowledge-external-panel').onclick = goConnect;
  $('knowledge-open-card').onclick = safe(() => openDocuments());
  section.querySelectorAll('[data-knowledge-back]').forEach(button => { button.onclick = goCatalog; });
  $('knowledge-documents-add').onclick = goCreate;
  $('knowledge-documents-refresh').onclick = safe(() => load());
  const openCreatePicker = () => $('knowledge-create-file').click();
  $('knowledge-upload-from-create').onclick = openCreatePicker;
  $('knowledge-next-upload').onclick = openCreatePicker;
  async function uploadCreateFiles(files) {
    if (!files.length) return;
    const picker = $('knowledge-upload-from-create');
    const action = $('knowledge-next-upload');
    const status = $('knowledge-create-status');
    if (picker.disabled) return;
    if (files.length > 5) {
      status.textContent = '每次最多选择 5 个文件。';
      return;
    }
    const key = identity();
    if (!key) {
      status.textContent = '请先恢复原访问密钥，或返回并选择本机资料库。';
      return;
    }
    let uploaded = 0;
    const failures = [];
    picker.disabled = true; action.disabled = true;
    try {
      for (const [index, file] of files.entries()) {
        if (key !== identity()) break;
        status.textContent = `正在上传 ${index + 1}/${files.length}：${file.name}`;
        try {
          await uploadDocumentFile(file, {key});
          ++uploaded;
        } catch (error) {
          failures.push(`${file.name}：${error.message}`);
        }
      }
      if (key !== identity()) return;
      const message = `已上传 ${uploaded} 个文件${failures.length ? `，${failures.length} 个失败。 ${failures.join('；')}` : '，资料已排队处理。'}`;
      status.textContent = message;
      if (uploaded) await load();
      notice(message, Boolean(failures.length));
      if (surface === 'create' && uploaded && !failures.length) goCatalog();
    } finally {
      picker.disabled = false; action.disabled = false;
    }
  }
  $('knowledge-create-file').onchange = safe(async event => {
    const input = event.currentTarget;
    const files = [...input.files];
    input.value = '';
    await uploadCreateFiles(files);
  });
  $('knowledge-external-form').onsubmit = event => {
    event.preventDefault();
    notice('外部知识库连接暂未接入。', true);
  };
  showSurface('catalog');
  $('knowledge-api').onclick = () => notice('服务 API 入口将在当前资料库作用域内使用现有接口。');
  $('knowledge-external').onclick = goConnect;
  $('knowledge-pipeline-convert').onclick = () => notice('流水线转换需要先完成当前知识库的处理配置。');
  const selectionEditor = document.createElement('details'); selectionEditor.className = 'input-editor';
  selectionEditor.innerHTML = `<summary>知识资料 · 为本轮检索证据</summary><div class="card stack"><label class="field"><span>检索问题</span><input id="task-knowledge-query" maxlength="4000" placeholder="留空时不使用知识库"></label><label class="check"><input type="checkbox" id="task-knowledge-consent"> 允许将本轮检索资料发送给已配置的分析模型</label><p class="hint">从当前选择的资料库检索已发布资料，截止时间采用预测生成日期。只有明确勾选后，证据才会进入模型输入。</p><button type="button" class="btn tiny" data-goto="knowledge">管理资料与版本</button></div>`;
  $('facts-editor').after(selectionEditor);
  $('knowledge-scope').value = scope;
  $('knowledge-scope').onchange = safe(async event => {
    scope = event.currentTarget.value;
    sessionStorage.setItem(scopeKey, scope);
    identityReset();
    await load();
  });
  function selectTab(name) {
    section.querySelectorAll('[data-kb-pane]').forEach(el => {
      el.hidden = name === 'documents' || el.dataset.kbPane !== name;
    });
    section.querySelectorAll('[data-kb-tab]').forEach(el => el.classList.toggle('active', el.dataset.kbTab === name));
    section.querySelectorAll('[data-dify-kb-tab]').forEach(el => el.classList.toggle('active', el.dataset.difyKbTab === name));
    showSurface(name === 'documents' ? 'documents' : 'tools');
  }
  async function openTab(name) {
    if (name === 'documents') return openDocuments();
    selectTab(name);
    if (name === 'processing' && identity()) await configs();
  }
  section.querySelectorAll('[data-kb-tab], [data-dify-kb-tab]').forEach(el => {
    el.onclick = safe(() => openTab(el.dataset.kbTab || el.dataset.difyKbTab));
  });
  function closeDetail() {
    ++detailRequest;
    $('knowledge-detail').hidden = true;
  }
  function reset() { $('task-knowledge-query').value = ''; $('task-knowledge-consent').checked = false; }
  function identityReset() {
    ++detailRequest; ++searchRequest; desktopStatus = ''; window.DesktopLibrary?.resetKnowledge();
    ++epoch; clearTimeout(timer); clearTimeout(queueTimer); waiting = null;
    documents = []; catalog = {total: 0, review: 0};
    for (const id of ['knowledge-list', 'knowledge-results', 'knowledge-answer-result', 'knowledge-configs', 'knowledge-indexes', 'knowledge-detail', 'knowledge-queue']) $(id).replaceChildren();
    closeDetail(); reset(); renderLanding(); renderDifyDocuments();
  }
  function selection() { return {knowledge_query: $('task-knowledge-query').value.trim(), knowledge_to_model: $('task-knowledge-consent').checked}; }
  function restore(value) { $('task-knowledge-query').value = value.knowledge_query || ''; $('task-knowledge-consent').checked = Boolean(value.knowledge_to_model); }
  function documentRow(item) {
    const row = document.createElement('article'); row.className = 'document-row';
    row.dataset.documentId = item.id; row.dataset.documentState = item.status;
    const name = document.createElement('div');
    text(name, 'h3', item.logical);
    text(name, 'p', `${item.filename} · ${fmt(item.uploaded)} · ${item.id.slice(0, 8)}`, 'hint');
    row.append(name);
    const status = document.createElement('div');
    text(status, 'p', `${STATE[item.status] || item.status}${item.active ? ' · 活动版本' : ''}`);
    text(status, 'p', item.error_message || STEP[item.step] || item.step, item.error ? 'error-text' : 'hint');
    row.append(status, action(item.status === 'review' ? '审阅候选' : '查看资料', () => detail(item.id)));
    return row;
  }
  function renderDifyDocuments() {
    const host = $('knowledge-documents-list'); host.replaceChildren();
    if (documents.length) renderDocumentsTable(host, documents);
    else text(host, 'p', '尚未上传文档。', 'empty');
    if (documents.length < catalog.total) host.append(action('加载更多文档', () => load(true)));
  }
  function renderDocumentsTable(host, items) {
    const table = document.createElement('table'); table.className = 'knowledge-documents-table';
    table.innerHTML = '<thead><tr><th scope="col">名称</th><th scope="col">来源</th><th scope="col">上传时间</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>';
    const body = document.createElement('tbody');
    for (const item of items) {
      const row = document.createElement('tr');
      row.dataset.documentId = item.id;
      const name = document.createElement('td');
      name.append(action(item.logical || item.filename, () => detail(item.id)));
      if (item.logical !== item.filename) text(name, 'small', item.filename, 'hint');
      row.append(name);
      text(row, 'td', item.metadata?.source || '用户上传');
      text(row, 'td', fmt(item.uploaded));
      text(row, 'td', STATE[item.status] || item.status);
      const operations = document.createElement('td');
      operations.append(action('查看详情', () => detail(item.id)));
      row.append(operations); body.append(row);
    }
    table.append(body); host.append(table);
  }
  function renderDocuments(items) {
    const host = $('knowledge-list');
    for (const item of items) host.append(documentRow(item));
    $('knowledge-count').textContent = `${catalog.total} 个版本 · ${catalog.review} 待审阅${documents.length < catalog.total ? ` · 已显示 ${documents.length}` : ''}`;
    const more = $('knowledge-more'); if (more) more.remove();
    if (documents.length < catalog.total) {
      const button = action(`加载更多 · 已显示 ${documents.length} / ${catalog.total}`, () => load(true));
      button.id = 'knowledge-more'; host.append(button);
    }
    if (!documents.length) text(host, 'p', desktopStatus && matchMedia('(min-width: 761px)').matches ? '这个状态暂无资料，可切换状态或上传资料。' : '上传第一份资料，建立可追溯的证据库。', 'empty');
    renderLanding(); renderDifyDocuments();
    window.DesktopLibrary?.knowledge({items:documents, catalog, status:desktopStatus});
  }
  function shortAge(seconds) {
    if (seconds === null || seconds === undefined) return '未知';
    if (seconds < 60) return `${Math.max(1, Math.round(seconds))} 秒前`;
    if (seconds < 5400) return `${Math.round(seconds / 60)} 分钟前`;
    return `${Math.round(seconds / 3600)} 小时前`;
  }
  // 队列条回答两个问题：进程在不在、卡在哪一份。计数每几秒轮询一次，
  // 所以只读一个聚合接口，不重载列表。
  function renderQueue(data) {
    const host = $('knowledge-queue'); host.replaceChildren();
    const counts = data.counts || {}, worker = data.worker || {};
    const head = document.createElement('p'); head.className = 'queue-head';
    const dot = document.createElement('span');
    dot.className = 'dot ' + (worker.online ? 'ok' : worker.seen ? 'warn' : 'off');
    const title = worker.online
      ? (worker.state === 'busy' ? `清洗进程正在处理 · ${worker.current_logical || '其他资料'}` : '清洗进程在线 · 空闲')
      : worker.seen
        ? (worker.state === 'stopped' ? '清洗进程已退出' : `清洗进程无响应 · 最近心跳 ${shortAge(worker.age)}`)
        : '清洗进程尚未在本机启动';
    text(head, 'strong', title); head.prepend(dot);
    if (worker.seen) text(head, 'span', `最近心跳 ${shortAge(worker.age)} · 本次已处理 ${worker.processed} 份 · ${worker.host}:${worker.pid}`, 'hint');
    host.append(head);
    text(host, 'p', `排队 ${counts.pending || 0} · 处理中 ${counts.processing || 0} · 待审阅 ${counts.review || 0} · 失败 ${counts.failed || 0} · 已发布 ${counts.ready || 0}`, 'hint');
    if (!worker.online && data.waiting) {
      const note = document.createElement('p'); note.className = 'note warn';
      note.textContent = `有 ${data.waiting} 份资料在排队，但没有进程在处理。在本机运行 uv run stock-predict-mailer knowledge-worker 常驻处理，或加 --once 处理完即退出。`;
      host.append(note);
    }
    for (const item of data.attention || []) {
      const row = document.createElement('div'); row.className = 'queue-attention';
      text(row, 'span', `${STATE[item.status] || item.status} · ${item.logical}`, item.status === 'failed' ? 'error-text' : 'hint');
      if (item.status === 'failed') text(row, 'span', item.error_message || '处理失败', 'hint');
      row.append(action('查看', () => detail(item.id)));
      host.append(row);
    }
    window.DesktopLibrary?.queue(data);
  }
  async function queueStatus(reload = true) {
    clearTimeout(queueTimer);
    const key = identity();
    if (!key) { $('knowledge-queue').replaceChildren(); waiting = null; return; }
    let busy = waiting;
    try {
      const data = await api('knowledge/queue');
      if (key !== identity()) return;
      renderQueue(data);
      busy = data.waiting || 0;
      // 队列从有到空：列表里的状态已经过期，补一次重载。load() 内部以 reload=false
      // 调用本函数，避免两边互相触发。
      if (reload && waiting !== null && waiting > 0 && busy === 0) await load();
      waiting = busy;
    } catch (error) { window.DesktopLibrary?.queueError(); /* Keep the previous queue display. */ }
    queueTimer = setTimeout(() => queueStatus(), busy ? 4000 : 8000);
  }
  async function load(append = false) {
    clearTimeout(timer);
    const extend = append === true;
    const requestEpoch = ++epoch;
    const key = identity();
    $('knowledge-access').hidden = Boolean(key); $('knowledge-body').hidden = !key;
    if (!key) {
      documents = []; catalog = {total: 0, review: 0};
      $('knowledge-list').replaceChildren(); $('knowledge-queue').replaceChildren();
      closeDetail(); clearTimeout(queueTimer); waiting = null;
      renderLanding(); renderDifyDocuments(); window.DesktopLibrary?.resetKnowledge();
      return;
    }
    window.DesktopLibrary?.knowledgeLoading(desktopStatus);
    queueStatus(false);
    try {
      const offset = extend ? documents.length : 0;
      const limit = extend ? PAGE : Math.min(500, Math.max(PAGE, documents.length));
      const status = matchMedia('(min-width: 761px)').matches ? desktopStatus : '';
      const data = await api(`knowledge/documents?limit=${limit}&offset=${offset}${status ? '&status=' + status : ''}`);
      if (requestEpoch !== epoch || key !== identity()) return;
      if (!extend) { documents = []; $('knowledge-list').replaceChildren(); }
      documents = documents.concat(data.items); catalog = data;
      renderDocuments(data.items);
      if (!section.hidden && data.items.some(item => ['pending', 'processing'].includes(item.status))) timer = setTimeout(() => load(), 4000);
    } catch (error) { if (requestEpoch === epoch) { notice(error.message, true); window.DesktopLibrary?.knowledgeError(error.message); } }
  }
  async function filterStatus(status = '') {
    desktopStatus = Object.hasOwn(STATE, status) ? status : '';
    documents = []; $('knowledge-list').replaceChildren();
    return load();
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
    const key = identity();
    const request = ++detailRequest;
    const current = () => key === identity() && request === detailRequest;
    const [item, versions] = await Promise.all([api('knowledge/documents/' + id), api(`knowledge/documents/${id}/versions`)]);
    if (!current()) return;
    const summary = documents.find(doc => doc.id === id);
    if (summary && (summary.status !== item.status || summary.active !== item.active)) {
      Object.assign(summary, {status: item.status, active: item.active, step: item.step});
      renderLanding(); renderDifyDocuments();
    }
    const host = $('knowledge-detail'); host.replaceChildren(); host.hidden = false;
    text(host, 'h2', item.logical);
    text(host, 'p', `${item.filename} · 上传于 ${fmt(item.uploaded)} · ${item.chunks?.length || 0} 个片段`, 'hint');
    if (item.error_message) text(host, 'p', item.error_message, 'error-text');
    text(host, 'p', `${STATE[item.status] || item.status} · ${item.active ? '活动版本' : '非活动版本'} · ${item.id}`, 'hint');
    text(host, 'p', `来源：${item.metadata.source} · 文档日期 ${item.metadata.document_date || '未知'} · 可用日期 ${item.metadata.available_date} · 失效日期 ${item.metadata.valid_to || '未声明'}`, 'hint');
    const tags = TAGS.filter(([key]) => (item.metadata[key] || []).length);
    if (tags.length) text(host, 'p', tags.map(([key]) => `${TAG_LABEL[key]}：${item.metadata[key].join('、')}`).join(' · '), 'hint');
    if (versions.length > 1) {
      const history = document.createElement('details'); history.className = 'knowledge-version-history'; text(history, 'summary', `版本历史 · ${versions.length} 个版本`);
      for (const version of versions) text(history, 'p', `${version.id.slice(0, 8)}${version.id === id ? '（当前查看）' : ''} · ${STATE[version.status] || version.status}${version.active ? ' · 活动版本' : ''} · ${fmt(version.uploaded)}`, 'hint');
      text(history, 'p', '检索按截止日期选用当时有效的最新版本；下架不退回到旧版本。', 'hint');
      host.append(history);
    }
    for (const warning of item.warnings || []) text(host, 'p', typeof warning === 'string' ? warning : JSON.stringify(warning), 'note warn');
    const actions = document.createElement('div'); actions.className = 'actions mt-16';
    const close = action('关闭详情', closeDetail); close.classList.add('knowledge-detail-close'); actions.append(close);
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
    if (item.active) actions.append(action('下架此版本', async () => {
      if (!confirm('下架后该版本不再参与检索与任务证据，加密原件与历史引用仍保留。下架不退回旧版本。继续？')) return;
      await api(`knowledge/documents/${id}/retire`, 'POST', {}); await load(); await detail(id);
    }));
    actions.append(action('永久删除', async () => {
      const badge = id.slice(0, 8);
      if (prompt(`永久删除会销毁加密原件、片段与全部索引，无法恢复。输入资料 ID 前 8 位（${badge}）确认：`) !== badge) return;
      await api('knowledge/documents/' + id, 'DELETE'); host.hidden = true; await load();
    }));
    host.append(actions);
    const excerpts = document.createElement('details'); excerpts.open = true; text(excerpts, 'summary', '清洗后的来源片段与定位');
    chunkText(excerpts, item.chunks); host.append(excerpts);
    if (!item.chunks?.length) text(excerpts, 'p', '尚未生成可查看的清洗片段。', 'hint');
    if (item.status === 'review') await review(id, host, item, current);
    if (!current()) return;
    window.DesktopLibrary?.document(item, versions);
    host.scrollIntoView({block: 'start', behavior: 'smooth'});
  }
  async function review(id, host, sourceDocument, current = () => true) {
    const key = identity();
    const batch = await api(`knowledge/documents/${id}/review`);
    if (key !== identity() || !current()) return;
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
  function renderGroups(container, data) {
    const found = data.results || data.citations || [], groups = data.groups || [];
    const order = groups.length ? groups.map(group => group.logical) : [...new Set(found.map(item => item.logical || item.document_id))];
    for (const slot of order) {
      const items = found.filter(item => (item.logical || item.document_id) === slot);
      if (!items.length) continue;
      const group = groups.find(item => item.logical === slot) || {};
      const wrap = document.createElement('section'); wrap.className = 'evidence-group';
      const head = document.createElement('div'); head.className = 'section-head';
      text(head, 'h4', group.filename || items[0].filename || slot);
      const state = group.expired ? `已于 ${group.valid_to} 失效` : group.valid_to ? `有效期至 ${group.valid_to}` : '未声明有效期';
      text(head, 'span', state, group.expired ? 'tag expired' : 'tag');
      wrap.append(head);
      const hits = group.hits ?? items.length, shown = group.shown ?? items.length;
      const meta = [`文档日期 ${group.document_date || items[0].metadata?.document_date || '未知'}`];
      if (group.available_date) meta.push(`可用 ${group.available_date}`);
      meta.push(hits > shown ? `命中 ${hits} 段，显示 ${shown} 段` : `命中 ${shown} 段`, `槽位 ${slot}`);
      text(wrap, 'p', meta.join(' · '), 'hint');
      for (const item of items) {
        const article = document.createElement('article'); article.className = 'source-excerpt';
        text(article, 'h4', item.citation_id);
        text(article, 'p', item.text || item.quote || '', 'source-text');
        text(article, 'p', `文档日期 ${item.metadata?.document_date || '未知'} · ${JSON.stringify(item.location || {})}`, 'hint');
        for (const warning of item.warnings || []) text(article, 'p', warning, 'note warn');
        article.append(action('查看来源定位', async () => {
          const cite = await api('knowledge/citations/' + item.citation_id);
          const source = document.createElement('div');
          text(source, 'p', `${cite.document.filename} · 版本 ${cite.document.id}`, 'hint');
          chunkText(source, [cite.chunk]); article.append(source);
        })); wrap.append(article);
      }
      container.append(wrap);
    }
    if (data.logical_total && data.logical_total > groups.length) text(container, 'p', `另有 ${data.logical_total - groups.length} 个版本命中但未进入前 ${data.limit || ''} 段，可提高片段数或补充条件后再检索。`, 'hint');
  }
  /* 别名扩展必须回显：出现了「用口语问、按全称命中」的结果时，
     使用者要知道是词表在起作用，而不是以为检索在乱猜。 */
  function aliasHint(host, data) {
    if (!data.aliases?.length) return;
    const pairs = data.aliases.map(item => `${item.alias} → ${item.canonical.join(' / ')}`).join('；');
    text(host, 'p', `已按别名扩展查询：${pairs}。资料按原文写法入库，扩词只发生在查询侧。`, 'hint');
  }
  /* 锚定与别名一样需要回显：这条结果为什么排第一，取决于问题里认出了哪家主体。 */
  function anchorHint(host, data) {
    if (!data.anchors?.length) return;
    const items = data.anchors.map(item => {
      const origin = item.source === 'param' ? '参数指定' : '查询识别';
      const scope = item.slots?.length ? `${item.slots.length} 份资料` : '语料里没有对应资料';
      return `${item.value}（${origin} · ${scope}）`;
    });
    text(host, 'p', `已锚定主体：${items.join('；')}。锚定只决定先看谁的资料，不改变证据本身。`, 'hint');
  }
  function renderEvidence(host, data) {
    host.replaceChildren();
    const found = data.citations || data.results || [];
    const groups = data.groups || [];
    text(host, 'h3', groups.length ? `来源证据 · ${found.length} 段 · ${groups.length} 个版本` : `来源证据 · ${found.length} 条`);
    const scope = [`截止日期 ${data.as_of || '今天'}`];
    if (data.start_date) scope.push(`文档日期不早于 ${data.start_date}`);
    if (data.limit) scope.push(`片段上限 ${data.limit} 段`);
    text(host, 'p', `${scope.join(' · ')}。来源声明与模型推断需要分别核对；日期未知、证据不足与冲突不代表事实已被确认。`, 'hint');
    aliasHint(host, data);
    anchorHint(host, data);
    if (!found.length) text(host, 'p', '没有找到满足权限与截止时间的证据。', 'empty');
    renderGroups(host, data);
    for (const warning of data.warnings || []) text(host, 'p', typeof warning === 'string' ? warning : JSON.stringify(warning), 'note warn');
    if (data.conflicts?.length) { const d = document.createElement('details'); text(d, 'summary', `冲突候选 ${data.conflicts.length} 项`); text(d, 'pre', JSON.stringify(data.conflicts, null, 2), 'mono'); host.append(d); }
    window.DesktopLibrary?.searchRendered(host, data);
  }
  /* 汇总回答：把 search 的结构化结果排成「摘录 → 关系 → 推断」，
     推断永远带 citation_id，且明确标注它是规则推断而不是模型结论。 */
  function renderAnswer(host, data) {
    host.replaceChildren();
    const found = data.results || [], groups = data.groups || [], relations = data.relations || [];
    const wrap = document.createElement('section'); wrap.className = 'answer';
    text(wrap, 'h3', `汇总回答 · ${found.length} 段证据 · ${groups.length} 个版本`);
    const scope = [`截止日期 ${data.as_of || '今天'}`];
    if (data.start_date) scope.push(`文档日期不早于 ${data.start_date}`);
    if (data.limit) scope.push(`片段上限 ${data.limit} 段`);
    scope.push(data.mode === 'evidence_extract' ? '规则汇总，非模型生成' : String(data.mode || '规则汇总'));
    text(wrap, 'p', scope.join(' · '), 'hint');
    aliasHint(wrap, data);
    anchorHint(wrap, data);
    if (!found.length) {
      text(wrap, 'p', '证据不足：未找到当前权限与截止时间范围内的资料。可放宽截止日期、去掉股票代码或主体限制后重试；没有证据时不生成结论。', 'note warn');
      host.append(wrap); window.DesktopLibrary?.searchRendered(host, data); return;
    }
    text(wrap, 'p', '下面按固定顺序拼接：关系证据 → 条件性推断 → 冲突。推断都标明了依据片段，但不等于事实；影响规模、因果关系和收益都无法由此得出。', 'note');

    text(wrap, 'h4', `关系证据 · ${relations.length} 条`);
    if (!relations.length) text(wrap, 'p', '本次没有命中带有效期的关系证据。', 'hint');
    for (const edge of relations) {
      const row = document.createElement('div'); row.className = 'answer-edge';
      text(row, 'p', `${edge.subject} —${edge.predicate}→ ${edge.object}`);
      text(row, 'p', `有效期 ${edge.valid_from || '未知'} 至 ${edge.valid_to || '未声明'} · [${edge.doc}:${edge.chunk}]`, 'hint');
      wrap.append(row);
    }

    const inferences = data.inferences || [];
    text(wrap, 'h4', `条件性推断 · ${inferences.length} 条`);
    if (!inferences.length) text(wrap, 'p', '本次未触发条件性推断：需要同时命中「供应商关系」与停产、延期、短缺、制裁、火灾一类事件证据，且两侧都没有警告。', 'hint');
    for (const item of inferences) {
      const card = document.createElement('article'); card.className = 'answer-edge';
      text(card, 'p', item.text);
      text(card, 'p', `依据 ${item.evidence_ids.join('、')} · ${item.kind === 'bounded_rule_inference' ? '有界规则推断' : item.kind}`, 'hint');
      card.append(action('查看依据原文', async () => {
        if (card.querySelector('.citation-pop')) return;
        const pop = document.createElement('div'); pop.className = 'citation-pop';
        for (const ref of item.evidence_ids) {
          const cite = await api('knowledge/citations/' + ref);
          text(pop, 'p', `${ref} · ${cite.document.filename} · 文档日期 ${cite.document.metadata?.document_date || '未知'}`, 'hint');
          chunkText(pop, [cite.chunk]);
        }
        card.append(pop);
      }));
      wrap.append(card);
    }

    const conflicts = data.conflicts || [];
    if (conflicts.length) {
      text(wrap, 'h4', `冲突候选 · ${conflicts.length} 项（不自动择一）`);
      for (const item of conflicts) {
        const row = document.createElement('div'); row.className = 'answer-conflict';
        const label = item.field || [item.subject, item.field, item.period, item.unit].filter(Boolean).join(' · ');
        text(row, 'p', item.status === 'same_period_unit_different_source_values'
          ? `${label}：同主体、同周期、同单位，不同来源数值不同`
          : `${label}：取值不同，可能是周期或口径不同`);
        for (const source of item.sources || []) text(row, 'p', `${JSON.stringify(source.value)} · ${source.document_date || '日期未知'} · ${source.citation_id}`, 'hint');
        wrap.append(row);
      }
    }

    if (data.warnings?.length) {
      const box = document.createElement('div'); box.className = 'note warn';
      text(box, 'h4', '需要注意');
      for (const warning of data.warnings) text(box, 'p', typeof warning === 'string' ? warning : JSON.stringify(warning));
      wrap.append(box);
    }

    const details = document.createElement('details');
    text(details, 'summary', `展开 ${found.length} 段来源原文`);
    renderGroups(details, data);
    wrap.append(details);
    if (data.answer) {
      const raw = document.createElement('details');
      text(raw, 'summary', '纯文本（可复制进报告）');
      text(raw, 'pre', data.answer, 'mono');
      wrap.append(raw);
    }
    host.append(wrap); window.DesktopLibrary?.searchRendered(host, data); host.scrollIntoView({block: 'start'});
  }
  function evidence(data) {
    let host = $('knowledge-report-evidence');
    if (!host) { host = document.createElement('section'); host.id = 'knowledge-report-evidence'; ($('analysis-pane-report') || $('inspector-content')).append(host); }
    renderEvidence(host, data); host.scrollIntoView({block: 'start'});
  }
  const CONFIG_LABELS = {provider: '服务类型', base_url: '服务地址', model: '模型名称', version: '模型版本', timeout_seconds: '单次超时（秒）', allow_external: '允许向远程服务发送资料与查询', mode: '处理范围', document_timeout_seconds: '每份资料总超时（秒）', max_calls: '每份资料最大调用次数', max_input_chars: '单次输入字符上限', max_output_tokens: '单次输出 Token 上限', budget_usd: '每份资料预算（美元）', input_usd_per_million: '每百万输入 Token 单价（美元）', output_usd_per_million: '每百万输出 Token 单价（美元）'};
  async function configs() {
    const key = identity();
    const [embedding, cleaner, indexes] = await Promise.all([api('knowledge/config'), api('knowledge/cleaner/config'), api('knowledge/indexes')]);
    if (key !== identity()) return;
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
  async function uploadDocumentFile(file, options = {}) {
    if (!file || !file.size || file.size > 10 * 1024 * 1024) throw new Error('请选择 1 字节至 10 MiB 的受支持文件');
    const key = options.key ?? identity();
    const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    const metadata = {source: '用户上传', available_date: localInput(new Date()).slice(0, 10), ...(options.metadata || {})};
    if (!key || key !== identity()) throw new Error('资料库已切换，请重新上传');
    await api('knowledge/documents', 'POST', {filename: file.name, data: btoa(binary), logical: options.logical || file.name, metadata});
  }
  $('knowledge-refresh').onclick = safe(() => load());
  $('knowledge-upload').onsubmit = safe(async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('[type=submit]'); button.disabled = true;
    try {
      const file = $('knowledge-file').files[0];
      const metadata = {source: $('knowledge-source').value || '用户上传', available_date: $('knowledge-available').value};
      if ($('knowledge-date').value) metadata.document_date = $('knowledge-date').value;
      if ($('knowledge-valid').value) metadata.valid_to = $('knowledge-valid').value;
      for (const [key, id] of TAGS) { const values = tagValues(id); if (values.length) metadata[key] = values; }
      await uploadDocumentFile(file, {logical: $('knowledge-logical').value || file.name, metadata});
      $('knowledge-file').value = ''; notice('资料已排队，等待独立清洗进程处理。'); await load(); goCatalog();
    } finally { button.disabled = false; }
  });
  function searchFilters() {
    const body = {query: $('knowledge-query').value, limit: Number($('knowledge-limit').value) || 8};
    for (const [name, id] of [['as_of', 'knowledge-asof'], ['start_date', 'knowledge-start'], ['stock_code', 'knowledge-stock'], ['entity', 'knowledge-entity']]) if ($(id).value) body[name] = $(id).value;
    return body;
  }
  $('knowledge-search').onsubmit = safe(async event => {
    event.preventDefault(); const button = event.currentTarget.querySelector('[type=submit]'); button.disabled = true;
    const key = identity(), request = ++searchRequest, filters = searchFilters(), signature = JSON.stringify(filters);
    window.DesktopLibrary?.searchLoading('检索');
    try {
      const data = await api('knowledge/search', 'POST', filters);
      if (key === identity() && (!matchMedia('(min-width: 761px)').matches || request === searchRequest && signature === JSON.stringify(searchFilters()))) renderEvidence($('knowledge-results'), data);
      else if (key === identity() && request === searchRequest) window.DesktopLibrary?.searchDiscarded();
    } catch (error) {
      if (key === identity() && request === searchRequest) window.DesktopLibrary?.searchError(error.message);
      throw error;
    } finally { button.disabled = false; }
  });
  $('knowledge-answer').onclick = safe(async () => {
    const button = $('knowledge-answer'), host = $('knowledge-answer-result');
    if (!$('knowledge-query').value.trim()) { notice('先填写要查的问题。', true); $('knowledge-query').focus(); return; }
    button.disabled = true;
    const key = identity(), request = ++searchRequest, filters = searchFilters(), signature = JSON.stringify(filters);
    window.DesktopLibrary?.searchLoading('规则汇总');
    try {
      const data = await api('knowledge/answer', 'POST', filters);
      if (key === identity() && (!matchMedia('(min-width: 761px)').matches || request === searchRequest && signature === JSON.stringify(searchFilters()))) renderAnswer(host, data);
      else if (key === identity() && request === searchRequest) window.DesktopLibrary?.searchDiscarded();
    } catch (error) {
      if (key === identity() && request === searchRequest) window.DesktopLibrary?.searchError(error.message);
      throw error;
    } finally { button.disabled = false; }
  });
  $('knowledge-rebuild').onclick = safe(async () => {
    if (!confirm('按已保存的配置重建索引？启用远程 Embedding 时会发送资料并可能计费，失败时保留旧索引。')) return;
    const button = $('knowledge-rebuild'); button.disabled = true;
    try { await api('knowledge/rebuild', 'POST', {}); notice('索引重建完成。'); await configs(); } finally { button.disabled = false; }
  });
  return {init, load, reset, identityReset, scope: () => scope, restore, selection, evidence, open:openDocuments, close:closeDetail, filter:filterStatus, filterStatus:() => desktopStatus, processing: safe(() => openTab('processing'))};
})();
