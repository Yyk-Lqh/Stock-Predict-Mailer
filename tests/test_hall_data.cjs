const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c=vm.createContext({});vm.runInContext(fs.readFileSync('src/stock_predict_mailer/control/web/modules/hall-data.js','utf8'),c);
const {Feed,normalize,seat}=c.PonyHallData,feed=new Feed();
assert.equal(feed.connection,'demo');assert.equal(feed.market.as_of,null,'static sample never claims a live timestamp');assert.equal(feed.market.candles.length,0,'demo does not invent OHLC');
const live={source:'Authorized fixture feed',as_of:'2026-11-13T02:03:04Z',timezone:'Asia/Shanghai',quotes:[{symbol:'FIXTURE',name:'测试标的',last:10.5,change_pct:-.5}],history:[{at:'2026-11-12',value:10},{at:'2026-11-13',value:10.5}],candles:[{at:'2026-11-13',open:10,high:11,low:9,close:10.5,volume:123}]};
for(const invalid of [{...live,source:''},{...live,as_of:'invalid'},{...live,quotes:[{...live.quotes[0],last:NaN}]},{...live,quotes:[live.quotes[0],live.quotes[0]]},{...live,candles:[{...live.candles[0],high:9}]},{...live,timezone:'not-a-zone'}])assert.throws(()=>normalize(invalid));
feed.receive(live);const snapshot=feed.market;assert.equal(feed.connection,'connected');assert.equal(snapshot.demo,false);assert.equal(snapshot.candles[0].volume,123);
assert.equal(feed.status(feed.receivedAt+91000),'stale','no new snapshot eventually reports inactivity');assert.equal(feed.market,snapshot,'staleness does not discard last data');
feed.disconnect();assert.equal(feed.connection,'disconnected');assert.equal(feed.market,snapshot,'disconnect retains exact last quote snapshot and time');
assert.throws(()=>feed.receive({...live,source:''}));assert.equal(feed.market,snapshot,'invalid update cannot replace last data');
const task={id:'task1',metadata:{request:{subject:'FIXTURE',horizon:{value:5,unit:'trading_days'},direction:'up',value:11,confidence:.7}},status:{state:'working'}};
assert.doesNotThrow(()=>feed.sync(task,null),'initial submitted task can arrive before event batch');
feed.sync(task,[{kind:'step',step:'risk',status:'running',label:'检查缺失数据'},{kind:'analysis',preview:{risks:['缺少成交量'],inferences:[{statement:'仅可作条件性解读'}]}}]);
let summary=feed.summary([{id:'main',state:'running'},{id:'risk',name:'风险分析',state:'running'}]);
assert.equal(summary.subject,'FIXTURE');assert.equal(summary.horizon,'5 交易日');assert.ok(!summary.progress.includes('%'),'no estimated percentage for unknown plan');assert.equal(summary.pending[0],'风险分析');assert.equal(summary.risks[0],'缺少成交量');
summary=feed.summary([{id:'main',totalSteps:4,completedSteps:2,progressPercent:50}]);assert.equal(summary.progress,'2/4 · 50%');
assert.ok(seat({id:'prediction',state:'running'},summary,'task').includes('70%'),'confidence only comes from upstream value');
assert.ok(seat({id:'mail',state:'idle'},summary,'task').includes('本轮未请求发送'),'never implies an email was sent');
feed.sync({...task,status:{state:'completed'}},[{kind:'mail',status:'failed',label:'邮件授权拒绝'}]);assert.equal(feed.summary().mail.label,'邮件授权拒绝');assert.equal(feed.summary().stage,'分析完成');
feed.sync({id:'task2',status:{state:'submitted'}},[]);assert.equal(feed.summary().risks.length,0,'new task clears previous risks and output');assert.equal(feed.chart,null);
for(const desktop of [true,false]){
 const context=vm.createContext({matchMedia:()=>({matches:desktop})});
 for(const name of ['pony-door','pony-model'])vm.runInContext(fs.readFileSync(`src/stock_predict_mailer/control/web/modules/${name}.js`,'utf8'),context);
 const roles=context.PonyFloor.roles,find=id=>roles.find(r=>r.id===id);
 assert.equal(find('main').x,desktop?525:220);assert.equal(find('mail').x,desktop?830:220);assert.equal(find('prediction').x,desktop?220:525);
 assert.equal(context.PonyFloor.hall,desktop);
}
console.log('Hall data passed: labelled demo, validated source/time/OHLC, stale preservation, genuine task state and unchanged mobile layout.');
