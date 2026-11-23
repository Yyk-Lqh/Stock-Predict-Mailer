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
    failed: '执行失败', skipped: '已跳过', degraded: '降级完成', needs_input: '等待用户处理', canceled: '已取消'
  };
  const STATUS_ICON = {idle: '○', waiting: '⋯', running: '◌', completed: '✓', failed: '!', skipped: '–', degraded: '≈', needs_input: '?', canceled: '×'};
  const TYPE_LABEL = {
    model: '模型', trained: '模型版本', input: '资料', validation: '校验', retrieval: '上下文', analysis: '分析',
    review: '风险', forecast: '归档', knowledge: '知识', database: '数据库', tool: '工具', merge: '汇总',
    chart: '图表', report: '报告', delivery: '交付', custom: '自定义'
  };
  const STEP_TO_KEY = {input:'prediction', validate:'evidence', forecast:'forecast', knowledge:'knowledge',
    tools:'context', main:'main', merge:'merge', charts:'charts', report:'report', mail:'delivery'};
  const CHILDREN = {prediction:'预测子 Agent', risk:'风险子 Agent', advice:'建议子 Agent'};
  const EDGE_CONDITIONS = {always:'始终', has_facts:'有已校验事实', no_facts:'没有已校验事实', notify:'启用邮件通知', no_notify:'未启用邮件通知'};
  const clone = value => JSON.parse(JSON.stringify(value));
  const GRID_SPACING = 18;
  const defaultCanvasPan = () => ({x: 30, y: 22});
  const draftKey = workflowKey + '.draft';
  const libraryKey = workflowKey + '.library';
  const nodeDrafts = new Map();
  let workflowCatalog = null, workSurface = 'edit', archived = null, archivedEvents = [], submitKey = null, submitBody = null;
  let systemTemplate = null, debugDialog = null, selectingPort = null;
  let selectedEdge = null, edgeDrag = null;

  const systemPosition = index => {
    const row=Math.floor(index/4), column=index%4;
    return {x:36+(row%2?3-column:column)*248,y:160+row*232};
  };
  const defaultGraph = () => {
    if (systemTemplate) return normalizeGraph({...systemTemplate, mode:'system'});
    const spec = [
      ['prediction','input','资料输入'], ['evidence','validation','资料校验'], ['forecast','forecast','预测归档'],
      ['knowledge','knowledge','知识检索'], ['context','retrieval','MCP 上下文'], ['main','analysis','主分析'],
      ['merge','merge','结果汇总'], ['charts','chart','图表'], ['report','report','报告'], ['delivery','delivery','邮件交付']
    ];
    return normalizeGraph({version:2, mode:'system', nodes:spec.map(([id,type,label], index) => ({
      id, position:systemPosition(index), data:{type,label,actualKey:Object.keys(STEP_TO_KEY).find(key=>STEP_TO_KEY[key]===id)}
    })), edges:spec.slice(1).map(([target],index)=>({source:spec[index][0],target}))});
  };

  let root = null, focus = null, feedback = null, task = null, pane = 'progress';
  let navFocus = null, navHall = null, modeSwitch = null, navCollapse = null, origin = null, mode = 'focus', expiry = null, expiresAt = 0;
  let disconnected = false, sampling = false, selected = 'prediction', graph = defaultGraph(), savedGraph = clone(graph), dirty = false;
  let history = [], message = '', canvasPan = defaultCanvasPan(), canvasZoom = .72, canvasDrag = null, composerParent = null;
  const runtime = {taskId: null, states: new Map(), details: new Map(), events: []};
  try {
    if (localStorage.getItem(preference) === 'hall') mode = 'hall';
    const pan = JSON.parse(localStorage.getItem('stock_predict_mailer.desktop.canvas.pan.v1') || 'null');
    const zoom = Number(localStorage.getItem('stock_predict_mailer.desktop.canvas.zoom.v1'));
    if (Number.isFinite(pan?.x) && Number.isFinite(pan.y)) canvasPan = pan;
    if (zoom > 0 && zoom <= 1.6) canvasZoom = zoom;
    const stored = localStorage.getItem(workflowKey);
    if (stored) graph = savedGraph = normalizeGraph(JSON.parse(stored));
    const draft = JSON.parse(localStorage.getItem(draftKey) || 'null');
    if (draft?.graph) {
      graph = normalizeGraph(draft.graph);
      for (const [key, value] of draft.fields || []) nodeDrafts.set(key, value);
      dirty = JSON.stringify(graph) !== JSON.stringify(savedGraph) || nodeDrafts.size > 0;
    }

  } catch (_) { /* Invalid or unavailable local storage keeps system defaults. */ }

  const NAV_ICONS = {'new-analysis': '+', analysis: '⌂', knowledge: '▦', records: '▤', overview: '?', settings: '⚙', memory: '◌'};
  const navCollapsed = () => { try { return localStorage.getItem('stock_predict_mailer.desktop.nav.collapsed.v1') === '1'; } catch (_) { return false; } };

  const put = (id, value) => { const node = $(id); if (node && node.textContent !== value) node.textContent = value; };
  const safeProfiles = () => { try { return profiles; } catch (_) { return []; } };
  const safeSettings = () => { try { return settings; } catch (_) { return null; } };
  const activeTask = () => Boolean(task && ['submitted', 'working'].includes(task.status?.state));
  const shownTask = () => archived || task;
  const showingRun = () => workSurface === 'run';
  const nodeById = id => shownGraph().nodes.find(node => node.id === id);
  const runtimeFor = id => runtime.details.get(id) || {};
  const statusFor = id => runtime.states.get(id) || 'idle';
  const statusText = id => STATUS_LABEL[statusFor(id)] || STATUS_LABEL.idle;

  function safeLegacy(value) {
    if (Array.isArray(value)) return value.map(safeLegacy);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
      .filter(([key]) => !/(token|secret|password|api.?key|authorization|headers|env)/i.test(key))
      .map(([key,item]) => [key,safeLegacy(item)]));
    return value;
  }

  function normalizeGraph(raw) {
    if (!raw || ![1,2].includes(raw.version) || !Array.isArray(raw.nodes) || !Array.isArray(raw.edges) ||
        !raw.nodes.length || raw.nodes.length > 24 || raw.edges.length > 64) throw Error('流程文件版本、节点或连线数量无效');
    const coord = value => Number.isFinite(Number(value)) ? Number(value) : 0;
    const nodes = raw.nodes.map(node => {
      if (!node || typeof node.id !== 'string' || !node.data || typeof node.data !== 'object') throw Error('流程文件中有无效节点');
      const data = node.data;
      const fallback = {validate:'validation',tools:'retrieval',main:'analysis',charts:'chart',report:'report',mail:'delivery'};
      const type = raw.version === 1 ? fallback[data.actualKey] || String(data.type || 'custom') : String(data.type || 'custom');
      const fields = type==='database' ? {source:'string',query:'string',scope:'string',path:'string',table:'string',
        symbol_column:'string',limit:'number',include_fact:'boolean'} : type==='tool' ? {tool:'string',required:'boolean'} :
        {model:'string',binding:'string'};
      const config = Object.fromEntries(Object.entries(fields).filter(([key,kind])=>typeof data.config?.[key]===kind)
        .map(([key])=>[key,data.config[key]]));
      return {id:node.id.trim(), position:{x:coord(node.position?.x),y:coord(node.position?.y)}, data:{
        label:String(data.label||'未命名节点'), type, detail:String(data.detail||''), actualKey:data.actualKey||null,
        enabled:data.enabled!==false, failurePolicy:data.failurePolicy==='report'?'stop':data.failurePolicy||'stop', config,
        ...(data.modelVersion?{modelVersion:data.modelVersion}:{}),
        ...(raw.version===1 || data.legacy ? {legacy:safeLegacy(data.legacy || data)} : {})
      }};
    });
    const edges = raw.edges.map(edge=>{
      if (!edge || typeof edge.source!=='string' || typeof edge.target!=='string') throw Error('流程文件中有无效连线');
      return {id:String(edge.id||edge.source+'-'+edge.target),source:edge.source,target:edge.target,
        condition:edge.condition||'always', ...(edge.input?{input:edge.input}:{}), ...(edge.output?{output:edge.output}:{})};
    });
    return {version:2, mode:raw.mode==='system'?'system':'custom',nodes,edges};
  }

  function validateGraph(value = graph) {
    const errors = [], nodes = new Map();
    for (const node of value.nodes) {
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(node.id) || nodes.has(node.id)) errors.push(`${node.id} · 节点 ID 无效或重复`);
      nodes.set(node.id,node);
      if (workflowCatalog && !workflowCatalog.nodes[node.data.type]) errors.push(`${node.id} · 草稿节点缺少执行器`);
    }
    const seen = new Set(), incoming = new Map(value.nodes.map(node=>[node.id,0]));
    for (const edge of value.edges) {
      const from = nodes.get(edge.source), to = nodes.get(edge.target), key = edge.source+'→'+edge.target;
      if (!from || !to || from===to || seen.has(key)) {
        errors.push(`${edge.target} · 连线无效 ${key}`);
        continue;
      }
      seen.add(key);
      incoming.set(to.id,incoming.get(to.id)+1);
      const ports = workflowCatalog?.nodes;
      if (ports?.[from.data.type] && ports?.[to.data.type] && ports[from.data.type].output!==ports[to.data.type].input)
        errors.push(`${to.id} · 端口不匹配 ${key}`);
    }
    if (value.mode !== 'system') {
      const roots = [...incoming].filter(([,degree])=>degree===0).map(([key])=>key);
      if (roots.length!==1 || nodes.get(roots[0])?.data.type!=='input') errors.push(`${roots.join('、')} · 入口或断链节点`);
    }
    return errors;
  }

  function persistDraft() {
    try { localStorage.setItem(draftKey,JSON.stringify({graph,fields:[...nodeDrafts]})); } catch (_) {}
  }

  function customCopy(value = graph) {
    const copy = clone(value);
    if (copy.mode==='system') {
      copy.mode='custom';
      for (const node of copy.nodes) {
        node.data.actualKey=null;
        if (node.data.type==='analysis') node.data.failurePolicy='degrade';
        if (node.data.type==='merge') node.data.enabled=false;
      }
    }
    return copy;
  }

  function shownGraph() {
    if (!showingRun()) return graph;
    const current=shownTask(), metadata=current?.metadata?.workflow;
    const run=metadata?.graph ? normalizeGraph({...metadata.graph,mode:metadata.mode}) : defaultGraph();
    if (run.mode==='custom') return run;
    const events=archived?archivedEvents:runtime.events;
    const plan=events.filter(event=>event.kind==='plan').at(-1)?.steps || [];
    const sequence=plan.map(step=>step.id);
    const main=run.nodes.findIndex(node=>node.id==='main');
    const childNodes=sequence.filter(step=>Object.hasOwn(CHILDREN,step)).map(step=>({
      id:'child-'+step, position:{x:0,y:190}, data:{label:CHILDREN[step],type:'review',actualKey:step, enabled:true,detail:'由主 Agent 决策并由后端串行执行'}
    }));
    if (childNodes.length) run.nodes.splice(main+1,0,...childNodes);
    run.nodes.forEach((node,index)=>{node.position=systemPosition(index);});
    run.edges=run.nodes.slice(1).map((node,index)=>({id:'run-'+index,source:run.nodes[index].id,target:node.id,condition:'always'}));
    return run;
  }

  function canConnect(source, target, ignoredEdge) {
    if (!source || !target || source === target || !nodeById(source) || !nodeById(target)) return false;
    const edges=graph.edges.filter(edge=>edge.id!==ignoredEdge);
    if (edges.some(edge => edge.source === source && edge.target === target)) return false;
    const visited = new Set();
    const reaches = id => { if (id === source) return true; if (visited.has(id)) return false; visited.add(id); return edges.filter(edge => edge.source === id).some(edge => reaches(edge.target)); };
    return !reaches(target);
  }
  function setMessage(value) { message = value; const node = $('desktop-workflow-message'); if (node) node.textContent = value; }
  function commit(next, announcement) { history = [...history.slice(-19), clone(graph)]; graph = normalizeGraph(customCopy({...graph,...next})); dirty = true; persistDraft(); setMessage(announcement); renderCanvas(); renderInspector(); updateSaveState(); }
  function selectNode(id, moveFocus = false) { if (!nodeById(id)) return; selected = id; renderCanvas(); renderInspector(); if (moveFocus) nodeElement(id)?.focus({preventScroll: true}); }
  function removeNode() { const node = nodeById(selected); if (!node || showingRun()) return; const incoming = graph.edges.filter(edge => edge.target === selected), outgoing = graph.edges.filter(edge => edge.source === selected), remaining = {nodes: graph.nodes.filter(item => item.id !== selected), edges: graph.edges.filter(edge => edge.source !== selected && edge.target !== selected)}; if (incoming.length === 1 && outgoing.length === 1 && canConnect(incoming[0].source, outgoing[0].target)) remaining.edges.push({id: `bridge-${Date.now()}`, source: incoming[0].source, target: outgoing[0].target}); commit(remaining, incoming.length === 1 && outgoing.length === 1 ? '节点已删除，已尝试保留前后依赖。' : '节点及其连线已删除，请检查流程入口和结束节点。'); selected = remaining.nodes[0]?.id || ''; renderCanvas(); renderInspector(); }
  const TYPE_DEFAULTS = {
    input: ['资料输入', '分析所需的行情、财报或研究资料。'], validation: ['数据校验', '核对交易日、缺口与价格口径。'],
    model: ['预测模型', '产出预测的模型与参数。'], retrieval: ['上下文检索', '从知识库补充可核对的事实。'],
    analysis: ['分析', '综合预测与资料形成结论。'], review: ['风险复核', '检查极端值与失效条件。'],
    trained: ['已训练模型', '接入注册表里的某个版本，参数与训练区间取自模型清单。'],
    forecast: ['预测归档','按事前评价定义固定预测。'], knowledge: ['知识检索','按预测时点检索持有访问权的来源。'],
    database: ['数据库','查询本机 SQLite 文件或项目任务库。'],
    tool: ['内置工具','选择只读检查或查询工具。'],
    merge: ['结果汇总','复核结构化分析。'], chart: ['图表', '生成走势与分布图。'], report: ['报告', '汇总为可交付的文本。'],
    delivery: ['交付', '发送邮件或归档。'], custom: ['新建节点', '请说明此节点的输入、输出和执行边界。']
  };
  const TYPE_COLOR = {input: '#3f8f6a', validation: '#7a6fbf', model: '#4a6cc4', trained: '#5a5fb0', retrieval: '#3f7f9f', analysis: '#a0703f', review: '#b5544f', chart: '#3f8a84', report: '#6a6f8a', delivery: '#8a7a3f', custom: '#8a8f94'};
  function addNode(type = 'custom', overrides = {}) {
    if (showingRun() || graph.nodes.length>=24) return;
    const base = nodeById(selected), id = `${type}-${crypto.randomUUID().slice(0,8)}`, [label, detail] = TYPE_DEFAULTS[type] || TYPE_DEFAULTS.custom;
    const node = {id, position: {x: (base?.position.x ?? 80) + 248, y: base?.position.y ?? 80}, data: {...{label, type, detail, source: '用户配置', input: '等待数据', output: '等待数据', enabled: true, condition: '前置节点完成', failurePolicy: 'stop', actualKey: null}, ...overrides}};
    if(type==='tool' && !node.data.config) {
      const [first]=Object.keys(workflowCatalog?.nodes.tool?.options||{});
      if(first) node.data.config={tool:first,required:false};
    }
    const edges = graph.edges;
    node.position.y += 160;
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
  function addBuiltinTool(id) {
    const spec=workflowCatalog?.nodes.tool?.options[id];
    if (!spec || graph.nodes.length>=24) return false;
    if(showingRun()){workSurface='edit';archived=null;archivedEvents=[];updateWorkspaceTabs();}
    addNode('tool',{label:spec.label,detail:spec.detail,config:{tool:id,required:false}});
    return true;
  }
  function editNode(event) {
    event.preventDefault();
    const form=event.currentTarget, node=nodeById(selected);
    if (!node || showingRun()) return;
    const fields=Object.fromEntries(new FormData(form));
    const type=fields.type, config={};
    if (fields.binding?.trim() && type==='retrieval') config.binding=fields.binding.trim();
    if (fields.model && ['analysis','merge'].includes(type)) config.model=fields.model;
    if (type==='tool') Object.assign(config,{tool:fields.tool,required:form.elements.required.checked});
    if (type==='database') {
      Object.assign(config,{limit:Number(fields.limit),include_fact:form.elements.include_fact.checked});
      if (fields.source==='sqlite') Object.assign(config,{source:'sqlite',path:fields.path.trim(),table:fields.table,
        symbol_column:fields.symbol_column});
      else Object.assign(config,{query:fields.query,scope:fields.scope});
    }
    const data={...node.data,type,label:fields.label.trim(),detail:fields.detail.trim(),enabled:form.elements.enabled.checked,
      failurePolicy:fields.failurePolicy,config};
    if (!data.label) return;
    nodeDrafts.delete(node.id);
    document.activeElement?.blur();
    commit({...graph,nodes:graph.nodes.map(item=>item.id===node.id?{...item,data}:item)}, '节点配置已更新');
  }
  function linkNodes(source,target,condition='always',existing=null) {
    if (existing && existing.source===source && existing.target===target) return;
    if (!canConnect(source,target,existing?.id)) {setMessage('请选择不同节点并避免重复连线与环路');return;}
    const ports=workflowCatalog?.nodes, from=ports?.[nodeById(source).data.type], to=ports?.[nodeById(target).data.type];
    if (from && to && from.output!==to.input) {setMessage(`${target} · 端口不匹配 ${from.output} → ${to.input}`);return;}
    document.activeElement?.blur();
    if (existing) {
      commit({edges:graph.edges.map(edge=>edge.id===existing.id?{...edge,source,target}:edge)},'连线已改接，可点击「撤销」恢复');
      return;
    }
    commit({...graph,edges:[...graph.edges,{id:crypto.randomUUID(),source,target,condition}]},'连线已创建');
  }
  function connectNodes(event) {event.preventDefault();const form=event.currentTarget;linkNodes(form.elements.source.value,form.elements.target.value,form.elements.condition.value);}
  function undo() {
    const previous=history.pop(); if (!previous || showingRun()) return;
    graph=normalizeGraph(previous);dirty=true;persistDraft();setMessage('已撤销上一次编辑');renderCanvas();renderInspector();
  }
  function saveWorkflow() {
    if (showingRun()) return;
    try { localStorage.setItem(workflowKey,JSON.stringify(graph)); savedGraph=clone(graph); dirty=nodeDrafts.size>0; persistDraft();
      setMessage(dirty?'流程已保存。节点表单还有未提交修改':'流程已保存到本机');updateSaveState();
    } catch (_) {setMessage('本机存储不可用，当前编辑仍保留在页面中');}
  }
  function restoreDefault() {
    if (dirty && !confirm('恢复系统模板会替换当前画布和节点表单。继续吗？')) return;
    history.push(clone(graph));graph=defaultGraph();nodeDrafts.clear();dirty=true;workSurface='edit'; selected='prediction';
    persistDraft();setMessage('已恢复系统模板');renderCanvas();renderInspector();
  }
  function duplicateNode(node) {
    if (graph.nodes.length>=24) return;
    const copy=clone(node);
    copy.id=crypto.randomUUID();copy.data.label=(copy.data.label+' 副本').slice(0,80);copy.position.y+=165;
    selected=copy.id;commit({...graph,nodes:[...graph.nodes,copy]},'节点已复制，请连接输入和输出');
  }
  function exportWorkflow() {
    const blob=new Blob([JSON.stringify(safeLegacy(graph),null,2)],{type:'application/json'}), url=URL.createObjectURL(blob);
    const link=document.createElement('a');link.href=url;link.download='stock-predict-mailer-workflow.json';link.click();URL.revokeObjectURL(url);
    setMessage('工作流已导出');
  }
  async function importWorkflow(event) {
    const file=event.target.files?.[0];event.target.value='';if (!file) return;
    try {
      if (file.size>128*1024) throw Error('流程文件超过 128 KiB');
      const candidate=normalizeGraph(JSON.parse(await file.text()));
      const keys=new Set(candidate.nodes.map(node=>node.id));
      const parents=new Map([...keys].map(key=>[key,new Set()]));
      if(keys.size!==candidate.nodes.length) throw Error('文件包含重复节点');
      for (const edge of candidate.edges) {
        if(!keys.has(edge.source)||!keys.has(edge.target)||edge.source===edge.target||parents.get(edge.target).has(edge.source))
          throw Error('文件中的连线无效或重复');
        parents.get(edge.target).add(edge.source);
      }
      const resolved=new Set();
      while(resolved.size<keys.size) {
        const next=[...keys].find(key=>!resolved.has(key)&&[...parents.get(key)].every(parent=>resolved.has(parent)));
        if(!next) throw Error('流程文件包含环路');
        resolved.add(next);
      }
      history.push(clone(graph));graph=candidate;nodeDrafts.clear();dirty=true;workSurface='edit';selected=graph.nodes[0].id;
      persistDraft();setMessage('工作流已导入，请运行校验后保存');renderCanvas();renderInspector();
    } catch (error) {setMessage('导入失败 · '+error.message);}
  }
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
    if (workflowCatalog && !workflowCatalog.nodes[node.data.type] && !showingRun()) article.dataset.draft='true';
    if (node.data.modelVersion) article.title = `模型版本 ${node.data.modelVersion}`;
    const head = document.createElement('header'), icon = document.createElement('span'), title = document.createElement('div'), label = document.createElement('strong'), type = document.createElement('small');
    icon.className = 'desktop-flow-node-icon';
    icon.textContent = STATUS_ICON[status] || '○';
    label.textContent = node.data.label;
    type.textContent = (TYPE_LABEL[node.data.type] || node.data.type) + (article.dataset.draft?' · 草稿':'');
    title.append(label, type);
    head.append(icon, title);
    const body = document.createElement('p');
    const database=workflowCatalog?.nodes.database?.options;
    const query=node.data.config?.source==='sqlite' ? (node.data.config.table || '本机 SQLite 文件') :
      database?.queries[node.data.config?.query || database?.defaults.query];
    const tool=workflowCatalog?.nodes.tool?.options[node.data.config?.tool]?.label;
    const configured=(node.data.type==='database' && query ? `${query} · 最多 ${node.data.config?.limit ?? database.defaults.limit} 条` : '') ||
      tool || node.data.config?.binding || (node.data.config?.model && safeProfiles().find(profile=>profile.id===node.data.config.model)?.name);
    body.textContent = configured || node.data.detail || workflowCatalog?.nodes[node.data.type]?.detail || '草稿配置';
    const foot = document.createElement('footer'), badge = document.createElement('span'), source = document.createElement('span');
    badge.className = 'desktop-flow-status';
    badge.textContent = STATUS_LABEL[status] || '未开始';
    source.textContent = details.source || workflowCatalog?.nodes[node.data.type]?.source || '用户配置';
    source.title = details.source || node.data.source || '';
    foot.append(badge, source);
    const inPort = document.createElement('button'), outPort = document.createElement('button');
    inPort.className = 'desktop-flow-port in';
    outPort.className = 'desktop-flow-port out';
    for (const [port,direction] of [[inPort,'input'],[outPort,'output']]) {
      port.type='button';port.disabled=showingRun() || (direction==='input' && node.data.type==='input');
      port.setAttribute('aria-label',`${node.data.label} ${direction==='input'?'输入':'输出'}端口`);
      port.addEventListener('pointerdown',event=>event.stopPropagation());
      port.addEventListener('click',event=>{
        event.stopPropagation();
        if(direction==='output'){selectingPort=node.id;setMessage('选择目标节点的输入端口');}
        else if(selectingPort){linkNodes(selectingPort,node.id);selectingPort=null;}
      });
    }
    article.append(head, body, foot, inPort, outPort);
    article.addEventListener('click', () => selectNode(node.id, true));
    article.addEventListener('keydown', event => {
      if(event.target!==article) return;
      if (canvasDrag || (showingRun() && !['Enter',' '].includes(event.key))) return;
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
    for (const edge of shownGraph().edges) {
      if (movedId && edge.source !== movedId && edge.target !== movedId) continue;
      const source = nodeById(edge.source), target = nodeById(edge.target);
      if (!source || !target) continue;
      const geometry = edgePath(source, target);
      if (movedId) {
        const path=layer.querySelector(`[data-edge-id="${CSS.escape(edge.id)}"]`);
        path?.setAttribute('d',geometry);
        continue;
      }
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', geometry);
      path.setAttribute('class', edge.id===selectedEdge&&!showingRun()?'desktop-flow-edge selected':'desktop-flow-edge');
      path.dataset.edgeId = edge.id;
      path.setAttribute('marker-end', 'url(#desktop-flow-arrow)');
      path.setAttribute('tabindex', '0');
      path.setAttribute('aria-label', `${source.data.label} → ${target.data.label}`);
      const selectEdge=()=>{
        selectedEdge=showingRun()?null:edge.id;
        selectNode(edge.source);
        if(selectedEdge) setMessage('拖动圆形手柄可更换起点或终点');
      };
      path.addEventListener('click',selectEdge);
      path.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();selectEdge();}});
      paths.push(path);
    }
    if (!movedId) layer.replaceChildren(...paths);
    renderEdgeHandles(layer);
  }

  function renderEdgeHandles(layer) {
    layer.querySelectorAll('[data-edge-end]').forEach(handle=>handle.remove());
    if (!selectedEdge || showingRun()) return;
    const path=layer.querySelector(`[data-edge-id="${CSS.escape(selectedEdge)}"]`);
    if (!path) return;
    const length=path.getTotalLength(), inset=Math.min(length*.27,15/canvasZoom);
    for(const end of ['source','target']) {
      const point=path.getPointAtLength(end==='source'?inset:length-inset);
      const handle=document.createElementNS(path.namespaceURI,'circle');
      handle.dataset.edgeEnd=end;
      handle.setAttribute('class','desktop-flow-edge-handle');
      handle.setAttribute('cx',point.x);
      handle.setAttribute('cy',point.y);
      handle.setAttribute('r',6/canvasZoom);
      const title=document.createElementNS(path.namespaceURI,'title');
      title.textContent=end==='source'?'拖动改接起点':'拖动改接终点';
      handle.append(title);
      layer.append(handle);
    }
  }

  function installEdgeDragging(canvas) {
    const svg=$('desktop-workflow-edges');
    const line=document.createElementNS(svg.namespaceURI,'path');
    line.setAttribute('class','desktop-flow-edge-preview');
    svg.append(line);
    canvas.addEventListener('pointerdown',event=>{
      const end=event.target.closest('[data-edge-end]')?.dataset.edgeEnd;
      const edge=end&&graph.edges.find(item=>item.id===selectedEdge);
      if(!edge || showingRun() || event.button!==0 || edgeDrag || canvasDrag) return;
      const path=svg.querySelector(`[data-edge-id="${CSS.escape(edge.id)}"]`);
      if(!path)return;
      const fixed=path.getPointAtLength(end==='source'?path.getTotalLength():0).matrixTransform(path.getCTM());
      edgeDrag={edge,end,fixed,pointer:event.pointerId};
      canvas.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    canvas.addEventListener('pointermove',event=>{
      if(event.pointerId!==edgeDrag?.pointer) return;
      const point=canvasPoint(canvas,event), {fixed}=edgeDrag;
      line.setAttribute('d',`M ${fixed.x} ${fixed.y} L ${point.x} ${point.y}`);
    });
    const finish=event=>{
      if(event.pointerId!==edgeDrag?.pointer) return;
      const {edge,end}=edgeDrag;
      edgeDrag=null;
      line.removeAttribute('d');
      if(event.type!=='pointerup' || showingRun() || !graph.edges.includes(edge)) return;
      const hit=document.elementFromPoint(event.clientX,event.clientY);
      const port=hit?.closest('.desktop-flow-port');
      const node=hit?.closest('[data-workflow-node]')?.dataset.workflowNode;
      if(!node || (port && !port.classList.contains(end==='source'?'out':'in'))) {
        setMessage('请将手柄拖到对应的节点端口');return;
      }
      linkNodes(end==='source'?node:edge.source,end==='target'?node:edge.target,edge.condition,edge);
    };
    for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,finish);
  }

  function renderCanvas() {
    const host = $('desktop-workflow-nodes');
    if (!host) return;
    const focusedId = document.activeElement?.dataset.workflowNode;
    host.replaceChildren(...shownGraph().nodes.map(createNodeElement));
    renderEdges();
    if (focusedId) nodeElement(focusedId)?.focus({preventScroll: true});
    updateSaveState();
  }

  function makeButton(label, callback) {
    const button=document.createElement('button');
    button.type='button';button.textContent=label;button.onclick=callback;
    return button;
  }

  function terms(values, className='desktop-flow-runtime') {
    const list=document.createElement('dl');list.className=className;
    for (const [label,value] of values) {
      if(value==null || value==='') continue;
      const dt=document.createElement('dt'), dd=document.createElement('dd');
      dt.textContent=label;dd.textContent=typeof value==='object'?JSON.stringify(value,null,2):String(value);list.append(dt,dd);
    }
    return list;
  }

  function connectionEditor(host,node) {
    const links=document.createElement('div');links.className='desktop-flow-connections';
    for (const edge of graph.edges.filter(item=>item.source===node.id||item.target===node.id)) {
      const row=document.createElement('div');row.className='desktop-flow-connection';
      row.textContent=`${nodeById(edge.source)?.data.label} → ${nodeById(edge.target)?.data.label}`;
      const condition=document.createElement('select');
      condition.setAttribute('aria-label','连线条件 '+row.textContent);
      for(const [id,label] of Object.entries(EDGE_CONDITIONS)) condition.add(new Option(label,id));
      condition.value=edge.condition;
      condition.onchange=()=>commit({...graph,edges:graph.edges.map(item=>item.id===edge.id?{...item,condition:condition.value}:item)},'连线条件已更新');
      row.append(condition,makeButton('删除',()=>commit({...graph,edges:graph.edges.filter(item=>item.id!==edge.id)},'连线已删除')));
      links.append(row);
    }
    host.append(links);
    const form=document.createElement('form');form.className='desktop-flow-connect';
    form.innerHTML='<h4>创建连线</h4><label>从<select name="source"></select></label><label>到<select name="target"></select></label>'+
      '<label>条件<select name="condition"></select></label><button type="submit">连接节点</button>';
    for(const select of [form.elements.source,form.elements.target]) {
      for(const item of graph.nodes) select.add(new Option(item.data.label,item.id));
    }
    for(const [id,label] of Object.entries(EDGE_CONDITIONS)) form.elements.condition.add(new Option(label,id));
    form.elements.source.value=node.id;form.onsubmit=connectNodes;host.append(form);
  }

  let databaseFiles;
  let databaseScan={scope:'common',directory:''};
  function databaseForm(form,fields,database) {
    if (!database) return ()=>{};
    for (const [name,choices,fallback] of [['source',database.sources,'tasks'],['query',database.queries,database.defaults.query],
      ['scope',database.scopes,database.defaults.scope]]) {
      for (const [key,label] of Object.entries(choices || {})) form.elements[name].add(new Option(label,key));
      form.elements[name].value=fields[name] ?? fallback;
    }
    for (const name of ['path','table','symbol_column']) form.elements[name].value=fields[name] ?? '';
    form.elements.limit.max=database.max_results;
    form.elements.limit.value=fields.limit ?? database.defaults.limit;
    form.elements.include_fact.checked=fields.include_fact ?? database.defaults.include_fact;
    const tables=form.querySelector('datalist'), status=form.querySelector('[data-database-status]');
    const button=form.querySelector('[data-database-inspect]');
    const picker=form.querySelector('[data-database-files]'), refresh=form.querySelector('[data-database-refresh]');
    const scanStatus=form.querySelector('[data-database-scan-status]');
    const scope=form.querySelector('[data-scan-scope]'), folder=form.querySelector('[data-scan-folder]');
    scope.value=databaseScan.scope;
    folder.value=databaseScan.directory;
    const showFolder=()=>{folder.closest('label').hidden=scope.value!=='directory';};
    scope.onchange=showFolder;
    showFolder();
    let requested=false;
    async function scan(force=false) {
      const selection={scope:scope.value,directory:folder.value.trim()};
      if (force && selection.scope==='directory' && !selection.directory) {
        scanStatus.textContent='请先填写本机目录的绝对路径';
        return;
      }
      requested=true;
      refresh.disabled=true;
      scanStatus.textContent='正在查找 SQLite 文件…';
      if (force || !databaseFiles) {
        databaseScan=selection;
        const loading=selection.scope==='common'?api('workflows/database/discover'):
          api('workflows/database/discover','POST',selection);
        databaseFiles=loading.catch(error=>{databaseFiles=null;throw error;});
      }
      try {
        const data=await databaseFiles;
        picker.replaceChildren(new Option('选择已发现的文件',''));
        for (const file of data.files) picker.add(new Option(`${file.name} · ${file.path}`,file.path));
        picker.value=form.elements.path.value;
        if (!picker.value) picker.selectedIndex=0;
        const count=data.files.length?`发现 ${data.files.length} 个文件`:'当前范围暂无候选文件';
        scanStatus.textContent=count+(data.truncated?'，结果部分显示，可缩小到指定目录':'');
      } catch(error) {scanStatus.textContent=error.message;}
      finally {refresh.disabled=false;}
    }
    refresh.onclick=()=>scan(true);
    picker.onchange=()=>{
      if (!picker.value || picker.value===form.elements.path.value) return;
      form.elements.path.value=picker.value;
      form.elements.path.dispatchEvent(new Event('input',{bubbles:true}));
      button.click();
    };
    form.elements.path.addEventListener('input',()=>{
      tables.replaceChildren();status.textContent='';form.elements.table.value='';form.elements.symbol_column.value='';
      picker.value=form.elements.path.value;
      if (!picker.value) picker.selectedIndex=0;
    });
    button.onclick=async()=>{
      const path=form.elements.path.value.trim();
      if (!path) {status.textContent='请先填写 SQLite 文件路径';return;}
      button.disabled=true;status.textContent='正在读取数据表…';
      try {
        const result=await api('workflows/database/inspect','POST',{path});
        if (form.elements.path.value.trim()!==path) return;
        tables.replaceChildren(...result.tables.map(name=>new Option(name)));
        status.textContent=result.tables.length ? `连接成功，找到 ${result.tables.length}${result.has_more?'+':''} 张表。可在数据表字段中选择。` : '连接成功，暂无可查询的表';
      } catch(error) {
        if (form.elements.path.value.trim()===path) status.textContent=error.message;
      } finally {button.disabled=false;}
    };
    return ()=>{if(!requested) scan();};
  }

  let mcpTools, mcpToolsAt=0;
  function fillMcpTools(form) {
    const list=form.querySelector('#workflow-mcp-tools');
    if(list.dataset.requested) return;
    list.dataset.requested='true';
    if(!mcpTools || Date.now()-mcpToolsAt>5000) {
      mcpToolsAt=Date.now();
      mcpTools=api('workflows/tools/mcp').catch(()=>{mcpTools=null;return {bindings:{}};});
    }
    mcpTools.then(data=>list.replaceChildren(...Object.entries(data.bindings).map(([id,label])=>new Option(label,id))));
  }

  function nodeEditor(host,node) {
    const form=document.createElement('form');form.className='desktop-flow-form';
    form.innerHTML='<label>节点名称<input name="label" maxlength="80" required></label><label>节点类型<select name="type"></select></label>'+
      '<label>节点说明<textarea name="detail" rows="2" maxlength="400"></textarea></label>'+
      '<label data-node-config="binding">授权 MCP 工具<input name="binding" list="workflow-mcp-tools" maxlength="145" placeholder="留空继承主 Agent 已授权工具"></label>'+
      '<datalist id="workflow-mcp-tools"></datalist>'+
      '<label data-node-config="tool">选择工具<select name="tool" required></select></label>'+
      '<p data-node-config="tool" data-tool-detail class="hint"></p>'+
      '<label data-node-config="tool" class="desktop-flow-check"><input name="required" type="checkbox"> 缺少所需数据时触发失败策略</label>'+
      '<label data-node-config="model">分析模型<select name="model"></select></label>'+
      '<label data-node-config="database">数据来源<select name="source" required></select></label>'+
      '<label data-node-config="tasks">查询类型<select name="query" required></select></label>'+
      '<label data-node-config="tasks">标的范围<select name="scope" required></select></label>'+
      '<label data-node-config="sqlite">已发现的数据库<select data-database-files><option value="">选择已发现的文件</option></select></label>'+
      '<label data-node-config="sqlite">扫描范围<select data-scan-scope><option value="common">常用位置</option>'+
      '<option value="directory">指定目录</option><option value="disks">本机磁盘</option></select></label>'+
      '<label data-node-config="sqlite">目录绝对路径<input data-scan-folder maxlength="1024" placeholder="例如 D:\\data"></label>'+
      '<div data-node-config="sqlite"><button type="button" data-database-refresh>重新扫描</button><p role="status" data-database-scan-status></p></div>'+
      '<label data-node-config="sqlite">SQLite 文件绝对路径<input name="path" maxlength="1024" required></label>'+
      '<div data-node-config="sqlite"><button type="button" data-database-inspect>测试连接</button><p role="status" data-database-status></p></div>'+
      '<label data-node-config="sqlite">数据表<input name="table" list="workflow-database-tables" maxlength="128" required></label>'+
      '<datalist id="workflow-database-tables"></datalist>'+
      '<label data-node-config="sqlite">标的列（可选）<input name="symbol_column" maxlength="128" placeholder="例如 symbol"></label>'+
      '<label data-node-config="database">返回条数<input name="limit" type="number" min="1" step="1" required></label>'+
      '<label data-node-config="database" class="desktop-flow-check"><input name="include_fact" type="checkbox"> 将返回条数作为事实传给下游</label>'+
      '<label>失败处理<select name="failurePolicy"><option value="stop">停止流程</option><option value="degrade">降级继续</option>'+
      '<option value="skip">跳过失败步骤</option></select></label><label class="desktop-flow-check"><input name="enabled" type="checkbox"> 启用此节点</label>';
    const fields=nodeDrafts.get(node.id)||{...node.data,...node.data.config};
    const tools=workflowCatalog?.nodes.tool?.options||{};
    for(const [id,entry] of Object.entries(tools)) form.elements.tool.add(new Option(entry.label,id));
    if(fields.tool) form.elements.tool.value=fields.tool;
    form.elements.required.checked=fields.required===true;
    const types={...TYPE_LABEL,[node.data.type]:TYPE_LABEL[node.data.type]||`${node.data.type}（草稿）`};
    for(const [id,label] of Object.entries(types)) form.elements.type.add(new Option(label,id));
    form.elements.model.add(new Option('继承主 Agent',''));
    for(const model of safeProfiles()) if(model.enabled) form.elements.model.add(new Option(model.name,model.id));
    if(fields.model && ![...form.elements.model.options].some(option=>option.value===fields.model)) form.elements.model.add(new Option('模型已停用或不可用',fields.model));
    const scanDatabases=databaseForm(form,fields,workflowCatalog?.nodes.database?.options);
    for(const key of ['label','type','detail','binding','model','failurePolicy']) form.elements[key].value=fields[key]||'';
    form.elements.enabled.checked=fields.enabled!==false;
    const sync=()=>{
      for(const label of form.querySelectorAll('[data-node-config]')) {
        const key=label.dataset.nodeConfig;
        const type=form.elements.type.value;
        const source=form.elements.source.value;
        const visible={database:type==='database',tasks:type==='database'&&source==='tasks',
          sqlite:type==='database'&&source==='sqlite',binding:type==='retrieval',tool:type==='tool',model:['analysis','merge'].includes(type)};
        label.hidden=!visible[key] || (label.contains(form.querySelector('[data-scan-folder]')) &&
          form.querySelector('[data-scan-scope]').value!=='directory');
        const control=label.querySelector('input,select');
        if(control) control.disabled=label.hidden;
      }
      if(form.elements.type.value==='database' && form.elements.source.value==='sqlite') scanDatabases();
      if(form.elements.type.value==='retrieval') fillMcpTools(form);
      const spec=tools[form.elements.tool.value];
      form.querySelector('[data-tool-detail]').textContent=spec?`${spec.detail}。拦截情形：${spec.requirement}。`:'';
    };
    sync();form.oninput=()=>{
      sync();
      nodeDrafts.set(node.id,{...Object.fromEntries(new FormData(form)),enabled:form.elements.enabled.checked,
        include_fact:form.elements.include_fact.checked,required:form.elements.required.checked});
      dirty=true;persistDraft();updateSaveState();
    };
    form.onsubmit=editNode;
    host.append(form);
    const actions=document.createElement('div');actions.className='desktop-flow-actions';
    actions.append(makeButton('保存节点',()=>form.requestSubmit()),makeButton('复制节点',()=>duplicateNode(node)),makeButton('删除节点',removeNode));
    host.append(actions);
    if(node.data.legacy){
      const previous=document.createElement('details'), summary=document.createElement('summary');
      summary.textContent='旧版配置';previous.append(summary,terms([['原配置',node.data.legacy]]));host.append(previous);
    }
    connectionEditor(host,node);
  }

  function renderInspector() {
    const host=$('desktop-workflow-inspector');
    if (!host || host.contains(document.activeElement) && document.activeElement.closest('form') && host.dataset.node===selected) return;
    host.dataset.node=selected;
    host.replaceChildren();
    const node=nodeById(selected), heading=document.createElement('h3');
    heading.textContent=node?.data.label||'节点详情';host.append(heading);
    const version=shownTask()?.metadata?.workflow?.version;
    if (showingRun()) host.append(terms([['执行版本',version||'旧任务 · 无图版本'],
      ['配置版本',shownTask()?.metadata?.workflow?.configuration_version?.slice(0,12)],
      ['任务状态',shownTask()?.status?.state||'未选择运行']]));
    if(!node) return;
    const spec=workflowCatalog?.nodes[node.data.type], info=runtimeFor(node.id);
    const deps=shownGraph().edges.filter(edge=>edge.target===node.id).map(edge=>nodeById(edge.source)?.data.label||edge.source);
    host.append(terms([['状态',statusText(node.id)],['读取',spec?.input||'任务输入'],['输出类型',spec?.output||'—'],
      ['依赖',deps.join('、')||'入口'],['运行条件',deps.length?'上游完成且连线条件成立':'收到任务输入'],
      ['说明',node.data.detail||spec?.detail],['来源',info.source||spec?.source||'用户草稿'],['耗时',info.duration!=null?`${info.duration} ms`:null],
      ['分支来源',info.branch?.join('、')],['错误或跳过原因',info.failure],['执行尝试',info.attempts||null],['重试次数',info.retries]]));
    if(showingRun()) {
      host.append(terms([['输入摘要',info.input],['输出摘要',info.output]]));
      return;
    }
    if (workSurface==='debug') {
      host.append(makeButton('单测所选节点',()=>openDebug(node)));
      const button=host.lastElementChild;button.disabled=spec?.testable!==true || node.data.enabled===false;
    }
    if (node.data.type==='input') host.append(terms([['输入预览',info.output],['来源',info.source]]));
    if (node.data.type==='retrieval') {
      const market=window.PonyMarketFeed?.current?.(), quote=market?.snapshot;
      host.append(terms([['行情墙参考',quote ? `${quote.source} · ${quote.as_of||'未提供观测时间'} · ${quote.timezone||'未提供时区'} · ${quote.demo?'演示':market.status==='stale'?'已过期':quote.session==='live'&&market.status==='connected'?'实时':'最近快照'}` : '暂无行情']]));
    }
    if (!spec) host.append(terms([['草稿能力','选择有执行器的节点类型，或移除此节点后再运行']]));
    nodeEditor(host,node);
    if (graph.mode!=='system') for (const error of validateGraph().slice(0,6)) {
      const id=error.split(' · ')[0];
      const item=makeButton(error,()=>nodeById(id)&&selectNode(id,true)); item.className='desktop-flow-issue';host.append(item);
    }
  }

  function inputState() { let raw; try { raw = JSON.parse($('task-data').value); if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw Error(); } catch (_) { return {state: 'invalid', field: 'task-data', label: '请修正原始 JSON', detail: '原始输入无法解析，请打开资料检查格式。'}; } const prediction = window.AnalysisInput.currentPrediction(); if (typeof prediction?.subject !== 'string' || !prediction.subject.trim()) return {state: 'empty', label: '填写分析资料', detail: '先填写标的、预测周期和上游模型版本。'}; const result = {prediction, facts: Array.isArray(raw.context?.facts) ? raw.context.facts.length : 0}; if (typeof prediction.model_version !== 'string' || !prediction.model_version.trim()) return {...result, state: 'invalid', field: 'p-model-version', label: '补充模型版本', detail: '请填写这份预测的上游模型版本。'}; if (!(Number.isFinite(prediction.horizon?.value) && prediction.horizon.value > 0)) return {...result, state: 'invalid', field: 'p-horizon-value', label: '核对预测周期', detail: '预测周期需要大于零。'}; if (!(Date.parse(prediction.valid_until) > Date.now())) return {...result, state: 'expired', field: 'p-valid-until', label: '更新过期预测', detail: '预测已过期或缺少有效期，请核对原始资料后更新。'}; if (prediction.confidence != null && !(Number.isFinite(prediction.confidence) && prediction.confidence >= 0 && prediction.confidence <= 1)) return {...result, state: 'invalid', field: 'p-confidence', label: '核对置信度', detail: '置信度须在 0 到 1 之间；上游未提供时可留空。'}; if (raw.context?.facts && (!Array.isArray(raw.context.facts) || raw.context.facts.some(fact => typeof fact?.source !== 'string' || !fact.source.trim() || !Number.isFinite(Date.parse(fact.observed_at))))) return {...result, state: 'invalid', label: '补充事实来源', detail: '每条客观事实都需要来源和有效的观测时间。'}; return {...result, state: 'ready', label: prediction.subject, detail: '主要资料已填写；发送时会再次校验资料、归档和授权。'}; }
  function openData() { origin = document.activeElement?.getClientRects?.().length ? document.activeElement : $('analysis-data-open'); $('prediction-editor').open = true; window.AnalysisInput.open('input'); const target = $('task-form').querySelector('[aria-invalid="true"]') || $(inputState().field || 'p-subject'); for (let parent = target.parentElement; parent && parent !== $('task-form'); parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; target.focus(); target.scrollIntoView({block: 'nearest'}); }
  function openResult() { if (!task) return; origin = document.activeElement; window.AnalysisInput.open(['submitted', 'working'].includes(task.status.state) ? 'progress' : 'report'); $('analysis-tab-' + pane).focus(); }
  function chooseModel() { origin = document.activeElement; if (safeProfiles().some(item => item.enabled && item.id === safeSettings()?.default_model_id)) $('composer-model').click(); else { showView('settings'); showPanel('models'); $('model-name').focus(); } }
  async function sample(event) { if (sampling) return; const button = event.currentTarget, current = safeProfiles().find(item => item.enabled && item.id === safeSettings()?.default_model_id); if (current?.provider !== 'mock' && current && !confirm('准备示例会将工作台默认模型切换为 Mock，并替换当前预测与事实。不会自动提交分析。继续？')) return; if (window.AnalysisInput.currentPrediction()?.subject && (!current || current.provider === 'mock') && !confirm('用合成示例替换当前预测与事实？当前问题会保留，不会自动提交。')) return; sampling = true; button.disabled = true; try { await $('try-sample').onclick(); if ($('task-data').value.includes('console-mock')) { update(); $('conversation-message').focus(); notice('离线示例已准备：默认模型为 Mock，资料为合成资料。输入问题后点击发送。'); } } finally { sampling = false; button.disabled = false; } }

  function runtimeSet(id,status,patch={}) {
    if(status && STATUS_LABEL[status]) runtime.states.set(id,status);
    const values=Object.fromEntries(Object.entries(patch).filter(([,value])=>value!==undefined && value!==null));
    runtime.details.set(id,{...runtimeFor(id),...values});
  }
  function applyEvent(event) {
    if (!event) return;
    if (!runtime.events.some(item=>item.seq && item.seq===event.seq)) runtime.events.push(event);

  }
  function deriveRuntime(nextTask) {
    const id=nextTask?.id||null;
    if (id!==runtime.taskId) {runtime.taskId=id;runtime.events=[];}
    runtime.states.clear();runtime.details.clear();
    if (!showingRun()) {
      const state=inputState();
      runtimeSet('prediction',state.state==='ready'?'completed':'needs_input',{source:state.prediction?.model_version,
        output:state.prediction?.confidence==null?'上游未提供置信度':`上游置信度 ${state.prediction.confidence}`,failure:state.state==='ready'?'':state.detail});
      return;
    }
    const current=shownTask(), events=archived?archivedEvents:runtime.events;
    const custom=current?.metadata?.workflow?.mode==='custom';
    const plan=events.filter(event=>event.kind==='plan').at(-1)?.steps || [];
    const planned=new Set(plan.map(step=>step.id));
    const status=current?.status?.state;
    for(const node of shownGraph().nodes) runtimeSet(node.id, !custom && plan.length && !planned.has(node.data.actualKey) && node.id!=='prediction'
      ?'skipped':status==='working'||status==='submitted'?'waiting':'idle');
    for(const event of events) {
      const id=custom?event.step:CHILDREN[event.step]?'child-'+event.step:STEP_TO_KEY[event.step];
      if(!id) continue;
      if(event.kind==='step' || event.kind==='node_result') runtimeSet(id,event.status,{source:event.source||event.label,input:event.input_summary,
        output:event.summary,failure:event.code||event.reason,duration:event.duration_ms,attempts:event.attempts,retries:event.retries});
      if(event.kind==='branch') runtimeSet(id,null,{branch:event.selected});
      if(event.kind==='tool') runtimeSet(id,null,{attempts:event.attempt||1,failure:event.code});
      if(event.kind==='adjustment' && (event.code||event.step==='main')) runtimeSet(id,'degraded',{failure:event.label});
    }
    if(status==='canceled'||status==='failed') for(const node of shownGraph().nodes) {
      if(statusFor(node.id)==='running') runtimeSet(node.id,status,{failure:current.metadata?.error?.code||'任务已取消'});
    }
    const result=current?.artifacts?.[0]?.parts?.[0]?.data;
    if(result?.analysis && !custom && !events.length) runtimeSet('report','completed',{source:'历史报告产物'});
    if(result?.mail && !custom) runtimeSet('delivery',['sent','simulated'].includes(result.mail.status)?'completed':'degraded',{output:result.mail.status});
    if(result?.analysis?.charts && !custom) runtimeSet('charts',null,{output:`${result.analysis.charts.length} 个报告图表`});
  }

  function graphSubmission(key,debug=null) {
    const draft=debug?customCopy():graph;
    return {mode:draft.mode,key,...(draft.mode==='custom'?{graph:safeLegacy(draft)}:{}),...(debug?{debug}:{})};
  }
  function workflowPayload(request) {
    if(mode!=='focus'||!desktop.matches) return {};
    const serialized=JSON.stringify([request,graph]);
    if(submitBody!==serialized){submitBody=serialized;submitKey=crypto.randomUUID();}
    return {workflow:graphSubmission(submitKey)};
  }
  function acceptWorkflow(value) {
    if(!value?.metadata?.workflow) return;
    submitBody=null;submitKey=null;archived=null;archivedEvents=[];
    task=value;workSurface='run'; deriveRuntime(value);updateWorkspaceTabs();renderCanvas();renderInspector();
  }

  function currentTestInput() {
    const input=JSON.parse($('task-data').value);
    const cid=$('conversation-id').value;
    return {...input,...(cid?{conversation_id:cid}:{}),...window.KnowledgeUI?.selection(),notify:false};
  }
  function explainError(error) {
    const text=error.message||String(error);
    setMessage(text);
    const node=text.split(' · ').map(part=>part.trim()).find(part=>nodeById(part));
    if(node) selectNode(node,true);
  }
  async function previewWorkflow() {
    try {
      const data=currentTestInput();
      const enabled=$('task-notify').checked, recipients=window.MailRecipients?.values()||[];
      const request=data.prediction || data.conversation_id ? {...data,notify:enabled,
        recipient:recipients[0]||$('task-recipient').value||null,recipients} : undefined;
      const result=await api('workflows/preview','POST',{workflow:graphSubmission(crypto.randomUUID()),request});
      const list=result.nodes.map(node=>`${nodeById(node.id)?.data.label||node.id} · ${{ready:'可运行',skip:'跳过',blocked:'受阻',conditional:'待条件'}[node.state]}${node.reason?'（'+node.reason+'）':''}`);
      setMessage('校验通过 · '+result.version.slice(0,8));
      const dialog=document.createElement('dialog');dialog.className='plugin-dialog workflow-run-dialog';
      const heading=document.createElement('h3');heading.textContent='运行前计划';
      dialog.append(heading,terms(list.map(value=>['节点',value])),makeButton('关闭',()=>dialog.close()));
      dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();
    } catch(error){explainError(error);}
  }
  async function loadRun(id) {
    const value=await api('tasks/'+encodeURIComponent(id)), events=[];
    let after=0;
    for(;;) {
      const page=await api(`tasks/${encodeURIComponent(id)}/events?after=${after}`);
      events.push(...page.events);
      if(page.events.length<100) break;
      after=page.events.at(-1).seq;
    }
    return {value,events};
  }
  function showRun(value,events) {
    archived=value;archivedEvents=events;workSurface='run';selected=shownGraph().nodes[0]?.id||'';
    deriveRuntime(task);updateWorkspaceTabs();renderCanvas();renderInspector();
  }
  async function chooseRun() {
    const dialog=document.createElement('dialog');dialog.className='plugin-dialog workflow-run-dialog';
    const heading=document.createElement('h3');heading.textContent='运行记录';dialog.append(heading);
    const list=document.createElement('div');list.className='workflow-run-list';
    let cursor=null;
    const next=makeButton('加载更早记录',()=>read());
    async function read() {
      next.disabled=true;
      try {
        const data=await api('workflows/runs'+(cursor?'?before='+cursor:''));
        for(const item of data.items) {
          list.append(makeButton(`${item.debug?'单节点调试':item.subject||'任务'} · ${item.status.state} · ${item.version?.slice(0,8)||'旧任务'} · ${item.status.timestamp}`,async()=>{
            try {const run=await loadRun(item.id);dialog.close();showRun(run.value,run.events);} catch(error){explainError(error);}
          }));
        }
        if(!list.childElementCount) list.textContent='暂无运行记录';
        cursor=data.next_before;next.hidden=!cursor;
      } catch(error){list.append(document.createTextNode(error.message));}
      finally{next.disabled=false;}
    }
    dialog.append(list,next,makeButton('关闭',()=>dialog.close()));
    dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();await read();
  }

  function workflowLibrary() {
    const dialog=document.createElement('dialog');dialog.className='plugin-dialog workflow-run-dialog';
    const title=document.createElement('h3');title.textContent='自定义流程';
    const form=document.createElement('form');
    form.innerHTML='<label>流程名称<input name="label" maxlength="50" required></label><button type="submit">另存当前流程</button><p role="status"></p>';
    const list=document.createElement('div');list.className='workflow-run-list';
    let records;
    try {records=JSON.parse(localStorage.getItem(libraryKey)||'[]');} catch(_){records=[];}
    for(const entry of records) {
      list.append(makeButton(entry.label,()=>{
        if (dirty && !confirm('打开其他流程会替换当前草稿。继续吗？')) return;
        try {
          history.push(clone(graph));graph=normalizeGraph(entry.graph);nodeDrafts.clear();dirty=true;workSurface='edit';
          selected=graph.nodes[0].id;dialog.close();persistDraft();updateWorkspaceTabs();renderCanvas();renderInspector();
        } catch(error){form.querySelector('[role=status]').textContent=error.message;}
      }));
    }
    form.onsubmit=event=>{
      event.preventDefault();
      const label=form.elements.label.value.trim();
      if (!label) return;
      try {
        const saved={label,graph:safeLegacy(customCopy())};
        localStorage.setItem(libraryKey,JSON.stringify([saved,...records.filter(entry=>entry.label!==label)].slice(0,20)));
        dialog.close();setMessage('已另存自定义流程 '+label);
      } catch(error){form.querySelector('[role=status]').textContent='无法保存流程 · '+error.message;}
    };
    dialog.append(title,list,form,makeButton('关闭',()=>dialog.close()));dialog.onclose=()=>dialog.remove();
    document.body.append(dialog);dialog.showModal();
  }
  function openDebug(node) {
    if(debugDialog?.open) return;
    const dialog=document.createElement('dialog');debugDialog=dialog;dialog.className='plugin-dialog workflow-run-dialog';
    dialog.innerHTML='<form><h3></h3><label>测试任务 JSON<textarea name="request" rows="10" required></textarea></label>'+
      '<p class="hint">使用输入运行本次调试所依赖的上游节点。归档和投递在调试中跳过。</p>'+
      '<button type="submit">运行节点测试</button><button type="button" data-close>关闭</button><p role="status"></p></form>';
    const form=dialog.querySelector('form'), status=dialog.querySelector('[role=status]');
    dialog.querySelector('h3').textContent='单节点调试 · '+node.data.label;
    try {form.elements.request.value=JSON.stringify(currentTestInput(),null,2);} catch(_){form.elements.request.value='{}';}
    let currentId=null, frozenKey=null, previous=null;
    const cancel=makeButton('取消调试',async()=>{
      try {if(currentId) await api(`tasks/${currentId}/cancel`,'POST',{});} catch(error){status.textContent=error.message;}
    });
    cancel.disabled=true;
    form.append(cancel);
    dialog.querySelector('[data-close]').onclick=()=>dialog.close();
    form.onsubmit=async event=>{
      event.preventDefault();const submit=form.querySelector('[type=submit]');submit.disabled=true;
      try {
        const raw=JSON.parse(form.elements.request.value), text=form.elements.request.value;
        if(previous!==text){previous=text;frozenKey=crypto.randomUUID();}
        const created=await api('tasks','POST',{...raw,workflow:graphSubmission(frozenKey,node.id)});
        currentId=created.id;cancel.disabled=false;status.textContent='调试执行中';
        let record=await loadRun(currentId);
        while (dialog.open && ['submitted','working'].includes(record.value.status.state)) {
          await new Promise(resolve=>setTimeout(resolve,400));record=await loadRun(currentId);
        }
        if(dialog.open){dialog.close();showRun(record.value,record.events);selected=node.id;renderCanvas();renderInspector();}
      } catch(error){status.textContent=error.message;}
      finally{submit.disabled=false;cancel.disabled=true;}
    };
    dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();
  }
  function updateWorkspaceTabs() {
    for(const button of focus.querySelectorAll('[data-workflow-surface]')) button.setAttribute('aria-pressed',String(button.dataset.workflowSurface===workSurface));
    focus.dataset.workflowSurface=workSurface;
    for(const button of focus.querySelectorAll('[data-workflow-action]')) button.hidden=showingRun();
    focus.querySelector('.desktop-flow-palette').hidden=showingRun();
  }
  function workflowControls() {
    const toolbar=focus.querySelector('.desktop-flow-toolbar-actions');
    for (const [key,label] of [['edit','编辑'],['debug','调试'],['run','运行记录']]) {
      const button=makeButton(label,()=>{
        if(key==='run'){chooseRun();return;}
        archived=null;archivedEvents=[];workSurface=key;
        if(!nodeById(selected)) selected=graph.nodes[0]?.id||'';
        deriveRuntime(task);updateWorkspaceTabs();renderCanvas();renderInspector();
      });
      button.dataset.workflowSurface=key;toolbar.insertBefore(button,toolbar.querySelector('[data-workflow-action]'));
    }
    const copy=makeButton('复制系统模板',()=>{
      history.push(clone(graph));graph=customCopy(defaultGraph());selected=graph.nodes[0].id;dirty=true;nodeDrafts.clear();
      persistDraft();setMessage('模板副本可编辑并执行');renderCanvas();renderInspector();
    });
    copy.dataset.workflowAction='copy';
    toolbar.prepend(makeButton('校验计划',previewWorkflow),copy,makeButton('自定义流程',workflowLibrary));
    toolbar.prepend(makeButton('运行流程',()=>$('task-form').requestSubmit()));
    const palette=focus.querySelector('.desktop-flow-palette'), search=document.createElement('input');
    search.type='search';search.placeholder='搜索节点';search.setAttribute('aria-label','搜索节点库');palette.insertBefore(search,palette.querySelector('button'));
    search.oninput=()=>{for(const button of palette.querySelectorAll('[data-node-type]')) button.hidden=!button.textContent.includes(search.value.trim());};
    updateWorkspaceTabs();
    api('workflows/catalog').then(data=>{
      workflowCatalog=data;systemTemplate=data.system;
      if(graph.mode==='system' && !dirty){
        graph=savedGraph=defaultGraph();
        requestAnimationFrame(()=>{if(mode==='focus' && !localStorage.getItem('stock_predict_mailer.desktop.canvas.zoom.v1')) fitCanvas();});
      }
      renderCanvas();renderInspector();
    }).catch(error=>setMessage('流程登记表读取失败 · '+error.message));
  }

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
    const nodes=shownGraph().nodes;
    if (!canvas.clientWidth || !canvas.clientHeight || !nodes.length) return;
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const node of nodes) {
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
    const palette=focus.querySelector('.desktop-flow-palette').getBoundingClientRect();
    const viewLeft = Math.max(20,palette.right-rect.left+12), viewTop = Math.max(20, toolbarBottom + 16);
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
    installEdgeDragging(canvas);
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
      if (event.button !== 0 || canvasDrag || edgeDrag || event.target.closest('.desktop-flow-edge, [data-edge-end]')) return;
      const element = event.target.closest('.desktop-flow-node');
      if (element && showingRun()) {selectNode(element.dataset.workflowNode,true);return;}
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
      if (!canvasDrag && !edgeDrag) canvasZoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12, canvasPoint(canvas, event));
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

  function install() { if (!desktop.matches) { moveComposer(false); navCollapse?.remove(); navCollapse = null; navFocus?.remove(); navFocus = null; navHall?.remove(); navHall = null; modeSwitch?.remove(); modeSwitch = null; document.body.classList.remove('desktop-nav-collapsed'); if (root) { root.hidden = focus.hidden = feedback.hidden = true; document.body.classList.remove('desktop-workbench', 'desktop-focus-view'); office.querySelector('.office-stage').inert = false; office.querySelector('.market-wall')?.removeAttribute('inert'); clearTimeout(expiry); expiresAt = 0; statusParent.insertBefore($('task-status'), statusNext); $('analysis-composer').classList.remove('desktop-history-open'); inspectorTitle.textContent = originalTitle; document.querySelectorAll('.nav [aria-current]').forEach(button => button.removeAttribute('aria-current')); window.AnalysisInput.layout(); } return; } if (!root) { root = document.createElement('section'); root.id = 'desktop-workflow'; root.setAttribute('aria-label', '分析流程'); root.innerHTML = `<div class="desktop-workflow-heading"><div><h1 id="desktop-title"></h1><p id="desktop-subtitle"></p></div></div><div class="desktop-workflow-actions"><button type="button" id="desktop-model"><span class="desktop-step">1 · 模型</span><strong id="desktop-model-value"></strong></button><button type="button" id="desktop-data"><span class="desktop-step">2 · 资料</span><strong id="desktop-data-value"></strong></button><button type="button" id="desktop-result"><span class="desktop-step">3 · 结果</span><strong id="desktop-result-value"></strong></button></div>`; focus = document.createElement('section'); focus.id = 'desktop-focus'; focus.setAttribute('aria-label', '可编辑分析工作流'); focus.innerHTML = `<div class="desktop-focus-intro"><p class="eyebrow">本轮分析工作流</p><h2 id="desktop-focus-title"></h2><p id="desktop-focus-copy"></p><div class="desktop-focus-actions"><button type="button" id="desktop-focus-data" class="btn primary">填写 / 修改资料</button><button type="button" id="desktop-sample" class="btn">准备离线示例</button></div><p class="hint desktop-sample-note">离线示例会将默认模型设为 Mock 并填入 synthetic 资料，准备后仍需手动发送。</p></div><div class="desktop-flow-toolbar"><div class="desktop-flow-toolbar-status"><strong>可视化流程</strong><span id="desktop-workflow-message" role="status" aria-live="polite">选择节点查看详情。</span></div><div class="desktop-flow-toolbar-actions"><span id="desktop-workflow-validation"></span><button type="button" data-workflow-action="add">新增节点</button><button type="button" data-workflow-action="undo" id="desktop-workflow-undo">撤销</button><button type="button" data-workflow-action="save" id="desktop-workflow-save">保存流程</button><button type="button" data-workflow-action="restore">恢复默认</button><button type="button" data-workflow-action="import">导入</button><button type="button" data-workflow-action="export">导出</button><div class="desktop-flow-viewport-tools" role="group" aria-label="画布视图控制"><button type="button" data-viewport-action="zoom-out" aria-label="缩小画布">−</button><span id="desktop-workflow-zoom">72%</span><button type="button" data-viewport-action="zoom-in" aria-label="放大画布">+</button><button type="button" data-viewport-action="fit" aria-label="适配画布">适配</button></div><input id="desktop-workflow-file" type="file" accept="application/json,.json" hidden></div></div><div class="desktop-flow-layout"><div class="desktop-flow-canvas" id="desktop-workflow-canvas" role="application" aria-label="分析工作流画布"><svg id="desktop-workflow-edges" aria-label="工作流连线"><defs><marker id="desktop-flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs><g id="desktop-workflow-edge-paths"></g></svg><div class="desktop-flow-surface" id="desktop-workflow-surface"><div id="desktop-workflow-nodes"></div></div></div><aside class="desktop-flow-inspector" id="desktop-workflow-inspector" aria-label="节点详情"></aside></div><dl class="desktop-summary"><div><dt>分析模型</dt><dd id="desktop-summary-model"></dd></div><div><dt>预测周期</dt><dd id="desktop-summary-prediction"></dd></div><div><dt>客观事实</dt><dd id="desktop-summary-facts"></dd></div><div><dt>本轮通知</dt><dd id="desktop-summary-mail"></dd></div></dl>`; const intro = focus.querySelector('.desktop-focus-intro'); if (intro) intro.hidden = true; const focusData = focus.querySelector('#desktop-focus-data'); if (focusData) focus.querySelector('.desktop-flow-toolbar')?.prepend(focusData); const summary = focus.querySelector('.desktop-summary'); if (summary) summary.hidden = true; feedback = document.createElement('div'); feedback.id = 'desktop-feedback'; feedback.innerHTML = '<span id="desktop-feedback-text" role="status" aria-live="polite"></span><button type="button" id="desktop-feedback-action"></button><button type="button" id="desktop-history" aria-controls="conversation-thread" aria-expanded="false" hidden></button><span class="desktop-send-hint">Enter 发送 · Shift+Enter 换行</span>'; office.prepend(root, focus); modeSwitch = document.createElement('div'); modeSwitch.className = 'desktop-mode-switch'; modeSwitch.setAttribute('role', 'group'); modeSwitch.setAttribute('aria-label', '界面模式'); for (const [value, text] of [['hall', '普通'], ['focus', '专业']]) { const node = document.createElement('button'); node.type = 'button'; node.textContent = text; node.dataset.desktopMode = value; node.onclick = () => setMode(value); modeSwitch.append(node); } document.querySelector('.nav')?.append(modeSwitch); if (!focus.querySelector('.desktop-flow-palette')) { const palette = document.createElement('aside'); palette.className = 'desktop-flow-palette'; palette.setAttribute('aria-label', '节点库'); const heading = document.createElement('p'); heading.className = 'eyebrow'; heading.textContent = '节点库'; palette.append(heading); for (const [type, [label]] of Object.entries(TYPE_DEFAULTS)) { const item = document.createElement('button'); item.type = 'button'; item.dataset.nodeType = type; item.title = `添加${label}节点`; const dot = document.createElement('i'); dot.setAttribute('aria-hidden', 'true'); dot.style.background = TYPE_COLOR[type] || TYPE_COLOR.custom; item.append(dot, document.createTextNode(label)); item.onclick = () => type === 'trained' ? addTrainedNode() : addNode(type); palette.append(item); } focus.querySelector('.desktop-flow-layout')?.prepend(palette); } navCollapse = document.createElement('button'); navCollapse.type = 'button'; navCollapse.className = 'desktop-nav-collapse'; navCollapse.onclick = () => setNavCollapsed(!document.body.classList.contains('desktop-nav-collapsed')); document.querySelector('.topbar')?.insertBefore(navCollapse, document.querySelector('.nav')); installNavIcons(); setNavCollapsed(navCollapsed()); $('analysis-composer').prepend(feedback); $('desktop-data').onclick = $('desktop-focus-data').onclick = openData; $('desktop-model').onclick = chooseModel; $('desktop-result').onclick = openResult; $('desktop-sample').onclick = sample; $('desktop-history').onclick = () => historyPanel(!$('analysis-composer').classList.contains('desktop-history-open')); root.querySelectorAll('[data-desktop-mode]').forEach(button => { button.onclick = () => setMode(button.dataset.desktopMode); }); focus.querySelectorAll('[data-workflow-action]').forEach(button => { button.onclick = () => ({add: addNode, undo, save: saveWorkflow, restore: restoreDefault, import: () => $('desktop-workflow-file').click(), export: exportWorkflow}[button.dataset.workflowAction])(); }); focus.querySelectorAll('[data-viewport-action]').forEach(button => { button.onclick = () => button.dataset.viewportAction === 'fit' ? fitCanvas() : canvasZoomBy(button.dataset.viewportAction === 'zoom-in' ? 1.15 : 1 / 1.15); }); installCanvasInteractions(); workflowControls(); $('desktop-workflow-file').addEventListener('change', importWorkflow); $('report-close').addEventListener('click', returnFocus); new MutationObserver(() => historyPanel()).observe($('conversation-turns'), {childList: true}); document.addEventListener('pointerdown', event => { if (desktop.matches && !$('analysis-composer').contains(event.target)) historyPanel(false); }); document.addEventListener('keydown', event => { if (window.DesktopInteractions?.active?.()) return; if (desktop.matches && event.key === 'Escape' && $('analysis-composer').classList.contains('desktop-history-open')) { event.preventDefault(); event.stopImmediatePropagation(); historyPanel(false); $('desktop-history').focus(); } }, true); $('task-form').addEventListener('submit', () => historyPanel(false));  const toolbar = focus.querySelector('.desktop-flow-toolbar'); const resize = new ResizeObserver(() => { if (!desktop.matches) return; focus.style.setProperty('--desktop-flow-toolbar-height', toolbar.offsetHeight + 'px'); const height = root.offsetHeight + 'px'; if (office.style.getPropertyValue('--desktop-workflow-height') !== height) { office.style.setProperty('--desktop-workflow-height', height); document.documentElement.style.setProperty('--desktop-workflow-height', height); window.AnalysisInput.layout(); } renderEdges(); }); resize.observe(root); resize.observe(toolbar); window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } }); document.addEventListener('click', event => { const target = event.target.closest?.('.nav [data-view], #new-analysis'); if (target && dirty && target.dataset.view !== 'analysis' && !confirm('当前工作流尚未保存，离开后编辑内容会保留在本机草稿中。继续吗？')) { event.preventDefault(); event.stopImmediatePropagation(); } }, true); } root.hidden = focus.hidden = feedback.hidden = false; if (navFocus) { navFocus.hidden = document.body.dataset.view !== 'analysis'; navFocus.setAttribute('aria-pressed', String(mode === 'focus')); } if (navHall) { navHall.hidden = document.body.dataset.view !== 'analysis'; navHall.setAttribute('aria-pressed', String(mode === 'hall')); } $('analysis-pane-progress').prepend($('task-status')); document.body.classList.add('desktop-workbench'); setMode(mode); panel(pane); update(); }
  desktop.addEventListener('change', install); new MutationObserver(update).observe(document.body, {attributes: true, attributeFilter: ['data-view']}); document.addEventListener('visibilitychange', () => { if (!document.hidden) update(); }); window.addEventListener('focus', update); install();
  return {update, panel, setMode, addBuiltinTool, workflowPayload, acceptWorkflow, explainError, mode: () => mode, observeProgressTask(value) {task=value;deriveRuntime(task);}, observe(value) { task = value; update(); }, event: applyEvent, connectionLost(value) { disconnected = value; update(); }, selectionState() { update(); }, reset() { task = null; archived=null; archivedEvents=[]; workSurface='edit'; if(focus)updateWorkspaceTabs(); disconnected = false; runtime.taskId = null; runtime.events=[]; runtime.states.clear(); runtime.details.clear(); update(); }};
})();
