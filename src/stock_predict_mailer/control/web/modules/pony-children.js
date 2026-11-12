/* Tracks only backend-reported child steps; it never starts or calls an agent. */
globalThis.PonyChildren = (() => {
  const labels={prediction:'预测分析',risk:'风险分析',advice:'建议生成'};
  const terminals=new Set(['completed','failed','canceled']);
  class Tracker {
    constructor(){this.reset();}
    reset(){this.pending=new Map();this.outcomes=new Map();}
    snapshot(){return [...this.pending].map(([role,childId])=>({role,childId}));}
    update(role,childId,status){
      if(!Object.hasOwn(labels,role))return null;
      if(status==='running'){this.pending.set(role,childId||null);this.outcomes.delete(role);}
      else if(terminals.has(status)){this.pending.delete(role);this.outcomes.set(role,status);}
      else return null;
      const pending=this.snapshot();
      const failed=[...this.outcomes].filter(([,result])=>result==='failed').map(([childRole])=>labels[childRole]);
      const canceled=[...this.outcomes].filter(([,result])=>result==='canceled').map(([childRole])=>labels[childRole]);
      const result=[failed.length?`${failed.join('、')}失败`:null,canceled.length?`${canceled.join('、')}已取消`:null].filter(Boolean).join('，');
      const message=pending.length
        ? `等待 ${pending.map(child=>labels[child.role]).join('、')} 返回${result?` · ${result}`:''}`
        : failed.length||canceled.length?`${result} · 主 Agent 继续`:'子 Agent 已返回 · 汇总结果';
      return{pending,message};
    }
  }
  return{Tracker,labels};
})();
