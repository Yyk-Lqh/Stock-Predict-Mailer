const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({});
vm.runInContext(fs.readFileSync('src/stock_predict_mailer/control/web/modules/pony-progress.js','utf8'),context);
const tracker=new context.PonyTaskProgress.Tracker();
const progress=()=>JSON.parse(JSON.stringify(tracker.snapshot()));

tracker.update({kind:'plan',steps:[{id:'validate',label:'校验数据'}],finalized:false});
tracker.update({kind:'step',step:'validate',status:'completed',label:'数据已校验'});
assert.equal(progress().percent,null,'a provisional plan does not produce a percentage');
assert.equal(progress().completed,1,'completed events are retained until the final plan arrives');

tracker.update({kind:'plan',steps:[
  {id:'validate',label:'校验数据'},
  {id:'main',label:'主分析'},
  {id:'risk',label:'风险分析'},
  {id:'merge',label:'汇总子 Agent'}
],finalized:true});
assert.deepEqual([progress().total,progress().completed,progress().percent],[4,1,25]);
assert.deepEqual(progress().byRole.risk,{total:1,completed:0,percent:0});

tracker.update({kind:'step',step:'risk',status:'completed'});
tracker.update({kind:'step',step:'risk',status:'completed'});
assert.deepEqual([progress().completed,progress().percent],[2,50],'duplicate completion events count only once');
assert.deepEqual(progress().byRole.risk,{total:1,completed:1,percent:100});

tracker.update({kind:'step',step:'merge',status:'running'});
tracker.update({kind:'step',step:'merge',status:'failed'});
assert.deepEqual([progress().completed,progress().percent],[2,50],'failed steps do not count as completed');

tracker.reset();
assert.deepEqual([progress().total,progress().completed,progress().percent],[null,0,null],'reset clears prior task progress');
tracker.update({kind:'step',step:'main',status:'completed'});
assert.equal(progress().percent,null,'step events without an authoritative final plan never invent a total');
console.log('Pony task progress passed: finalized plans, unique completion, role progress, failure and reset.');
