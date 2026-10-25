"use strict";
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="upload-session"]').content;
let current = null;
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
  const data=await api("/api/uploads"); $("incoming").textContent=data.incoming;
  $("file-list").replaceChildren();
  if(!data.uploads.length) $("file-list").append(element("p","还没有资料。选择文件或扫描投放目录开始处理。","muted"));
  for(const file of data.uploads) {
    const button=element("button",undefined,"file-row"+(current?.upload_id===file.upload_id?" active":""));
    button.append(element("span",file.filename,"file-name"),element("span",`${file.format.toUpperCase()} · ${(file.bytes/1024).toFixed(1)} KB`,"file-meta"),badge(file.status));
    button.addEventListener("click",async()=>{try {render(await api("/api/uploads/"+file.upload_id));await refresh();} catch(e){notice(e.message,true);}});
    $("file-list").append(button);
  }
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
      publish.disabled=table.status!=="ready";
      publish.addEventListener("click",async()=>{publish.disabled=true;try{const result=await post("/api/publish",{upload_id:file.upload_id,table_index:table.index});notice("已发布行情快照："+result.snapshot_id);}catch(e){notice(e.message,true);}finally{publish.disabled=table.status!=="ready";}});
      $("tables").append(publish);
    }
  }
  $("issues").replaceChildren();
  if(file.issue_count) {
    $("issues").append(element("h3",`问题记录 · ${file.issue_count} 条`),element("p","页面最多显示 200 条，完整清单保存在本机处理目录。","muted"));
    file.issues.forEach(issue=>$("issues").append(element("div",`${issue.table} · 记录 ${issue.row} · ${issue.field||issue.code}：${issue.message}`,"issue")));
  }
}
async function uploadFiles(files) {
  let failed=0;const control=$("files");control.disabled=true;
  for(const file of files) {
    if(file.size>50*1024*1024){notice(file.name+" 超过 50MB，请拆分后上传。",true);failed++;continue;}
    notice("正在识别与清洗："+file.name);
    try {render(await api("/api/upload?name="+encodeURIComponent(file.name),{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file}));}
    catch(e){notice(e.message,true);failed++;}
  }
  control.disabled=false;control.value="";await refresh();notice(failed?`处理结束，${failed} 个文件未完成，请检查格式或大小。`:"处理完成。请查看待确认信息和问题记录。",failed>0);
}
$("files").addEventListener("change",e=>uploadFiles([...e.target.files]).catch(e=>notice(e.message,true)));
const zone=$("drop-zone");zone.addEventListener("dragover",e=>{e.preventDefault();zone.classList.add("dragging");});zone.addEventListener("dragleave",()=>zone.classList.remove("dragging"));zone.addEventListener("drop",e=>{e.preventDefault();zone.classList.remove("dragging");uploadFiles([...e.dataTransfer.files]).catch(e=>notice(e.message,true));});
$("options-form").addEventListener("submit",async e=>{
  e.preventDefault();if(!current)return;const button=e.submitter;button.disabled=true;
  try {const options={kind:$("kind").value,source:$("source").value.trim(),price_basis:$("price-basis").value,volume_unit:$("volume-unit").value};
    if($("available-at").value.trim())options.available_at=$("available-at").value.trim();
    if($("column-map").value.trim())options.column_map=JSON.parse($("column-map").value);
    notice("正在重新清洗…");render(await post("/api/process",{upload_id:current.upload_id,options}));await refresh();notice("信息已保存，清洗结果已更新。");
  }catch(error){notice(error.message,true);}finally{button.disabled=false;}
});
$("scan").addEventListener("click",async e=>{e.target.disabled=true;try{notice("正在扫描投放目录…");const r=await post("/api/scan",{});await refresh();notice(`扫描完成，共 ${r.processed.length} 个文件。`);}catch(error){notice(error.message,true);}finally{e.target.disabled=false;}});
$("refresh").addEventListener("click",()=>refresh().catch(e=>notice(e.message,true)));
refresh().catch(e=>notice(e.message,true));
