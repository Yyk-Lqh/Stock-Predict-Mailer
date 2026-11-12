/* Derives task progress only from the backend's finalized plan and step events. */
globalThis.PonyTaskProgress = (() => {
  const roles = ['prediction','risk','advice','charts','mail'];
  class Tracker {
    constructor(){this.reset();}
    reset(){this.finalized=false;this.plan=new Map();this.completed=new Set();}
    update(event){
      if(event?.kind==='plan'&&event.finalized===true&&Array.isArray(event.steps)){
        this.plan=new Map();
        for(const step of event.steps)if(typeof step?.id==='string'&&step.id)this.plan.set(step.id,String(step.label||step.id));
        this.finalized=true;
      }else if(event?.kind==='step'&&typeof event.step==='string'){
        if(event.status==='completed')this.completed.add(event.step);
        else if(['running','failed','canceled'].includes(event.status))this.completed.delete(event.step);
      }
      return this.snapshot();
    }
    snapshot(){
      const ids=this.finalized?[...this.plan.keys()]:[];
      const completed=this.finalized?ids.filter(id=>this.completed.has(id)).length:this.completed.size;
      const total=this.finalized?ids.length:null;
      const percent=total?Math.round(completed*100/total):null;
      const byRole={};
      for(const role of roles)if(this.plan.has(role)){
        const done=this.completed.has(role)?1:0;
        byRole[role]={total:1,completed:done,percent:done*100};
      }
      return{finalized:this.finalized,total,completed,percent,byRole};
    }
  }
  return{Tracker};
})();
