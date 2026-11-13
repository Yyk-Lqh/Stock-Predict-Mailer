/* Composer tools use existing model, execution and mail authorization contracts. */
window.ComposerControls = (() => {
  const dock=$('analysis-composer'),toolbar=dock.querySelector('.analysis-composer-controls'),send=$('analysis-send'),message=$('conversation-message');
  const icons={plus:'M12 5v14M5 12h14',shield:'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6ZM9 12l2 2 4-4',mic:'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8',arrow:'M12 19V5m-6 6 6-6 6 6',stop:'M6 6h12v12H6Z',chevron:'m8 10 4 4 4-4'};
  const icon=name=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name]}"/></svg>`;
  const button=(id,label,markup)=>{const b=document.createElement('button');b.id=id;b.type='button';b.className='composer-tool';b.setAttribute('aria-label',label);b.title=label;b.innerHTML=markup;return b;};
  const left=document.createElement('div'),right=document.createElement('div');left.className='composer-tools-left';right.className='composer-tools-right';
  const plus=$('analysis-data-open');plus.className='composer-tool composer-add';plus.onclick=null;
  const permission=button('composer-permission','操作权限',icon('shield')+'<span></span>');
  const model=button('composer-model','选择工作台默认模型','<span></span>'+icon('chevron'));
  const effort=button('composer-effort','调整推理强度','<span></span>');
  const voice=button('composer-voice','语音输入',icon('mic'));
  voice.setAttribute('aria-pressed','false');
  send.innerHTML=icon('arrow');send.className='composer-send';send.setAttribute('aria-label','发送消息');send.title='发送消息 · Enter';
  const cancel=$('task-cancel');cancel.innerHTML=icon('stop');cancel.className='composer-tool';cancel.setAttribute('aria-label','停止任务');cancel.title='停止任务';
  $('analysis-session-label').hidden=true;
  left.append(plus,permission);right.append(model,effort,voice,cancel,send);toolbar.prepend(left);toolbar.append(right);
  let active=null,trigger=null,saving=false,recognition=null,listening=false,flushEffort=null;
  const panel=document.createElement('div');panel.className='composer-popover';panel.hidden=true;panel.id='composer-popover';panel.setAttribute('role','dialog');dock.append(panel);
  const levels=['light','medium','high','extreme','ultra'],labels=['轻度','中','高','极高','Ultra'];
  const effective=()=>$('task-effort').value||settings?.default_reasoning_effort||'high';
  function close(focus=false){flushEffort?.();flushEffort=null;panel.hidden=true;trigger?.setAttribute('aria-expanded','false');if(focus)trigger?.focus();active=null;}
  function row(label,callback,selected=false){const b=document.createElement('button');b.type='button';b.className='composer-menu-row';b.textContent=label;b.onclick=callback;if(selected){b.classList.add('selected');b.setAttribute('aria-current','true');}panel.append(b);return b;}
  function title(text){const h=document.createElement('h3');h.textContent=text;panel.append(h);panel.setAttribute('aria-label',text);}
  function note(text){const p=document.createElement('p');p.className='hint';p.textContent=text;panel.append(p);}
  function show(kind,source){
    if(active===kind){close();return;}
    close();active=kind;trigger=source;panel.replaceChildren();panel.hidden=false;
    panel.classList.toggle('composer-popover-left',kind==='add'||kind==='permission');
    source.setAttribute('aria-expanded','true');
    if(kind==='add'){
      title('添加分析资料');
      row('填写预测与客观事实',()=>{close();AnalysisInput.open('input');});
      row('导入预测 JSON',()=>{close();AnalysisInput.open('input');$('prediction-import').click();});
    }else if(kind==='permission'){
      title('操作权限');
      row('仅分析与生成报告',()=>{$('task-notify').checked=false;changed($('task-notify'));showPermission();},!$('task-notify').checked);
      row('完成后发送授权邮件',()=>{$('task-notify').checked=true;changed($('task-notify'));showPermission();},$('task-notify').checked);
      const label=document.createElement('label');label.className='field';label.textContent='收件地址';
      const input=document.createElement('input');input.type='email';input.value=$('task-recipient').value;input.placeholder='授权清单内的邮箱';input.setAttribute('aria-label','授权收件地址');
      input.oninput=()=>{$('task-recipient').value=input.value;changed($('task-recipient'));};label.append(input);panel.append(label);
      note('邮件仅向设置中的授权地址投递，未授权地址不会发送。');
    }else if(kind==='models'){
      title('选择模型');note('更改工作台默认模型，用于后续分析。');
      for(const p of profiles.filter(p=>p.enabled))row(p.name,()=>pickModel(p.id),p.id===settings?.default_model_id);
      if(!profiles.some(p=>p.enabled))note('尚无已启用模型，请先配置模型。');
      row('管理模型…',()=>{close();showView('settings');showPanel('models');});
    }else{
      title('推理强度');
      const value=document.createElement('output');value.className='composer-effort-value';panel.append(value);
      const slider=document.createElement('input');slider.type='range';slider.min='0';slider.max='4';slider.step='.001';slider.value=String(Math.max(0,levels.indexOf(effective())));slider.setAttribute('aria-label','推理强度');
      let frame=0,dirty=false;
      const index=()=>Math.round(Number(slider.value));
      const paint=()=>{frame=0;value.textContent=labels[index()];slider.setAttribute('aria-valuetext',value.textContent);slider.style.setProperty('--effort-fill',Number(slider.value)*25+'%');};
      const commit=()=>{
        if(!dirty)return;dirty=false;
        if(frame){cancelAnimationFrame(frame);frame=0;}
        slider.value=String(index());paint();
        const field=$('task-effort'),next=levels[index()];
        if(field.value!==next){field.value=next;changed(field);}
      };
      // Native thumb movement remains continuous. Avoid form events, draft
      // serialization and textarea layout while the pointer is moving.
      slider.oninput=()=>{dirty=true;if(!frame)frame=requestAnimationFrame(paint);};
      slider.onchange=commit;flushEffort=commit;
      slider.onkeydown=event=>{
        const direction={ArrowLeft:-1,ArrowDown:-1,PageDown:-1,ArrowRight:1,ArrowUp:1,PageUp:1}[event.key];
        if(!direction&&!['Home','End'].includes(event.key))return;
        event.preventDefault();slider.value=String(event.key==='Home'?0:event.key==='End'?4:Math.max(0,Math.min(4,index()+direction)));
        dirty=true;commit();
      };
      paint();panel.append(slider);
      const ticks=document.createElement('div');ticks.className='composer-effort-ticks';for(const text of labels){const span=document.createElement('span');span.textContent=text;ticks.append(span);}panel.append(ticks);
      row('恢复默认档位',()=>{dirty=false;if(frame)cancelAnimationFrame(frame);flushEffort=null;$('task-effort').value='';changed($('task-effort'));close();});
      note('强度影响分析步骤、调用预算与超时；模型原生推理由已配置映射决定。');
    }
    panel.querySelector('button, input')?.focus();
  }
  function showPermission(){active=null;show('permission',permission);}
  function changed(field){field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));update();}
  async function pickModel(id){
    if(saving)return;saving=true;const wasDisabled=send.disabled;send.disabled=true;
    panel.querySelectorAll('button').forEach(b=>{b.disabled=true;});
    try{const latest=await api('settings');await api('settings','PUT',{...latest,default_model_id:id});await refresh();close();}
    catch(error){notice(error.message,true);panel.querySelectorAll('button').forEach(b=>{b.disabled=false;});}
    finally{saving=false;send.disabled=wasDisabled;update();}
  }
  for(const [node,kind]of [[plus,'add'],[permission,'permission'],[model,'models'],[effort,'effort']]){
    node.setAttribute('aria-haspopup','dialog');node.setAttribute('aria-controls',panel.id);node.setAttribute('aria-expanded','false');node.onclick=()=>show(kind,node);
  }
  document.addEventListener('pointerdown',event=>{if(active&&!panel.contains(event.target)&&!trigger?.contains(event.target))close();});
  dock.addEventListener('keydown',event=>{if(event.key==='Escape'&&active){event.preventDefault();close(true);}});
  const Speech=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Speech){voice.disabled=true;voice.title='当前浏览器不支持语音输入';voice.setAttribute('aria-label',voice.title);}
  else voice.onclick=()=>{
    if(listening){recognition?.stop();return;}
    const base=message.value;recognition=new Speech();recognition.lang='zh-CN';recognition.interimResults=true;
    recognition.onstart=()=>{listening=true;voice.classList.add('listening');voice.setAttribute('aria-pressed','true');voice.title='停止语音输入';};
    recognition.onresult=event=>{message.value=base+Array.from(event.results,result=>result[0].transcript).join('');message.dispatchEvent(new Event('input',{bubbles:true}));};
    recognition.onerror=event=>notice(event.error==='not-allowed'?'请允许麦克风权限后重试。':'语音输入未完成，请重试或直接输入文字。',true);
    recognition.onend=()=>{listening=false;voice.classList.remove('listening');voice.setAttribute('aria-pressed','false');voice.title='语音输入';};
    try{recognition.start();}catch(error){notice('无法启动语音输入，请检查麦克风权限。',true);}
  };
  $('task-form').addEventListener('submit',()=>recognition?.stop(),true);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)recognition?.stop();});
  function update(){
    plus.innerHTML=icon('plus');plus.setAttribute('aria-label','添加分析资料');plus.title=$('analysis-data-status').textContent;
    permission.querySelector('span').textContent=$('task-notify').checked?'授权邮件':'仅分析';
    const selected=profiles.find(p=>p.id===settings?.default_model_id);
    model.querySelector('span').textContent=selected?.name||'选择模型';model.title=selected?`默认模型：${selected.name}`:'选择或配置分析模型';
    effort.querySelector('span').textContent=labels[levels.indexOf(effective())]||'默认';
    effort.title=`推理强度：${effort.textContent.trim()}`;
  }
  new MutationObserver(()=>{if(!document.body.classList.contains('analysis-composer-visible'))close();}).observe(document.body,{attributes:true,attributeFilter:['class']});
  update();return {update,close};
})();
