/* The import surface retains each source draft and follows real document receipts. */
window.KnowledgeImport = (() => {
  const sources=[['upload','▤','导入已有文本'],['notion','▣','同步自 Notion 内容'],['web','◎','同步自 Web 站点']];
  const tools=[['jina','Jina Reader'],['firecrawl','Firecrawl'],['watercrawl','WaterCrawl']];
  const names={notion:'Notion',...Object.fromEntries(tools)};
  const availability={connected:'已配置',unconfigured:'未配置',failed:'连接失败',unavailable:'暂未接入'};
  const statuses={pending:'等待处理',processing:'处理中',review:'待审阅',ready:'可检索',failed:'处理失败',rejected:'已拒绝',deleting:'等待删除'};
  const defaults={formats:['.pdf','.docx','.txt','.md','.csv','.xlsx','.json'],
    max_files:5,max_file_bytes:10*1024*1024,chunk_size:1600};
  const drafts=new Map();
  let active, host, timer;
  const mk=(tag,cls)=>Object.assign(document.createElement(tag),{className:cls||''});
  const id=()=>crypto.randomUUID().replaceAll('-','');
  const storage=(context,suffix)=>'knowledge.import.'+context.knowledgeScope+'.'+suffix;
  const scopeKey=context=>context.knowledgeScope==='private'?context.key:'local';
  const draftKey=(context,slot)=>context.workspace+'.'+storage(context,slot);
  function read(context,slot){
    if(context.knowledgeScope!=='private')return AnalysisMode.read(storage(context,slot),'shared');
    try{return JSON.parse(sessionStorage.getItem(draftKey(context,slot)));}catch(_){return null;}
  }
  function write(context,slot,value){
    if(context.knowledgeScope!=='private')return AnalysisMode.write(storage(context,slot),value,'shared');
    try{
      const key=draftKey(context,slot);
      if(value===null)sessionStorage.removeItem(key);
      else sessionStorage.setItem(key,JSON.stringify(value));
    }catch(_){/* Storage is optional. */}
  }
  const visible=draft=>active===draft&&!host.hidden&&document.body.dataset.view==='knowledge';
  const current=draft=>job(draft);
  function job(draft, source=draft.source==='web'?draft.tool:draft.source){
    return draft.jobs[source] ||= {source,step:1,items:[],selected:{},size:draft.rules?.chunk_size||1600};
  }
  function persist(draft){
    const context=draft.bridge.context;
    if(context.workspace!==AnalysisMode.workspaceId())return;
    const {source,tool,jobs,target,library,name,description}=draft;
    const plain=Object.fromEntries(Object.entries(jobs).map(([key,value])=>{
      const {step,items,selected,size,custom,query,addresses,history=[]}=value;
      return [key,{source:key,step,selected,size,custom,query,addresses,
        items:items.map(({file,segments,...item})=>item),history}];
    }));
    const value={source,tool,jobs:plain,target,library,name,description};
    if(drafts.get(draftKey(context,draft.slot))===draft)write(context,draft.slot,value);
    if(!draft.existing&&target){
      const slot='library.'+target+'.'+scopeKey(context), key=draftKey(context,slot);
      if(!drafts.has(key))drafts.set(key,draft);
      if(drafts.get(key)===draft)write(context,slot,value);
    }
  }
  function call(draft,path,method='GET',body,library=draft.target||draft.library){
    return api('knowledge/'+path,method,body,undefined,{...draft.bridge.context,knowledgeLibrary:library});
  }
  function button(label,fn,primary=false,id=''){
    const control=mk('button',primary?'btn primary':'btn');
    control.type='button';control.textContent=label;
    if(id)control.id=id;
    control.onclick=fn;return control;
  }
  function label(host,caption,control){
    const field=text(host,'label','','field');text(field,'span',caption);field.append(control);return control;
  }
  function same(draft,entry){return visible(draft)&&current(draft)===entry;}
  function message(draft,entry,value){
    entry.message=value;
    if(same(draft,entry))render();
  }
  function refreshView(draft,entry){
    persist(draft);if(same(draft,entry))render();
  }
  async function ensureTarget(draft){
    if(draft.target)return draft.target;
    if(!draft.name.trim())throw Error('请先填写知识库名称。');
    if(!draft.creation){
      draft.creation=call(draft,'libraries','POST',{id:draft.library,name:draft.name.trim(),description:draft.description},'default')
        .then(value=>{draft.target=value.id;draft.name=value.name;persist(draft);return value.id;})
        .finally(()=>{draft.creation=null;});
    }
    return draft.creation;
  }
  function settings(draft){
    if(draft.reading)return draft.reading;
    const library=draft.target||'default';
    draft.reading=Promise.allSettled([call(draft,'import/options','GET',undefined,library),call(draft,'sources')])
      .then(([rules,connections])=>{
        if(rules.status==='fulfilled'&&(draft.target||'default')===library){
          draft.rules={...rules.value,cleaner:draft.target?rules.value.cleaner:'none'};
          draft.settingsError='';
        }
        else if(rules.status==='rejected')draft.settingsError=rules.reason.message;
        if(connections.status==='fulfilled'){
          draft.connections=Object.fromEntries(connections.value.items.map(item=>[item.id,item]));
          draft.connectionError='';
        }else draft.connectionError=connections.reason.message;
        if(visible(draft)&&!current(draft).configuring)render();
      }).finally(()=>{draft.reading=null;});
    return draft.reading;
  }
  function open(container,bridge){
    host=container;
    const library=bridge.context.knowledgeLibrary;
    const slot=(bridge.existing?'library.'+library:'new')+'.'+scopeKey(bridge.context);
    const key=draftKey(bridge.context,slot);
    let saved=read(bridge.context,slot)||{};
    let draft=drafts.get(key);
    if(!bridge.existing&&!bridge.resume&&(draft?.target||saved.target)){saved={};draft=null;}
    if(!draft){
      draft={slot, existing:bridge.existing,library:bridge.existing?library:id(),target:bridge.existing?library:'',
        name:bridge.existing?bridge.name:'',description:'',source:'upload',tool:'jina',jobs:{},...saved};
      for(const entry of Object.values(draft.jobs)){
        for(const item of entry.items){
          if(item.status==='sending'||entry.source==='upload'&&item.status==='candidate'){
            item.status='submit_failed';item.error=item.preview?'上次提交尚未确认，可以重试。':'请重新选择原文件以继续。';
          }
        }
        if(entry.step===2&&!entry.items.some(item=>item.status==='candidate'))entry.step=1;
      }
      drafts.set(key,draft);
    }
    draft.bridge=bridge;active=draft;
    write(bridge.context,'open',{existing:bridge.existing,library,key:scopeKey(bridge.context)});
    persist(draft);render();settings(draft);schedule();
  }
  function shouldResume(context){
    const record=read(context,'open');
    return record?.key===scopeKey(context)?record:null;
  }
  function leave(){
    if(active){
      const context=active.bridge.context;
      write(context,'open',null);
      persist(active);
    }
    active=null;clearTimeout(timer);
  }
  function choose(draft,source){
    draft.source=source;persist(draft);render();schedule();
  }
  function settingsPanel(draft,entry,main){
    if(draft.settingsError){
      text(main,'p','暂未读取目标库设置 · '+draft.settingsError,'error-text');
      main.append(button('重试读取设置',()=>settings(draft)));
    }
    const cleaner={none:'规则清洗与去重'}[draft.rules?.cleaner]||'规则清洗、配置的模型抽取与审阅';
    text(main,'p',`通用分段 · 默认 ${draft.rules?.chunk_size||1600} 字符 · ${cleaner}`,'hint');
    const size=mk('input');size.type='number';size.min='400';size.max='4000';size.step='1';size.value=entry.size;
    label(main,'本次最大分段长度（字符）',size);
    size.oninput=()=>{entry.size=Number(size.value);persist(draft);};
    listItems(draft,entry,main);
    const smallText=item=>item.file&&/\.(txt|md)$/i.test(item.name)&&item.file.size<=(draft.rules?.preview_max_bytes||512*1024);
    const first=entry.items.find(item=>item.status==='candidate'&&(item.preview||smallText(item)));
    if(!first&&entry.source==='upload')text(main,'p','提交前可预览 512 KiB 以内的 TXT 和 Markdown，其余格式在处理后查看分段。','hint');
    if(first){
      main.append(button('查看分段预览',async()=>{
        if(!size.reportValidity())return;
        const selectedSize=entry.size;
        try{
          let request={id:first.preview};
          if(!first.preview){
            let value;
            try{value=new TextDecoder('utf-8',{fatal:true}).decode(await first.file.arrayBuffer());}
            catch(_){throw Error('文件无法按 UTF-8 解码，请检查编码。');}
            request={filename:first.name,text:value};
          }
          const segments=await call(draft,'import/segments','POST',{...request,chunk_size:selectedSize},draft.target||draft.library);
          if(selectedSize===entry.size&&same(draft,entry)&&entry.step===2){first.segments=segments;render();}
        }catch(error){message(draft,entry,error.message);}
      }));
      for(const item of entry.items.filter(item=>item.segments)){
        text(main,'h3',item.name+' · '+item.segments.count+' 段');
        for(const chunk of item.segments.chunks)text(main,'p',chunk,'source-excerpt source-text');
      }
    }
    const actions=mk('div','actions');main.append(actions);
    actions.append(button('返回数据源',()=>{entry.step=1;refreshView(draft,entry);}),
      button('开始导入',()=>{if(size.reportValidity())submit(draft,entry);},true));
  }
  function filesPanel(draft,entry,main){
    const rules=draft.rules||defaults;
    const file=mk('input');file.type='file';file.accept=rules.formats.join(',');file.multiple=true;
    file.hidden=true;file.id='knowledge-create-file';
    const drop=mk('div','knowledge-dropzone');main.append(drop);
    const check=mk('input');check.type='checkbox';check.checked=Boolean(entry.custom);
    const option=text(main,'label','','check knowledge-import-custom');
    option.append(check,document.createTextNode('自定义本次分段与清洗'));
    check.onchange=()=>{entry.custom=check.checked;persist(draft);};
    drop.append(button('选择文件',()=>file.click(),true,'knowledge-upload-from-create'),file);
    text(drop,'p',`也可拖放文件。支持 ${rules.formats.join('、')}，每次最多 ${rules.max_files} 个，每个不超过 ${rules.max_file_bytes/1024/1024} MiB。`,'hint');
    file.onchange=()=>selectFiles(draft,entry,[...file.files]);
    for(const event of ['dragover','dragleave','drop'])drop.addEventListener(event,value=>{
      value.preventDefault();drop.classList.toggle('is-dragging',event==='dragover');
      if(event==='drop')selectFiles(draft,entry,[...value.dataTransfer.files]);
    });
    if(entry.items.length)listItems(draft,entry,main);
    if(entry.items.some(item=>item.doc))
      main.append(button('查看处理结果',()=>{entry.step=3;refreshView(draft,entry);schedule();}));
  }
  function selectFiles(draft,entry,files){
    if(!files.length||entry.busy)return;
    if(!draft.target&&!draft.name.trim())return message(draft,entry,'请先填写知识库名称。');
    const rules=draft.rules||defaults;
    const metadata={available_date:localInput(new Date()).slice(0,10)};
    const items=files.slice(0,rules.max_files).map(file=>{
      let error;
      if(!file.size)error='文件为空';
      else if(file.size>rules.max_file_bytes)error='文件体积超过上限';
      else if(!rules.formats.some(ext=>file.name.toLowerCase().endsWith(ext)))error='文件格式不支持';
      return {key:id(),name:file.name,file,metadata,status:error?'invalid':'candidate',error};
    });
    keepPrevious(entry);
    entry.items=items;
    if(!entry.custom)entry.size=rules.chunk_size;
    entry.message=files.length>rules.max_files?`本批只接收前 ${rules.max_files} 个文件，请另开一批处理其余文件。`:'';
    entry.step=entry.custom?2:3;
    refreshView(draft,entry);
    if(!entry.custom)submit(draft,entry);
  }
  function connectionPanel(draft,entry,main){
    const connection=draft.connections?.[entry.source];
    const state=connection?.state;
    const panel=mk('section','knowledge-source-panel');main.append(panel);
    if(!connection){
      text(panel,'h3',draft.connectionError?'来源状态暂未读取':'正在读取来源状态');
      if(draft.connectionError){text(panel,'p',draft.connectionError,'error-text');panel.append(button('重试读取',()=>settings(draft)));}
      return false;
    }
    const name=names[entry.source];
    text(panel,'h3',name+' '+(entry.source==='notion'?{connected:'已绑定',unconfigured:'未绑定'}[state]||availability[state]:availability[state]));
    if(connection.tested_at)text(panel,'p',[connection.workspace,'连接测试 '+fmt(connection.tested_at)].filter(Boolean).join(' · '),'hint');
    if(connection.error)text(panel,'p',connection.error,'error-text');
    if(state==='unavailable'){
      text(panel,'p','当前控制台尚无该工具的读取适配器。可选择 Jina Reader。','hint');return false;
    }
    if(!entry.configuring){
      if(state!=='connected')text(panel,'p',entry.source==='notion'?'使用官方内部集成令牌，先在 Notion 中向集成共享要导入的页面。':'保存并测试 Reader API Key 后可预览公开网页。','hint');
      panel.append(button(state==='connected'?'更换凭据':entry.source==='notion'?'去绑定':'配置工具',()=>{
        entry.configuring=true;render();
      },state!=='connected'));
      if(state==='connected'||state==='failed')panel.append(button(entry.source==='notion'?'解除绑定':'清除配置',async()=>{
        try{
          await call(draft,'sources/'+entry.source,'DELETE');
          keepPrevious(entry);entry.pages=[];entry.selected={};entry.items=[];
          await settings(draft);
        }
        catch(error){message(draft,entry,error.message);}
      }));
      return state==='connected';
    }
    const secret=mk('input');secret.type='password';secret.autocomplete='new-password';
    secret.placeholder=entry.source==='notion'?'粘贴内部集成令牌':'粘贴 Reader API Key';
    label(panel,entry.source==='notion'?'Notion 集成令牌':'Reader API Key',secret);
    const actions=mk('div','actions mt-12');panel.append(actions);
    if(entry.source==='notion'){
      const guide=text(panel,'a','管理 Notion 内部集成','hint');
      guide.href='https://www.notion.so/my-integrations';guide.target='_blank';guide.rel='noopener noreferrer';
    }
    const cancel=button('取消配置',()=>{entry.configuring=false;entry.message='配置已取消，表单内容已保留。';render();});
    actions.append(cancel,button('保存并测试',async event=>{
      if(!secret.value.trim()){secret.focus();return;}
      const control=event.currentTarget;control.disabled=cancel.disabled=true;
      const status=text(panel,'p','正在测试连接…','hint');
      try{
        await call(draft,'sources/'+entry.source,'PUT',{token:secret.value.trim()});
        entry.configuring=false;entry.message='连接测试通过。';entry.pages=null;
        await settings(draft);
      }catch(error){
        entry.message=error.message;status.textContent=error.message;status.className='error-text';
      }finally{secret.value='';control.disabled=cancel.disabled=false;}
    },true));
    return false;
  }
  async function findPages(draft,entry,append=false){
    const request=entry.searchRequest=(entry.searchRequest||0)+1;
    entry.searching=true;entry.error='';
    try{
      const value=await call(draft,'sources/notion/pages','POST',{q:entry.query||'',cursor:append?entry.cursor:null});
      if(request!==entry.searchRequest)return;
      const pages=new Map((append?entry.pages:[]).map(item=>[item.id,item]));
      for(const item of value.items)pages.set(item.id,item);
      entry.pages=[...pages.values()];entry.cursor=value.next_cursor;
    }catch(error){
      if(request===entry.searchRequest){entry.error=error.message;await settings(draft);}
    }finally{
      if(request===entry.searchRequest){entry.searching=false;if(same(draft,entry)&&entry.step===1)render();}
    }
  }
  function notionPages(draft,entry,main){
    const query=mk('input');query.type='search';query.placeholder='按页面标题搜索';query.value=entry.query||'';query.maxLength=100;
    label(main,'选择共享给集成的页面',query);
    query.oninput=()=>{entry.query=query.value;persist(draft);};
    main.append(button('搜索页面',()=>findPages(draft,entry)));
    if(entry.error)text(main,'p',entry.error,'error-text');
    if(!entry.pages&&!entry.searching&&!entry.error)queueMicrotask(()=>findPages(draft,entry));
    if(entry.searching)text(main,'p','正在读取页面…','hint');
    if(entry.pages&&!entry.pages.length)text(main,'p','暂无匹配页面。请核对共享权限或搜索词。','hint');
    const list=mk('div','knowledge-source-pages');main.append(list);
    const selected=Object.values(entry.selected);
    const caption=text(main,'p',`已选 ${selected.length} 个页面`,'hint');
    const next=button('读取所选页面',()=>preview(draft,entry,Object.keys(entry.selected)),true);
    next.disabled=!selected.length||entry.busy;
    for(const page of new Map([...selected,...(entry.pages||[])].map(item=>[item.id,item])).values()){
      const row=text(list,'label','','check'), check=mk('input');
      check.type='checkbox';check.checked=Boolean(entry.selected[page.id]);row.append(check,document.createTextNode(page.title));
      check.onchange=()=>{
        if(check.checked&&Object.keys(entry.selected).length>=defaults.max_files){
          check.checked=false;caption.textContent='每批最多选择 5 个页面。';return;
        }
        if(check.checked)entry.selected[page.id]=page;else delete entry.selected[page.id];
        next.disabled=!Object.keys(entry.selected).length||entry.busy;
        caption.textContent=`已选 ${Object.keys(entry.selected).length} 个页面`;persist(draft);
      };
    }
    if(entry.cursor)main.append(button('加载更多页面',()=>findPages(draft,entry,true)));
    main.append(next);
  }
  function webPanel(draft,entry,main){
    const field=mk('textarea');field.rows=3;field.value=entry.addresses||'';field.placeholder='https://example.com/report';
    label(main,'公开网页地址（每行一个，最多 5 个）',field);
    field.oninput=()=>{entry.addresses=field.value;persist(draft);};
    const read=button('读取网页预览',()=>preview(draft,entry,lines(field.value)),true);
    read.disabled=Boolean(entry.busy);main.append(read);
  }
  async function preview(draft,entry,inputs,retry=false){
    if(entry.busy)return;
    if(!inputs.length||inputs.length>defaults.max_files)return message(draft,entry,'请提供 1 至 5 条来源。');
    if(!draft.target&&!draft.name.trim())return message(draft,entry,'请先填写知识库名称。');
    entry.busy=true;message(draft,entry,'正在读取来源，请稍候。');
    try{
      const response=await call(draft,'sources/'+entry.source+'/preview','POST',{items:inputs},draft.target||draft.library);
      const items=response.items.map(item=>({key:id(),input:item.input,name:item.title||entry.selected[item.input]?.title||item.input,
        preview:item.id,url:item.url,excerpt:item.excerpt,status:item.error?'preview_failed':'candidate',error:item.error}));
      if(retry){
        entry.items=entry.items.map(item=>item.status==='preview_failed'?items.find(newItem=>newItem.input===item.input)||item:item);
      }else {
        keepPrevious(entry);
        entry.items=items;
      }
      entry.step=1;
      entry.message=items.some(item=>item.error)?'部分来源读取失败，可重试失败项。':'已读取来源，请核对预览。';
      if(response.items.some(item=>item.code==='SOURCE_AUTH'))await settings(draft);
    }catch(error){entry.message=error.message;}
    finally{entry.busy=false;refreshView(draft,entry);}
  }
  function keepPrevious(entry){
    const receipts=entry.items.filter(item=>item.doc||item.error)
      .map(({file,segments,excerpt,preview,...item})=>item);
    if(receipts.length)entry.history=[...receipts,...(entry.history||[])].slice(0,20);
  }
  async function submit(draft,entry,one=null){
    if(entry.busy)return;
    const candidates=one?[one]:entry.items.filter(item=>item.status==='candidate');
    if(!candidates.length){message(draft,entry,'请先选择可导入的资料。');return;}
    if(entry.source!=='upload')entry.message='';
    entry.busy=true;entry.step=3;refreshView(draft,entry);
    try{
      const target=await ensureTarget(draft);
      for(const item of candidates){
        item.status='sending';item.error='';refreshView(draft,entry);
        try{
          const result=item.preview
            ? await call(draft,'import/submit','POST',{id:item.preview,chunk_size:entry.size})
            : await draft.bridge.upload(item.file,{context:{...draft.bridge.context,knowledgeLibrary:target},chunkSize:entry.size,metadata:item.metadata});
          item.doc=result.id;item.status=result.status;item.error=result.error_message;
        }catch(error){item.status='submit_failed';item.error=error.message;}
        refreshView(draft,entry);
      }
      if(visible(draft))await draft.bridge.refresh(target);
    }catch(error){
      entry.step=1;entry.message=error.message;
    }finally{
      entry.busy=false;refreshView(draft,entry);schedule();
    }
  }
  function listItems(draft,entry,main,items=entry.items){
    const list=mk('div','knowledge-import-list');main.append(list);
    for(const item of items){
      const row=mk('article','knowledge-import-row');list.append(row);
      text(row,'strong',item.name);
      text(row,'span',statuses[item.status]||({candidate:'待确认',sending:'正在提交',invalid:'无效文件',
        preview_failed:'读取失败',submit_failed:'提交失败'})[item.status]||item.status,'tag');
      if(item.url)text(row,'p',item.url,'hint');
      if(item.error)text(row,'p',item.error,'error-text');
      if(item.excerpt&&entry.step!==3){
        const details=mk('details');row.append(details);
        text(details,'summary','正文预览');text(details,'p',item.excerpt,'source-text');
      }
      const actions=mk('div','actions');row.append(actions);
      if(item.doc){
        actions.append(button('查看文档',()=>draft.bridge.viewDocument(draft.target,item.doc)));
        if(item.status==='ready')actions.append(button('召回测试',()=>draft.bridge.recall(draft.target)));
        if(item.status==='failed')actions.append(button('重试处理',async()=>{
          try{const result=await call(draft,'documents/'+item.doc+'/retry','POST',{});
            item.status=result.status;item.error=result.error_message;refreshView(draft,entry);schedule();}
          catch(error){message(draft,entry,error.message);}
        }));
      }
      if(items===entry.items&&item.status==='submit_failed'){
        if(item.file||item.preview)actions.append(button('重试提交',()=>submit(draft,entry,item)));
        else text(actions,'span','请选择原文件以重试。','hint');
      }
    }
    if(items===entry.items&&items.some(item=>item.status==='preview_failed'))main.append(button('重试读取失败项',()=>
      preview(draft,entry,entry.items.filter(item=>item.status==='preview_failed').map(item=>item.input),true)));
  }
  function previousImports(draft,entry,main){
    if(!entry.history?.length)return;
    const history=mk('details','knowledge-import-history');
    text(history,'summary',`近期导入 · ${entry.history.length} 条`);
    listItems(draft,entry,history,entry.history);
    main.append(history);
  }
  function schedule(){
    clearTimeout(timer);
    const draft=active;
    if(!draft||!visible(draft)||!draft.target)return;
    const items=Object.values(draft.jobs).flatMap(entry=>[...entry.items,...(entry.history||[])])
      .filter(item=>item.doc&&['pending','processing'].includes(item.status));
    if(!items.length)return;
    timer=setTimeout(async()=>{
      const responses=await Promise.allSettled([call(draft,'queue'),...items.map(item=>call(draft,'documents/'+item.doc))]);
      const [queue,...details]=responses;
      if(queue.status==='fulfilled')draft.worker=queue.value.worker;
      else draft.pollError=queue.reason.message;
      let published=false;
      for(const [index,result]of details.entries()){
        if(result.status==='fulfilled'){
          items[index].status=result.value.status;items[index].error=result.value.error_message;
          published ||= result.value.status==='ready';
        }else draft.pollError=result.reason.message;
      }
      if(details.every(result=>result.status==='fulfilled')&&queue.status==='fulfilled')draft.pollError='';
      persist(draft);
      if(visible(draft)){if(current(draft).step===3)render();if(published)draft.bridge.refresh(draft.target);schedule();}
    },1800);
  }
  function resultPanel(draft,entry,main){
    text(main,'h2','处理结果');
    text(main,'p','文件接收后进入处理队列，显示「可检索」时可查看召回来源。','hint');
    if(entry.items.some(item=>item.status==='pending')&&draft.worker&&!draft.worker.online)
      text(main,'p','处理进程离线。资料仍在队列中，进程恢复后继续处理。','warn');
    if(draft.pollError)text(main,'p','读取处理状态失败 · '+draft.pollError+'。将自动重试。','error-text');
    listItems(draft,entry,main);
    const more=button('继续添加资料',()=>{entry.step=1;refreshView(draft,entry);});
    more.disabled=Boolean(entry.busy);main.append(more);
    if(draft.target)main.append(button('查看文档列表',()=>draft.bridge.viewDocument(draft.target),true));
    previousImports(draft,entry,main);
  }
  function render(){
    const draft=active;
    if(!draft||!visible(draft))return;
    const entry=job(draft), head=mk('div','knowledge-step-head'), main=mk('div','knowledge-create-body');
    host.replaceChildren(head,main);head.append(button('← 返回知识库',draft.bridge.back));
    const steps=mk('ol','knowledge-steps');steps.setAttribute('aria-label','导入步骤');head.append(steps);
    ['选择数据源','分段与清洗','处理结果'].forEach((title,index)=>{
      const row=mk('li');steps.append(row);
      const control=button(title,()=>{entry.step=index+1;entry.configuring=false;refreshView(draft,entry);});
      control.disabled=entry.busy||index+1>entry.step||index+1===entry.step;
      if(index+1===entry.step)control.setAttribute('aria-current','step');
      text(control,'span',String(index+1),'knowledge-step-number').setAttribute('aria-hidden','true');
      row.append(control);
    });
    text(main,'h1',draft.target?'添加资料':'创建知识库');
    if(draft.target)text(main,'p','目标知识库 · '+draft.name,'hint');
    else{
      const fields=mk('div','knowledge-create-target');main.append(fields);
      const name=mk('input');name.value=draft.name;name.maxLength=80;name.required=true;
      const description=mk('input');description.value=draft.description;description.maxLength=500;
      label(fields,'知识库名称',name);label(fields,'描述（可选）',description);
      name.oninput=()=>{draft.name=name.value;persist(draft);};
      description.oninput=()=>{draft.description=description.value;persist(draft);};
      fields.append(button('创建空知识库',async event=>{
        if(!name.reportValidity())return;
        const control=event.currentTarget;control.disabled=true;
        try{const target=await ensureTarget(draft);if(visible(draft))await draft.bridge.viewDocument(target);}
        catch(error){message(draft,entry,error.message);}
        finally{control.disabled=false;}
      }));
    }
    if(entry.message)text(main,'p',entry.message,'hint').setAttribute('role','status');
    if(entry.step===2){settingsPanel(draft,entry,main);return;}
    if(entry.step===3){resultPanel(draft,entry,main);return;}
    text(main,'h2','选择数据源');
    const options=mk('div','knowledge-source-options');options.setAttribute('role','group');options.setAttribute('aria-label','资料来源');main.append(options);
    for(const [key,icon,title]of sources){
      const control=button('',()=>choose(draft,key));
      control.dataset.knowledgeSource=key;control.classList.toggle('selected',draft.source===key);
      control.setAttribute('aria-pressed',String(draft.source===key));
      text(control,'span',icon,'knowledge-source-mark').setAttribute('aria-hidden','true');
      text(control,'span',title);options.append(control);
    }
    options.onkeydown=event=>{
      const keys=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'];
      if(!keys.includes(event.key))return;
      event.preventDefault();
      const index=sources.findIndex(([key])=>key===draft.source);
      const next=sources[(index+(keys.indexOf(event.key)%2?1:2))%3][0];
      choose(draft,next);host.querySelector('[data-knowledge-source="'+next+'"]')?.focus();
    };
    if(draft.source==='upload'){filesPanel(draft,entry,main);previousImports(draft,entry,main);return;}
    if(draft.source==='web'){
      const group=mk('div','actions knowledge-web-tools');group.setAttribute('role','group');group.setAttribute('aria-label','网页读取工具');
      main.append(group);
      for(const [key,title]of tools){
        const status=draft.connections?.[key]?.state;
        const choice=button(title+(status?' · '+availability[status]:''),()=>{draft.tool=key;persist(draft);render();});
        choice.setAttribute('aria-pressed',String(draft.tool===key));group.append(choice);
      }
    }
    if(!connectionPanel(draft,entry,main)){previousImports(draft,entry,main);return;}
    if(draft.source==='notion')notionPages(draft,entry,main);else webPanel(draft,entry,main);
    if(entry.items.length)listItems(draft,entry,main);
    if(entry.items.some(item=>item.status==='candidate'))
      main.append(button('下一步',()=>{entry.step=2;refreshView(draft,entry);},true));
    if(entry.items.some(item=>item.doc))
      main.append(button('查看处理结果',()=>{entry.step=3;refreshView(draft,entry);schedule();}));
    previousImports(draft,entry,main);
  }
  return {open,leave,shouldResume};
})();
