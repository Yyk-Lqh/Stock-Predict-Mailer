/* Articulated SVG office; backend state is never inferred from animation. */
window.PonyOffice = (() => {
  const {Floor, roles} = PonyFloor, floor = new Floor(), childProgress = new PonyChildren.Tracker(), taskProgress = new PonyTaskProgress.Tracker();
  const NS = 'http://www.w3.org/2000/svg';
  let taskId = null, replay = true, seen = new Set(), active = true, connected = true, taskState = 'idle', selected = 'main';
  let lastFrame = 0, raf = 0, lastUI = 0, roleSignature = '', terminalFeedback = '';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const el = (name, attrs = {}, markup = '') => {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (markup) node.innerHTML = markup;
    return node;
  };
  const office = document.createElement('section'); office.className = 'pony-office'; office.setAttribute('aria-label', '小马协作办公室');
  office.innerHTML = `<div class="office-heading"><div><span class="eyebrow">AGENT OFFICE</span><h2>小马办公室</h2></div><span id="office-live" class="hint">等待分析任务</span></div><div class="office-mobile-tabs"><button type="button" id="office-show-room" aria-pressed="true">办公室</button><button type="button" id="office-show-output" aria-pressed="false">进度与报告</button></div><div class="office-stage"></div><div class="office-legend" aria-label="角色选择"></div><p class="office-footnote">围巾标记职责 · 在室亮屏 · 游戏仅为空闲活动 · 点击小马查看真实进度</p>`;
  $('analysis-title').textContent = '分析工作台';
  $('analysis-title').closest('.page-head').after(office);
  $('workbench-intro').classList.add('office-welcome');
  const svg = el('svg', {viewBox: '-65 0 1025 620', role: 'group', 'aria-label': '六个固定工位，小马通过门洞进出办公室'});
  svg.innerHTML = `<defs>
    <filter id="pony-shadow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="5"/></filter>
    <linearGradient id="pony-desk" x2="0" y2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#eceeed"/></linearGradient>
    <linearGradient id="pony-chair" x2="1" y2="1"><stop stop-color="#fdfdfb"/><stop offset="1" stop-color="#d8ddde"/></linearGradient>
    <radialGradient id="pony-daylight" cx=".2" cy=".12" r="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#e9eceb"/></radialGradient>
    <clipPath id="pony-screen-clip"><rect x="-48" y="-116" width="96" height="58" rx="2"/></clipPath>
    <clipPath id="pony-portal-clip" clipPathUnits="userSpaceOnUse"><path d="M8 436H74V552H8ZM80 0H960V620H80Z"/></clipPath>
    </defs><rect x="-65" width="1025" height="620" rx="12" class="office-floor"/>
    <path d="M64 580H910" class="office-floor-line"/><text x="76" y="603" class="office-floor-caption">预测 · 证据 · 分析 · 交付</text>`;
  const door = el('g', {transform: `translate(0 ${PonyDoor.frame.y})`}, '<ellipse cx="40" cy="128" rx="46" ry="7" fill="#58636b" opacity=".12"/><rect x="1" y="0" width="79" height="128" rx="4" class="office-door-frame"/><rect x="8" y="6" width="66" height="116" rx="1" fill="#6e7d84"/><g id="office-door-leaf" class="office-door-leaf"><path class="office-door-panel" fill="#e4e8e6"/><path class="office-door-inset" fill="#f5f6f2" stroke="#cbd2d0"/><g class="office-door-handle" data-door-side="outside"><circle r="2.5" fill="#b1996a"/><path d="M0 0H7" stroke="#9b8256" stroke-width="2.3" stroke-linecap="round"/></g><g class="office-door-handle" data-door-side="inside"><circle r="2.5" fill="#b1996a"/><path d="M0 0H-7" stroke="#9b8256" stroke-width="2.3" stroke-linecap="round"/></g></g><text x="40" y="147" text-anchor="middle" class="office-floor-caption">出入口</text>');
  svg.append(door);
  const world = el('g'); svg.append(world); office.querySelector('.office-stage').append(svg);
  const frontDoor=el('g',{transform:`translate(0 ${PonyDoor.frame.y})`,'pointer-events':'none'},'<use class="office-door-front-leaf" href="#office-door-leaf" display="none"/><path d="M1 0H80V128H1ZM8 6V122H74V6Z" fill="#aeb9c3" fill-rule="evenodd"/>');
  svg.append(frontDoor);
  const desks = new Map(), chairs = new Map(), ponies = new Map(), avatars = new Map(), buttons = new Map(), rigs = new Map(), screens = new Map();
  let lastScreen = -1;
  function choose(id) {
    selected = id;
    if (id === 'assistant') { window.AnalysisInput?.open('input'); return; }
    for (const [key, button] of buttons) button.setAttribute('aria-pressed', String(key === id));
    window.Workbench.inspector(true);
    $('office-roles').querySelector(`[data-office-role="${id}"]`)?.scrollIntoView({block: 'nearest'});
    renderUI();
  }
  for (const role of roles) {
    const desk = el('g', {transform: `translate(${role.x} ${role.y})`, 'data-office-desk':role.id}, `
      <ellipse cx="3" cy="68" rx="112" ry="18" fill="#58616a" opacity=".12" filter="url(#pony-shadow)"/>
      <path d="M-99-25L-95 64H-88L-85-25M85-25L89 64H96L101-25" fill="#c9d0d1"/>
      <path d="M-96 60H-88V65H-96M89 60H97V65H89" fill="#9da9ac"/>
      <path d="M57-13H98V55H57Z" fill="#e2e6e5"/><path d="M57-13L64-18H101L98 55H94V-9Z" fill="#f4f5f2"/>
      <path d="M60 11H94M60 33H94" stroke="#c8d0ce"/><path d="M73 0H82M73 22H82" stroke="#acb7b6" stroke-width="2" stroke-linecap="round"/>
      <path d="M-110 1H110V10H-110Z" fill="#d6dddb"/><path d="M-98-53H98L110 1H-110Z" fill="url(#pony-desk)" stroke="#e3e7e5"/>
      <path d="M-108 2H108" stroke="#fff" stroke-width="1.5"/>
      <ellipse cx="0" cy="-25" rx="28" ry="5" fill="#a9b5b8" opacity=".15"/>
      <path d="M-6-55H6L9-27H-9Z" fill="#c2cbcd"/><path d="M-21-28H21L27-23H-27Z" fill="#d4dbdc" stroke="#bbc6c9" stroke-width=".6"/>
      <rect x="35" y="-13" width="28" height="20" rx="4" fill="#dce3e3" stroke="#cdd5d5" stroke-width=".6"/>
      <g class="office-keyboard"><path d="M-44-10H27L32 4H-48Z" fill="#c6d1d5" stroke="#a6b5bc" stroke-width=".7"/>
      <path d="M-40-7H25M-41-3H26M-42 1H27M-32-8L-34 1M-23-8L-24 1M-14-8V1M-5-8V1M4-8L5 1M13-8L15 1M21-8L23 1" stroke="#f8faf8" stroke-width="1.4"/><path d="M-25 2H11" stroke="#fdfefb" stroke-width="2"/></g>
      <g class="office-mouse"><ellipse cx="48" cy="-1" rx="8" ry="5.7" fill="#abb9bf"/><ellipse cx="48" cy="-2" rx="7" ry="5" fill="#f6f7f3"/><path d="M48-6V-2M43-2H53" stroke="#b8c4c8" stroke-width=".7"/><path d="M48-6V-4" stroke="#73868e" stroke-width="1.5"/></g>
      <rect x="-54" y="-122" width="108" height="71" rx="5" fill="#c3ced0"/>
      <rect x="-52" y="-121" width="104" height="68" rx="4" fill="#f7f8f5"/>
      <rect x="-48" y="-116" width="96" height="58" rx="2" fill="#283339" class="office-monitor"/>
      <g class="office-screen" clip-path="url(#pony-screen-clip)" visibility="hidden"></g>
      <image class="office-chart-screen" x="18" y="-103" width="28" height="17" clip-path="url(#pony-screen-clip)" visibility="hidden"/>
      <circle class="office-monitor-light" cx="0" cy="-54.5" r="1" fill="#93b8a0"/>
      <ellipse cx="0" cy="87" rx="29" ry="7" fill="#74828a" opacity=".13"/>
      <path d="M0 63V92M0 91L-23 103M0 91L23 103M0 91V105" stroke="#aebbbf" stroke-width="4" stroke-linecap="round"/>
      <circle cx="-23" cy="104" r="3" fill="#76898e"/><circle cx="23" cy="104" r="3" fill="#76898e"/><circle cx="0" cy="106" r="3" fill="#76898e"/>
      <path d="M-27 37Q0 28 27 37L29 54Q0 65-29 54Z" fill="url(#pony-chair)" stroke="#c5cfcf" stroke-width=".7"/>
      <text x="0" y="-139" text-anchor="middle" class="office-desk-name">${role.name}</text><circle cx="-63" cy="-143" r="4" fill="${role.color}"/>`);
    desks.set(role.id, desk); world.append(desk);
    const chair=el('g',{transform:`translate(${role.x} ${role.y})`,'data-office-chair':role.id},'<path d="M-24 48Q0 42 24 48L27 77Q0 86-27 77Z" fill="url(#pony-chair)" stroke="#cbd4d3" stroke-width=".8"/><path d="M-22 51Q0 47 22 51" stroke="#fff" stroke-width="1.5" fill="none"/><path d="M-27 77Q0 86 27 77" stroke="#b9c5c5" stroke-width="1.2" fill="none"/>');
    chairs.set(role.id,chair);world.append(chair);
    if (!role.station) desk.setAttribute('display', 'none');
    if (!role.station) chair.setAttribute('display','none');
    const pony = el('g', {role: 'button', tabindex: '0', 'aria-label': `${role.name}小马，查看工作状态`, 'data-pony': role.id});
    pony.innerHTML = PonyRig.markup(role, roles.indexOf(role));
    pony.addEventListener('click', () => choose(role.id));
    pony.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); choose(role.id); } });
    const avatar=el('g',{'data-pony-portal':role.id});avatar.append(pony);
    ponies.set(role.id, pony);avatars.set(role.id,avatar);world.append(avatar);
    rigs.set(role.id, Object.fromEntries(['eyes','head','rig','leg-left','leg-right','arm-left','arm-right','scarf','tail','ear','mane','seated-head','back-eye','back-ear','front-head','front-eyes'].map(part => [part, pony.querySelector('.pony-'+part)])));
    rigs.get(role.id).pupils = [...pony.querySelectorAll('.pony-pupil')];
    const rig = rigs.get(role.id);
    rig.expression = pony.querySelector('.pony-expression');
    rig.torso = pony.querySelector('.pony-torso');
    rig.ground=pony.querySelector('.pony-ground');
    rig.armsLayer=pony.querySelector('.pony-arms');
    rig.arms = Object.fromEntries(['left','right'].map(side => [side, {
      line: rig['arm-'+side].querySelector('path'), elbow:rig['arm-'+side].querySelector('circle'), hoof:rig['arm-'+side].querySelector('ellipse')
    }]));
    const screen = desk.querySelector('.office-screen');
    screen.dataset.officeRole=role.id;
    screen.replaceChildren(); const screenTitle = el('title'); desk.prepend(screenTitle);
    screens.set(role.id, {node:screen, title:screenTitle, chart:desk.querySelector('.office-chart-screen')});
    const button = document.createElement('button'); button.type = 'button'; button.className = 'office-role-button';
    button.textContent = role.name; button.style.setProperty('--role-color', role.color); button.setAttribute('aria-pressed', 'false'); button.onclick = () => choose(role.id);
    buttons.set(role.id, button); office.querySelector('.office-legend').append(button);
  }
  const portal = document.createElement('div'); portal.className = 'sidebar-office-door';
  portal.innerHTML = '<span class="sidebar-door-art" aria-hidden="true"><i></i></span><span>协作通道<small>子 Agent 由此进出</small></span>';
  office.querySelector('.office-heading').append(portal);
  const progress = document.createElement('section'); progress.id = 'office-progress'; progress.className = 'office-progress';
  progress.innerHTML = '<h3>工作进度</h3><p id="office-task-state" role="status">等待分析任务</p><p id="office-connection" class="error-text" hidden>连接中断，正在恢复；暂不显示新的工作进展。</p><div id="office-roles"></div>';
  $('inspector-content').prepend(progress);
  for (const id of ['runviz', 'effective-effort']) progress.append($(id));
  progress.append(document.querySelector('.execution-details'), $('analysis-preview'), $('chart-preview'));
  $('report-inspector').querySelector('h2').textContent = '工作进度与产出';
  const captions = {idle: '待命', pending: '等待执行', running: '执行中', completed: '已完成', failed: '失败', canceled: '已取消', uncertain: '结果未知', simulated: '模拟投递', submitted: '已提交服务器', retry: '等待重试', not_requested: '未请求通知'};
  function renderUI() {
    $('office-live').textContent = taskId ? `${TASK_STATE[taskState] || taskState} · ${taskId.slice(0, 8)}` : '等待分析任务';
    $('office-task-state').textContent = taskId ? `${TASK_STATE[taskState] || taskState} · 已运行 ${$('runviz-elapsed').textContent}` : '尚无运行任务，主 Agent 与邮件小马待命。';
    $('office-connection').hidden = connected;
    const signature = floor.actors.map(a => [a.id,a.state,a.pose,a.last,a.activity,a.present].join(':')).join('|') + selected;
    if (signature === roleSignature) return;
    roleSignature = signature;
    const host = $('office-roles'); host.replaceChildren();
    for (const actor of floor.actors) {
      const row = document.createElement('button'); row.type = 'button'; row.className = 'office-role-state'; row.dataset.officeRole = actor.id;
      row.classList.toggle('selected', selected === actor.id); row.style.setProperty('--role-color', actor.color);
      const name = document.createElement('strong'); name.textContent = actor.name;
      const state = document.createElement('span'); state.textContent = `${captions[actor.state] || actor.state}${actor.present && !['seated', 'absent'].includes(actor.pose) ? ' · ' + ({walking: '前往工位 / 返回', waiting: '等待通行', turning: '调整朝向', sitting: '正在落座', rising: '正在离座', opening:'正在开门', 'door-handle':'正在开门', 'door-close':'正在关门', idle:'观察环境'}[actor.pose] || actor.pose) : ''}`;
      const note = document.createElement('small'); note.textContent = actor.state === 'running' || floor.time < actor.feedbackUntil ? actor.last : !actor.present ? '离室 · 场景来访不会启动模型' : actor.pose === 'seated' ? '空闲 · ' + PonyScreen.games[actor.activity % 5] : '办公室活动 · 未启动模型';
      row.append(name, state, note); row.onclick = () => { if (actor.id === 'assistant') window.AnalysisInput?.open('input'); selected = actor.id; renderUI(); }; host.append(row);
    }
  }
  function reset(id = null, restoring = true) {
    taskId = id; replay = restoring; seen = new Set(); taskState = id ? 'submitted' : 'idle'; connected = true; floor.reset();
    childProgress.reset(); taskProgress.reset();
    terminalFeedback='';
    for (const desk of desks.values()) {
      const chart=desk.querySelector('.office-chart-screen');
      chart.setAttribute('visibility','hidden');chart.removeAttribute('href');
    }
    renderUI(); draw();
  }
  function sync(task, events = []) {
    if (task.id !== taskId) reset(task.id, true);
    taskState = task.status.state; connected = true;
    for (const event of events || []) {
      if (seen.has(event.seq)) continue; seen.add(event.seq);
      const progress=taskProgress.update(event), mainActor=floor.actors.find(a=>a.id==='main');
      mainActor.completedSteps=progress.completed; mainActor.totalSteps=progress.total; mainActor.progressPercent=progress.percent;
      for(const actor of floor.actors)if(actor.id!=='main'){
        const roleProgress=progress.byRole[actor.id];
        actor.completedSteps=roleProgress?.completed||0; actor.totalSteps=roleProgress?.total??null; actor.progressPercent=roleProgress?.percent??null;
      }
      const id = ['prediction', 'risk', 'advice', 'charts', 'mail'].includes(event.step) ? event.step : 'main';
      if (event.kind === 'step') {
        const actor = floor.actors.find(a => a.id === id);
        const state = event.status === 'running' ? 'running' : event.status;
        actor.taskId = task.id; actor.taskLabel = task.metadata?.request?.subject || task.input?.subject || 'Agent 任务';
        if (event.child_id) actor.childId = event.child_id;
        if (state === 'running' && !actor.startedAt) actor.startedAt = event.timestamp;
        if (replay) { actor.state = state; actor.last = event.label; if (state === 'running') { actor.present = true; actor.pose = 'seated'; } }
        else floor.set(id, state, event.label);
      }
      if (event.kind === 'tool' || event.kind === 'adjustment') {
        const actor = floor.actors.find(a => a.id === id);
        actor.last = event.label || actor.last;
        if (event.kind === 'tool' && event.status === 'running') floor.set(id, 'running', '调用工具 · ' + event.label);
      }
      if (event.kind === 'step' && ['prediction','risk','advice'].includes(id)) {
        const main = floor.actors.find(a => a.id === 'main');
        main.taskId = task.id;
        const progress=childProgress.update(id,event.child_id,event.status);
        if (progress && (event.status==='running' || main.state==='running')) floor.set('main','running',progress.message);
      }
      if (event.kind === 'mail') floor.set('mail', event.status, event.label);
      if (event.kind === 'chart' && event.svg) {
        const screen = desks.get('charts').querySelector('.office-chart-screen'); screen.setAttribute('href', 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(event.svg));
      }
    }
    if (['completed', 'failed', 'canceled'].includes(taskState) && terminalFeedback!==task.id+taskState) {
      floor.finish(taskState);
      floor.set('main',taskState,taskState==='completed'?'分析任务已完成':taskState==='failed'?'分析任务失败':'分析任务已取消');
      terminalFeedback=task.id+taskState;
    }
    if (replay) for (const actor of floor.actors) if (!actor.resident && actor.state !== 'running') { actor.present = false; actor.pose = 'absent'; }
    if (events && events.length < 100) replay = false;
    renderUI(); draw(true);
  }
  function draw(force = false) {
    const refreshScreen = force || floor.time - lastScreen > .16 || lastScreen > floor.time;
    if (refreshScreen) lastScreen = floor.time;
    const nodes = [];
    for (const actor of floor.actors) {
      if (actor.state === 'running' && actor.startedAt && Number.isFinite(Date.parse(actor.startedAt))) actor.elapsed = Math.max(0,(Date.now()-Date.parse(actor.startedAt))/1000);
      const desk = desks.get(actor.id), pony = ponies.get(actor.id), rig = rigs.get(actor.id), screen = screens.get(actor.id);
      const working = connected && actor.state === 'running' && actor.pose === 'seated' && !['completed', 'failed', 'canceled'].includes(taskState);
      if (refreshScreen) {
        const display = PonyScreen.render(actor, floor.time, connected);
        screen.node.setAttribute('visibility', display.mode === 'off' ? 'hidden' : 'visible');
        screen.node.dataset.mode = display.mode; screen.title.textContent = actor.name + ' · ' + display.title;
        screen.node.innerHTML = display.markup;
      }
      screen.chart.setAttribute('visibility', actor.id === 'charts' && working && screen.chart.hasAttribute('href') ? 'visible' : 'hidden');
      nodes.push({node: desk, depth: actor.deskY + 25});
      nodes.push({node: chairs.get(actor.id), depth: actor.deskY + 79});
      const seated = ['seated', 'sitting', 'rising'].includes(actor.pose);
      const motion=floor.motion(actor.id);
      const portal=PonyDoor.portal(actor,motion,floor.door),avatar=avatars.get(actor.id);
      pony.setAttribute('display',portal.visible?'inline':'none');pony.setAttribute('tabindex',portal.visible?'0':'-1');
      pony.setAttribute('aria-hidden',String(!portal.visible));pony.dataset.portalState=portal.state;
      if(portal.clipped)avatar.setAttribute('clip-path','url(#pony-portal-clip)');else avatar.removeAttribute('clip-path');
      const transition = Math.min(1, (motion?.elapsed || 0) / (actor.pose === 'rising' ? .55 : .7));
      const sit = PonyRig.smooth(actor.pose === 'seated' ? 1 : actor.pose === 'sitting' ? transition : actor.pose === 'rising' ? 1-transition : 0);
      const walking = actor.pose === 'walking' && !reduced.matches;
      const phase = actor.phase, stride = walking ? Math.sin(phase)*23 : 0;
      // Root stays at the seat anchor. Breathing and typing never drag hooves off devices.
      const action=actor.doorAction, lean=action?actor.heading*action.lean:0;
      const bob = reduced.matches||action ? 0 : walking ? Math.abs(Math.sin(phase))*1.7 : Math.sin(phase)*.4*(1-sit);
      const origin={x:actor.x+lean,y:actor.y-bob};
      pony.setAttribute('transform', `translate(${origin.x.toFixed(3)} ${origin.y.toFixed(3)}) scale(${PonyRig.scale})`);
      actor.visualHeading = reduced.matches ? actor.heading : (actor.visualHeading ?? actor.heading) + (actor.heading-(actor.visualHeading ?? actor.heading))*.14;
      const turnWidth=Math.sign(actor.visualHeading||1)*(.78+.22*Math.abs(actor.visualHeading));
      const scaleX=sit+turnWidth*(1-sit);
      rig.rig.setAttribute('transform', `scale(${scaleX} 1)`);
      rig.ground.setAttribute('transform',`translate(${-lean/PonyRig.scale} 0)`);
      const rear=sit || (walking&&actor.facing==='back'?1:0);
      const front=!rear&&walking&&actor.facing==='front'?1:0;
      rig.head.setAttribute('opacity', String((1-rear)*(1-front)));
      rig['seated-head'].setAttribute('opacity', String(rear));
      rig['front-head'].setAttribute('opacity',String(front));
      const mode=PonyScreen.state(actor,floor.time,connected);
      const expression=PonyRig.expression(actor,floor.time,mode,reduced.matches);
      const blink=expression.blink;
      screen.node.setAttribute('opacity',String(1-expression.sleep*.24));
      rig.eyes.setAttribute('visibility', actor.facing==='back' && walking ? 'hidden':'visible');
      rig.eyes.setAttribute('transform', `translate(0 -92) scale(1 ${blink}) translate(0 92)`);
      rig['front-eyes'].setAttribute('transform', `translate(0 -94) scale(1 ${blink}) translate(0 94)`);
      rig['back-eye'].setAttribute('transform',`translate(0 -94) scale(1 ${blink}) translate(0 94)`);
      rig['back-eye'].setAttribute('opacity',String(.3+Math.max(0,expression.look)*.7));
      const joints=PonyRig.arms(actor,origin,sit,floor.time,mode,reduced.matches);
      const armAnchor=sit>.4||action?rig.head:rig.torso;
      if(rig.armsLayer.nextSibling!==armAnchor) rig.rig.insertBefore(rig.armsLayer,armAnchor);
      rig['arm-left'].setAttribute('opacity',String(sit>.1||['front','back'].includes(actor.facing)?1:.35));
      const tilt=action?action.look*4:expression.tilt;
      rig.head.setAttribute('transform',`rotate(${tilt} 0 -65)`);
      rig['front-head'].setAttribute('transform',`rotate(${tilt} 0 -65)`);
      rig['seated-head'].setAttribute('transform',`translate(${expression.look*2} ${expression.nod+expression.breath}) rotate(${tilt*.5+expression.look*3} 0 -65)`);
      rig.torso.setAttribute('transform',`translate(0 -42) scale(1 ${1+expression.breath*.012}) translate(0 42)`);
      for(const pupil of rig.pupils) pupil.setAttribute('transform',`translate(${action?action.look:expression.look*1.3} ${action?action.look*2.5:working ? -1 : 0})`);
      rig.expression.setAttribute('d',working ? 'M20-69L28-69':actor.state==='failed' && floor.time<actor.feedbackUntil ? 'M20-67Q24-71 28-68':'M20-69Q24-65 28-69');
      const legs=PonyRig.legs(actor,sit,reduced.matches);
      for(const side of ['left','right']) {
        const leg=legs[side];
        rig['leg-'+side].setAttribute('transform',`translate(${leg.hip.x-lean/(PonyRig.scale*scaleX)} ${leg.hip.y}) rotate(${leg.angle})`);
      }
      rig.tail.setAttribute('transform',`rotate(${reduced.matches ? 0 : Math.sin(phase*.8)*9+stride*.12} -22 -32)`);
      for(const ear of [rig.ear,rig['back-ear']]) ear.setAttribute('transform',`rotate(${expression.ear} 0 -105)`);
      rig.mane.setAttribute('transform',`rotate(${stride*.07} -8 -96)`);
      for(const side of ['left','right']) {
        let arm=joints[side];
        if(action&&side==='right') arm=PonyRig.doorArm(actor,origin,scaleX,arm,floor.door);
        const nodes=rig.arms[side];
        nodes.line.setAttribute('d',PonyRig.path(arm));
        nodes.elbow.setAttribute('cx',String(arm.elbow.x)); nodes.elbow.setAttribute('cy',String(arm.elbow.y));
        nodes.hoof.setAttribute('cx',String(arm.hoof.x)); nodes.hoof.setAttribute('cy',String(arm.hoof.y));
        nodes.hoof.setAttribute('transform',`rotate(${sit*-8} ${arm.hoof.x} ${arm.hoof.y})`);
      }
      pony.dataset.operation=actor.pose==='seated'?joints.operation.label:actor.pose;
      if(action) {pony.dataset.doorPhase=action.phase;pony.dataset.doorSide=action.side;}
      else {delete pony.dataset.doorPhase;delete pony.dataset.doorSide;}
      pony.dataset.mood=expression.sleep>.5?'打瞌睡':working?'专注工作':actor.pose==='seated'?'放松':'观察环境';
      // Contact coordinates are observable for browser geometry regression checks.
      pony.dataset.contacts=JSON.stringify({left:joints.left.hoof,right:joints.right.hoof,origin,sit});
      rig.scarf.setAttribute('transform',`rotate(${walking?Math.sin(phase-.5)*4:0} -10 -54)`);
      nodes.push({node: avatar, depth: actor.y});
    }
    nodes.sort((a, b) => a.depth - b.depth).forEach((item, index) => { if (world.children[index] !== item.node) world.insertBefore(item.node, world.children[index] || null); });
    const geometry=PonyDoor.geometry(floor.door);
    const polygon=points=>points.map(([x,y],i)=>{const p=geometry.project(x,y);return `${i?'L':'M'}${p.x} ${p.y}`;}).join('')+'Z';
    door.querySelector('.office-door-panel').setAttribute('d',polygon([[8,6],[74,6],[74,122],[8,122]]));
    door.querySelector('.office-door-inset').setAttribute('d',polygon([[14,14],[68,14],[68,60],[14,60]]));
    const operator=floor.actors.find(a=>a.doorAction);
    const visibleSide=operator?.doorAction.side||(floor.doorDirection==='enter'?'outside':'inside');
    for(const handle of door.querySelectorAll('.office-door-handle')) {
      const p=geometry.handle(handle.dataset.doorSide);
      handle.setAttribute('transform',`translate(${p.x} ${p.y-PonyDoor.frame.y}) rotate(${operator?.doorAction.pressed?-12:0})`);
      handle.setAttribute('opacity',handle.dataset.doorSide===visibleSide?'1':'0');
    }
    const passing=floor.actors.some(a=>PonyDoor.portal(a,floor.motion(a.id),floor.door).clipped);
    frontDoor.setAttribute('display',passing?'inline':'none');
    frontDoor.querySelector('use').setAttribute('display','inline');
    portal.dataset.open = String(floor.door > .2);
  }
  function frame(now) {
    raf = 0;
    if (!active || document.hidden) { lastFrame = 0; return; }
    const dt = lastFrame ? Math.min((now - lastFrame) / 1000, .05) : 0; lastFrame = now;
    if (connected) floor.tick(dt, reduced.matches, true);
    for (const actor of floor.actors) if (actor.present && actor.pose === 'seated' && actor.state !== 'running') {
      actor.idleClock = (actor.idleClock || 0) + dt;
      actor.activity = (actor.seed + Math.floor(actor.idleClock/33)) % 5;
    }
    for (const actor of floor.actors) {
      const target=PonyRig.operation({...actor,deviceBlend:undefined},floor.time,PonyScreen.state(actor,floor.time,connected),reduced.matches).mouse;
      const value=actor.deviceBlend||0, delta=target-value;
      actor.deviceBlend=value+Math.sign(delta)*Math.min(Math.abs(delta),dt*1.25);
    }
    draw(); if (now - lastUI > 450) { renderUI(); lastUI = now; }
    raf = requestAnimationFrame(frame);
  }
  function view(name) { active = name === 'analysis'; if (active && !raf) raf = requestAnimationFrame(frame); }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && active) { lastFrame = 0; if (taskId) poll(taskId); if (!raf) raf = requestAnimationFrame(frame); } });
  $('office-show-output').onclick = () => window.Workbench.inspector(true);
  $('office-show-room').onclick = () => window.Workbench.inspector(false);
  window.addEventListener('pagehide', () => { if (raf) cancelAnimationFrame(raf); raf = 0; });
  window.addEventListener('pageshow', () => { lastFrame = 0; if (active && !raf) raf = requestAnimationFrame(frame); });
  reset(); view(document.body.dataset.view || 'analysis');
  return {reset, sync, view, disconnected: () => { connected = false; renderUI(); draw(true); }, snapshot: () => ({taskId, taskState, door: floor.door, actors: floor.actors.map(a => ({id: a.id, present: a.present, pose: a.pose, state: a.state, x: a.x, y: a.y, screen: PonyScreen.state(a, floor.time, connected), taskId: a.taskId, childId:a.childId, activity:a.activity}))})};
})();
