/* Validated presentation data. Demo prices never become task or live-market input. */
globalThis.PonyHallData=(()=>{
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite=v=>typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=1e12;
  const units={trading_days:'交易日',calendar_days:'自然日',hours:'小时'};
  const horizon=p=>p&&Number.isFinite(p.value)?`${p.value} ${units[p.unit]||p.unit||''}`:'未提供周期';
  const number=value=>finite(value)?value.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  const demo=()=>({demo:true,source:'内置静态示例',as_of:null,timezone:null,quotes:[
    {symbol:'DEMO.SH',name:'沪市综合 · DEMO',last:3268.42,change_pct:.68},
    {symbol:'DEMO.SZ',name:'深市综合 · DEMO',last:10482.16,change_pct:-.42},
    {symbol:'DEMO.GROW',name:'成长板块 · DEMO',last:2186.75,change_pct:1.26},
    {symbol:'DEMO.WATCH',name:'自选组合 · DEMO',last:1286.30,change_pct:.35}
  ],history:[3228,3235,3231,3247,3240,3255,3248,3251,3241,3259,3254,3261,3258,3270,3264,3268.42].map((value,i)=>({at:new Date(Date.UTC(2026,0,5+i)).toISOString(),value})),candles:[]});
  function normalize(raw){
    if(!raw||typeof raw.source!=='string'||!raw.source.trim()||!Number.isFinite(Date.parse(raw.as_of)))throw Error('行情必须提供来源与有效更新时间');
    if(!Array.isArray(raw.quotes)||raw.quotes.length<1||raw.quotes.length>50)throw Error('行情须包含1至50个标的');
    const quotes=raw.quotes.map(q=>{
      if(!q||typeof q.symbol!=='string'||typeof q.name!=='string'||!finite(q.last)||q.last<0||!finite(q.change_pct))throw Error('行情价格或涨跌幅无效');
      return{symbol:q.symbol.slice(0,40),name:q.name.slice(0,60),last:q.last,change_pct:q.change_pct,...typeof q.industry==='string'?{industry:q.industry.slice(0,60)}:{}};
    });
    if(new Set(quotes.map(q=>q.symbol)).size!==quotes.length)throw Error('行情标的重复');
    const history=(raw.history||[]).map(p=>{if(!finite(p.value)||!Number.isFinite(Date.parse(p.at)))throw Error('历史价格序列无效');return{at:new Date(p.at).toISOString(),value:p.value};}).sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
    const candles=(raw.candles||[]).map(p=>{
      if(!Number.isFinite(Date.parse(p.at))||![p.open,p.high,p.low,p.close].every(finite)||p.low>Math.min(p.open,p.close)||p.high<Math.max(p.open,p.close)||p.low>p.high||p.volume!=null&&(!finite(p.volume)||p.volume<0))throw Error('K线须有有效开高低收数据');
      return{at:new Date(p.at).toISOString(),open:p.open,high:p.high,low:p.low,close:p.close,...p.volume!=null?{volume:p.volume}:{}};
    }).sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
    if(history.length>500||candles.length>500)throw Error('单次图表最多500个点');
    if(raw.timezone){try{new Intl.DateTimeFormat('zh-CN',{timeZone:raw.timezone});}catch{throw Error('行情时区无效');}}
    const session=['live','delayed'].includes(raw.session)?raw.session:null;
    const omitted=Number.isInteger(raw.omitted)&&raw.omitted>0?Math.min(raw.omitted,50):0;
    return{demo:false,source:raw.source.trim().slice(0,100),as_of:new Date(raw.as_of).toISOString(),timezone:raw.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone,quotes,history,candles,...session?{session}:{},...omitted?{omitted}:{}};
  }
  class Feed{
    constructor(){this.market=demo();this.connection='demo';this.resetTask();}
    receive(raw){const snapshot=normalize(raw);this.market=snapshot;this.connection='connected';this.receivedAt=Date.now();return snapshot;}
    disconnect(){if(!this.market.demo)this.connection='disconnected';}
    stale(){if(this.connection==='connected')this.connection='stale';}
    status(now=Date.now()){return this.connection==='connected'&&now-this.receivedAt>90000?'stale':this.connection;}
    resetTask(){this.task=null;this.analysis=null;this.preview={};this.stage='等待分析任务';this.chart=null;this.mail=null;}
    sync(task,events=[]){
      if(this.task?.id!==task.id)this.resetTask();this.task=task;
      const data=task.artifacts?.[0]?.parts?.[0]?.data;
      if(data?.analysis)this.analysis=data.analysis;if(data?.mail)this.mail=data.mail;
      for(const event of events||[]){
        if(event.kind==='step'&&event.status==='running')this.stage=event.label||event.step;
        if(event.preview)this.preview={...this.preview,...event.preview};
        if(event.kind==='chart'&&typeof event.svg==='string'&&event.svg.length<500000)this.chart=event.svg;
        if(event.kind==='mail')this.mail={status:event.status,label:event.label};
      }
      if(['completed','failed','canceled'].includes(task.status.state))this.stage={completed:'分析完成',failed:'分析失败',canceled:'任务已取消'}[task.status.state];
    }
    summary(actors=[]){
      const meta=this.task?.metadata?.request||{},p=this.analysis?.prediction||this.task?.input?.prediction||meta;
      const main=actors.find(a=>a.id==='main'),planned=main&&Number.isInteger(main.totalSteps)&&main.totalSteps>0&&Number.isFinite(main.progressPercent);
      const subject=p.subject||meta.subject||'尚未选择分析标的',quote=this.market.quotes.find(q=>q.symbol===subject);
      return{subject,displaySubject:quote&&(!this.market.demo||p.synthetic)?subject+' · '+quote.name:subject,industry:quote?.industry||p.industry||'行业未提供',prediction:p,horizon:horizon(p.horizon||meta.horizon),stage:this.stage,
        progress:planned?`${main.completedSteps||0}/${main.totalSteps} · ${main.progressPercent}%`:this.task?'阶段信息 · 不估算百分比':'尚未开始',
        pending:actors.filter(a=>['prediction','risk','advice'].includes(a.id)&&a.state==='running').map(a=>a.name),
        risks:this.analysis?.risks||this.preview.risks||[],limitations:this.analysis?.limitations||this.preview.limitations||[],
        inferences:this.analysis?.inferences||this.preview.inferences||[],mail:this.mail,notify:meta.notify===true};
    }
  }
  function seat(actor,summary,mode){
    const p=summary.prediction,elapsed=`${Math.floor(actor.elapsed||0)}s`,progress=Number.isInteger(actor.totalSteps)&&actor.totalSteps>0&&Number.isFinite(actor.progressPercent)?`${actor.completedSteps||0}/${actor.totalSteps} · ${actor.progressPercent}%`:`当前步骤 · ${elapsed}`;
    const states={completed:'已完成',failed:'失败',canceled:'已取消',submitted:'已提交',simulated:'模拟投递',uncertain:'结果待确认',retry:'等待重试',not_requested:'未请求发送'};
    const role={main:['执行计划',summary.pending.length?'等待 '+summary.pending.join('、'):'协调与汇总',progress],
      prediction:['模型预测',`${{up:'↑ 看涨',down:'↓ 看跌',flat:'→ 持平'}[p.direction]||'方向待返回'}${finite(p.value)?' '+number(p.value)+' '+(p.value_unit||''):''}`,summary.horizon,finite(p.confidence)?`模型置信 ${Math.round(p.confidence*100)}%`:'模型未提供置信信息'],
      risk:['风险核对',summary.risks[0]||'风险项待核对',summary.limitations[0]||'缺失与冲突待返回'],
      charts:['图表产出','历史实线 / 预测虚线',progress],
      advice:['分析要点',summary.inferences[0]?.statement||summary.inferences[0]?.text||'分析要点待汇总','适用条件与限制见报告'],
      mail:['报告交付',summary.mail?.label||states[summary.mail?.status]||(summary.notify?'等待报告准备':'本轮未请求发送'),summary.notify?'仍须通过收件授权':'仅生成分析报告']}[actor.id]||['资料接待','点击打开分析资料'];
    const lines=actor.id==='prediction'&&mode!=='disconnected'?role:[role[0],mode==='disconnected'?'连接中断 · 保留进度':states[actor.state]||actor.last||role[1],...role.slice(1)];
    return lines.slice(0,4).map((line,i)=>{const full=String(line),limit=i?14:12,label=full.length>limit?full.slice(0,limit-1)+'…':full;return `<text x="5" y="${10+i*12}" fill="${i?'#d6e5eb':'#8ddbd5'}" font-size="${i?6:7}" font-family="sans-serif">${escape(label)}<title>${escape(full)}</title></text>`;}).join('');
  }
  return{Feed,normalize,demo,escape,number,horizon,seat};
})();
