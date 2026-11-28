/* Desktop professional workflow canvas. Mobile keeps the original shell. */
window.DesktopWorkbench = (() => {
  const desktop = matchMedia('(min-width: 761px)');
  const NodeUI = window.WorkflowNodeUI;
  const CanvasUI = window.WorkflowCanvasUI;

  const professional = 'professional';
  const legacyWorkflowKey = 'stock_predict_mailer.desktop.workflow.v1';
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
  const nodeDrafts = new Map();
  let workflowCatalog = null, workSurface = 'edit', archived = null, archivedEvents = [], submitKey = null, submitBody = null;
  let catalogLoading = false, catalogFailed = false;
  let systemTemplate = null, debugDialog = null, selectingPort = null;
  let canvasUI, pickerPlacement, replacement;
  let selectedEdge = null, edgeDrag = null;
  const narrowCanvas = matchMedia('(max-width: 1050px)');
  let libraryOpen = !narrowCanvas.matches, inspectorOpen = !narrowCanvas.matches;
  let inspectorTab = 'config', editorView = null;

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
  let history = [], redoHistory = [], message = '', canvasPan = defaultCanvasPan(), canvasZoom = .72, canvasDrag = null, composerParent = null;
  const runtime = {taskId: null, states: new Map(), details: new Map(), events: []};
  let archivedId = null, debugNode = null;
  let definition = null, lastRun = null, lastRunRequest = 0, lastRunTimer, recordRequest = 0, blankCanvas = false;
  let workspaceLoaded = false, hasViewport = false;
  const read = key => AnalysisMode.read(key, professional);
  const write = (key, value) => AnalysisMode.write(key, value, professional);
  const canvasKey = key => definition ? [key, definition.id, definition.revision].join('.') : blankCanvas ? key+'.blank' : key;
  const nodeRunKey = () => definition ? 'node-run-ids.'+definition.id : canvasKey('node-run-ids');
  function restoreWorkspace() {
    if (workspaceLoaded) return;
    workspaceLoaded = true;
    AnalysisMode.importLegacy('active-mode', 'shared', 'stock_predict_mailer.desktop.view.v1', value => value === 'hall' ? 'standard' : professional);
    AnalysisMode.importLegacy('workflow', professional, legacyWorkflowKey);
    AnalysisMode.importLegacy('workflow-draft', professional, legacyWorkflowKey + '.draft');
    AnalysisMode.importLegacy('workflow-library', professional, legacyWorkflowKey + '.library');
    AnalysisMode.importLegacy('canvas-pan', professional, 'stock_predict_mailer.desktop.canvas.pan.v1');
    AnalysisMode.importLegacy('canvas-zoom', professional, 'stock_predict_mailer.desktop.canvas.zoom.v1', Number);
    definition = read('canvas-definition');
    blankCanvas = Boolean(read('canvas-blank'));
    restoreCanvas();
    const initial = AnalysisMode.read('active-mode', 'shared') || (desktop.matches ? professional : 'standard');
    AnalysisMode.activate(initial);
    setMode(initial === professional ? 'focus' : 'hall', {boot:true});
    if (focus) { updateWorkspaceTabs(); update(); }
  }

  function restoreCanvas() {
    clearTimeout(lastRunTimer);lastRun=null;++lastRunRequest;++recordRequest;
    canvasPan = defaultCanvasPan(); canvasZoom = .72; hasViewport = false;
    savedGraph = definition ? normalizeGraph({...definition.graph, mode:definition.mode}) :
      blankCanvas ? {version:2,mode:'custom',nodes:[],edges:[]} : defaultGraph();
    graph = clone(savedGraph); nodeDrafts.clear();
    for(const [key,value] of definition?.draft_edits || [])nodeDrafts.set(key,value);
    history = []; redoHistory = []; dirty = false;
    selected = graph.nodes[0]?.id || ''; selectedEdge = null; workSurface = 'edit'; archivedId = debugNode = null;
    inspectorTab = 'config'; libraryOpen = inspectorOpen = !narrowCanvas.matches; editorView=null;message = '';
    try {
      const pan = read(canvasKey('canvas-pan')), zoom = read(canvasKey('canvas-zoom'));
      if (Number.isFinite(pan?.x) && Number.isFinite(pan.y)) canvasPan = pan;
      if (zoom > 0 && zoom <= 1.6) { canvasZoom = zoom; hasViewport = true; }
      const stored = read(canvasKey('workflow')), draft = read(canvasKey('workflow-draft'));
      if (stored) savedGraph = normalizeGraph(stored);
      graph = draft?.graph ? normalizeGraph(draft.graph) : clone(savedGraph);
      if(draft)nodeDrafts.clear();
      for (const [key, value] of draft?.fields || []) nodeDrafts.set(key, value);
      history = Array.isArray(draft?.history) ? draft.history : [];
      redoHistory = Array.isArray(draft?.redo) ? draft.redo : [];
      dirty = JSON.stringify(graph) !== JSON.stringify(savedGraph) ||
        JSON.stringify([...nodeDrafts])!==JSON.stringify(definition?.draft_edits || []);
      const ui = read(canvasKey('workflow-ui'));
      if (ui) {
        ({workSurface, selected, selectedEdge, inspectorTab, libraryOpen, inspectorOpen, archivedId, debugNode, message} = ui);
        editorView=ui.editorView || null;
      }
    } catch (_) { /* Invalid or unavailable local storage keeps system defaults. */ }
  }

  const NAV_ICONS = {'new-analysis': '+', analysis: '⌂', knowledge: '▦', records: '▤', overview: '?', settings: '⚙', tools: '✦', memory: '◌'};
  const navCollapsed = () => { try { return localStorage.getItem('stock_predict_mailer.desktop.nav.collapsed.v1') === '1'; } catch (_) { return false; } };

  const put = (id, value) => { const node = $(id); if (node && node.textContent !== value) node.textContent = value; };
  const safeProfiles = () => { try { return profiles; } catch (_) { return []; } };
  const shownTask = () => archived || task;
  const showingRun = () => workSurface === 'run';
  const nodeById = id => shownGraph().nodes.find(node => node.id === id);
  const runtimeFor = id => runtime.details.get(id) || {};
  const statusFor = id => runtime.states.get(id) || 'idle';
  const statusText = id => STATUS_LABEL[statusFor(id)] || STATUS_LABEL.idle;
  const nodeTypeLabel = kind => NodeUI.label(kind) || workflowCatalog?.nodes[kind]?.label || kind || '';

  function safeLegacy(value) {
    if (Array.isArray(value)) return value.map(safeLegacy);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
      .filter(([key]) => !/(token|secret|password|api.?key|authorization|headers|env)/i.test(key))
      .map(([key,item]) => [key,safeLegacy(item)]));
    return value;
  }

  function normalizeGraph(raw) {
    if (!raw || ![1,2].includes(raw.version) || !Array.isArray(raw.nodes) || !Array.isArray(raw.edges) ||
        raw.nodes.length > 24 || raw.edges.length > 64) throw Error('流程文件版本、节点或连线数量无效');
    const coord = value => Number.isFinite(Number(value)) ? Number(value) : 0;
    const nodes = raw.nodes.map(node => {
      if (!node || typeof node.id !== 'string' || !node.data || typeof node.data !== 'object') throw Error('流程文件中有无效节点');
      const data = node.data;
      const fallback = {validate:'validation',tools:'retrieval',main:'analysis',charts:'chart',report:'report',mail:'delivery'};
      const type = raw.version === 1 ? fallback[data.actualKey] || String(data.type || 'custom') : String(data.type || 'custom');
      const fields = type==='database' ? {source:'string',query:'string',scope:'string',path:'string',table:'string',
        symbol_column:'string',limit:'number',include_fact:'boolean'} : type==='tool' ? {tool:'string',required:'boolean'} :
        ['chart','report'].includes(type) ? {renderer:'string'} : type==='analysis' ? {model:'string',instruction:'string'} : {model:'string',binding:'string'};
      const variable = NodeUI.variableTypes.includes(type) ||
        type === 'input' && Array.isArray(data.config?.fields) || type === 'knowledge' && 'source' in (data.config || {});
      const config = variable ? clone(data.config || {}) : Object.fromEntries(Object.entries(fields)
        .filter(([key,kind])=>typeof data.config?.[key]===kind).map(([key]) => [key,data.config[key]]));
      if(type==='analysis' && Array.isArray(data.config?.tools))config.tools=[...data.config.tools];
      return {id:node.id.trim(), position:{x:coord(node.position?.x),y:coord(node.position?.y)}, data:{
        label:String(data.label||'未命名节点'), type, detail:String(data.detail||''), actualKey:data.actualKey||null,
        enabled:data.enabled!==false, failurePolicy:data.failurePolicy==='report'?'stop':data.failurePolicy||'stop', config,
        ...(data.modelVersion?{modelVersion:data.modelVersion}:{}),
        ...(raw.version===1 || data.legacy || ['model','trained','review','custom'].includes(type) || !variable && !Object.hasOwn(TYPE_LABEL,type) ?
          {legacy:safeLegacy(data.legacy || data)} : {})
      }};
    });
    const edges = raw.edges.map(edge=>{
      if (!edge || typeof edge.source!=='string' || typeof edge.target!=='string') throw Error('流程文件中有无效连线');
      return {id:String(edge.id||[edge.source,edge.output,edge.target,edge.input,edge.field].filter(Boolean).join('-')),source:edge.source,target:edge.target,
        condition:edge.condition||'always', ...(edge.input?{input:edge.input}:{}), ...(edge.output?{output:edge.output}:{}), ...(edge.field?{field:edge.field}:{})};
    });
    const canvas=CanvasUI.normalize(raw.canvas);
    return {version:2, mode:raw.mode==='system'?'system':'custom',nodes,edges,...(canvas?{canvas}:{})};
  }

  let diagnostics=[], checkedGraph=null, validationTimer, validationRequest=0, issuesDialog=null;
  function localIssues() {
    if(graph.mode==='system')return [];
    const result=[], variables=NodeUI.isVariable(graph);
    for(const [index,edge] of graph.edges.entries()) {
      const from=nodeById(edge.source), to=nodeById(edge.target);
      const location={edge:edge.id,edge_index:index,node:edge.target,source:edge.source,input:edge.input||'value',output:edge.output||'value',severity:'error'};
      if(!draftCompatibility(from,to,location.output,location.input,variables))
        result.push({...location,message:'端口不匹配或已删除'});
      if(wouldCycle(edge.source,edge.target,edge.id))
        result.push({...location,message:'此连线形成循环依赖'});
    }
    return result;
  }
  const pendingIssues=()=>[...nodeDrafts.keys()].filter(id=>nodeById(id))
    .map(node=>({severity:'error',node,message:'此节点还有待提交的配置，请保存节点参数。'}));
  const activeIssues=()=>[...(checkedGraph===graph?diagnostics:localIssues()),...pendingIssues()];
  const issueLabel=item=>{
    const node=nodeById(item.node)?.data.label, origin=nodeById(item.source)?.data.label;
    const location=origin && node ? origin+'.'+item.output+' → '+node+'.'+item.input : node;
    return [item.severity==='warning'?'提醒':'错误',location,item.message].filter(Boolean).join(' · ');
  };
  function issueButton(item) {
    const button=makeButton(issueLabel(item),()=>{
      if(issuesDialog?.open)issuesDialog.close();
      locateIssue(item);
    });
    button.className='desktop-flow-issue';button.dataset.severity=item.severity;
    return button;
  }
  function locateIssue(item) {
    const edge=graph.edges.find(link=>link.id===item.edge) || graph.edges[item.edge_index];
    const node=nodeById(item.node) || (edge && nodeById(edge.source));
    if(!node)return;
    inspectorTab='config';
    if(edge)selectedEdge=edge.id;
    focusDownstream(node.id);
    explainError(Error(item.node+' · '+item.message));
    const row=edge && $('desktop-node-config').querySelector('[data-connection-id="'+CSS.escape(edge.id)+'"]');
    if(row) {
      row.setAttribute('data-located','');
      row.scrollIntoView({block:'nearest'});row.querySelector('button')?.focus({preventScroll:true});
    }
  }
  function markIssues() {
    if(!focus || showingRun())return;
    const issues=activeIssues(), errors=issues.filter(item=>item.severity==='error');
    const indicator=$('desktop-workflow-validation');
    if(indicator) {
      indicator.dataset.state=errors.length?'invalid':'valid';
      indicator.textContent=errors.length+' 错误 · '+(issues.length-errors.length)+' 提醒';
    }
    const badNodes=new Set(errors.flatMap(item=>[item.node,item.source]).filter(Boolean));
    for(const card of focus.querySelectorAll('[data-workflow-node]')) {
      const id=card.dataset.workflowNode, bad=badNodes.has(id);
      card.toggleAttribute('data-invalid',bad);
      const mark=card.querySelector('.workflow-node-invalid');
      if(mark)mark.hidden=!bad;
      for(const port of card.querySelectorAll('.desktop-flow-port')) {
        const invalid=errors.some(item=>port.classList.contains('in')?
          item.node===id && item.input===port.dataset.port:item.source===id && item.output===port.dataset.port);
        port.toggleAttribute('data-invalid',invalid);
        if(invalid)port.setAttribute('aria-invalid','true');else port.removeAttribute('aria-invalid');
      }
    }
    const invalid=new Set(errors.map(item=>item.edge || graph.edges[item.edge_index]?.id).filter(Boolean));
    for(const line of focus.querySelectorAll('[data-edge-id]')) {
      line.toggleAttribute('data-invalid',invalid.has(line.dataset.edgeId));
      let title=line.querySelector('title');
      const issue=errors.find(item=>(item.edge || graph.edges[item.edge_index]?.id)===line.dataset.edgeId);
      if(issue && !title) {title=document.createElementNS(line.namespaceURI,'title');line.append(title);}
      if(title)title.textContent=issue?.message || '';
    }
    const panel=$('workflow-node-issues');
    if(panel) {
      const relevant=issues.filter(item=>item.node===selected || item.source===selected);
      const signature=JSON.stringify(relevant);
      if(panel.dataset.signature!==signature) {
        panel.dataset.signature=signature;panel.replaceChildren();
        if(relevant.length) {
          text(panel,'h4','校验问题');
          panel.append(...relevant.map(issueButton));
        }
        panel.hidden=!relevant.length;
      }
    }
  }
  function showIssues(items=activeIssues()) {
    if(issuesDialog?.open)issuesDialog.close();
    const dialog=document.createElement('dialog');dialog.className='plugin-dialog workflow-run-dialog workflow-issues';
    dialog.setAttribute('aria-label','流程校验结果');
    text(dialog,'h3','流程校验');
    if(items.length)dialog.append(...items.map(issueButton));
    else text(dialog,'p','校验通过，可以运行。');
    dialog.append(makeButton('关闭',()=>dialog.close()));
    dialog.onclose=()=>{dialog.remove();if(issuesDialog===dialog)issuesDialog=null;};
    issuesDialog=dialog;document.body.append(dialog);dialog.showModal();
  }
  async function checkWorkflow({show=false, requireClean=false}={}) {
    clearTimeout(validationTimer);
    const id=++validationRequest, source=graph, scope=AnalysisMode.capture();
    try {
      const data={workflow:graphSubmission(crypto.randomUUID())};
      const model=AnalysisMode.read('model');
      if(model)data.model_id=model;
      if(AnalysisMode.read('tools'))data.tools=AnalysisMode.tools();
      const result=await api('workflows/validate','POST',data,undefined,scope);
      if(!AnalysisMode.current(scope) || graph!==source || id!==validationRequest || showingRun())return false;
      checkedGraph=source;diagnostics=result.issues;markIssues();
      const items=activeIssues(), valid=!items.some(item=>item.severity==='error');
      if(show || requireClean && !valid)showIssues(items);
      return valid;
    } catch(error) {
      if(AnalysisMode.current(scope) && graph===source && (show || requireClean)) {
        showIssues([{severity:'error',message:error.message}]);
      }
      return false;
    }
  }
  function scheduleValidation() {
    if(checkedGraph===graph || !workflowCatalog || showingRun() || AnalysisMode.active()!==professional ||
        !document.body.classList.contains('workflow-mobile-canvas'))return;
    clearTimeout(validationTimer);
    validationTimer=setTimeout(()=>checkWorkflow(),220);
  }

  function persistDraft() {
    write(canvasKey('workflow-draft'), {graph, fields:[...nodeDrafts], history:history.slice(-20), redo:redoHistory.slice(-20)});
  }
  function persistUI() {
    write(canvasKey('workflow-ui'), {workSurface, selected, selectedEdge, inspectorTab, libraryOpen, inspectorOpen, archivedId, debugNode, editorView, message});
  }

  function enterRunSurface() {
    if(!showingRun()) editorView={selected,selectedEdge,inspectorOpen,inspectorTab,canvasPan,canvasZoom};
    workSurface='run';
  }
  function restoreEditorView() {
    if(!editorView)return;
    ({selected,selectedEdge,inspectorOpen,inspectorTab,canvasPan,canvasZoom}=editorView);
    if(inspectorOpen && narrowCanvas.matches) libraryOpen=false;
    editorView=null;applyCanvasViewport();saveCanvasViewport();
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

  function compatible(source, targetType, port, variables=NodeUI.isVariable(graph)) {
    const spec=workflowCatalog?.nodes;
    if (variables) return targetType!=='input' && spec?.[targetType]?.variables && NodeUI.ports(source,true).some(item=>item.id===port);
    return targetType!=='input' && (spec?.[source.data.type] && spec?.[targetType]
      ? spec[source.data.type].output!=null && spec[source.data.type].output===spec[targetType].input : true);
  }
  function draftCompatibility(from,to,output,input,variables) {
    if(!from || !to || !compatible(from,to.data.type,output,variables))return false;
    if(!variables || input==='value')return true;
    const port=NodeUI.inputPorts(to,true).find(item=>item.id===input);
    const field=NodeUI.branched(from.data.type)?'label':from.data.type==='input' && output==='value'?'message':output;
    const type=NodeUI.outputs(from,true)[field];
    return Boolean(port && type && (port.type==='any' || type==='any' || port.type===type ||
      port.type==='list' && input!=='source'));
  }
  function canConnect(source,target,ignoredEdge,port='value',input='value') {
    if(!nodeById(source) || !nodeById(target))return false;
    return !graph.edges.some(edge=>edge.id!==ignoredEdge && edge.source===source && edge.target===target &&
      (edge.output||'value')===port && (edge.input||'value')===input && !edge.field);
  }
  function wouldCycle(source,target,ignoredEdge) {
    const visited=new Set(), todo=[target];
    while(todo.length) {
      const item=todo.pop();
      if(item===source)return true;
      if(visited.has(item))continue;
      visited.add(item);
      todo.push(...graph.edges.filter(edge=>edge.id!==ignoredEdge && edge.source===item).map(edge=>edge.target));
    }
    return false;
  }
  function setMessage(value) { message = value; const node = $('desktop-workflow-message'); if (node) node.textContent = value; }
  function updateDefinitionVisual() {
    const host = root?.querySelector('.desktop-workflow-heading > div');
    if (!host) return;
    let visual = host.querySelector('.desktop-definition-image');
    if (!visual) { visual = document.createElement('span'); visual.className = 'desktop-definition-image'; host.prepend(visual); }
    visual.replaceChildren(); visual.classList.toggle('wfcat-default-image', !definition?.image);
    if (definition?.image) { const image = document.createElement('img'); image.src = 'data:' + definition.image.mime + ';base64,' + definition.image.data; image.alt = ''; image.onerror = () => { image.remove(); visual.classList.add('wfcat-default-image'); }; visual.append(image); }
  }
  function commit(next, announcement, clearDraft) {
    const snapshot=clone(graph);
    if(clearDraft){snapshot.editor=[clearDraft,nodeDrafts.get(clearDraft) || null];nodeDrafts.delete(clearDraft);}
    history=[...history.slice(-19),snapshot];redoHistory=[];graph=normalizeGraph(customCopy({...graph,...next}));
    dirty=true;persistDraft();setMessage(announcement);renderCanvas();renderInspector();updateSaveState();
  }
  function selectNode(id, moveFocus = false) {
    if (!nodeById(id)) return;
    canvasUI?.deselect();
    selected = id;
    if(moveFocus) showCanvasPanel('inspector',true);
    renderCanvas();renderInspector();persistUI();
    if (moveFocus) nodeElement(id)?.focus({preventScroll:true});
    if (inspectorOpen && inspectorTab==='runtime' && !showingRun()) loadLastRun();
  }
  function removeNode(id=selected) {
    const node=nodeById(id);
    if(!node || showingRun())return;
    const links=graph.edges.filter(edge=>edge.target===node.id || edge.source===node.id);
    const readers=graph.nodes.filter(item=>item.id!==node.id && [item.data.config,nodeDrafts.get(item.id)?.config]
      .some(config=>NodeUI.references(config).some(ref=>String(ref).startsWith(node.id+'.'))));
    if((links.length || readers.length) && !confirm('删除 '+node.data.label+' 会移除 '+links.length+' 条连线'+
      (readers.length?'；需检查变量引用：'+readers.map(item=>item.data.label).join('、'):'')+'。此操作可撤销。'))return;
    const remaining=graph.nodes.filter(item=>item.id!==node.id);
    selected=remaining[0]?.id || '';selectedEdge=null;
    commit({nodes:remaining,edges:graph.edges.filter(edge=>!links.includes(edge))},'节点与连线已删除，可撤销',node.id);
  }
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
  function addNode(type = 'input', overrides = {}, from = null, position = null) {
    const start = !graph.nodes.length && type!=='input'
      ? {id:'input-'+crypto.randomUUID().slice(0,8),position:{x:40,y:80},
         data:{type:'input',label:NodeUI.label('input'),config:{fields:[]}}}
      : null;
    if (showingRun() || graph.nodes.length+Number(Boolean(start))>=24) {
      setMessage('此流程已达到 24 个节点的上限。');return;
    }
    if (start) from={id:start.id,port:'value'};
    const base = start || nodeById(from?.id || selected), id = `${type}-${crypto.randomUUID().slice(0,8)}`;
    const label=NodeUI.label(type) || TYPE_DEFAULTS[type]?.[0] || type;
    const detail=workflowCatalog?.nodes[type]?.detail || TYPE_DEFAULTS[type]?.[1] || '';
    const node = {id, position: {x: (base?.position.x ?? 80) + 248, y: base?.position.y ?? 80}, data: {...{label, type, detail, source: '用户配置', input: '等待数据', output: '等待数据', enabled: true, condition: '前置节点完成', failurePolicy: 'stop', actualKey: null}, ...overrides}};
    if(type==='tool' && !node.data.config) {
      const [first]=Object.keys(workflowCatalog?.nodes.tool?.options||{});
      if(first) node.data.config={tool:first,required:false};
    }
    const variables = variableDraft();
    if (!node.data.config && variables) node.data.config=NodeUI.defaults(type);
    if (start) {
      const ref=start.id+'.message', cfg=node.data.config;
      if ('source' in cfg && ['text','any'].includes(NodeUI.sourceTypes[type]) && type!=='document') cfg.source=ref;
      if ('template' in cfg) cfg.template='{{'+ref+'}}';
      if (type==='aggregate') cfg.sources=[ref];
    }
    const insertion=from?.edge && graph.edges.find(edge=>edge.id===from.edge);
    if(from?.edge && !insertion) { closeNodePicker();return; }
    const nextPort=insertion && insertionPort(node,nodeById(insertion.target),variables);
    if(from && !start && (!base || !compatible(base,type,from.port,variables) || insertion && !nextPort)) {
      setMessage('请选择能够连接此端口的节点。');return;
    }
    if(graph.edges.length>=64 && from) {setMessage('此流程已达到 64 条连线的上限。');return;}
    if(!base) node.position={x:40,y:80};
    else if(from) node.position.y += Math.max(0, NodeUI.ports(base,variables).findIndex(port=>port.id===from.port))*155;
    else node.position.y += 150;
    if(position)node.position=position;
    else if(from) node.position=availableNodePosition(from.position || node.position);
    const outgoing=(source,target,output)=>({id:crypto.randomUUID(),source,target,condition:'always',...(variables?{output}:{})});
    const edges=insertion ? [...graph.edges.map(edge=>edge===insertion?{...edge,target:id}:edge),
      outgoing(id,insertion.target,nextPort.id)] : from ? [...graph.edges,outgoing(from.id,id,from.port)] : graph.edges;
    closeNodePicker();selected=id;
    if(insertion)selectedEdge=null;
    commit({nodes:[...graph.nodes,...(start?[start]:[]),node],edges},
      insertion ? `已插入 ${label}，可撤销此次插入` : `已添加 ${label}${from?' 并连线':''}`);
    if(position || narrowCanvas.matches) showCanvasPanel('inspector',true);
    nodeElement(id)?.focus({preventScroll:true});
  }
  function availableNodePosition(origin) {
    const occupied=graph.nodes.map(node=>{
      const card=nodeElement(node.id);
      return {...node.position,width:card?.offsetWidth || 208,height:card?.offsetHeight || 110};
    });
    const step=156, clear=(x,y)=>occupied.every(box=>
      x+222<=box.x || x>=box.x+box.width+14 || y+142<=box.y || y>=box.y+box.height+22);
    if(clear(origin.x,origin.y))return origin;
    for(let offset=1;offset<=occupied.length;offset++) {
      for(const direction of [1,-1]) {
        const y=origin.y+offset*step*direction;
        if(clear(origin.x,y))return {x:origin.x,y};
      }
    }
    return {x:Math.max(...occupied.map(box=>box.x+box.width))+28,y:origin.y};
  }
  function insertionPort(source,target,variables) {
    if(!target)return;
    const ports=NodeUI.ports(source,variables).filter(port=>compatible(source,target.data.type,port.id,variables));
    return ports.find(port=>port.id==='default') || ports[0];
  }
  function addBuiltinTool(id) {
    const spec=workflowCatalog?.nodes.tool?.options[id];
    if (AnalysisMode.active() !== professional || !spec || graph.nodes.length>=24) return false;
    if(showingRun()){workSurface='edit';clearArchive();updateWorkspaceTabs();}
    addNode('tool',{label:spec.label,detail:spec.detail,config:{tool:id,required:false}});
    return true;
  }
  function useRenderer(kind,id) {
    if(AnalysisMode.active() !== professional || !['chart','report'].includes(kind) || !Object.hasOwn(workflowCatalog?.nodes[kind]?.options||{},id))return false;
    const target=graph.nodes.find(node=>node.id===selected && node.data.type===kind) || graph.nodes.find(node=>node.data.type===kind);
    if(!target && graph.nodes.length>=24)return false;
    if(showingRun()){workSurface='edit';clearArchive();updateWorkspaceTabs();}
    inspectorTab='config';showCanvasPanel('inspector',true);
    if(!target){addNode(kind,{config:{renderer:id}});return true;}
    selected=target.id;
    if(nodeDrafts.has(selected))nodeDrafts.get(selected).renderer=id;
    const updated={...target,data:{...target.data,config:{renderer:id}}};
    commit({...graph,nodes:graph.nodes.map(node=>node.id===selected?updated:node)},'已将渲染插件应用到流程草稿');
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
    if (type==='analysis') {
      if(fields.instruction?.trim())config.instruction=fields.instruction.trim();
      const tools=[...form.elements.agent_tools.selectedOptions].map(item=>item.value);
      if(tools.length)config.tools=tools;
    }
    if (fields.renderer && ['chart','report'].includes(type)) config.renderer=fields.renderer;
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
  function needsValidationLink(source,target,variables) {
    return !variables && source?.data.type==='input' && workflowCatalog?.nodes[target?.data.type]?.input==='context';
  }
  function planValidationLink(source,target,existing) {
    const incoming=graph.edges.filter(edge=>edge.target===target.id && edge!==existing);
    const candidates=graph.edges.filter(edge=>{
      if(edge.source!==source.id || edge.condition!=='always' && edge!==existing)return false;
      const data=nodeById(edge.target)?.data;
      return data?.type==='validation' && data.enabled!==false;
    });
    const connected=candidates.find(edge=>incoming.some(link=>link.source===edge.target));
    if(connected)return {via:connected.target,connected:true};
    if(incoming.length)return {error:'目标已有上游。请改接现有连线，避免加入重复的资料来源。'};
    const upstream=candidates.find(edge=>canConnect(edge.target,target.id,existing?.id) && !wouldCycle(edge.target,target.id,existing?.id));
    const extra=upstream ? Number(!existing || upstream===existing) : existing ? 1 : 2;
    if(graph.edges.length+extra>64 || !upstream && graph.nodes.length>=24)
      return {error:'流程已达节点或连线上限，无法补充资料校验。'};
    return {via:upstream?.target,upstream};
  }
  function connectThroughValidation(source,target,condition,existing,route) {
    if(route.error){setMessage(route.error);return;}
    const label=nodeById(target).data.label;
    if(route.connected || existing && route.via===existing.source && target===existing.target) {
      setMessage(`已通过资料校验连接到 ${label}`);return;
    }
    const original=existing && existing!==route.upstream ? existing : null;
    const edges=graph.edges.filter(edge=>edge!==original);
    let via=route.via, nodes=graph.nodes;
    if(!via) {
      via='validation-'+crypto.randomUUID().slice(0,8);
      const {x,y}=nodeById(source).position, end=nodeById(target).position;
      const position=availableNodePosition({x:Math.round((x+end.x)/2),y:Math.round((y+end.y)/2)});
      const data={type:'validation',label:NodeUI.label('validation'),detail:workflowCatalog.nodes.validation.detail,config:{}};
      nodes=[...nodes,{id:via,position,data}];
      edges.push({id:crypto.randomUUID(),source,target:via,condition:'always'});
    }
    edges.push({id:original?.id || crypto.randomUUID(),source:via,target,condition});
    commit({nodes,edges},`已通过资料校验连接到 ${label}，可撤销`);
  }
  function linkNodes(source,target,condition='always',existing=null,port=existing?.output || 'value',input=existing?.input || 'value',{bridge=true}={}) {
    if(source===target){setMessage('节点不能连接自身。');return;}
    if(existing && existing.source===source && existing.target===target && (existing.output||'value')===port &&
        (existing.input||'value')===input)return;
    if(!canConnect(source,target,existing?.id,port,input)) {setMessage('此端口组合已有连线，已保留原连线。');return;}
    const from=nodeById(source), to=nodeById(target), variables=NodeUI.isVariable(graph);
    if(bridge && input==='value' && port==='value' && !wouldCycle(source,target,existing?.id) && needsValidationLink(from,to,variables)) {
      const route=planValidationLink(from,to,existing);
      if(!route.error){connectThroughValidation(source,target,condition,existing,route);return;}
    }
    if(!existing && graph.edges.length>=64) {setMessage('此流程已达到 64 条连线的上限。');return;}
    const wire={id:existing?.id || crypto.randomUUID(),source,target,condition,
      ...((variables || port!=='value')?{output:port}:{}),...(input!=='value'?{input}:{}),
      ...(existing?.field && existing.source===source && existing.output===port?{field:existing.field}:{})};
    document.activeElement?.blur();
    commit({edges:existing?graph.edges.map(edge=>edge===existing?wire:edge):[...graph.edges,wire]},
      existing?'连线已改接，可撤销':'连线已创建');
  }
  function connectNodes(event) {
    event.preventDefault();
    const {source,target,condition,output,input}=event.currentTarget.elements;
    linkNodes(source.value,target.value,condition.value,null,output.value,input.value,{bridge:false});
  }
  function restoreEdit(from,to,message) {
    if(showingRun() || !from.length) return;
    const previous=from.pop(), snapshot=clone(graph);
    if(previous.editor){
      const [id,fields]=previous.editor;snapshot.editor=[id,nodeDrafts.get(id) || null];
      if(fields)nodeDrafts.set(id,fields);else nodeDrafts.delete(id);
    }
    to.push(snapshot);graph=normalizeGraph(previous);dirty=true;selectingPort=null;
    if(!nodeById(selected))selected=graph.nodes[0]?.id || '';
    for(const id of nodeDrafts.keys())if(!nodeById(id))nodeDrafts.delete(id);
    persistDraft();setMessage(message);renderCanvas();renderInspector();
  }
  const undo=()=>restoreEdit(history,redoHistory,'已撤销上一次编辑');
  const redo=()=>restoreEdit(redoHistory,history,'已重做上一次编辑');
  function saveWorkflow() {
    if (showingRun()) return;
    canvasUI?.flush();
    if (definition?.mode === 'custom') {
      window.WorkflowChat?.saveCanvas(canvasSnapshot(), {direct:true});
      return;
    }
    if (blankCanvas || NodeUI.isVariable(graph)) {window.WorkflowChat?.saveCanvas(canvasSnapshot());return;}
    try { write(canvasKey('workflow'),graph); savedGraph=clone(graph); dirty=nodeDrafts.size>0; persistDraft();
      setMessage(dirty?'流程已保存。节点表单还有未提交修改':'流程已保存到本机');updateSaveState();
    } catch (_) {setMessage('本机存储不可用，当前编辑仍保留在页面中');}
  }
  function readyToSave() {
    const pending=[...nodeDrafts.keys()].find(id=>nodeById(id));
    if (!pending) return true;
    inspectorTab='config';selectNode(pending,true);
    $('desktop-node-config').querySelector('[type="submit"]')?.focus();
    setMessage('请先保存当前节点配置，再保存或运行流程。');
    return false;
  }
  function canvasSnapshot() {
    canvasUI?.flush();
    return {definition, graph:safeLegacy(customCopy()), edits:safeLegacy([...nodeDrafts].filter(([id])=>nodeById(id))),source:graph};
  }
  function useDefinition(value, {empty=false} = {}) {
    if (!focus) return false;
    canvasUI?.reset();closeNodePicker();
    persistDraft(); persistUI(); clearArchive();
    definition = value;blankCanvas=empty;lastRun=null;++lastRunRequest;
    write('canvas-definition', definition);
    write('canvas-blank', blankCanvas);
    restoreCanvas();
    workSurface = 'edit'; archivedId = null;restoreEditorView();
    selectingPort = null;
    updateWorkspaceTabs(); update(); applyCanvasViewport();
    loadLastRun();
    setMessage(value ? value.name + ' · 已打开可编辑草稿' : '已打开本机画布');
    return true;
  }
  function savedDefinition(value,snapshot) {
    if (definition?.id !== snapshot.definition?.id || graph !== snapshot.source) return;
    if (blankCanvas && !definition) {
      for (const key of ['workflow','workflow-draft','workflow-ui','canvas-pan','canvas-zoom']) write(canvasKey(key),null);
    }
    definition = value;blankCanvas=false;savedGraph = normalizeGraph({...value.graph,mode:value.mode}); graph = clone(savedGraph);
    write('canvas-definition', value);
    write('canvas-blank', false);
    write(canvasKey('workflow'), savedGraph);
    dirty=JSON.stringify(safeLegacy([...nodeDrafts]))!==JSON.stringify(snapshot.edits);
    persistDraft(); persistUI(); saveCanvasViewport();
    setMessage((value.draft?'已保存流程草稿 · ':'已保存可运行版本 · ')+value.revision.slice(0,8));
    update();
  }
  function restoreDefault() {
    if (dirty && !confirm('恢复系统模板会替换当前画布和节点表单。继续吗？')) return;
    history.push(clone(graph));redoHistory=[];graph=defaultGraph();nodeDrafts.clear();dirty=true;workSurface='edit'; selected='prediction';
    persistDraft();setMessage('已恢复系统模板');renderCanvas();renderInspector();
  }
  function duplicateNode(node, position) {
    if(graph.nodes.length>=24){setMessage('此流程已达到 24 个节点的上限。');return;}
    const copy=safeLegacy(node);
    copy.id=crypto.randomUUID();copy.data.label=(copy.data.label+' 副本').slice(0,80);
    copy.position=position || availableNodePosition({x:copy.position.x,y:copy.position.y+165});
    selected=copy.id;commit({...graph,nodes:[...graph.nodes,copy]},'节点已复制，请连接输入和输出');
    selectNode(copy.id,true);
  }
  function replaceNode(origin, kind) {
    const old=nodeById(origin.id);
    if(origin.graph!==graph || !old || old.data.type===kind)return;
    const variables=NodeUI.isVariable(graph), config=variables?NodeUI.defaults(kind):{};
    const shared=variables?Object.keys(config).concat(kind==='llm'?['model']:[]):
      ({analysis:['model','tools','instruction'],merge:['model'],retrieval:['binding']}[kind] || []);
    for(const field of shared)if(field!=='cases' && Object.hasOwn(old.data.config,field))config[field]=old.data.config[field];
    const missing=[];
    if(variables && config.source) {
      const actual=NodeUI.upstream(graph,old.id).find(item=>item.ref===config.source)?.type;
      const expected=NodeUI.sourceTypes[kind];
      if(!actual || expected && !['any',actual].includes(expected) && actual!=='any'){
        missing.push('需要重新绑定来源 '+config.source);config.source='';
      }
    }
    const next={...old,data:{type:kind,label:old.data.label===nodeTypeLabel(old.data.type)?nodeTypeLabel(kind):old.data.label,
      detail:old.data.detail,enabled:true,failurePolicy:'stop',config}};
    const outputs=NodeUI.outputs(next,variables), previousOutputs=NodeUI.outputs(old,variables);
    const removed=graph.edges.filter(edge=>{
      if(edge.source!==old.id && edge.target!==old.id)return false;
      const from=edge.source===old.id?next:nodeById(edge.source),to=edge.target===old.id?next:nodeById(edge.target);
      const port=edge.output || 'value', input=edge.input || 'value';
      return !draftCompatibility(from,to,port,input,variables) ||
        variables && edge.source===old.id && edge.field && !outputs[edge.field];
    });
    const nextGraph={nodes:graph.nodes.map(node=>node===old?next:node),edges:graph.edges.filter(edge=>!removed.includes(edge))};
    const references=graph.nodes.flatMap(node=>{
      const refs=NodeUI.references(nodeDrafts.get(node.id)?.config || node.data.config).filter(ref=>ref.startsWith(old.id+'.'));
      if(!refs.length)return [];
      const available=new Set(NodeUI.upstream(nextGraph,node.id).map(item=>item.ref));
      return refs.filter(ref=>{
        const field=ref.split('.')[1];return !available.has(ref) || outputs[field]!==previousOutputs[field];
      }).map(ref=>`${node.data.label} · ${ref}`);
    });
    const details=[...missing,...removed.map(edge=>`移除连线 ${nodeById(edge.source)?.data.label} · ${edge.output || 'value'} → ${nodeById(edge.target)?.data.label} · ${edge.input || 'value'}`),
      ...references.map(ref=>'需重新绑定 '+ref)];
    const fields=Object.keys(old.data.config).filter(field=>field==='cases' || !Object.hasOwn(config,field));
    if(fields.length)details.push('无法迁移的配置：'+fields.join('、'));
    if(nodeDrafts.has(old.id))details.push('未保存的节点表单将暂存到撤销记录。');
    if(details.length && !confirm(`将 ${old.data.label} 更改为 ${nodeTypeLabel(kind)}？\n\n${details.join('\n')}`))return;
    closeNodePicker();selected=old.id;selectedEdge=null;
    commit(nextGraph,`已更改为 ${nodeTypeLabel(kind)}，可撤销`,old.id);
    selectNode(old.id,true);
  }
  function exportWorkflow() {
    const blob=new Blob([JSON.stringify(safeLegacy(graph),null,2)],{type:'application/json'}), url=URL.createObjectURL(blob);
    const link=document.createElement('a');link.href=url;link.download='stock-predict-mailer-workflow.json';link.click();URL.revokeObjectURL(url);
    setMessage('工作流已导出');
  }
  async function importWorkflow(event) {
    const file=event.target.files?.[0];event.target.value='';if (!file) return;
    const scope = AnalysisMode.capture();
    try {
      if (file.size>384*1024) throw Error('流程文件超过 384 KiB');
      const candidate=normalizeGraph(JSON.parse(await file.text()));
      if (!AnalysisMode.current(scope) || scope.mode !== professional) return;
      const keys=new Set(candidate.nodes.map(node=>node.id));
      if(keys.size!==candidate.nodes.length) throw Error('文件包含重复节点');
      history.push(clone(graph));redoHistory=[];graph=candidate;nodeDrafts.clear();dirty=true;workSurface='edit';selected=graph.nodes[0]?.id||'';
      persistDraft();setMessage('工作流已导入，请运行校验后保存');renderCanvas();renderInspector();
    } catch (error) {if (AnalysisMode.current(scope)) setMessage('导入失败 · '+error.message);}
  }
  function updateSaveState() {
    const save=$('desktop-workflow-save'), undoButton=$('desktop-workflow-undo');
    if(save){save.disabled=!dirty;save.textContent=dirty?'保存流程 *':'已保存';}
    if(undoButton)undoButton.disabled=showingRun() || !history.length;
    markIssues();scheduleValidation();
  }

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
    const kind=node.data.type, typeLabel=nodeTypeLabel(kind);
    const valueGraph=shownGraph(), variables=NodeUI.isVariable(valueGraph);
    article.style.setProperty('--node-accent', NodeUI.appearance.get(kind)?.color || TYPE_COLOR[kind] || TYPE_COLOR.custom);
    article.tabIndex = 0;
    article.setAttribute('aria-label', `${node.data.label}，${typeLabel}，${STATUS_LABEL[status] || '未开始'}`);
    drawNodePosition(article, nodePosition(node));
    article.classList.toggle('selected', node.id === selected);
    article.classList.toggle('disabled', node.data.enabled === false);
    article.classList.toggle('dragging', canvasDrag?.id === node.id && Boolean(canvasDrag.preview));
    if (workflowCatalog && !workflowCatalog.nodes[node.data.type] && !showingRun()) article.dataset.draft='true';
    if (node.data.modelVersion) article.title = `模型版本 ${node.data.modelVersion}`;
    const head = document.createElement('header'), icon = NodeUI.icon(kind), title = document.createElement('div'), label = document.createElement('strong'), type = document.createElement('small');
    label.textContent = node.data.label;
    label.title=node.data.label;
    type.textContent = typeLabel + (article.dataset.draft?' · 待配置':'');
    title.append(label, type);
    head.append(icon, title);
    const database=workflowCatalog?.nodes.database?.options;
    const query=node.data.config?.source==='sqlite' ? (node.data.config.table || '本机 SQLite 文件') :
      database?.queries[node.data.config?.query || database?.defaults.query];
    const tool=workflowCatalog?.nodes.tool?.options[node.data.config?.tool]?.label;
    const renderer=node.data.config?.renderer && workflowCatalog?.nodes[node.data.type]?.options?.[node.data.config.renderer];
    const configured=(node.data.type==='database' && query ? `${query} · 最多 ${node.data.config?.limit ?? database.defaults.limit} 条` : '') ||
      renderer || tool || node.data.config?.binding || (node.data.config?.model && safeProfiles().find(profile=>profile.id===node.data.config.model)?.name);
    const modelName=id=>safeProfiles().find(item=>item.id===(id||AnalysisMode.model()))?.name || '待配置 · 模型';
    const summaries=NodeUI.summary(node,valueGraph,modelName);
    if(!summaries.length && !NodeUI.branched(kind)) summaries.push(configured || details.source || workflowCatalog?.nodes[kind]?.detail || '待配置');
    const errorMark=text(head,'span','⚠','workflow-node-invalid');errorMark.hidden=true;errorMark.title='节点有校验错误';
    const badge = document.createElement('span');
    badge.className = 'desktop-flow-status';
    badge.textContent = STATUS_ICON[status] || '○';
    badge.title=STATUS_LABEL[status] || '未开始';
    badge.setAttribute('aria-hidden','true');
    head.append(badge);article.append(head);
    for(const value of summaries) {
      const item=text(article,'p',value,'workflow-card-summary');item.title=value;
      if(value.startsWith('待配置'))article.dataset.configState='missing';
    }
    function makePort(direction, outlet) {
      const outgoing=direction==='out';
      const port=makeButton('',event=>{
        event.stopPropagation();
        if(outgoing) {
          openNodePicker({id:node.id,port:outlet.id},port);
        } else if(selectingPort) {
          const source=selectingPort;
          if(source.edge)return;
          closeNodePicker();
          linkNodes(source.id,node.id,'always',null,source.port,outlet.id);
        }
      });
      port.className='desktop-flow-port '+direction;port.dataset.port=outlet.id;
      const attached=outgoing ? valueGraph.edges.some(edge=>edge.source===node.id && (edge.output || 'value')===outlet.id) :
        valueGraph.edges.some(edge=>edge.target===node.id && (edge.input||'value')===outlet.id);
      port.classList.toggle('connected',attached);
      port.disabled=showingRun() || outgoing && Boolean(workflowCatalog && !workflowCatalog.nodes[kind]);
      const type=outlet.type || workflowCatalog?.nodes[kind]?.[outgoing?'output':'input'];
      port.title=[node.data.label,outlet.label,NodeUI.types[type] || type].filter(Boolean).join(' · ');
      port.setAttribute('aria-label',port.title+(outgoing?'，拖动连线或点击添加节点':'，拖动连接上游节点'));
      if(outgoing)port.setAttribute('aria-haspopup','dialog');
      return port;
    }
    for(const port of NodeUI.inputPorts(node,variables)) {
      if(port.id==='value')article.append(makePort('in',port));
      else {
        const row=text(article,'div',port.label,'workflow-card-inlet');
        text(row,'small',NodeUI.types[port.type] || port.type,'workflow-port-type');
        row.append(makePort('in',port));
      }
    }
    for(const port of NodeUI.ports(node,variables)) {
      if(!NodeUI.branched(kind) && port.id==='value'){article.append(makePort('out',port));continue;}
      const row=text(article,'div',port.label,'workflow-card-outlet');
      if(port.type)text(row,'small',NodeUI.types[port.type] || port.type,'workflow-port-type');
      const targets=valueGraph.edges.filter(edge=>edge.source===node.id&&edge.output===port.id)
        .map(edge=>valueGraph.nodes.find(item=>item.id===edge.target)?.data.label);
      if(targets.length)text(row,'small',targets.join('、'));
      row.append(makePort('out',port));
    }
    article.addEventListener('click', () => {if(!canvasUI?.takeClick())selectNode(node.id,true);});
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

  function edgePath(edge,source,target) {
    const anchor = (node, direction, portId) => {
      const {x,y}=nodePosition(node), element=nodeElement(node.id);
      const nodeBox=element?.getBoundingClientRect();
      const port=element?.querySelector(`.desktop-flow-port.${direction}[data-port="${CSS.escape(portId)}"]`)?.getBoundingClientRect();
      if(port?.width) return {x:x+(port.left+port.width/2-nodeBox.left)/canvasZoom,
        y:y+(port.top+port.height/2-nodeBox.top)/canvasZoom};
      return {x:x+(direction==='out'?(element?.offsetWidth || 208):0),y:y+(element?.offsetHeight || 100)/2};
    };
    const from=anchor(source,'out',edge.output || 'value'), to=anchor(target,'in',edge.input || 'value');
    return edgeCurve(from,to);
  }
  function edgeCurve(from,to) {
    const dx=to.x-from.x, dy=Math.abs(to.y-from.y);
    const bend=Math.max(28,Math.min(190,dx>0 ? dx*.46+Math.min(dy*.16,35) : Math.abs(dx)*.28+dy*.35));
    return `M ${from.x} ${from.y} C ${from.x+bend} ${from.y}, ${to.x-bend} ${to.y}, ${to.x} ${to.y}`;
  }

  function selectConnection(edge) {
    selectedEdge=showingRun()?null:edge.id;
    nodeElement(selected)?.classList.remove('selected');
    selected=edge.source;
    nodeElement(selected)?.classList.add('selected');
    renderEdges();renderInspector();
    if(selectedEdge)setMessage('拖动线身后选择左侧输入或右侧输出。右键可删除连线。');
  }

  function removeConnection(id) {
    if(showingRun() || !graph.edges.some(edge=>edge.id===id))return;
    if(selectedEdge===id)selectedEdge=null;
    commit({edges:graph.edges.filter(edge=>edge.id!==id)},'连线已删除，可撤销');
  }

  function renderEdges(movedId) {
    const layer = $('desktop-workflow-edge-paths');
    if (!layer) return;
    const paths = [];
    for (const edge of shownGraph().edges) {
      if (movedId && edge.source !== movedId && edge.target !== movedId) continue;
      const source = nodeById(edge.source), target = nodeById(edge.target);
      if (!source || !target) continue;
      const geometry = edgePath(edge,source,target);
      if (movedId) {
        for(const path of layer.querySelectorAll(`[data-edge-id="${CSS.escape(edge.id)}"],[data-edge-hit="${CSS.escape(edge.id)}"]`))path.setAttribute('d',geometry);
        continue;
      }
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', geometry);
      path.setAttribute('class', edge.id===selectedEdge&&!showingRun()?'desktop-flow-edge selected':'desktop-flow-edge');
      path.dataset.edgeId = edge.id;
      const activePort=runtimeFor(source.id).output?.selected;
      if(showingRun() && (statusFor(target.id)==='skipped' || activePort && edge.output!==activePort)) path.classList.add('skipped');
      path.setAttribute('tabindex', '0');
      path.setAttribute('aria-label', `${source.data.label} → ${target.data.label}`);
      const selectEdge=()=>selectConnection(edge);
      path.addEventListener('click',selectEdge);
      path.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();selectEdge();}});
      const group=document.createElementNS(path.namespaceURI,'g');
      group.setAttribute('class','workflow-edge-group'+(edge.id===selectedEdge?' selected':''));
      if(edge.id===selectingPort?.edge)group.setAttribute('data-picking','');
      if(!showingRun()) {
        const hit=document.createElementNS(path.namespaceURI,'path');
        hit.dataset.edgeHit=edge.id;
        hit.setAttribute('d',geometry);hit.setAttribute('class','desktop-flow-edge-hit');
        hit.setAttribute('aria-hidden','true');
        hit.addEventListener('click',selectEdge);
        group.append(hit,path);
        group.append(edgeInsertButton(edge,path));
      } else {
        group.append(path);
      }
      paths.push(group);
    }
    if (!movedId) layer.replaceChildren(...paths);
    positionEdgeInsertButtons(layer);
    markIssues();
  }

  function positionEdgeInsertButtons(layer) {
    for(const button of layer.querySelectorAll('[data-edge-insert]')) {
      const path=button.parentElement.querySelector('[data-edge-id]');
      const point=path.getPointAtLength(path.getTotalLength()/2);
      button.setAttribute('transform',`translate(${point.x} ${point.y}) scale(${1/canvasZoom})`);
    }
  }
  function edgeInsertButton(edge,path) {
    const make=tag=>document.createElementNS(path.namespaceURI,tag);
    const button=make('g'), target=nodeById(edge.target);
    button.dataset.edgeInsert=edge.id;
    button.setAttribute('role','button');button.setAttribute('tabindex','0');
    button.setAttribute('aria-label','在 '+nodeById(edge.source).data.label+' 与 '+target.data.label+' 之间插入节点');
    button.setAttribute('aria-haspopup','dialog');
    const circle=make('circle'), plus=make('path');
    circle.setAttribute('r','11');plus.setAttribute('d','M -4 0 H 4 M 0 -4 V 4');
    button.append(circle,plus);
    const open=event=>{
      event.preventDefault();event.stopPropagation();
      const point=path.getPointAtLength(path.getTotalLength()/2).matrixTransform(path.getScreenCTM());
      const start=nodeById(edge.source), end=nodeById(edge.target);
      const position={x:Math.round((end.position.x+start.position.x)/2),
        y:Math.round((end.position.y+start.position.y)/2)};
      openNodePicker({id:edge.source,port:edge.output || 'value',edge:edge.id,position},button,point);
    };
    button.addEventListener('click',open);
    button.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key))open(event);});
    return button;
  }

  function installEdgeDragging(canvas) {
    const svg=$('desktop-workflow-edges');
    const line=document.createElementNS(svg.namespaceURI,'path');
    line.setAttribute('class','desktop-flow-edge-preview');
    svg.append(line);
    const center=rect=>({x:rect.x+rect.width/2,y:rect.y+rect.height/2});
    const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
    const pointOf=event=>({x:event.clientX,y:event.clientY});
    function cardDistance(card,point) {
      const rect=card.getBoundingClientRect();
      return Math.hypot(Math.max(rect.left-point.x,0,point.x-rect.right),Math.max(rect.top-point.y,0,point.y-rect.bottom));
    }
    function destination(event,drag) {
      const hit=document.elementFromPoint(event.clientX,event.clientY);
      if(!hit || !canvas.contains(hit))return null;
      const card=hit.closest('[data-workflow-node]'), direct=hit.closest('.desktop-flow-port');
      const point=pointOf(event), variables=NodeUI.isVariable(graph);
      const candidates=card?[card]:[...canvas.querySelectorAll('[data-workflow-node]')]
        .map(node=>({node,gap:cardDistance(node,point)}))
        .filter(({gap})=>gap<=20).sort((a,b)=>a.gap-b.gap).map(({node})=>node);
      for(const candidate of candidates) {
        const right=direct?direct.classList.contains('out'):point.x>=center(candidate.getBoundingClientRect()).x;
        const end=drag.edge?(right?'source':'target'):drag.end;
        const side=end==='source'?'out':'in';
        const ports=direct?[direct]:[...candidate.querySelectorAll('.desktop-flow-port.'+side)];
        const drop=ports.filter(port=>!port.disabled && port.classList.contains(side))
          .map(port=>({port,position:center(port.getBoundingClientRect())}))
          .sort((a,b)=>distance(point,a.position)-distance(point,b.position))[0];
        if(!drop)continue;
        const id=candidate.dataset.workflowNode, name=drop.port.dataset.port;
        const source=end==='source'?id:drag.source, target=end==='target'?id:drag.target;
        const output=(end==='source'?name:drag.output) || 'value', input=(end==='target'?name:drag.input) || 'value';
        const blocked=source===target?'节点不能连接自身。':!canConnect(source,target,drag.edge?.id,output,input)?'此端口组合已有连线。':'';
        const from=nodeById(source), to=nodeById(target), cyclic=wouldCycle(source,target,drag.edge?.id);
        const bridge=!blocked && !cyclic && input==='value' && output==='value' && needsValidationLink(from,to,variables)
          ?planValidationLink(from,to,drag.edge):null;
        const valid=!blocked && (bridge && !bridge.error || draftCompatibility(from,to,output,input,variables) && !cyclic);
        return {...drop,card:candidate,source,target,output,input,end,bridge,valid,blocked};
      }
      return null;
    }
    function highlightDrop(drag,drop) {
      if(drag.drop?.port===drop?.port)return;
      drag.drop?.port.classList.remove('edge-drop-target');
      drag.drop?.card.classList.remove('edge-drop-card');
      drag.drop?.card.removeAttribute('data-drop-invalid');
      drop?.port.classList.add('edge-drop-target');
      drop?.card.classList.add('edge-drop-card');
      if(drop && !drop.valid) {
        drop.card.setAttribute('data-drop-invalid','');
        setMessage(drop.blocked || '此端口组合有校验问题，松手后会保留草稿连线。');
      } else if(drop?.bridge && !drop.bridge.error) {
        const label=nodeById(drop.target).data.label;
        setMessage(drop.bridge.via?`松手后经资料校验连接到 ${label}`:`松手后添加资料校验并连接到 ${label}`);
      } else if(drop && drag.edge)setMessage(`松手后改接${drop.end==='source'?'起点':'终点'} · ${drop.port.title}`);
      else if(drag.drop)setMessage(drag.message);
      drag.drop=drop;
    }
    canvas.addEventListener('pointerdown',event=>{
      if(showingRun() || canvasUI?.panning() || event.button!==0 || edgeDrag || canvasDrag) return;
      const port=event.target.closest('.desktop-flow-port');
      const start=pointOf(event);
      if(port && !port.disabled) {
        const id=port.closest('[data-workflow-node]').dataset.workflowNode, outbound=port.classList.contains('out');
        edgeDrag={end:outbound?'target':'source',source:outbound?id:null,target:outbound?null:id,
          output:outbound?port.dataset.port:'value',input:outbound?'value':port.dataset.port,
          fixed:center(port.getBoundingClientRect()),start,pointer:event.pointerId,port,graph};
        return;
      }
      const stroke=event.target.closest('[data-edge-id], [data-edge-hit], [data-edge-insert]');
      const edge=graph.edges.find(item=>item.id===(stroke?.dataset.edgeId || stroke?.dataset.edgeHit || stroke?.dataset.edgeInsert));
      if(!edge)return;
      const path=svg.querySelector('[data-edge-id="'+CSS.escape(edge.id)+'"]');
      if(!path)return;
      const matrix=path.getScreenCTM(), length=path.getTotalLength();
      const source=path.getPointAtLength(0).matrixTransform(matrix), target=path.getPointAtLength(length).matrixTransform(matrix);
      const end=!stroke.dataset.edgeInsert && distance(start,source)<distance(start,target)?'source':'target';
      edgeDrag={edge,end,anchors:{source,target},start,pointer:event.pointerId,source:edge.source,target:edge.target,
        output:edge.output,input:edge.input,graph};
    });
    canvas.addEventListener('pointermove',event=>{
      if(event.pointerId!==edgeDrag?.pointer) return;
      const drag=edgeDrag;
      if(!drag.moved) {
        if(distance(drag.start,pointOf(event))<4)return;
        drag.moved=true;
        canvas.setPointerCapture(event.pointerId);
        closeNodePicker();
        if(drag.edge)selectConnection(drag.edge);
        drag.message=message;
        canvas.classList.add('connecting');
        drag.port?.classList.add('edge-origin');
      }
      const drop=destination(event,drag);
      highlightDrop(drag,drop);
      const inverse=svg.getScreenCTM().inverse(), point=drop?.position || pointOf(event), end=drop?.end || drag.end;
      const fixed=drag.anchors?(end==='source'?drag.anchors.target:drag.anchors.source):drag.fixed;
      const [a,b]=(end==='source'?[point,fixed]:[fixed,point])
        .map(({x,y})=>new DOMPoint(x,y).matrixTransform(inverse));
      line.setAttribute('d',edgeCurve(a,b));
      line.classList.toggle('snapped',Boolean(drop?.valid));
      line.classList.toggle('invalid',Boolean(drop && !drop.valid));
    });
    function finish(event) {
      if(event.pointerId!==edgeDrag?.pointer || event.type==='lostpointercapture' && event.target!==canvas)return;
      const drag=edgeDrag, {edge}=drag;
      const dropped=drag.moved && event.type==='pointerup' && !showingRun() && drag.graph===graph;
      const drop=dropped && destination(event,drag);
      edgeDrag=null;
      highlightDrop(drag,null);
      drag.port?.classList.remove('edge-origin');
      canvas.classList.remove('connecting');
      line.removeAttribute('d');
      if(!dropped)return;
      if(drop) {
        if(drop.blocked){setMessage(drop.blocked);return;}
        linkNodes(drop.source,drop.target,edge?.condition || 'always',edge,drop.output,drop.input);
        return;
      }
      const hit=document.elementFromPoint(event.clientX,event.clientY);
      const card=hit?.closest('[data-workflow-node]');
      const from=nodeById(drag.source), to=card && nodeById(card.dataset.workflowNode);
      if(drag.end==='target' && needsValidationLink(from,to,NodeUI.isVariable(graph))) {
        const route=planValidationLink(from,to,drag.edge);
        if(route.error){setMessage(route.error);return;}
      }
      if(!edge && drag.end==='target' && hit && canvas.contains(hit) && !hit.closest('[data-workflow-node], [data-edge-insert],button')) {
        const position=worldPoint(canvasPoint(canvas,event));
        openNodePicker({id:drag.source,port:drag.output,position},drag.port,pointOf(event));
        return;
      }
      setMessage(edge?'请在左侧输入或右侧输出高亮后松手。':'请拖到兼容节点，或从输出拖到空白处添加节点。');
    }
    for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,finish);
    canvas.addEventListener('pointerleave',event=>{if(!edgeDrag?.moved)finish(event);});
    document.addEventListener('keydown',event=>{
      if(event.key==='Escape' && edgeDrag) {
        event.preventDefault();finish({type:'pointercancel',pointerId:edgeDrag.pointer});
      }
    });
  }

  function renderCanvas() {
    const host = $('desktop-workflow-nodes');
    if (!host) return;
    const focusedId = document.activeElement?.dataset.workflowNode;
    host.replaceChildren(...shownGraph().nodes.map(createNodeElement));
    for(const card of host.children)card.classList.toggle('box-selected',Boolean(canvasUI?.contains(card.dataset.workflowNode)));
    $('workflow-canvas-empty').hidden=Boolean(shownGraph().nodes.length);
    $('desktop-workflow-redo').disabled=!redoHistory.length || showingRun();
    refreshLibrary();
    renderEdges();
    canvasUI?.render();
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
    const variables=NodeUI.isVariable(graph);
    const ports=NodeUI.ports(node,variables), outgoing=graph.edges.filter(edge=>edge.source===node.id);
    const incoming=graph.edges.filter(edge=>edge.target===node.id);
    if(incoming.length) {
      const sources=nodeSection(host,'上游连线');
      for(const edge of incoming)connectionRow(sources,edge,edge.source,variables);
    }
    const section=nodeSection(host,ports.length || outgoing.length?'下一步':'连线');
    for(const edge of outgoing) {
      const port=edge.output || 'value';
      if(!ports.some(item=>item.id===port))ports.push({id:port,label:'旧版出口 · '+port,legacy:true});
    }
    for (const port of ports) {
      const links=text(section,'div','','workflow-next-port');
      text(links,'small',port.label);
      for(const edge of outgoing.filter(edge=>(edge.output || 'value')===port.id))connectionRow(links,edge,edge.target,variables);
      if(!port.legacy && workflowCatalog?.nodes[node.data.type]) {
        const add=makeButton('+ 添加下游',()=>openNodePicker({id:node.id,port:port.id},add));
        links.append(add);
      }
    }
    const manual=document.createElement('details');manual.className='workflow-connect-manual';
    text(manual,'summary','手动连接');
    const form=document.createElement('form');form.className='desktop-flow-connect';
    form.innerHTML='<label>从<select name="source"></select></label><label>到<select name="target"></select></label>'+
      '<label>源端口<select name="output"></select></label><label>目标端口<select name="input"></select></label><label>条件<select name="condition"></select></label><button type="submit">连接节点</button>';
    const {source,target}=form.elements;
    for(const item of graph.nodes) source.add(new Option(item.data.label,item.id));
    for(const [id,label] of Object.entries(EDGE_CONDITIONS)) form.elements.condition.add(new Option(label,id));
    form.elements.condition.closest('label').hidden=variables;
    form.elements.output.closest('label').hidden=!variables;
    form.elements.input.closest('label').hidden=!variables;
    const choices=()=>{
      const from=nodeById(source.value), ports=from?NodeUI.ports(from,variables):[];
      form.elements.output.replaceChildren(...ports.map(item=>new Option(item.label,item.id)));
      const to=nodeById(target.value), inputs=to?NodeUI.inputPorts(to,variables):[];
      form.elements.input.replaceChildren(...inputs.map(item=>new Option(item.label,item.id)));
      if(!inputs.length)form.elements.input.add(new Option('输入','value'));
      if(!ports.length)form.elements.output.add(new Option('输出','value'));
    };
    source.value=node.id;target.onchange=choices;
    (source.onchange=()=>{
      const previous=target.value, candidates=graph.nodes.filter(item=>item.id!==source.value);
      target.replaceChildren(...candidates.map(item=>new Option(item.data.label,item.id)));
      target.value=(candidates.find(item=>item.id===previous) || candidates.find(item=>item.data.type!=='input') || candidates[0])?.id || '';
      form.querySelector('button').disabled=!target.value;choices();
    })();
    form.onsubmit=connectNodes;manual.append(form);section.append(manual);
  }

  function connectionRow(host,edge,id,variables) {
    const target=nodeById(id), row=text(host,'div','','desktop-flow-connection');
    row.dataset.connectionId=edge.id;
    const label=target?.data.label || id;
    const jump=makeButton('',()=>focusDownstream(id));
    jump.className='workflow-next-node';jump.disabled=!target;jump.title=label;
    jump.append(NodeUI.icon(target?.data.type));text(jump,'span',label);row.append(jump);
    if(!variables) {
      const condition=document.createElement('select');
      const path=[edge.source,edge.target].map(key=>nodeById(key)?.data.label || key).join(' → ');
      condition.setAttribute('aria-label','连线条件 '+path);
      for(const [key,name] of Object.entries(EDGE_CONDITIONS)) condition.add(new Option(name,key));
      condition.value=edge.condition;
      condition.onchange=()=>commit({edges:graph.edges.map(item=>item.id===edge.id?{...item,condition:condition.value}:item)},'连线条件已更新');
      row.append(condition);
    }
    if(variables)text(row,'small',(edge.output || 'value')+' → '+(edge.input || 'value'));
    const remove=makeButton('×',()=>removeConnection(edge.id));
    remove.setAttribute('aria-label','删除与 '+label+' 的连线');row.append(remove);
  }

  function focusDownstream(id) {
    const node=nodeById(id);
    if(!node)return;
    selectNode(id,true);
    const canvas=$('desktop-workflow-canvas').getBoundingClientRect(), card=nodeElement(id)?.getBoundingClientRect();
    if(card && (card.left<canvas.left || card.right>canvas.right || card.top<canvas.top || card.bottom>canvas.bottom)) {
      canvasPan={x:Math.round(canvas.width/2-(node.position.x+104)*canvasZoom),y:Math.round(canvas.height/2-(node.position.y+42)*canvasZoom)};
      applyCanvasViewport();saveCanvasViewport();
    }
    $('desktop-node-config').querySelector('[name="label"]')?.focus({preventScroll:true});
  }
  function nodeSection(host,title) {
    const section=text(host,'section','','workflow-node-section');text(section,'h4',title);return section;
  }
  function editForm(host,node) {
    const form=document.createElement('form');form.className='desktop-flow-form';form.id='workflow-node-editor';
    form.innerHTML='<label>节点名称 <span class="workflow-required" aria-hidden="true">*</span><input name="label" required maxlength="80"></label>';
    host.append(form);
    const description=$('desktop-node-description');
    description.value=nodeDrafts.get(node.id)?.detail ?? node.data.detail ?? '';
    return form;
  }
  function editorActions(form) {
    const feedback=text(form,'p','','warn workflow-node-feedback');feedback.setAttribute('role','status');
    const actions=text(form,'div','','desktop-flow-actions workflow-node-save');
    const save=makeButton('保存节点');save.type='submit';save.className='btn primary';actions.append(save);
    $('desktop-node-description').oninput=()=>form.oninput?.();
    form.addEventListener('input',event=>{
      if(event.target.validity?.valid && !event.target.matches('[data-reference]'))event.target.removeAttribute('aria-invalid');
      put('desktop-node-heading',form.elements.label.value || '未命名节点');
    });
    form.addEventListener('invalid',event=>{
      revealField(event.target,event.target.validationMessage);
      feedback.textContent='请检查标记的必填项和参数。';
    },true);
    return feedback;
  }
  function revealField(field, message) {
    if(!field)return;
    for(let section=field.closest('details');section;section=section.parentElement.closest('details'))section.open=true;
    field.setAttribute('aria-invalid','true');
    const label=field.closest('label');
    if(label && message) {
      let error=label.querySelector('.workflow-field-error');
      if(!error)error=text(label,'small','','warn workflow-field-error');
      error.textContent=message;error.id ||= 'workflow-field-error-'+crypto.randomUUID();field.setAttribute('aria-describedby',error.id);
      field.addEventListener('input',()=>{error.remove();field.removeAttribute('aria-describedby');field.removeAttribute('aria-invalid');},{once:true});
    }
    field.focus();
  }

  function variableEditor(host,node) {
    const form=editForm(host,node);form.noValidate=true;
    const saved=nodeDrafts.get(node.id), original=node.data.config;
    const fields=form.elements;
    fields.label.value=saved?.label ?? node.data.label;
    const kind=node.data.type;
    const hasSource=Object.hasOwn(NodeUI.sourceTypes,kind);
    const inputs=hasSource?nodeSection(form,'输入'):null;
    const parameters=kind==='document'?inputs:nodeSection(form,kind==='input'?'输入':kind==='output'?'返回设置':'参数');
    const modelChoices=Object.fromEntries(safeProfiles().filter(model=>model.enabled).map(model=>[model.id,model.name]));
    const configured=saved?.config || original;
    if(configured.model && !modelChoices[configured.model]) modelChoices[configured.model]='已停用或不可用的模型';
    const config=NodeUI.settings(parameters,node,graph,configured,modelChoices,inputs || parameters,
      workflowCatalog?.nodes[kind]?.options);
    const feedback=editorActions(form);
    form.oninput=()=>{
      nodeDrafts.set(node.id,{label:fields.label.value,detail:fields.detail.value,config:config(true)});
      feedback.textContent='';
      dirty=true;persistDraft();updateSaveState();
    };
    form.onsubmit=event=>{
      event.preventDefault();
      try {
        const data={...node.data,label:fields.label.value.trim(),detail:fields.detail.value.trim(),config:config(false)};
        if(!data.label){feedback.textContent='请填写节点名称。';return;}
        const available=NodeUI.ports({...node,data},true).map(port=>port.id);
        const inputs=NodeUI.inputPorts({...node,data},true).map(port=>port.id);
        const affected=graph.edges.filter(edge=>edge.source===node.id && !available.includes(edge.output||'value') ||
          edge.target===node.id && edge.input && !inputs.includes(edge.input));
        const oldOutputs=NodeUI.outputs(node,true), outputs=NodeUI.outputs({...node,data},true);
        const gone=Object.keys(oldOutputs).filter(key=>!Object.hasOwn(outputs,key)).map(key=>node.id+'.'+key);
        const readers=graph.nodes.filter(item=>item.id!==node.id &&
          [item.data.config,nodeDrafts.get(item.id)?.config].some(config=>NodeUI.references(config).some(ref=>gone.includes(ref))));
        const impacted=[...new Set([...affected.map(edge=>nodeById(edge.target)?.data.label || edge.target),...readers.map(item=>item.data.label)])];
        if(impacted.length && !confirm(`受影响节点：${impacted.join('、')}。将移除 ${affected.length} 条连线，${readers.length} 个节点需更新变量引用。可撤销此修改。继续吗？`))return;
        nodeDrafts.delete(node.id);document.activeElement?.blur();
        commit({nodes:graph.nodes.map(item=>item.id===node.id?{...item,data}:item),edges:graph.edges.filter(edge=>!affected.includes(edge))},
          affected.length?`节点已更新，移除 ${affected.length} 条连线`:'节点配置已更新');
      } catch (error) { feedback.textContent=error.message;revealField(error.field,error.message); }
    };
    const result=Object.entries(NodeUI.outputs({...node,data:{...node.data,config:saved?.config||original}},true));
    if(result.length)nodeSection(host,'输出变量').append(terms(result.map(([name,type])=>[name,NodeUI.types[type] || type])));
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
    const form=editForm(host,node), params=nodeSection(form,'参数');
    params.innerHTML+='<label>节点类型<select name="type"></select></label>'+
      '<label data-node-config="binding">授权 MCP 工具<input name="binding" list="workflow-mcp-tools" maxlength="145" placeholder="留空继承主 Agent 已授权工具"></label>'+
      '<datalist id="workflow-mcp-tools"></datalist>'+
      '<label data-node-config="tool">选择工具<select name="tool" required></select></label>'+
      '<p data-node-config="tool" data-tool-detail class="hint"></p>'+
      '<label data-node-config="tool" class="desktop-flow-check"><input name="required" type="checkbox"> 缺少所需数据时触发失败策略</label>'+
      '<label data-node-config="model">分析模型<select name="model"></select></label>'+
      '<label data-node-config="agent">任务指令<textarea name="instruction" rows="3" maxlength="2000"></textarea></label>'+
      '<label data-node-config="agent">授权工具<select name="agent_tools" multiple size="3"></select></label>'+
      '<label data-node-config="renderer">渲染插件<select name="renderer"></select></label>'+
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
    const fields={...node.data,...node.data.config,...nodeDrafts.get(node.id)};
    const spec=workflowCatalog?.nodes[node.data.type];
    if(spec?.input || spec?.source) {
      const inputs=nodeSection(form,'输入');
      inputs.append(terms([['输入类型',spec.input],['数据来源',spec.source]]));
      form.insertBefore(inputs,params);
    }
    const tools=workflowCatalog?.nodes.tool?.options||{};
    for(const [id,entry] of Object.entries(tools)) form.elements.tool.add(new Option(entry.label,id));
    if(fields.tool && !Object.hasOwn(tools,fields.tool))form.elements.tool.add(new Option('工具已不可用',fields.tool));
    if(fields.tool) form.elements.tool.value=fields.tool;
    form.elements.required.checked=fields.required===true;
    const types=Object.fromEntries(Object.entries(TYPE_LABEL).map(([id,label])=>[id,NodeUI.label(id)||label]));
    if(!types[node.data.type])types[node.data.type]=`${node.data.type}（草稿）`;
    for(const [id,label] of Object.entries(types)) form.elements.type.add(new Option(label,id));
    form.elements.model.add(new Option('继承主 Agent',''));
    const authorised=(settings?.agents?.main?.tools || []).filter(binding=>{
      const [id,name]=binding.split(':',2), server=servers.find(item=>item.id===id);
      return server?.enabled && server.allowed_tools.includes(name) && server.effects?.[name]==='read';
    });
    for(const binding of new Set([...authorised,...(fields.tools || [])])) {
      const [id,name]=binding.split(':',2);
      const option=new Option((servers.find(server=>server.id===id)?.name || id)+' · '+name+
        (authorised.includes(binding)?'':' · 已失去授权'),binding);
      option.selected=(fields.tools || []).includes(binding);
      form.elements.agent_tools.append(option);
    }
    for(const model of safeProfiles()) if(model.enabled) form.elements.model.add(new Option(model.name,model.id));
    if(fields.model && ![...form.elements.model.options].some(option=>option.value===fields.model)) form.elements.model.add(new Option('模型已停用或不可用',fields.model));
    const scanDatabases=databaseForm(form,fields,workflowCatalog?.nodes.database?.options);
    for(const key of ['label','type','detail','binding','model','instruction','failurePolicy']) form.elements[key].value=fields[key]||'';
    form.elements.enabled.checked=fields.enabled!==false;
    let rendererKind;
    const sync=()=>{
      const nodeType=form.elements.type.value, renderer=form.elements.renderer;
      if(nodeType!==rendererKind){
        rendererKind=nodeType;
        const options=workflowCatalog?.nodes[nodeType]?.options;
        renderer.replaceChildren(new Option('采用系统默认',''));
        if(['chart','report'].includes(nodeType)){
          for(const [value,label] of Object.entries(options||{}))renderer.add(new Option(label,value));
          if(nodeType===fields.type && fields.renderer){
            if(!Object.hasOwn(options||{},fields.renderer))renderer.add(new Option('插件不可用，请重新选择',fields.renderer));
            renderer.value=fields.renderer;
          }
        }
      }
      for(const label of form.querySelectorAll('[data-node-config]')) {
        const key=label.dataset.nodeConfig;
        const type=form.elements.type.value;
        const source=form.elements.source.value;
        const visible={database:type==='database',tasks:type==='database'&&source==='tasks',
          sqlite:type==='database'&&source==='sqlite',binding:type==='retrieval',tool:type==='tool',model:['analysis','merge'].includes(type),
          agent:type==='analysis',renderer:['chart','report'].includes(type)};
        label.hidden=!visible[key] || (label.contains(form.querySelector('[data-scan-folder]')) &&
          form.querySelector('[data-scan-scope]').value!=='directory');
        const control=label.querySelector('input,select,textarea');
        if(control) control.disabled=label.hidden;
      }
      if(form.elements.type.value==='database' && form.elements.source.value==='sqlite') scanDatabases();
      if(form.elements.type.value==='retrieval') fillMcpTools(form);
      const spec=tools[form.elements.tool.value];
      form.querySelector('[data-tool-detail]').textContent=spec?`${spec.detail}。拦截情形：${spec.requirement}。`:'';
    };
    editorActions(form);
    sync();form.oninput=()=>{
      sync();
      nodeDrafts.set(node.id,{...Object.fromEntries(new FormData(form)),enabled:form.elements.enabled.checked,
        include_fact:form.elements.include_fact.checked,required:form.elements.required.checked,
        tools:[...form.elements.agent_tools.selectedOptions].map(item=>item.value)});
      dirty=true;persistDraft();updateSaveState();
    };
    form.onsubmit=editNode;
    if(spec?.output) nodeSection(host,'输出变量').append(terms([['数据类型',spec.output]]));
    if(node.data.legacy || node.data.modelVersion){
      const previous=document.createElement('details'), summary=document.createElement('summary');
      summary.textContent='旧版配置';previous.append(summary,terms([['模型版本',node.data.modelVersion],['原配置',node.data.legacy]]));
      nodeSection(host,'兼容信息').append(previous);
    }
  }

  let inspectedGraph, inspectedCatalog, inspectedSurface, inspectedSettings, inspectedRecord, runtimeStamp;
  function renderInspector() {
    const host=$('desktop-workflow-inspector');
    if (!host) return;
    const id=selected, node=nodeById(id), config=$('desktop-node-config');
    const spec=workflowCatalog?.nodes[node?.data.type];
    const description=$('desktop-node-description');
    const runId=showingRun()?shownTask()?.id:null;
    const changed=host.dataset.node!==id || inspectedGraph!==graph || inspectedCatalog!==workflowCatalog ||
      inspectedSurface!==workSurface || inspectedSettings!==settings || inspectedRecord!==runId;
    put('desktop-node-state',node?statusText(id):'');
    updateInspectorTabs();
    if(changed) {
      const switching=host.dataset.node!==id || inspectedSurface!==workSurface;
      Object.assign(host.dataset,{node:id,kind:node?.data.type || ''});
      inspectedGraph=graph;inspectedCatalog=workflowCatalog;inspectedSurface=workSurface;inspectedSettings=settings;inspectedRecord=runId;
      put('desktop-node-heading',nodeDrafts.get(id)?.label || node?.data.label || '节点详情');
      put('desktop-node-type',nodeTypeLabel(node?.data.type));
      $('desktop-node-type').title=spec?.detail || '';
      $('desktop-node-heading').title=node?.data.label || '';
      $('desktop-node-icon').replaceChildren(...(node?[NodeUI.icon(node.data.type)]:[]));
      $('desktop-node-actions').hidden=!node || showingRun();
      $('desktop-node-test').hidden=!spec?.testable || node?.data.enabled===false;
      $('desktop-node-test').onclick=()=>{if(readyToSave())openDebug(node);};
      $('desktop-node-copy').onclick=()=>duplicateNode(node);
      description.readOnly=showingRun();description.hidden=!node;
      description.value=node?.data.detail || '';description.oninput=null;
      host.style.setProperty('--node-accent',NodeUI.appearance.get(node?.data.type)?.color || 'var(--accent)');
      config.replaceChildren();
      if(!node) text(config,'p','选择画布上的节点以配置。','hint');
      else if(!showingRun()) {
        const variables=NodeUI.isVariable(graph) && spec?.variables;
        nodeSection(config,'').id='workflow-node-issues';
        if(!spec && workflowCatalog)text(config,'p','此类型保留在草稿中。执行时需要更换为已支持的节点类型。','hint');
        if(variables) variableEditor(config,node);
        else nodeEditor(config,node);
        connectionEditor(config,node);
      }
      if(switching)config.scrollTop=0;
    }
    if(showingRun() || inspectorTab==='runtime')renderNodeRuntime(node);
    else markIssues();
  }

  function nodeEvents(record,node) {
    if(!node)return [];
    const workflow=record.value?.metadata?.workflow;
    const step=workflow?.mode==='system'?(node.data.actualKey || Object.keys(STEP_TO_KEY).find(key=>STEP_TO_KEY[key]===node.id)):node.id;
    return record.events.filter(event=>event.step===step);
  }
  function renderNodeRuntime(node) {
    const host=$('desktop-node-runtime');
    const archive=showingRun(), value=shownTask();
    const latest=lastRun?.node===node?.id && lastRun?.kind===node?.data.type?lastRun:null;
    const record=archive && value?{value,events:archived?archivedEvents:runtime.events}:latest?.record;
    const stamp=[archive,node?.id,record?.value?.id,record?.value?.status?.state,record?.events.at(-1)?.seq,!record&&latest?.pending,latest?.error].join('|');
    if(stamp===runtimeStamp)return;
    if(host.dataset.node!==node?.id)host.scrollTop=0;
    host.dataset.node=node?.id || '';
    runtimeStamp=stamp;
    host.replaceChildren();
    if(!record) {
      text(host,'p',latest?.error || (latest?.pending?'正在读取节点运行记录…':node?'此节点尚无运行记录。':'选择节点查看运行详情。'),'hint');
      if(latest?.error)host.append(makeButton('重新读取',()=>loadLastRun({refresh:true})));
      return;
    }
    const workflow=record.value.metadata?.workflow, taskStatus=record.value.status.state;
    const events=nodeEvents(record,node);
    const step=events.findLast(event=>event.kind==='step');
    const output=events.findLast(event=>event.kind==='node_result');
    const info=archive && node ? runtimeFor(node.id):{};
    const reported=archive && node?statusFor(node.id):output?.status || step?.status;
    const state=['running','needs_input'].includes(reported) && ['failed','canceled'].includes(taskStatus)?taskStatus:reported;
    const version=workflow?.flow?.revision || workflow?.version;
    const failure=state==='failed' && taskStatus==='failed'?record.value.metadata?.error?.message:null;
    const summary=nodeSection(host,'执行摘要');
    summary.append(terms([['流程版本',version || '旧任务 · 无快照版本'],['节点状态',STATUS_LABEL[state] || '未执行'],
      ['耗时',(step?.duration_ms ?? info.duration)==null?null:(step?.duration_ms ?? info.duration)+' ms'],
      ['来源',info.source || step?.source],['错误或跳过原因',output?.reason || step?.reason || failure || info.failure || step?.code],
      ['运行时间',workflow?.started_at || record.value.status.timestamp]]));
    const input=events.find(event=>event.input_summary!=null)?.input_summary ?? info.input;
    const result=output?.summary ?? info.output;
    if(input!=null) nodeSection(host,'输入摘要').append(terms([['输入',input]]));
    if(result!=null) nodeSection(host,'输出摘要').append(terms([['输出',result]]));
    const branches=events.findLast(event=>event.kind==='branch')?.selected;
    if(branches?.length)nodeSection(host,'实际出口').append(terms([['命中',branches]]));
    const tools=events.filter(event=>event.kind==='tool');
    if(tools.length)nodeSection(host,'工具调用').append(terms(tools.map(event=>[event.label || event.tool || '工具',event.code || STATUS_LABEL[event.status] || event.status])));
    NodeUI.humanAction(host,record.value,events,values=>api('tasks/'+encodeURIComponent(record.value.id)+'/continue',
      'POST',values,undefined,AnalysisMode.capture()));
    if(archive) {
      const outputs=record.value.artifacts?.[0]?.parts?.[0]?.data?.workflow_outputs;
      if(outputs?.length) {
        const details=document.createElement('details');
        details.open=node?.data.type==='output';
        text(details,'summary','流程输出');
        details.append(terms(outputs.map(item=>[item.label,item.value])));host.append(details);
      }
      if(archived)host.append(runRecordAction(record.value.id, ['submitted','working'].includes(taskStatus)));
    } else host.append(makeButton('查看此运行',()=>showRun(record.value,record.events,{nodeId:node.id})));
  }

  function runRecordAction(id,running) {
    return makeButton(running?'取消此运行':'删除此运行记录',async()=>{
      const scope=AnalysisMode.capture();
      if(!running && !confirm('删除此运行的记录与结果？'))return;
      try {
        if(running) {
          await api('tasks/'+id+'/cancel','POST',{},undefined,scope);
          if(AnalysisMode.current(scope) && archivedId===id)scheduleArchive(0);
        } else {
          await api('tasks/'+id,'DELETE',undefined,undefined,scope);
          if(AnalysisMode.current(scope) && archivedId===id) {
            clearArchive();persistUI();update();
          }
          await window.Workbench?.removedTask(id,scope);
        }
      } catch(error){if(AnalysisMode.current(scope))explainError(error);}
    });
  }

  function inputState() { let raw; try { raw = JSON.parse($('task-data').value); if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw Error(); } catch (_) { return {state: 'invalid', field: 'task-data', label: '请修正原始 JSON', detail: '原始输入无法解析，请打开资料检查格式。'}; } const prediction = window.AnalysisInput.currentPrediction(); if (typeof prediction?.subject !== 'string' || !prediction.subject.trim()) return {state: 'empty', label: '填写分析资料', detail: ''}; const result = {prediction, facts: Array.isArray(raw.context?.facts) ? raw.context.facts.length : 0}; if (typeof prediction.model_version !== 'string' || !prediction.model_version.trim()) return {...result, state: 'invalid', field: 'p-model-version', label: '补充模型版本', detail: '请填写这份预测的上游模型版本。'}; if (!prediction.direction && !Number.isFinite(prediction.value)) return {...result, state: 'invalid', field: 'p-direction-up', label: '补充预测方向', detail: '请按上游预测选择本轮方向。'}; if (!(Number.isFinite(prediction.horizon?.value) && prediction.horizon.value > 0)) return {...result, state: 'invalid', field: 'p-horizon-value', label: '核对预测周期', detail: '预测周期需要大于零。'}; if (!(Date.parse(prediction.valid_until) > Date.now())) return {...result, state: 'expired', field: 'p-valid-until', label: '更新过期预测', detail: '预测已过期或缺少有效期，请核对原始资料后更新。'}; if (prediction.confidence != null && !(Number.isFinite(prediction.confidence) && prediction.confidence >= 0 && prediction.confidence <= 1)) return {...result, state: 'invalid', field: 'p-confidence', label: '核对置信度', detail: '置信度须在 0 到 1 之间；上游未提供时可留空。'}; if (raw.context?.facts && (!Array.isArray(raw.context.facts) || raw.context.facts.some(fact => typeof fact?.source !== 'string' || !fact.source.trim() || !Number.isFinite(Date.parse(fact.observed_at))))) return {...result, state: 'invalid', label: '补充事实来源', detail: '每条客观事实都需要来源和有效的观测时间。'}; return {...result, state: 'ready', label: prediction.subject, detail: '主要资料已填写；发送时会再次校验资料、归档和授权。'}; }
  function openData() { origin = document.activeElement?.getClientRects?.().length ? document.activeElement : $('analysis-data-open'); $('prediction-editor').open = true; window.AnalysisInput.open('input'); const target = $('task-form').querySelector('[aria-invalid="true"]') || $(inputState().field || 'p-subject'); for (let parent = target.parentElement; parent && parent !== $('task-form'); parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; target.focus(); target.scrollIntoView({block: 'nearest'}); }
  function openResult() { const task = window.Workbench?.result(); if (!task) return; origin = document.activeElement; window.AnalysisInput.open(['submitted', 'working'].includes(task.status.state) ? 'progress' : 'report'); $('analysis-tab-' + pane).focus(); }
  function chooseModel() { origin = document.activeElement; if (safeProfiles().some(item => item.enabled && item.id === AnalysisMode.model())) window.ComposerControls.openModels(); else { showView('settings'); showPanel('models'); $('model-name').focus(); } }
  async function sample(event) { if (sampling) return; const button = event.currentTarget, current = safeProfiles().find(item => item.enabled && item.id === AnalysisMode.model()); if (current?.provider !== 'mock' && current && !confirm('准备示例会将工作台默认模型切换为 Mock，并替换当前预测与事实。不会自动提交分析。继续？')) return; if (window.AnalysisInput.currentPrediction()?.subject && (!current || current.provider === 'mock') && !confirm('用合成示例替换当前预测与事实？当前问题会保留，不会自动提交。')) return; sampling = true; button.disabled = true; try { await $('try-sample').onclick(); if ($('task-data').value.includes('console-mock')) { update(); $('conversation-message').focus(); notice('离线示例已准备：默认模型为 Mock，资料为合成资料。输入问题后点击发送。'); } } finally { sampling = false; button.disabled = false; } }

  function runtimeSet(id,status,patch={}) {
    if(status && STATUS_LABEL[status]) runtime.states.set(id,status);
    const values=Object.fromEntries(Object.entries(patch).filter(([,value])=>value!==undefined && value!==null));
    runtime.details.set(id,{...runtimeFor(id),...values});
  }
  function applyEvent(event) {
    if (!event || AnalysisMode.active() !== professional) return;
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
      if(['running','needs_input'].includes(statusFor(node.id))) runtimeSet(node.id,status,{failure:current.metadata?.error?.code||'任务已取消'});
    }
    const result=current?.artifacts?.[0]?.parts?.[0]?.data;
    if(result?.analysis && !custom && !events.length) runtimeSet('report','completed',{source:'历史报告产物'});
    if(result?.mail && !custom) runtimeSet('delivery',['sent','simulated'].includes(result.mail.status)?'completed':'degraded',{output:result.mail.status});
    if(result?.analysis?.charts && !custom) runtimeSet('charts',null,{output:`${result.analysis.charts.length} 个报告图表`});
  }

  function graphSubmission(key,debug=null) {
    const draft=debug?customCopy():graph;
    return {mode:draft.mode,key,...(draft.mode==='custom'?{graph:safeLegacy({version:draft.version,nodes:draft.nodes,edges:draft.edges})}:{}),...(debug?{debug}:{})};
  }
  function runVariableCanvas() {
    if (document.querySelector('[data-workflow-run-form][open]')) return;
    const snapshot=canvasSnapshot(), scope=AnalysisMode.capture(), runKey=nodeRunKey();
    const start=snapshot.graph.nodes.find(node=>node.data.type==='input');
    const saved=definition?.fields && !dirty ? definition : null;
    const draftKey=canvasKey('run-input'), draft=read(draftKey) || {};
    const dialog=document.createElement('dialog');
    dialog.className='plugin-dialog workflow-run-dialog';dialog.dataset.workflowRunForm='';
    dialog.innerHTML='<form><h3>运行流程</h3><label>需求<textarea name="message" rows="3" maxlength="4000"></textarea></label>'+
      '<div data-workflow-run-fields></div><label data-workflow-run-knowledge>资料范围<select name="knowledge"><option value="local">本机资料</option><option value="private">私有资料</option></select></label>'+
      '<div class="actions"><button type="submit" class="btn primary">开始运行</button><button type="button" class="btn" data-close>关闭</button></div><p role="status"></p></form>';
    const form=dialog.querySelector('form'), fields=form.querySelector('[data-workflow-run-fields]'), status=form.querySelector('[role=status]');
    form.elements.message.required=Boolean(saved);
    form.elements.message.value=draft.message || '';
    const knowledge=form.elements.knowledge;
    knowledge.value=draft.knowledge || scope.knowledgeScope;
    knowledge.closest('label').hidden=!NodeUI.needsLibrary(snapshot.graph);
    const inputs=start.data.config.fields.map(field=>{
      const label=document.createElement('label');
      const control=document.createElement(field.type==='boolean'?'select':['list','object'].includes(field.type)?'textarea':'input');
      if(field.type==='boolean')control.append(new Option('未填写',''),new Option('是','true'),new Option('否','false'));
      if(field.type==='number'){control.type='number';control.step='any';}
      if(field.required && field.default===undefined)control.required=true;
      const value=draft.values?.[field.name] ?? field.default;
      control.value=value===undefined?'':typeof value==='string'?value:JSON.stringify(value);
      label.append(document.createTextNode(field.label || field.name),control);fields.append(label);
      return [field,control];
    });
    function persist() {
      write(draftKey,{message:form.elements.message.value,knowledge:knowledge.value,
        values:Object.fromEntries(inputs.map(([field,input])=>[field.name,input.value]))});
    }
    form.oninput=persist;
    dialog.querySelector('[data-close]').onclick=()=>dialog.close();
    dialog.onclose=()=>dialog.remove();
    let signature, key;
    form.onsubmit=async event=>{
      event.preventDefault();
      const submit=form.querySelector('[type=submit]');submit.disabled=true;
      const ownsCanvas=()=>AnalysisMode.current(scope) && graph===snapshot.source && definition===snapshot.definition &&
        document.body.classList.contains('workflow-mobile-canvas');
      try {
        const parameters={};
        for(const [field,input] of inputs) {
          if(!input.value.trim())continue;
          try {parameters[field.name]=field.type==='text'?input.value:JSON.parse(input.value);}
          catch(_){input.focus();throw Error('请检查 '+(field.label || field.name)+' 的输入格式');}
        }
        const choices={model_id:AnalysisMode.read('model'),...(AnalysisMode.read('tools')?{tools:AnalysisMode.tools()}: {})};
        const request={message:form.elements.message.value.trim(),parameters,...choices};
        const next=JSON.stringify([request,knowledge.value]);
        if(next!==signature){signature=next;key=crypto.randomUUID();}
        const endpoint=saved?'workflows/definitions/'+encodeURIComponent(saved.id)+'/runs':'tasks';
        const payload=saved?{...request,key,revision:saved.revision}:{...request,workflow:{mode:'custom',key,graph:snapshot.graph}};
        status.textContent='正在提交…';
        const context={...scope,knowledgeScope:knowledge.value};
        const created=await api(endpoint,'POST',payload,undefined,context);
        if (!saved && scope.key===memoryKey) rememberRun(created.id,runKey);
        if (!ownsCanvas())return;
        dialog.close();
        showRun(created,[]);
        setMessage('本次结果与进度见右侧面板');
        requestAnimationFrame(()=>{if(archivedId===created.id)fitCanvas();});
        try {
          const record=await loadRun(created.id,context);
          if(AnalysisMode.current(scope) && archivedId===created.id) showRun(record.value,record.events,{restore:true});
        } catch(_){if(archivedId===created.id)scheduleArchive(500);}
      } catch(error){
        status.textContent=error.message;
        if(ownsCanvas()) {
          if(error.issues?.length){persist();dialog.close();}
          explainError(error);
        }
      }
      finally{submit.disabled=false;}
    };
    document.body.append(dialog);dialog.showModal();
  }
  function workflowPayload(request) {
    if(AnalysisMode.active()!==professional) return {};
    if(pendingIssues().length){showIssues();throw Error('请提交节点参数后再运行');}
    const serialized=JSON.stringify([request,graph,request.knowledge_query && window.KnowledgeUI?.scope()]);
    if(submitBody!==serialized){submitBody=serialized;submitKey=crypto.randomUUID();}
    return {workflow:graphSubmission(submitKey)};
  }
  function acceptWorkflow(value) {
    if(!value?.metadata?.workflow || AnalysisMode.active() !== professional || !focus) return;
    submitBody=null;submitKey=null;clearArchive();
    task=value;enterRunSurface();deriveRuntime(value);updateWorkspaceTabs();renderCanvas();renderInspector();persistUI();
    rememberRun(value.id,nodeRunKey());
  }

  function currentTestInput() {
    const input=JSON.parse($('task-data').value);
    const cid=$('conversation-id').value;
    return {...input,...(cid?{conversation_id:cid}:{}),...window.KnowledgeUI?.selection(),
      model_id:AnalysisMode.read('model'), ...(AnalysisMode.read('tools') ? {tools:AnalysisMode.tools()} : {}), notify:false};
  }
  function explainError(error) {
    if(error.issues?.length) {
      setMessage(error.message);checkedGraph=graph;diagnostics=error.issues;markIssues();showIssues();return;
    }
    const message=error.message||String(error);
    setMessage(message);
    const id=message.split(' · ').map(part=>part.trim()).find(part=>nodeById(part));
    if(!id || showingRun())return;
    inspectorTab='config';selectNode(id,true);
    const form=$('workflow-node-editor');
    if(!form)return;
    const field=[...form.querySelectorAll('[data-reference],textarea,input,select')].find(item=>
      item.value && /[\w-]+\.[\w-]+/.test(item.value) && (item.matches('[data-reference]') && message.includes(item.value) ||
        NodeUI.references({template:item.value}).some(ref=>message.includes(ref))));
    const groups=[[/HTTP.{0,5}(目标|凭据)/,'[data-config-key="target"]'],[/等待时限/,'[data-config-key="wait_seconds"]'],
      [/人工介入说明/,'[data-config-key="prompt"]'],[/停止条件/,'[data-config-key="until"]'],[/计算表达式/,'[data-config-key="expression"]'],
      [/次数上限/,'[data-config-key="limit"]'],[/HTTP 超时/,'[data-config-key="timeout"]'],
      [/工具|授权/,'[name="binding"],[name="agent_tools"],[name="tool"]'],[/模型/,'[data-config-key="model"],[name="model"]'],
      [/提示词|模板|变量格式/,'[data-config-key="template"]'],[/比较值|关键词|条件无效/,'[data-config-key="match"]'],
      [/出口/,'[data-config-key="cases"]'],[/默认值/,'[data-config-key="default"]'],[/变量名/,'[data-config-key="name"],[data-config-key="fields"]'],
      [/字段/,'[data-config-key="fields"]'],[/上游变量|来源/,'[data-reference]'],[/检索条数/,'[data-config-key="limit"]'],
      [/结束索引/,'[data-config-key="end"]'],[/索引/,'[data-config-key="start"]'],[/输出格式|JSON 输出/,'[data-config-key="format"]']];
    const selector=groups.find(([pattern])=>pattern.test(message))?.[1];
    const namedCase=[...form.querySelectorAll('.workflow-config-row')].find(row=>message.split(' · ').slice(1,-1).includes(row.querySelector('[data-config-key="cases"]')?.value));
    const matchingField=selector && [...form.querySelectorAll(selector)].find(item=>!item.disabled && !item.closest('[hidden]'));
    revealField((namedCase && selector && namedCase.querySelector(selector)) || field || matchingField,message);
    form.querySelector('.workflow-node-feedback').textContent=message;
  }
  async function previewWorkflow() {
    const scope = AnalysisMode.capture(), source=graph;
    const matching=()=>AnalysisMode.current(scope) && graph===source && !showingRun();
    try {
      const variables=NodeUI.isVariable(graph), data=variables ? {model_id:AnalysisMode.read('model'),
        ...(AnalysisMode.read('tools') ? {tools:AnalysisMode.tools()} : {})} : currentTestInput();
      const enabled=$('task-notify').checked, recipients=window.MailRecipients?.values()||[];
      const request=variables ? data : data.prediction || data.conversation_id ? {...data,notify:enabled,
        recipient:recipients[0]||$('task-recipient').value||null,recipients} : undefined;
      const result=await api('workflows/preview','POST',{workflow:graphSubmission(crypto.randomUUID()),request},undefined,scope);
      if (!matching()) return;
      const list=result.nodes.map(node=>`${nodeById(node.id)?.data.label||node.id} · ${{ready:'可运行',skip:'跳过',blocked:'受阻',conditional:'待条件'}[node.state]}${node.reason?'（'+node.reason+'）':''}`);
      setMessage('校验通过 · '+result.version.slice(0,8));
      const dialog=document.createElement('dialog');dialog.className='plugin-dialog workflow-run-dialog';
      const heading=document.createElement('h3');heading.textContent='运行前计划';
      dialog.append(heading,terms(list.map(value=>['节点',value])),makeButton('关闭',()=>dialog.close()));
      dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();
    } catch(error){if (matching()) explainError(error);}
  }
  async function loadRun(id, scope) {
    const value=await api('tasks/'+encodeURIComponent(id),'GET',undefined,undefined,scope), events=[];
    let after=0;
    for(;;) {
      const page=await api(`tasks/${encodeURIComponent(id)}/events?after=${after}`,'GET',undefined,undefined,scope);
      events.push(...page.events);
      if(page.events.length<100) break;
      after=page.events.at(-1).seq;
    }
    return {value,events};
  }
  const rememberRun=(id,key)=>write(key,[id,...(read(key)||[]).filter(value=>value!==id)].slice(0,24));
  async function loadLastRun({refresh=false} = {}) {
    const node=nodeById(selected);
    if (!node || showingRun() || !inspectorOpen || inspectorTab!=='runtime' || AnalysisMode.active()!==professional) return;
    const flow=definition?.id, key=nodeRunKey(), scope=AnalysisMode.capture();
    if (!refresh && lastRun?.pending && lastRun.node===node.id && lastRun.kind===node.data.type && lastRun.key===key) return;
    clearTimeout(lastRunTimer);
    const request=++lastRunRequest;
    const matching=()=>request===lastRunRequest && selected===node.id && nodeById(selected)?.data.type===node.data.type &&
      nodeRunKey()===key && AnalysisMode.current(scope) && !showingRun() && inspectorTab==='runtime' && inspectorOpen;
    const context={node:node.id,kind:node.data.type,key};
    lastRun={...context,pending:true,record:lastRun?.node===node.id && lastRun.kind===node.data.type && lastRun.key===key?lastRun.record:null};
    renderNodeRuntime(node);
    try {
      const query=new URLSearchParams({node:node.id,kind:node.data.type});
      const page=flow?await api('workflows/definitions/'+encodeURIComponent(flow)+'/runs?'+query,'GET',undefined,undefined,scope):null;
      if(!matching())return;
      const saved=page?.items[0] && await loadRun(page.items[0].id,scope);
      let local;
      for(const id of read(key) || []) {
        if (!matching()) return;
        try {
          const candidate=await loadRun(id,scope), workflow=candidate.value.metadata?.workflow;
          if(candidate.value.id===id && workflow?.graph?.nodes.some(item=>item.id===node.id && item.data.type===node.data.type) &&
              nodeEvents(candidate,node).some(event=>['step','node_result'].includes(event.kind) &&
                ['running','needs_input','completed','degraded','failed','canceled'].includes(event.status))) { local=candidate;break; }
        } catch(error) {if(!/NOT_FOUND|FORBIDDEN/.test(error.message))throw error;}
      }
      if(!matching())return;
      const created=record=>record?.value.metadata?.workflow?.started_at || record?.value.status?.timestamp || '';
      const record=created(local)>created(saved)?local:saved || local;
      lastRun={...context,record};renderNodeRuntime(node);
      lastRunTimer=setTimeout(()=>loadLastRun({refresh:true}),['submitted','working'].includes(record?.value.status.state)?900:5000);
    } catch(error) {
      if(matching()){lastRun={...context,error:error.message};renderNodeRuntime(node);}
    } finally {
      if(request===lastRunRequest && lastRun?.pending)lastRun.pending=false;
    }
  }
  async function openRecordedRun(flowId,id) {
    const scope=AnalysisMode.capture(), request=++recordRequest;
    const matches=()=>request===recordRequest && AnalysisMode.current(scope) && definition?.id===flowId;
    try {
      const run=await loadRun(id,scope);
      if(matches() && run.value.metadata?.workflow?.flow?.id===flowId) {
        showRun(run.value,run.events);
        requestAnimationFrame(fitCanvas);
      }
    } catch(error){if(matches()) explainError(error);}
  }
  let archiveTimer;
  function clearArchive() {
    clearTimeout(archiveTimer);
    archived = archivedId = null; archivedEvents = [];
  }
  function showRun(value,events,{restore = false,nodeId} = {}) {
    enterRunSurface();archived=value;archivedId=value.id;archivedEvents=events;
    if (!restore) {
      selected=(nodeId && nodeById(nodeId) ? nodeId : value.metadata?.workflow?.debug) || shownGraph().nodes[0]?.id || '';
      showCanvasPanel('inspector',true);
    }
    deriveRuntime(task);updateWorkspaceTabs();renderCanvas();renderInspector();persistUI();
    if (['working', 'submitted'].includes(value.status.state)) scheduleArchive();
  }
  function scheduleArchive(delay = 700) {
    clearTimeout(archiveTimer);
    const id = archivedId, scope = AnalysisMode.capture();
    if (!id || scope.mode !== professional || workSurface !== 'run') return;
    archiveTimer = setTimeout(async () => {
      try {
        const run = await loadRun(id, scope);
        if (AnalysisMode.current(scope) && archivedId === id && workSurface === 'run') showRun(run.value, run.events, {restore:true});
      } catch (error) {
        if (!AnalysisMode.current(scope) || archivedId !== id) return;
        if (/NOT_FOUND|FORBIDDEN/.test(error.message)) { clearArchive(); persistUI(); }
        else scheduleArchive(2500);
      }
    }, delay);
  }
  async function chooseRun() {
    const scope = AnalysisMode.capture();
    let selectedRun;
    const endpoint=definition?.id?'workflows/definitions/'+encodeURIComponent(definition.id)+'/runs':'workflows/runs';
    const dialog=document.createElement('dialog');dialog.className='plugin-dialog workflow-run-dialog';
    const heading=document.createElement('h3');heading.textContent='运行记录';dialog.append(heading);
    const list=document.createElement('div');list.className='workflow-run-list';
    let cursor=null;
    const next=makeButton('加载更早记录',()=>read());
    async function read() {
      next.disabled=true;
      try {
        const data=await api(endpoint+(cursor?'?before='+cursor:''), 'GET', undefined, undefined, scope);
        if (!AnalysisMode.current(scope) || !dialog.open) return;
        for(const item of data.items) {
          list.append(makeButton(`${item.debug?'单节点调试':item.summary||item.subject||'任务'} · ${item.status.state} · ${item.version?.slice(0,8)||'旧任务'} · ${item.status.timestamp}`,async()=>{
            selectedRun=item.id;
            try {
              const run=await loadRun(item.id,scope);
              if (selectedRun===item.id && AnalysisMode.current(scope) && dialog.open) { dialog.close(); showRun(run.value,run.events); }
            } catch(error){if (selectedRun===item.id && AnalysisMode.current(scope) && dialog.open) explainError(error);}
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
    const records = read('workflow-library') || [];
    for(const entry of records) {
      list.append(makeButton(entry.label,()=>{
        if (dirty && !confirm('打开其他流程会替换当前草稿。继续吗？')) return;
        try {
          history.push(clone(graph));redoHistory=[];graph=normalizeGraph(entry.graph);nodeDrafts.clear();dirty=true;workSurface='edit';
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
        write('workflow-library',[saved,...records.filter(entry=>entry.label!==label)].slice(0,20));
        dialog.close();setMessage('已另存自定义流程 '+label);
      } catch(error){form.querySelector('[role=status]').textContent='无法保存流程 · '+error.message;}
    };
    dialog.append(title,list,form,makeButton('关闭',()=>dialog.close()));dialog.onclose=()=>dialog.remove();
    document.body.append(dialog);dialog.showModal();
  }
  function openDebug(node) {
    if(debugDialog?.open) return;
    const scope = AnalysisMode.capture();
    const dialog=document.createElement('dialog');debugDialog=dialog;dialog.className='plugin-dialog workflow-run-dialog';
    dialog.innerHTML='<form><h3></h3><label>测试任务 JSON<textarea name="request" rows="10" required></textarea></label>'+
      '<p class="hint">使用输入运行本次调试所依赖的上游节点。归档和投递在调试中跳过。</p>'+
      '<button type="submit">运行节点测试</button><button type="button" data-close>关闭</button><p role="status"></p></form>';
    const form=dialog.querySelector('form'), status=dialog.querySelector('[role=status]');
    dialog.querySelector('h3').textContent='单节点调试 · '+node.data.label;
    const required=graph.nodes.find(item=>item.data.type==='input')?.data.config.fields?.filter(field=>field.required && !Object.hasOwn(field,'default')) || [];
    if(required.length)form.querySelector('.hint').append(' 必填参数：'+required.map(field=>`${field.label || field.name} (${field.name})`).join('、'));
    try {form.elements.request.value=JSON.stringify(NodeUI.isVariable(graph) ?
      {message:'',parameters:{},model_id:AnalysisMode.read('model')} : currentTestInput(),null,2);
    } catch(_){form.elements.request.value='{}';}
    const inputKey = canvasKey('debug-input.' + node.id), runKey=nodeRunKey(), debugGraph=graph;
    form.elements.request.value = read(inputKey) ?? form.elements.request.value;
    form.elements.request.oninput = () => write(inputKey, form.elements.request.value);
    debugNode = node.id;
    let currentId=null, frozenKey=null, previous=null;
    const cancel=makeButton('取消调试',async()=>{
      try {if(currentId) await api(`tasks/${currentId}/cancel`,'POST',{},undefined,scope);} catch(error){status.textContent=error.message;}
    });
    cancel.disabled=true;
    form.append(cancel);
    dialog.querySelector('[data-close]').onclick=()=>dialog.close();
    form.onsubmit=async event=>{
      event.preventDefault();const submit=form.querySelector('[type=submit]');submit.disabled=true;
      try {
        const raw=JSON.parse(form.elements.request.value), text=form.elements.request.value;
        if(previous!==text){previous=text;frozenKey=crypto.randomUUID();}
        const created=await api('tasks','POST',{...raw,workflow:graphSubmission(frozenKey,node.id)},undefined,scope);
        if (scope.key !== memoryKey) return;
        rememberRun(created.id,runKey);
        if(graph!==debugGraph)return;
        archivedId=created.id;enterRunSurface();debugNode=null;persistUI();
        if (!AnalysisMode.current(scope) || !dialog.open) {
          if (AnalysisMode.active() === professional) scheduleArchive(0);
          return;
        }
        currentId=created.id;cancel.disabled=false;status.textContent='调试执行中';
        let record=await loadRun(currentId,scope);
        while (AnalysisMode.current(scope) && dialog.open && ['submitted','working'].includes(record.value.status.state)) {
          await new Promise(resolve=>setTimeout(resolve,400));record=await loadRun(currentId,scope);
        }
        if(AnalysisMode.current(scope) && dialog.open){dialog.close();showRun(record.value,record.events);}
      } catch(error){status.textContent=error.message;}
      finally{submit.disabled=false;cancel.disabled=true;}
    };
    dialog.onclose=()=>{
      write(inputKey, form.elements.request.value);
      if (AnalysisMode.current(scope)) debugNode=null;
      if (currentId && AnalysisMode.active() === professional && !archived) scheduleArchive(0);
      dialog.remove();
    };document.body.append(dialog);dialog.showModal();
  }
  function updateWorkspaceTabs() {
    for(const button of focus.querySelectorAll('[data-workflow-surface]')) button.setAttribute('aria-pressed',String(button.dataset.workflowSurface===workSurface));
    focus.dataset.workflowSurface=workSurface;
    for(const button of focus.querySelectorAll('[data-workflow-action]')) button.hidden=showingRun();
    syncCanvasPanels();
  }
  function showCanvasPanel(panel, open) {
    if (panel==='library') {
      libraryOpen=open;
      if(open&&narrowCanvas.matches)inspectorOpen=false;
    } else {
      inspectorOpen=open;
      if(open&&narrowCanvas.matches)libraryOpen=false;
    }
    syncCanvasPanels();if(workspaceLoaded)persistUI();
  }
  function syncCanvasPanels() {
    const library=Boolean(libraryOpen || selectingPort)&&!showingRun();
    focus.querySelector('.desktop-flow-palette').hidden=!library;
    $('desktop-workflow-inspector').hidden=!inspectorOpen;
    $('workflow-library-toggle').disabled=showingRun();
    $('workflow-library-toggle').setAttribute('aria-expanded',String(library));
    $('workflow-inspector-toggle').setAttribute('aria-expanded',String(inspectorOpen));
    focus.classList.toggle('inspector-open',inspectorOpen);
    canvasUI?.sync();
  }
  function updateInspectorTabs() {
    const current=showingRun()?'runtime':inspectorTab;
    for(const button of focus.querySelectorAll('[data-node-view]')) {
      const view=button.dataset.nodeView;
      button.disabled=showingRun()&&view==='config';
      button.setAttribute('aria-pressed',String(view===current));
      button.setAttribute('aria-selected',String(view===current));
      button.tabIndex=view===current?0:-1;
      $(`desktop-node-${view}`).hidden=view!==current;
    }
  }
  function layoutWorkspace(toolbar, palette) {
    const host=$('desktop-workflow-inspector');
    host.innerHTML=`<header class="workflow-node-heading">
      <div class="workflow-node-title-row"><span id="desktop-node-icon"></span><div class="workflow-node-title"><h3 id="desktop-node-heading"></h3><small id="desktop-node-type"></small></div>
        <div class="workflow-node-heading-actions" id="desktop-node-actions">
          <button type="button" id="desktop-node-test" aria-label="单测所选节点" title="单测所选节点"><span class="sr-only">单测所选节点</span></button>
          <button type="button" id="desktop-node-copy" aria-label="复制节点" title="复制节点">⧉</button>
          <button type="button" id="desktop-node-delete" aria-label="删除节点" title="删除节点">⌫</button>
        </div><button type="button" id="desktop-node-close" aria-label="关闭节点配置" title="关闭节点配置">×</button>
      </div>
      <textarea id="desktop-node-description" name="detail" form="workflow-node-editor" maxlength="400" rows="2" aria-label="节点描述" placeholder="添加描述…"></textarea>
      </header><div class="workflow-node-tabs" role="tablist" aria-label="节点详情视图">
        <button type="button" id="workflow-node-config-tab" data-node-view="config" role="tab" aria-controls="desktop-node-config">设置</button>
        <button type="button" id="workflow-node-runtime-tab" data-node-view="runtime" role="tab" aria-controls="desktop-node-runtime">上次运行</button>
        <small id="desktop-node-state" role="status"></small>
      </div><section id="desktop-node-config" class="workflow-node-body" role="tabpanel" aria-labelledby="workflow-node-config-tab"></section>
      <section id="desktop-node-runtime" class="workflow-node-body" role="tabpanel" aria-labelledby="workflow-node-runtime-tab" tabindex="0"></section>`;
    function closeInspector() {
      showCanvasPanel('inspector',false);clearTimeout(lastRunTimer);
      const target=narrowCanvas.matches?$('workflow-inspector-toggle'):nodeElement(selected);
      (target || $('workflow-inspector-toggle')).focus({preventScroll:true});
    }
    $('desktop-node-close').onclick=closeInspector;
    $('desktop-node-delete').onclick=()=>removeNode();
    for(const button of host.querySelectorAll('[data-node-view]')) button.onclick=()=>{
      inspectorTab=button.dataset.nodeView;renderInspector();persistUI();
      if(inspectorTab==='runtime')loadLastRun();
      else clearTimeout(lastRunTimer);
    };
    host.onkeydown=event=>{
      if(event.key==='Escape'){event.stopPropagation();closeInspector();return;}
      if(!event.target.matches('[data-node-view]') || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();
      const tabs=[...host.querySelectorAll('[data-node-view]:not(:disabled)')];
      const next=tabs[event.key==='Home'?0:event.key==='End'?tabs.length-1:(tabs.indexOf(event.target)+1)%tabs.length];
      next.focus();next.click();
    };
    const rail=document.createElement('div');rail.className='workflow-canvas-rail';
    palette.id='workflow-node-library';
    document.addEventListener('pointerdown',event=>{
      if((selectingPort || replacement) && !palette.contains(event.target) && !event.target.closest('.desktop-flow-port, [data-edge-insert], #workflow-library-toggle')) {
        closeNodePicker();
      }
    });
    for(const [id,label,target,panel] of [['workflow-library-toggle','节点库',palette.id,'library'],['workflow-inspector-toggle','详情',host.id,'inspector']]) {
      const button=makeButton(label,()=>{
        const open=button.getAttribute('aria-expanded')!=='true';
        if(panel==='library'){
          if(open)openLibrary(centerCanvas());else {closeNodePicker();showCanvasPanel(panel,false);}
          return;
        }
        showCanvasPanel(panel,open);refreshLibrary();
        if(panel==='inspector' && inspectorOpen)loadLastRun();
      });
      button.id=id;button.setAttribute('aria-controls',target);rail.append(button);
    }
    const redoButton=makeButton('重做',redo);redoButton.id='desktop-workflow-redo';
    rail.append($('desktop-workflow-undo'),redoButton);
    const add=toolbar.querySelector('[data-workflow-action="add"]');
    add.textContent='添加节点';add.onclick=()=>openLibrary();
    const blank=makeButton('添加节点',()=>openLibrary());
    blank.id='workflow-canvas-empty';blank.className='btn primary';blank.hidden=true;
    $('desktop-workflow-canvas').append(blank);
    const viewport=toolbar.querySelector('.desktop-flow-viewport-tools');
    focus.append(rail,viewport);
    rail.setAttribute('role','toolbar');rail.setAttribute('aria-label','画布工具栏');
    CanvasUI.decorate($('workflow-inspector-toggle'),'◫','详情');
    CanvasUI.decorate($('desktop-workflow-undo'),'↶','撤销','Ctrl/Cmd + Z');
    CanvasUI.decorate(redoButton,'↷','重做','Ctrl/Cmd + Shift + Z');
    const board=$('desktop-workflow-canvas');
    canvasUI=CanvasUI.install({board,rail,panel:host,button:makeButton,
      data:()=>showingRun()?null:graph,node:nodeById,selected:()=>nodeById(selected),owner:()=>AnalysisMode.capture().key,
      editable:()=>AnalysisMode.active()===professional && !showingRun() && board.getClientRects().length,
      commit,message:setMessage,copy:safeLegacy,duplicate:duplicateNode,remove:removeNode,removeEdge:removeConnection,run:runWorkflow,undo,redo,
      fit:fitCanvas,export:exportWorkflow,add:openLibrary,select:id=>selectNode(id),
      world:event=>worldPoint(canvasPoint(board,event)),
      screen:point=>{const rect=board.getBoundingClientRect();return {x:rect.left+canvasPan.x+point.x*canvasZoom,y:rect.top+canvasPan.y+point.y*canvasZoom};},
      center:centerCanvas,
      canvasFocus:()=>board.focus({preventScroll:true}),
      annotationFocus:()=>{if(!desktop.matches && inspectorOpen)showCanvasPanel('inspector',false);},
      boxSelect:ids=>{selected=ids[0] || '';renderCanvas();renderInspector();persistUI();},
      panning:()=>canvasUI?.panning(),
      debugReason:node=>node.data.enabled===false?'节点已停用':workflowCatalog?.nodes[node.data.type]?.testable?'':'此节点不支持单步调试',
      debug:node=>{if(readyToSave())openDebug(node);},
      replace:(node,point)=>{openLibrary();replacement={id:node.id,point,graph};refreshLibrary();}});
    narrowCanvas.addEventListener('change',event=>{if(event.matches&&inspectorOpen&&libraryOpen)showCanvasPanel('library',false);});
    const menu=document.createElement('details');menu.className='workflow-file-menu';
    const summary=document.createElement('summary');summary.textContent='流程管理';
    const actions=document.createElement('div');actions.className='workflow-file-actions';
    actions.append(...toolbar.querySelectorAll('[data-workflow-action="copy"], [data-workflow-action="restore"], [data-workflow-action="import"], [data-workflow-action="export"], .workflow-library-action'));
    actions.addEventListener('click',()=>{menu.open=false;});
    menu.append(summary,actions);toolbar.append(menu);
    const modes=document.createElement('div');modes.className='workflow-surface-switch';modes.setAttribute('role','group');modes.setAttribute('aria-label','工作流视图');
    modes.append(...toolbar.querySelectorAll('[data-workflow-surface]'));
    const status=focus.querySelector('.desktop-flow-toolbar-status');
    status.querySelector('strong').textContent='流程画布';status.after(modes);
  }
  function openLibrary(position=null) {
    closeNodePicker();
    pickerPlacement=position;
    showCanvasPanel('library',true);
    refreshLibrary();
    focus.querySelector('.desktop-flow-palette input').focus({preventScroll:true});
  }
  function centerCanvas() {
    const board=$('desktop-workflow-canvas');
    return worldPoint({x:board.clientWidth/2-100,y:board.clientHeight/2-48});
  }
  function openNodePicker(source,anchor,point) {
    const palette=$('workflow-node-library');
    if(!palette || showingRun())return;
    pickerPlacement=replacement=null;
    const rect=anchor.getBoundingClientRect();
    selectingPort={...source,anchor,point:point || {x:rect.right,y:rect.top+rect.height/2}};
    palette.querySelector('input').value='';
    syncCanvasPanels();refreshLibrary();
    palette.querySelector('input').focus({preventScroll:true});
  }
  function closeNodePicker(restoreFocus=false) {
    if(!selectingPort && !replacement && !pickerPlacement)return;
    const anchor=selectingPort?.anchor;
    if(replacement)libraryOpen=false;
    selectingPort=replacement=pickerPlacement=null;
    const palette=$('workflow-node-library');
    if(!palette)return;
    palette.querySelector('input').value='';
    syncCanvasPanels();refreshLibrary();
    if(restoreFocus)(anchor?.isConnected?anchor:$('workflow-library-toggle'))?.focus({preventScroll:true});
  }
  function positionNodePicker(palette,point) {
    const layout=palette.offsetParent?.getBoundingClientRect();
    if(!layout)return;
    const canvas=$('desktop-workflow-canvas').getBoundingClientRect();
    const width=Math.min(242,layout.width-16);
    const left=Math.max(layout.left+8,Math.min(point.x+10,layout.right-width-8));
    const top=Math.max(canvas.top+7,Math.min(point.y+12,layout.bottom-250));
    palette.style.setProperty('--workflow-picker-left',`${left-layout.left}px`);
    palette.style.setProperty('--workflow-picker-top',`${top-layout.top}px`);
    palette.style.setProperty('--workflow-picker-height',`${Math.min(390,layout.bottom-top-8)}px`);
  }
  const variableDraft = () => NodeUI.isVariable(graph) || !graph.nodes.length ||
    (!graph.nodes.some(node=>node.data.type==='input') && graph.nodes.some(node=>NodeUI.variableTypes.includes(node.data.type)));
  function pickNode(kind) {
    if(replacement){replaceNode(replacement,kind);return;}
    const position=pickerPlacement;
    if (!variableDraft() && NodeUI.variableTypes.includes(kind)) {
      const origin=definition;
      if (!useDefinition(null,{empty:true}))return;
      addNode(kind,{},null,position);
      setMessage(`已在变量画布添加 ${NodeUI.label(kind)}，${origin?.name || '分析流程'}草稿已保留`);
      return;
    }
    addNode(kind,{},selectingPort,position);
  }
  function refreshLibrary() {
    const palette=focus?.querySelector('.desktop-flow-palette');
    if(!palette?.querySelector('input'))return;
    const query=palette.querySelector('input').value.trim().toLocaleLowerCase(), source=selectingPort && nodeById(selectingPort.id);
    const insertion=selectingPort?.edge && graph.edges.find(edge=>edge.id===selectingPort.edge);
    const context=source && (!selectingPort.edge || insertion);
    palette.toggleAttribute('data-context',Boolean(context || replacement));
    if(context || replacement) {
      palette.setAttribute('role','dialog');
      palette.setAttribute('aria-label',replacement?'更改节点':insertion?'插入节点':'添加下游节点');
      positionNodePicker(palette,(replacement || selectingPort).point);
    } else {
      palette.removeAttribute('role');palette.setAttribute('aria-label','节点库');
    }
    for(const edge of focus.querySelectorAll('.workflow-edge-group[data-picking]'))edge.removeAttribute('data-picking');
    if(insertion)focus.querySelector('[data-edge-insert="'+CSS.escape(insertion.id)+'"]')?.parentElement.setAttribute('data-picking','');
    palette.querySelector('.eyebrow').textContent=replacement?'更改节点':context?(insertion?'插入节点':'添加下游节点'):'节点库';
    const variables=variableDraft();
    let count=0, mismatch=false;
    for(const group of palette.querySelectorAll('section')) {
      for(const button of group.querySelectorAll('[data-node-type]')) {
        const kind=button.dataset.nodeType, spec=workflowCatalog?.nodes[kind];
        mismatch ||= Boolean(workflowCatalog && !spec);
        const separate = !variables && NodeUI.variableTypes.includes(kind);
        const base=kind==='input' ? !graph.nodes.some(node=>node.data.type==='input') : variables ? spec?.variables : true;
        const bridge={data:{type:kind,config:{fallback:true}}};
        const fits=!insertion || insertionPort(bridge,nodeById(insertion.target),variables);
        const allowed=replacement?Boolean(base && spec && !separate && kind!=='input' && kind!==nodeById(replacement.id)?.data.type):
          Boolean(graph.nodes.length<24 && (!source || graph.edges.length<64) && base && spec && fits &&
            (!source || compatible(source,kind,selectingPort.port,variables)));
        button.hidden=!workflowCatalog || !button.dataset.label.toLocaleLowerCase().includes(query) || Boolean((source || replacement) && !allowed);
        button.disabled=!allowed;
        const badge=button.querySelector('small');
        badge.hidden=allowed&&!separate;
        badge.textContent=allowed?'变量画布':spec?(kind==='input'?'入口已存在':'分析流程'):'版本不一致';
        button.title=allowed?(separate?'在独立变量画布中添加，保留当前草稿':button.dataset.label):
          spec?'当前流程或端口不适用':'当前控制台的节点目录缺少此类型';
        if(!button.hidden)count++;
      }
      group.hidden=!group.querySelector('[data-node-type]:not([hidden])');
    }
    const note=palette.querySelector('[role=status]');
    const outlet=source && NodeUI.ports(source,variables).find(port=>port.id===selectingPort.port);
    const location=insertion ? source.data.label+' → '+nodeById(insertion.target)?.data.label :
      [source?.data.label,outlet?.label].filter(Boolean).join(' · ');
    palette.querySelector('[data-catalog-retry]').hidden=catalogLoading || !(catalogFailed || mismatch);
    note.textContent=catalogLoading?'正在读取节点目录…':catalogFailed?'节点目录读取失败，可重试。':
      mismatch?'控制台前后端版本不一致。更新后端后重新读取目录。':replacement?(count?'选择新的节点类型':'没有匹配的节点'):
      graph.nodes.length>=24 ? '已达到 24 个节点的上限' : source && graph.edges.length>=64 ? '已达到 64 条连线的上限' :
      source ? (count ? location : '没有匹配的兼容节点，请调整搜索') :
      !count ? '没有匹配的节点，试试其他关键词' : variables ? '' : '选择标有「变量画布」的节点可在独立画布添加。';
  }
  async function loadWorkflowCatalog() {
    if(catalogLoading)return;
    catalogLoading=true;refreshLibrary();
    try {
      const data=await api('workflows/catalog');
      if(!data?.nodes || !Array.isArray(data.system?.nodes))throw Error('节点目录格式无效');
      workflowCatalog=data;systemTemplate=data.system;catalogFailed=false;
      if(graph.mode==='system' && !dirty){
        graph=savedGraph=defaultGraph();
        requestAnimationFrame(()=>{if(mode==='focus' && !hasViewport) fitCanvas();});
      }
      renderCanvas();renderInspector();
    } catch(error) {
      catalogFailed=true;setMessage('节点目录读取失败 · '+error.message);
    } finally {
      catalogLoading=false;refreshLibrary();
    }
  }
  async function runWorkflow() {
    canvasUI?.flush();
    if(!await checkWorkflow({requireClean:true}))return;
    if(!graph.nodes.length){setMessage('先添加节点并连接到输出节点');openLibrary();return;}
    if(!variableDraft()){$('task-form').requestSubmit();return;}
    if(!NodeUI.isVariable(graph)){setMessage('请先添加用户输入节点');openLibrary();return;}
    runVariableCanvas();
  }
  function workflowControls() {
    const toolbar=focus.querySelector('.desktop-flow-toolbar-actions');
    for (const [key,label] of [['edit','编辑'],['debug','调试'],['run','运行记录']]) {
      const button=makeButton(label,()=>{
        if(key==='run'){chooseRun();return;}
        clearArchive();workSurface=key;restoreEditorView();
        if(!nodeById(selected)) selected=graph.nodes[0]?.id||'';
        deriveRuntime(task);updateWorkspaceTabs();renderCanvas();renderInspector();persistUI();loadLastRun();
      });
      button.dataset.workflowSurface=key;toolbar.insertBefore(button,toolbar.querySelector('[data-workflow-action]'));
    }
    const copy=makeButton('复制系统模板',()=>{
      history.push(clone(graph));redoHistory=[];graph=customCopy(defaultGraph());selected=graph.nodes[0].id;dirty=true;nodeDrafts.clear();
      persistDraft();setMessage('模板副本可编辑并执行');renderCanvas();renderInspector();
    });
    copy.dataset.workflowAction='copy';
    const library=makeButton('自定义流程',workflowLibrary);library.className='workflow-library-action';
    const saveToChat=makeButton('保存为可选流程',()=>window.WorkflowChat?.saveCanvas(canvasSnapshot()));
    saveToChat.className='workflow-library-action';
    const backToDirectory=makeButton('返回流程列表',()=>window.WorkflowChat?.showDirectory());
    backToDirectory.className='workflow-library-action';
    toolbar.prepend(makeButton('校验流程',()=>checkWorkflow({show:true})),makeButton('校验计划',previewWorkflow),copy,library,saveToChat,backToDirectory);
    $('desktop-workflow-validation').onclick=()=>checkWorkflow({show:true});
    $('desktop-workflow-validation').setAttribute('role','button');$('desktop-workflow-validation').tabIndex=0;
    $('desktop-workflow-validation').onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();checkWorkflow({show:true});}};
    const run=makeButton('运行流程',runWorkflow);run.className='workflow-run-primary';toolbar.prepend(run);
    const palette=focus.querySelector('.desktop-flow-palette'), search=document.createElement('input');
    const pickerHeading=document.createElement('div');pickerHeading.className='workflow-picker-heading';
    const title=palette.querySelector('.eyebrow');
    title.replaceWith(pickerHeading);
    search.type='search';search.placeholder='搜索节点';search.setAttribute('aria-label','搜索节点库');
    pickerHeading.append(title,search);
    const hint=text(pickerHeading,'p','','hint');hint.setAttribute('role','status');
    const retry=makeButton('重新读取节点目录',loadWorkflowCatalog);
    retry.dataset.catalogRetry='';retry.hidden=true;pickerHeading.append(retry);
    for(const [label,,types] of NodeUI.groups) {
      const group=document.createElement('section');
      text(group,'h4',label);
      for(const [kind,name] of types) {
        const item=makeButton('',()=>pickNode(kind));item.dataset.nodeType=kind;item.dataset.label=name;
        item.append(NodeUI.icon(kind));text(item,'span',name);text(item,'small','不可用');
        group.append(item);
      }
      palette.append(group);
    }
    search.oninput=refreshLibrary;
    palette.onkeydown=event=>{
      if(event.key==='Escape') {
        if(selectingPort || replacement)closeNodePicker(true);
        else {showCanvasPanel('library',false);$('workflow-library-toggle').focus();}
        return;
      }
      if(!['ArrowDown','ArrowUp','Enter'].includes(event.key))return;
      const rows=[...palette.querySelectorAll('[data-node-type]:not([hidden]):not(:disabled)')];
      if(!rows.length)return;
      if(event.key==='Enter') {
        if(event.target===search){event.preventDefault();rows[0].click();}
        return;
      }
      const index=rows.indexOf(event.target), delta=event.key==='ArrowDown'?1:-1;
      event.preventDefault();rows[(index<0?(delta>0?0:rows.length-1):(index+delta+rows.length)%rows.length)].focus();
    };
    layoutWorkspace(toolbar,palette);
    updateWorkspaceTabs();
    loadWorkflowCatalog();
  }

  function saveCanvasViewport() {
    hasViewport = true;
    write(canvasKey('canvas-pan'), canvasPan);
    write(canvasKey('canvas-zoom'), canvasZoom);
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
    canvas.style.setProperty('--workflow-port-size',Math.min(38,24/canvasZoom)+'px');
    put('desktop-workflow-zoom', canvasZoom < .01 ? '<1%' : `${Math.round(canvasZoom * 100)}%`);
    positionEdgeInsertButtons($('desktop-workflow-edge-paths'));
    canvasUI?.sync();
  }

  function fitCanvas() {
    const canvas = $('desktop-workflow-canvas');
    const {nodes,canvas:details}=shownGraph();
    const markers=[...(details?.notes || []),...(details?.comments || [])];
    if (!canvas.clientWidth || !canvas.clientHeight || !(nodes.length || markers.length)) return;
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const node of nodes) {
      const {x, y} = node.position, element = nodeElement(node.id);
      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x + (element?.offsetWidth || 208));
      bottom = Math.max(bottom, y + (element?.offsetHeight || 126));
    }
    for(const {x,y,width=28,height=28} of markers){
      left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x+width);bottom=Math.max(bottom,y+height);
    }
    const rect = canvas.getBoundingClientRect();
    const inspectorLeft = $('desktop-workflow-inspector').getBoundingClientRect().left - rect.left;
    const toolbarBottom = focus.querySelector('.desktop-flow-toolbar').getBoundingClientRect().bottom - rect.top;
    const composerTop = $('analysis-composer').getBoundingClientRect().top - rect.top;
    const palette=focus.querySelector('.desktop-flow-palette').getBoundingClientRect();
    const rail=focus.querySelector('.workflow-canvas-rail').getBoundingClientRect();
    const viewLeft = desktop.matches ? Math.max(20,Math.max(palette.right,rail.right)-rect.left+12) : 24;
    const viewTop = Math.max(20, toolbarBottom + 16);
    const viewRight = desktop.matches && inspectorLeft > 120 ? inspectorLeft - 16 : canvas.clientWidth - 20;
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
      const hand=canvasUI?.panning();
      if(event.button!==0 || canvasDrag || edgeDrag || event.target.closest('.canvas-note-tools,.canvas-context-menu,.canvas-comment-panel') ||
          !hand && event.target.closest('[data-edge-id],[data-edge-hit],[data-edge-insert],button,.canvas-note') ||
          hand && event.target.closest('textarea,input,select,button'))return;
      const element = !hand && event.target.closest('.desktop-flow-node');
      if (element && showingRun()) {selectNode(element.dataset.workflowNode,true);return;}
      const node = element && nodeById(element.dataset.workflowNode);
      const start = canvasPoint(canvas, event);
      const world = worldPoint(start);
      canvasDrag = {pointerId:event.pointerId,id:node?.id,box:!node&&!hand&&!showingRun(),start,pan:canvasPan,preview:null,frame:null,lastFrame:null};
      if (node) canvasDrag.offset = {x: world.x - node.position.x, y: world.y - node.position.y};
      else if(!canvasDrag.box)canvas.classList.add('panning');
      canvas.focus({preventScroll:true});
      canvas.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    canvas.addEventListener('pointermove', event => {
      if (event.pointerId !== canvasDrag?.pointerId) return;
      const position = canvasPoint(canvas, event), {id, start, pan} = canvasDrag;
      const dx = position.x - start.x, dy = position.y - start.y;
      if(canvasDrag.box){canvasUI?.marquee(start,position);return;}
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
      const {id, box, start, pan, preview, frame} = canvasDrag;
      canvasDrag = null;
      if (frame !== null) cancelAnimationFrame(frame);
      canvas.classList.remove('panning');
      if(box)canvasUI?.marquee(start,event.type==='pointerup'?canvasPoint(canvas,event):start,true);
      else if(!id && (pan.x!==canvasPan.x || pan.y!==canvasPan.y))canvasUI?.ignoreClick();
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
    value = Boolean(value);
    document.body.classList.toggle('desktop-nav-collapsed', value);
    if (navCollapse) navCollapse.textContent = value ? '›' : '‹';
    navCollapse?.setAttribute('aria-expanded', String(!value));
    navCollapse?.setAttribute('aria-label', value ? '展开导航栏' : '折叠导航栏');
    navCollapse?.setAttribute('title', value ? '展开导航栏' : '折叠导航栏');
    try { localStorage.setItem('stock_predict_mailer.desktop.nav.collapsed.v1', value ? '1' : '0'); } catch (_) {}
    window.AnalysisInput.resize();
  }

  function closeDialogs() {
    for (const dialog of document.querySelectorAll('.workflow-run-dialog[open], .report-page-preview[open]')) dialog.close();
  }
  function resumeWorkspace() {
    if (!focus || !workspaceLoaded || AnalysisMode.active() !== professional) return;
    setMessage(message || '选择节点查看详情。');
    updateWorkspaceTabs();
    scheduleArchive(0);
    if(inspectorTab==='runtime'&&!showingRun())loadLastRun();
    if (debugNode && workSurface === 'debug' && !debugDialog?.open) {
      const node = nodeById(debugNode);
      if (node) openDebug(node);
    }
  }

  function setMode(value, options) {
    const target = value === 'focus' ? professional : value === 'legacy' ? 'legacy' : 'standard';
    if (AnalysisMode.active() === professional && target !== professional) {
      canvasUI?.reset();
      persistDraft(); persistUI(); clearTimeout(archiveTimer);clearTimeout(lastRunTimer);
      closeNodePicker();
      ++lastRunRequest;++recordRequest;
      if(lastRun)lastRun.pending=false;
    }
    mode = value;
    for (const node of modeSwitch?.children || []) node.setAttribute('aria-pressed', String(node.dataset.desktopMode === mode));
    if (root && desktop.matches) {
      const canvas = mode === 'focus';
      document.body.classList.toggle('desktop-focus-view', canvas);
      document.body.classList.toggle('dify-professional-view', canvas);
      office.querySelector('.office-stage').inert = canvas;
      if (office.querySelector('.market-wall')) office.querySelector('.market-wall').inert = canvas;
      moveComposer(canvas);
      for (const button of root.querySelectorAll('[data-desktop-mode]')) button.setAttribute('aria-pressed', String(button.dataset.desktopMode === mode));
      window.AnalysisInput.resize();
      if (canvas) applyCanvasViewport();
    }
    if (workspaceLoaded && target !== 'legacy') AnalysisMode.write('active-mode', target, 'shared');
    const switching = window.Workbench?.switchMode(target, options);
    window.WorkflowChat?.syncView();
    if (!options?.boot) resumeWorkspace();
    return switching;
  }
  function panel(value) { pane = value; if (!desktop.matches || !root) return; if (document.activeElement instanceof HTMLElement && !document.activeElement.closest('#report-inspector') && document.activeElement !== document.body) origin = document.activeElement; inspectorTitle.textContent = {input: '分析资料', progress: '工作进度', report: '报告与证据'}[pane]; }
  function returnFocus() { if (!desktop.matches || !root) return; const candidates = [origin, $('analysis-data-open'), $('desktop-data'), $('desktop-focus-data')]; candidates.find(target => target?.isConnected && target.getClientRects().length)?.focus(); }
  function historyPanel(open = $('analysis-composer').classList.contains('desktop-history-open')) { if (!root || !desktop.matches) return; const count = $('conversation-turns').childElementCount, expanded = Boolean(open && count); $('desktop-history').hidden = !count; put('desktop-history', `会话记录 · ${count} 轮`); $('desktop-history').setAttribute('aria-expanded', String(expanded)); $('analysis-composer').classList.toggle('desktop-history-open', expanded); }

  function update() { if (!root || (!desktop.matches && mode !== 'focus')) return; deriveRuntime(task); if (navFocus) { navFocus.hidden = document.body.dataset.view !== 'analysis'; navFocus.setAttribute('aria-pressed', String(mode === 'focus')); } if (navHall) { navHall.hidden = document.body.dataset.view !== 'analysis'; navHall.setAttribute('aria-pressed', String(mode === 'hall')); } const input = inputState(), model = safeProfiles().find(item => item.enabled && item.id === AnalysisMode.model()), prediction = input.prediction, until = Date.parse(prediction?.valid_until) || 0; if (until !== expiresAt) { clearTimeout(expiry); expiresAt = until; if (until > Date.now()) expiry = setTimeout(() => { expiresAt = 0; update(); }, Math.min(until - Date.now() + 50, 2147483647)); } const viewTask = window.Workbench?.result(); const active = ['submitted', 'working'].includes(viewTask?.status.state), result = viewTask?.artifacts?.[0]?.parts?.[0]?.data, failed = viewTask?.status.state === 'failed', canceled = viewTask?.status.state === 'canceled'; updateDefinitionVisual(); put('desktop-title', definition?.name || (prediction?.subject ? `${prediction.subject} · 专业分析` : '专业分析工作流')); put('desktop-subtitle', failed ? '任务失败，画布保留真实失败节点和修正入口。' : active && disconnected ? '进度暂未更新，任务可能仍在服务端执行。' : active ? '正在读取真实任务事件，节点状态会随事件更新。' : '可编辑流程结构，提交时仍使用现有分析任务接口。'); for (const id of ['desktop-model', 'desktop-data', 'desktop-focus-data']) $(id).disabled = false; $('desktop-sample').disabled = sampling; put('desktop-model-value', model?.name || '选择模型'); $('desktop-model').dataset.state = model ? 'ready' : 'empty'; $('desktop-model').title = model ? `工作台默认模型：${model.name}` : '先添加或选择一个默认模型。'; put('desktop-data-value', input.label); $('desktop-data').dataset.state = input.state; $('desktop-data').title = input.detail; $('desktop-result').disabled = !viewTask; put('desktop-result-value', active ? '查看工作进度' : failed ? '查看失败原因' : canceled ? '查看已取消任务' : result ? '查看报告与证据' : '等待分析报告'); $('desktop-result').dataset.state = failed ? 'invalid' : result ? 'ready' : active ? 'working' : 'empty'; put('desktop-focus-title', prediction?.subject || '准备你的第一份分析'); put('desktop-focus-copy', prediction ? input.detail : '导入上游预测，或填写标的与周期。画布会把真实任务链路映射为可核对的节点。'); put('desktop-summary-model', model ? `${model.name}${model.provider === 'mock' ? ' · 离线模拟' : ''}` : '尚未选择默认模型'); put('desktop-summary-prediction', prediction ? `${horizonText(prediction.horizon)} · ${prediction.synthetic ? '合成数据' : '上游声明数据'}` : '尚未提供预测'); put('desktop-summary-facts', input.facts ? `${input.facts} 条来源声明` : '本轮未附新增事实'); put('desktop-summary-mail', $('task-notify').checked ? '本轮启用邮件 · 仍需核对授权收件人' : '仅分析 · 本轮不发送邮件'); $('desktop-sample').hidden = Boolean(viewTask); focus.querySelector('.desktop-sample-note').hidden = Boolean(viewTask); historyPanel(); let feedbackText = active ? '分析进行中，工作流状态来自实际任务事件。' : !model ? '先选择分析模型，或准备一个离线示例。' : input.state !== 'ready' ? input.detail : failed ? '上一轮分析失败，请查看失败节点和任务详情。' : canceled ? '上一轮任务已取消，可核对资料后重新发送。' : result ? `上一轮报告已生成${result.analysis?.status === 'degraded' ? '，分析存在降级' : ''}。` : input.detail; if (!active && input.state === 'ready' && $('task-notify').checked && !$('task-recipient').value.trim()) feedbackText = '本轮启用了邮件，请先填写授权收件地址。'; if (active && disconnected) feedbackText = '进度读取中断，任务可能仍在服务端运行。'; put('desktop-feedback-text', feedbackText); feedback.dataset.state = failed || (active && disconnected) || ['invalid', 'expired'].includes(input.state) ? 'invalid' : active ? 'working' : 'normal'; put('desktop-feedback-action', active ? '查看进度' : failed ? '查看原因' : result ? '查看报告' : !model ? '选择模型' : '检查资料'); $('desktop-feedback-action').disabled = false; $('desktop-feedback-action').onclick = active || failed || result ? openResult : !model ? chooseModel : openData; for (const button of document.querySelectorAll('.nav [data-view]')) { if (button.dataset.view === document.body.dataset.view) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); } renderCanvas(); renderInspector(); }

  function installModeSwitch() {
    if (modeSwitch) return;
    modeSwitch = document.createElement('div');
    modeSwitch.className = 'desktop-mode-switch';
    modeSwitch.setAttribute('role', 'group');
    modeSwitch.setAttribute('aria-label', '界面模式');
    for (const [value, label] of [['hall', '普通'], ['focus', '专业']]) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = label; button.dataset.desktopMode = value;
      button.setAttribute('aria-pressed', String(mode === value));
      button.onclick = () => setMode(value);
      modeSwitch.append(button);
    }
    document.querySelector('.nav')?.append(modeSwitch);
  }

  function install() { installModeSwitch(); if (!root) { root = document.createElement('section'); root.id = 'desktop-workflow'; root.setAttribute('aria-label', '分析流程'); root.innerHTML = `<div class="desktop-workflow-heading"><div><h1 id="desktop-title"></h1><p id="desktop-subtitle"></p></div></div><div class="desktop-workflow-actions"><button type="button" id="desktop-model"><span class="desktop-step">1 · 模型</span><strong id="desktop-model-value"></strong></button><button type="button" id="desktop-data"><span class="desktop-step">2 · 资料</span><strong id="desktop-data-value"></strong></button><button type="button" id="desktop-result"><span class="desktop-step">3 · 结果</span><strong id="desktop-result-value"></strong></button></div>`; focus = document.createElement('section'); focus.id = 'desktop-focus'; focus.setAttribute('aria-label', '可编辑分析工作流'); focus.innerHTML = `<div class="desktop-focus-intro"><p class="eyebrow">本轮分析工作流</p><h2 id="desktop-focus-title"></h2><p id="desktop-focus-copy"></p><div class="desktop-focus-actions"><button type="button" id="desktop-focus-data" class="btn primary">填写 / 修改资料</button><button type="button" id="desktop-sample" class="btn">准备离线示例</button></div><p class="hint desktop-sample-note">离线示例会将默认模型设为 Mock 并填入 synthetic 资料，准备后仍需手动发送。</p></div><div class="desktop-flow-toolbar"><div class="desktop-flow-toolbar-status"><strong>可视化流程</strong><span id="desktop-workflow-message" role="status" aria-live="polite">选择节点查看详情。</span></div><div class="desktop-flow-toolbar-actions"><span id="desktop-workflow-validation"></span><button type="button" data-workflow-action="add">新增节点</button><button type="button" data-workflow-action="undo" id="desktop-workflow-undo">撤销</button><button type="button" data-workflow-action="save" id="desktop-workflow-save">保存流程</button><button type="button" data-workflow-action="restore">恢复默认</button><button type="button" data-workflow-action="import">导入</button><button type="button" data-workflow-action="export">导出</button><div class="desktop-flow-viewport-tools" role="group" aria-label="画布视图控制"><button type="button" data-viewport-action="zoom-out" aria-label="缩小画布">−</button><span id="desktop-workflow-zoom">72%</span><button type="button" data-viewport-action="zoom-in" aria-label="放大画布">+</button><button type="button" data-viewport-action="fit" aria-label="适配画布">适配</button></div><input id="desktop-workflow-file" type="file" accept="application/json,.json" hidden></div></div><div class="desktop-flow-layout"><div class="desktop-flow-canvas" id="desktop-workflow-canvas" role="application" aria-label="分析工作流画布"><svg id="desktop-workflow-edges" aria-label="工作流连线"><defs><marker id="desktop-flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs><g id="desktop-workflow-edge-paths"></g></svg><div class="desktop-flow-surface" id="desktop-workflow-surface"><div id="desktop-workflow-nodes"></div></div></div><aside class="desktop-flow-inspector" id="desktop-workflow-inspector" aria-label="节点详情"></aside></div><dl class="desktop-summary"><div><dt>分析模型</dt><dd id="desktop-summary-model"></dd></div><div><dt>预测周期</dt><dd id="desktop-summary-prediction"></dd></div><div><dt>客观事实</dt><dd id="desktop-summary-facts"></dd></div><div><dt>本轮通知</dt><dd id="desktop-summary-mail"></dd></div></dl>`; const intro = focus.querySelector('.desktop-focus-intro'); if (intro) intro.hidden = true; const focusData = focus.querySelector('#desktop-focus-data'); if (focusData) focus.querySelector('.desktop-flow-toolbar')?.prepend(focusData); const summary = focus.querySelector('.desktop-summary'); if (summary) summary.hidden = true; feedback = document.createElement('div'); feedback.id = 'desktop-feedback'; feedback.innerHTML = '<span id="desktop-feedback-text" role="status" aria-live="polite"></span><button type="button" id="desktop-feedback-action"></button><button type="button" id="desktop-history" aria-controls="conversation-thread" aria-expanded="false" hidden></button>'; office.prepend(root, focus); if (!focus.querySelector('.desktop-flow-palette')) { const palette = document.createElement('aside'); palette.className = 'desktop-flow-palette'; palette.setAttribute('aria-label', '节点库'); const heading = document.createElement('p'); heading.className = 'eyebrow'; heading.textContent = '节点库'; palette.append(heading); focus.querySelector('.desktop-flow-layout')?.prepend(palette); } navCollapse = document.createElement('button'); navCollapse.type = 'button'; navCollapse.className = 'desktop-nav-collapse'; navCollapse.onclick = () => setNavCollapsed(!document.body.classList.contains('desktop-nav-collapsed')); document.querySelector('.topbar')?.insertBefore(navCollapse, document.querySelector('.nav')); installNavIcons(); setNavCollapsed(navCollapsed()); $('analysis-composer').prepend(feedback); $('desktop-data').onclick = $('desktop-focus-data').onclick = openData; $('desktop-model').onclick = chooseModel; $('desktop-result').onclick = openResult; $('desktop-sample').onclick = sample; $('desktop-history').onclick = () => historyPanel(!$('analysis-composer').classList.contains('desktop-history-open')); root.querySelectorAll('[data-desktop-mode]').forEach(button => { button.onclick = () => setMode(button.dataset.desktopMode); }); focus.querySelectorAll('[data-workflow-action]').forEach(button => { button.onclick = () => ({add: addNode, undo, save: saveWorkflow, restore: restoreDefault, import: () => $('desktop-workflow-file').click(), export: exportWorkflow}[button.dataset.workflowAction])(); }); focus.querySelectorAll('[data-viewport-action]').forEach(button => { button.onclick = () => button.dataset.viewportAction === 'fit' ? fitCanvas() : canvasZoomBy(button.dataset.viewportAction === 'zoom-in' ? 1.15 : 1 / 1.15); }); installCanvasInteractions(); workflowControls(); $('desktop-workflow-file').addEventListener('change', importWorkflow); $('report-close').addEventListener('click', returnFocus); new MutationObserver(() => historyPanel()).observe($('conversation-turns'), {childList: true}); document.addEventListener('pointerdown', event => { if (desktop.matches && !event.target.closest?.('[data-desktop-mode]') && !$('analysis-composer').contains(event.target)) historyPanel(false); }); document.addEventListener('keydown', event => { if (window.DesktopInteractions?.active?.()) return; if (desktop.matches && event.key === 'Escape' && $('analysis-composer').classList.contains('desktop-history-open')) { event.preventDefault(); event.stopImmediatePropagation(); historyPanel(false); $('desktop-history').focus(); } }, true); $('task-form').addEventListener('submit', () => historyPanel(false));  const toolbar = focus.querySelector('.desktop-flow-toolbar'); const resize = new ResizeObserver(() => { focus.style.setProperty('--desktop-flow-toolbar-height', toolbar.offsetHeight + 'px'); if (!desktop.matches) return; const height = root.offsetHeight + 'px'; if (office.style.getPropertyValue('--desktop-workflow-height') !== height) { office.style.setProperty('--desktop-workflow-height', height); document.documentElement.style.setProperty('--desktop-workflow-height', height); window.AnalysisInput.layout(); } renderEdges(); }); resize.observe(root); resize.observe(toolbar); window.addEventListener('pagehide', () => { if (workspaceLoaded) { persistDraft(); persistUI(); } }); } if (navCollapse) navCollapse.hidden = !desktop.matches; root.hidden = feedback.hidden = !desktop.matches; focus.hidden = false; if (navFocus) { navFocus.hidden = document.body.dataset.view !== 'analysis'; navFocus.setAttribute('aria-pressed', String(mode === 'focus')); } if (navHall) { navHall.hidden = document.body.dataset.view !== 'analysis'; navHall.setAttribute('aria-pressed', String(mode === 'hall')); } if (desktop.matches) $('analysis-pane-progress').prepend($('task-status'));
    else {
      moveComposer(false);
      document.body.classList.remove('desktop-nav-collapsed','desktop-focus-view','dify-professional-view');
      office.querySelector('.office-stage').inert = false;
      office.querySelector('.market-wall')?.removeAttribute('inert');
      statusParent.insertBefore($('task-status'), statusNext);
      inspectorTitle.textContent = originalTitle;
    }
    document.body.classList.toggle('desktop-workbench',desktop.matches);
    setMode(mode); panel(pane); update();
  }
  desktop.addEventListener('change', install); new MutationObserver(update).observe(document.body, {attributes: true, attributeFilter: ['data-view']}); document.addEventListener('visibilitychange', () => { if (!document.hidden) update(); }); window.addEventListener('focus', update); install();
  function clearRuntime() {
    task = null; disconnected = false; runtime.taskId = null; runtime.events=[];
    runtime.states.clear(); runtime.details.clear(); update();
  }
  function queueWorkflow() {
    clearArchive();
    enterRunSurface();
    persistUI();
    if (focus) updateWorkspaceTabs();
  }
  return {update, panel, setMode, restoreWorkspace, resumeWorkspace, closeDialogs, clearRuntime, historyOpen: historyPanel,
    useDefinition, savedDefinition, canvasSnapshot, openRecordedRun, fitCanvas, legacyDefinitions() {
      const current=read('workflow'), library=read('workflow-library') || [];
      return [...library, ...(current?.mode==='custom' ? [{label:'本机已保存流程', graph:current, key:'saved-canvas'}] : [])];
    },
    addBuiltinTool, useRenderer, checkWorkflow, showWorkflowIssues:showIssues, workflowPayload, acceptWorkflow, queueWorkflow, explainError, mode: () => mode,
    observeProgressTask(value) { if (AnalysisMode.active() === professional && taskMode(value) === professional) { task=value;deriveRuntime(task); } },
    observe(value) { if (AnalysisMode.active() === professional && taskMode(value) === professional) task=value; update(); },
    event: applyEvent, connectionLost(value) { disconnected = value; update(); }, selectionState: update};

})();
