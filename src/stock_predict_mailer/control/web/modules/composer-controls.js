/* Composer tools use existing model, execution and mail authorization contracts. */
window.ComposerControls = (() => {
  const dock=$('analysis-composer'),toolbar=dock.querySelector('.analysis-composer-controls'),send=$('analysis-send'),message=$('conversation-message');
  const icons={plus:'M12 5v14M5 12h14',shield:'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6ZM9 12l2 2 4-4',mic:'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8',arrow:'M12 19V5m-6 6 6-6 6 6',stop:'M6 6h12v12H6Z',next:'m10 6 6 6-6 6',files:'M6 3h8l4 4v14H6zM14 3v5h4M9 13h6m-6 4h6',mode:'M4 7h6m4 0h6M4 17h10m4 0h2M10 4v6m4 4v6',expert:'M16 8a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 20a8 6 0 0 1 16 0',skills:'M12 3v18M3 12h18M6 6l12 12M6 18 18 6',connectors:'m10 13 4-4m-7 1-3 3a4 4 0 0 0 6 6l3-3m-2-8 3-3a4 4 0 0 1 6 6l-3 3'};
  const icon=name=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name]}"/></svg>`;
  icons.bolt='M13 2 5 13h6l-1 9 9-12h-6z';
  icons.reset='M4 10a8 8 0 1 1 2 8M4 5v5h5';
  const button=(id,label,markup)=>{const b=document.createElement('button');b.id=id;b.type='button';b.className='composer-tool';b.setAttribute('aria-label',label);b.title=label;b.innerHTML=markup;return b;};
  const left=document.createElement('div'),right=document.createElement('div');left.className='composer-tools-left';right.className='composer-tools-right';
  const plus=$('analysis-data-open');plus.className='composer-tool composer-add';plus.onclick=null;
  const permission=button('composer-permission','操作权限',icon('shield')+'<span></span>');
  const effort=button('composer-effort','选择模型与推理强度','<span class="composer-model-name"></span><span class="composer-effort-label"></span>');
  const modelName=effort.querySelector('.composer-model-name'), effortLabel=effort.querySelector('.composer-effort-label');
  const options=document.createElement('div');options.className='composer-analysis-options';options.append(effort);
  const effortTip=text(options,'span','选择推理强度','composer-effort-tip');
  effortTip.id='composer-effort-tip';effortTip.setAttribute('role','tooltip');
  text(effortTip,'kbd','Ctrl+Shift+M');
  effort.removeAttribute('title');effort.setAttribute('aria-describedby',effortTip.id);
  effort.setAttribute('aria-keyshortcuts','Control+Shift+M');
  const voice=button('composer-voice','语音输入',icon('mic'));
  voice.setAttribute('aria-pressed','false');
  send.innerHTML=icon('arrow');send.className='composer-send';send.setAttribute('aria-label','发送消息');send.title='发送消息 · Enter';
  const cancel=$('task-cancel');cancel.innerHTML=icon('stop');cancel.className='composer-tool';cancel.setAttribute('aria-label','停止任务');cancel.title='停止任务';
  $('analysis-session-label').hidden=true;
  left.append(plus,permission);right.append(options,voice,cancel,send);toolbar.prepend(left);toolbar.append(right);
  let active=null,trigger=null,saving=false,recognition=null,listening=false,flushEffort=null;
  const panel=document.createElement('div');panel.className='composer-popover';panel.hidden=true;panel.id='composer-popover';panel.setAttribute('role','dialog');dock.append(panel);
  const desktop=matchMedia('(min-width: 761px)');
  const useCategories=()=>desktop.matches&&!dock.classList.contains('desktop-canvas-composer');
  const levels=['light','medium','high','extreme','ultra'],labels=['轻度','中','高','极高','Ultra'];
  const effective=()=>$('task-effort').value||settings?.default_reasoning_effort||'high';
  function close(focus=false){flushEffort?.();flushEffort=null;panel.hidden=true;trigger?.setAttribute('aria-expanded','false');if(focus)trigger?.focus();active=null;}
  function row(label,callback,selected=false,host=panel){const b=document.createElement('button');b.type='button';b.className='composer-menu-row';b.textContent=label;b.onclick=callback;if(selected){b.classList.add('selected');b.setAttribute('aria-current','true');}host.append(b);return b;}
  function title(text){const h=document.createElement('h3');h.textContent=text;panel.append(h);panel.setAttribute('aria-label',text);}
  function note(text){const p=document.createElement('p');p.className='hint';p.textContent=text;panel.append(p);}
  function files(host) {
    row('填写预测与客观事实',()=>{close();AnalysisInput.open('input');},false,host);
    row('导入预测 JSON',()=>{close();AnalysisInput.open('input');$('prediction-import').click();},false,host);
  }
  function settingsPage(tab) {
    close();
    showView('settings');
    showPanel(tab);
  }
  function modelChoices(host,actions=host) {
    const enabled=profiles.filter(profile=>profile.enabled);
    for (const profile of enabled) row(profile.name,()=>pickModel(profile.id),profile.id===settings?.default_model_id,host);
    if (!enabled.length) text(host,'p','尚无已启用模型。','hint');
    row('管理模型…',()=>settingsPage('models'),false,actions);
  }
  function fieldChoices(host,id) {
    const field=$(id);
    for (const option of field.options) {
      row(option.textContent,()=>{field.value=option.value;changed(field);close(true);},option.selected,host);
    }
  }
  function connectors(host) {
    const search=document.createElement('input');
    search.type='search';search.placeholder='搜索连接器';search.setAttribute('aria-label',search.placeholder);
    const list=document.createElement('div');list.className='composer-connector-list';
    const entries=[
      ['知识库',$('knowledge-scope').value==='private'?'旧版私有资料':'本机资料',()=>{
        close();AnalysisInput.open('input');
        const query=$('task-knowledge-query');query.closest('details').open=true;query.focus();
      }],
      ['邮件投递',$('task-notify').checked?'本轮启用':'本轮关闭',()=>{
        close();
        if(window.MailRecipients)window.MailRecipients.open();
        else show('permission',permission);
      }],
      ...servers.map(server=>[server.name,server.enabled?'已启用':'已停用',()=>{settingsPage('mcp');editServer(server);}]),
    ];
    function filter() {
      const query=search.value.trim().toLocaleLowerCase();
      list.replaceChildren();
      for (const [name,status,open] of entries) {
        if (!name.toLocaleLowerCase().includes(query)) continue;
        text(row(name,open,false,list),'small',status);
      }
      if (!list.childElementCount) text(list,'p','没有找到匹配的连接器。','hint');
    }
    search.oninput=filter;host.append(search,list);filter();
    row('管理外部工具…',()=>settingsPage('mcp'),false,host);
  }
  function categories() {
    panel.setAttribute('aria-label','对话工具');
    const nav=document.createElement('div');nav.className='composer-categories';nav.setAttribute('role','group');nav.setAttribute('aria-label','工具分类');
    const detail=document.createElement('section');detail.className='composer-category-detail';detail.id='composer-category-detail';
    const groups=[
      ['files','添加资料',host=>{
        files(host);
        row('上传知识资料',()=>{
          close();showView('knowledge');document.querySelector('[data-kb-tab="documents"]').click();
          $('knowledge-file').closest('details').open=true;
        },false,host);
      }],
      ['mode','分析模式',host=>fieldChoices(host,'task-complexity')],
      ['expert','模型与专家',host=>{
        modelChoices(host);
        row('专家协作设置',()=>settingsPage('settings'),false,host);
      }],
      ['skills','分析技能',host=>{
        fieldChoices(host,'task-goal');
        const plugins=$('hall-plugins-open');
        if(plugins)row('打开插件面板',()=>{close();plugins.click();},false,host);
      }],
      ['connectors','连接器',connectors],
    ];
    const buttons=[];
    function select(index) {
      const [,label,render]=groups[index];
      buttons.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));
      detail.setAttribute('aria-label',label);detail.replaceChildren();
      text(detail,'h3',label);render(detail);
    }
    groups.forEach(([glyph,label],index)=>{
      const category=button('composer-category-'+glyph,label,icon(glyph)+'<span></span>'+icon('next'));
      category.className='composer-category';category.querySelector('span').textContent=label;
      category.setAttribute('aria-controls',detail.id);
      category.onclick=()=>select(index);
      category.onkeydown=event=>{
        if(event.key==='ArrowRight'){event.preventDefault();select(index);detail.querySelector('button, input')?.focus();}
        if(event.key==='ArrowUp'||event.key==='ArrowDown'){
          event.preventDefault();buttons[(index+(event.key==='ArrowDown'?1:buttons.length-1))%buttons.length].focus();
        }
      };
      nav.append(category);buttons.push(category);
    });
    detail.onkeydown=event=>{
      if(event.key!=='ArrowLeft'||event.target.tagName!=='BUTTON')return;
      event.preventDefault();nav.querySelector('[aria-pressed="true"]').focus();
    };
    panel.append(nav,detail);select(0);
  }
  function positionOptions() {
    if(active!=='effort'&&active!=='models')return;
    const anchor=effort.getBoundingClientRect(), composer=dock.getBoundingClientRect();
    const right=Math.min(Math.max(anchor.right,panel.offsetWidth+8),document.documentElement.clientWidth-8);
    panel.style.setProperty('--options-right',`${composer.right-right}px`);
    panel.style.setProperty('--options-bottom',`${composer.bottom-anchor.top+5}px`);
    panel.style.setProperty('--options-room',`${Math.max(0,anchor.top-13)}px`);
  }
  function showEffort() {
    panel.setAttribute('aria-label','选择推理强度');
    const header=document.createElement('div');header.className='composer-effort-head';header.innerHTML=icon('bolt');
    const value=text(header,'output','','composer-effort-value');
    const reset=button('composer-effort-reset','恢复默认档位',icon('reset'));
    header.append(reset);
    const modelChoice=button('composer-effort-model','选择工作台默认模型','<span></span>'+icon('next'));
    modelChoice.querySelector('span').textContent=modelName.textContent;
    modelChoice.onclick=openModels;
    const slider=document.createElement('input');
    slider.type='range';slider.min='0';slider.max='4';slider.step='.001';slider.value=String(Math.max(0,levels.indexOf(effective())));
    slider.setAttribute('aria-label','推理强度');
    let frame=0,dirty=false;
    const index=()=>Math.round(Number(slider.value));
    const paint=()=>{frame=0;value.textContent=labels[index()];slider.setAttribute('aria-valuetext',value.textContent);slider.style.setProperty('--effort-fill',Number(slider.value)*25+'%');};
    const commit=()=>{
      if(!dirty)return;dirty=false;
      if(frame)cancelAnimationFrame(frame);
      slider.value=String(index());paint();
      const field=$('task-effort'),next=levels[index()];
      if(field.value!==next){field.value=next;changed(field);}
    };
    // Drag previews the continuous position. Release commits one semantic level.
    slider.oninput=()=>{dirty=true;if(!frame)frame=requestAnimationFrame(paint);};
    slider.onchange=commit;flushEffort=commit;
    slider.onkeydown=event=>{
      const direction={ArrowLeft:-1,ArrowDown:-1,PageDown:-1,ArrowRight:1,ArrowUp:1,PageUp:1}[event.key];
      if(!direction&&!['Home','End'].includes(event.key))return;
      event.preventDefault();slider.value=String(event.key==='Home'?0:event.key==='End'?4:Math.max(0,Math.min(4,index()+direction)));
      dirty=true;commit();
    };
    reset.onclick=()=>{
      dirty=false;if(frame)cancelAnimationFrame(frame);
      const field=$('task-effort');
      if(field.value){field.value='';changed(field);}
      slider.value=String(Math.max(0,levels.indexOf(effective())));paint();slider.focus();
    };
    const scale=document.createElement('div');scale.className='composer-effort-scale';
    const ticks=document.createElement('div');ticks.className='composer-effort-ticks';ticks.setAttribute('aria-hidden','true');
    ticks.append(...levels.map(()=>document.createElement('i')));
    scale.append(slider,ticks);panel.append(header,modelChoice,scale);
    paint();positionOptions();slider.focus();
  }
  function show(kind,source){
    if(active===kind){close();return;}
    close();active=kind;trigger=source;panel.replaceChildren();panel.hidden=false;
    panel.classList.toggle('composer-popover-left',kind==='add'||kind==='permission');
    const cascade=kind==='add'&&useCategories();
    panel.classList.toggle('composer-cascade',cascade);
    panel.classList.toggle('composer-options-popover',kind==='effort'||kind==='models');
    panel.classList.toggle('composer-model-popover',kind==='models');
    source.setAttribute('aria-expanded','true');
    if(kind==='add'){
      if(cascade)categories();
      else{title('添加分析资料');files(panel);}
    }else if(kind==='permission'){
      title('操作权限');
      row('仅分析与生成报告',()=>{$('task-notify').checked=false;changed($('task-notify'));showPermission();},!$('task-notify').checked);
      row('完成后发送授权邮件',()=>{$('task-notify').checked=true;changed($('task-notify'));showPermission();},$('task-notify').checked);
      const label=document.createElement('label');label.className='field';label.textContent='收件地址';
      const input=document.createElement('input');input.type='email';input.multiple=$('task-recipient').multiple;input.value=$('task-recipient').value;input.placeholder=input.multiple?'授权清单内的邮箱，多个用逗号分隔':'授权清单内的邮箱';input.setAttribute('aria-label','授权收件地址');
      input.oninput=()=>{$('task-recipient').value=input.value;changed($('task-recipient'));};label.append(input);panel.append(label);
      note('邮件仅向设置中的授权地址投递，未授权地址不会发送。');
    }else if(kind==='models'){
      title('选择模型');
      modelChoices(text(panel,'div','','composer-model-list'),panel);
      positionOptions();
    }else{showEffort();return;}
    const selected=kind==='models'?panel.querySelector('.selected'):null;
    (selected||panel.querySelector('button, input'))?.focus();
  }
  function openModels(){show('models',effort);}
  function showPermission(){active=null;show('permission',permission);}
  function changed(field){field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));update();}
  async function pickModel(id){
    if(saving)return;saving=true;const wasDisabled=send.disabled;send.disabled=true;
    panel.querySelectorAll('button').forEach(b=>{b.disabled=true;});
    try{const latest=await api('settings');await api('settings','PUT',{...latest,default_model_id:id});await refresh();close(true);}
    catch(error){notice(error.message,true);panel.querySelectorAll('button').forEach(b=>{b.disabled=false;});}
    finally{saving=false;send.disabled=wasDisabled;update();}
  }
  for(const [node,kind]of [[plus,'add'],[permission,'permission'],[effort,'effort']]){
    node.setAttribute('aria-haspopup','dialog');node.setAttribute('aria-controls',panel.id);node.setAttribute('aria-expanded','false');
    node.onclick=()=>{if(trigger===node&&!panel.hidden)close();else show(kind,node);};
  }
  document.addEventListener('pointerdown',event=>{if(active&&!panel.contains(event.target)&&!trigger?.contains(event.target))close();});
  document.addEventListener('keydown',event=>{
    if(event.defaultPrevented||event.repeat||event.isComposing||!event.ctrlKey||!event.shiftKey||event.altKey||event.metaKey||event.key.toLowerCase()!=='m')return;
    if(!effort.getClientRects().length||getComputedStyle(effort).visibility!=='visible'||dock.inert||toolbar.inert||document.querySelector('dialog[open]'))return;
    event.preventDefault();show('effort',effort);
  });
  dock.addEventListener('keydown',event=>{if(event.key==='Escape'&&active){event.preventDefault();close(true);}});
  panel.addEventListener('keydown',event=>{
    if(active!=='models'||!['ArrowUp','ArrowDown'].includes(event.key))return;
    const items=[...panel.querySelectorAll('.composer-menu-row:not(:disabled)')];
    if(!items.length)return;
    event.preventDefault();
    const next=items.indexOf(document.activeElement)+(event.key==='ArrowDown'?1:-1);
    items[(next+items.length)%items.length].focus();
  });
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
    plus.innerHTML=icon('plus');plus.title=$('analysis-data-status').textContent;
    permission.querySelector('span').textContent=$('task-notify').checked?'授权邮件':'仅分析';
    const selected=profiles.find(p=>p.enabled&&p.id===settings?.default_model_id);
    modelName.textContent=selected?.name||'选择模型';
    effortLabel.textContent=labels[levels.indexOf(effective())]||'默认';
    effort.setAttribute('aria-label',`选择模型与推理强度，${modelName.textContent}，${effortLabel.textContent}`);
    positionOptions();
    window.DesktopWorkbench?.update();
  }
  function syncMenu() {
    const cascade=useCategories();
    if(!document.body.classList.contains('analysis-composer-visible') || (active==='add'&&panel.classList.contains('composer-cascade')!==cascade))close();
    plus.setAttribute('aria-label',cascade?'打开对话工具':'添加分析资料');
    positionOptions();
  }
  new MutationObserver(syncMenu).observe(document.body,{attributes:true,attributeFilter:['class']});
  desktop.addEventListener('change',syncMenu);
  new ResizeObserver(positionOptions).observe(dock);
  syncMenu();update();return {update,close,openModels};
})();
