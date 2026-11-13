/* Desktop trading hall. Market transport may call receive(); no automatic feed. */
globalThis.PonyHall=(()=>{
  function mount(office,choose){
    const data=new PonyHallData.Feed(),wall=document.createElement('section'),prices=new Map();
    wall.className='market-wall';wall.setAttribute('aria-label','证券行情与当前分析任务');
    wall.innerHTML=`<div class="market-wall-head"><div><strong>小马证券分析大厅</strong><span class="market-mode">演示行情</span><small class="market-provenance"></small></div><div class="market-wall-actions"><button type="button" class="market-palette">红涨绿跌</button><button type="button" class="market-ticker-toggle" aria-pressed="false">暂停信息带</button></div></div><div class="market-quotes"></div><div class="market-wall-body"><div class="market-chart"><div class="market-chart-head"><label>走势 <select aria-label="大盘墙走势图"><option value="overview">市场概览 · 演示</option><option value="subject">当前分析标的</option></select></label><span class="market-chart-note"></span></div><div class="market-chart-image"></div></div><button type="button" class="market-task" aria-label="查看当前任务详情"><span class="market-task-label">当前分析</span><strong class="market-subject"></strong><span class="market-context"></span><span class="market-stage"></span><span class="market-progress"></span></button></div><div class="market-ticker" tabindex="0" aria-label="自选标的信息带，悬停或聚焦可暂停"><div class="market-ticker-track"></div></div>`;
    office.prepend(wall);
    const find=s=>wall.querySelector(s);let actors=[],last=0,paused=false,palette='cn',marketDirty=true,taskConnected=true,lastChart='',pendingInput=null;
    try{palette=localStorage.getItem('stock_predict_mailer.market.palette')||'cn';}catch{}
    const paintPalette=()=>{office.dataset.marketPalette=palette;find('.market-palette').textContent=palette==='cn'?'红涨绿跌':'绿涨红跌';};paintPalette();
    find('.market-palette').onclick=()=>{palette=palette==='cn'?'international':'cn';paintPalette();try{localStorage.setItem('stock_predict_mailer.market.palette',palette);}catch{}};
    find('.market-ticker-toggle').onclick=()=>{paused=!paused;wall.classList.toggle('ticker-paused',paused);find('.market-ticker-toggle').setAttribute('aria-pressed',String(paused));find('.market-ticker-toggle').textContent=paused?'继续信息带':'暂停信息带';};
    find('.market-task').onclick=()=>choose('main');
    find('select').onchange=()=>{lastChart='';renderChart();};
    const signed=value=>`${value>0?'↑ +':value<0?'↓ ': '→ '}${value.toFixed(2)}%`;
    const trend=value=>value>0?'market-up':value<0?'market-down':'market-flat';
    function renderMarket(){
      const snapshot=data.market,status=data.status();
      const mode=snapshot.demo?'演示行情':status==='connected'?(snapshot.session==='live'?'实时行情':'最近快照'):status==='stale'?'行情暂未更新':'行情连接中断';
      find('.market-mode').textContent=mode;
      wall.dataset.marketState=status;
      const stamp=snapshot.as_of?new Date(snapshot.as_of).toLocaleString('zh-CN',{hour12:false,timeZone:snapshot.timezone}):'静态示例 · 未连接行情服务';
      find('.market-provenance').textContent=`${snapshot.source} · ${stamp}${snapshot.timezone?' · '+snapshot.timezone:''}${snapshot.omitted?' · '+snapshot.omitted+' 个标的未返回':''}`;
      const quotes=find('.market-quotes');quotes.replaceChildren();
      for(const q of snapshot.quotes.slice(0,5)){
        const card=document.createElement('div');card.className='market-quote '+trend(q.change_pct);
        const name=document.createElement('span');name.textContent=q.name;const value=document.createElement('strong');value.textContent=PonyHallData.number(q.last);
        if(prices.has(q.symbol)&&prices.get(q.symbol)!==q.last)value.className='market-value-changed';prices.set(q.symbol,q.last);
        const change=document.createElement('small');change.textContent=signed(q.change_pct);card.append(name,value,change);quotes.append(card);
      }
      const track=find('.market-ticker-track');track.replaceChildren();
      for(let copy=0;copy<2;copy++){
        const group=document.createElement('div');group.className='market-ticker-group';if(copy)group.setAttribute('aria-hidden','true');
        for(const q of snapshot.quotes){const span=document.createElement('span');span.className=trend(q.change_pct);span.textContent=`${q.name}  ${PonyHallData.number(q.last)}  ${signed(q.change_pct)}`;group.append(span);}track.append(group);
      }
      marketDirty=false;lastChart='';renderChart();
    }
    function renderChart(){
      const summary=data.summary(actors),subject=find('select').value==='subject',target=find('.market-chart-image');
      const key=[subject,data.market.as_of,data.connection,data.task?.id,data.chart,summary.subject].join('|');if(key===lastChart)return;lastChart=key;target.replaceChildren();
      find('select option[value=overview]').textContent=data.market.demo?'市场概览 · 演示':'市场概览';
      if(subject&&data.chart){const image=new Image();image.alt=summary.subject+' · 任务图表';image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(data.chart);target.append(image);find('.market-chart-note').textContent='任务图表 · 历史与预测按产出标注';return;}
      let observed=subject?data.task?.input?.chart_data?.series?.observed?.points:data.market.history;
      const forecast=subject?data.task?.input?.chart_data?.series?.forecast?.points:[];
      /* A 76px strip cannot resolve dozens of bars, so a dense series is drawn as its close line. */
      const candles=!subject&&data.market.candles.length<=20?data.market.candles:[];
      observed=(observed||[]).filter(p=>Number.isFinite(p.value)&&Number.isFinite(Date.parse(p.at)));
      const predicted=(forecast||[]).filter(p=>Number.isFinite(p.value)&&Number.isFinite(Date.parse(p.at)));
      const all=[...observed,...predicted,...predicted.flatMap(p=>[p.lower,p.upper].filter(Number.isFinite).map(value=>({at:p.at,value}))),...candles.flatMap(p=>[{at:p.at,value:p.low},{at:p.at,value:p.high}])];
      if(all.length<2){const empty=document.createElement('span');empty.className='market-chart-empty';empty.textContent=subject?'当前标的暂无历史序列，等待上游图表；不使用演示曲线替代。':'未提供价格序列';target.append(empty);find('.market-chart-note').textContent=subject?summary.subject:'等待行情序列';return;}
      const low=Math.min(...all.map(p=>p.value)),high=Math.max(...all.map(p=>p.value)),first=Math.min(...all.map(p=>Date.parse(p.at))),lastTime=Math.max(...all.map(p=>Date.parse(p.at)));
      const x=p=>16+(Date.parse(p.at)-first)/(lastTime-first||1)*658,y=v=>62-(v-low)/(high-low||1)*48;
      const line=points=>points.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(2)} ${y(p.value).toFixed(2)}`).join('');
      let paths='<path d="M16 14H674M16 38H674M16 62H674" stroke="#28424f" fill="none"/>';
      if(candles.length){const maxVolume=Math.max(1,...candles.map(p=>p.volume||0));for(const p of candles){const color=p.close>=p.open?'var(--market-up)':'var(--market-down)',xx=x(p);paths+=`<path d="M${xx} ${y(p.high)}V${y(p.low)}" stroke="${color}"/><rect x="${xx-2}" y="${Math.min(y(p.open),y(p.close))}" width="4" height="${Math.max(1,Math.abs(y(p.open)-y(p.close)))}" fill="${color}"/>`;if(p.volume!=null)paths+=`<rect x="${xx-2}" y="${75-p.volume/maxVolume*9}" width="4" height="${p.volume/maxVolume*9}" fill="${color}" opacity=".45"/>`;}}
      else paths+=`<path d="${line(observed)}" fill="none" stroke="#9adbe8" stroke-width="1.8"/>`;
      if(predicted.length){const interval=predicted.filter(p=>Number.isFinite(p.lower)&&Number.isFinite(p.upper));if(interval.length>1)paths+=`<path d="${line(interval.map(p=>({...p,value:p.upper})))} ${line(interval.slice().reverse().map(p=>({...p,value:p.lower}))).replace(/^M/,'L')}Z" fill="#bda26d" opacity=".15"/>`;paths+=`<path d="${line(predicted)}" fill="none" stroke="#e3bd79" stroke-dasharray="5 4" stroke-width="1.8"/>`;}
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 690 76');svg.setAttribute('role','img');svg.setAttribute('aria-label',subject?'上游历史实线与预测虚线':data.market.demo?'演示走势，非真实行情':'来源提供的历史行情');svg.innerHTML=paths;target.append(svg);
      find('.market-chart-note').textContent=subject?'历史实线 · 预测虚线 · 区间仅取上游数据':data.market.demo?'演示走势 · 非实时行情':candles.length?`K线 · ${data.market.source} 日线`:`历史收盘 · ${data.market.source}`;
    }
    function tick(now,force=false){
      if(!force&&now-last<1000)return;last=now;
      if(marketDirty||wall.dataset.marketState!==data.status())renderMarket();
      const summary=data.summary(actors);find('.market-subject').textContent=summary.displaySubject;
      find('.market-context').textContent=`${summary.horizon} · ${summary.industry}`;
      find('.market-stage').textContent=taskConnected?summary.stage:'任务连接中断 · 保留最后进度';
      find('.market-progress').textContent=summary.pending.length?'待返回：'+summary.pending.join(' / '):summary.progress;
      renderChart();
    }
    function receive(raw){data.receive(raw);marketDirty=true;tick(performance.now(),true);}
    function disconnect(){data.disconnect();marketDirty=true;tick(performance.now(),true);}
    window.addEventListener('pony-market-snapshot',event=>{try{receive(event.detail);}catch(error){wall.dataset.marketError=error.message;}});
    window.addEventListener('pony-market-disconnected',disconnect);window.addEventListener('offline',disconnect);
    document.addEventListener('visibilitychange',()=>{wall.classList.toggle('ticker-hidden',document.hidden);if(!document.hidden)tick(performance.now(),true);});
    tick(performance.now(),true);
    const relay=globalThis.PonyMarketFeed;
    if(relay)relay.attach({snapshot:value=>{try{receive(value);}catch(error){wall.dataset.marketError=error.message;}},
      stale:()=>{data.stale();marketDirty=true;tick(performance.now(),true);},down:disconnect});
    return{wall,data,receive,disconnect,tick,capture:input=>{pendingInput=structuredClone(input);},reset:()=>{data.resetTask();lastChart='';tick(performance.now(),true);},
      sync(task,events,allActors){actors=allActors;taskConnected=true;const input=data.task?.id===task.id?data.task.input:pendingInput;
        const subject=task.metadata?.request?.subject;if(input?.prediction?.subject===subject){task={...task,input};pendingInput=null;}data.sync(task,events);tick(performance.now(),true);},
      disconnected(){taskConnected=false;tick(performance.now(),true);},
      screen(actor,mode){return PonyHallData.seat(actor,data.summary(actors),mode);},
      aux(actor){const states={running:'执行中',completed:'完成',failed:'失败',idle:'待命',pending:'等待',canceled:'取消'};return `${actor.name.slice(0,4)} · ${states[actor.state]||actor.state}`;}};
  }
  return{mount};
})();
