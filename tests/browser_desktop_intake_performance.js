/* Loaded-list benchmark only; synthetic DOM rows are removed afterwards. Disposable intake fixture only. */
(async()=>{
  if(location.port!=='8788'||innerWidth<=760)throw Error('Use desktop browser_intake_fixture.py on :8788');
  const host=document.getElementById('file-list'),input=document.getElementById('intake-file-search'),previous=[...host.childNodes],result={loaded:4000};
  try{
    const files=Array.from({length:4000},(_,index)=>({upload_id:'benchmark-'+index,filename:'benchmark-file-'+index+'.csv',status:index%2?'ready':'needs_attention'}));
    host.replaceChildren(...files.map(file=>{const node=document.createElement('button');node.className='file-row';node.dataset.uploadId=file.upload_id;node.dataset.fileState=file.status;node.textContent=file.filename;return node;}));
    DesktopIntake.listing(files);
    const times=[];for(let round=0;round<3;round++)for(const query of ['file-9','file-12','benchmark','no-matches','']){input.value=query;const begin=performance.now();input.dispatchEvent(new Event('input',{bubbles:true}));times.push(performance.now()-begin);}
    result.filter_runs=times.length;result.median_ms=times.slice().sort((a,b)=>a-b)[Math.floor(times.length/2)];result.max_ms=Math.max(...times);
    document.body.dataset.desktopIntakePerformance=JSON.stringify(result);
  }catch(error){document.body.dataset.desktopIntakePerformance=JSON.stringify({...result,error:error.stack});}
  finally{input.value='';host.replaceChildren(...previous);await refresh();}
})();
