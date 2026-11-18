/* Actual 8-second browser read deadline, disposable :8768 only. */
(async()=>{
  const $=id=>document.getElementById(id),realFetch=window.fetch;let started=0,aborted=false;
  try{
    if(location.port!=='8768'||innerWidth<=760)throw Error('Use desktop fixture');DesktopPoll.stop();currentTask='poll-timeout';eventCursor=0;
    window.fetch=async(url,options)=>{if(String(url)==='/api/tasks/poll-timeout'){started=performance.now();return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{aborted=true;reject(new DOMException('Aborted','AbortError'));},{once:true}));}return realFetch(url,options);};
    showView('analysis');await poll(currentTask);
    const elapsed=performance.now()-started;if(!aborted||elapsed<7800||!$('desktop-poll-feedback').textContent.includes('超过 8 秒'))throw Error('Deadline or persistent timeout feedback missing');
    document.body.dataset.desktopPollTimeout=JSON.stringify({checks:['actual read aborts at the 8-second deadline and exposes persistent retry'],elapsed_ms:elapsed});
  }catch(error){document.body.dataset.desktopPollTimeout=JSON.stringify({error:error.stack});}
  finally{DesktopPoll.stop();currentTask=null;window.fetch=realFetch;}
})();
