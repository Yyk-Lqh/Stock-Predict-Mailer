/* Articulated SVG office; backend state is never inferred from animation. */
window.PonyOffice = (() => {
  const {Floor, roles} = PonyFloor, floor = new Floor();
  const NS = 'http://www.w3.org/2000/svg';
  let taskId = null, replay = true, seen = new Set(), active = true, connected = true, taskState = 'idle', selected = 'main';
  let lastFrame = 0, raf = 0, lastUI = 0;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const el = (name, attrs = {}, markup = '') => {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (markup) node.innerHTML = markup;
    return node;
  };
  const office = document.createElement('section'); office.className = 'pony-office'; office.setAttribute('aria-label', '小马协作办公室');
  office.innerHTML = `<div class="office-heading"><div><span class="eyebrow">AGENT OFFICE</span><h2>小马办公室</h2></div><span id="office-live" class="hint">等待分析任务</span></div><div class="office-mobile-tabs"><button type="button" id="office-show-room" aria-pressed="true">办公室</button><button type="button" id="office-show-output" aria-pressed="false">进度与报告</button></div><div class="office-stage"></div><div class="office-legend" aria-label="角色选择"></div><p class="office-footnote">围巾标记职责 · 黑屏表示未工作 · 点击小马查看真实进度</p>`;
  $('analysis-title').textContent = '分析工作台';
  $('analysis-title').closest('.page-head').after(office);
  $('workbench-intro').classList.add('office-welcome');
  const svg = el('svg', {viewBox: '0 0 960 620', role: 'group', 'aria-label': '六个固定工位，主 Agent 与邮件小马常驻'});
  svg.innerHTML = `<defs><filter id="pony-shadow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="7"/></filter><linearGradient id="pony-desk" x2="0" y2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#dfe2e5"/></linearGradient></defs><rect width="960" height="620" rx="12" class="office-floor"/><path d="M64 580H910" class="office-floor-line"/><text x="76" y="580" class="office-floor-caption">预测 · 证据 · 分析 · 交付</text>`;
  const door = el('g', {transform: 'translate(0 480)'}, '<rect x="1" y="0" width="60" height="108" rx="3" class="office-door-frame"/><rect x="8" y="6" width="46" height="96" fill="#222831"/><path d="M8 6H54V102H8Z" class="office-door-leaf"/><circle cx="45" cy="58" r="2" fill="#c3a97a"/><text x="30" y="127" text-anchor="middle" class="office-floor-caption">出入口</text>');
  svg.append(door);
  const world = el('g'); svg.append(world); office.querySelector('.office-stage').append(svg);
  const desks = new Map(), ponies = new Map(), buttons = new Map();
  function choose(id) {
    selected = id;
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
      <path d="M-105-45H105V-21H-105Z" fill="#d3d7da"/><path d="M-105-53H105V-29H-105Z" fill="url(#pony-desk)"/>
      <path d="M-40-43H40L34-34H-34Z" fill="#edf0f2" stroke="#cdd2d6"/>
      <path d="M-8-80H8V-57H-8Z" fill="#c5cbd0"/><path d="M-25-55H25" stroke="#bec5ca" stroke-width="5"/>
      <rect x="-53" y="-121" width="106" height="69" rx="2" fill="#cbd0d4"/>
      <rect x="-48" y="-116" width="96" height="58" rx="1" fill="#101215" class="office-monitor"/>
      <g class="office-screen" visibility="hidden"><rect x="-48" y="-116" width="96" height="58" fill="#79a9e0"/><path d="M-38-104H30M-38-94H20M-38-84H36M-38-74H8" stroke="#eaf4ff" stroke-width="4" opacity=".85"/></g>
      <image class="office-chart-screen" x="-48" y="-116" width="96" height="58" visibility="hidden"/>
      <path d="M-27 30H27L31 80H-31Z" fill="#d7dce0"/><path d="M-29 81H29L21 93H-21Z" fill="#c8cdd1"/><path d="M0 92V109M0 105L-22 115M0 105L22 115" stroke="#bfc6cb" stroke-width="4"/>
      <text x="0" y="-139" text-anchor="middle" class="office-desk-name">${role.name}</text><circle cx="-63" cy="-143" r="4" fill="${role.color}"/>`);
    desks.set(role.id, desk); world.append(desk);
    const pony = el('g', {role: 'button', tabindex: '0', 'aria-label': `${role.name}小马，查看工作状态`, 'data-pony': role.id});
    pony.innerHTML = `<title>${role.name}</title><ellipse class="pony-ground" cx="0" cy="-1" rx="29" ry="7" fill="#101820" opacity=".15"/><g class="pony-rig"><g class="pony-leg-left"><path d="M-12-26L-15-9L-24-3L-23 3H-7L-1-25Z" fill="#111315"/></g><g class="pony-leg-right"><path d="M4-26L9-7L5 2H23L24-5L17-27Z" fill="#111315"/></g><path d="M-21-56Q0-69 23-54L25-24Q0-12-24-25Z" fill="#0c0e11"/><path d="M-22-37Q-41-46-33-29L-21-23" fill="#111315" class="pony-tail"/><g class="pony-arm-left"><path d="M-18-54Q-33-53-31-35L-23-29L-13-45Z" fill="#111315"/></g><g class="pony-arm-right"><path d="M17-54Q31-53 33-36L25-29L12-44Z" fill="#111315"/></g><g class="pony-head"><path d="M-22-67Q-28-92-11-102L-9-117L3-105Q18-108 21-94L34-85L29-66L11-62Q-4-57-22-67Z" fill="#090b0d"/><path d="M-26-83L-32-94L-17-96L-23-106L-7-102L1-114L5-101" fill="#090b0d"/><g class="pony-eyes"><ellipse cx="8" cy="-87" rx="6" ry="9" fill="white"/><ellipse cx="23" cy="-83" rx="5" ry="8" fill="white"/><ellipse cx="10" cy="-86" rx="2.8" ry="5" fill="#141820"/><ellipse cx="25" cy="-82" rx="2.4" ry="4.5" fill="#141820"/></g></g><path d="M-23-65Q0-56 23-65L24-55Q0-45-24-56Z" fill="${role.color}"/><path class="pony-scarf" d="M-14-54L-16-32L-5-34L-4-53Z" fill="${role.color}"/></g><circle class="pony-selected" cx="0" cy="-36" r="39" fill="none" stroke="${role.color}" stroke-width="1.5" stroke-dasharray="4 5" visibility="hidden"/>`;
    pony.addEventListener('click', () => choose(role.id));
    pony.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); choose(role.id); } });
    ponies.set(role.id, pony); world.append(pony);
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
    const host = $('office-roles'); host.replaceChildren();
    for (const actor of floor.actors) {
      const row = document.createElement('button'); row.type = 'button'; row.className = 'office-role-state'; row.dataset.officeRole = actor.id;
      row.classList.toggle('selected', selected === actor.id); row.style.setProperty('--role-color', actor.color);
      const name = document.createElement('strong'); name.textContent = actor.name;
      const state = document.createElement('span'); state.textContent = `${captions[actor.state] || actor.state}${actor.present && !['seated', 'absent'].includes(actor.pose) ? ' · ' + ({walking: '前往工位 / 返回', waiting: '等待通行', turning: '对齐工位', sitting: '正在落座', rising: '正在离座'}[actor.pose] || actor.pose) : ''}`;
      const note = document.createElement('small'); note.textContent = actor.last || (actor.resident ? '常驻办公室' : '按实际任务需要参与');
      row.append(name, state, note); row.onclick = () => { selected = actor.id; renderUI(); }; host.append(row);
    }
  }
  function reset(id = null, restoring = true) {
    taskId = id; replay = restoring; seen = new Set(); taskState = id ? 'submitted' : 'idle'; connected = true; floor.reset();
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
        if (replay) { actor.state = state; actor.last = event.label; if (state === 'running') { actor.present = true; actor.pose = 'seated'; } }
        else floor.set(id, state, event.label);
      }
      if (event.kind === 'mail') floor.set('mail', event.status, event.label);
      if (event.kind === 'chart' && event.svg) {
        const screen = desks.get('charts').querySelector('.office-chart-screen'); screen.setAttribute('href', 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(event.svg));
      }
    }
    if (['completed', 'failed', 'canceled'].includes(taskState)) floor.finish(taskState);
    if (replay) for (const actor of floor.actors) if (!actor.resident && actor.state !== 'running') { actor.present = false; actor.pose = 'absent'; }
    if (events && events.length < 100) replay = false;
    renderUI(); draw();
  }
  function draw() {
    const nodes = [];
    for (const actor of floor.actors) {
      const desk = desks.get(actor.id), pony = ponies.get(actor.id);
      const working = connected && actor.state === 'running' && actor.pose === 'seated' && !['completed', 'failed', 'canceled'].includes(taskState);
      desk.querySelector('.office-screen').setAttribute('visibility', working ? 'visible' : 'hidden');
      if (actor.id === 'charts' && desk.querySelector('image').hasAttribute('href')) desk.querySelector('image').setAttribute('visibility', working ? 'visible' : 'hidden');
      nodes.push({node: desk, depth: actor.deskY + 25});
      pony.setAttribute('display', actor.present ? 'inline' : 'none'); pony.setAttribute('tabindex', actor.present ? '0' : '-1');
      const seated = ['seated', 'sitting', 'rising'].includes(actor.pose);
      const transition = Math.min(1, (floor.transit?.id === actor.id ? floor.transit.elapsed : 0) / .4);
      const sit = actor.pose === 'seated' ? 1 : actor.pose === 'sitting' ? transition : actor.pose === 'rising' ? 1 - transition : 0;
      const walking = actor.pose === 'walking' && !reduced.matches;
      const phase = actor.phase, stride = walking ? Math.sin(phase) * 25 : 0;
      const bob = walking ? Math.abs(Math.sin(phase)) * 2 : 0;
      pony.setAttribute('transform', `translate(${actor.x.toFixed(2)} ${(actor.y - bob - (seated ? (1 - sit) * 5 : 0)).toFixed(2)}) scale(.88)`);
      pony.querySelector('.pony-eyes').setAttribute('visibility', sit > .6 ? 'hidden' : 'visible');
      pony.querySelector('.pony-head').setAttribute('transform', `rotate(${working && !reduced.matches ? Math.sin(phase * 4) * 1.4 : 0} 0 -72)`);
      pony.querySelector('.pony-rig').setAttribute('transform', `scale(${seated ? 1 : actor.heading} 1)`);
      pony.querySelector('.pony-leg-left').setAttribute('transform', seated ? `translate(${-2 * sit} ${-8 * sit}) rotate(${40 * sit} -10 -24)` : `rotate(${stride} -10 -26)`);
      pony.querySelector('.pony-leg-right').setAttribute('transform', seated ? `translate(${2 * sit} ${-8 * sit}) rotate(${-40 * sit} 10 -24)` : `rotate(${-stride} 10 -26)`);
      const typing = working && !reduced.matches ? Math.sin(phase * 13) * 5 : 0;
      pony.querySelector('.pony-arm-left').setAttribute('transform', seated ? `rotate(${-95 * sit + typing} -18 -54)` : `rotate(${-stride * .7} -18 -54)`);
      pony.querySelector('.pony-arm-right').setAttribute('transform', seated ? `rotate(${95 * sit + typing} 18 -54)` : `rotate(${stride * .7} 18 -54)`);
      pony.querySelector('.pony-scarf').setAttribute('transform', `rotate(${walking ? Math.sin(phase - .5) * 5 : 0} -10 -54)`);
      pony.querySelector('.pony-selected').setAttribute('visibility', selected === actor.id && actor.present ? 'visible' : 'hidden');
      nodes.push({node: pony, depth: actor.y});
    }
    nodes.sort((a, b) => a.depth - b.depth).forEach((item, index) => { if (world.children[index] !== item.node) world.insertBefore(item.node, world.children[index] || null); });
    door.querySelector('.office-door-leaf').setAttribute('transform', `translate(8 0) scale(${1 - floor.door * .85} 1) translate(-8 0)`);
    portal.dataset.open = String(floor.door > .2);
  }
  function frame(now) {
    raf = 0;
    if (!active || document.hidden) { lastFrame = 0; return; }
    const dt = lastFrame ? Math.min((now - lastFrame) / 1000, .05) : 0; lastFrame = now;
    if (connected) floor.tick(dt, reduced.matches);
    draw(); if (now - lastUI > 450) { renderUI(); lastUI = now; }
    raf = requestAnimationFrame(frame);
  }
  function view(name) { active = name === 'analysis'; if (active && !raf) raf = requestAnimationFrame(frame); }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && active) { lastFrame = 0; if (taskId) poll(taskId); if (!raf) raf = requestAnimationFrame(frame); } });
  $('office-show-output').onclick = () => window.Workbench.inspector(true);
  $('office-show-room').onclick = () => window.Workbench.inspector(false);
  reset(); view(document.body.dataset.view || 'analysis');
  return {reset, sync, view, disconnected: () => { connected = false; renderUI(); draw(); }, snapshot: () => ({taskId, taskState, door: floor.door, actors: floor.actors.map(a => ({id: a.id, present: a.present, pose: a.pose, state: a.state, x: a.x, y: a.y}))})};
})();
