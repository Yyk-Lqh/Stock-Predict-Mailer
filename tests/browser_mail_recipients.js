/* gstack eval on disposable fixture only. Never calls SMTP. */
(async()=>{
 const assert=(value,message)=>{if(!value)throw Error(message);};
 if(!['8768','8769'].includes(location.port))throw Error('Use disposable fixture');
 window.__mailRecipientsCheck={state:'running'};
 const wait=async fn=>{for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out');};
 await wait(()=>window.MailRecipients&&window.PonyOffice);
 document.querySelector('.nav [data-view=analysis]').click();
 $('new-analysis').click();await wait(()=>$('conversation-id').value&&!$('new-analysis').disabled);
 $('try-sample').click();await wait(()=>!$('try-sample').disabled&&$('task-data').value.includes('console-mock'));
 const emails=['first@example.invalid','second@example.invalid'];
 const policy=await api('settings');assert(policy.mail.transport==='file','Only file transport is allowed');
 const retained='retained@example.invalid';policy.mail.recipient_allowlist=[retained];policy.mail.allow_synthetic=true;settings=await api('settings','PUT',policy);
 const before=PonyOffice.snapshot().taskId;
 $('task-recipient').value='';$('task-notify').checked=false;
 document.querySelector('[data-pony=mail]').dispatchEvent(new MouseEvent('click',{bubbles:true}));
 $('mail-recipients-enabled').checked=false;$('mail-recipients-enabled').dispatchEvent(new Event('change'));
 $('mail-recipients-dialog').querySelector('[type=submit]').click();assert(!$('mail-recipients-dialog').open,'disabled delivery permits an empty list');
 document.querySelector('[data-pony=mail]').dispatchEvent(new MouseEvent('click',{bubbles:true}));
 const dialog=$('mail-recipients-dialog');assert(dialog.open,'mail pony opens recipient dialog');
 $('mail-recipients-list').querySelector('input').value='invalid';assert(!dialog.querySelector('form').checkValidity(),'invalid address rejected');
 $('mail-recipients-list').querySelector('input').value=emails[0];$('mail-recipients-add').click();
 $('mail-recipients-list').querySelectorAll('input')[1].value=emails[1];$('mail-recipients-add').click();
 $('mail-recipients-list').querySelectorAll('input')[2].value=emails[0];
 dialog.querySelector('[type=submit]').click();assert(dialog.open&&!$('mail-recipients-authorize').hidden,'unknown addresses offer in-dialog authorization');
 assert((await api('settings')).mail.recipient_allowlist.length===1,'ordinary save never silently grants permission');
 const originalApi=api;
 try{
  api=async(path,method,...args)=>{if(path==='settings'&&method==='PUT')throw Error('模拟保存失败');return originalApi(path,method,...args);};
  $('mail-recipients-authorize').click();await wait(()=>$('mail-recipients-error').textContent.includes('模拟保存失败'));
  assert(dialog.open&&$('mail-recipients-list').children.length===3,'failed authorization retains editable addresses');
 }finally{api=originalApi;}
 $('mail-recipients-authorize').click();await wait(()=>!dialog.open);
 const granted=(await api('settings')).mail;
 assert([retained,...emails].every(email=>granted.recipient_allowlist.includes(email)),'explicit grant merges new addresses and retains previous grants');
 assert(emails.every(email=>$('mail-allowlist').value.includes(email)),'settings editor reflects the new grants');
 assert(granted.transport===policy.mail.transport&&granted.allow_synthetic===policy.mail.allow_synthetic,'transport and other mail policy preserved');
 assert(MailRecipients.values().length===2,'duplicate addresses removed');assert(PonyOffice.snapshot().taskId===before,'saving does not submit or send');
 document.querySelector('[data-pony=mail]').dispatchEvent(new MouseEvent('click',{bubbles:true}));
 $('mail-recipients-list').querySelector('button').click();assert($('mail-recipients-list').children.length===1,'remove address');
 $('mail-recipients-cancel').click();assert(MailRecipients.values().length===2,'cancel preserves saved list');
 $('task-complexity').value='simple';$('analysis-send').click();
 await wait(()=>/^[a-f0-9]{32}$/.test(PonyOffice.snapshot().taskId||''));const id=PonyOffice.snapshot().taskId;
 await wait(()=>PonyOffice.snapshot().taskState==='completed');const task=await api('tasks/'+id),mail=task.artifacts[0].parts[0].data.mail;
 assert(mail.status==='simulated'&&mail.deliveries.length===2,'actual backend delivers both to file transport');
 assert(mail.deliveries.every(d=>d.status==='simulated'),'no real email sent');
 window.__mailRecipientsCheck={state:'done',taskId:id,recipients:mail.recipients,status:mail.status,cancel:true,deduplicate:true,invalid:true,explicitGrant:true,grantFailureRetainsInput:true};
})().catch(error=>window.__mailRecipientsCheck={state:'failed',error:error.stack});
