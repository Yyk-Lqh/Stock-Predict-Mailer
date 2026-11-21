/* Desktop professional workflow canvas. Mobile keeps the original shell. */
window.DesktopWorkbench = (() => {
  const desktop = matchMedia('(min-width: 761px)');
  if (!desktop.matches) return;

  const preference = 'stock_predict_mailer.desktop.view.v1';
  const workflowKey = 'stock_predict_mailer.desktop.workflow.v1';
  const office = document.querySelector('.pony-office');
  const inspectorTitle = document.querySelector('.inspector-head h2');
  const originalTitle = inspectorTitle.textContent;
  const statusParent = $('task-status').parentElement;
  const statusNext = $('task-status').nextSibling;
  const STATUS_LABEL = {
    idle: '未开始', waiting: '等待前置节点', running: '执行中', completed: '已完成',
    failed: '执行失败', skipped: '已跳过', degraded: '降级完成', needs_input: '等待用户处理'
  };
  const STATUS_ICON = {idle: '○', waiting: '⋯', running: '◌', completed: '✓', failed: '!', skipped: '–', degraded: '≈', needs_input: '?'};
  const TYPE_LABEL = {
    model: '模型', trained: '模型版本', input: '资料', validation: '校验', retrieval: '上下文', analysis: '分析',
    review: '风险', chart: '图表', report: '报告', delivery: '交付', custom: '自定义'
  };
  const REAL_KEYS = new Set(['model', 'prediction', 'validate', 'tools', 'main', 'risk', 'charts', 'report', 'mail']);
  const STEP_TO_KEY = {validate: 'evidence', forecast: 'prediction', tools: 'context', main: 'main', prediction: 'main', risk: 'risk', advice: 'main', merge: 'risk', charts: 'charts', report: 'report', mail: 'delivery'};
  const clone = value => JSON.parse(JSON.stringify(value));
  const GRID_SPACING = 18;
  const defaultCanvasPan = () => ({x: 30, y: 22});

  const defaultGraph = () => ({
    version: 1,
    nodes: [
      {id: 'model', position: {x: 36, y: 200}, data: {label: '选择或校验分析模型', type: 'model', detail: '确认已启用的默认模型或角色模型，未配置时阻止任务提交。', source: '默认模型设置 · 角色配置', input: '默认模型 ID、角色配置', output: '可用的分析模型', enabled: true, condition: '始终', failurePolicy: 'stop', actualKey: 'model'}},
      {id: 'prediction', position: {x: 284, y: 200}, data: {label: '读取预测资料', type: 'input', detail: '读取上游预测、周期、有效期和 synthetic 标记。', source: '任务表单 · 原始任务 JSON', input: 'prediction', output: '已解析的预测资料', enabled: true, condition: '模型已可用', failurePolicy: 'stop', actualKey: 'prediction'}},
      {id: 'evidence', position: {x: 532, y: 200}, data: {label: '校验事实与证据', type: 'validation', detail: '校验事实来源、观测时间、知识引用和输入结构。', source: 'context · knowledge citations · validate 事件', input: '预测资料、事实、证据引用', output: '通过校验的证据包', enabled: true, condition: '预测资料完整', failurePolicy: 'stop', actualKey: 'validate'}},
      {id: 'context', position: {x: 780, y: 200}, data: {label: '获取行情或上下文', type: 'retrieval', detail: '读取已授权 MCP 工具结果或行情快照。无来源时保持等待数据。', source: '授权 MCP 工具 · /api/market/snapshot', input: '标的、上下文查询', output: '事实与历史序列（如有）', enabled: true, condition: '证据校验完成', failurePolicy: 'degrade', actualKey: 'tools'}},
      {id: 'main', position: {x: 1028, y: 200}, data: {label: '执行主分析', type: 'analysis', detail: '执行主 Agent 或确定性降级分析，所有结论必须带允许的依据。', source: 'main step · 主模型/确定性分析', input: '预测、事实、上下文', output: '推断、建议、限制', enabled: true, condition: '上下文已读取或明确缺失', failurePolicy: 'degrade', actualKey: 'main'}},
      {id: 'risk', position: {x: 1152, y: 34}, data: {label: '风险核对', type: 'review', detail: '复核风险、限制和不确定性，保留与上游预测冲突的记录。', source: 'risk 子 Agent · analysis.risks/limitations', input: '主分析结果', output: '风险与限制', enabled: true, condition: '主分析完成', failurePolicy: 'degrade', actualKey: 'risk'}},
      {id: 'charts', position: {x: 1152, y: 366}, data: {label: '图表生成', type: 'chart', detail: '仅使用任务事件或分析产物中的真实图表数据，没有序列时显示空状态。', source: 'chart 事件 · analysis.charts', input: '历史/预测序列（如有）', output: '任务实际生成的 SVG 图表', enabled: true, condition: '主分析完成', failurePolicy: 'skip', actualKey: 'charts'}},
      {id: 'report', position: {x: 1400, y: 200}, data: {label: '报告生成', type: 'report', detail: '校验分析并保存报告，报告内容包含事实、推断、限制和来源。', source: 'report 事件 · /api/tasks/{id}/report', input: '分析、风险、图表', output: '报告产物', enabled: true, condition: '风险和图表处理完成', failurePolicy: 'stop', actualKey: 'report'}},
      {id: 'delivery', position: {x: 1648, y: 200}, data: {label: '邮件或其他交付', type: 'delivery', detail: '按已授权收件人和配置传输报告，记录模拟、成功、失败或待确认状态。', source: 'mail 事件 · 邮件回执', input: '报告、授权收件人', output: '交付状态', enabled: true, condition: '报告已生成且启用通知', failurePolicy: 'report', actualKey: 'mail'}}
    ],
    edges: [
      {id: 'model-prediction', source: 'model', target: 'prediction'}, {id: 'prediction-evidence', source: 'prediction', target: 'evidence'},
      {id: 'evidence-context', source: 'evidence', target: 'context'}, {id: 'context-main', source: 'context', target: 'main'},
      {id: 'main-risk', source: 'main', target: 'risk'}, {id: 'main-charts', source: 'main', target: 'charts'},
      {id: 'risk-report', source: 'risk', target: 'report'}, {id: 'charts-report', source: 'charts', target: 'report'},
      {id: 'report-delivery', source: 'report', target: 'delivery'}
    ]
  });

  let root = null, focus = null, feedback = null, task = null, pane = 'progress';
  let navFocus = null, navHall = null, modeSwitch = null, navCollapse = null, origin = null, mode = 'focus', expiry = null, expiresAt = 0;
  let disconnected = false, sampling = false, selected = 'model', graph = defaultGraph(), savedGraph = clone(graph), dirty = false;
  let history = [], message = '', canvasPan = defaultCanvasPan(), canvasZoom = .72, canvasDrag = null, composerParent = null;
  const runtime = {taskId: null, states: new Map(), details: new Map(), events: []};
  try {
    if (localStorage.getItem(preference) === 'hall') mode = 'hall';
    const pan = JSON.parse(localStorage.getItem('stock_predict_mailer.desktop.canvas.pan.v1') || 'null');
    const zoom = Number(localStorage.getItem('stock_predict_mailer.desktop.canvas.zoom.v1'));
    if (Number.isFinite(pan?.x) && Number.isFinite(pan.y)) canvasPan = pan;
    if (zoom > 0 && zoom <= 1.6) canvasZoom = zoom;
    const stored = localStorage.getItem(workflowKey);
    if (stored) {
      const candidate = normalizeGraph(JSON.parse(stored));
      if (!validateGraph(candidate).length) graph = savedGraph = candidate;
    }
  } catch (_) { /* Invalid or unavailable local storage keeps system defaults. */ }

  const NAV_ICONS = {'new-analysis': '+', analysis: '⌂', knowledge: '▦', records: '▤', overview: '?', settings: '⚙', memory: '◌'};
  const navCollapsed = () => { try { return localStorage.getItem('stock_predict_mailer.desktop.nav.collapsed.v1') === '1'; } catch (_) { return false; } };

  const put = (id, value) => { const node = $(id); if (node && node.textContent !== value) node.textContent = value; };
  const safeProfiles = () => { try { return profiles; } catch (_) { return []; } };
  const safeSettings = () => { try { return settings; } catch (_) { return null; } };
  const activeTask = () => Boolean(task && ['submitted', 'working'].includes(task.status?.state));
  const nodeById = id => graph.nodes.find(node => node.id === id);
  const runtimeFor = id => runtime.details.get(id) || {};
  const statusFor = id => runtime.states.get(id) || 'idle';
  const statusText = id => STATUS_LABEL[statusFor(id)] || STATUS_LABEL.idle;

  function normalizeGraph(raw) {
    if (!raw || typeof raw !== 'object' || !Array.isArray(raw.nodes) || !Array.isArray(raw.edges)) throw Error('工作流配置必须包含 nodes 和 edges');
    const coordinate = value => Number.isFinite(Number(value)) ? Number(value) : 0;
    return {version: 1, nodes: raw.nodes.map(node => ({id: String(node.id || '').trim(), position: {x: coordinate(node.position?.x), y: coordinate(node.position?.y)}, data: {
      label: String(node.data?.label || '').trim(), type: String(node.data?.type || 'custom'), detail: String(node.data?.detail || '').trim(), source: String(node.data?.source || '用户配置').trim(),
      input: String(node.data?.input || '等待数据').trim(), output: String(node.data?.output || '等待数据').trim(), enabled: node.data?.enabled !== false,
      condition: String(node.data?.condition || '始终').trim(), failurePolicy: String(node.data?.failurePolicy || 'stop'), actualKey: typeof node.data?.actualKey === 'string' ? node.data.actualKey : null,
      modelVersion: typeof node.data?.modelVersion === 'string' ? node.data.modelVersion : null
    }})), edges: raw.edges.map(edge => ({id: String(edge.id || '').trim(), source: String(edge.source || '').trim(), target: String(edge.target || '').trim()}))};
  }

  function validateGraph(value = graph) {
    const errors = [], ids = new Set();
    for (const node of value.nodes) {
      if (!node.id) errors.push('存在空节点 ID');
      if (ids.has(node.id)) errors.push(`节点 ID 重复：${node.id}`);
      ids.add(node.id);
      if (!node.data.label || !node.data.detail || !node.data.type) errors.push(`节点配置不完整：${node.id || '未命名节点'}`);
    }
    const seenEdges = new Set();
    for (const edge of value.edges) {
      if (!ids.has(edge.source) || !ids.has(edge.target)) errors.push(`连线引用不存在的节点：${edge.id || edge.source + '→' + edge.target}`);
      if (edge.source === edge.target) errors.push(`连线不能连接自身：${edge.source}`);
      const key = `${edge.source}→${edge.target}`;
      if (seenEdges.has(key)) errors.push(`连线重复：${key}`);
      seenEdges.add(key);
    }
    const adjacency = new Map(value.nodes.map(node => [node.id, []]));
    for (const edge of value.edges) if (adjacency.has(edge.source) && adjacency.has(edge.target)) adjacency.get(edge.source).push(edge.target);
    const visiting = new Set(), visited = new Set();
    const visit = id => { if (visiting.has(id)) return true; if (visited.has(id)) return false; visiting.add(id); const cycle = (adjacency.get(id) || []).some(visit); visiting.delete(id); visited.add(id); return cycle; };
    if (value.nodes.some(node => visit(node.id))) errors.push('工作流存在循环依赖');
    const enabled = value.nodes.filter(node => node.data.enabled !== false), enabledIds = new Set(enabled.map(node => node.id));
    const incoming = new Map(enabled.map(node => [node.id, 0])), outgoing = new Map(enabled.map(node => [node.id, 0]));
    for (const edge of value.edges) if (enabledIds.has(edge.source) && enabledIds.has(edge.target)) { incoming.set(edge.target, incoming.get(edge.target) + 1); outgoing.set(edge.source, outgoing.get(edge.source) + 1); }
    const entries = enabled.filter(node => incoming.get(node.id) === 0), ends = enabled.filter(node => outgoing.get(node.id) === 0);
    if (entries.length !== 1) errors.push(`流程入口必须唯一（当前 ${entries.length} 个）`);
    if (ends.length !== 1) errors.push(`流程结束节点必须唯一（当前 ${ends.length} 个）`);
    return [...new Set(errors)];
  }

  function canConnect(source, target) {
    if (!source || !target || source === target || !nodeById(source) || !nodeById(target)) return false;
    if (graph.edges.some(edge => edge.source === source && edge.target === target)) return false;
    const visited = new Set();
    const reaches = id => { if (id === source) return true; if (visited.has(id)) return false; visited.add(id); return graph.edges.filter(edge => edge.source === id).some(edge => reaches(edge.target)); };
    return !reaches(target);
  }
  function setMessage(value) { message = value; const node = $('desktop-workflow-message'); if (node) node.textContent = value; }
  function commit(next, announcement) { history = [...history.slice(-19), clone(graph)]; graph = normalizeGraph(next); dirty = true; setMessage(announcement); renderCanvas(); renderInspector(); updateSaveState(); }
  function selectNode(id, moveFocus = false) { if (!nodeById(id)) return; selected = id; renderCanvas(); renderInspector(); if (moveFocus) nodeElement(id)?.focus({preventScroll: true}); }
  function removeNode() { const node = nodeById(selected); if (!node) return; const incoming = graph.edges.filter(edge => edge.target === selected), outgoing = graph.edges.filter(edge => edge.source === selected), remaining = {nodes: graph.nodes.filter(item => item.id !== selected), edges: graph.edges.filter(edge => edge.source !== selected && edge.target !== selected)}; if (incoming.length === 1 && outgoing.length === 1 && canConnect(incoming[0].source, outgoing[0].target)) remaining.edges.push({id: `bridge-${Date.now()}`, source: incoming[0].source, target: outgoing[0].target}); commit(remaining, incoming.length === 1 && outgoing.length === 1 ? '节点已删除，已尝试保留前后依赖。' : '节点及其连线已删除，请检查流程入口和结束节点。'); selected = remaining.nodes[0]?.id || ''; renderCanvas(); renderInspector(); }
  const TYPE_DEFAULTS = {
    input: ['资料输入', '分析所需的行情、财报或研究资料。'], validation: ['数据校验', '核对交易日、缺口与价格口径。'],
    model: ['预测模型', '产出预测的模型与参数。'], retrieval: ['上下文检索', '从知识库补充可核对的事实。'],
    analysis: ['分析', '综合预测与资料形成结论。'], review: ['风险复核', '检查极端值与失效条件。'],
    trained: ['已训练模型', '接入注册表里的某个版本，参数与训练区间取自模型清单。'],
    chart: ['图表', '生成走势与分布图。'], report: ['报告', '汇总为可交付的文本。'],
    delivery: ['交付', '发送邮件或归档。'], custom: ['新建节点', '请说明此节点的输入、输出和执行边界。']
  };
  const TYPE_COLOR = {input: '#3f8f6a', validation: '#7a6fbf', model: '#4a6cc4', trained: '#5a5fb0', retrieval: '#3f7f9f', analysis: '#a0703f', review: '#b5544f', chart: '#3f8a84', report: '#6a6f8a', delivery: '#8a7a3f', custom: '#8a8f94'};
  function addNode(type = 'custom', overrides = {}) {
    const base = nodeById(selected), id = `${type}-${Date.now().toString(36)}`, [label, detail] = TYPE_DEFAULTS[type] || TYPE_DEFAULTS.custom;
    const node = {id, position: {x: (base?.position.x ?? 80) + 248, y: base?.position.y ?? 80}, data: {...{label, type, detail, source: '用户配置', input: '等待数据', output: '等待数据', enabled: true, condition: '前置节点完成', failurePolicy: 'stop', actualKey: null}, ...overrides}};
    const outgoing = base && graph.edges.filter(edge => edge.source === base.id);
    const edges = outgoing.length === 1 ? graph.edges.map(edge => edge.id === outgoing[0].id ? {...edge, source: id} : edge).concat({id: `${base.id}-${id}`, source: base.id, target: id}) : graph.edges;
    commit({nodes: [...graph.nodes, node], edges}, `已添加${TYPE_DEFAULTS[type] ? label : '自定义节点'}，请完善配置。`); selected = id; renderCanvas(); renderInspector();
  }
  async function addTrainedNode() {
    let body;
    try { body = await api('registry'); } catch (error) { setMessage(`读取模型注册表失败：${error.message}`); return; }
    const models = (body && body.models) || [];
    if (!models.length) { setMessage('注册表里还没有已训练的模型；先在本地训练一个，再把它接入画布。'); return; }
    const latest = models[0];
    addNode('trained', {label: `${latest.algorithm || '模型'} · ${latest.version.slice(0, 8)}`, detail: `${latest.synthetic ? '合成' : '真实'}数据 · ${latest.training_rows || 0} 行 · 标签至 ${latest.train_label_end || '—'}`, modelVersion: latest.version});
  }
  function editNode(event) { event.preventDefault(); const node = nodeById(selected); if (!node) return; const form = event.currentTarget, data = {...node.data, label: form.elements.label.value.trim(), detail: form.elements.detail.value.trim(), type: form.elements.type.value, enabled: form.elements.enabled.checked, condition: form.elements.condition.value.trim() || '始终', failurePolicy: form.elements.failurePolicy.value}; if (!data.label || !data.detail) { setMessage('节点名称和说明不能为空。'); return; } commit({...graph, nodes: graph.nodes.map(item => item.id === selected ? {...item, data} : item)}, '节点配置已更新。'); }
  function connectNodes(event) { event.preventDefault(); const form = event.currentTarget, source = form.elements.source.value, target = form.elements.target.value; if (!canConnect(source, target)) { setMessage('连线无效：不能自连、重复或产生循环依赖。'); return; } commit({...graph, edges: [...graph.edges, {id: `${source}-${target}-${Date.now().toString(36)}`, source, target}]}, '连线已创建。'); }
  function undo() { const previous = history.at(-1); if (!previous) return; history = history.slice(0, -1); graph = normalizeGraph(previous); dirty = true; setMessage('已撤销上一次编辑。'); renderCanvas(); renderInspector(); updateSaveState(); }
  function saveWorkflow() { const errors = validateGraph(); if (errors.length) { setMessage(`保存失败：${errors[0]}`); renderInspector(); return; } try { localStorage.setItem(workflowKey, JSON.stringify(graph)); savedGraph = clone(graph); dirty = false; setMessage('自定义流程已保存到本机。'); updateSaveState(); } catch (_) { setMessage('保存失败：本机存储不可用，当前编辑内容已保留。'); } }
  function restoreDefault() { if (dirty && !confirm('当前流程尚未保存，恢复系统默认会覆盖当前编辑内容。继续吗？')) return; commit(defaultGraph(), '已恢复系统默认流程，请保存后作为当前流程使用。'); selected = 'model'; renderCanvas(); renderInspector(); }
  function exportWorkflow() { const blob = new Blob([JSON.stringify(graph, null, 2)], {type: 'application/json'}), url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = 'stock-predict-mailer-workflow.json'; link.click(); URL.revokeObjectURL(url); setMessage('工作流配置已导出。'); }
  function importWorkflow(event) { const file = event.target.files?.[0]; event.target.value = ''; if (!file) return; const reader = new FileReader(); reader.onload = () => { try { const candidate = normalizeGraph(JSON.parse(reader.result)), errors = validateGraph(candidate); if (errors.length) throw Error(errors[0]); commit(candidate, '工作流已导入，请保存以保留本次配置。'); selected = candidate.nodes[0]?.id || ''; renderCanvas(); renderInspector(); } catch (error) { setMessage('导入失败：' + error.message); } }; reader.readAsText(file); }
  function updateSaveState() { const save = $('desktop-workflow-save'), undoButton = $('desktop-workflow-undo'), validation = $('desktop-workflow-validation'), errors = validateGraph(); if (save) { save.disabled = !dirty; save.textContent = dirty ? '保存流程 *' : '已保存'; } if (undoButton) undoButton.disabled = !history.length; if (validation) { validation.dataset.state = errors.length ? 'invalid' : 'valid'; validation.textContent = errors.length ? `流程有 ${errors.length} 个问题` : '流程校验通过'; } }

  function nodeElement(id) {
    return $('desktop-workflow-nodes')?.querySelector(`[data-workflow-node="${CSS.escape(id)}"]`);
  }

  function nodePosition(node) {
    return canvasDrag?.id === node.id && canvasDrag.preview ? canvasDrag.preview : node.position;
  }

  function drawNodePosition(element, {x, y}) {
    if (!element) return;
    element.style.left = `${x}px`;
    element.style.top = `${y}px`;
  }

  function moveNode(id, position) {
    selected = id;
    commit({...graph, nodes: graph.nodes.map(node => node.id === id ? {...node, position} : node)}, '节点位置已更新。');
    nodeElement(id)?.focus({preventScroll: true});
  }

  function createNodeElement(node) {
    const status = statusFor(node.id), details = runtimeFor(node.id), article = document.createElement('article');
    article.className = `desktop-flow-node status-${status}`;
    article.dataset.workflowNode = node.id;
    article.dataset.status = status;
    article.dataset.type = node.data.type;
    article.style.setProperty('--node-accent', TYPE_COLOR[node.data.type] || TYPE_COLOR.custom);
    article.tabIndex = 0;
    article.setAttribute('aria-label', `${node.data.label}，${TYPE_LABEL[node.data.type] || '自定义'}，${STATUS_LABEL[status] || '未开始'}`);
    drawNodePosition(article, nodePosition(node));
    article.classList.toggle('selected', node.id === selected);
    article.classList.toggle('disabled', node.data.enabled === false);
    article.classList.toggle('dragging', canvasDrag?.id === node.id && Boolean(canvasDrag.preview));
    if (node.data.modelVersion) article.title = `模型版本 ${node.data.modelVersion}`;
    const head = document.createElement('header'), icon = document.createElement('span'), title = document.createElement('div'), label = document.createElement('strong'), type = document.createElement('small');
    icon.className = 'desktop-flow-node-icon';
    icon.textContent = STATUS_ICON[status] || '○';
    label.textContent = node.data.label;
    type.textContent = TYPE_LABEL[node.data.type] || node.data.type;
    title.append(label, type);
    head.append(icon, title);
    const body = document.createElement('p');
    body.textContent = node.data.detail;
    const foot = document.createElement('footer'), badge = document.createElement('span'), source = document.createElement('span');
    badge.className = 'desktop-flow-status';
    badge.textContent = STATUS_LABEL[status] || '未开始';
    source.textContent = details.source || node.data.source || '用户配置';
    source.title = details.source || node.data.source || '';
    foot.append(badge, source);
    const inPort = document.createElement('span'), outPort = document.createElement('span');
    inPort.className = 'desktop-flow-port in';
    outPort.className = 'desktop-flow-port out';
    inPort.setAttribute('aria-hidden', 'true');
    outPort.setAttribute('aria-hidden', 'true');
    article.append(head, body, foot, inPort, outPort);
    article.addEventListener('click', () => selectNode(node.id, true));
    article.addEventListener('keydown', event => {
      if (canvasDrag) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectNode(node.id, true);
      } else if (event.key.startsWith('Arrow')) {
        event.preventDefault();
        const step = event.shiftKey ? 32 : 8, next = {...node.position};
        if (event.key === 'ArrowLeft') next.x -= step;
        if (event.key === 'ArrowRight') next.x += step;
        if (event.key === 'ArrowUp') next.y -= step;
        if (event.key === 'ArrowDown') next.y += step;
        moveNode(node.id, next);
      } else if (event.key === 'Delete' && document.activeElement === article) {
        event.preventDefault();
        selected = node.id;
        removeNode();
      }
    });
    return article;
  }

  function edgePath(source, target) {
    const center = node => {
      const {x, y} = nodePosition(node), element = nodeElement(node.id);
      const halfWidth = (element?.offsetWidth || 208) / 2, halfHeight = (element?.offsetHeight || 126) / 2;
      return {x: x + halfWidth, y: y + halfHeight, halfWidth, halfHeight};
    };
    const from = center(source), to = center(target);
    const dx = to.x - from.x, dy = to.y - from.y;
    if (Math.abs(dy) > Math.max(208, Math.abs(dx))) {
      const direction = Math.sign(dy);
      const sy = from.y + from.halfHeight * direction, ty = to.y - to.halfHeight * direction;
      const bend = Math.max(46, Math.abs(ty - sy) * .42) * direction;
      return `M ${from.x} ${sy} C ${from.x} ${sy + bend}, ${to.x} ${ty - bend}, ${to.x} ${ty}`;
    }
    const direction = dx < 0 ? -1 : 1;
    const sx = from.x + from.halfWidth * direction, tx = to.x - to.halfWidth * direction;
    const bend = Math.max(46, Math.abs(tx - sx) * .42) * direction;
    return `M ${sx} ${from.y} C ${sx + bend} ${from.y}, ${tx - bend} ${to.y}, ${tx} ${to.y}`;
  }

  function renderEdges(movedId) {
    const layer = $('desktop-workflow-edge-paths');
    if (!layer) return;
    const paths = [];
    for (const edge of graph.edges) {
      if (movedId && edge.source !== movedId && edge.target !== movedId) continue;
      const source = nodeById(edge.source), target = nodeById(edge.target);
      if (!source || !target) continue;
      const geometry = edgePath(source, target);
      if (movedId) {
        layer.querySelector(`[data-edge-id="${CSS.escape(edge.id)}"]`)?.setAttribute('d', geometry);
        continue;
      }
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', geometry);
      path.setAttribute('class', 'desktop-flow-edge');
      path.dataset.edgeId = edge.id;
      path.setAttribute('marker-end', 'url(#desktop-flow-arrow)');
      path.setAttribute('tabindex', '0');
      path.setAttribute('aria-label', `${source.data.label} → ${target.data.label}`);
      path.addEventListener('click', () => selectNode(edge.source));
      paths.push(path);
    }
    if (!movedId) layer.replaceChildren(...paths);
  }

  function renderCanvas() {
    const host = $('desktop-workflow-nodes');
    if (!host) return;
    const focusedId = document.activeElement?.dataset.workflowNode;
    host.replaceChildren(...graph.nodes.map(createNodeElement));
    renderEdges();
    if (focusedId) nodeElement(focusedId)?.focus({preventScroll: true});
    updateSaveState();
  }

  function renderInspector() { const host = $('desktop-workflow-inspector'); if (!host) return; const node = nodeById(selected), errors = validateGraph(); host.replaceChildren(); const heading = document.createElement('div'); heading.className = 'desktop-flow-inspector-head'; const title = document.createElement('h3'); title.textContent = node ? '节点详情' : '工作流详情'; const status = document.createElement('span'); status.textContent = errors.length ? `流程有 ${errors.length} 个问题` : '流程校验通过'; status.dataset.state = errors.length ? 'invalid' : 'valid'; heading.append(title, status); host.append(heading); if (node) { const form = document.createElement('form'); form.className = 'desktop-flow-form'; form.innerHTML = `<label>节点名称<input name="label" maxlength="80" required></label><label>节点类型<select name="type">${Object.entries(TYPE_LABEL).map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></label><label>节点说明<textarea name="detail" rows="3" maxlength="400"></textarea></label><label>执行条件<input name="condition" maxlength="120"></label><label>失败处理<select name="failurePolicy"><option value="stop">停止流程</option><option value="degrade">降级继续</option><option value="skip">跳过节点</option><option value="report">记录并继续</option></select></label><label class="desktop-flow-check"><input name="enabled" type="checkbox"> 启用此节点</label>`; form.elements.label.value = node.data.label; form.elements.type.value = node.data.type; form.elements.detail.value = node.data.detail; form.elements.condition.value = node.data.condition; form.elements.failurePolicy.value = node.data.failurePolicy; form.elements.enabled.checked = node.data.enabled !== false; form.onsubmit = editNode; host.append(form); const runtimeBox = document.createElement('dl'); runtimeBox.className = 'desktop-flow-runtime'; const info = runtimeFor(node.id); [['当前状态', STATUS_LABEL[statusFor(node.id)] || '未开始'], ['输入数据', info.input || node.data.input || '等待数据'], ['输出数据', info.output || node.data.output || '等待数据'], ['数据来源', info.source || node.data.source || '用户配置'], ['失败原因', info.failure || '无']].forEach(([key, value]) => { const dt = document.createElement('dt'); dt.textContent = key; const dd = document.createElement('dd'); dd.textContent = value; runtimeBox.append(dt, dd); }); host.append(runtimeBox); const actions = document.createElement('div'); actions.className = 'desktop-flow-actions'; const save = document.createElement('button'); save.type = 'button'; save.textContent = '保存节点'; save.onclick = () => form.requestSubmit(); const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'danger'; remove.textContent = '删除节点'; remove.onclick = removeNode; actions.append(save, remove); host.append(actions); const connections = document.createElement('div'); connections.className = 'desktop-flow-connections'; const h4 = document.createElement('h4'); h4.textContent = '连接'; connections.append(h4); for (const edge of graph.edges.filter(item => item.source === node.id || item.target === node.id)) { const row = document.createElement('div'); row.className = 'desktop-flow-connection'; row.textContent = `${nodeById(edge.source)?.data.label || edge.source} → ${nodeById(edge.target)?.data.label || edge.target}`; const button = document.createElement('button'); button.type = 'button'; button.textContent = '删除'; button.onclick = () => commit({...graph, edges: graph.edges.filter(item => item.id !== edge.id)}, '连线已删除。'); row.append(button); connections.append(row); } host.append(connections); } const connect = document.createElement('form'); connect.className = 'desktop-flow-connect'; connect.innerHTML = '<h4>创建连线</h4><label>从<select name="source"></select></label><label>到<select name="target"></select></label><button type="submit">连接节点</button>'; for (const select of [connect.elements.source, connect.elements.target]) for (const item of graph.nodes) select.append(new Option(item.data.label, item.id)); connect.elements.source.value = selected; connect.onsubmit = connectNodes; host.append(connect); }

  function inputState() { let raw; try { raw = JSON.parse($('task-data').value); if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw Error(); } catch (_) { return {state: 'invalid', field: 'task-data', label: '请修正原始 JSON', detail: '原始输入无法解析，请打开资料检查格式。'}; } const prediction = window.AnalysisInput.currentPrediction(); if (typeof prediction?.subject !== 'string' || !prediction.subject.trim()) return {state: 'empty', label: '填写分析资料', detail: '先填写标的、预测周期和上游模型版本。'}; const result = {prediction, facts: Array.isArray(raw.context?.facts) ? raw.context.facts.length : 0}; if (typeof prediction.model_version !== 'string' || !prediction.model_version.trim()) return {...result, state: 'invalid', field: 'p-model-version', label: '补充模型版本', detail: '请填写这份预测的上游模型版本。'}; if (!(Number.isFinite(prediction.horizon?.value) && prediction.horizon.value > 0)) return {...result, state: 'invalid', field: 'p-horizon-value', label: '核对预测周期', detail: '预测周期需要大于零。'}; if (!(Date.parse(prediction.valid_until) > Date.now())) return {...result, state: 'expired', field: 'p-valid-until', label: '更新过期预测', detail: '预测已过期或缺少有效期，请核对原始资料后更新。'}; if (prediction.confidence != null && !(Number.isFinite(prediction.confidence) && prediction.confidence >= 0 && prediction.confidence <= 1)) return {...result, state: 'invalid', field: 'p-confidence', label: '核对置信度', detail: '置信度须在 0 到 1 之间；上游未提供时可留空。'}; if (raw.context?.facts && (!Array.isArray(raw.context.facts) || raw.context.facts.some(fact => typeof fact?.source !== 'string' || !fact.source.trim() || !Number.isFinite(Date.parse(fact.observed_at))))) return {...result, state: 'invalid', label: '补充事实来源', detail: '每条客观事实都需要来源和有效的观测时间。'}; return {...result, state: 'ready', label: prediction.subject, detail: '主要资料已填写；发送时会再次校验资料、归档和授权。'}; }
  function openData() { origin = document.activeElement?.getClientRects?.().length ? document.activeElement : $('analysis-data-open'); $('prediction-editor').open = true; window.AnalysisInput.open('input'); const target = $('task-form').querySelector('[aria-invalid="true"]') || $(inputState().field || 'p-subject'); for (let parent = target.parentElement; parent && parent !== $('task-form'); parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; target.focus(); target.scrollIntoView({block: 'nearest'}); }
  function openResult() { if (!task) return; origin = document.activeElement; window.AnalysisInput.open(['submitted', 'working'].includes(task.status.state) ? 'progress' : 'report'); $('analysis-tab-' + pane).focus(); }
  function chooseModel() { origin = document.activeElement; if (safeProfiles().some(item => item.enabled && item.id === safeSettings()?.default_model_id)) $('composer-model').click(); else { showView('settings'); showPanel('models'); $('model-name').focus(); } }
  async function sample(event) { if (sampling) return; const button = event.currentTarget, current = safeProfiles().find(item => item.enabled && item.id === safeSettings()?.default_model_id); if (current?.provider !== 'mock' && current && !confirm('准备示例会将工作台默认模型切换为 Mock，并替换当前预测与事实。不会自动提交分析。继续？')) return; if (window.AnalysisInput.currentPrediction()?.subject && (!current || current.provider === 'mock') && !confirm('用合成示例替换当前预测与事实？当前问题会保留，不会自动提交。')) return; sampling = true; button.disabled = true; try { await $('try-sample').onclick(); if ($('task-data').value.includes('console-mock')) { update(); $('conversation-message').focus(); notice('离线示例已准备：默认模型为 Mock，资料为合成资料。输入问题后点击发送。'); } } finally { sampling = false; button.disabled = false; } }

  function runtimeSet(id, status, patch = {}) { if (!nodeById(id)) return; const current = statusFor(id); if (current === 'failed' && status !== 'failed') return; if (['waiting', 'running', 'failed', 'completed', 'degraded', 'skipped', 'needs_input'].includes(status)) runtime.states.set(id, status); runtime.details.set(id, {...runtimeFor(id), ...patch}); }
  function marketDetail() { const current = globalThis.PonyMarketFeed?.current?.(); const snapshot = current?.snapshot; if (!snapshot) return {source: current?.status === 'down' ? '行情源不可用' : '行情源尚未返回', input: '标的或上下文查询', output: current?.status === 'down' ? '暂无实时数据' : '等待数据', failure: current?.status === 'down' ? '行情源不可用，未使用静态走势替代' : '等待行情源返回'}; let stamp = snapshot.as_of || '更新时间未提供'; try { stamp = `${new Date(snapshot.as_of).toLocaleString('zh-CN', {hour12: false, timeZone: snapshot.timezone || undefined})} · ${snapshot.timezone || '时区未提供'}`; } catch (_) {} const session = snapshot.session === 'live' ? '实时' : snapshot.session === 'delayed' ? '延迟' : '状态未提供'; return {source: `${snapshot.source} · ${stamp} · ${session}`, input: '行情快照', output: `${snapshot.quotes?.length || 0} 个标的 · ${snapshot.history?.length || snapshot.candles?.length || 0} 个历史点`, failure: ''}; }
  function applyEvent(event) { if (!event) return; runtime.events.push(event); if (runtime.events.length > 200) runtime.events.shift(); if (event.kind === 'step') { const id = STEP_TO_KEY[event.step]; if (id) runtimeSet(id, event.status === 'completed' ? 'completed' : event.status === 'failed' ? 'failed' : 'running', {source: event.label || '任务执行事件', output: event.summary?.join(' / ') || undefined, failure: event.code || undefined}); } if (event.kind === 'tool') runtimeSet('context', event.status === 'completed' ? 'completed' : event.status === 'failed' ? 'degraded' : 'running', {source: event.label || '授权上下文工具', output: event.status === 'completed' ? event.label : '等待工具返回', failure: event.status === 'failed' ? event.code : undefined}); if (event.kind === 'chart') runtimeSet('charts', 'completed', {source: '任务 chart 事件', output: event.label || '任务图表已生成'}); if (event.kind === 'report') runtimeSet('report', 'completed', {source: '任务 report 事件', output: event.label || '报告已保存'}); if (event.kind === 'mail') runtimeSet('delivery', ['sent', 'simulated', 'completed'].includes(event.status) ? 'completed' : ['uncertain', 'failed'].includes(event.status) ? 'failed' : 'running', {source: event.label || '邮件回执', output: event.label, failure: event.code || undefined}); if (event.kind === 'adjustment' && event.step && event.code) runtimeSet(STEP_TO_KEY[event.step] || event.step, 'degraded', {failure: `${event.code}：${event.label || '执行降级'}`}); renderCanvas(); renderInspector(); }
  function deriveRuntime(nextTask) { const id = nextTask?.id || null; if (id !== runtime.taskId) { const initialBatch = runtime.taskId === null && runtime.events.length > 0; runtime.taskId = id; if (!initialBatch) { runtime.states.clear(); runtime.details.clear(); runtime.events = []; } } const input = inputState(), model = safeProfiles().find(item => item.enabled && item.id === safeSettings()?.default_model_id), result = nextTask?.artifacts?.[0]?.parts?.[0]?.data, analysis = result?.analysis; runtimeSet('model', model ? 'completed' : 'needs_input', {source: model ? `模型设置 · ${model.name}` : '模型设置', input: '默认模型 ID', output: model ? model.name + (model.provider === 'mock' ? ' · 离线模拟' : '') : '未选择模型', failure: model ? '' : '未配置默认模型或角色模型'}); runtimeSet('prediction', input.state === 'ready' ? 'completed' : 'needs_input', {source: input.prediction?.synthetic ? '上游声明 · synthetic' : '上游预测资料', input: '预测 JSON', output: input.prediction?.subject || '等待预测资料', failure: input.state === 'ready' ? '' : input.detail}); const market = marketDetail(); if (!['completed', 'running', 'failed', 'degraded'].includes(statusFor('context'))) runtimeSet('context', 'waiting', market); if (!nextTask) { for (const node of graph.nodes) if (!['model', 'prediction', 'context'].includes(node.id)) runtime.states.set(node.id, node.data.enabled === false ? 'skipped' : 'waiting'); return; } if (analysis) { runtimeSet('risk', analysis.risks?.length || analysis.limitations?.length ? 'completed' : 'degraded', {source: '分析产物 risks/limitations', output: analysis.risks?.[0] || analysis.limitations?.[0] || '未提供风险条目'}); runtimeSet('charts', analysis.charts?.length ? 'completed' : 'degraded', {source: analysis.charts?.length ? '分析产物 charts' : '任务未返回图表序列', output: analysis.charts?.length ? `${analysis.charts.length} 个任务图表` : '暂无实时数据'}); runtimeSet('report', analysis.status === 'degraded' ? 'degraded' : 'completed', {source: '分析报告产物', output: analysis.status === 'degraded' ? '报告已生成，含降级说明' : '报告已生成'}); } if (result?.mail || nextTask.metadata?.request?.notify === false) { const mail = result?.mail; runtimeSet('delivery', !mail ? 'skipped' : ['sent', 'simulated', 'completed'].includes(mail.status) ? 'completed' : mail.status === 'uncertain' || mail.status === 'failed' ? 'failed' : 'degraded', {source: mail ? '邮件结果/授权传输' : '本轮未请求邮件', output: mail ? mail.status : '本轮仅生成报告', failure: mail?.error || ''}); } if (nextTask.status.state === 'failed') { const error = nextTask.metadata?.error?.code || 'TASK_FAILED', running = graph.nodes.find(node => statusFor(node.id) === 'running' || statusFor(node.id) === 'waiting'); if (running) runtimeSet(running.id, 'failed', {failure: `${error}：任务执行失败`, source: '任务终态'}); } if (nextTask.status.state === 'canceled') for (const node of graph.nodes) if (statusFor(node.id) === 'running') runtimeSet(node.id, 'skipped', {failure: '任务已取消'}); for (const node of graph.nodes) { if (node.data.enabled === false) { runtime.states.set(node.id, 'skipped'); continue; } if (!node.data.actualKey && activeTask()) { runtimeSet(node.id, 'skipped', {failure: '当前任务接口未提供该自定义操作', source: '用户配置'}); continue; } if (!['completed', 'degraded', 'failed', 'skipped', 'running', 'needs_input'].includes(statusFor(node.id))) { const deps = graph.edges.filter(edge => edge.target === node.id).map(edge => statusFor(edge.source)); runtime.states.set(node.id, activeTask() && deps.some(state => !['completed', 'degraded', 'skipped'].includes(state)) ? 'waiting' : 'idle'); } } }

  function saveCanvasViewport() {
    try { localStorage.setItem('stock_predict_mailer.desktop.canvas.pan.v1', JSON.stringify(canvasPan)); localStorage.setItem('stock_predict_mailer.desktop.canvas.zoom.v1', String(canvasZoom)); } catch (_) {}
  }

  function applyCanvasViewport() {
    const canvas = $('desktop-workflow-canvas');
    if (!canvas) return;
    const {x, y} = canvasPan;
    $('desktop-workflow-surface').style.transform = `translate(${x}px, ${y}px) scale(${canvasZoom})`;
    $('desktop-workflow-edge-paths').setAttribute('transform', `translate(${x} ${y}) scale(${canvasZoom})`);
    const scaledSpacing = GRID_SPACING * canvasZoom;
    // Keep every second, fourth, etc. grid line at very small scales so the visible dots stay aligned.
    const spacing = scaledSpacing * 2 ** Math.max(0, Math.ceil(Math.log2(8 / scaledSpacing)));
    canvas.style.setProperty('--desktop-grid-spacing', `${spacing}px`);
    canvas.style.setProperty('--desktop-grid-dot', `${Math.max(.55, .7 * canvasZoom)}px`);
    canvas.style.setProperty('--desktop-grid-x', `${x % spacing - spacing / 2}px`);
    canvas.style.setProperty('--desktop-grid-y', `${y % spacing - spacing / 2}px`);
    put('desktop-workflow-zoom', canvasZoom < .01 ? '<1%' : `${Math.round(canvasZoom * 100)}%`);
  }

  function fitCanvas() {
    const canvas = $('desktop-workflow-canvas');
    if (!canvas.clientWidth || !canvas.clientHeight || !graph.nodes.length) return;
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const node of graph.nodes) {
      const {x, y} = node.position, element = nodeElement(node.id);
      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x + (element?.offsetWidth || 208));
      bottom = Math.max(bottom, y + (element?.offsetHeight || 126));
    }
    const rect = canvas.getBoundingClientRect();
    const inspectorLeft = $('desktop-workflow-inspector').getBoundingClientRect().left - rect.left;
    const toolbarBottom = focus.querySelector('.desktop-flow-toolbar').getBoundingClientRect().bottom - rect.top;
    const composerTop = $('analysis-composer').getBoundingClientRect().top - rect.top;
    const viewLeft = 20, viewTop = Math.max(20, toolbarBottom + 16);
    const viewRight = inspectorLeft > 120 ? inspectorLeft - 16 : canvas.clientWidth - 20;
    const viewBottom = composerTop > viewTop + 100 ? composerTop - 16 : canvas.clientHeight - 20;
    const width = right - left, height = bottom - top;
    canvasZoom = Math.min(1, (viewRight - viewLeft) / width, (viewBottom - viewTop) / height);
    if (!(canvasZoom > 0)) canvasZoom = Math.min(1, canvas.clientWidth / width, canvas.clientHeight / height);
    canvasPan = {
      x: (viewLeft + viewRight) / 2 - (left + width / 2) * canvasZoom,
      y: (viewTop + viewBottom) / 2 - (top + height / 2) * canvasZoom
    };
    applyCanvasViewport();
    saveCanvasViewport();
  }

  function worldPoint({x, y}) {
    return {x: (x - canvasPan.x) / canvasZoom, y: (y - canvasPan.y) / canvasZoom};
  }

  function canvasPoint(canvas, event) {
    const rect = canvas.getBoundingClientRect();
    return {x: event.clientX - rect.left, y: event.clientY - rect.top};
  }

  function canvasZoomBy(factor, point) {
    const canvas = $('desktop-workflow-canvas');
    const anchor = point ?? {x: canvas.clientWidth / 2, y: canvas.clientHeight / 2};
    const world = worldPoint(anchor);
    canvasZoom = Math.max(Math.min(.05, canvasZoom), Math.min(1.6, canvasZoom * factor));
    canvasPan = {x: anchor.x - world.x * canvasZoom, y: anchor.y - world.y * canvasZoom};
    applyCanvasViewport();
    saveCanvasViewport();
  }

  function installCanvasInteractions() {
    const canvas = $('desktop-workflow-canvas');
    const edgeSpeed = (position, size) => {
      const margin = 36;
      if (position < margin) return Math.min(1, (margin - position) / margin) * 14;
      if (position > size - margin) return -Math.min(1, (position - size + margin) / margin) * 14;
      return 0;
    };
    const updateDrag = () => {
      const {id, position, offset} = canvasDrag;
      const world = worldPoint(position);
      canvasDrag.preview = {x: world.x - offset.x, y: world.y - offset.y};
      drawNodePosition(nodeElement(id), canvasDrag.preview);
      renderEdges(id);
    };
    const panAtEdge = timestamp => {
      canvasDrag.frame = null;
      const {position, lastFrame} = canvasDrag;
      const step = lastFrame === null ? 1 : Math.min(2, (timestamp - lastFrame) / (1000 / 60));
      canvasDrag.lastFrame = timestamp;
      const width = canvas.clientWidth, height = canvas.clientHeight;
      if (!width || !height) return;
      const x = edgeSpeed(position.x, width), y = edgeSpeed(position.y, height);
      if (!x && !y) {
        canvasDrag.lastFrame = null;
        return;
      }
      canvasPan = {x: canvasPan.x + x * step, y: canvasPan.y + y * step};
      applyCanvasViewport();
      updateDrag();
      canvasDrag.frame = requestAnimationFrame(panAtEdge);
    };
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0 || canvasDrag || event.target.closest('.desktop-flow-edge')) return;
      const element = event.target.closest('.desktop-flow-node');
      const node = element && nodeById(element.dataset.workflowNode);
      const start = canvasPoint(canvas, event);
      const world = worldPoint(start);
      canvasDrag = {pointerId: event.pointerId, id: node?.id, start, pan: canvasPan, preview: null, frame: null, lastFrame: null};
      if (node) canvasDrag.offset = {x: world.x - node.position.x, y: world.y - node.position.y};
      else canvas.classList.add('panning');
      canvas.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    canvas.addEventListener('pointermove', event => {
      if (event.pointerId !== canvasDrag?.pointerId) return;
      const position = canvasPoint(canvas, event), {id, start, pan} = canvasDrag;
      const dx = position.x - start.x, dy = position.y - start.y;
      if (!id) {
        canvasPan = {x: pan.x + dx, y: pan.y + dy};
        applyCanvasViewport();
        return;
      }
      if (!canvasDrag.preview && Math.hypot(dx, dy) < 3) return;
      canvasDrag.position = position;
      nodeElement(id)?.classList.add('dragging');
      updateDrag();
      if (canvasDrag.frame === null) canvasDrag.frame = requestAnimationFrame(panAtEdge);
    });
    const finish = event => {
      if (event.pointerId !== canvasDrag?.pointerId) return;
      const {id, preview, frame} = canvasDrag;
      canvasDrag = null;
      if (frame !== null) cancelAnimationFrame(frame);
      canvas.classList.remove('panning');
      if (id && event.type === 'pointerup') {
        if (preview) moveNode(id, preview);
        else selectNode(id, true);
      } else if (id && preview) renderCanvas();
      saveCanvasViewport();
    };
    for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(event, finish);
    canvas.addEventListener('wheel', event => {
      if (!event.deltaY) return;
      event.preventDefault();
      if (!canvasDrag) canvasZoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12, canvasPoint(canvas, event));
    }, {passive: false});
  }
  function moveComposer(inCanvas) {
    const dock = $('analysis-composer');
    if (!dock || !focus) return;
    if (!composerParent) composerParent = {parent: dock.parentElement, next: dock.nextSibling};
    if (inCanvas && dock.parentElement !== focus) { focus.append(dock); dock.classList.add('desktop-canvas-composer'); }
    if (!inCanvas && dock.parentElement === focus) { composerParent.parent.insertBefore(dock, composerParent.next && composerParent.next.parentElement === composerParent.parent ? composerParent.next : null); dock.classList.remove('desktop-canvas-composer'); }
  }
  function installNavIcons() {
    for (const button of document.querySelectorAll('.nav button')) {
      const glyph = button === navFocus ? '◇' : button === navHall ? '▣' : NAV_ICONS[button.dataset.view || button.id];
      if (!glyph) continue;
      const label = button.textContent.trim();
      button.title ||= label;
      if (!button.hasAttribute('aria-label')) button.setAttribute('aria-label', label);
      const icon = document.createElement('span');
      icon.className = 'desktop-nav-icon';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = glyph;
      button.prepend(icon);
    }
  }

  function setNavCollapsed(value) {
    document.body.classList.toggle('desktop-nav-collapsed', value);
    if (navCollapse) navCollapse.textContent = value ? '›' : '‹';
    navCollapse?.setAttribute('aria-expanded', String(!value));
    navCollapse?.setAttribute('aria-label', value ? '展开导航栏' : '折叠导航栏');
    navCollapse?.setAttribute('title', value ? '展开导航栏' : '折叠导航栏');
    try { localStorage.setItem('stock_predict_mailer.desktop.nav.collapsed.v1', value ? '1' : '0'); } catch (_) {}
    window.AnalysisInput.layout();
  }

  function setMode(value) { mode = value; if (!root || !desktop.matches) return; document.body.classList.toggle('desktop-focus-view', mode === 'focus'); if (modeSwitch) for (const node of modeSwitch.children) node.setAttribute('aria-pressed', String(node.dataset.desktopMode === mode)); office.querySelector('.office-stage').inert = mode === 'focus'; if (office.querySelector('.market-wall')) office.querySelector('.market-wall').inert = mode === 'focus'; moveComposer(mode === 'focus'); for (const button of root.querySelectorAll('[data-desktop-mode]')) button.setAttribute('aria-pressed', String(button.dataset.desktopMode === mode)); try { localStorage.setItem(preference, mode); } catch (_) {} window.AnalysisInput.layout(); if (mode === 'focus') applyCanvasViewport(); }
  function panel(value) { pane = value; if (!desktop.matches || !root) return; if (document.activeElement instanceof HTMLElement && !document.activeElement.closest('#report-inspector') && document.activeElement !== document.body) origin = document.activeElement; inspectorTitle.textContent = {input: '分析资料', progress: '工作进度', report: '报告与证据'}[pane]; }
  function returnFocus() { if (!desktop.matches || !root) return; const candidates = [origin, $('analysis-data-open'), $('desktop-data'), $('desktop-focus-data')]; candidates.find(target => target?.isConnected && target.getClientRects().length)?.focus(); }
  function historyPanel(open = $('analysis-composer').classList.contains('desktop-history-open')) { if (!root || !desktop.matches) return; const count = $('conversation-turns').childElementCount, expanded = Boolean(open && count); $('desktop-history').hidden = !count; put('desktop-history', `会话记录 · ${count} 轮`); $('desktop-history').setAttribute('aria-expanded', String(expanded)); $('analysis-composer').classList.toggle('desktop-history-open', expanded); }

  function update() { if (!root || !desktop.matches) return; deriveRuntime(task); if (navFocus) { navFocus.hidden = document.body.dataset.view !== 'analysis'; navFocus.setAttribute('aria-pressed', String(mode === 'focus')); } if (navHall) { navHall.hidden = document.body.dataset.view !== 'analysis'; navHall.setAttribute('aria-pressed', String(mode === 'hall')); } const input = inputState(), model = safeProfiles().find(item => item.enabled && item.id === safeSettings()?.default_model_id), prediction = input.prediction, until = Date.parse(prediction?.valid_until) || 0; if (until !== expiresAt) { clearTimeout(expiry); expiresAt = until; if (until > Date.now()) expiry = setTimeout(() => { expiresAt = 0; update(); }, Math.min(until - Date.now() + 50, 2147483647)); } const active = activeTask(), result = task?.artifacts?.[0]?.parts?.[0]?.data, failed = task?.status.state === 'failed', canceled = task?.status.state === 'canceled'; put('desktop-title', prediction?.subject ? `${prediction.subject} · 专业分析` : '专业分析工作流'); put('desktop-subtitle', failed ? '任务失败，画布保留真实失败节点和修正入口。' : active && disconnected ? '进度暂未更新，任务可能仍在服务端执行。' : active ? '正在读取真实任务事件，节点状态会随事件更新。' : '可编辑流程结构，提交时仍使用现有分析任务接口。'); for (const id of ['desktop-model', 'desktop-data', 'desktop-focus-data']) $(id).disabled = false; $('desktop-sample').disabled = sampling; put('desktop-model-value', model?.name || '选择模型'); $('desktop-model').dataset.state = model ? 'ready' : 'empty'; $('desktop-model').title = model ? `工作台默认模型：${model.name}` : '先添加或选择一个默认模型。'; put('desktop-data-value', input.label); $('desktop-data').dataset.state = input.state; $('desktop-data').title = input.detail; $('desktop-result').disabled = !task; put('desktop-result-value', active ? '查看工作进度' : failed ? '查看失败原因' : canceled ? '查看已取消任务' : result ? '查看报告与证据' : '等待分析报告'); $('desktop-result').dataset.state = failed ? 'invalid' : result ? 'ready' : active ? 'working' : 'empty'; put('desktop-focus-title', prediction?.subject || '准备你的第一份分析'); put('desktop-focus-copy', prediction ? input.detail : '导入上游预测，或填写标的与周期。画布会把真实任务链路映射为可核对的节点。'); put('desktop-summary-model', model ? `${model.name}${model.provider === 'mock' ? ' · 离线模拟' : ''}` : '尚未选择默认模型'); put('desktop-summary-prediction', prediction ? `${horizonText(prediction.horizon)} · ${prediction.synthetic ? '合成数据' : '上游声明数据'}` : '尚未提供预测'); put('desktop-summary-facts', input.facts ? `${input.facts} 条来源声明` : '本轮未附新增事实'); put('desktop-summary-mail', $('task-notify').checked ? '本轮启用邮件 · 仍需核对授权收件人' : '仅分析 · 本轮不发送邮件'); $('desktop-sample').hidden = Boolean(task); focus.querySelector('.desktop-sample-note').hidden = Boolean(task); historyPanel(); let feedbackText = active ? '分析进行中，工作流状态来自实际任务事件。' : !model ? '先选择分析模型，或准备一个离线示例。' : input.state !== 'ready' ? input.detail : failed ? '上一轮分析失败，请查看失败节点和任务详情。' : canceled ? '上一轮任务已取消，可核对资料后重新发送。' : result ? `上一轮报告已生成${result.analysis?.status === 'degraded' ? '，分析存在降级' : ''}。` : input.detail; if (!active && input.state === 'ready' && $('task-notify').checked && !$('task-recipient').value.trim()) feedbackText = '本轮启用了邮件，请先填写授权收件地址。'; if (active && disconnected) feedbackText = '进度读取中断，任务可能仍在服务端运行。'; put('desktop-feedback-text', feedbackText); feedback.dataset.state = failed || (active && disconnected) || ['invalid', 'expired'].includes(input.state) ? 'invalid' : active ? 'working' : 'normal'; put('desktop-feedback-action', active ? '查看进度' : failed ? '查看原因' : result ? '查看报告' : !model ? '选择模型' : '检查资料'); $('desktop-feedback-action').disabled = false; $('desktop-feedback-action').onclick = active || failed || result ? openResult : !model ? chooseModel : openData; for (const button of document.querySelectorAll('.nav [data-view]')) { if (button.dataset.view === document.body.dataset.view) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); } renderCanvas(); renderInspector(); }

  function install() { if (!desktop.matches) { moveComposer(false); navCollapse?.remove(); navCollapse = null; navFocus?.remove(); navFocus = null; navHall?.remove(); navHall = null; modeSwitch?.remove(); modeSwitch = null; document.body.classList.remove('desktop-nav-collapsed'); if (root) { root.hidden = focus.hidden = feedback.hidden = true; document.body.classList.remove('desktop-workbench', 'desktop-focus-view'); office.querySelector('.office-stage').inert = false; office.querySelector('.market-wall')?.removeAttribute('inert'); clearTimeout(expiry); expiresAt = 0; statusParent.insertBefore($('task-status'), statusNext); $('analysis-composer').classList.remove('desktop-history-open'); inspectorTitle.textContent = originalTitle; document.querySelectorAll('.nav [aria-current]').forEach(button => button.removeAttribute('aria-current')); window.AnalysisInput.layout(); } return; } if (!root) { root = document.createElement('section'); root.id = 'desktop-workflow'; root.setAttribute('aria-label', '分析流程'); root.innerHTML = `<div class="desktop-workflow-heading"><div><h1 id="desktop-title"></h1><p id="desktop-subtitle"></p></div></div><div class="desktop-workflow-actions"><button type="button" id="desktop-model"><span class="desktop-step">1 · 模型</span><strong id="desktop-model-value"></strong></button><button type="button" id="desktop-data"><span class="desktop-step">2 · 资料</span><strong id="desktop-data-value"></strong></button><button type="button" id="desktop-result"><span class="desktop-step">3 · 结果</span><strong id="desktop-result-value"></strong></button></div>`; focus = document.createElement('section'); focus.id = 'desktop-focus'; focus.setAttribute('aria-label', '可编辑分析工作流'); focus.innerHTML = `<div class="desktop-focus-intro"><p class="eyebrow">本轮分析工作流</p><h2 id="desktop-focus-title"></h2><p id="desktop-focus-copy"></p><div class="desktop-focus-actions"><button type="button" id="desktop-focus-data" class="btn primary">填写 / 修改资料</button><button type="button" id="desktop-sample" class="btn">准备离线示例</button></div><p class="hint desktop-sample-note">离线示例会将默认模型设为 Mock 并填入 synthetic 资料，准备后仍需手动发送。</p></div><div class="desktop-flow-toolbar"><div class="desktop-flow-toolbar-status"><strong>可视化流程</strong><span id="desktop-workflow-message" role="status" aria-live="polite">选择节点查看详情。</span></div><div class="desktop-flow-toolbar-actions"><span id="desktop-workflow-validation"></span><button type="button" data-workflow-action="add">新增节点</button><button type="button" data-workflow-action="undo" id="desktop-workflow-undo">撤销</button><button type="button" data-workflow-action="save" id="desktop-workflow-save">保存流程</button><button type="button" data-workflow-action="restore">恢复默认</button><button type="button" data-workflow-action="import">导入</button><button type="button" data-workflow-action="export">导出</button><div class="desktop-flow-viewport-tools" role="group" aria-label="画布视图控制"><button type="button" data-viewport-action="zoom-out" aria-label="缩小画布">−</button><span id="desktop-workflow-zoom">72%</span><button type="button" data-viewport-action="zoom-in" aria-label="放大画布">+</button><button type="button" data-viewport-action="fit" aria-label="适配画布">适配</button></div><input id="desktop-workflow-file" type="file" accept="application/json,.json" hidden></div></div><div class="desktop-flow-layout"><div class="desktop-flow-canvas" id="desktop-workflow-canvas" role="application" aria-label="分析工作流画布"><svg id="desktop-workflow-edges" aria-label="工作流连线"><defs><marker id="desktop-flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs><g id="desktop-workflow-edge-paths"></g></svg><div class="desktop-flow-surface" id="desktop-workflow-surface"><div id="desktop-workflow-nodes"></div></div></div><aside class="desktop-flow-inspector" id="desktop-workflow-inspector" aria-label="节点详情"></aside></div><dl class="desktop-summary"><div><dt>分析模型</dt><dd id="desktop-summary-model"></dd></div><div><dt>预测周期</dt><dd id="desktop-summary-prediction"></dd></div><div><dt>客观事实</dt><dd id="desktop-summary-facts"></dd></div><div><dt>本轮通知</dt><dd id="desktop-summary-mail"></dd></div></dl>`; const intro = focus.querySelector('.desktop-focus-intro'); if (intro) intro.hidden = true; const focusData = focus.querySelector('#desktop-focus-data'); if (focusData) focus.querySelector('.desktop-flow-toolbar')?.prepend(focusData); const summary = focus.querySelector('.desktop-summary'); if (summary) summary.hidden = true; feedback = document.createElement('div'); feedback.id = 'desktop-feedback'; feedback.innerHTML = '<span id="desktop-feedback-text" role="status" aria-live="polite"></span><button type="button" id="desktop-feedback-action"></button><button type="button" id="desktop-history" aria-controls="conversation-thread" aria-expanded="false" hidden></button><span class="desktop-send-hint">Enter 发送 · Shift+Enter 换行</span>'; office.prepend(root, focus); modeSwitch = document.createElement('div'); modeSwitch.className = 'desktop-mode-switch'; modeSwitch.setAttribute('role', 'group'); modeSwitch.setAttribute('aria-label', '界面模式'); for (const [value, text] of [['hall', '普通'], ['focus', '专业']]) { const node = document.createElement('button'); node.type = 'button'; node.textContent = text; node.dataset.desktopMode = value; node.onclick = () => setMode(value); modeSwitch.append(node); } document.querySelector('.nav')?.append(modeSwitch); if (!focus.querySelector('.desktop-flow-palette')) { const palette = document.createElement('aside'); palette.className = 'desktop-flow-palette'; palette.setAttribute('aria-label', '节点库'); const heading = document.createElement('p'); heading.className = 'eyebrow'; heading.textContent = '节点库'; palette.append(heading); for (const [type, [label]] of Object.entries(TYPE_DEFAULTS)) { const item = document.createElement('button'); item.type = 'button'; item.dataset.nodeType = type; item.title = `添加${label}节点`; const dot = document.createElement('i'); dot.setAttribute('aria-hidden', 'true'); dot.style.background = TYPE_COLOR[type] || TYPE_COLOR.custom; item.append(dot, document.createTextNode(label)); item.onclick = () => type === 'trained' ? addTrainedNode() : addNode(type); palette.append(item); } focus.querySelector('.desktop-flow-layout')?.prepend(palette); } navCollapse = document.createElement('button'); navCollapse.type = 'button'; navCollapse.className = 'desktop-nav-collapse'; navCollapse.onclick = () => setNavCollapsed(!document.body.classList.contains('desktop-nav-collapsed')); document.querySelector('.topbar')?.insertBefore(navCollapse, document.querySelector('.nav')); installNavIcons(); setNavCollapsed(navCollapsed()); $('analysis-composer').prepend(feedback); $('desktop-data').onclick = $('desktop-focus-data').onclick = openData; $('desktop-model').onclick = chooseModel; $('desktop-result').onclick = openResult; $('desktop-sample').onclick = sample; $('desktop-history').onclick = () => historyPanel(!$('analysis-composer').classList.contains('desktop-history-open')); root.querySelectorAll('[data-desktop-mode]').forEach(button => { button.onclick = () => setMode(button.dataset.desktopMode); }); focus.querySelectorAll('[data-workflow-action]').forEach(button => { button.onclick = () => ({add: addNode, undo, save: saveWorkflow, restore: restoreDefault, import: () => $('desktop-workflow-file').click(), export: exportWorkflow}[button.dataset.workflowAction])(); }); focus.querySelectorAll('[data-viewport-action]').forEach(button => { button.onclick = () => button.dataset.viewportAction === 'fit' ? fitCanvas() : canvasZoomBy(button.dataset.viewportAction === 'zoom-in' ? 1.15 : 1 / 1.15); }); installCanvasInteractions(); $('desktop-workflow-file').addEventListener('change', importWorkflow); $('report-close').addEventListener('click', returnFocus); new MutationObserver(() => historyPanel()).observe($('conversation-turns'), {childList: true}); document.addEventListener('pointerdown', event => { if (desktop.matches && !$('analysis-composer').contains(event.target)) historyPanel(false); }); document.addEventListener('keydown', event => { if (window.DesktopInteractions?.active?.()) return; if (desktop.matches && event.key === 'Escape' && $('analysis-composer').classList.contains('desktop-history-open')) { event.preventDefault(); event.stopImmediatePropagation(); historyPanel(false); $('desktop-history').focus(); } }, true); $('task-form').addEventListener('submit', () => historyPanel(false)); $('task-form').addEventListener('submit', event => { if (!validateGraph().length) return; event.preventDefault(); event.stopImmediatePropagation(); setMessage('当前工作流未通过校验，请先修正画布问题。'); renderInspector(); }, true); const toolbar = focus.querySelector('.desktop-flow-toolbar'); const resize = new ResizeObserver(() => { if (!desktop.matches) return; focus.style.setProperty('--desktop-flow-toolbar-height', toolbar.offsetHeight + 'px'); const height = root.offsetHeight + 'px'; if (office.style.getPropertyValue('--desktop-workflow-height') !== height) { office.style.setProperty('--desktop-workflow-height', height); document.documentElement.style.setProperty('--desktop-workflow-height', height); window.AnalysisInput.layout(); } renderEdges(); }); resize.observe(root); resize.observe(toolbar); window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } }); document.addEventListener('click', event => { const target = event.target.closest?.('.nav [data-view], #new-analysis'); if (target && dirty && target.dataset.view !== 'analysis' && !confirm('当前工作流尚未保存，离开后编辑内容会保留在本机草稿中。继续吗？')) { event.preventDefault(); event.stopImmediatePropagation(); } }, true); } root.hidden = focus.hidden = feedback.hidden = false; if (navFocus) { navFocus.hidden = document.body.dataset.view !== 'analysis'; navFocus.setAttribute('aria-pressed', String(mode === 'focus')); } if (navHall) { navHall.hidden = document.body.dataset.view !== 'analysis'; navHall.setAttribute('aria-pressed', String(mode === 'hall')); } $('analysis-pane-progress').prepend($('task-status')); document.body.classList.add('desktop-workbench'); setMode(mode); panel(pane); update(); }
  desktop.addEventListener('change', install); new MutationObserver(update).observe(document.body, {attributes: true, attributeFilter: ['data-view']}); document.addEventListener('visibilitychange', () => { if (!document.hidden) update(); }); window.addEventListener('focus', update); install();
  return {update, panel, setMode, mode: () => mode, observe(value) { task = value; update(); }, event: applyEvent, connectionLost(value) { disconnected = value; update(); }, selectionState() { update(); }, reset() { task = null; disconnected = false; runtime.taskId = null; runtime.states.clear(); runtime.details.clear(); update(); }};
})();
