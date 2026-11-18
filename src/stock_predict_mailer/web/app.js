"use strict";
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="upload-session"]').content;
let current = null;
let selectionRevision = 0, refreshRevision = 0;
const states = {ready: "检查通过", needs_attention: "待确认", rejected: "已隔离"};
const kinds = {bars:"股票日行情",financial:"财务数据",news:"新闻与公告",macro:"宏观指标",table:"其他表格",document:"文本资料"};
function element(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
function notice(text, error=false) { $("notice").textContent=text; $("notice").className=error?"error":""; }
async function api(path, options={}) {
  const headers = {"X-Upload-Token":token, ...(options.headers||{})};
  const response=await fetch(path,{...options,headers});
  const value=await response.json(); if(!response.ok) throw new Error(value.error||"请求失败"); return value;
}
function post(path, values) { return api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)}); }
function badge(status) { return element("span",states[status]||status,"badge "+status); }
async function refresh() {
  const revision=++refreshRevision, data=await api("/api/uploads");
  if(window.DesktopIntake && revision!==refreshRevision)return;
  $("incoming").textContent=data.incoming;
  if(!window.DesktopIntake?.renderList(data.uploads,fileRow)) {
    $("file-list").replaceChildren();
    if(!data.uploads.length) $("file-list").append(element("p","还没有资料。选择文件或扫描投放目录开始处理。","muted"));
    for(const file of data.uploads)$("file-list").append(fileRow(file));
  }
  window.DesktopIntake?.listing(data.uploads);
}
function fileRow(file) {
  const button=element("button",undefined,"file-row"+(current?.upload_id===file.upload_id?" active":""));
  button.dataset.uploadId=file.upload_id;button.dataset.fileState=file.status;
  button.append(element("span",file.filename,"file-name"),element("span",`${file.format.toUpperCase()} · ${(file.bytes/1024).toFixed(1)} KB`,"file-meta"),badge(file.status));
  button.addEventListener("click",async()=>{const revision=++selectionRevision;try {const selected=await api("/api/uploads/"+file.upload_id);if(window.DesktopIntake && revision!==selectionRevision)return;render(selected);await refresh();} catch(e){notice(e.message,true);}});
  return button;
}
function render(file) {
  current=file; $("selected").hidden=false; $("selection-hint").hidden=true;
  $("file-summary").replaceChildren(element("h3",file.filename),badge(file.status),element("span",file.format.toUpperCase(),"badge"));
  if(file.error) $("file-summary").append(element("p",file.error.message,"file-error"));
  $("kind").value=file.options.kind||"auto"; $("source").value=file.options.source||"";
  $("price-basis").value=file.options.price_basis||"unknown"; $("volume-unit").value=file.options.volume_unit||"unknown";
  $("available-at").value=file.options.available_at||""; $("column-map").value=file.options.column_map?JSON.stringify(file.options.column_map):"";
  $("tables").replaceChildren();
  if(file.document_preview!==undefined) {
    $("tables").append(element("h3","文本预览"),element("p",file.needs_confirmation.join("；"),"needs"),element("pre",file.document_preview));
  }
  for(const table of file.tables) {
    $("tables").append(element("h3",`${table.name} · ${kinds[table.kind]||table.kind}`),badge(table.status),element("p",`输入 ${table.input_rows} 行 → 保留 ${table.output_rows} 行 · 重复 ${table.duplicates_removed} 行 · 隔离 ${table.excluded_rows} 行`));
    if(table.date_range) $("tables").append(element("p",`${table.security_count} 只证券 · ${table.date_range[0]} 至 ${table.date_range[1]}`,"muted"));
    if(table.needs_confirmation.length) $("tables").append(element("p","待确认："+table.needs_confirmation.join("；"),"needs"));
    const wrap=element("div",undefined,"table-scroll"), grid=element("table"), head=element("tr");
    const keys=[...new Set(table.preview.flatMap(row=>Object.keys(row)))];
    keys.forEach(key=>head.append(element("th",key))); const thead=element("thead");thead.append(head);grid.append(thead);
    const tbody=element("tbody");for(const row of table.preview){const tr=element("tr");keys.forEach(key=>tr.append(element("td",row[key]===null||row[key]===undefined?"—":String(row[key]))));tbody.append(tr);} grid.append(tbody);wrap.append(grid);$("tables").append(wrap);
    if(table.kind==="bars") {
      const publish=element("button","发布为训练用行情快照","secondary");
      publish.dataset.intakePublish=String(table.index);
      publish.disabled=table.status!=="ready";
      publish.addEventListener("click",async()=>{if(window.DesktopIntake?.busy)return;window.DesktopIntake?.lock();publish.disabled=true;let received=false;try{const result=await post("/api/publish",{upload_id:file.upload_id,table_index:table.index});received=true;window.DesktopIntake?.published(file,table.index,result);notice("已发布行情快照："+result.snapshot_id);}catch(e){notice(e.message,true);}finally{window.DesktopIntake?.unlock();publish.disabled=table.status!=="ready"||Boolean(window.DesktopIntake&&received);if(window.DesktopIntake&&received)publish.textContent="本页已收到发布回执";}});
      $("tables").append(publish);
    }
  }
  $("issues").replaceChildren();
  if(file.issue_count) {
    $("issues").append(element("h3",`问题记录 · ${file.issue_count} 条`),element("p","页面最多显示 200 条，完整清单保存在本机处理目录。","muted"));
    file.issues.forEach(issue=>{const node=element("div",`${issue.table} · 记录 ${issue.row} · ${issue.field||issue.code}：${issue.message}`,"issue");node.dataset.issueField=issue.field||issue.code||"未指定字段";$("issues").append(node);});
  }
  window.DesktopIntake?.selected(file);
}
async function uploadFiles(files) {
  files=Array.from(files);if(!files.length)return;
  if(window.DesktopIntake?.busy){notice("已有一批文件正在处理，请等待本批结束。",true);return;}
  const selectedAtStart=selectionRevision;window.DesktopIntake?.begin(files);
  let failed=0;const control=$("files");control.disabled=true;
  for(const [index,file] of files.entries()) {
    window.DesktopIntake?.start(index);
    if(file.size>50*1024*1024){notice(file.name+" 超过 50MB，请拆分后上传。",true);failed++;window.DesktopIntake?.outcome(index,null,"超过 50 MiB，请拆分后重新选择文件。",false);continue;}
    notice("正在识别与清洗："+file.name);
    try {const result=await api("/api/upload?name="+encodeURIComponent(file.name),{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});if(!window.DesktopIntake||selectedAtStart===selectionRevision)render(result);window.DesktopIntake?.outcome(index,result);}
    catch(e){notice(e.message,true);failed++;window.DesktopIntake?.outcome(index,null,e.message,true);}
  }
  control.disabled=false;control.value="";window.DesktopIntake?.end();await refresh();notice(failed?`处理结束，${failed} 个文件未完成，请检查格式或大小。`:"处理完成。请查看待确认信息和问题记录。",failed>0);
}
$("files").addEventListener("change",e=>uploadFiles([...e.target.files]).catch(e=>notice(e.message,true)));
const zone=$("drop-zone");zone.addEventListener("dragover",e=>{e.preventDefault();zone.classList.add("dragging");});zone.addEventListener("dragleave",()=>zone.classList.remove("dragging"));zone.addEventListener("drop",e=>{e.preventDefault();zone.classList.remove("dragging");uploadFiles([...e.dataTransfer.files]).catch(e=>notice(e.message,true));});
$("options-form").addEventListener("submit",async e=>{
  e.preventDefault();if(!current||window.DesktopIntake?.busy)return;const button=e.submitter||$("options-form").querySelector('button[type="submit"]');window.DesktopIntake?.lock();button.disabled=true;
  const selectedAtStart=selectionRevision,target=current.upload_id;
  try {const options={kind:$("kind").value,source:$("source").value.trim(),price_basis:$("price-basis").value,volume_unit:$("volume-unit").value};
    if($("available-at").value.trim())options.available_at=$("available-at").value.trim();
    if($("column-map").value.trim())options.column_map=JSON.parse($("column-map").value);
    notice("正在重新清洗…");const result=await post("/api/process",{upload_id:target,options});const same=!window.DesktopIntake||selectedAtStart===selectionRevision;if(same)render(result);await refresh();notice(same?"信息已保存，清洗结果已更新。":"该文件的信息已保存，可从文件记录重新查看结果。");
  }catch(error){notice(error.message,true);}finally{button.disabled=false;window.DesktopIntake?.unlock();}
});
$("scan").addEventListener("click",async e=>{if(window.DesktopIntake?.busy)return;window.DesktopIntake?.lock();e.target.disabled=true;try{notice("正在扫描投放目录…");const r=await post("/api/scan",{});await refresh();notice(`扫描完成，共 ${r.processed.length} 个文件。`);}catch(error){notice(error.message,true);}finally{e.target.disabled=false;window.DesktopIntake?.unlock();}});
$("refresh").addEventListener("click",()=>refresh().catch(e=>notice(e.message,true)));
refresh().catch(e=>notice(e.message,true));

/* Desktop intake guidance; original endpoints and immutable processing receipts remain authoritative. */
window.DesktopIntake = (() => {
  if (!matchMedia('(min-width: 761px)').matches) return;
  const make=element, receipts=new Map(), locked=new Map();
  let busy=false, batch=[], records=[], filter='all', index=new Map(), counts={};
  const rows=new Map();
  const action=(text,fn)=>{const node=make('button',text,'secondary');node.type='button';node.onclick=fn;return node;};
  const lockNew=()=>{for(const node of document.querySelectorAll('#files,#scan,#options-form button,[data-intake-publish]')){if(!locked.has(node))locked.set(node,node.disabled);node.disabled=true;}};
  const lock=()=>{busy=true;lockNew();};
  const unlock=()=>{busy=false;for(const[node,disabled]of locked)node.disabled=disabled;locked.clear();};
  const themeLabel=make('label','外观','intake-theme'),theme=make('select');theme.id='intake-theme';theme.setAttribute('aria-label','数据接入中心外观');
  for(const[value,title]of [['system','跟随系统'],['dark','深色'],['light','浅色']])theme.add(new Option(title,value));
  let preference='system';try{preference=localStorage.getItem('spm-intake-theme')||'system';}catch(_){}
  theme.value=['system','dark','light'].includes(preference)?preference:'system';
  const systemTheme=matchMedia('(prefers-color-scheme: dark)');
  const applyTheme=()=>document.documentElement.dataset.intakeTheme=theme.value==='system'?(systemTheme.matches?'dark':'light'):theme.value;
  theme.onchange=()=>{applyTheme();try{localStorage.setItem('spm-intake-theme',theme.value);}catch(_){}};systemTheme.addEventListener('change',applyTheme);applyTheme();themeLabel.append(theme);document.querySelector('header').append(themeLabel);

  const batchPanel=make('section',undefined,'intake-batch');batchPanel.id='intake-batch';batchPanel.hidden=true;batchPanel.setAttribute('aria-label','本批文件处理结果');
  const batchTitle=make('h2','本批处理结果'),batchStatus=make('p',undefined,'muted'),batchList=make('ol'),retry=action('重新上传失败项',()=>uploadFiles(batch.filter(item=>item.state==='failed'&&item.retryable).map(item=>item.file)).catch(error=>notice(error.message,true)));
  batchStatus.setAttribute('role','status');batchStatus.setAttribute('aria-live','polite');batchPanel.append(batchTitle,batchStatus,batchList,retry);zone.after(batchPanel);
  function paintBatch() {
    batchList.replaceChildren();let completed=0,failed=0,attention=0;
    for(const item of batch){if(!['waiting','processing'].includes(item.state))completed++;if(item.state==='failed')failed++;if(item.state==='needs_attention'||item.state==='rejected')attention++;
      const row=make('li'),title=make('span',item.file.name,'file-name'),state=make('span',({waiting:'等待处理',processing:'正在处理',failed:'未完成',...states})[item.state],'badge '+item.state);row.append(title,state);if(item.message)row.append(make('span',item.message,'muted'));batchList.append(row);}
    batchStatus.textContent=`已完成 ${completed} / ${batch.length} 个文件${failed?' · '+failed+' 个未完成':''}${attention?' · '+attention+' 个需查看处理结果':''}。按文件依次处理。`;
    retry.hidden=busy||!batch.some(item=>item.state==='failed'&&item.retryable);
  }
  const toolbar=make('div',undefined,'intake-record-tools'),chips=make('div',undefined,'intake-filters'),searchLabel=make('label','查找文件名'),search=make('input'),scope=make('p',undefined,'muted'),empty=make('p','没有符合条件的已加载记录。','muted');
  search.id='intake-file-search';search.type='search';search.placeholder='仅筛选已加载记录';searchLabel.append(search);scope.id='intake-record-scope';empty.hidden=true;
  for(const[value,title]of [['all','全部'],['needs_attention','待确认'],['rejected','已隔离'],['ready','检查通过']]){const node=action(title,()=>{filter=value;paintRecords();});node.dataset.filter=value;node.dataset.label=title;chips.append(node);}
  toolbar.append(chips,searchLabel,scope);$('file-list').before(toolbar);$('file-list').after(empty);search.oninput=paintRecords;
  function paintRecords(){let visible=0;const term=search.value.trim().toLocaleLowerCase();
    for(const node of $('file-list').querySelectorAll('.file-row')){const file=index.get(node.dataset.uploadId),hidden=!file||(filter!=='all'&&file.status!==filter)||!file.name.includes(term);if(node.hidden!==hidden)node.hidden=hidden;if(!hidden)visible++;}
    for(const node of chips.children){const count=node.dataset.filter==='all'?records.length:counts[node.dataset.filter]||0;const text=`${node.dataset.label} ${count}`;if(node.textContent!==text)node.textContent=text;node.setAttribute('aria-pressed',String(filter===node.dataset.filter));}
    scope.textContent=`显示 ${visible} / ${records.length} 条已加载记录`;empty.hidden=!records.length||visible>0;
  }

  const guide=make('section',undefined,'intake-next');guide.id='intake-next';$('file-summary').after(guide);
  const issueTools=make('div',undefined,'intake-issue-tools'),issueLabel=make('label','按问题字段筛选'),issueField=make('select'),issueCount=make('p',undefined,'muted');issueField.id='intake-issue-field';issueLabel.append(issueField);issueTools.append(issueLabel,issueCount);$('issues').before(issueTools);issueField.onchange=paintIssues;
  function paintIssues(){const nodes=[...$('issues').querySelectorAll('.issue')];let shown=0;for(const node of nodes){node.hidden=issueField.value!=='all'&&node.dataset.issueField!==issueField.value;if(!node.hidden)shown++;}issueCount.textContent=`显示 ${shown} / ${nodes.length} 条已加载问题 · 本次处理共 ${current?.issue_count||0} 条`;}
  function jump(id){const target=$(id);const details=target.closest('details');if(details)details.open=true;target.scrollIntoView({block:'center',behavior:'smooth'});if(target.matches('input,select,textarea'))target.focus({preventScroll:true});}

  const mapping=make('details',undefined,'intake-mapping full');mapping.append(make('summary','辅助填写字段映射'),make('p','左侧填标准字段，右侧填文件中的原始列名。应用后仍需保存信息并重新清洗。','muted'));
  const mappingRow=make('div',undefined,'intake-mapping-row'),canonicalLabel=make('label','标准字段'),originalLabel=make('label','原始列名'),canonical=make('input'),original=make('input'),mappingStatus=make('p',undefined,'muted'),entries=make('div',undefined,'intake-mapping-entries');
  canonical.id='intake-map-target';canonical.placeholder='如 date / security_id';original.id='intake-map-source';original.placeholder='如 采集日期 / 证券编号';canonicalLabel.append(canonical);originalLabel.append(original);mappingStatus.setAttribute('role','status');
  function readMapping(){const value=JSON.parse($('column-map').value.trim()||'{}');if(!value||typeof value!=='object'||Array.isArray(value)||Object.values(value).some(item=>typeof item!=='string'))throw Error('字段映射需要 JSON 对象，值须为原始列名。当前输入已保留。');return value;}
  function mappingError(error){mapping.open=true;mappingStatus.textContent=error.message;mappingStatus.classList.add('error');jump('column-map');}
  function paintMapping(){entries.replaceChildren();try{for(const[key,value]of Object.entries(readMapping())){const row=make('div');row.append(make('code',`${key} ← ${value}`),action('移除此映射',()=>{try{const values=readMapping();delete values[key];$('column-map').value=JSON.stringify(values,null,2);paintMapping();mappingStatus.textContent='已从表单移除，保存后生效。';}catch(error){mappingError(error);}}));entries.append(row);}}catch(_){entries.append(make('p','当前原始 JSON 无法解析；修正后可继续使用辅助填写。','muted'));}}
  const applyMapping=action('应用映射',()=>{if(!canonical.value.trim()||!original.value.trim()){mappingStatus.textContent='请同时填写标准字段和原始列名。';mappingStatus.classList.add('error');return;}try{const values=readMapping();$('column-map').value=JSON.stringify({...values,[canonical.value.trim()]:original.value.trim()},null,2);canonical.value=original.value='';mappingStatus.textContent='映射已更新到表单，尚未重新清洗。';mappingStatus.classList.remove('error');paintMapping();}catch(error){mappingError(error);}});
  mappingRow.append(canonicalLabel,originalLabel,applyMapping);mapping.append(mappingRow,mappingStatus,entries);$('column-map').closest('label').before(mapping);$('column-map').addEventListener('input',paintMapping);
  $('options-form').addEventListener('submit',event=>{try{readMapping();if(canonical.value.trim()||original.value.trim())throw Error('辅助填写还有未应用内容，请先应用映射或清空这两个输入框。');}catch(error){event.preventDefault();event.stopImmediatePropagation();mappingError(error);}},true);

  function paintGuide(file){guide.replaceChildren(make('h3','本次处理结果'));
    const totals=file.tables.reduce((sum,table)=>[sum[0]+table.input_rows,sum[1]+table.output_rows,sum[2]+table.duplicates_removed,sum[3]+table.excluded_rows],[0,0,0,0]);
    guide.append(make('p',file.tables.length?`输入 ${totals[0]} 行 · 保留 ${totals[1]} 行 · 去重 ${totals[2]} 行 · 隔离 ${totals[3]} 行`:'当前文件没有可预览的表格。'));
    const confirmations=[...new Set([...(file.needs_confirmation||[]),...file.tables.flatMap(table=>table.needs_confirmation||[])])];
    guide.append(make('p',file.status==='ready'?'检查已通过。行情表可按下方操作单独发布快照。':file.status==='rejected'?'文件已隔离，请先查看错误与问题记录。':confirmations.length?confirmations.join('；'):'请核对资料信息与问题记录。','muted'));
    const actions=make('div',undefined,'intake-next-actions');actions.append(action('确认资料信息',()=>jump('source')));if(file.issue_count)actions.append(action('查看问题记录',()=>jump('intake-issue-field')));actions.append(action('查看清洗预览',()=>jump('tables')));guide.append(actions);
    for(const table of file.tables){const receipt=receipts.get(`${file.job_id}:${table.index}`);if(receipt)guide.append(make('p',`表 ${table.index} · 本页发布回执：${receipt.snapshot_id}`,'muted'));}
  }
  function selected(file){canonical.value=original.value='';mappingStatus.textContent='';mappingStatus.classList.remove('error');paintMapping();paintGuide(file);
    issueField.replaceChildren(new Option('全部问题字段','all'));for(const name of new Set(file.issues.map(issue=>issue.field||issue.code||'未指定字段')))issueField.add(new Option(name,name));issueTools.hidden=!file.issue_count;paintIssues();
    for(const node of $('tables').querySelectorAll('[data-intake-publish]'))if(receipts.has(`${file.job_id}:${node.dataset.intakePublish}`)){node.disabled=true;node.textContent='本页已收到发布回执';}
    if(busy)lockNew();
  }
  return {get busy(){return busy;},lock,unlock,
    begin(files){batch=files.map(file=>({file,state:'waiting',message:'',retryable:false}));lock();batchPanel.hidden=false;paintBatch();},
    start(index){batch[index].state='processing';paintBatch();},
    outcome(index,result,message='',retryable=false){Object.assign(batch[index],{state:result?.status||'failed',message,retryable});paintBatch();},
    end(){unlock();paintBatch();},listing(data){records=data;index=new Map(data.map(file=>[file.upload_id,{name:file.filename.toLocaleLowerCase(),status:file.status}]));counts={};for(const file of data)counts[file.status]=(counts[file.status]||0)+1;paintRecords();},selected,
    renderList(files,create){
      const host=$('file-list'),nodes=[],ids=new Set(),focused=host.contains(document.activeElement)?document.activeElement:null;
      for(const file of files){ids.add(file.upload_id);const signature=JSON.stringify([file.filename,file.format,file.bytes,file.status]);let entry=rows.get(file.upload_id);
        if(!entry){entry={node:create(file),signature};rows.set(file.upload_id,entry);}
        else if(entry.signature!==signature){const fresh=create(file);entry.node.replaceChildren(...fresh.childNodes);Object.assign(entry.node.dataset,fresh.dataset);entry.signature=signature;}
        entry.node.classList.toggle('active',current?.upload_id===file.upload_id);nodes.push(entry.node);
      }
      for(const[id]of rows)if(!ids.has(id))rows.delete(id);
      if(!files.length)nodes.push(element('p','还没有资料。选择文件或扫描投放目录开始处理。','muted'));
      let cursor=host.firstChild;for(const node of nodes){if(node===cursor)cursor=cursor.nextSibling;else host.insertBefore(node,cursor);}while(cursor){const next=cursor.nextSibling;cursor.remove();cursor=next;}
      if(focused?.isConnected&&document.activeElement!==focused)focused.focus({preventScroll:true});return true;
    },
    published(file,index,result){receipts.set(`${file.job_id}:${index}`,result);if(current?.job_id===file.job_id)paintGuide(file);}
  };
})();
