/* Unified tools center for MCP services, workflows, plugins and local custom tools. */
globalThis.ToolsCenter = (() => {
  const CUSTOM_KEY = 'stock_predict_mailer.tools.center.v1';
  const METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head'];
  const TABS = {all: '工具', custom: '自定义', workflow: '工作流', mcp: 'MCP', plugin: '插件'};
  const state = {mcp: [], plugins: [], catalog: null, settings: null, custom: [], errors: {}, loaded: false};
  let root = null;
  let loading = null;
  let activeTab = 'all';
  let activeDialog = null;
  let returnFocus = null;

  const node = (tag, className, value) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;
    return element;
  };
  const append = (parent, ...children) => parent.append(...children.filter(Boolean));
  const readCustom = () => {
    try {
      const value = JSON.parse(localStorage.getItem(CUSTOM_KEY) || '[]');
      return Array.isArray(value) ? value.filter(item => item && typeof item.id === 'string' && typeof item.name === 'string') : [];
    } catch (_) { return []; }
  };
  const writeCustom = () => {
    try {
      localStorage.setItem(CUSTOM_KEY, JSON.stringify(state.custom));
      return true;
    } catch (_) {
      return false;
    }
  };
  const safeText = value => typeof value === 'string' ? value.trim() : '';
  const shortId = value => value ? value.slice(0, 10) : '—';

  function field(label, control, hint) {
    const wrapper = node('label', 'tools-field');
    append(wrapper, node('span', 'tools-field-label', label), control);
    if (hint) append(wrapper, node('small', 'tools-field-hint', hint));
    return wrapper;
  }

  function input(type, placeholder, value = '') {
    const element = node('input', 'tools-input');
    element.type = type;
    element.placeholder = placeholder || '';
    element.value = value;
    return element;
  }

  function dialogShell(title, subtitle, kind) {
    const dialog = document.createElement('dialog');
    dialog.className = `tools-dialog tools-dialog-${kind}`;
    dialog.setAttribute('aria-labelledby', `tools-dialog-title-${kind}`);
    const header = node('header', 'tools-dialog-head');
    const copy = node('div');
    append(copy, node('p', 'tools-kicker', '工具中心'), node('h2', '', title), node('p', 'tools-dialog-subtitle', subtitle));
    const close = node('button', 'tools-dialog-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', '关闭');
    close.onclick = () => dialog.close();
    header.querySelector('h2').id = `tools-dialog-title-${kind}`;
    append(header, copy, close);
    dialog.append(header);
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => {
      dialog.remove();
      if (activeDialog === dialog) activeDialog = null;
      if (returnFocus?.getClientRects().length) returnFocus.focus({preventScroll: true});
      returnFocus = null;
    }, {once: true});
    document.body.append(dialog);
    activeDialog = dialog;
    dialog.showModal();
    return dialog;
  }

  function dialogFooter(dialog, submitText, status) {
    const footer = node('footer', 'tools-dialog-foot');
    const cancel = node('button', 'tools-secondary-button', '取消');
    cancel.type = 'button';
    cancel.onclick = () => dialog.close();
    const submit = node('button', 'tools-primary-button', submitText);
    submit.type = 'submit';
    append(footer, status, node('span', 'tools-dialog-foot-spacer'), cancel, submit);
    return {footer, submit};
  }

  function statusLine(className = '') {
    return node('p', `tools-dialog-status ${className}`.trim());
  }

  function tabs(items, onChange) {
    const wrapper = node('div', 'tools-modal-tabs');
    const panes = new Map();
    for (const [id, label] of items) {
      const button = node('button', '', label);
      button.type = 'button';
      button.dataset.toolsModalTab = id;
      button.setAttribute('aria-controls', `tools-modal-pane-${id}`);
      button.onclick = () => {
        wrapper.querySelectorAll('button').forEach(item => item.setAttribute('aria-selected', String(item === button)));
        panes.forEach((pane, key) => { pane.hidden = key !== id; });
        onChange?.(id);
      };
      wrapper.append(button);
      const pane = node('section', 'tools-modal-pane');
      pane.id = `tools-modal-pane-${id}`;
      pane.setAttribute('aria-labelledby', `tools-modal-tab-${id}`);
      button.id = `tools-modal-tab-${id}`;
      panes.set(id, pane);
    }
    wrapper.querySelector('button').setAttribute('aria-selected', 'true');
    for (const pane of panes.values()) pane.hidden = true;
    panes.get(items[0][0]).hidden = false;
    return {wrapper, panes};
  }

  function buildMcpDialog(existing = null) {
    const dialog = dialogShell(existing ? '编辑 MCP 服务' : '添加 MCP 服务请求', existing ? '更新连接信息，工具白名单会保留在当前服务配置中。' : '连接一个 HTTP MCP 服务，并在工具中心继续管理授权。', 'mcp');
    const form = node('form', 'tools-dialog-form');
    form.noValidate = true;
    const endpoint = input('url', 'https://example.com/mcp', existing?.url || '');
    endpoint.required = existing?.transport !== 'stdio';
    const name = input('text', '例如：股票数据服务', existing?.name || '');
    name.required = true;
    const icon = node('select', 'tools-input');
    [['spark', '✦ 星标'], ['chart', '◒ 图表'], ['database', '▦ 数据'], ['globe', '◎ 网络']].forEach(([value, label]) => icon.add(new Option(label, value)));
    const identifier = input('text', '例如：my-mcp-server');
    identifier.pattern = '[A-Za-z0-9_-]{1,64}';
    const base = node('section', 'tools-form-section');
    append(base, node('h3', '', '基础信息'), field('服务端点 URL', endpoint, '只支持 MCP Streamable HTTP 服务。'), field('名称和图标', (() => { const row = node('div', 'tools-inline-fields'); append(row, name, icon); return row; })()), field('服务器标识符', identifier, '用于在工作区内识别服务，当前不会覆盖后端生成的配置 ID。'));

    const auth = node('section', 'tools-form-section');
    const authToken = input('password', 'Bearer token，可留空');
    authToken.autocomplete = 'new-password';
    const dynamic = node('input');
    dynamic.type = 'checkbox';
    const clientId = input('text', '客户端 ID');
    const clientSecret = input('password', '客户端密钥');
    clientSecret.autocomplete = 'new-password';
    const authFields = node('div', 'tools-stack');
    append(authFields, field('Bearer token', authToken, '保存后不会回显。'), field('动态客户端注册', (() => { const row = node('label', 'tools-switch'); append(row, dynamic, node('span', '', '启用动态客户端注册')); return row; })()), field('客户端 ID', clientId), field('客户端密钥', clientSecret));
    append(auth, node('h3', '', '认证'), authFields, node('p', 'tools-field-hint tools-form-note', '当前后端只持久化 Bearer token。客户端注册字段用于本次请求配置预览。'));

    const request = node('section', 'tools-form-section');
    const headerRows = node('div', 'tools-repeat-list');
    const addHeader = node('button', 'tools-outline-button', '＋ 添加请求头');
    addHeader.type = 'button';
    const addHeaderRow = () => {
      const row = node('div', 'tools-repeat-row');
      const key = input('text', 'Header 名称');
      const value = input('password', 'Header 值');
      value.autocomplete = 'new-password';
      const remove = node('button', 'tools-icon-button', '×');
      remove.type = 'button'; remove.setAttribute('aria-label', '移除请求头'); remove.onclick = () => row.remove();
      append(row, key, value, remove); headerRows.append(row); key.focus();
    };
    addHeader.onclick = addHeaderRow;
    const timeout = input('number', '30', String(existing?.timeout_seconds || 30)); timeout.min = '1'; timeout.max = '120';
    const sseTimeout = input('number', '300', '300'); sseTimeout.min = '1'; sseTimeout.max = '600';
    append(request, node('h3', '', '请求头与配置'), node('p', 'tools-field-hint', '请求头只保留在本次表单中，后端当前没有通用请求头字段。'), headerRows, addHeader, field('连接超时（秒）', timeout), field('SSE 读取超时（秒）', sseTimeout));

    const {wrapper: tabBar, panes} = tabs([['auth', '认证'], ['headers', '请求头'], ['config', '配置']], id => {
      panes.get('auth').hidden = id !== 'auth'; panes.get('headers').hidden = id !== 'headers'; panes.get('config').hidden = id !== 'config';
    });
    append(panes.get('auth'), auth);
    append(panes.get('headers'), request);
    const configCopy = node('div', 'tools-config-summary');
    append(configCopy, node('strong', '', '连接参数'), node('p', '', '超时设置会随 MCP 服务保存。SSE 读取超时作为本次请求的辅助配置。'));
    append(panes.get('config'), configCopy, field('连接超时（秒）', timeout), field('SSE 读取超时（秒）', sseTimeout));
    const mcpStatus = statusLine();
    const footer = dialogFooter(dialog, existing ? '保存更改' : '添加并授权', mcpStatus);
    append(form, base, tabBar, footer.footer);
    dialog.append(form);
    dialog.querySelector('[data-tools-modal-tab="auth"]').focus();

    form.addEventListener('submit', async event => {
      event.preventDefault();
      mcpStatus.textContent = '';
      if (!endpoint.checkValidity() || !name.checkValidity()) { mcpStatus.textContent = '请填写服务端点 URL 和名称。'; return; }
      footer.submit.disabled = true;
      mcpStatus.textContent = '正在保存 MCP 服务…';
      const body = existing ? {...existing, name: safeText(name.value), url: endpoint.value.trim(), timeout_seconds: Number(timeout.value) || 30} : {name: safeText(name.value), transport: 'streamable_http', url: endpoint.value.trim(), timeout_seconds: Number(timeout.value) || 30, allowed_tools: [], allowed_resources: [], effects: {}};
      for (const key of ['id', 'has_secret', 'secret_mask', 'env_keys']) delete body[key];
      if (authToken.value) body.auth_token = authToken.value;
      try {
        await api(`mcp${existing ? '/' + existing.id : ''}`, existing ? 'PUT' : 'POST', body);
        authToken.value = ''; clientSecret.value = '';
        mcpStatus.textContent = existing ? 'MCP 服务已更新。' : 'MCP 服务已添加。请在工具中心测试连接并授权工具。';
        await window.refreshConsole?.();
        await load(true);
        setTimeout(() => dialog.close(), 500);
      } catch (error) {
        mcpStatus.textContent = `保存失败。${error.message}`;
      } finally { footer.submit.disabled = false; }
    });
    return dialog;
  }

  const exampleSchema = {
    openapi: '3.0.0', info: {title: '天气查询', version: '1.0.0'}, paths: {
      '/weather': {get: {operationId: 'getWeather', summary: '查询城市天气', parameters: [{name: 'city', in: 'query', required: true}]}}
    }
  };

  function parseSchema(raw) {
    let value;
    try { value = JSON.parse(raw); } catch (_) { throw new Error('Schema 不是有效的 JSON。'); }
    if (!value || typeof value !== 'object' || (!value.openapi && !value.swagger)) throw new Error('Schema 需要包含 openapi 或 swagger 版本字段。');
    if (!value.paths || typeof value.paths !== 'object') throw new Error('Schema 缺少 paths 对象。');
    const tools = [];
    for (const [path, methods] of Object.entries(value.paths)) {
      if (!methods || typeof methods !== 'object') continue;
      for (const method of METHODS) {
        const operation = methods[method];
        if (!operation || typeof operation !== 'object') continue;
        const parameters = Array.isArray(operation.parameters) ? operation.parameters : [];
        tools.push({name: safeText(operation.operationId) || `${method.toUpperCase()} ${path}`, description: safeText(operation.summary || operation.description) || '未提供描述', method: method.toUpperCase(), path, parameters: parameters.filter(item => item && typeof item.name === 'string').slice(0, 20).map(item => item.name)});
      }
    }
    if (!tools.length) throw new Error('Schema 中没有可用的 HTTP 操作。');
    return {title: safeText(value.info?.title) || '自定义工具', version: safeText(value.info?.version) || safeText(value.info?.['x-version']) || '—', tools: tools.slice(0, 50)};
  }

  function buildCustomDialog(existing = null) {
    const dialog = dialogShell(existing ? '编辑自定义工具' : '创建自定义工具', '粘贴 OpenAPI 或 Swagger Schema，将接口整理成可复用工具。', 'custom');
    const form = node('form', 'tools-dialog-form'); form.noValidate = true;
    const name = input('text', '例如：公司天气服务', existing?.name || ''); name.required = true;
    const icon = node('select', 'tools-input'); [['spark', '✦ 星标'], ['chart', '◒ 图表'], ['database', '▦ 数据'], ['globe', '◎ 网络']].forEach(([value, label]) => icon.add(new Option(label, value))); icon.value = existing?.icon || 'spark';
    const schema = node('textarea', 'tools-schema-editor'); schema.rows = 11; schema.spellcheck = false; schema.placeholder = '在此处输入 OpenAPI Schema'; schema.value = existing?.schemaDraft || '';
    const example = node('select', 'tools-input'); example.add(new Option('选择示例', '')); example.add(new Option('天气查询', 'weather')); example.add(new Option('当前时间', 'time'));
    const importUrl = input('url', '仅支持同源 Schema 地址');
    const importButton = node('button', 'tools-outline-button', '从 URL 导入'); importButton.type = 'button';
    const schemaStatus = statusLine('tools-schema-status');
    const preview = node('div', 'tools-schema-preview');
    const auth = node('select', 'tools-input'); [['none', '无'], ['bearer', 'Bearer Token'], ['apiKey', 'API Key']].forEach(([value, label]) => auth.add(new Option(label, value))); auth.value = existing?.auth || 'none';
    const tags = input('text', '例如：搜索, 数据', existing?.tags?.join(', ') || '');
    const privacy = input('url', '隐私协议地址（可选）', existing?.privacy || '');
    const disclaimer = input('text', '例如：仅用于内部数据查询', existing?.disclaimer || '');
    const basic = node('section', 'tools-form-section');
    const nameRow = node('div', 'tools-inline-fields'); append(nameRow, name, icon);
    append(basic, node('h3', '', '基本信息'), field('名称和图标', nameRow), field('Schema', schema, '仅保存解析后的工具摘要，不保存原始 Schema。'));
    const importRow = node('div', 'tools-inline-fields'); append(importRow, importUrl, importButton); append(basic, field('从 URL 导入', importRow));
    const exampleRow = node('div', 'tools-inline-fields'); const fillExample = node('button', 'tools-outline-button', '填入示例'); fillExample.type = 'button'; append(exampleRow, example, fillExample); append(basic, field('快速开始', exampleRow));
    const details = node('section', 'tools-form-section');
    append(details, node('h3', '', '工具预览'), preview, node('p', 'tools-field-hint', '解析结果只展示名称、描述、方法和路径。保存后可在工具中心加入工作流。'));
    const policy = node('section', 'tools-form-section');
    append(policy, node('h3', '', '权限和说明'), field('鉴权方式', auth), field('标签', tags), field('隐私协议', privacy), field('自定义免责声明', disclaimer));
    const customStatus = statusLine();
    const footer = dialogFooter(dialog, existing ? '保存修改' : '保存工具', customStatus);
    append(form, basic, details, policy, footer.footer); dialog.append(form);

    let parsed = existing?.tools?.length ? {title: existing.schemaTitle || existing.name, version: existing.schemaVersion || '—', tools: existing.tools} : null;
    const renderPreview = () => {
      preview.replaceChildren();
      if (!parsed) { preview.append(node('p', 'tools-preview-empty', '输入 Schema 后会在这里显示可用工具。')); return; }
      const summary = node('div', 'tools-preview-summary'); append(summary, node('strong', '', `${parsed.title} · v${parsed.version}`), node('span', '', `${parsed.tools.length} 个可用工具`)); preview.append(summary);
      const table = node('div', 'tools-preview-table');
      for (const tool of parsed.tools) { const row = node('div', 'tools-preview-row'); append(row, node('strong', '', tool.name), node('span', '', tool.description), node('code', '', `${tool.method} ${tool.path}`)); table.append(row); }
      preview.append(table);
    };
    const parse = () => {
      try { parsed = parseSchema(schema.value); schemaStatus.textContent = `已解析 ${parsed.tools.length} 个工具。`; schemaStatus.dataset.state = 'ok'; }
      catch (error) { parsed = null; schemaStatus.textContent = error.message; schemaStatus.dataset.state = 'error'; }
      renderPreview();
    };
    schema.addEventListener('input', parse);
    fillExample.onclick = () => { schema.value = JSON.stringify(exampleSchema, null, 2); example.value = 'weather'; parse(); };
    example.onchange = () => { if (example.value === 'weather') { schema.value = JSON.stringify(exampleSchema, null, 2); parse(); } };
    importButton.onclick = async () => {
      const url = importUrl.value.trim(); if (!url) return;
      try {
        const parsedUrl = new URL(url, location.href);
        if (parsedUrl.origin !== location.origin) throw new Error('跨域地址无法由浏览器直接读取，请粘贴 Schema 内容。');
        importButton.disabled = true; schemaStatus.textContent = '正在导入 Schema…';
        const response = await fetch(parsedUrl.href, {credentials: 'same-origin'});
        if (!response.ok) throw new Error(`导入失败（HTTP ${response.status}）。`);
        schema.value = await response.text(); parse();
      } catch (error) { schemaStatus.textContent = error.message; schemaStatus.dataset.state = 'error'; }
      finally { importButton.disabled = false; }
    };
    if (existing?.schemaDraft) parse(); else renderPreview();
    form.addEventListener('submit', event => {
      event.preventDefault(); customStatus.textContent = '';
      if (!name.checkValidity()) { customStatus.textContent = '请填写工具名称。'; return; }
      if (!parsed) { customStatus.textContent = '请先输入有效的 OpenAPI 或 Swagger Schema。'; return; }
      const record = {id: existing?.id || `custom-${crypto.randomUUID()}`, name: safeText(name.value), icon: icon.value, schemaTitle: parsed.title, schemaVersion: parsed.version, tools: parsed.tools, tags: lines(tags.value.replace(/,/g, '\n')), auth: auth.value, privacy: safeText(privacy.value), disclaimer: safeText(disclaimer.value), createdAt: existing?.createdAt || new Date().toISOString()};
      const prior = state.custom.findIndex(item => item.id === record.id);
      if (prior >= 0) state.custom.splice(prior, 1, record); else state.custom.unshift(record);
      if (!writeCustom()) { customStatus.textContent = '浏览器存储不可用，工具只会保留到本次打开。'; }
      render();
      customStatus.textContent = '自定义工具已保存。';
      setTimeout(() => dialog.close(), 500);
    });
    return dialog;
  }

  function buildPluginDialog() {
    const dialog = dialogShell('添加插件', '从 GitHub 安装声明式插件，安装前请确认仓库来源可信。', 'plugin');
    const form = node('form', 'tools-dialog-form'); form.noValidate = true;
    const url = input('url', 'https://github.com/owner/repo'); url.required = true;
    const status = statusLine();
    const help = node('div', 'tools-plugin-help'); append(help, node('strong', '', '安装要求'), node('p', '', '仓库默认分支根目录需要包含 stock-predict-mailer-plugin.json。当前后端支持 exporter 类型插件。'));
    const footer = dialogFooter(dialog, '添加插件', status);
    append(form, field('GitHub 仓库地址', url), help, footer.footer); dialog.append(form);
    form.addEventListener('submit', async event => {
      event.preventDefault(); status.textContent = '';
      if (!url.checkValidity()) { status.textContent = '请输入有效的 GitHub 仓库地址。'; return; }
      footer.submit.disabled = true; status.textContent = '正在从 GitHub 获取插件…';
      try { await api('plugins/github', 'POST', {url: url.value.trim()}); await load(true); status.textContent = '插件已添加。'; setTimeout(() => dialog.close(), 500); }
      catch (error) { status.textContent = `添加失败。${error.message}`; }
      finally { footer.submit.disabled = false; }
    });
    return dialog;
  }

  function open(kind, existing) {
    if (activeDialog) activeDialog.close();
    returnFocus = document.activeElement;
    return kind === 'mcp' ? buildMcpDialog(existing) : kind === 'custom' ? buildCustomDialog(existing) : buildPluginDialog();
  }

  async function inspectMcp(item) {
    try {
      const data = await api(`mcp/${item.id}/test`, 'POST', {});
      const dialog = dialogShell(`${item.name} · 工具发现`, '发现结果展示服务能力，授权配置可从编辑入口继续管理。', 'mcp-discovery');
      const body = node('div', 'tools-discovery-body');
      append(body, node('p', 'tools-field-hint', `协议 ${data.protocol_version || '未知'} · ${data.tools.length} 个工具 · ${data.resources.length} 个资源`));
      const list = node('div', 'tools-discovery-list');
      for (const tool of data.tools) {
        const row = node('div', 'tools-discovery-row');
        append(row, node('strong', '', tool.name), node('span', '', item.allowed_tools.includes(tool.name) ? '已授权' : '待授权'));
        list.append(row);
      }
      for (const resource of data.resources) list.append(node('div', 'tools-discovery-row', `资源 · ${resource.name} · ${resource.uri}`));
      append(body, list);
      const close = node('button', 'tools-secondary-button', '关闭'); close.type = 'button'; close.onclick = () => dialog.close();
      const manage = node('button', 'tools-primary-button', '编辑授权'); manage.type = 'button'; manage.onclick = () => { dialog.close(); open('mcp', item); };
      const footer = node('footer', 'tools-dialog-foot'); append(footer, node('span', 'tools-dialog-foot-spacer'), close, manage);
      dialog.append(body, footer);
    } catch (error) { root.querySelector('#tools-status').textContent = `MCP 测试失败。${error.message}`; }
  }

  async function toggleMcp(item) {
    try { await api(`mcp/${item.id}`, 'PUT', {...item, enabled: !item.enabled}); await window.refreshConsole?.(); await load(true); }
    catch (error) { root.querySelector('#tools-status').textContent = `更新失败。${error.message}`; }
  }

  async function removeMcp(item) {
    if (!confirm(`删除 MCP 服务“${item.name}”？被工作流或邮件引用的服务需要先解除引用。`)) return;
    try { await api(`mcp/${item.id}`, 'DELETE'); await window.refreshConsole?.(); await load(true); }
    catch (error) { root.querySelector('#tools-status').textContent = `删除失败。${error.message}`; }
  }

  function editableSchema(record) {
    const paths = {};
    for (const tool of record.tools || []) {
      const method = String(tool.method || 'GET').toLowerCase();
      const path = tool.path || '/tool';
      paths[path] ||= {};
      paths[path][method] = {operationId: tool.name, summary: tool.description, parameters: (tool.parameters || []).map(name => ({name, in: 'query'}))};
    }
    return JSON.stringify({openapi: '3.0.0', info: {title: record.schemaTitle || record.name, version: record.schemaVersion || '1.0.0'}, paths}, null, 2);
  }

  function records() {
    const result = [];
    for (const item of state.mcp) result.push({type: 'mcp', id: item.id, label: item.name, description: item.transport === 'stdio' ? '本地 stdio 服务' : item.url, tags: ['MCP', item.enabled ? '已启用' : '已停用'], status: item.enabled ? '已连接' : '已停用', data: item});
    for (const item of state.custom) result.push({type: 'custom', id: item.id, label: item.name, description: `${item.tools.length} 个 OpenAPI 工具 · ${item.schemaTitle}`, tags: ['自定义', ...(item.tags || [])], status: '本地工具', data: item});
    for (const item of state.plugins) result.push({type: 'plugin', id: item.id, label: item.label, description: item.capabilities?.join(' · ') || '插件能力', tags: ['插件', item.kind || '扩展'], status: item.available ? '可用' : '缺依赖', data: item});
    const options = state.catalog?.nodes?.tool?.options || {};
    for (const [id, item] of Object.entries(options)) result.push({type: 'workflow', id: `workflow-tool-${id}`, label: item.label, description: item.detail, tags: ['工作流', '内置工具'], status: '可加入流程', data: {id, ...item}});
    result.push({type: 'workflow', id: 'workflow-canvas', label: '专业工作流画布', description: '编排资料、MCP、分析、报告和邮件交付节点', tags: ['工作流', '编排'], status: '可编辑', data: {canvas: true}});
    return result;
  }

  function renderTags(resources) {
    const select = root.querySelector('[data-tools-tag]');
    const current = select.value;
    const tags = [...new Set(resources.flatMap(item => item.tags || []))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
    select.replaceChildren(new Option('全部标签', ''));
    tags.forEach(tag => select.add(new Option(tag, tag)));
    select.value = tags.includes(current) ? current : '';
  }

  function filtered(resources) {
    const query = root.querySelector('[data-tools-search]').value.trim().toLowerCase();
    const tag = root.querySelector('[data-tools-tag]').value;
    return resources.filter(item => {
      const tabMatch = activeTab === 'all' || item.type === activeTab;
      const tagMatch = !tag || item.tags.includes(tag);
      const textMatch = !query || [item.label, item.description, item.id, ...(item.tags || [])].join(' ').toLowerCase().includes(query);
      return tabMatch && tagMatch && textMatch;
    });
  }

  function actionButton(label, fn, className = 'tools-card-button') {
    const button = node('button', className, label); button.type = 'button'; button.onclick = fn; return button;
  }

  function renderCard(item) {
    const card = node('article', 'tools-resource-card'); card.dataset.resourceType = item.type;
    const icon = node('span', `tools-resource-icon tools-resource-icon-${item.type}`, item.type === 'mcp' ? '⌁' : item.type === 'plugin' ? '▣' : item.type === 'workflow' ? '↗' : '✦'); icon.setAttribute('aria-hidden', 'true');
    const heading = node('div', 'tools-resource-heading'); append(heading, node('strong', '', item.label), node('span', 'tools-resource-status', item.status));
    const copy = node('div', 'tools-resource-copy'); append(copy, heading, node('p', '', item.description));
    const tags = node('div', 'tools-card-tags'); for (const tag of item.tags || []) tags.append(node('span', '', tag));
    const footer = node('footer', 'tools-resource-footer');
    if (item.type === 'mcp') append(footer, actionButton('编辑', () => open('mcp', item.data)), actionButton('测试与发现', () => inspectMcp(item.data)), actionButton(item.data.enabled ? '停用' : '启用', () => toggleMcp(item.data)), actionButton('删除', () => removeMcp(item.data), 'tools-card-button tools-card-button-danger'));
    if (item.type === 'custom') append(footer, actionButton('编辑', () => open('custom', {...item.data, schemaDraft: editableSchema(item.data)})), actionButton('删除', () => removeCustom(item.data), 'tools-card-button tools-card-button-danger'));
    if (item.type === 'plugin') {
      if (item.data.github_url) { const link = node('a', 'tools-resource-link', '查看来源 ↗'); link.href = item.data.github_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; footer.append(link); }
      append(footer, actionButton('移除', () => removePlugin(item.data), 'tools-card-button tools-card-button-danger'));
    }
    if (item.type === 'workflow') append(footer, actionButton(item.data.canvas ? '打开画布' : '加入工作流', () => item.data.canvas ? openWorkflow() : addWorkflowTool(item.data.id)));
    append(card, icon, copy, tags, footer); return card;
  }

  function render() {
    if (!root) return;
    const resources = records(); renderTags(resources); const matches = filtered(resources);
    const grid = root.querySelector('#tools-resource-grid'); grid.replaceChildren(...matches.map(renderCard));
    const empty = root.querySelector('#tools-empty'); empty.hidden = Boolean(matches.length);
    root.querySelector('#tools-resource-count').textContent = `${resources.length} 个资源`;
    root.querySelector('#tools-filter-status').textContent = matches.length === resources.length ? '' : `${matches.length} 个匹配`;
    root.querySelector('#tools-status').textContent = Object.keys(state.errors).length ? Object.values(state.errors).join('；') : '';
    root.querySelectorAll('[data-tools-tab]').forEach(button => { const selected = button.dataset.toolsTab === activeTab; button.setAttribute('aria-selected', String(selected)); });
  }

  function removeCustom(item) {
    if (!confirm(`删除本地自定义工具“${item.name}”？`)) return;
    state.custom = state.custom.filter(value => value.id !== item.id); writeCustom(); render();
  }

  async function removePlugin(item) {
    if (!confirm(`移除插件“${item.label}”？`)) return;
    try { await api(`plugins/github/${encodeURIComponent(item.id)}`, 'DELETE'); await load(true); }
    catch (error) { root.querySelector('#tools-status').textContent = `移除失败。${error.message}`; }
  }

  function openWorkflow() {
    showView('analysis');
    setTimeout(() => window.DesktopWorkbench?.setMode?.('focus'), 0);
  }

  function addWorkflowTool(id) {
    showView('analysis');
    window.DesktopWorkbench?.setMode('focus');
    const ready = window.DesktopWorkbench?.addBuiltinTool?.(id);
    if (ready) notice('已将工作流工具加入当前流程。');
    else notice('请先打开专业工作流画布，再将工具加入流程。', true);
  }

  async function load(force = false) {
    if (!root) return;
    if (loading && !force) return loading;
    loading = (async () => {
      const requests = await Promise.allSettled([api('mcp'), api('plugins'), api('workflows/catalog'), api('settings')]);
      state.errors = {};
      const [mcp, plugins, catalog, settings] = requests;
      if (mcp.status === 'fulfilled') state.mcp = mcp.value; else state.errors.mcp = `MCP 加载失败。${mcp.reason.message}`;
      if (plugins.status === 'fulfilled') state.plugins = plugins.value.plugins || []; else state.errors.plugin = `插件加载失败。${plugins.reason.message}`;
      if (catalog.status === 'fulfilled') state.catalog = catalog.value; else state.errors.workflow = `工作流加载失败。${catalog.reason.message}`;
      if (settings.status === 'fulfilled') state.settings = settings.value; else state.errors.settings = `设置加载失败。${settings.reason.message}`;
      state.loaded = true; render();
    })().finally(() => { loading = null; });
    return loading;
  }

  function handleGlobalAction(event) {
    const button = event.target.closest?.('[data-tools-action]');
    if (!button || !button.closest('#tools-center') || event.__toolsCenterHandled) return;
    event.__toolsCenterHandled = true;
    event.preventDefault();
    event.stopPropagation();
    try { open(button.dataset.toolsAction); }
    catch (error) {
      globalThis.openToolsFallback?.(button.dataset.toolsAction, error);
    }
  }

  function bind() {
    if (!root || root.dataset.bound) return;
    root.dataset.bound = 'true'; state.custom = readCustom();
    root.addEventListener('click', event => {
      const button = event.target.closest('[data-tools-action]');
      if (!button || !root.contains(button)) return;
      event.preventDefault();
      event.stopPropagation();
      open(button.dataset.toolsAction);
    });
    root.querySelector('[data-tools-refresh]').onclick = () => load(true);
    root.querySelector('[data-tools-search]').oninput = render;
    root.querySelector('[data-tools-tag]').onchange = render;
    root.querySelectorAll('[data-tools-tab]').forEach(button => { button.onclick = () => { activeTab = button.dataset.toolsTab; render(); }; });
    render();
  }

  function install() {
    root = document.getElementById('tools-center'); bind();
  }

  function safeInstall() {
    try { install(); }
    catch (error) {
      globalThis.ToolsCenterError = error;
      root = null;
      document.getElementById('tools-status')?.replaceChildren(node('span', '', `工具中心初始化失败。${error.message || error}`));
    }
  }

  function view(name) {
    if (!root) safeInstall();
    document.body.classList.toggle('tools-center-view', name === 'tools');
    root?.closest('[data-view-pane]')?.classList.toggle('tools-page-active', name === 'tools');
    if (name === 'tools') load().catch(error => { root.querySelector('#tools-status').textContent = error.message; });
  }

  document.addEventListener('click', handleGlobalAction, true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', safeInstall, {once: true}); else safeInstall();
  return {install, view, refresh: () => load(true), openAction: kind => open(kind)};
})();
