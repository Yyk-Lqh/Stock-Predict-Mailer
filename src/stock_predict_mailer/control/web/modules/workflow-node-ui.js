/* The node library, port labels and variable-node configuration. */
window.WorkflowNodeUI = (() => {
  const groups = [
    ['基础节点', '#446bc3', [['input','用户输入','↳'], ['llm','LLM','✦'], ['knowledge','知识检索','▤'], ['analysis','Agent','◎'],
      ['output','输出','→'], ['validation','资料校验','✓'], ['merge','结果汇总','⋈'], ['forecast','预测归档','◷'],
      ['chart','图表','▥'], ['report','报告','▧'], ['delivery','邮件交付','✉']]],
    ['问题理解', '#258466', [['classifier','问题分类器','⋮']]],
    ['逻辑节点', '#327e92', [['branch','条件分支','⤴'], ['human','人工介入','◇'], ['iteration','迭代','↻'], ['loop','循环','∞']]],
    ['转换节点', '#7262ba', [['code','代码执行','⌘'], ['template','模板转换','¶'], ['aggregate','变量聚合器','⋈'],
      ['document','文档提取器','▤'], ['assign','变量赋值','='], ['extract','参数提取器','⊞']]],
    ['工具节点', '#966738', [['http','HTTP 请求','↗'], ['list','列表操作','≡'], ['retrieval','MCP 上下文','⌁'],
      ['database','数据库','▦'], ['tool','内置工具','⚙']]],
  ];
  const appearance = new Map(groups.flatMap(([,color,items]) => items.map(([kind,label,glyph]) => [kind,{color,label,glyph}])));
  for (const [kind,label,glyph] of [['model','模型','◎'],['trained','模型版本','◷'],['review','风险复核','✓'],['custom','自定义','◇']]) {
    appearance.set(kind,{color:'#687990',label,glyph});
  }
  const variableTypes = ['classifier','branch','template','aggregate','assign','extract','document','list','llm','output'];
  const types = {text:'文本', number:'数值', boolean:'布尔', object:'对象', list:'列表', any:'任意 JSON'};
  const isVariable = graph => graph.nodes.some(node => node.data.type === 'input' && Array.isArray(node.data.config?.fields));
  const branched = kind => kind === 'classifier' || kind === 'branch';
  const needsLibrary = graph => graph.nodes.some(node => ['knowledge','document'].includes(node.data.type));
  const element = (tag, name) => Object.assign(document.createElement(tag), {className:name || ''});
  function icon(kind) {
    const node=element('span','workflow-node-glyph'), style=appearance.get(kind);
    node.textContent=style?.glyph || '◇';
    node.style.setProperty('--node-accent',style?.color || '#687990');
    node.setAttribute('aria-hidden','true');
    return node;
  }
  const label = kind => appearance.get(kind)?.label;
  function ports(node, variables) {
    const kind=node.data.type, cfg=node.data.config || {};
    if (variables && kind === 'output' || !variables && kind === 'delivery') return [];
    if (branched(kind)) return [...configRows(cfg.cases).map(item => ({id:item.id,label:item.label || '未命名出口'})),
      ...(cfg.fallback ? [{id:'default',label:'默认出口'}] : [])];
    return [{id:'value',label:'输出',type:variables?outputs(node,true).value || 'any':null},
      ...(variables?Object.entries(outputs(node,true)).filter(([id])=>id!=='value')
        .map(([id,type])=>({id,label:id,type})):[])];
  }
  function inputPorts(node,variables) {
    if(node.data.type==='input')return [];
    const kind=node.data.type, cfg=node.data.config || {};
    if(variables && kind==='output' && Array.isArray(cfg.fields))return cfg.fields.filter(field=>field?.name)
      .map(field=>({id:field.name,label:field.label || field.name,type:field.type,required:field.required}));
    const type={classifier:'text',extract:'text',knowledge:'text',document:'text',list:'list',assign:cfg.value_type}[kind] || 'any';
    const names=['classifier','branch','assign','extract','knowledge','document','list','output'];
    return [{id:'value',label:variables?'依赖':'输入',type:'any'},
      ...(variables && names.includes(kind)?[{id:'source',label:'数据输入',type,required:true}]:[]),
      ...(variables && kind==='aggregate'?[{id:'sources',label:'聚合输入',type:'list',required:true}]:[])];
  }
  const configRows = value => Array.isArray(value) ? value.filter(item=>item!=null) : [];
  function outputs(node, variables) {
    const kind=node.data.type, cfg=node.data.config || {};
    if (!variables) return {};
    if (kind === 'input' || kind === 'extract') return {...(kind==='input'?{message:'text'}:{}),
      ...Object.fromEntries(configRows(cfg.fields).filter(field=>field.name).map(field=>[field.name,field.type]))};
    if (branched(kind)) return {selected:'text',label:'text'};
    if (kind === 'assign') return cfg.name ? {[cfg.name]:cfg.value_type} : {};
    if (kind === 'knowledge') return {hits:'list'};
    if (kind === 'document') return {value:'text',source:'object'};
    if (kind === 'aggregate') return {value:'list'};
    if (kind === 'list') return {value:cfg.operation==='item'?'any':'list'};
    if (kind === 'llm') return {value:cfg.format==='json'?'object':'text'};
    return {value:kind==='output'&&cfg.format==='json'?'any':'text'};
  }
  function upstream(graph, id) {
    const seen=new Set([id]), queue=[id];
    while(queue.length) {
      const target=queue.pop();
      for(const edge of graph.edges.filter(edge=>edge.target===target)) {
        if(!seen.has(edge.source)){seen.add(edge.source);queue.push(edge.source);}
      }
    }
    const result=[];
    for (const node of graph.nodes.filter(node=>node.id!==id&&seen.has(node.id))) {
      for (const [field,type] of Object.entries(outputs(node,true))) {
        result.push({ref:node.id+'.'+field,type,label:node.data.label+' · '+field+' · '+(types[type] || type)});
      }
    }
    return result;
  }
  function defaults(kind) {
    if (kind==='input' || kind==='extract') return {fields:[]};
    if (branched(kind)) return {source:'',cases:[{id:'case_'+crypto.randomUUID().slice(0,8),label:'类别 1',description:'',match:'',
      ...(kind==='branch'?{operation:'equals'}:{})}],fallback:true};
    return {template:{template:''},llm:{template:'',format:'text'},aggregate:{sources:[],empty:'omit'},
      assign:{source:'',name:'result',value_type:'text'},knowledge:{source:'',limit:4},
      list:{source:'',operation:'slice',start:0,end:5},output:{source:'',format:'text'}}[kind] || {};
  }
  function summary(node, graph, model) {
    const kind=node.data.type, cfg=node.data.config, variables=isVariable(graph);
    if (!variables && !variableTypes.includes(kind)) {
      if(kind==='input') return ['预测数据 · 客观事实'];
      if(kind==='analysis'||kind==='merge') return [model(cfg.model),...(kind==='analysis'?
        [cfg.tools?.length ? '工具 · '+cfg.tools.map(item=>item.split(':').at(-1)).join('、') : '输出分析与依据']:[])];
      if(kind==='knowledge') return ['运行所选资料库'];
      if(kind==='report') return ['输出分析报告'];
      return [];
    }
    if(kind==='input') return ['message · 文本',...configRows(cfg.fields).map(field=>field.name+' · '+(types[field.type]||'待配置')).slice(0,3)];
    if(branched(kind)) return [...(!cfg.source?['待配置 · 上游变量']:[]),...(!cfg.cases?.length?['待配置 · 添加出口']:[])];
    if(kind==='llm') return [model(cfg.model),cfg.template ? (cfg.format==='json'?'输出 JSON 对象':'输出文本') : '待配置 · 提示词'];
    if(kind==='knowledge') return ['运行所选资料库',cfg.source?'最多 '+cfg.limit+' 段':'待配置 · 查询变量'];
    if(kind==='template') return [cfg.template || '待配置 · 模板'];
    if(kind==='aggregate') return [cfg.sources?.length ? cfg.sources.length+' 个来源 · 列表' : '待配置 · 来源'];
    if(kind==='output') return [Array.isArray(cfg.fields)?'返回 '+cfg.fields.length+' 个字段':
      cfg.source ? (cfg.format==='json'?'返回 JSON':'返回文本')+' · '+cfg.source.split('.').at(-1) : '选择返回变量或连接数据输入'];
    return [cfg.source ? cfg.source.split('.').at(-1) : '待配置 · 上游变量'];
  }
  function control(host, title, tag, value, options) {
    const wrapper=element('label'), field=element(tag);
    if (options) field.append(...Object.entries(options).map(([key,caption])=>new Option(caption,key)));
    if (tag==='textarea') field.rows=3;
    field.value=value ?? '';
    wrapper.append(document.createTextNode(title),field);
    host.append(wrapper);
    return field;
  }
  function markRequired(field) {
    field.required=true;
    const mark=element('span','workflow-required');mark.textContent=' *';mark.setAttribute('aria-hidden','true');
    field.before(mark);
  }
  function refField(host, title, refs, value, expected) {
    const options={'':'选择上游变量'};
    for(const item of refs) if(!expected || item.type===expected || item.type==='any') options[item.ref]=item.label;
    const wrongType=refs.find(item=>item.ref===value);
    const unavailable=value && !Object.hasOwn(options,value);
    if(unavailable) options[value]=(wrongType?'类型不匹配':'失效引用')+' · '+value;
    const field=control(host,title,'select',value || '',options);
    field.dataset.reference='';
    if(unavailable) {
      const message=text(field.parentElement,'small',wrongType ? `需要${types[expected]}，当前为${types[wrongType.type]}` : '请选择仍然可访问的上游字段。','warn');
      field.setAttribute('aria-invalid','true');
      field.addEventListener('change',()=>{
        field.toggleAttribute('aria-invalid',field.value===value);
        message.hidden=field.value!==value;
      });
    }
    return field;
  }
  function checkbox(host, title, checked) {
    const wrapper=element('label','desktop-flow-check'), field=element('input');
    field.type='checkbox';field.checked=Boolean(checked);
    wrapper.append(field,document.createTextNode(title));host.append(wrapper);
    return field;
  }
  function jsonField(field) {
    try {return field.value.trim() ? JSON.parse(field.value) : undefined;}
    catch (_) {throw Object.assign(Error('请检查此字段的 JSON 格式。'),{field});}
  }
  function editableRows(host, title, initial, draw, fresh, max, readConfig, caption) {
    const group=element('fieldset','workflow-config-rows'), list=element('div'), rows=[];
    const trigger=(caption,action)=>{const button=element('button');button.type='button';button.textContent=caption;button.onclick=action;return button;};
    const add=trigger('添加'+title,()=>{
      const row=append(fresh());row.open=true;
      row.dispatchEvent(new Event('input',{bubbles:true}));row.querySelector('input,select')?.focus();
    });
    text(group,'legend',title);group.append(list,add);host.append(group);
    function append(value) {
      const box=element('details','workflow-config-row'), header=text(box,'summary','');
      const body=element('div','workflow-config-row-body'), get=draw(body,value), row={box,get};
      box.append(body);
      const describe=()=>{header.textContent=caption(get(true));};
      describe();body.addEventListener('input',describe);
      const buttons=element('div','actions');
      const move=delta=>{
        const index=rows.indexOf(row), other=rows[index+delta];
        if(!other)return;
        rows.splice(index,1);rows.splice(index+delta,0,row);
        list.replaceChildren(...rows.map(item=>item.box));
        box.dispatchEvent(new Event('input',{bubbles:true}));
      };
      buttons.append(trigger('上移',()=>move(-1)),trigger('下移',()=>move(1)),trigger('删除',()=>{
        rows.splice(rows.indexOf(row),1);box.remove();add.disabled=false;
        list.dispatchEvent(new Event('input',{bubbles:true}));
      }));
      body.append(buttons);rows.push(row);list.append(box);add.disabled=rows.length>=max;
      return box;
    }
    configRows(initial).forEach(append);
    readConfig.push(draft=>rows.map(item=>item.get(draft)));
  }
  function settings(host, node, graph, config, models, inputs=host) {
    const kind=node.data.type, cfg={...defaults(kind),...config}, refs=upstream(graph,node.id);
    const readers={};
    const named=kind==='output'?checkbox(host,'返回多个字段',Array.isArray(cfg.fields)):null;
    const read=(name,field,convert=x=>x)=>{
      field.dataset.configKey=name;
      readers[name]=draft=>convert(field.value,draft);
    };
    if(kind==='input'||kind==='extract'||named) {
      if(kind==='input') text(host,'p','对话需求自动提供 message（文本）。','hint');
      const rows=[];
      const fieldHost=named?element('div'):host;
      if(named) {
        fieldHost.hidden=!named.checked;host.append(fieldHost);
        text(fieldHost,'p','从画布连接各字段。列表字段按连线顺序收集激活路径的值。','hint');
      }
      editableRows(fieldHost,'字段',cfg.fields || [],(row,field)=>{
        const name=control(row,'变量名','input',field.name);
        name.pattern='[A-Za-z_][A-Za-z_0-9]{0,39}';markRequired(name);
        const caption=control(row,'显示名称或说明','input',field.label);
        const type=control(row,'值类型','select',field.type || 'text',Object.fromEntries(Object.entries(types).slice(0,5)));
        const required=checkbox(row,'必填',field.required);
        const initial=control(row,'默认值（JSON，可留空）','input',field.defaultRaw ?? (field.default===undefined?'':JSON.stringify(field.default)));
        name.dataset.configKey='fields';initial.dataset.configKey='default';
        return draft=>({name:name.value.trim(),label:caption.value.trim(),type:type.value,required:required.checked,
          ...(initial.value.trim()?(draft?{defaultRaw:initial.value}:{default:jsonField(initial)}):{})});
      },()=>({name:'',type:'text',required:true}),12,rows,
      field=>`${field.name||'新字段'} · ${types[field.type] || field.type}${field.required?' · 必填':''}${field.defaultRaw?' · 默认 '+field.defaultRaw:''}`);
      readers.fields=draft=>!named || named.checked?rows[0](draft):undefined;
      if(named)named.addEventListener('input',()=>{fieldHost.hidden=!named.checked;});
    }
    if(['classifier','branch','assign','extract','document','knowledge','list','output'].includes(kind)) {
      const expected={classifier:'text',extract:'text',document:'text',knowledge:'text',list:'list'}[kind];
      const source=refField(inputs,'上游变量',refs,cfg.source,expected);
      const linked=graph.edges.some(edge=>edge.target===node.id&&edge.input==='source');
      if(!linked)markRequired(source);
      const update=()=>{
        source.closest('label').hidden=Boolean(named?.checked);
        source.disabled=Boolean(named?.checked);
      };
      named?.addEventListener('input',update);update();
      read('source',source,value=>named?.checked?undefined:value);
      if(!refs.length)text(inputs,'p','先连接产生变量的上游节点。','hint');
    }
    if(branched(kind)) {
      const rows=[];
      editableRows(host,kind==='classifier'?'分类出口':'条件出口',cfg.cases || [],(row,item)=>{
        const title=control(row,'出口名称','input',item.label);
        markRequired(title);title.maxLength=80;
        const description=control(row,'说明','input',item.description);
        const op=kind==='branch'?control(row,'判断','select',item.operation,{equals:'等于（JSON）',contains:'文本包含',exists:'变量存在'}):null;
        const value=control(row,kind==='classifier'?'关键词（逗号分隔）':'匹配值','input',
          item.matchRaw ?? (op?.value==='equals'&&item.match!==undefined?JSON.stringify(item.match):item.match));
        title.dataset.configKey='cases';value.dataset.configKey='match';
        markRequired(value);
        const updateOperation=()=>{value.disabled=value.closest('label').hidden=op?.value==='exists';};
        if(op)op.oninput=updateOperation;
        updateOperation();
        return draft=>({id:item.id,label:title.value.trim(),description:description.value.trim(),
          ...(op?{operation:op.value}:{}),...(op?.value==='exists'?{}:op?.value==='equals' ?
            (draft ? {matchRaw:value.value}:{match:jsonField(value)}) : {match:value.value})});
      },()=>({id:'case_'+crypto.randomUUID().slice(0,8),label:'新出口',operation:'equals'}),8,rows,
      item=>[item.label||'未命名出口',item.description].filter(Boolean).join(' · '));
      readers.cases=rows[0];
      const fallback=checkbox(host,'启用默认出口',cfg.fallback);
      readers.fallback=()=>fallback.checked;
    }
    if(kind==='llm') read('model',control(host,'分析模型','select',cfg.model,{'':'跟随工作区模型',...models}),value=>value||undefined);
    if(kind==='template'||kind==='llm') {
      const template=control(host,kind==='llm'?'提示词':'模板','textarea',cfg.template);
      template.rows=6;template.maxLength=4000;markRequired(template);
      const picker=refField(host,'插入上游变量',refs,'');
      picker.onchange=()=>{
        if(!picker.value)return;
        template.setRangeText('{{'+picker.value+'}}',template.selectionStart,template.selectionEnd,'end');
        picker.value='';template.focus();template.dispatchEvent(new Event('input',{bubbles:true}));
      };
      read('template',template);
    }
    if(kind==='llm'||kind==='output') {
      const format=control(host,'输出格式','select',cfg.format,{text:'文本',json:'结构化 JSON'});
      const update=()=>{format.disabled=Boolean(named?.checked);};
      named?.addEventListener('input',update);update();
      read('format',format,value=>named?.checked?'json':value);
    }
    if(kind==='aggregate') {
      const sources=[];
      editableRows(host,'聚合来源',cfg.sources || [],(row,ref)=>{
        const input=refField(row,'上游变量',refs,ref);
        return ()=>input.value;
      },()=>'',12,sources,ref=>refs.find(item=>item.ref===ref)?.label || ref || '选择来源');
      readers.sources=sources[0];
      read('empty',control(host,'缺失或跳过的来源','select',cfg.empty,{omit:'省略',null:'保留 null',error:'报错'}));
      text(host,'p','按来源顺序生成列表。','hint');
    }
    if(kind==='assign') {
      read('name',control(host,'目标变量名','input',cfg.name));
      read('value_type',control(host,'目标类型','select',cfg.value_type,Object.fromEntries(Object.entries(types).slice(0,5))));
      text(host,'p','作用域为本次运行的后续节点。','hint');
    }
    if(kind==='knowledge') {
      const limit=control(host,'检索条数（1–8）','input',cfg.limit);
      limit.type='number';limit.min=1;limit.max=8;limit.required=true;
      read('limit',limit,(value,draft)=>draft?value:Number(value));
      text(host,'p','使用运行时选定且有权限访问的资料库。','hint');
    }
    if(kind==='document') text(host,'p','变量应为已处理的知识库文件 ID。','hint');
    if(kind==='list') {
      const operation=control(host,'操作','select',cfg.operation,{filter:'等值筛选',sort:'升序',slice:'切片',item:'取值'});
      read('operation',operation);
      const start=control(host,'起始或取值索引','input',cfg.start), end=control(host,'切片结束索引','input',cfg.end);
      for(const field of [start,end]) {field.type='number';field.min=-200;field.max=200;}
      read('start',start,(value,draft)=>draft?value:Number(value));
      read('end',end,(value,draft)=>draft?value:Number(value));
      const filter=control(host,'筛选值（JSON）','input',cfg.valueRaw ?? (cfg.value===undefined?'':JSON.stringify(cfg.value)));
      filter.dataset.configKey='value';
      const relevant=()=>{
        start.disabled=start.closest('label').hidden=!['item','slice'].includes(operation.value);
        end.disabled=end.closest('label').hidden=operation.value!=='slice';
        filter.closest('label').hidden=operation.value!=='filter';
      };
      operation.oninput=relevant;relevant();
      readers.value=draft=>draft?undefined:operation.value==='filter'?jsonField(filter):cfg.value;
      readers.valueRaw=draft=>draft?filter.value:undefined;
      text(host,'p','筛选、排序和切片对空列表返回空列表，越界取值返回 null。','hint');
    }
    return draft=>Object.fromEntries(Object.entries(readers).map(([name,get])=>[name,get(draft)]).filter(([,value])=>value!==undefined));
  }
  function references(config) {
    return [config?.source,...configRows(config?.sources),...Array.from(String(config?.template || '').matchAll(/\{\{\s*([\w-]+\.[\w-]+)\s*\}\}/g),match=>match[1])].filter(Boolean);
  }
  return {groups, icon, label, appearance, isVariable, needsLibrary, variableTypes, branched, ports, inputPorts, outputs,
    defaults, summary, settings, types, references};
})();
