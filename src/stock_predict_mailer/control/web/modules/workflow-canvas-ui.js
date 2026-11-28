/* Canvas menus and editor-only annotations. Coordinates stay in the workflow's world space. */
window.WorkflowCanvasUI = (() => {
  const colors={blue:'蓝色',yellow:'黄色',green:'绿色',purple:'紫色',neutral:'灰色'};
  const icons={'⊕':'M12 8v8m-4-4h8m5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
    '▧':'M5 4h14v12l-4 4H5Zm10 16v-4h4M8 8h8m-8 4h6',
    '➚':'m6 3 12 11-6 1-3 5Zm6 12 4 5',
    '✋':'M7 12V8a1.5 1.5 0 0 1 3 0v3-6a1.5 1.5 0 0 1 3 0v6-4a1.5 1.5 0 0 1 3 0v5-2a1.5 1.5 0 0 1 3 0v5a6 6 0 0 1-6 6h-1c-3 0-4-2-6-4l-2-3a1.5 1.5 0 0 1 2-2l1 1',
    '◫':'M4 5h16v14H4Zm10 0v14',
    '↶':'m9 6-4 4 4 4m-4-4h9a4 4 0 1 1 0 8h-2',
    '↷':'m15 6 4 4-4 4m4-4h-9a4 4 0 1 0 0 8h2',
    '⛶':'M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5',
    '⋯':'M5 12h.01m7 0h.01m7 0h.01'};
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const point=({x,y})=>({x:clamp(x,-20000,20000),y:clamp(y,-20000,20000)});
  const element=(tag,cls)=>Object.assign(document.createElement(tag),{className:cls || ''});
  const label=(host,tag,content)=>{const node=element(tag);node.textContent=content;host.append(node);return node;};
  function normalize(raw) {
    const canvas={notes:[],comments:[]}, seen=new Set();
    for(const kind of Object.keys(canvas)) {
      if(!Array.isArray(raw?.[kind]))continue;
      for(const item of raw[kind].slice(0,24)) {
        if(!item || !/^[\w-]{1,64}$/.test(item.id) || seen.has(item.id) || typeof item.body!=='string' ||
            !Number.isFinite(item.x) || !Number.isFinite(item.y) || kind==='comments' && !item.body.trim())continue;
        seen.add(item.id);
        const saved={id:item.id,...point(item),body:item.body.slice(0,1500)};
        canvas[kind].push(kind==='comments'?saved:{...saved,color:Object.hasOwn(colors,item.color)?item.color:'blue',
          font:[14,16,20].includes(item.font)?item.font:14,width:clamp(Number(item.width)||260,160,1000),height:clamp(Number(item.height)||146,92,800)});
      }
    }
    return canvas.notes.length || canvas.comments.length?canvas:null;
  }
  function decorate(button, icon, name, shortcut='') {
    button.textContent=icon;button.title=shortcut?`${name} · ${shortcut}`:name;
    button.setAttribute('aria-label',name);button.dataset.tip=button.title;
    if(icons[icon]){
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
      const path=document.createElementNS(svg.namespaceURI,'path');
      svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
      path.setAttribute('d',icons[icon]);svg.append(path);button.replaceChildren(svg);
    }
    return button;
  }
  function safeURL(value) {
    try {const url=new URL(value);return ['https:','http:'].includes(url.protocol)?url.href:null;}
    catch (_) {return null;}
  }
  function markdown(host, lines) {
    const inline=(row,text)=>{
      const tokens=/\[([^\]\n]+)\]\(([^)\n]+)\)|\*\*([^*\n]+)\*\*|~~([^~\n]+)~~|\*([^*\n]+)\*/g;
      let offset=0;
      for(const match of text.matchAll(tokens)) {
        row.append(text.slice(offset,match.index));offset=match.index+match[0].length;
        const href=match[2] && safeURL(match[2]);
        if(href) {
          const link=label(row,'a',match[1]);link.href=href;link.target='_blank';link.rel='noopener noreferrer';
        } else if(match[1])row.append(match[0]);
        else label(row,match[3]?'strong':match[4]?'s':'em',match[3] || match[4] || match[5]);
      }
      row.append(text.slice(offset));
    };
    let list;
    for(const line of lines.split('\n')) {
      if(line.startsWith('- ')){
        if(!list){list=element('ul');host.append(list);}
        const item=element('li');list.append(item);inline(item,line.slice(2));
      } else {
        list=null;const row=element('div');host.append(row);inline(row,line || '\u00a0');
      }
    }
  }

  function install(api) {
    const {board,rail,layer,button}=api;
    const surface=board.querySelector('.desktop-flow-surface');
    const cards=element('div','canvas-annotations'), toolbar=element('div','canvas-note-tools');
    const menu=element('div','canvas-context-menu'), comment=element('form','canvas-comment-panel');
    const box=element('div','canvas-selection-box');
    surface.prepend(cards);board.append(toolbar,menu,comment,box);
    for(const item of [toolbar,menu,comment,box])item.hidden=true;
    menu.setAttribute('role','menu');menu.setAttribute('aria-label','画布操作');
    toolbar.setAttribute('role','toolbar');toolbar.setAttribute('aria-label','注释格式');
    let drawn, active, editor, clipboard, hand=false, menuAnchor, menuEdge, commentPoint, selection=[];
    let spaceHeld=false, suppressClick=false;
    const details=()=>api.data()?.canvas || {notes:[],comments:[]};
    const note=id=>details().notes.find(item=>item.id===id);
    const editing=target=>target.closest?.('input,textarea,select,[contenteditable="true"]');
    const spaceTarget=target=>board.contains(target) || rail.contains(target) || target===document.body;
    const bounds=()=>board.getBoundingClientRect();
    function dock(item,x,y,avoidPanel=false) {
      const rect=bounds(), panel=api.panel.getBoundingClientRect();
      const available=avoidPanel && panel.width && panel.height && panel.left-rect.left>item.offsetWidth+60?panel.left:rect.right;
      item.style.left=clamp(x-rect.left,6,Math.max(6,available-rect.left-item.offsetWidth-6))+'px';
      item.style.top=clamp(y-rect.top,6,Math.max(6,rect.height-item.offsetHeight-6))+'px';
    }
    function sync() {
      const card=active && cards.querySelector(`[data-canvas-note="${CSS.escape(active)}"]`);
      toolbar.hidden=!card;
      if(card){const rect=card.getBoundingClientRect();dock(toolbar,rect.left,rect.top-toolbar.offsetHeight-7,true);}
      if(!menu.hidden && menuAnchor)dock(menu,menuAnchor.x,menuAnchor.y);
      if(!comment.hidden && commentPoint){const location=api.screen(commentPoint);dock(comment,location.x+15,location.y+15,true);}
    }
    const write=(kind,items,message)=>api.commit({canvas:{...details(),[kind]:items}},message);
    function revise(change,message) {
      const item=note(active);
      if(!item)return;
      const updated={...item,...(editor?{body:editor.value}:{}),...change};
      if(JSON.stringify(item)!==JSON.stringify(updated))write('notes',details().notes.map(value=>value===item?updated:value),message);
    }
    function flush() {if(editor)revise({},'注释已更新');}
    function selectNote(id,focus=false) {
      if(active!==id)flush();
      active=id;selection=[];api.annotationFocus();draw();
      if(focus)editor?.focus({preventScroll:true});
    }
    function dropNoteFocus() {if(active){flush();active=null;draw();}}
    function markup(start,end=start) {
      if(!editor)return;
      const {selectionStart:a,selectionEnd:b,value}=editor;
      editor.setRangeText(start+value.slice(a,b)+end,a,b,'end');
      editor.focus({preventScroll:true});
    }
    function noteTools(item) {
      toolbar.replaceChildren();
      const color=element('select');color.setAttribute('aria-label','注释背景色');
      for(const [id,name] of Object.entries(colors))color.add(new Option(name,id));
      color.value=item.color;color.onchange=()=>{revise({color:color.value},'注释颜色已更新');editor?.focus({preventScroll:true});};
      const font=element('select');font.setAttribute('aria-label','注释字号');
      for(const [size,name] of [[14,'小'],[16,'中'],[20,'大']])font.add(new Option(name,size));
      font.value=item.font;font.onchange=()=>{revise({font:Number(font.value)},'注释字号已更新');editor?.focus({preventScroll:true});};
      toolbar.append(color,font);
      for(const [icon,name,format] of [['B','加粗','**'],['I','斜体','*'],['S̶','删除线','~~']]) {
        toolbar.append(decorate(button('',()=>markup(format)),icon,name));
      }
      toolbar.append(decorate(button('',()=>{
        const href=prompt('输入 HTTP 或 HTTPS 链接');
        if(href && safeURL(href)&&editor){
          const start=editor.selectionStart===editor.selectionEnd?'['+href:'[';
          markup(start,`](${href})`);
        }
        else if(href)api.message('请输入有效的 HTTP 或 HTTPS 链接。');
      }),'↗','插入链接'),decorate(button('',()=>{
        if(!editor)return;
        const a=editor.value.lastIndexOf('\n',editor.selectionStart-1)+1;
        const end=editor.value.indexOf('\n',editor.selectionEnd), b=end<0?editor.value.length:end;
        editor.setRangeText(editor.value.slice(a,b).split('\n').map(line=>'- '+line).join('\n'),a,b,'end');editor.focus();
      }),'≡','列表'),decorate(button('',()=>removeNote()),'⌫','删除注释'));
      toolbar.onpointerdown=event=>{if(event.target.closest('button'))event.preventDefault();};
    }
    function place(card,item) {card.style.left=item.x+'px';card.style.top=item.y+'px';}
    function drag(handle,card,item,resize) {
      handle.onpointerdown=event=>{
        if(event.button!==0 || api.panning())return;
        event.stopPropagation();event.preventDefault();handle.setPointerCapture(event.pointerId);
        const start=api.world(event);let change=null;
        handle.onpointermove=move=>{
          if(move.pointerId!==event.pointerId)return;
          const current=api.world(move), dx=current.x-start.x, dy=current.y-start.y;
          if(!change && Math.hypot(dx,dy)<2)return;
          change=resize?{width:clamp(item.width+dx,160,1000),height:clamp(item.height+dy,92,800)}:
            point({x:item.x+dx,y:item.y+dy});
          if(resize){card.style.width=change.width+'px';card.style.height=change.height+'px';}
          else place(card,change);
          sync();
        };
        handle.onpointerup=()=>{
          handle.onpointermove=null;
          if(change){
            if(active && active!==item.id)flush();
            const body=active===item.id && editor?editor.value:item.body;
            write('notes',details().notes.map(value=>value.id===item.id?{...item,...change,body}:value),resize?'注释大小已更新':'注释位置已更新');
          } else selectNote(item.id);
        };
        handle.onpointercancel=()=>{handle.onpointermove=null;draw();};
      };
    }
    function draw() {
      drawn=api.data();editor=null;cards.replaceChildren();
      if(!drawn){active=null;sync();return;}
      for(const item of details().notes) {
        const card=element('article','canvas-note');card.dataset.canvasNote=item.id;card.dataset.color=item.color;
        card.style.width=item.width+'px';card.style.height=item.height+'px';card.style.fontSize=item.font+'px';place(card,item);
        const grip=decorate(button('',()=>{}),'⠿','拖动注释');grip.className='canvas-note-grip';
        card.append(grip);drag(grip,card,item,false);
        if(active===item.id){
          const area=element('textarea');area.placeholder='输入注释…';area.setAttribute('aria-label','注释正文');area.maxLength=1500;area.value=item.body;
          area.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();dropNoteFocus();api.canvasFocus();}};
          editor=area;card.append(area);card.dataset.active='';
          const resize=decorate(button('',()=>{}),'⌟','调整注释大小');resize.className='canvas-note-resize';
          card.append(resize);drag(resize,card,item,true);noteTools(item);
        } else {
          const content=element('div','canvas-note-text');content.tabIndex=0;content.setAttribute('aria-label','编辑注释');
          markdown(content,item.body || '输入注释…');card.append(content);
          content.onclick=event=>{if(!event.target.closest('a')&&!api.panning())selectNote(item.id,true);};
          content.onkeydown=event=>{if(event.target===content && event.key==='Enter'){event.preventDefault();selectNote(item.id,true);}};
        }
        cards.append(card);
      }
      for(const item of details().comments) {
        const pin=decorate(button('',()=>openComment(item,item)),'▤','查看评论');pin.className='canvas-comment-pin';
        pin.dataset.commentId=item.id;place(pin,item);cards.append(pin);
      }
      if(active && !note(active))active=null;
      sync();
    }
    function addNote(location) {
      flush();if(details().notes.length>=24){api.message('已达到 24 张注释的上限');return;}
      const item={id:crypto.randomUUID(),...point(location),body:'',width:260,height:146,color:'blue',font:14};
      active=item.id;selection=[];api.annotationFocus();
      write('notes',[...details().notes,item],'已添加注释');editor?.focus({preventScroll:true});
    }
    function removeNote() {
      const id=active;flush();active=null;editor=null;
      write('notes',details().notes.filter(item=>item.id!==id),'注释已删除，可撤销');
    }
    function closeComment(){comment.hidden=true;commentPoint=null;}
    function openComment(location,item,editing=false) {
      dropNoteFocus();
      if(!item && details().comments.length>=24){api.message('已达到 24 条评论的上限');return;}
      comment.replaceChildren();comment.hidden=false;commentPoint=point(location);
      label(comment,'strong',item?'画布评论 · 本工作区':'添加评论');
      const close=button('关闭',closeComment);
      if(item && !editing){
        label(comment,'p',item.body);
        const actions=element('div','actions');
        actions.append(button('编辑评论',()=>openComment(item,item,true)),button('删除评论',()=>{
          closeComment();write('comments',details().comments.filter(value=>value.id!==item.id),'评论已删除，可撤销');
        }),close);
        comment.append(actions);sync();return;
      }
      const area=element('textarea');area.required=true;area.maxLength=1500;area.rows=3;
      area.placeholder='输入评论…';area.setAttribute('aria-label','评论内容');area.value=item?.body || '';
      area.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();closeComment();api.canvasFocus();}};
      const submit=button(item?'保存评论':'发送评论');submit.type='submit';
      const actions=element('div','actions');actions.append(submit,close);
      comment.append(area,actions);
      comment.onsubmit=event=>{
        event.preventDefault();const body=area.value.trim();if(!body)return;
        const saved={id:item?.id || crypto.randomUUID(),...commentPoint,body};
        closeComment();write('comments',item?details().comments.map(value=>value.id===item.id?saved:value):[...details().comments,saved],'评论已保存到流程草稿');
      };
      sync();area.focus({preventScroll:true});
    }
    function closeMenu(restore=false) {
      if(menu.hidden)return;
      menu.hidden=true;menuEdge=null;
      if(restore)api.canvasFocus();
    }
    function showMenu(entries,anchor,edge=null) {
      menuEdge=edge;
      menu.toggleAttribute('data-edge-menu',Boolean(edge));
      menu.setAttribute('aria-label',edge?'连线操作':'画布操作');
      menu.replaceChildren();menu.hidden=false;menuAnchor=anchor;
      for(const [name,shortcut,operation,reason] of entries) {
        const row=button('',()=>{closeMenu();operation();});row.setAttribute('role','menuitem');row.tabIndex=-1;
        row.disabled=Boolean(reason);label(row,'span',name);
        if(shortcut)label(row,'kbd',shortcut);
        if(reason){label(row,'small',reason);row.title=reason;}
        menu.append(row);
      }
      dock(menu,anchor.x,anchor.y);menu.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
    }
    function saveCopy(node) {
      clipboard={owner:api.owner(),node:api.copy(node)};api.message('已拷贝节点，可在画布中粘贴');
    }
    function paste(location) {
      if(clipboard?.owner===api.owner())api.duplicate(clipboard.node,location);
    }
    function edgeAt(target) {
      const data=target.closest('[data-edge-id],[data-edge-hit],[data-edge-insert]')?.dataset;
      return data?.edgeId || data?.edgeHit || data?.edgeInsert;
    }
    function context(target,anchor) {
      dropNoteFocus();closeComment();
      const edge=edgeAt(target);
      if(edge){showMenu([['删除','',()=>api.removeEdge(edge)]],anchor,edge);return;}
      const card=target.closest('[data-workflow-node]'), node=card && api.node(card.dataset.workflowNode);
      const location=api.world({clientX:anchor.x,clientY:anchor.y});
      if(node){
        api.select(node.id);
        showMenu([['运行此步骤','',()=>api.debug(node),api.debugReason(node)],
          ['更改节点','',()=>api.replace(node,anchor),node.data.type==='input'?'流程入口需保留':''],
          ['拷贝','Ctrl/Cmd + C',()=>saveCopy(node)],['复制','Ctrl/Cmd + D',()=>api.duplicate(node)],
          ['删除','Delete',()=>api.remove(node.id)]],anchor);
      } else {
        showMenu([['添加节点','',()=>api.add(location)],['添加注释','',()=>addNote(location)],
          ['添加评论','',()=>openComment(location)],...(clipboard?.owner===api.owner()?
            [['粘贴','Ctrl/Cmd + V',()=>paste(location)]]:[]),['测试运行','Alt + R',api.run]],anchor);
      }
    }
    board.addEventListener('contextmenu',event=>{
      if(!api.editable() || event.target.closest('.canvas-context-menu,.canvas-note,.canvas-comment-panel,.canvas-comment-pin,.canvas-note-tools'))return;
      event.preventDefault();context(event.target,{x:event.clientX,y:event.clientY});
    });
    menu.onkeydown=event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeMenu(true);return;}
      if(event.key==='Tab'){closeMenu(true);return;}
      if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
      event.preventDefault();const items=[...menu.querySelectorAll('button:not(:disabled)')];
      const index=items.indexOf(document.activeElement), next=event.key==='Home'?0:event.key==='End'?items.length-1:
        (index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;
      items[next]?.focus({preventScroll:true});
    };
    document.addEventListener('pointerdown',event=>{
      if(!menu.contains(event.target))closeMenu();
      if(!comment.contains(event.target) && !event.target.closest('.canvas-comment-pin'))closeComment();
      if(!toolbar.contains(event.target) && !event.target.closest('[data-canvas-note]'))dropNoteFocus();
    });
    document.addEventListener('keydown',event=>{
      if(event.defaultPrevented || !api.editable() || !spaceTarget(event.target) || editing(event.target) || document.querySelector('dialog[open]'))return;
      const key=event.key.toLowerCase(), modified=event.ctrlKey || event.metaKey, node=api.selected();
      if(key==='escape'){closeMenu(true);closeComment();dropNoteFocus();return;}
      if((key==='contextmenu' || key==='f10' && event.shiftKey) && (board.contains(event.target)||event.target===board)){
        event.preventDefault();const card=event.target.closest('[data-workflow-node]');
        const rect=(card || board).getBoundingClientRect(), anchor={x:rect.left+20,y:rect.top+40};
        context(event.target,anchor);return;
      }
      if(key===' ' && event.target===board){spaceHeld=true;event.preventDefault();return;}
      let action;
      if(event.altKey && key==='r')action=api.run;
      else if(modified && key==='v' && clipboard?.owner===api.owner())action=()=>paste(api.center());
      else if(modified && key==='c' && node && !active)action=()=>saveCopy(node);
      else if(modified && key==='d' && node && !active)action=()=>api.duplicate(node);
      else if(modified && ['z','y'].includes(key))action=key==='y'||event.shiftKey?api.redo:api.undo;
      else if(key==='delete'){
        const edge=menuEdge || edgeAt(event.target);
        if(edge)action=()=>{closeMenu(true);api.removeEdge(edge);};
        else if(active || node)action=()=>active?removeNote():api.remove(node.id);
      }
      if(action){event.preventDefault();action();}
    });
    window.addEventListener('keyup',event=>{if(event.key===' ')spaceHeld=false;});
    window.addEventListener('blur',()=>{spaceHeld=false;});
    window.addEventListener('pagehide',flush);
    function setMode(value) {
      hand=value;rail.querySelector('[data-canvas-tool="pan"]').setAttribute('aria-pressed',String(hand));
      rail.querySelector('[data-canvas-tool="select"]').setAttribute('aria-pressed',String(!hand));
      board.classList.toggle('canvas-select-tool',!hand);
    }
    const tool=(key,icon,name,action,shortcut)=>{
      const item=decorate(button('',action),icon,name,shortcut);item.dataset.canvasTool=key;return item;
    };
    const add=rail.querySelector('#workflow-library-toggle');
    decorate(add,'⊕','添加节点');add.dataset.canvasTool='nodes';
    rail.prepend(add,tool('note','▧','添加注释',()=>addNote(api.center())),tool('select','➚','选择',()=>setMode(false)),
      tool('pan','✋','平移',()=>setMode(true)));
    rail.append(tool('fit','⛶','适应视图',api.fit),tool('more','⋯','更多操作',event=>{
      const rect=event.currentTarget.getBoundingClientRect();
      showMenu([['添加评论','',()=>openComment(api.center())],['测试运行','Alt + R',api.run],['导出流程','',api.export]],{x:rect.right+6,y:rect.top});
    }));
    setMode(false);board.tabIndex=0;
    const resize=new ResizeObserver(sync);resize.observe(board);resize.observe(api.panel);
    return {render(){
        for(const item of rail.querySelectorAll('[data-canvas-tool="note"],[data-canvas-tool="more"]'))item.disabled=!api.data();
        if(drawn!==api.data())draw();else sync();
      },sync,flush,
      reset(){dropNoteFocus();closeComment();closeMenu();selection=[];},panning:()=>hand||spaceHeld,
      takeClick(){const value=suppressClick;suppressClick=false;return value;},
      deselect(){selection=[];},contains:id=>selection.includes(id),
      marquee(from,to,finish=false){
        const x=Math.min(from.x,to.x),y=Math.min(from.y,to.y),w=Math.abs(from.x-to.x),h=Math.abs(from.y-to.y);
        box.hidden=finish || w+h<5;box.style.left=x+'px';box.style.top=y+'px';box.style.width=w+'px';box.style.height=h+'px';
        if(!finish)return;
        const rect=bounds();selection=w+h<5?[]:[...board.querySelectorAll('[data-workflow-node]')].filter(card=>{
          const b=card.getBoundingClientRect();return b.right>=rect.left+x && b.left<=rect.left+x+w && b.bottom>=rect.top+y && b.top<=rect.top+y+h;
        }).map(card=>card.dataset.workflowNode);
        api.boxSelect(selection);if(selection.length)api.message(`已框选 ${selection.length} 个节点`);
      },ignoreClick(){suppressClick=true;setTimeout(()=>{suppressClick=false;},0);}};
  }
  return {install,normalize,decorate};
})();
