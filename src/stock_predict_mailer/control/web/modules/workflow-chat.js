/* A professional conversation uses the same task runner and event receipts as the canvas. */
window.WorkflowChat = (() => {
  const mode = 'professional', endpoint = 'workflows/definitions';
  const read = key => AnalysisMode.read('workflow-chat.' + key, mode);
  const write = (key, value) => AnalysisMode.write('workflow-chat.' + key, value, mode);
  const terminal = state => ['completed', 'failed', 'canceled'].includes(state);
  const stateLabel = {submitted:'排队中', working:'运行中', running:'运行中', completed:'已完成',
    failed:'失败', skipped:'已跳过', canceled:'已取消', degraded:'已降级', waiting:'等待执行', needs_input:'等待用户处理'};
  const flows = new Map(), workspaces = new Map(), runs = new Map(), articles = new Map();
  let root, directoryRoot, shortcut, canvasShortcut, current = '', fields = {}, timer, catalogRequest, identity = '', failedCatalog = '';
  let stopSpeech;
  const mk = (tag, className) => Object.assign(document.createElement(tag), {className:className || ''});
  const el = id => root.querySelector('#workflow-chat-' + id);
  const scope = () => ({...AnalysisMode.capture(), mode});
  const active = () => root && !root.hidden;
  const directoryActive = () => directoryRoot && !directoryRoot.hidden;
  const flow = () => flows.get(current);
  const path = (id, suffix = '') => endpoint + '/' + encodeURIComponent(id) + suffix;
  const matches = id => active() && id === current;
  const duration = ms => ms == null ? '' : ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(1) + ' 秒';

  function button(label, click, className = 'btn tiny') {
    const node = mk('button', className);
    node.type = 'button'; node.textContent = label; node.onclick = click;
    return node;
  }
  function state(id = current) {
    if (!workspaces.has(id)) {
      const stored = read('flow.' + id) || {};
      workspaces.set(id, {draft:{message:'', values:{}, ...stored.draft}, ids:stored.ids || [],
        viewing:stored.viewing || '', scroll:stored.scroll, pending:stored.pending,
        history:[], cursor:null, error:'', historyError:'', waiting:false});
    }
    return workspaces.get(id);
  }
  function persist(id = current) {
    if (!id) return;
    const {draft, ids, viewing, scroll, pending} = state(id);
    write('flow.' + id, {draft, ids:ids.slice(-20), viewing, scroll, pending});
  }
  function choices() {
    const model = AnalysisMode.read('model', mode);
    const saved = AnalysisMode.read('tools', mode);
    const allowed = settings?.agents?.main?.tools || [];
    return {...(model ? {model_id:model} : {}), ...(saved ? {tools:saved.filter(item => allowed.includes(item))} : {})};
  }
  const effort = () => state().draft.effort || settings?.default_reasoning_effort || 'extreme';
  async function importLocal(context) {
    for (const item of window.DesktopWorkbench.legacyDefinitions()) {
      if (!item.label || !item.graph) continue;
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(item.key || item.label));
      const key = Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
      if (read('import.' + key)) continue;
      try {
        await api(endpoint, 'POST', {name:item.label, graph:item.graph, import_key:key, draft:true, ...choices()}, undefined, context);
        if (context.key === memoryKey) write('import.' + key, true);
      } catch (_) { /* The original canvas draft remains available for validation and editing. */ }
    }
  }
  function loadCatalog({reload = false} = {}) {
    const context = scope();
    const query = new URLSearchParams(Object.entries(choices()).map(([key, value]) => [key, Array.isArray(value) ? JSON.stringify(value) : value]));
    const key = context.key + '?' + query;
    if (!reload && catalogRequest?.key === key) return catalogRequest.promise;
    const request = catalogRequest = {key};
    request.promise = (async () => {
      try {
        await importLocal(context);
        const data = await api(endpoint + '?' + query, 'GET', undefined, undefined, context);
        if (catalogRequest !== request || context.key !== memoryKey) return;
        fields = data.fields;
        flows.clear(); data.items.forEach(item => flows.set(item.id, item));
        failedCatalog = '';
      } catch (error) {
        if (catalogRequest === request && context.key === memoryKey) failedCatalog = error.message;
      } finally {
        if (catalogRequest === request) {
          catalogRequest = null;
          if (active()) { renderHeader(); renderFormIfChanged(); }
          if (directoryActive()) renderDirectory();
        }
      }
    })();
    if (active()) renderFeedback();
    return request.promise;
  }
  function setSurface(value) { write('surface', value); syncView(); }
  function showDirectory() { if (AnalysisMode.active() !== mode) return; write('surface', 'directory'); syncView(); loadCatalog(); }
  function flowImage(item) {
    const image = item?.image;
    return image?.mime && image?.data ? 'data:' + image.mime + ';base64,' + image.data : '';
  }
  function appendFlowImage(host, item, className = 'wfcat-inline-image') {
    const image = flowImage(item), preview = mk('span', className);
    if (image) { const img = document.createElement('img'); img.src = image; img.alt = ''; img.onerror = () => { img.remove(); preview.classList.add('wfcat-default-image'); }; preview.append(img); }
    else preview.classList.add('wfcat-default-image');
    host.append(preview); return preview;
  }
  function renderDirectory() {
    if (!directoryRoot) return;
    const grid = directoryRoot.querySelector('.wfcat-grid');
    const status = directoryRoot.querySelector('.wfcat-status');
    grid.replaceChildren();
    status.textContent = failedCatalog ? '流程读取失败：' + failedCatalog : flows.size ? '' : '还没有保存流程，先新建一个流程。';
    const create = mk('article', 'wfcat-card wfcat-create');
    const createHead = mk('div', 'wfcat-card-head'), mark = text(createHead, 'span', '+', 'wfcat-create-mark');
    mark.setAttribute('aria-hidden', 'true');
    const openBlank = () => enterCanvas(null, {empty:true});
    const add = button('新建流程', event => { event.stopPropagation(); openBlank(); }, 'wfcat-create-title');
    add.id = 'wfcat-new'; createHead.append(add);
    const createActions = mk('div', 'actions wfcat-actions');
    createActions.append(button('分析模板', event => { event.stopPropagation(); enterCanvas(null); }));
    create.append(createHead, createActions); create.onclick = openBlank; grid.append(create);
    if (failedCatalog) { status.append(' ', button('重试读取', loadCatalog)); return; }
    [...flows.values()].sort((a,b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''))).forEach(item => {
      const card = mk('article', 'wfcat-card'), head = mk('div', 'wfcat-card-head'), heading = mk('div', 'wfcat-card-heading');
      appendFlowImage(head, item, 'wfcat-image');
      const title = text(heading, 'h3', item.name); title.title = item.name;
      const meta = text(heading, 'p', item.updated_at ? '更新于 ' + fmt(item.updated_at) : '版本 ' + item.revision.slice(0,8), 'wfcat-meta');
      const state = text(meta, 'span', item.runnable ? '可运行' : '草稿', 'wfcat-state');
      state.dataset.state = item.runnable ? 'ready' : 'invalid';
      if (!item.runnable) state.title = item.reason || '配置未完成';
      head.append(heading);
      if (item.mode === 'custom') {
        const versions = button('版本记录', event => { event.stopPropagation(); showRevisions(item); }, 'btn tiny wfcat-versions');
        versions.setAttribute('aria-label', item.name + '的版本记录');
        head.append(versions);
      }
      card.append(head);
      if (item.description) text(card, 'p', item.description, 'hint wfcat-description');
      const actions = mk('div', 'actions wfcat-actions');
      actions.append(button('打开画布', event => { event.stopPropagation(); enterCanvas(item); }), button('编辑卡片', event => { event.stopPropagation(); editCard(item); }), button('在对话中使用', event => { event.stopPropagation(); select(item.id); setSurface('chat'); }));
      card.append(actions); card.onclick = () => enterCanvas(item); grid.append(card);
    });
  }
  function syncView() {
    if (!root) return;
    const professional = AnalysisMode.active() === mode && document.body.dataset.view === 'analysis';
    const surface = read('surface') || 'directory';
    const show = professional && surface === 'chat';
    const showDirectory = professional && surface === 'directory';
    document.body.classList.toggle('workflow-mobile-canvas', professional && surface === 'canvas');
    shortcut.hidden = !professional;
    shortcut.setAttribute('aria-pressed', String(show));
    canvasShortcut.hidden = !professional;
    canvasShortcut.setAttribute('aria-pressed', String(showDirectory));
    if (show === !root.hidden && showDirectory === !directoryRoot.hidden) return;
    if (!show) stopSpeech();
    root.hidden = !show;
    directoryRoot.hidden = !showDirectory;
    document.body.classList.toggle('workflow-chat-view', show || showDirectory);
    clearTimeout(timer);
    if (show || showDirectory) {
      if (identity !== memoryKey) {
        identity = memoryKey; flows.clear(); workspaces.clear(); runs.clear(); articles.clear(); current = read('selected') || '';
      }
      if (show) render();
      if (showDirectory) renderDirectory();
      loadCatalog().then(() => { if (active() && flow()) resume(current); });
    } else {
      persist();
      for (const dialog of document.querySelectorAll('.workflow-chat-dialog[open]')) dialog.close();
    }
  }
  function enterCanvas(value, options) {
    window.DesktopWorkbench?.setMode('focus');
    if (!window.DesktopWorkbench?.useDefinition(value || null, options)) {
      state().error = '画布尚未加载，请重试。';
      if (active()) renderFeedback(); return;
    }
    setSurface('canvas');
    window.DesktopWorkbench?.checkWorkflow();
    if (matchMedia('(max-width: 760px)').matches) requestAnimationFrame(window.DesktopWorkbench.fitCanvas);
    return true;
  }
  function dialog(title) {
    const layer = mk('dialog', 'plugin-dialog workflow-chat-dialog');
    layer.setAttribute('aria-label', title);
    const head = mk('header', 'wfchat-dialog-head');
    text(head, 'h2', title); head.append(button('关闭', () => layer.close()));
    const body = mk('div', 'wfchat-dialog-body'); layer.append(head, body);
    layer.onclose = () => layer.remove();
    document.body.append(layer); layer.showModal();
    return {layer, body};
  }
  function revisionChanges(current, selected) {
    const canonical = value => JSON.stringify(value, (_, item) =>
      item && typeof item === 'object' && !Array.isArray(item)
        ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
    const differs = (left, right) => canonical(left) !== canonical(right);
    const changes = [];
    const previous = new Map(current.graph.nodes.map(node => [node.id, node]));
    const next = new Map(selected.graph.nodes.map(node => [node.id, node]));
    const name = node => node.data.label || node.id;
    for (const [id, node] of next) {
      const old = previous.get(id);
      if (!old) { changes.push('新增节点 · ' + name(node)); continue; }
      const fields = [];
      const {label, type, ...config} = node.data;
      const {label: oldLabel, type: oldType, ...oldConfig} = old.data;
      if (label !== oldLabel) fields.push('名称');
      if (type !== oldType) fields.push('类型');
      if (differs(oldConfig, config)) fields.push('配置');
      if (differs(old.position, node.position)) fields.push('画布位置');
      if (fields.length) {
        const label = name(old) === name(node) ? name(node) : name(old) + ' → ' + name(node);
        changes.push('更新节点 · ' + label + ' · ' + fields.join('、'));
      }
    }
    for (const [id, node] of previous) if (!next.has(id)) changes.push('移除节点 · ' + name(node));
    if (differs([...previous.keys()].filter(id => next.has(id)), [...next.keys()].filter(id => previous.has(id))))
      changes.push('调整节点顺序');
    if ((previous.size !== current.graph.nodes.length || next.size !== selected.graph.nodes.length)
        && differs(current.graph.nodes, selected.graph.nodes)) changes.push('节点 ID 重复，请核对画布中的节点');

    function edges(graph) {
      return graph.edges.map(({source, target, output = 'value', input = 'value', field = '', condition = 'always'}) =>
        [source, output, field, target, input, condition]);
    }
    const oldEdges = edges(current.graph), newEdges = edges(selected.graph);
    const unmatched = oldEdges.map(edge => JSON.stringify(edge));
    const edgeLabel = ([source, output, field, target, input, condition], nodes) => {
      const label = id => nodes.has(id) ? name(nodes.get(id)) : id;
      return label(source) + '.' + output + (field && field !== output ? '［' + field + '］' : '') + ' → ' +
        label(target) + '.' + input + (condition !== 'always' ? ' · ' + condition : '');
    };
    let added = false;
    for (const edge of newEdges) {
      const index = unmatched.indexOf(JSON.stringify(edge));
      if (index !== -1) { unmatched.splice(index, 1); continue; }
      changes.push('新增连线 · ' + edgeLabel(edge, next)); added = true;
    }
    for (const edge of unmatched) changes.push('移除连线 · ' + edgeLabel(JSON.parse(edge), previous));
    if (!added && !unmatched.length && differs(oldEdges, newEdges)) changes.push('调整连线顺序');

    for (const [key, label] of Object.entries({name:'名称', description:'描述', image:'图标', inputs:'分析输入'}))
      if (differs(current[key] ?? null, selected[key] ?? null)) changes.push('更新流程' + label);
    if (Boolean(current.draft) !== Boolean(selected.draft)) changes.push('保存时的草稿状态不同');
    for (const [key, label] of Object.entries({notes:'注释', comments:'评论'}))
      if (differs(current.graph.canvas?.[key] || [], selected.graph.canvas?.[key] || [])) changes.push('更新画布' + label);
    if (differs(Object.fromEntries(current.draft_edits || []), Object.fromEntries(selected.draft_edits || [])))
      changes.push('更新未提交的节点参数');
    return changes;
  }
  function showRevisions(item) {
    const {layer, body} = dialog('流程版本记录');
    const context = scope(), url = path(item.id, '/revisions');
    const visible = () => layer.open && AnalysisMode.current(context);
    const status = text(body, 'p', '', 'hint');
    status.role = 'status';
    const list = mk('div', 'wfcat-revision-list'), preview = mk('section', 'wfcat-revision-preview');
    const more = button('加载更早的版本', load);
    body.append(list, more, preview);
    const readVersion = revision => api(url + '/' + revision, 'GET', undefined, undefined, context);
    let cursor, latest, baseline, selection = 0;
    const compareAgainst = () => baseline ||= readVersion(latest).catch(error => { baseline = null; throw error; });
    async function load() {
      more.hidden = true;
      status.textContent = '正在读取版本…';
      try {
        const page = await api(url + (cursor ? '?before=' + cursor : ''), 'GET', undefined, undefined, context);
        if (!visible()) return;
        latest ||= page.items[0]?.revision;
        cursor = page.next_before;
        status.textContent = item.name;
        for (const row of page.items) {
          const currentVersion = row.revision === latest;
          const label = [
            currentVersion ? '当前' : '版本', row.revision.slice(0, 8), fmt(row.updated_at), row.name,
            row.draft ? '草稿' : '', row.restored_from ? '恢复自 ' + row.restored_from.slice(0, 8) : '',
          ].filter(Boolean).join(' · ');
          const entry = button(label, () => inspect(row, entry), 'btn tiny');
          entry.setAttribute('aria-pressed', 'false');
          list.append(entry);
        }
        more.textContent = '加载更早的版本';
        more.hidden = !cursor;
      } catch (error) {
        if (!visible()) return;
        status.textContent = error.message;
        more.textContent = '重试读取'; more.hidden = false;
      }
    }
    async function inspect(row, entry) {
      const request = ++selection, revisionUrl = url + '/' + row.revision;
      for (const control of list.children) control.setAttribute('aria-pressed', String(control === entry));
      preview.replaceChildren();
      const feedback = text(preview, 'p', '正在读取版本…', 'hint');
      feedback.role = 'status';
      try {
        const version = await readVersion(row.revision);
        if (!visible() || request !== selection) return;
        feedback.textContent = '版本 ' + version.revision.slice(0, 8);
        text(preview, 'h3', version.name);
        if (version.description) text(preview, 'p', version.description);
        renderGraph(preview, version);
        if (row.revision === latest) { baseline ||= Promise.resolve(version); return; }
        const comparison = mk('details', 'wfcat-revision-diff');
        text(comparison, 'summary', '与当前版本对比');
        const summary = text(comparison, 'p', '', 'hint');
        summary.role = 'status';
        let requested = false;
        comparison.ontoggle = async () => {
          if (!comparison.open || requested) return;
          requested = true;
          summary.textContent = '正在读取当前版本…';
          try {
            const base = await compareAgainst();
            if (!visible() || request !== selection) return;
            const changes = revisionChanges(base, version);
            const label = '当前 ' + base.revision.slice(0, 8) + ' → 所选 ' + version.revision.slice(0, 8);
            summary.textContent = label + (changes.length ? ' · 已保存内容的差异' : ' · 流程内容一致');
            if (changes.length) {
              const entries = mk('ul');
              for (const change of changes) text(entries, 'li', change);
              comparison.append(entries);
            }
          } catch (error) {
            if (visible() && request === selection) summary.textContent = error.message + '。收起后重新展开可重试。';
            requested = false;
          }
        };
        preview.append(comparison);
        const restore = button('恢复此版本', async () => {
          if (restore.textContent === '恢复此版本') {
            feedback.textContent = '将此版本的画布和卡片保存为新的当前版本。';
            restore.textContent = '确认恢复'; return;
          }
          restore.disabled = true;
          try {
            const saved = await api(revisionUrl + '/restore', 'POST', {base_revision:latest, ...choices()}, undefined, context);
            if (context.key !== memoryKey) return;
            if (visible()) { layer.close(); notice('已恢复流程 · ' + saved.revision.slice(0, 8)); }
            loadCatalog({reload:true});
          } catch (error) {
            if (visible() && request === selection) feedback.textContent = error.message;
            restore.disabled = false;
          }
        }, 'btn primary');
        preview.append(restore);
      } catch (error) {
        if (visible() && request === selection) feedback.textContent = error.message;
      }
    }
    load();
  }
  async function editCard(item) {
    const {layer, body} = dialog('编辑流程卡片');
    const form = mk('form', 'stack');
    form.innerHTML = '<label class="field"><span>流程名称</span><input name="name" maxlength="80" required></label><label class="field"><span>描述</span><textarea name="description" maxlength="400" rows="2"></textarea></label><label class="field"><span>替换图像 · PNG、JPEG 或 WebP，最大 512 KiB</span><input name="image" type="file" accept="image/png,image/jpeg,image/webp"></label><div class="wfcat-image wfcat-image-preview" data-image-preview></div><button type="button" class="btn tiny" data-image-reset>恢复默认图标</button><p class="warn" role="alert"></p><button type="submit" class="btn primary">保存卡片</button>';
    form.elements.name.value = item.name; form.elements.description.value = item.description || '';
    let image = item.image || null, reset = false; const preview = form.querySelector('[data-image-preview]');
    const show = value => { preview.replaceChildren(); preview.classList.toggle('wfcat-default-image', !value); if (value) { const img = document.createElement('img'); img.src = 'data:' + value.mime + ';base64,' + value.data; img.alt = '流程图像'; preview.append(img); } };
    show(image);
    form.elements.image.onchange = async () => { const file = form.elements.image.files?.[0]; if (!file) return; if (file.size > 512 * 1024 || !['image/png','image/jpeg','image/webp'].includes(file.type)) { form.querySelector('[role="alert"]').textContent = '请选择不超过 512 KiB 的 PNG、JPEG 或 WebP 图像。'; form.elements.image.value = ''; return; } const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(file); }); image = {mime:file.type, data}; reset = false; show(image); };
    form.querySelector('[data-image-reset]').onclick = () => { image = null; reset = true; form.elements.image.value = ''; show(null); };
    form.onsubmit = async event => { event.preventDefault(); const submit = form.querySelector('[type="submit"]'); submit.disabled = true; const values = {name:form.elements.name.value, description:form.elements.description.value, graph:item.graph, inputs:item.inputs, draft:true, draft_edits:item.draft_edits || [], base_revision:item.revision}; if (image || reset) values.image = image; try { const saved = await api(path(item.id), 'PUT', values, undefined, scope()); flows.set(saved.id,{...saved,runnable:!saved.draft}); layer.close(); renderDirectory(); } catch (error) { form.querySelector('[role="alert"]').textContent = error.message; } finally { submit.disabled = false; } };
    body.append(form); form.elements.name.focus();
  }
  async function choose() {
    const {layer, body} = dialog('选择流程');
    const listing = mk('div', 'wfchat-picker');
    text(listing, 'p', '正在读取流程…', 'hint'); body.append(listing);
    body.append(button('打开画布', () => { layer.close(); enterCanvas(null,{empty:true}); }));
    await loadCatalog();
    if (!layer.open) return;
    listing.replaceChildren();
    if (failedCatalog) text(listing, 'p', failedCatalog, 'warn');
    for (const item of flows.values()) {
      const row = button('', () => { layer.close(); select(item.id); }, 'wfchat-choice');
      row.setAttribute('aria-pressed', String(item.id === current));
      appendFlowImage(row, item);
      text(row, 'strong', item.name);
      text(row, 'span', item.runnable ? '可运行 · '+item.revision.slice(0, 8) : item.reason, 'hint');
      listing.append(row);
    }
  }
  function select(id) {
    if (!flows.has(id)) return;
    stopSpeech();
    persist();
    current = id; write('selected', id);
    render();
    resume(id);
  }
  function renderHeader() {
    const item = flow();
    el('title').textContent = item?.name || '';
    el('title').hidden = !item;
    const choose = el('choose');
    choose.textContent = item?.name || '选择流程';
    choose.title = item ? '选择流程 · ' + item.name : '选择流程';
    choose.setAttribute('aria-label', choose.title);
    const host = el('definition');
    host.replaceChildren();
    if (!item) { text(host, 'p', '选择后可查看流程说明与版本。', 'hint'); return; }
    appendFlowImage(host, item); text(host, 'h3', item.name);
    if (item.description) text(host, 'p', item.description, 'hint');
    text(host, 'p', (item.runnable ? '可运行版本 ' : '版本 ') + item.revision.slice(0, 10), 'wfchat-version');
    const actions = mk('div', 'actions');
    actions.append(button('查看流程', () => showDefinition(item)), button('画布编辑', () => enterCanvas(item)));
    host.append(actions);
  }
  function showDefinition(item, historical = false) {
    const {body} = dialog(historical ? '执行时的流程' : item.name);
    text(body, 'p', '版本 '+item.revision, 'wfchat-version');
    if (item.description) text(body, 'p', item.description);
    renderGraph(body, item);
  }
  function renderGraph(body, item) {
    const nodes = new Map(item.graph.nodes.map(node => [node.id, node.data.label]));
    const list = mk('ol', 'wfchat-graph-list');
    for (const node of item.graph.nodes) {
      const children = item.graph.edges.filter(edge => edge.source === node.id).map(edge => nodes.get(edge.target));
      text(list, 'li', node.data.label + (children.length ? ' → '+children.join('、') : ''));
    }
    body.append(list);
  }
  function renderFormIfChanged() {
    const item = flow(), signature = item ? item.id + item.revision : '';
    if (el('form').dataset.signature !== signature) renderForm();
    else renderFeedback();
  }
  function renderForm() {
    const item = flow(), data = state();
    el('form').dataset.signature = item ? item.id + item.revision : '';
    el('message').value = data.draft.message;
    el('knowledge').value = data.draft.knowledge || 'local';
    const host = el('parameters');
    host.replaceChildren();
    const custom = Array.isArray(item?.fields), parameters = inputFields(item);
    const knowledge = custom ? WorkflowNodeUI.needsLibrary(item.graph) : true;
    el('inputs').hidden = !parameters.length && !knowledge;
    el('knowledge').closest('label').hidden = !knowledge;
    el('fill').hidden = custom;
    const requiredCount = parameters.filter(field=>field.required && field.default===undefined).length;
    el('parameter-toggle').lastElementChild.textContent = requiredCount ? '参数 · ' + requiredCount + ' 项必填' : '补充参数';
    for (const field of parameters) {
      const {name, required}=field;
      const checkbox=field.type==='boolean' && !custom, list=['object','list','lines'].includes(field.type);
      const label = mk('label', checkbox ? 'check' : 'field');
      const input = mk(field.type === 'choice' || (custom && field.type==='boolean') ? 'select' : list ? 'textarea' : 'input');
      input.name = name; input.id = 'workflow-chat-input-' + name;
      if (checkbox) {
        input.type = 'checkbox'; input.checked = Boolean(data.draft.values[name]);
      } else {
        if (field.type === 'choice') input.append(new Option('请选择', ''), ...Object.entries(field.options).map(([key, value]) => new Option(value, key)));
        if (custom && field.type==='boolean') input.append(new Option('未填写',''),new Option('是','true'),new Option('否','false'));
        if (field.type === 'object' || field.type==='list') { input.rows = 3; input.placeholder = '粘贴 '+field.label+' JSON'; input.spellcheck = false; }
        if (field.type === 'lines') { input.rows = 2; input.placeholder = '每行一项'; }
        if (field.type==='number') { input.type='number';input.step='any'; }
        const fallback=field.default;
        input.value = data.draft.values[name] ?? (fallback===undefined?'': typeof fallback==='string'?fallback:JSON.stringify(fallback));
      }
      text(label, 'span', field.label + (required ? ' · 必填' : ''));
      if (required) input.setAttribute('aria-required', 'true');
      input.oninput = () => {
        data.draft.values[name] = checkbox ? input.checked : input.value;
        if (!data.pending) data.error = '';
        input.removeAttribute('aria-invalid'); persist(item.id);
        renderFeedback();
      };
      label.append(input); host.append(label);
    }
    el('inputs').open = Boolean(data.draft.inputsOpen);
    renderFeedback();
  }
  function inputFields(item) {
    if (Array.isArray(item?.fields)) return item.fields.map(field=>({...field,label:field.label || field.name}));
    return Object.entries(item?.inputs || {}).filter(([name])=>fields[name]).map(([name,required])=>({...fields[name],name,required}));
  }
  function applyParameters(params) {
    const item = flow();
    if (!item) return;
    const data = state();
    for (const name of Object.keys(item.inputs)) {
      if (params[name] == null) continue;
      const type = fields[name].type;
      data.draft.values[name] = type === 'object' ? JSON.stringify(params[name], null, 2)
        : type === 'lines' ? params[name].join('\n') : params[name];
    }
    persist();
    renderForm();
  }
  function readParameters(item) {
    const parameters = {};
    for (const field of inputFields(item)) {
      const {name, required}=field, input = el('input-' + name);
      const value = input.type === 'checkbox' ? input.checked : input.value.trim();
      try {
        if (value === '') {
          if (required && field.default===undefined) throw Error('请填写'+field.label);
          continue;
        }
        const parsed = ['object','list','number','boolean'].includes(field.type) && typeof value==='string' ? JSON.parse(value)
          : field.type === 'lines' ? value.split(/\r?\n/).map(line => line.trim()).filter(Boolean) : value;
        if (field.type === 'object' && (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))) throw Error(field.label+'需要 JSON 对象');
        if (field.type === 'list' && !Array.isArray(parsed)) throw Error(field.label+'需要 JSON 数组');
        parameters[name] = parsed;
      } catch (error) {
        el('inputs').open = true; input.setAttribute('aria-invalid','true'); input.focus();
        if (error instanceof SyntaxError) throw Error(field.label+'的 JSON 格式无效');
        throw error;
      }
    }
    return parameters;
  }
  function renderFeedback() {
    const item = flow(), data = state();
    const running = data.ids.some(id => runs.get(id)?.task && !terminal(runs.get(id).task.status.state));
    el('feedback').textContent = data.error || failedCatalog || (data.pending
      ? '提交尚未确认。可用原提交标识恢复。' : !item ? '请选择一个流程。'
      : !item.runnable ? item.reason : running ? '此流程正在处理上一条需求。' : '');
    el('feedback').classList.toggle('warn', Boolean(data.error || failedCatalog || (item && !item.runnable)));
    el('send').disabled = !item?.runnable || Boolean(catalogRequest || data.waiting || data.pending || running);
    el('message').disabled = !item;
    el('resume').hidden = !data.pending || data.waiting;
    el('edit').hidden = !item || (item.runnable && !data.issues?.length);
    el('edit').textContent='定位流程问题';
    el('edit').onclick=()=>{
      if(item && enterCanvas(item))window.DesktopWorkbench?.checkWorkflow({show:true});
    };
    el('live').hidden = !data.viewing;
    el('form').hidden = Boolean(data.viewing);
  }
  function runState(id, flowId) {
    if (!runs.has(id)) runs.set(id, {id, flowId, events:new Map(), cursor:0, task:null, error:''});
    return runs.get(id);
  }
  function accept(receipt, flowId) {
    const entry = runState(receipt.id, flowId);
    if (entry.flowId !== flowId) return entry;
    entry.receipt = {...entry.receipt, ...receipt};
    if (receipt.input) entry.input = receipt.input;
    if (receipt.task && (!entry.task || receipt.task.status.timestamp >= entry.task.status.timestamp ||
        (!terminal(entry.task.status.state) && terminal(receipt.task.status.state)))) {
      entry.task = receipt.task;
      entry.receipt.status = entry.task.status;
    }
    if (entry.task && entry.task.status.timestamp >= entry.receipt.status.timestamp) entry.receipt.status = entry.task.status;
    return entry;
  }
  function receiptOf(task) {
    const spec = task.metadata.workflow, info = spec.flow || {};
    return {id:task.id, task, status:task.status, input:info.input, choices:info.choices, version:info.revision || spec.version,
      started_at:spec.started_at, summary:info.input?.message || task.metadata.request?.subject || '分析运行'};
  }
  async function send(retryEntry = null) {
    const id = current, item = flow(), data = state();
    if (!item || data.waiting || data.viewing || catalogRequest || (!data.pending && !item.runnable)) return;
    stopSpeech();
    if (!data.pending) {
      try {
        const message = retryEntry?.input?.message ?? el('message').value.trim();
        if (!message) { el('message').focus(); throw Error('请输入本轮需求。'); }
        const parameters = retryEntry?.input?.parameters ?? readParameters(item);
        const picked = retryEntry?.receipt?.choices || {...choices(), reasoning_effort:effort()};
        const {knowledge_scope, ...runChoices} = picked;
        data.pending = {knowledgeScope:knowledge_scope || el('knowledge').value, fromDraft:!retryEntry, body:{revision:retryEntry?.receipt?.version || item.revision,
          key:crypto.randomUUID(), message, parameters, ...runChoices}};
        persist(id);
      } catch (error) { data.error = error.message; renderFeedback(); return; }
    }
    const outgoing = data.pending, context = {...scope(), knowledgeScope:outgoing.knowledgeScope};
    data.waiting = true; data.error = ''; data.issues=null;renderFeedback();
    try {
      const task = await api(path(id, '/runs'), 'POST', outgoing.body, undefined, context);
      if (context.key !== memoryKey || taskMode(task) !== mode || task.metadata?.workflow?.flow?.id !== id) return;
      accept(receiptOf(task), id);
      if (!data.ids.includes(task.id)) data.ids.push(task.id);
      data.ids = data.ids.slice(-20);
      if (outgoing.fromDraft && data.draft.message.trim() === outgoing.body.message) data.draft.message = '';
      data.pending = null;
      recordLoaded = false;
      if (matches(id)) {
        el('message').value = data.draft.message;
        renderThread({forceBottom:true}); renderHistory(); schedule(0);
      }
    } catch (error) {
      if (context.key !== memoryKey) return;
      if (error.status && error.status < 500) data.pending = null;
      data.error = error.message;
      data.issues=error.issues;
      if(error.issues?.length && matches(id) && enterCanvas(item))window.DesktopWorkbench?.showWorkflowIssues(error.issues);
    } finally {
      data.waiting = false;
      if (context.key === memoryKey) persist(id);
      if (matches(id)) renderFeedback();
    }
  }
  async function loadHistory(id, append = false) {
    const data = state(id), context = scope();
    if (data.historyPending) return data.historyPending;
    const base = append ? '?before=' + data.cursor : '';
    data.historyPending = (async () => {
      try {
        const page = await api(path(id, '/runs') + base, 'GET', undefined, undefined, context);
        if (context.key !== memoryKey) return;
        data.history = [...new Set([...(append ? data.history : []), ...page.items.map(item => item.id)])];
        page.items.forEach(item => accept(item, id));
        data.cursor = page.next_before; data.historyError = '';
      } catch (error) {
        if (context.key === memoryKey) data.historyError = error.message;
      }
    })();
    await data.historyPending;
    data.historyPending = null;
    if (matches(id)) renderHistory();
  }
  async function loadRun(id, flowId) {
    const entry = runState(id, flowId), context = scope();
    if (entry.loading) return entry.loading;
    entry.loading = (async () => {
      try {
        const receipt = await api(path(flowId, '/runs/' + encodeURIComponent(id)), 'GET', undefined, undefined, context);
        if (context.key !== memoryKey || receipt.id !== id || (receipt.flow_id && receipt.flow_id !== flowId)) return;
        accept(receipt, flowId);
        let page;
        do {
          page = await api('tasks/'+encodeURIComponent(id)+'/events?after='+entry.cursor, 'GET', undefined, undefined, context);
          if (context.key !== memoryKey) return;
          for (const event of page.events) {
            entry.events.set(event.seq, event); entry.cursor = Math.max(event.seq, entry.cursor);
          }
        } while (page.events.length === 100 && matches(flowId));
        entry.drained = page.events.length < 100;
        entry.error = '';
      } catch (error) {
        if (context.key === memoryKey) {
          entry.error = error.message;
          entry.unavailable = [403,404].includes(error.status);
        }
      } finally {
        entry.loading = null;
        if (context.key === memoryKey && matches(flowId)) {
          renderThread(); renderHistory(); renderFeedback();
        }
      }
    })();
    return entry.loading;
  }
  async function watch() {
    const id = current;
    if (!matches(id) || !id || document.hidden) return;
    const data = state(id), ids = data.viewing ? [data.viewing] : data.ids;
    const pending = ids.filter(tid => {
      const entry = runs.get(tid);
      return !entry?.unavailable && (!entry?.task || !terminal(entry.task.status.state) || !entry.drained);
    });
    await Promise.all(pending.map(tid => loadRun(tid, id)));
    if (matches(id) && pending.some(tid => {
      const entry = runs.get(tid);
      return !entry?.unavailable && (!entry?.task || !terminal(entry.task.status.state) || !entry.drained);
    })) schedule(pending.some(tid => runs.get(tid)?.error) ? 2300 : 650);
  }
  function schedule(delay = 650) { clearTimeout(timer); timer = setTimeout(watch, delay); }
  function resume(id) {
    loadHistory(id);
    if (matches(id)) schedule(0);
  }
  async function cancel(entry) {
    if (entry.canceling) return;
    const id = entry.flowId, context = scope();
    entry.canceling = true; renderThread();
    try {
      const task = await api('tasks/'+entry.id+'/cancel', 'POST', {}, undefined, context);
      if (context.key !== memoryKey || task.id !== entry.id || taskMode(task) !== mode) return;
      accept(receiptOf(task), id);
      entry.drained = false;
      if (matches(id)) schedule(0);
    } catch (error) {
      if (context.key === memoryKey) entry.error = error.message;
    } finally {
      entry.canceling = false;
      if (context.key === memoryKey && matches(id)) { renderThread(); renderHistory(); }
    }
  }
  function trace(entry, host, opened) {
    const task = entry.task, graph = task.metadata.workflow.graph, events = [...entry.events.values()].sort((a,b) => a.seq - b.seq);
    const nodes = new Map();
    const specs = new Map((graph?.nodes || []).flatMap(node => [[node.id,node.data],[node.data.actualKey,node.data]]));
    for (const event of events) {
      for (const step of event.steps || []) if (!nodes.has(step.id)) nodes.set(step.id, {label:step.label, events:[]});
      if (!event.step) continue;
      if (!nodes.has(event.step)) nodes.set(event.step, {label:event.label, events:[]});
      const item = nodes.get(event.step);
      item.events.push(event);
      if (event.kind === 'step') Object.assign(item, {status:event.status, duration:event.duration_ms, label:event.label || item.label});
      if (event.kind === 'node_result' && !item.status) item.status = event.status;
      const type = specs.get(event.step)?.type;
      const hits=event.summary?.hits || event.summary?.citations;
      if (event.kind === 'node_result' && type === 'knowledge' && Array.isArray(hits)) {
        item.note = '已检索到 '+hits.length+' 段知识库资料';
      } else if (event.kind === 'node_result' && event.summary?.selected && event.summary?.label && WorkflowNodeUI.branched(type)) {
        item.note = '命中 '+event.summary.label;
      } else if (event.kind === 'node_result' && type === 'report') item.note = '分析报告已生成';
      else if (event.reason || ['tool','report','knowledge','forecast'].includes(event.kind)) item.note = event.reason || event.label;
    }
    const remember = (key, value) => {
      const storage = 'trace.' + entry.id;
      write(storage, {...read(storage), [key]:value});
    };
    const list = mk('ol', 'wfchat-timeline');
    for (const [id, node] of nodes) {
      if (!node.status && terminal(task.status.state) && !node.events.length) continue;
      const li = mk('li', 'wfchat-step');
      li.dataset.state = node.status || 'waiting';
      const details = mk('details'); details.dataset.step = id; details.open = opened.has(id);
      details.ontoggle = () => remember(id, details.open);
      const row = mk('summary', 'wfchat-step-head');
      const label = mk('span', 'wfchat-step-name');
      text(label, 'strong', specs.get(id)?.label || node.label);
      if (node.note && node.note !== specs.get(id)?.label) text(label, 'span', node.note, 'hint wfchat-node-note');
      row.append(label);
      text(row, 'span', [stateLabel[li.dataset.state] || li.dataset.state, duration(node.duration)].filter(Boolean).join(' · '), 'wfchat-status');
      details.append(row);
      for (const event of node.events) {
        const sections = [['输入摘要', event.input_summary], ['输出摘要', event.summary], ['来源', event.source],
          ['工具调用', event.kind==='tool'?event.label:null], ['原因', event.reason], ['错误', event.code]];
        for (const [label,value] of sections) if (value != null && value !== '') {
          text(details, 'span', label, 'wfchat-detail-label');
          text(details, typeof value === 'object' ? 'pre' : 'p', typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value));
        }
      }
      li.append(details); list.append(li);
    }
    if (list.children.length) {
      const outer = mk('details', 'wfchat-trace'); outer.open = !opened.has('trace-closed');
      outer.ontoggle = () => remember('trace-closed', !outer.open);
      text(outer, 'summary', '执行时间线 · '+list.children.length+' 个节点');
      outer.append(list); host.append(outer);
    }
  }
  async function showTaskReport(id, context, current) {
    const {layer, body} = dialog('分析报告');
    text(body, 'p', '正在读取报告…', 'hint');
    try {
      const response = await fetch('/api/tasks/'+encodeURIComponent(id)+'/report',
        {headers:{'X-Memory-Key':context.key, 'X-Analysis-Mode':context.mode}});
      if (!response.ok) throw Error('无法读取此运行的报告。');
      const html = await response.text();
      if (!layer.open || !current() || context.key !== memoryKey) return;
      const frame = mk('iframe', 'wfchat-report');
      const preview = new DOMParser().parseFromString(html, 'text/html');
      preview.querySelectorAll('script').forEach(script => script.remove());
      frame.title = '本次分析报告'; frame.setAttribute('sandbox','');
      frame.srcdoc = '<!doctype html>' + preview.documentElement.outerHTML;
      const download = button('下载原报告', () => {
        const url = URL.createObjectURL(new Blob([html], {type:'text/html;charset=utf-8'}));
        const link = mk('a'); link.href = url; link.download = 'analysis-'+id+'.html'; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
      body.replaceChildren(frame, download);
    } catch (error) { if (layer.open) body.textContent = error.message; }
  }
  function article(id, readonly) {
    const entry = runState(id, current), task = entry.task, receipt = entry.receipt;
    const currentArticle = articles.get(id) || mk('article', 'wfchat-run');
    articles.set(id, currentArticle);
    const signature = JSON.stringify([task?.status, entry.cursor, entry.error, entry.canceling, readonly, entry.input, receipt?.summary]);
    if (currentArticle.dataset.signature === signature) return currentArticle;
    const opened = new Set(Object.entries(read('trace.' + id) || {}).filter(([, open]) => open).map(([step]) => step));
    for (const node of currentArticle.querySelectorAll('details[data-step][open]')) opened.add(node.dataset.step);
    if (currentArticle.querySelector('.wfchat-trace:not([open])')) opened.add('trace-closed');
    currentArticle.dataset.signature = signature; currentArticle.dataset.run = id;
    currentArticle.replaceChildren();
    const bubble = mk('div', 'wfchat-message');
    text(bubble, 'span', '本轮需求', 'wfchat-meta');
    text(bubble, 'p', entry.input?.message || receipt?.summary || '正在读取历史输入…');
    if (entry.input && Object.keys(entry.input.parameters || {}).length) {
      const params = mk('details');
      text(params, 'summary', '查看发送参数');
      text(params, 'pre', JSON.stringify(entry.input.parameters, null, 2));
      bubble.append(params);
    }
    currentArticle.append(bubble);
    if (entry.error) text(currentArticle, 'p', '读取或操作中断 · ' + entry.error, 'warn');
    if (!task) return currentArticle;
    const version = receipt.version?.slice(0, 10) || '旧版本';
    const progress = mk('div', 'wfchat-execution');
    const head = mk('header', 'wfchat-run-head');
    text(head, 'strong', stateLabel[task.status.state] || task.status.state);
    text(head, 'span', '版本 '+version, 'wfchat-version');
    text(head, 'time', shortTime(receipt.started_at || task.status.timestamp), 'wfchat-meta');
    if (!readonly && !terminal(task.status.state)) {
      const stop = button('取消运行', () => cancel(entry)); stop.disabled = Boolean(entry.canceling); head.append(stop);
    }
    progress.append(head);
    trace(entry, progress, opened);
    if(!readonly)WorkflowNodeUI.humanAction(progress,task,[...entry.events.values()].sort((a,b)=>a.seq-b.seq),
      values=>api('tasks/'+encodeURIComponent(id)+'/continue','POST',values,undefined,scope()));
    const analysis = task.artifacts?.[0]?.parts?.[0]?.data?.analysis;
    if (analysis) {
      const result = mk('div', 'wfchat-result');
      text(result, 'strong', (analysis.prediction?.subject || '分析')+' · '+(analysis.status === 'degraded' ? '报告已生成，分析存在降级' : '报告已生成'));
      result.append(button('打开报告', () => showTaskReport(entry.id, scope(), () => matches(entry.flowId)), 'btn'));
      progress.append(result);
    } else if (task.artifacts?.[0]?.parts?.[0]?.data?.workflow_outputs) {
      for (const output of task.artifacts[0].parts[0].data.workflow_outputs) {
        const result=mk('section','wfchat-output');
        text(result,'strong',output.label);
        text(result,'pre',output.format==='json'?JSON.stringify(output.value,null,2):output.value);
        progress.append(result);
      }
    } else if (task.status.state === 'failed') {
      const error = task.metadata.error;
      text(progress, 'p', error?.message || '执行失败，请查看节点时间线。', 'warn');
    }
    if (terminal(task.status.state)) {
      const actions = mk('div', 'actions wfchat-run-actions');
      actions.append(button('查看执行版本', () => showDefinition({graph:task.metadata.workflow.graph, revision:receipt.version}, true)));
      if (task.metadata.workflow.flow?.id === flow()?.id) actions.append(button('在画布查看本次运行',()=>{
        const item=flow();
        if(enterCanvas(item))window.DesktopWorkbench?.openRecordedRun(item.id,task.id);
      }));
      if (!readonly && entry.input && task.metadata.workflow.flow && ['failed','canceled'].includes(task.status.state)) {
        actions.append(button('重试此版本', () => send(entry)));
      }
      progress.append(actions);
    }
    currentArticle.append(progress);
    return currentArticle;
  }
  function renderThread({forceBottom = false, restore = false} = {}) {
    const thread = el('thread'), data = state();
    const atEnd = thread.scrollHeight - thread.clientHeight - thread.scrollTop < 48;
    const scroll = thread.scrollTop;
    const ids = data.viewing ? [data.viewing] : data.ids;
    const host = el('messages');
    if (!ids.length) {
      const blank = mk('div', 'wfchat-empty');
      text(blank, 'span', '↳', 'wfchat-empty-mark').setAttribute('aria-hidden', 'true');
      text(blank, 'h2', flow() ? '这个流程需要完成什么？' : '从选择流程开始');
      text(blank, 'p', flow() ? '输入需求并补充参数，节点进度会出现在这里。' : '选择本轮使用的流程，再输入分析需求。', 'hint');
      if (!flow()) blank.append(button('选择流程', choose, 'btn primary'));
      host.replaceChildren(blank);
    } else {
      const incoming = ids.map(id => article(id, Boolean(data.viewing)));
      if (host.children.length !== incoming.length || incoming.some((node,index) => node !== host.children[index])) host.replaceChildren(...incoming);
    }
    if (restore && !data.viewing && Number.isFinite(data.scroll)) thread.scrollTop = data.scroll;
    else if (forceBottom || (!data.viewing && atEnd && !restore)) thread.scrollTop = thread.scrollHeight;
    else thread.scrollTop = restore ? (data.viewing ? 0 : thread.scrollHeight) : scroll;
  }
  function renderHistory() {
    const data = state(), host = el('history'), ids = [...new Set([...data.ids.slice().reverse(), ...data.history])];
    const recordedAt = id => runs.get(id)?.receipt?.started_at || runs.get(id)?.receipt?.status.timestamp || '';
    ids.sort((a,b) => recordedAt(b).localeCompare(recordedAt(a)));
    host.replaceChildren();
    if (!flow() || !ids.length) text(host, 'p', data.historyError || (flow() ? '此流程暂无运行。' : '选择流程后查看运行。'), 'hint');
    for (const id of ids) {
      const entry = runs.get(id), item = entry?.receipt;
      if (!item) continue;
      const row = button('', () => {
        stopSpeech();
        if (!data.viewing) data.scroll = el('thread').scrollTop;
        data.viewing = id; persist(); renderThread({restore:true}); renderFeedback(); renderHistory();
        loadRun(id, current); schedule();
      }, 'wfchat-history-row');
      row.dataset.run = id; row.setAttribute('aria-pressed', String(id === data.viewing));
      text(row, 'strong', item.summary);
      text(row, 'span', [stateLabel[item.status.state], shortTime(item.started_at || item.status.timestamp), item.version?.slice(0,8), duration(item.duration_ms)]
        .filter(Boolean).join(' · '), 'hint');
      host.append(row);
    }
    if (ids.length && data.historyError) text(host,'p',data.historyError,'warn');
    el('more').hidden = !data.cursor;
  }
  function render() { renderHeader(); renderForm(); renderThread({restore:true}); renderHistory(); }

  async function openTask(task) {
    const id = task.metadata.workflow.flow.id;
    window.DesktopWorkbench.setMode('focus');
    showView('analysis');
    setSurface('chat');
    const context = scope();
    await loadCatalog();
    if (!AnalysisMode.current(context) || !active() || !flows.has(id)) return;
    accept(receiptOf(task), id);
    state(id).viewing = task.id; select(id);
    await loadRun(task.id, id);
  }
  async function openDefinition(id) {
    setSurface('chat');
    await loadCatalog();
    if(active() && flows.has(id))select(id);
  }

  async function saveCanvas(snapshot, {direct = false} = {}) {
    const context = scope(), editing = snapshot.definition?.mode === 'custom' ? snapshot.definition : null;
    const selectedAtSave = current;
    async function save(values, error) {
      try {
        const saved = await api(editing ? path(editing.id) : endpoint, editing ? 'PUT' : 'POST',
          {...values, graph:snapshot.graph, draft:true, draft_edits:snapshot.edits, ...choices(),
            ...(editing ? {base_revision:editing.revision} : {})}, undefined, context);
        if (context.key !== memoryKey) return false;
        window.DesktopWorkbench.savedDefinition(saved,snapshot);
        flows.set(saved.id, {...saved, runnable:!saved.draft});
        await loadCatalog();
        if (AnalysisMode.current(context) && current === selectedAtSave) { write('selected', saved.id); current = saved.id; }
        showDirectory();
        return true;
      } catch (failure) {
        if (context.key === memoryKey) error(failure);
        return false;
      }
    }
    if (direct && editing) {
      const ok = await save({name:editing.name, description:editing.description, inputs:editing.inputs},
        failure => { if (AnalysisMode.current(context)) {
          notice(failure.message, true);
          if(window.DesktopWorkbench.canvasSnapshot().source===snapshot.source)window.DesktopWorkbench.explainError(failure);
        } });
      if (ok) showDirectory();
      return;
    }
    await loadCatalog();
    if (AnalysisMode.active() !== mode || context.key !== memoryKey) return;
    const {layer, body} = dialog(editing ? '流程名称与卡片' : '保存流程');
    const form = mk('form', 'stack');
    form.innerHTML = '<label class="field"><span>流程名称</span><input name="name" maxlength="80" required></label>'+
      '<label class="field"><span>描述</span><textarea name="description" maxlength="400" rows="2"></textarea></label>'+
      '<label class="field"><span>流程图像 · PNG、JPEG 或 WebP，最大 512 KiB</span><input name="image" type="file" accept="image/png,image/jpeg,image/webp"></label>'+
      '<div class="wfcat-image wfcat-image-preview" data-image-preview></div><button type="button" class="btn tiny" data-image-reset>恢复默认图标</button>'+
      '<fieldset class="stack"><legend>开始节点的输入参数</legend></fieldset><p class="warn" role="alert"></p>'+
      '<button type="submit" class="btn primary">保存流程版本</button>';
    form.elements.name.value = editing?.name || '';
    form.elements.description.value = editing?.description || '';
    let selectedImage = editing?.image || null, resetImage = false;
    const preview = form.querySelector('[data-image-preview]');
    const showImage = image => {
      preview.replaceChildren(); preview.classList.toggle('wfcat-default-image', !image);
      if (image) { const img = document.createElement('img'); img.src = 'data:' + image.mime + ';base64,' + image.data; img.alt = '流程图像'; preview.append(img); }
    };
    showImage(selectedImage);
    form.elements.image.onchange = async () => {
      const file = form.elements.image.files?.[0]; if (!file) return;
      if (file.size > 512 * 1024 || !['image/png','image/jpeg','image/webp'].includes(file.type)) {
        form.querySelector('[role="alert"]').textContent = '请选择不超过 512 KiB 的 PNG、JPEG 或 WebP 图像。'; form.elements.image.value = ''; return;
      }
      const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(file); });
      selectedImage = {mime:file.type, data}; resetImage = false; showImage(selectedImage);
    };
    form.querySelector('[data-image-reset]').onclick = () => { selectedImage = null; resetImage = true; form.elements.image.value = ''; showImage(null); };
    const custom=WorkflowNodeUI.isVariable(snapshot.graph);
    const defaultFields = editing?.inputs || flows.get('system')?.inputs || {prediction:true};
    form.querySelector('fieldset').hidden=custom;
    for (const [key, field] of custom?[]:Object.entries(fields)) {
      const label = mk('label', 'field wfchat-definition-field');
      text(label, 'span', field.label);
      const select = mk('select'); select.name = 'field-' + key;
      select.append(new Option('不使用', ''), new Option('选填', 'optional'), new Option('必填', 'required'));
      select.value = defaultFields[key] ? 'required' : key in defaultFields ? 'optional' : '';
      select.disabled = key === 'prediction';
      label.append(select); form.querySelector('fieldset').append(label);
    }
    form.onsubmit = async event => {
      event.preventDefault(); const submit = form.querySelector('[type="submit"]'); submit.disabled = true;
      const inputs = {prediction:true};
      for (const select of form.querySelectorAll('select')) if (select.value) inputs[select.name.slice(6)] = select.value === 'required';
      const values = {name:form.elements.name.value, description:form.elements.description.value, inputs};
      if (selectedImage || resetImage) values.image = selectedImage;
      form.querySelector('[data-locate-node]')?.remove();
      const ok = await save(values,
        failure => {
          form.querySelector('[role="alert"]').textContent = failure.message;
          if(!snapshot.graph.nodes.some(node=>failure.message.split(' · ').includes(node.id)))return;
          const locate=mk('button','btn tiny','定位节点配置');locate.type='button';locate.dataset.locateNode='';
          locate.onclick=()=>{
            layer.close();
            if(AnalysisMode.current(context) && window.DesktopWorkbench.canvasSnapshot().source===snapshot.source)
              window.DesktopWorkbench.explainError(failure);
          };
          submit.before(locate);
        });
      if (ok) layer.close();
      submit.disabled = false;
    };
    body.append(form); form.elements.name.focus();
  }
  function init() {
    root = mk('section', 'workflow-chat');
    root.id = 'workflow-chat'; root.hidden = true;
    root.setAttribute('aria-label','流程对话');
    root.innerHTML = `
      <header class="wfchat-header"><h1 id="workflow-chat-title" hidden></h1>
        <div class="actions"><button type="button" class="btn tiny" id="workflow-chat-live" hidden>返回当前会话</button>
        <button type="button" class="btn tiny" id="workflow-chat-canvas">流程画布</button></div></header>
      <div class="wfchat-main"><section id="workflow-chat-thread" class="wfchat-thread" aria-label="流程对话记录" tabindex="0"><div id="workflow-chat-messages"></div></section>
        <form id="workflow-chat-form" class="wfchat-form">
          <textarea id="workflow-chat-message" rows="2" maxlength="4000" aria-label="本轮需求" placeholder="输入本轮分析需求…" required></textarea>
          <div class="wfchat-toolbar"><div class="composer-tools-left">
            <details id="workflow-chat-inputs" class="wfchat-inputs"><summary id="workflow-chat-parameter-toggle" class="composer-tool" aria-label="补充流程参数" title="补充流程参数">${ComposerControls.icon('plus')}<span></span></summary>
              <div class="wfchat-input-panel"><div class="actions"><button type="button" class="btn tiny" id="workflow-chat-fill">带入分析资料</button></div>
                <div id="workflow-chat-parameters"></div>
                <label class="field"><span>本轮资料库</span><select id="workflow-chat-knowledge"><option value="local">本机资料</option><option value="private">旧版私有资料</option></select></label>
              </div>
            </details><button type="button" class="composer-tool" id="workflow-chat-choose">选择流程</button></div>
            <div class="composer-tools-right"></div></div>
          <div class="wfchat-send-row"><p id="workflow-chat-feedback" role="status" class="hint"></p><button type="button" class="btn tiny" id="workflow-chat-edit" hidden>打开流程</button>
            <button type="button" class="btn tiny" id="workflow-chat-resume" hidden>恢复提交</button></div>
        </form></div>
      <aside class="wfchat-aside">
        <details id="workflow-chat-aside" open><summary>流程与运行历史</summary><div class="wfchat-aside-content">
          <section><h2>当前流程</h2><div id="workflow-chat-definition"></div></section>
          <section><h2>运行历史</h2><div id="workflow-chat-history"></div>
            <button type="button" class="btn tiny" id="workflow-chat-more" hidden>加载更早的运行</button></section>
        </div></details>
      </aside>`;
    const controls = root.querySelector('.composer-tools-right');
    const voice = ComposerControls.button('workflow-chat-voice', '语音输入', ComposerControls.icon('mic'));
    const submit = mk('button', 'composer-send');
    submit.id = 'workflow-chat-send'; submit.type = 'submit'; submit.title = '发送并运行';
    submit.setAttribute('aria-label', submit.title); submit.innerHTML = ComposerControls.icon('arrow');
    controls.append(voice, submit);
    stopSpeech = ComposerControls.speechInput(voice, el('message'), () => {
      const id = current, context = scope();
      return () => matches(id) && AnalysisMode.current(context) && !state(id).viewing;
    }, error => { state().error = error; renderFeedback(); });
    document.querySelector('[data-view-pane="analysis"]').prepend(root);
    directoryRoot = mk('section', 'workflow-catalog');
    directoryRoot.hidden = true;
    directoryRoot.setAttribute('aria-label', '流程目录');
    directoryRoot.innerHTML = '<main class="wfcat-main"><p class="wfcat-status hint" role="status"></p><div class="wfcat-grid"></div></main>';
    document.querySelector('[data-view-pane="analysis"]').prepend(directoryRoot);
    shortcut = button('流程对话', () => setSurface('chat'), 'wfchat-nav');
    shortcut.id = 'workflow-chat-nav';
    canvasShortcut = button('画布', showDirectory, 'wfchat-nav');
    canvasShortcut.id = 'workflow-canvas-nav';
    document.querySelector('.nav')?.append(shortcut, canvasShortcut);
    el('choose').onclick = choose;
    el('canvas').onclick = () => enterCanvas(flow(), {empty:!flow()});
    el('edit').onclick = () => enterCanvas(flow());
    el('resume').onclick = () => send();
    el('more').onclick = () => loadHistory(current, true);
    el('live').onclick = () => { state().viewing = ''; persist(); renderThread({restore:true}); renderFeedback(); renderHistory(); schedule(0); };
    el('message').oninput = () => { state().draft.message = el('message').value; persist(); };
    el('form').onsubmit = event => { event.preventDefault(); send(); };
    el('inputs').ontoggle = () => {
      if (active() && current) { state().draft.inputsOpen = el('inputs').open; persist(); }
    };
    el('knowledge').onchange = () => { state().draft.knowledge = el('knowledge').value; persist(); };
    el('fill').onclick = () => {
      try { applyParameters(JSON.parse($('task-data').value)); }
      catch (_) { state().error = '请先在分析资料中准备可用的预测数据。'; renderFeedback(); }
    };
    el('thread').onscroll = () => { if (active() && !state().viewing) state().scroll = el('thread').scrollTop; };
    const narrow = matchMedia('(max-width: 780px)');
    const layout = () => { el('aside').open = !narrow.matches || Boolean(read('narrow-panel')); };
    narrow.addEventListener('change', layout); layout();
    el('aside').ontoggle = () => { if (narrow.matches) write('narrow-panel',el('aside').open); };
    new MutationObserver(syncView).observe(document.body, {attributes:true, attributeFilter:['data-view','class']});
    document.addEventListener('visibilitychange', () => { if (active() && !document.hidden) schedule(0); });
    window.addEventListener('online', () => { if (active()) { schedule(0); loadHistory(current); } });
    window.addEventListener('pagehide', () => { if (active()) persist(); });
    syncView();
  }
  return {init, syncView, saveCanvas, openTask, openDefinition, showTaskReport, showCanvas:() => {setSurface('canvas');window.DesktopWorkbench?.checkWorkflow();}, showDirectory};
})();
