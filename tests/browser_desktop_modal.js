/* Native Escape must be driven with gstack press Escape at each ready marker. Disposable :8768. */
(async()=>{
  const $=id=>document.getElementById(id),checks=[],realFetch=window.fetch;let releaseGrant;
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const wait=async(fn,label)=>{for(let i=0;i<120;i++){if(fn())return;await new Promise(resolve=>setTimeout(resolve,80));}throw Error('Timeout: '+label);};
  const stage=name=>new Promise(resolve=>{window.__desktopModalContinue=resolve;document.body.dataset[name]='true';});
  try{
    assert(innerWidth>760&&location.port==='8768','Use desktop fixture');showView('analysis');AnalysisInput.open('input');MailRecipients.open();await stage('nativeEscapeReady');
    assert(!$('mail-recipients-dialog').open&&!$('report-inspector').hidden,'Native dialog Escape also closed inspector or did not close dialog');
    checks.push('Native Escape closes only mail dialog and preserves the underlying inspector');
    MailRecipients.open();const email='desktop-modal-fixture@example.invalid';$('mail-recipients-enabled').checked=true;$('mail-recipients-list').querySelector('input').value=email;$('mail-recipients-dialog').querySelector('form').requestSubmit();
    const authorize=$('mail-recipients-authorize');await wait(()=>!authorize.hidden,'explicit authorize');let held=false;
    window.fetch=async(url,options)=>{if(String(url)==='/api/settings'&&options?.method==='PUT'){held=true;await new Promise(resolve=>{releaseGrant=resolve;});return new Response(JSON.stringify({error:{code:'fixture',message:'合成授权失败'}}),{status:503,headers:{'Content-Type':'application/json'}});}return realFetch(url,options);};authorize.click();await wait(()=>held,'held grant');await stage('grantEscapeReady');
    assert($('mail-recipients-dialog').open&&!$('report-inspector').hidden,'Escape bypassed pending grant cancellation guard');releaseGrant();await wait(()=>$('mail-recipients-error').textContent.includes('授权未完成'),'grant failure');window.fetch=realFetch;
    assert($('mail-recipients-list').querySelector('input').value===email&&!authorize.disabled,'Grant failure lost input or stayed disabled');
    await stage('failedGrantEscapeReady');assert(!$('mail-recipients-dialog').open&&!$('report-inspector').hidden,'Escape after failure affected background');
    assert(!(await api('settings')).mail.recipient_allowlist.includes(email),'Failed grant changed backend authorization');
    checks.push('Pending grant blocks native Escape, failed grant retains input, and later Escape closes only dialog without authorizing mail');
    document.body.dataset.desktopModalTest=JSON.stringify({checks});
  }catch(error){document.body.dataset.desktopModalTest=JSON.stringify({checks,error:error.stack});}
  finally{window.fetch=realFetch;releaseGrant?.();$('mail-recipients-dialog').close();}
})();
