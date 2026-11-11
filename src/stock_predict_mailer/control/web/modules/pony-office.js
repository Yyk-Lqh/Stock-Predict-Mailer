/* Articulated SVG office; backend state is never inferred from animation. */
window.PonyOffice = (() => {
  const {Floor, roles} = PonyFloor, floor = new Floor();
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
  const svg = el('svg', {viewBox: '-65 0 1025 620', role: 'group', 'aria-label': '六个固定工位，主 Agent 与邮件小马常驻，门外设候门区'});
  svg.innerHTML = `<defs><filter id="pony-shadow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="7"/></filter><linearGradient id="pony-desk" x2="0" y2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#dfe2e5"/></linearGradient></defs><rect width="960" height="620" rx="12" class="office-floor"/><path d="M64 580H910" class="office-floor-line"/><text x="76" y="580" class="office-floor-caption">预测 · 证据 · 分析 · 交付</text>`;
  const door = el('g', {transform: 'translate(0 480)'}, '<rect x="1" y="0" width="60" height="108" rx="3" class="office-door-frame"/><rect x="8" y="6" width="46" height="96" fill="#222831"/><g class="office-door-leaf"><path d="M8 6H54V102H8Z"/><circle cx="18" cy="52" r="2" fill="#c3a97a"/><circle cx="45" cy="52" r="2" fill="#c3a97a"/></g><text x="30" y="127" text-anchor="middle" class="office-floor-caption">出入口</text>');
  svg.append(door);
  svg.insertBefore(el('rect',{x:-65,y:465,width:65,height:140,rx:8,fill:'#465361',opacity:.12}),door);
  const world = el('g'); svg.append(world); office.querySelector('.office-stage').append(svg);
  const desks = new Map(), ponies = new Map(), buttons = new Map(), rigs = new Map(), screens = new Map();
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
    const desk = el('g', {transform: `translate(${role.x} ${role.y})`}, `
      <ellipse cx="8" cy="76" rx="109" ry="28" fill="#131820" opacity=".13" filter="url(#pony-shadow)"/>
      <path d="M-98-28L-91 65H-85L-84-28M91-28L85 65H91L99-28" fill="#c8cdd1"/>
      <path d="M52-22H94V57H52Z" fill="#e3e5e7"/><path d="M55-2H91M55 19H91" stroke="#cbd0d4"/>
      <path d="M-105-13H105V12H-105Z" fill="#d3d7da"/><path d="M-105-53H105V3H-105Z" fill="url(#pony-desk)"/>
      <g class="office-keyboard" transform="translate(-4 34)"><path d="M-40-43H30L34-31H-44Z" fill="#b8c5ce" stroke="#8f9eaa"/><path d="M-35-40H25M-37-36H27M-20-42V-33M-5-42V-33M10-42V-33" stroke="#edf4fa" stroke-width="1.5"/></g><g class="office-mouse" transform="translate(-1 34)"><ellipse cx="49" cy="-36" rx="7" ry="5" fill="#9eabb8"/><path d="M49-40V-36" stroke="#e6edf4"/></g>
      <path d="M-8-80H8V-57H-8Z" fill="#c5cbd0"/><path d="M-25-55H25" stroke="#bec5ca" stroke-width="5"/>
      <rect x="-53" y="-121" width="106" height="69" rx="2" fill="#cbd0d4"/>
      <rect x="-48" y="-116" width="96" height="58" rx="1" fill="#101215" class="office-monitor"/>
      <g class="office-screen" visibility="hidden"><rect x="-48" y="-116" width="96" height="58" fill="#79a9e0"/><path d="M-38-104H30M-38-94H20M-38-84H36M-38-74H8" stroke="#eaf4ff" stroke-width="4" opacity=".85"/></g>
      <image class="office-chart-screen" x="-48" y="-116" width="96" height="58" visibility="hidden"/>
      <path d="M-26 38Q0 31 26 38L29 72Q0 83-29 72Z" fill="#d7dce0"/><path d="M-29 53H29L25 64H-25Z" fill="#c8cdd1"/><path d="M0 65V99M0 94L-22 105M0 94L22 105" stroke="#bfc6cb" stroke-width="4"/>
      <text x="0" y="-139" text-anchor="middle" class="office-desk-name">${role.name}</text><circle cx="-63" cy="-143" r="4" fill="${role.color}"/>`);
    desks.set(role.id, desk); world.append(desk);
    if (!role.station) desk.setAttribute('display', 'none');
    const pony = el('g', {role: 'button', tabindex: '0', 'aria-label': `${role.name}小马，查看工作状态`, 'data-pony': role.id});
    pony.innerHTML = PonyRig.markup(role, roles.indexOf(role));
    pony.addEventListener('click', () => choose(role.id));
    pony.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); choose(role.id); } });
    ponies.set(role.id, pony); world.append(pony);
    rigs.set(role.id, Object.fromEntries(['eyes','head','rig','leg-left','leg-right','arm-left','arm-right','scarf','tail','ear','mane','seated-head','back-eye','back-ear'].map(part => [part, pony.querySelector('.pony-'+part)])));
    rigs.get(role.id).pupils = [...pony.querySelectorAll('.pony-pupil')];
    const rig = rigs.get(role.id);
    rig.expression = pony.querySelector('.pony-expression');
    rig.arms = Object.fromEntries(['left','right'].map(side => [side, {
      line: rig['arm-'+side].querySelector('path'), elbow:rig['arm-'+side].querySelector('circle'), hoof:rig['arm-'+side].querySelector('ellipse')
    }]));
    const screen = desk.querySelector('.office-screen');
    screen.replaceChildren(); const screenTitle = el('title'); desk.prepend(screenTitle);
    screens.set(role.id, {node:screen, title:screenTitle, chart:desk.querySelector('.office-chart-screen')});
    const button = document.createElement('button'); button.type = 'button'; button.className = 'office-role-button';
    button.textContent = role.name; button.style.setProperty('--role-color', role.color); button.setAttribute('aria-pressed', 'false'); button.onclick = () => choose(role.id);
    buttons.set(role.id, button); office.querySelector('.office-legend').append(button);
  }
  door.querySelector('circle').classList.add('office-door-handle');
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
      const state = document.createElement('span'); state.textContent = `${captions[actor.state] || actor.state}${actor.present && !['seated', 'absent'].includes(actor.pose) ? ' · ' + ({walking: '前往工位 / 返回', waiting: '等待通行', turning: '对齐工位', sitting: '正在落座', rising: '正在离座'}[actor.pose] || actor.pose) : ''}`;
      const note = document.createElement('small'); note.textContent = actor.state === 'running' || floor.time < actor.feedbackUntil ? actor.last : !actor.present ? '离室 · 场景来访不会启动模型' : actor.pose === 'seated' ? '空闲 · ' + PonyScreen.games[actor.activity % 5] : '办公室活动 · 未启动模型';
      row.append(name, state, note); row.onclick = () => { if (actor.id === 'assistant') window.AnalysisInput?.open('input'); selected = actor.id; renderUI(); }; host.append(row);
    }
  }
  function reset(id = null, restoring = true) {
    taskId = id; replay = restoring; seen = new Set(); taskState = id ? 'submitted' : 'idle'; connected = true; floor.reset();
    terminalFeedback='';
    for (const desk of desks.values()) desk.querySelector('.office-chart-screen').setAttribute('visibility', 'hidden');
    renderUI(); draw();
  }
  function sync(task, events = []) {
    if (task.id !== taskId) reset(task.id, true);
    taskState = task.status.state; connected = true;
    for (const event of events || []) {
      if (seen.has(event.seq)) continue; seen.add(event.seq);
      const id = ['prediction', 'risk', 'advice', 'charts', 'mail'].includes(event.step) ? event.step : 'main';
      if (event.kind === 'step') {
        const actor = floor.actors.find(a => a.id === id);
        const state = event.status === 'running' ? 'running' : event.status;
        actor.taskId = task.id; actor.taskLabel = task.metadata?.request?.subject || task.input?.subject || 'Agent 任务';
        if (event.child_id) actor.childId = event.child_id;
        if (state === 'completed') actor.completedSteps++;
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
        if (event.status === 'running') floor.set('main','running','等待 ' + (floor.actors.find(a => a.id === id).name) + ' 返回');
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
      pony.setAttribute('display', actor.present ? 'inline' : 'none'); pony.setAttribute('tabindex', actor.present ? '0' : '-1');
      const seated = ['seated', 'sitting', 'rising'].includes(actor.pose);
      const motion=floor.motion(actor.id);
      const transition = Math.min(1, (motion?.elapsed || 0) / (actor.pose === 'rising' ? .55 : .7));
      const sit = PonyRig.smooth(actor.pose === 'seated' ? 1 : actor.pose === 'sitting' ? transition : actor.pose === 'rising' ? 1-transition : 0);
      const walking = actor.pose === 'walking' && !reduced.matches;
      const phase = actor.phase, stride = walking ? Math.sin(phase)*23 : 0;
      // Root stays at the seat anchor. Breathing and typing never drag hooves off devices.
      const bob = reduced.matches ? 0 : walking ? Math.abs(Math.sin(phase))*1.7 : Math.sin(phase)*.4*(1-sit);
      const origin={x:actor.x,y:actor.y-bob};
      pony.setAttribute('transform', `translate(${origin.x.toFixed(3)} ${origin.y.toFixed(3)}) scale(${PonyRig.scale})`);
      actor.visualHeading = reduced.matches ? actor.heading : (actor.visualHeading ?? actor.heading) + (actor.heading-(actor.visualHeading ?? actor.heading))*.14;
      rig.rig.setAttribute('transform', `scale(${1*sit+actor.visualHeading*(1-sit)} 1)`);
      rig.head.setAttribute('opacity', String(1-sit));
      rig['seated-head'].setAttribute('opacity', String(sit));
      const blink = !reduced.matches && actor.phase % (7.3+actor.seed*.37) > 7.05+actor.seed*.37 ? .08 : 1;
      rig.eyes.setAttribute('visibility', actor.facing==='back' && walking ? 'hidden':'visible');
      rig.eyes.setAttribute('transform', `translate(0 -85) scale(1 ${blink}) translate(0 85)`);
      rig['back-eye'].setAttribute('transform',`translate(0 -89) scale(1 ${blink}) translate(0 89)`);
      const mode=PonyScreen.state(actor,floor.time,connected);
      const joints=PonyRig.arms(actor,origin,sit,floor.time,mode,reduced.matches);
      const focus=working ? .6 : 1.6;
      const tilt=reduced.matches ? 0 : Math.sin(phase*.42)*focus;
      rig.head.setAttribute('transform',`rotate(${tilt} 0 -65)`);
      rig['seated-head'].setAttribute('transform',`rotate(${tilt*.5} 0 -65) translate(0 ${reduced.matches ? 0 : Math.sin(phase)*.35})`);
      for(const pupil of rig.pupils) pupil.setAttribute('transform',`translate(${reduced.matches ? 0 : Math.sin(phase*.27)} ${working ? -1 : 0})`);
      rig.expression.setAttribute('d',working ? 'M20-69L28-69':actor.state==='failed' && floor.time<actor.feedbackUntil ? 'M20-67Q24-71 28-68':'M20-69Q24-65 28-69');
      rig['leg-left'].setAttribute('transform',`translate(${-sit*2} ${-sit*9}) rotate(${sit*27+stride*(1-sit)} -10 -26)`);
      rig['leg-right'].setAttribute('transform',`translate(${sit*2} ${-sit*9}) rotate(${-sit*27-stride*(1-sit)} 10 -26)`);
      rig.tail.setAttribute('transform',`rotate(${reduced.matches ? 0 : Math.sin(phase*.8)*9+stride*.12} -22 -32)`);
      for(const ear of [rig.ear,rig['back-ear']]) ear.setAttribute('transform',`rotate(${reduced.matches ? 0 : Math.sin(phase*.31)*5} 0 -101)`);
      rig.mane.setAttribute('transform',`rotate(${stride*.07} -8 -96)`);
      for(const side of ['left','right']) {
        let arm=joints[side];
        const opening=actor.pose==='opening'||actor.pose==='door-handle';
        if(opening && side==='right') {
          // The handle contact uses the same fixed-length solver as the devices.
          const exit=Boolean(motion?.exit);
          const heading=exit?-1:1;
          const contact={x:exit?45:18,y:532};
          const goal={x:(contact.x-origin.x)/(PonyRig.scale*heading),y:(contact.y-origin.y)/PonyRig.scale};
          const progress=exit?(motion.handleElapsed||0)/.35:(motion.elapsed-.5)/.3;
          const reach=PonyRig.smooth(progress)*(1-PonyRig.smooth(floor.door/.45));
          arm=PonyRig.solve({x:20,y:-54},{x:arm.hoof.x+(goal.x-arm.hoof.x)*reach,y:arm.hoof.y+(goal.y-arm.hoof.y)*reach},exit?1:-1);
        }
        const nodes=rig.arms[side];
        nodes.line.setAttribute('d',PonyRig.path(arm));
        nodes.elbow.setAttribute('cx',String(arm.elbow.x)); nodes.elbow.setAttribute('cy',String(arm.elbow.y));
        nodes.hoof.setAttribute('cx',String(arm.hoof.x)); nodes.hoof.setAttribute('cy',String(arm.hoof.y));
        nodes.hoof.setAttribute('transform',`rotate(${sit*-8} ${arm.hoof.x} ${arm.hoof.y})`);
      }
      pony.dataset.operation=actor.pose==='seated'?joints.operation.label:actor.pose;
      // Contact coordinates are observable for browser geometry regression checks.
      pony.dataset.contacts=JSON.stringify({left:joints.left.hoof,right:joints.right.hoof,origin,sit});
      rig.scarf.setAttribute('transform',`rotate(${walking?Math.sin(phase-.5)*4:0} -10 -54)`);
      nodes.push({node: pony, depth: actor.y});
    }
    nodes.sort((a, b) => a.depth - b.depth).forEach((item, index) => { if (world.children[index] !== item.node) world.insertBefore(item.node, world.children[index] || null); });
    door.querySelector('.office-door-leaf').setAttribute('transform', `translate(54 0) scale(${1 - floor.door * .85} 1) translate(-54 0)`);
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
