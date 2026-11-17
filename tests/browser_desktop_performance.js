/* Repeatable desktop measurements. Run through gstack on the disposable console fixture only. */
(async () => {
  if(!['8768','8769'].includes(location.port)||innerWidth<=760)throw Error('Use a desktop disposable console fixture');
  const $=id=>document.getElementById(id),sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const saved={records,recordFilter,recordQuery,recordCursor,recordLoaded},result={viewport:[innerWidth,innerHeight]};
  const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];
  async function scene(mode){if(mode==='settings')showView('settings');else{showView('analysis');document.querySelector(`[data-desktop-mode="${mode}"]`).click();}await sleep(160);
    let mutations=0;const observer=new MutationObserver(items=>{mutations+=items.length;});observer.observe(document.querySelector('.office-stage'),{attributes:true,childList:true,subtree:true});
    await sleep(1200);observer.disconnect();return mutations;
  }
  try {
    const nav=performance.getEntriesByType('navigation')[0];result.navigation={ttfb_ms:nav.responseStart-nav.requestStart,interactive_ms:nav.domInteractive,load_ms:nav.loadEventEnd};
    result.paint=performance.getEntriesByType('paint').map(({name,startTime})=>({name,ms:startTime}));
    result.assets=performance.getEntriesByType('resource').filter(item=>['script','link'].includes(item.initiatorType)).map(item=>({path:new URL(item.name).pathname,bytes:item.encodedBodySize,duration_ms:item.duration}));
    result.scene_mutations_1200ms={focus:await scene('focus'),hall:await scene('hall'),settings:await scene('settings')};
    recordLoaded=true;recordCursor='benchmark-older';recordFilter='all';recordQuery='';
    records=Array.from({length:1500},(_,index)=>({id:'benchmark-'+index,contextId:'benchmark-'+index,status:{state:index%3?'completed':'working',timestamp:new Date(Date.UTC(2026,10,17)-index*60000).toISOString()},metadata:{request:{subject:'BENCH-'+index,direction:'up',horizon:{value:1,unit:'trading_days'}}}}));
    showView('records');clearTimeout(recordTimer);renderRecords();
    const prior=new Set($('record-list').querySelectorAll('.task-row'));let begin=performance.now();renderRecords();result.unchanged_refresh_ms=performance.now()-begin;
    result.retained_rows=[...$('record-list').querySelectorAll('.task-row')].filter(node=>prior.has(node)).length;
    const times=[];for(let round=0;round<3;round++)for(const query of ['bench-9','bench-12','bench','no-matches','']){recordQuery=query;begin=performance.now();renderRecords();times.push(performance.now()-begin);}
    result.tasks={loaded:1500,filter_runs:times.length,median_ms:median(times),max_ms:Math.max(...times)};
    document.body.dataset.desktopPerformance=JSON.stringify(result);
  }catch(error){document.body.dataset.desktopPerformance=JSON.stringify({...result,error:error.stack});}
  finally{({records,recordFilter,recordQuery,recordCursor,recordLoaded}=saved);$('record-query').value=recordQuery;renderRecords();showView('analysis');document.querySelector('[data-desktop-mode="focus"]').click();}
})();
