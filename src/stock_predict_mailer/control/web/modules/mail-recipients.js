/* Desktop mail-seat editor. Saving preferences never sends a message. */
window.MailRecipients=(()=>{
  if(!PonyFloor.hall)return null;
  const field=$('task-recipient');field.multiple=true;
  field.placeholder='多个邮箱用逗号分隔';
  const dialog=document.createElement('dialog');dialog.id='mail-recipients-dialog';dialog.className='mail-recipients-dialog';dialog.setAttribute('aria-labelledby','mail-recipients-title');
  dialog.innerHTML='<form method="dialog"><h2 id="mail-recipients-title">邮箱投递</h2><p class="hint">填写收件邮箱，可自由添加或删除。保存后用于下一次提交的分析，不会立即发送邮件。</p><label class="check"><input id="mail-recipients-enabled" type="checkbox"> 分析完成后投递</label><div id="mail-recipients-list"></div><div class="actions"><button type="button" id="mail-recipients-add" class="btn">＋ 添加邮箱</button><span id="mail-recipients-count" role="status"></span></div><p class="hint">每次最多50个地址，逐地址投递并单独记录结果；仍遵循设置中的收件授权及任务预算。</p><p id="mail-recipients-error" role="alert" class="error-text"></p><div class="actions"><button type="button" id="mail-recipients-cancel" class="btn quiet">取消</button><button type="submit" class="btn primary">保存投递设置</button></div></form>';
  document.body.append(dialog);const list=$('mail-recipients-list');
  const authorize=document.createElement('button');authorize.id='mail-recipients-authorize';authorize.type='button';authorize.className='btn primary';authorize.textContent='授权以上邮箱并保存';authorize.hidden=true;
  $('mail-recipients-error').after(authorize);let saving=false;
  const clearAuthorization=()=>{authorize.hidden=true;$('mail-recipients-error').textContent='';};
  list.addEventListener('input',clearAuthorization);
  dialog.addEventListener('cancel',event=>{if(saving)event.preventDefault();});
  const parse=value=>[...new Set(value.split(/[,;，；\s]+/).map(v=>v.trim()).filter(Boolean))];
  function count(){clearAuthorization();const rows=list.querySelectorAll('input');$('mail-recipients-count').textContent=`${rows.length} 个邮箱输入位`;$('mail-recipients-add').disabled=rows.length>=50;rows.forEach((input,i)=>input.setAttribute('aria-label',`收件邮箱 ${i+1}`));}
  function add(value=''){const row=document.createElement('div');row.className='mail-recipient-row';const input=document.createElement('input');input.type='email';input.required=true;input.placeholder='name@example.com';input.value=value;input.maxLength=254;
    const remove=document.createElement('button');remove.type='button';remove.className='btn quiet';remove.textContent='删除';remove.onclick=()=>{row.remove();count();};row.append(input,remove);list.append(row);count();return input;}
  const requirements=()=>list.querySelectorAll('input').forEach(input=>{input.required=$('mail-recipients-enabled').checked;});
  $('mail-recipients-enabled').onchange=()=>{requirements();clearAuthorization();};
  $('mail-recipients-add').onclick=()=>{const input=add();requirements();input.focus();};$('mail-recipients-cancel').onclick=()=>dialog.close();
  async function save(allowNew=false){
    if(saving||!dialog.querySelector('form').reportValidity())return;
    const emails=parse([...list.querySelectorAll('input')].map(input=>input.value).join(',')),enabled=$('mail-recipients-enabled').checked;
    if(enabled&&!emails.length){$('mail-recipients-error').textContent='请至少添加一个收件邮箱。';return;}
    const allowed=settings?.mail?.recipient_allowlist||[];
    const missing=emails.filter(email=>!allowed.includes(email));
    if(enabled&&missing.length){
      if(!allowNew){$('mail-recipients-error').textContent='以下邮箱尚未授权：'+missing.join('、')+'。可点击下方按钮授权并保存，不会立即发送邮件。';authorize.hidden=false;return;}
      saving=true;const controls=[...dialog.querySelectorAll('input,button')];controls.forEach(node=>{node.disabled=true;});
      try{
        const latest=await api('settings');
        latest.mail.recipient_allowlist=[...new Set([...latest.mail.recipient_allowlist,...emails])];
        settings=await api('settings','PUT',latest);
        $('mail-allowlist').value=settings.mail.recipient_allowlist.join('\n');
      }catch(error){$('mail-recipients-error').textContent='授权未完成：'+error.message+'。已填写邮箱仍保留，请重试。';return;}
      finally{saving=false;controls.forEach(node=>{node.disabled=false;});$('mail-recipients-add').disabled=list.children.length>=50;}
    }
    field.value=emails.join(', ');$('task-notify').checked=enabled;
    for(const node of [field,$('task-notify')])node.dispatchEvent(new Event('change',{bubbles:true}));
    draftSchedule();dialog.close();notice(`已保存 ${emails.length} 个收件邮箱${enabled?'，下次分析完成后投递':'，暂不投递'}。`);
  }
  dialog.querySelector('form').onsubmit=event=>{event.preventDefault();save();};authorize.onclick=()=>save(true);
  function open(){list.replaceChildren();const emails=parse(field.value);(emails.length?emails:['']).forEach(add);$('mail-recipients-enabled').checked=$('task-notify').checked||!emails.length;requirements();clearAuthorization();dialog.showModal();list.querySelector('input')?.focus();}
  return{open,values:()=>parse(field.value)};
})();
