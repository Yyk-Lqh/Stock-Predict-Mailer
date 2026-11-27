/* Stock-Predict-Mailer · 预测分析控制台 */
/* ---------- theme ---------- */
/* One preference drives both the topbar orb and the settings radios: 浅色 / 深色 /
   跟随系统. The choice is stored locally per browser; the rendered attribute is
   always a concrete light|dark so the stylesheet keeps a single contract, and the
   system preference is re-read only while the stored choice is 跟随系统. */
const THEME_KEY = 'stock_predict_mailer.console.theme';
const THEME_MODES = ['light', 'dark', 'system'];
const DEFAULT_THEME = 'light';
const THEME_LABELS = {light: '浅色', dark: '深色'};
const SYSTEM_THEME = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
const THEME_MOTION = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
let themeMode = DEFAULT_THEME;

function systemTheme() { return SYSTEM_THEME && SYSTEM_THEME.matches ? 'dark' : 'light'; }
function resolvedTheme() { return themeMode === 'system' ? systemTheme() : themeMode; }
function themeName(mode) { return mode === 'system' ? '跟随系统' : `固定${THEME_LABELS[mode]}`; }

/* The orb is the only quick switch, so it carries two facts at once: its material
   shows the theme in effect (a pale orb on the graphite page, a deep one on the
   light page) and its label names the stored choice plus what a press would give. */
function syncThemeButton(theme) {
  const button = document.getElementById('theme-toggle');
  if (!button) return;
  const next = THEME_MODES[(THEME_MODES.indexOf(themeMode) + 1) % THEME_MODES.length];
  const current = themeMode === 'system' ? `跟随系统（当前${THEME_LABELS[theme]}）` : `${THEME_LABELS[theme]}主题`;
  button.setAttribute('aria-label', `界面主题：${current}。按下切换为${themeName(next)}。`);
  button.title = `界面主题：${current}｜点击切换为${themeName(next)}`;
}

function applyTheme(mode, options) {
  const {persist = false, announce = false} = options || {};
  themeMode = THEME_MODES.includes(mode) ? mode : DEFAULT_THEME;
  const theme = resolvedTheme();
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.dataset.themeMode = themeMode;
  document.querySelectorAll('[data-theme-choice]').forEach(choice => {
    const selected = choice.dataset.themeChoice === themeMode;
    if (choice.tagName === 'INPUT') choice.checked = selected;
    else choice.setAttribute('aria-pressed', String(selected));
    choice.closest('.theme-option')?.classList.toggle('is-selected', selected);
  });
  syncThemeButton(theme);
  const note = document.getElementById('theme-effective');
  if (note) {
    note.textContent = themeMode === 'system'
      ? `正在跟随系统，当前显示${THEME_LABELS[theme]}；系统切换时会自动调整。`
      : `已固定${THEME_LABELS[theme]}，不随系统变化。`;
  }
  const status = document.getElementById('theme-status');
  if (status && announce) {
    status.textContent = themeMode === 'system'
      ? `已跟随系统，当前${THEME_LABELS[theme]}`
      : `已切换到${THEME_LABELS[theme]}主题`;
  }
  if (persist) {
    try { localStorage.setItem(THEME_KEY, themeMode); } catch (_) { /* Theme still works without storage. */ }
  }
}

const themeToggle = document.getElementById('theme-toggle');
if (themeToggle) {
  themeToggle.addEventListener('click', () => {
    const next = THEME_MODES[(THEME_MODES.indexOf(themeMode) + 1) % THEME_MODES.length];
    applyTheme(next, {persist: true, announce: true});
  });
  /* The eyes lean toward the pointer while it is over the orb; under reduced
     motion they stay centred. Offsets stay under two pixels, so it reads as calm. */
  const orb = themeToggle.querySelector('.theme-orb');
  const gaze = (x, y) => {
    if (!orb) return;
    orb.style.setProperty('--gaze-x', `${x.toFixed(2)}px`);
    orb.style.setProperty('--gaze-y', `${y.toFixed(2)}px`);
  };
  themeToggle.addEventListener('pointermove', event => {
    if (!orb || (THEME_MOTION && THEME_MOTION.matches)) return;
    const rect = orb.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const clamp = value => Math.max(-1, Math.min(1, value));
    gaze(clamp((event.clientX - (rect.left + rect.width / 2)) / (rect.width / 2)) * 1.4,
      clamp((event.clientY - (rect.top + rect.height / 2)) / (rect.height / 2)) * 1.2);
  });
  themeToggle.addEventListener('pointerleave', () => gaze(0, 0));
  themeToggle.addEventListener('blur', () => gaze(0, 0));
}

document.querySelectorAll('[data-theme-choice]').forEach(choice => {
  const pick = () => applyTheme(choice.dataset.themeChoice, {persist: true, announce: true});
  if (choice.tagName === 'INPUT') choice.addEventListener('change', pick);
  else choice.addEventListener('click', pick);
});
try { applyTheme(localStorage.getItem(THEME_KEY)); } catch (_) { applyTheme(DEFAULT_THEME); }
/* Follow the OS only while the user asked us to; an explicit choice wins. */
const followSystem = () => { if (themeMode === 'system') applyTheme('system', {announce: true}); };
if (SYSTEM_THEME) {
  if (SYSTEM_THEME.addEventListener) SYSTEM_THEME.addEventListener('change', followSystem);
  else if (SYSTEM_THEME.addListener) SYSTEM_THEME.addListener(followSystem);
}
window.addEventListener('storage', event => { if (event.key === THEME_KEY) applyTheme(event.newValue); });

/* Occasional blink, so the orb reads as alive without drawing attention. Paused
   for reduced motion and for hidden tabs; the eyes stay put when it is skipped. */
(function startOrbBlink() {
  const orb = document.querySelector('.theme-orb');
  if (!orb) return;
  let timer = 0;
  const schedule = () => {
    clearTimeout(timer);
    orb.classList.remove('is-blinking');
    if ((THEME_MOTION && THEME_MOTION.matches) || document.visibilityState === 'hidden') return;
    timer = setTimeout(() => {
      orb.classList.add('is-blinking');
      timer = setTimeout(() => { orb.classList.remove('is-blinking'); schedule(); }, 140);
    }, 4800 + Math.random() * 5200);
  };
  schedule();
  if (THEME_MOTION) {
    if (THEME_MOTION.addEventListener) THEME_MOTION.addEventListener('change', schedule);
    else if (THEME_MOTION.addListener) THEME_MOTION.addListener(schedule);
  }
  document.addEventListener('visibilitychange', schedule);
})();
const $ = id => document.getElementById(id);
let csrf = '', profiles = [], servers = [], endpoints = [], settings = null, currentTask = null;
let taskControlsDirty = false;
let memoryKey = sessionStorage.getItem('spm_memory_key') || '';
const AnalysisMode = (() => {
  const storage = 'stock_predict_mailer.workspace.';
  let workspace = '', mode = 'standard', epoch = 0, legacy = false;
  const key = (name, scope = mode) => storage + workspace + '.' + scope + '.' + name;
  function read(name, scope = mode) {
    try { return workspace ? JSON.parse(localStorage.getItem(key(name, scope))) : null; } catch (_) { return null; }
  }
  function write(name, value, scope = mode) {
    if (!workspace) return;
    try {
      if (value == null) localStorage.removeItem(key(name, scope));
      else localStorage.setItem(key(name, scope), JSON.stringify(value));
    } catch (_) { /* Local storage is optional. */ }
  }
  function importLegacy(name, scope, oldKeys, parse = JSON.parse) {
    if (!legacy || read('imported.' + name, scope)) return;
    try {
      const value = [oldKeys].flat().map(oldKey => localStorage.getItem(oldKey)).find(item => item != null);
      if (value != null && read(name, scope) == null) write(name, parse(value), scope);
      write('imported.' + name, true, scope);
    } catch (_) { /* An invalid old draft can be ignored. */ }
  }
  function configure(id) {
    workspace = id || 'console';
    try {
      const claim = storage + 'legacy-workspace';
      if (!localStorage.getItem(claim)) localStorage.setItem(claim, workspace);
      legacy = localStorage.getItem(claim) === workspace;
    } catch (_) { /* Storage can be unavailable. */ }
  }
  function activate(value) { mode = value; ++epoch; }
  function capture() { return {mode, epoch, key: memoryKey, knowledgeScope: window.KnowledgeUI?.taskScope() || 'local'}; }
  const current = token => token.mode === mode && token.epoch === epoch && token.key === memoryKey;
  const model = () => read('model') || settings?.agents?.main?.model_id || settings?.default_model_id;
  const tools = () => {
    const allowed = settings?.agents?.main?.tools || [];
    return (read('tools') || allowed).filter(tool => allowed.includes(tool));
  };
  return {read, write, configure, importLegacy, activate, capture, current, model, tools,
    active: () => mode, canImportLegacy: () => legacy};
})();
const taskMode = task => task.metadata?.mode || (task.metadata?.workflow ? 'professional' : task.metadata?.request ? 'standard' : 'legacy');
const displayedTaskMode = () => window.Workbench?.resultMode() || AnalysisMode.active();
const pendingSubmissions = new Set();
const submitErrors = new Map();
const roles = {main: '主 Agent', prediction: '预测分析', risk: '风险分析', advice: '建议生成'};
const TASK_STATE = {submitted: '已提交', working: '运行中', completed: '已完成', failed: '失败', canceled: '已取消'};
const MAIL_STATE = {
  not_requested: '未请求通知', simulated: '模拟投递', submitted: '已提交服务器', retry: '等待重试',
  not_due: '等待到期', failed: '投递失败', uncertain: '结果未知', pending: '待发送', sending: '发送中', partial: '部分投递完成，查看逐邮箱结果'
};
/* 失败任务的解释表：先说人话，再说下一步可点的动作，最后才给错误码。
   宁可少写几条，也不要为了覆盖全部错误码而编造不确定的原因。 */
const ERROR_HELP = {
  MODEL_REQUIRED: {
    title: '还没选默认模型',
    why: '任务在调用模型之前就停下了。分析必须有一个默认模型，否则任何输入都不会开始跑。',
    fix: [{label: '去设置模型', view: 'settings', panel: 'models'}, {label: '用示例跑一遍', sample: true}]
  },
  INVALID_INPUT: {
    title: '提交的内容没通过校验',
    why: '最常见的是标的为空、有效期早于现在、事实缺来源，或置信度不在 0 到 1 之间。修好后重新提交即可。',
    fix: [{label: '回到表单检查', view: 'analysis'}]
  },
  INVALID_PARAMS: {
    title: '请求参数不被支持',
    why: '当前模型或接口不支持其中某个参数，通常来自高级 JSON 里的自定义字段。',
    fix: [{label: '回到表单检查', view: 'analysis'}]
  },
  TASK_TIMEOUT: {
    title: '超过任务时限',
    why: '整个任务跑过了设置里的超时上限。拆细一点、把复杂度改成简单，通常就能跑完。',
    fix: [{label: '改成简单任务重试', view: 'analysis'}]
  },
  CALL_TIMEOUT: {
    title: '上游模型调用超时',
    why: '某一次模型请求没有在时限内返回。这通常是上游抖动，同一份输入重试往往就能过。',
    fix: [{label: '重新提交', view: 'analysis'}]
  },
  BUDGET_EXHAUSTED: {
    title: '触到费用上限',
    why: '这次任务的预估费用超过了设置里的预算上限，系统按约定中止，没有继续花钱。',
    fix: [{label: '去调整预算', view: 'settings', panel: 'settings'}]
  },
  DEPTH_LIMIT: {
    title: '触到分支深度上限',
    why: '子角色还想继续往下拆，但设置里限制了深度。减少拆解层级即可。',
    fix: [{label: '去调整限制', view: 'settings', panel: 'settings'}]
  },
  STEP_LIMIT: {
    title: '触到步数上限',
    why: '任务调用外部工具的次数超过了上限，通常是工具反复失败导致的循环。',
    fix: [{label: '去调整限制', view: 'settings', panel: 'settings'}]
  },
  PERMISSION_DENIED: {
    title: '这一步没有权限',
    why: '可能是收件人不在授权清单里，或当前设置不允许合成数据投递。这不影响报告本身，只影响发送。',
    fix: [{label: '去检查授权', view: 'settings', panel: 'settings'}]
  },
  SECRET_CONFIG: {
    title: '模型的密钥没配好',
    why: '环境变量里没有读到这个模型需要的密钥，所以请求在本地就被拒绝了。',
    fix: [{label: '去设置模型', view: 'settings', panel: 'models'}]
  },
  INVALID_CONFIG: {
    title: '模型配置不被接受',
    why: '模型名、接口地址或参数组合不被上游接受，常见于温度超出范围或模型 ID 拼错。',
    fix: [{label: '去设置模型', view: 'settings', panel: 'models'}]
  },
  PARAMETER_UNSUPPORTED: {
    title: '模型不支持某个参数',
    why: '例如给不支持推理强度的模型传了 effort。把它留空即可。',
    fix: [{label: '去设置模型', view: 'settings', panel: 'models'}]
  },
  NOT_READY: {
    title: '服务还没准备好',
    why: '控制台启动了，但某些依赖还没就绪。稍等片刻再提交通常就好了。',
    fix: [{label: '重新提交', view: 'analysis'}]
  },
  SERVICE_UNAVAILABLE: {
    title: '上游服务不可用',
    why: '模型服务或外部工具暂时连不上。这是外部原因，不是你的输入有问题。',
    fix: [{label: '稍后重新提交', view: 'analysis'}]
  },
  BUSY: {
    title: '这个会话还有任务在收尾',
    why: '同一个会话不允许并发提交。等上一个任务结束，或改用独立任务。',
    fix: [{label: '回到表单', view: 'analysis'}]
  },
  INPUT_TOO_LARGE: {
    title: '输入超过了长度限制',
    why: '预测、事实或会话内容的体积超过上限。删掉一些事实或缩短文本再提交。',
    fix: [{label: '回到表单精简', view: 'analysis'}]
  },
  INTERRUPTED: {
    title: '进程重启打断了任务',
    why: '控制台在任务运行中重启了。系统不会自动重跑，因为可能已经产生过外部效果。',
    fix: [{label: '重新提交', view: 'analysis'}]
  },
  INVALID_AGENT_RESULT: {
    title: '子角色返回的结构不合规',
    why: '某个分析角色给出的结果缺字段，主 Agent 没有采用。多半是模型能力或提示词问题。',
    fix: [{label: '重新提交', view: 'analysis'}]
  },
  INTERNAL_ERROR: {
    title: '内部错误',
    why: '没有预期的异常，报告无法生成。重试一次；如果稳定复现，去看服务端日志里的堆栈。',
    fix: [{label: '重新提交', view: 'analysis'}]
  }
};
const MAIL_NOTE = {
  partial: '各邮箱结果不同，请查看下方逐地址回执；结果未知的邮件不会自动重发。',
  simulated: '文件写入本地目录，不代表对方收到。',
  submitted: '邮件服务器或工具已接受，不保证最终送达。',
  retry: '会在到期后重试；失败次数耗尽才会转为失败。',
  not_due: '还没到重试时间。',
  failed: '确定失败，检查凭据与收件人授权后重新发起。',
  uncertain: '可能已产生外部效果，系统不会自动重发，需要人工确认。',
  not_requested: '本次没有勾选通知，因此没有投递结果。'
};

/* ---------- base ---------- */
let noticeTimer = null;
function notice(message, error = false) {
  const el = $('notice');
  el.textContent = message;
  el.classList.toggle('error', error);
  el.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { el.hidden = true; }, error ? 12000 : 6000);
}
async function api(path, method = 'GET', body, signal, context) {
  const response = await fetch('/api/' + path, {
    method,
    signal,
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'X-Memory-Key': context?.key ?? memoryKey,
      'X-Knowledge-Scope': context?.knowledgeScope || window.KnowledgeUI?.scope() || 'local',
      ...(context?.mode ? {'X-Analysis-Mode': context.mode} : {})},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(`${data.error?.code || response.status} · ${data.error?.message || '请求失败'}`), {status:response.status, issues:data.error?.issues});
  return data;
}
function action(label, fn) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'btn tiny';
  b.textContent = label;
  b.onclick = async () => {
    const scope = AnalysisMode.capture();
    b.disabled = true;
    try { await fn(); } catch (e) { if (AnalysisMode.current(scope)) notice(e.message, true); } finally { b.disabled = false; }
  };
  return b;
}
function text(parent, tag, value, cls) {
  const el = document.createElement(tag);
  el.textContent = value;
  if (cls) el.className = cls;
  parent.append(el);
  return el;
}
const csv = value => value.split(',').map(s => s.trim()).filter(Boolean);
const lines = value => value.split('\n').map(s => s.trim()).filter(Boolean);
/* 收件人授权清单：解析、说人话、报错都用这一份规则。
   概览的「谁能收」和设置页的复述共用它，避免两处对同一条清单给出不同说法。 */
const ADDRESS_RE = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$/;
const allowlistBad = list => list.filter(item => !ADDRESS_RE.test(item));
function allowlistSentence(list, transport = 'file') {
  const bad = allowlistBad(list);
  if (bad.length) {
    const shown = bad.slice(0, 2).join('、') + (bad.length > 2 ? ' 等' : '');
    return {tone: 'danger', text: `${shown} 不像邮箱地址，这样的地址一个都收不到信。`};
  }
  if (!list.length) {
    return transport === 'file'
      ? {tone: '', text: '清单为空：本地文件投递不限制收件人，信只落在工作目录里，不会寄出。'}
      : {tone: 'warn', text: '清单为空：这里不限制，任何地址都能收到报告。换成真实通道后建议逐行填上。'};
  }
  const head = list.slice(0, 2).join('、');
  return {
    tone: '',
    text: list.length <= 2 ? `只寄给 ${head}。` : `只寄给 ${list.length} 个地址：${head} 等，其余一律拦下。`
  };
}
const num = id => Number($(id).value);
function options(select, items, value, emptyText = '继承默认') {
  select.replaceChildren();
  let op = document.createElement('option');
  op.value = '';
  op.textContent = emptyText;
  select.append(op);
  for (const item of items) {
    op = document.createElement('option');
    op.value = item.id;
    op.textContent = item.name + (item.enabled ? '' : '（停用）');
    select.append(op);
  }
  select.value = value || '';
}
function empty(container, message) {
  container.replaceChildren();
  if (message) text(container, 'p', message, 'empty');
}
function isoFromLocal(value) {
  if (!value) return null;
  const date = new Date(value);
  return isNaN(date.getTime()) ? null : date.toISOString();
}
function localInput(date) {
  const pad = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
const fmt = value => {
  const date = new Date(value);
  if (isNaN(date.getTime())) return value || '—';
  return date.toLocaleString('zh-CN', {hour12: false});
};

/* ---------- views ---------- */
function showView(name) {
  document.querySelectorAll('[data-view-pane]').forEach(el => { el.hidden = el.dataset.viewPane !== name; });
  document.querySelectorAll('.nav [data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === name));
  if (location.hash.slice(1) !== name) history.replaceState(null, '', '#' + name);
  window.scrollTo({top: 0});
  if (name === 'overview') renderSteps();
  if (name === 'records' && !recordLoaded) loadRecords();
  if (name === 'records') window.ForecastUI?.load(true);
  window.Workbench?.view(name);
  window.ToolsCenter?.view(name);
}
function showPanel(id) {
  document.querySelectorAll('.view:not([hidden]) .panel').forEach(el => { el.hidden = el.id !== id; });
  document.querySelectorAll('.subnav [data-panel]').forEach(el => el.classList.toggle('active', el.dataset.panel === id));
}
function openToolsFallback(kind, cause) {
  const titles = {mcp: '添加 MCP 服务请求', custom: '创建自定义工具', plugin: '添加插件'};
  const dialog = document.createElement('dialog');
  dialog.className = 'tools-dialog tools-dialog-fallback';
  const header = document.createElement('header'); header.className = 'tools-dialog-head';
  const copy = document.createElement('div');
  text(copy, 'p', '工具中心', 'tools-kicker'); text(copy, 'h2', titles[kind] || '添加工具');
  text(copy, 'p', cause ? `工具中心正在恢复，${cause.message || '请填写并提交表单。'}` : '填写信息后提交。', 'tools-dialog-subtitle');
  const close = document.createElement('button'); close.type = 'button'; close.className = 'tools-dialog-close'; close.textContent = '×'; close.setAttribute('aria-label', '关闭');
  close.onclick = () => dialog.close(); header.append(copy, close); dialog.append(header);
  const form = document.createElement('form'); form.className = 'tools-dialog-form';
  const body = document.createElement('section'); body.className = 'tools-form-section';
  const field = (label, control) => { const wrap = document.createElement('label'); wrap.className = 'tools-field'; text(wrap, 'span', label, 'tools-field-label'); wrap.append(control); return wrap; };
  const input = (type, placeholder) => { const control = document.createElement('input'); control.type = type; control.className = 'tools-input'; control.placeholder = placeholder; return control; };
  const name = input('text', '工具名称'); name.required = true;
  const url = input('url', kind === 'mcp' ? 'https://example.com/mcp' : 'https://github.com/owner/repo'); url.required = true;
  const schema = document.createElement('textarea'); schema.className = 'tools-schema-editor'; schema.rows = 10; schema.placeholder = '输入 OpenAPI 或 Swagger Schema';
  if (kind === 'mcp') { body.append(field('名称', name), field('服务端点 URL', url)); }
  else if (kind === 'plugin') body.append(field('GitHub 仓库地址', url));
  else body.append(field('名称', name), field('OpenAPI Schema', schema));
  const status = document.createElement('p'); status.className = 'tools-dialog-status';
  const footer = document.createElement('footer'); footer.className = 'tools-dialog-foot';
  const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'tools-secondary-button'; cancel.textContent = '取消'; cancel.onclick = () => dialog.close();
  const submit = document.createElement('button'); submit.type = 'submit'; submit.className = 'tools-primary-button'; submit.textContent = kind === 'mcp' ? '添加服务' : kind === 'plugin' ? '添加插件' : '保存工具';
  footer.append(status, document.createElement('span'), cancel, submit); form.append(body, footer); dialog.append(form); document.body.append(dialog);
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => dialog.remove(), {once: true});
  form.addEventListener('submit', async event => {
    event.preventDefault(); submit.disabled = true; status.textContent = '正在保存…';
    try {
      if (kind === 'mcp') await api('mcp', 'POST', {name: name.value.trim(), transport: 'streamable_http', url: url.value.trim(), timeout_seconds: 30, allowed_tools: [], allowed_resources: [], effects: {}});
      else if (kind === 'plugin') await api('plugins/github', 'POST', {url: url.value.trim()});
      else {
        const items = JSON.parse(localStorage.getItem('stock_predict_mailer.tools.center.v1') || '[]');
        items.unshift({id: `custom-${crypto.randomUUID()}`, name: name.value.trim(), icon: 'spark', schemaTitle: name.value.trim(), schemaVersion: '—', tools: [], tags: [], auth: 'none', privacy: '', disclaimer: '', createdAt: new Date().toISOString()});
        localStorage.setItem('stock_predict_mailer.tools.center.v1', JSON.stringify(items));
      }
      await window.refreshConsole?.(); await window.ToolsCenter?.refresh?.();
      status.textContent = '已保存。'; setTimeout(() => dialog.close(), 400);
    } catch (error) { status.textContent = `保存失败。${error.message}`; submit.disabled = false; }
  });
  dialog.showModal(); (kind === 'custom' ? name : url).focus();
  return dialog;
}
globalThis.openToolsFallback = openToolsFallback;
globalThis.openToolsAction = function openToolsAction(kind) {
  try {
    const dialog = window.ToolsCenter?.openAction?.(kind);
    if (dialog) return dialog;
  } catch (error) { return openToolsFallback(kind, error); }
  return openToolsFallback(kind);
};
document.querySelectorAll('.nav [data-view]').forEach(el => { el.onclick = () => showView(el.dataset.view); });
document.querySelectorAll('.subnav [data-panel]').forEach(el => { el.onclick = () => showPanel(el.dataset.panel); });
document.addEventListener('click', event => {
  const goto = event.target.closest('[data-goto]');
  if (goto) {
    showView(goto.dataset.goto);
    if (goto.dataset.panel) showPanel(goto.dataset.panel);
  }
  const toolAction = event.target.closest('[data-tools-action]');
  if (toolAction && !event.defaultPrevented) {
    event.preventDefault();
    globalThis.openToolsAction(toolAction.dataset.toolsAction);
  }
});

/* ---------- load ---------- */
async function refresh() {
  [profiles, servers, endpoints, settings] = await Promise.all([api('models'), api('mcp'), api('agents'), api('settings')]);
  renderModels();
  renderServers();
  renderSettings();
  renderVitals();
  renderSteps();
  loadOverviewTask();
  if ($('workspace-health')) $('workspace-health').textContent = settings.default_model_id ? '分析模型已配置' : '尚未选择分析模型';
  window.DesktopSettings?.refresh();
}
globalThis.refreshConsole = refresh;

/* ---------- models ---------- */
function record(container, title, description) {
  const el = document.createElement('article');
  el.className = 'record';
  text(el, 'h3', title);
  text(el, 'p', description);
  const actions = document.createElement('div');
  actions.className = 'record-actions';
  el.append(actions);
  container.append(el);
  return actions;
}
function renderModels() {
  empty($('model-list'), profiles.length ? '' : '尚未配置模型。添加一个 Mock 模型就能离线跑通全流程。');
  for (const p of profiles) {
    const meta = [
      `${p.provider} / ${p.model}`,
      p.enabled ? '已启用' : '已停用',
      p.has_secret ? '密钥已保存（脱敏）' : '密钥未设置',
      p.supported_parameters.includes('temperature') ? `温度 ${p.temperature_min}–${p.temperature_max}` : '不支持温度'
    ].join(' · ');
    const isDefault = settings.default_model_id === p.id;
    const title = p.name;
    const a = record($('model-list'), title, meta);
    if (isDefault) {
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = '默认';
      $('model-list').lastChild.querySelector('h3').append(tag);
    }
    a.append(
      action('编辑', () => editModel(p)),
      action(matchMedia('(min-width: 761px)').matches && p.provider !== 'mock' ? '测试连接（可能计费）' : '测试连接', async () => {
        try { const result = await api(`models/${p.id}/test`, 'POST', {}); window.DesktopSettings?.modelTest(p, result); notice(result.message); }
        catch (error) { window.DesktopSettings?.modelTest(p, null, error.message); throw error; }
      }),
      action('设为默认', async () => {
        await api('settings', 'PUT', {...settings, default_model_id: p.id});
        await refresh();
        notice('默认模型已更新。');
      }),
      action(p.enabled ? '停用' : '启用', async () => {
        await api(`models/${p.id}`, 'PUT', {...p, enabled: !p.enabled});
        await refresh();
      }),
      action('清除密钥', async () => {
        await api(`models/${p.id}`, 'PUT', {...p, clear_secrets: ['api_key']});
        await refresh();
        notice('模型密钥已清除。');
      }),
      action('删除', async () => {
        if (!window.confirm(`删除模型「${p.name}」？被角色引用的配置需要先解除引用。`)) return;
        await api(`models/${p.id}`, 'DELETE');
        await refresh();
      })
    );
  }
}
function editModel(p, saved = false) {
  if (!saved && window.DesktopSettings?.saving('model')) return;
  $('model-heading').textContent = '编辑模型';
  $('model-id').value = p.id;
  for (const [id, key] of Object.entries({
    'model-name': 'name', 'model-provider': 'provider', 'model-url': 'base_url', 'model-model': 'model',
    'model-timeout': 'timeout_seconds', 'model-retries': 'retries', 'model-temp-min': 'temperature_min',
    'model-temp-max': 'temperature_max', 'model-price-in': 'input_usd_per_million',
    'model-price-out': 'output_usd_per_million'
  })) $(id).value = p[key] ?? '';
  $('model-key').value = '';
  $('model-temperature').checked = p.supported_parameters.includes('temperature');
  $('model-supported').value = p.supported_parameters.filter(k => k !== 'temperature').join(',');
  $('model-params').value = JSON.stringify(p.parameters, null, 2);
  $('model-effort-map').value = JSON.stringify(p.reasoning_effort_map || {}, null, 2);
  window.DesktopSettings?.modelFields();
}
$('model-new').onclick = () => {
  $('model-form').reset();
  $('model-id').value = '';
  $('model-heading').textContent = '添加模型';
  window.DesktopSettings?.modelFields();
};
$('model-form').onsubmit = async event => {
  event.preventDefault();
  if (window.DesktopSettings && !window.DesktopSettings.beginSave('model')) return;
  try {
    const id = $('model-id').value;
    const old = profiles.find(p => p.id === id);
    const supported = csv($('model-supported').value).filter(k => k !== 'temperature');
    if ($('model-temperature').checked) supported.push('temperature');
    const body = {
      name: $('model-name').value, provider: $('model-provider').value, base_url: $('model-url').value,
      model: $('model-model').value, timeout_seconds: num('model-timeout'), retries: num('model-retries'),
      supported_parameters: supported, temperature_min: num('model-temp-min'), temperature_max: num('model-temp-max'),
      parameters: JSON.parse($('model-params').value), reasoning_effort_map: JSON.parse($('model-effort-map').value),
      input_usd_per_million: $('model-price-in').value === '' ? null : num('model-price-in'),
      output_usd_per_million: $('model-price-out').value === '' ? null : num('model-price-out'),
      api_key: $('model-key').value, enabled: old?.enabled ?? true
    };
    if (window.DesktopSettings?.mockMode()) {
      for (const field of ['base_url', 'api_key', 'input_usd_per_million', 'output_usd_per_million']) delete body[field];
      if (old) for (const field of ['base_url', 'input_usd_per_million', 'output_usd_per_million']) body[field] = old[field];
    }
    const saved = await api('models' + (id ? '/' + id : ''), id ? 'PUT' : 'POST', body);
    $('model-key').value = '';
    window.DesktopSettings?.modelSaved(saved);
    await refresh();
    notice('模型已保存。密钥不会回显。');
  } catch (error) { window.DesktopSettings?.modelError(error.message); notice(error.message, true); }
  finally { window.DesktopSettings?.endSave('model'); }
};

/* ---------- MCP data ---------- */
// MCP configuration is managed by the tools center. The settings page still
// reads this collection to populate the mail transport selector and role
// summaries, so refresh keeps the server data in memory without rendering a
// second editor.
function renderServers() {}

/* ---------- settings ---------- */
function renderSettings() {
  window.ComposerControls?.update();
  options($('default-model'), profiles, settings.default_model_id, '请选择默认模型');
  $('global-temperature').value = settings.global_temperature;
  $('default-effort').value = settings.default_reasoning_effort;
  $('chart-delivery').value = settings.mail.chart_delivery;

  const container = $('role-settings');
  container.replaceChildren();
  for (const [role, title] of Object.entries(roles)) {
    const row = document.createElement('div');
    row.className = 'role-row';
    text(row, 'h3', title);
    const grid = document.createElement('div');
    grid.className = 'grid-4';
    row.append(grid);
    for (const [field, label, items] of [['model_id', '使用模型', profiles], ['endpoint_id', 'A2A 对端', endpoints]]) {
      const wrap = document.createElement('label');
      wrap.className = 'field';
      text(wrap, 'span', label);
      const select = document.createElement('select');
      select.id = `role-${role}-${field}`;
      options(select, items, settings.agents[role][field], field === 'model_id' ? '继承默认模型' : '本机运行');
      if (role === 'main' && field === 'endpoint_id') select.disabled = true;
      wrap.append(select);
      grid.append(wrap);
    }
    const tempWrap = document.createElement('label');
    tempWrap.className = 'field';
    text(tempWrap, 'span', '温度覆盖');
    const input = document.createElement('input');
    input.type = 'number'; input.min = '0'; input.max = '2'; input.step = '.1';
    input.placeholder = '继承';
    input.id = `role-${role}-temperature`;
    input.value = settings.agents[role].temperature ?? '';
    tempWrap.append(input);
    grid.append(tempWrap);

    const toolWrap = document.createElement('label');
    toolWrap.className = 'field';
    text(toolWrap, 'span', '读取工具');
    const ti = document.createElement('input');
    ti.id = `role-${role}-tools`;
    ti.value = settings.agents[role].tools.join(',');
    ti.disabled = role !== 'main';
    ti.placeholder = servers[0] ? `${servers[0].id}:get_context` : '先添加 MCP 服务';
    toolWrap.append(ti);
    grid.append(toolWrap);
    container.append(row);

    const update = () => {
      const m = profiles.find(p => p.id === (row.querySelector('select').value || settings.default_model_id));
      input.disabled = !!m && !m.supported_parameters.includes('temperature');
      input.title = input.disabled ? '此模型不支持温度；清除旧覆盖后保存。' : '留空继承';
      if (m) { input.min = m.temperature_min; input.max = m.temperature_max; }
    };
    row.querySelector('select').onchange = update;
    update();
  }

  for (const [key, value] of Object.entries(settings.limits)) $('limit-' + key).value = value;
  const m = settings.mail;
  for (const key of ['transport', 'sender', 'host', 'port', 'tls']) $('mail-' + key).value = m[key];
  $('mail-allowlist').value = m.recipient_allowlist.join('\n');
  $('mail-synthetic').checked = m.allow_synthetic;
  options($('mail-mcp-server'), servers, m.mcp_server_id, '未选择邮件服务');
  $('mail-mcp-tool').value = m.mcp_tool || '';

  empty($('endpoint-list'), endpoints.length ? '' : '尚未配置外部 Agent。');
  for (const ep of endpoints) {
    const a = record($('endpoint-list'), ep.name, ep.url);
    a.append(
      action('编辑', () => {
        $('endpoint-id').value = ep.id;
        $('endpoint-name').value = ep.name;
        $('endpoint-url').value = ep.url;
        $('endpoint-cost').value = ep.cost_ceiling_usd;
        $('endpoint-token').value = '';
      }),
      action(ep.enabled ? '停用' : '启用', async () => {
        await api(`agents/${ep.id}`, 'PUT', {...ep, enabled: !ep.enabled});
        await refresh();
      }),
      action('删除', async () => {
        await api(`agents/${ep.id}`, 'DELETE');
        await refresh();
      })
    );
  }
  restoreSettingsEdits();
  renderAllowlist();
}
$('endpoint-save').onclick = async () => {
  try {
    const id = $('endpoint-id').value;
    const old = endpoints.find(e => e.id === id);
    await api('agents' + (id ? '/' + id : ''), id ? 'PUT' : 'POST', {
      name: $('endpoint-name').value, url: $('endpoint-url').value,
      cost_ceiling_usd: num('endpoint-cost'), auth_token: $('endpoint-token').value,
      enabled: old?.enabled ?? true
    });
    $('endpoint-id').value = '';
    $('endpoint-token').value = '';
    await refresh();
    notice('外部 Agent 已保存。');
  } catch (error) { notice(error.message, true); }
};
/* 设置页的复述：把清单与 synthetic 开关合成两句话，回答「谁能收、能收什么」。 */
function renderAllowlist() {
  const host = $('allowlist-summary');
  if (!host) return;
  const sentence = allowlistSentence(lines($('mail-allowlist').value), $('mail-transport').value);
  host.className = 'allow-sum' + (sentence.tone ? ' ' + sentence.tone : '');
  host.replaceChildren(document.createTextNode(sentence.text));
  const synth = document.createElement('span');
  synth.className = 'allow-sub';
  synth.textContent = $('mail-synthetic').checked
    ? '带 synthetic 标记的报告可以寄出。'
    : '带 synthetic 标记的报告会被拦下，只留在本地。';
  host.append(synth);
}
$('mail-allowlist').addEventListener('input', renderAllowlist);
$('mail-synthetic').addEventListener('change', renderAllowlist);
$('mail-transport').addEventListener('change', renderAllowlist);

$('settings-form').onsubmit = async event => {
  event.preventDefault();
  try {
    const allow = lines($('mail-allowlist').value);
    const bad = allowlistBad(allow);
    if (bad.length) {
      notice(`${bad.slice(0, 2).join('、')}${bad.length > 2 ? ' 等' : ''} 不像邮箱地址，改好再保存。`, true);
      $('mail-allowlist').focus();
      return;
    }
    const value = structuredClone(settings);
    value.default_model_id = $('default-model').value || null;
    value.global_temperature = num('global-temperature');
    value.default_reasoning_effort = $('default-effort').value;
    value.mail.chart_delivery = $('chart-delivery').value;
    for (const role of Object.keys(roles)) {
      const temp = $(`role-${role}-temperature`);
      value.agents[role] = {
        model_id: $(`role-${role}-model_id`).value || null,
        endpoint_id: role === 'main' ? null : ($(`role-${role}-endpoint_id`).value || null),
        temperature: temp.disabled || temp.value === '' ? null : Number(temp.value),
        tools: role === 'main' ? csv($(`role-${role}-tools`).value) : []
      };
    }
    for (const key of Object.keys(value.limits)) value.limits[key] = num('limit-' + key);
    const m = value.mail;
    for (const key of ['transport', 'sender', 'host', 'tls']) m[key] = $('mail-' + key).value;
    m.port = num('mail-port');
    m.recipient_allowlist = allow;
    m.allow_synthetic = $('mail-synthetic').checked;
    m.mcp_server_id = $('mail-mcp-server').value || null;
    m.mcp_tool = $('mail-mcp-tool').value || null;
    await api('settings', 'PUT', value);
    clearSettingsEdits();
    await refresh();
    notice('设置已保存。');
  } catch (error) { notice(error.message, true); }
};
$('reset-temperature').onclick = async () => {
  try {
    await api('settings/reset-temperature', 'POST', {});
    clearSettingsEdits();
    await refresh();
    notice('全局温度已恢复 0.2，角色覆盖已清空。');
  } catch (error) { notice(error.message, true); }
};

/* ---------- settings unsaved guard ---------- */
// 任何一次 refresh() 都会重绘角色行与下拉，必须把用户没保存的编辑原样放回。
let settingsDirty = false;
const settingsEdits = new Map();
const ENDPOINT_FIELDS = new Set(['endpoint-id', 'endpoint-name', 'endpoint-url', 'endpoint-token', 'endpoint-cost']);
function markSettingsDirty(event) {
  const el = event.target;
  if (!el.id || ENDPOINT_FIELDS.has(el.id)) return;
  settingsEdits.set(el.id, el.type === 'checkbox' ? el.checked : el.value);
  if (!settingsDirty) {
    settingsDirty = true;
    $('settings-dirty').hidden = false;
  }
}
$('settings-form').addEventListener('input', markSettingsDirty);
$('settings-form').addEventListener('change', markSettingsDirty);
function restoreSettingsEdits() {
  if (!settingsDirty) return;
  for (const [id, value] of settingsEdits) {
    const el = $(id);
    if (!el) continue;
    if (el.type === 'checkbox') el.checked = value;
    else el.value = value;
  }
}
function clearSettingsEdits() {
  settingsDirty = false;
  settingsEdits.clear();
  $('settings-dirty').hidden = true;
}
window.addEventListener('beforeunload', event => {
  if (!settingsDirty) return;
  event.preventDefault();
  event.returnValue = '';
});

/* ---------- 三步进度 ---------- */
/* 每一步的完成态都从真实状态派生，不靠用户手动勾：
   模型看 default_model_id，预测看表单当前值，报告看最近一次任务。 */
let overviewTask = null;
function draftBrief() {
  const subject = ($('p-subject').value || '').trim();
  if (!subject) return {done: false, meta: '还没填标的代码。填上之后这一步会自动打勾。'};
  const until = isoFromLocal($('p-valid-until').value);
  if (!until) return {done: false, meta: '有效期是空的，提交会被校验拒绝。'};
  if (new Date(until) <= new Date()) return {done: false, meta: '有效期已经过了，需要往后调一天。'};
  const direction = numericPrediction ? `${numericPrediction.value} ${numericPrediction.value_unit}` : {up: '上涨', down: '下跌', flat: '持平'}[currentDirection()];
  if (!direction) return {done: false, meta: '请按上游预测选择本轮方向。'};
  const horizon = horizonText({value: Number($('p-horizon-value').value) || 0, unit: $('p-horizon-unit').value});
  const named = facts.filter(fact => (fact.name || '').trim()).length;
  return {done: true, meta: `${subject} · ${direction} · ${horizon} · `
    + (named ? `${named} 条客观事实` : '未附客观事实')};
}
function renderSteps() {
  const host = $('steps');
  if (!host || !settings) return;
  const model = profiles.find(profile => profile.id === settings.default_model_id);
  const draft = draftBrief();
  const task = overviewTask;
  const state = task?.status?.state || '';
  const error = task?.metadata?.error?.code;
  const steps = [
    {
      done: Boolean(model && model.enabled),
      title: '有一个默认模型',
      meta: model
        ? (model.enabled ? `已选用 ${model.name} · ${model.provider}/${model.model}`
          : `${model.name} 已停用，任务会停在调用模型之前。`)
        : '还没有默认模型。可以先用 Mock 模型离线跑通，之后再换成真实模型。',
      action: {label: model && model.enabled ? '更换模型' : '去配置模型', view: 'settings', panel: 'models'}
    },
    {
      done: draft.done,
      title: '填一份预测',
      meta: draft.meta,
      action: {label: draft.done ? '继续编辑' : '去填写', view: 'analysis'}
    },
    {
      done: state === 'completed',
      title: '拿到一份报告',
      meta: task
        ? `${shortTime(task.status.timestamp)} · ${TASK_STATE[state] || state}`
          + (error ? ` · ${error}` : '') + (task.metadata?.request?.subject ? ` · ${task.metadata.request.subject}` : '')
        : '还没有跑过任务。跑完一次，这里会显示最近一次的结果。',
      action: state === 'completed' ? {label: '查看报告', open: task} : {label: '去跑一次', view: 'analysis'}
    }
  ];
  const doneCount = steps.filter(step => step.done).length;
  const next = steps.findIndex(step => !step.done);
  $('steps-count').textContent = `${doneCount} / 3 已完成`;
  host.replaceChildren();
  steps.forEach((step, index) => {
    const row = document.createElement('li');
    if (step.done) row.dataset.done = 'true';
    if (index === next) row.dataset.current = 'true';
    const mark = text(row, 'span', step.done ? '✓' : String(index + 1), 'mark');
    mark.setAttribute('aria-hidden', 'true');
    const body = document.createElement('span');
    body.className = 'body';
    text(body, 'b', step.title);
    text(body, 'span', step.meta, 'meta');
    row.append(body);
    const cell = document.createElement('span');
    cell.className = 'go';
    const button = text(cell, 'button', step.action.label, 'btn tiny ' + (index === next ? 'primary' : 'quiet'));
    button.type = 'button';
    if (step.action.open) button.onclick = () => openRecord(step.action.open);
    else {
      button.dataset.goto = step.action.view;
      if (step.action.panel) button.dataset.panel = step.action.panel;
    }
    row.append(cell);
    host.append(row);
  });
}
async function loadOverviewTask() {
  try {
    // 取几条再挑主任务：最新一条很可能是刚跑完的子 Agent 任务。
    const page = await api('tasks?order=desc&limit=5');
    overviewTask = page.items.find(topLevel) || null;
  } catch (error) {
    overviewTask = null;
  }
  renderSteps();
}

/* ---------- vitals ---------- */
function renderVitals() {
  const host = $('vitals');
  host.replaceChildren();
  const defaultModel = profiles.find(p => p.id === settings.default_model_id);
  const tools = servers.reduce((n, s) => n + s.allowed_tools.length, 0);
  const transport = {file: '本地文件（模拟，不会真的寄出）', smtp: 'SMTP', mcp: 'MCP 邮件工具'}[settings.mail.transport] || settings.mail.transport;
  const allow = allowlistSentence(settings.mail.recipient_allowlist, settings.mail.transport);
  const rows = [
    ['默认模型', defaultModel ? defaultModel.name : '未配置', defaultModel ? 'ok' : 'warn', defaultModel ? '' : '分析前必须先有模型', defaultModel ? null : 'models'],
    ['工具中心', servers.length ? `${servers.length} 个 MCP 服务 · ${tools} 个工具已授权` : '未连接', servers.length ? 'ok' : 'off', servers.length ? '' : '可选，不连接也能分析', 'tools'],
    ['邮件通道', transport, allow.tone ? 'warn' : 'ok', allow.text, allow.tone === 'danger' ? 'settings' : null],
    ['上游数据', '通过本页填写', 'ok', '控制台不做定时拉取', null]
  ];
  for (const [label, value, dot, flag, goto] of rows) {
    const row = document.createElement('div');
    row.className = 'vital';
    text(row, 'span', label, 'label');
    const val = document.createElement('span');
    val.className = 'value';
    const d = document.createElement('i');
    d.className = 'dot ' + dot;
    val.append(d, document.createTextNode(value));
    row.append(val);
    const right = document.createElement('span');
    right.className = 'flag';
    right.textContent = flag;
    if (goto) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn quiet tiny';
      b.dataset.goto = 'settings';
      b.dataset.panel = goto;
      b.textContent = '去设置 →';
      right.append(b);
    }
    row.append(right);
    host.append(row);
  }
}

/* ---------- facts editor ---------- */
let facts = [];
function factRow(fact, index) {
  const row = document.createElement('div');
  row.className = 'fact-row';
  row.dataset.index = index;
  const id = text(row, 'span', fact.id, 'fid');
  id.title = '事实编号，报告里用它引用';
  const make = (key, type, placeholder) => {
    const input = document.createElement('input');
    input.value = fact[key] ?? '';
    input.type = type;
    input.placeholder = placeholder;
    input.oninput = () => { fact[key] = input.value; syncJSON(); };
    return input;
  };
  row.append(make('name', 'text', '名称，如收盘价'));
  row.append(make('value', 'text', '数值'));
  row.append(make('unit', 'text', '单位'));
  row.append(make('source', 'text', '来源，如行情快照'));
  const time = make('observed_at', 'datetime-local', '');
  time.value = localInput(new Date(fact.observed_at || Date.now()));
  time.onchange = () => {
    fact.observed_at = isoFromLocal(time.value);
    fact.available_at = fact.observed_at;
    syncJSON();
  };
  row.append(time);
  const drop = document.createElement('button');
  drop.type = 'button';
  drop.className = 'drop';
  drop.title = '删除这条事实';
  drop.textContent = '×';
  drop.onclick = () => {
    facts = facts.filter(f => f !== fact);
    renderFacts();
    syncJSON();
  };
  row.append(drop);
  return row;
}
function renderFacts() {
  const host = $('facts');
  host.replaceChildren();
  if (!facts.length) {
    text(host, 'p', '还没有客观事实。分析会明确写出「缺少客观事实」。', 'facts-empty');
  } else {
    const head = document.createElement('div');
    head.className = 'fact-row fact-head';
    for (const label of ['编号', '名称', '数值', '单位', '来源', '观测时间', '']) head.append(text(document.createElement('span'), 'span', label));
    host.append(head);
    for (const [i, fact] of facts.entries()) host.append(factRow(fact, i));
  }
  $('fact-count').textContent = `${facts.length} 条`;
}
$('fact-add').onclick = () => {
  const now = new Date().toISOString();
  facts.push({id: `F-${String(facts.length + 1).padStart(2, '0')}`, name: '', value: '', unit: '', source: '', observed_at: now, available_at: now});
  renderFacts();
  syncJSON();
};

/* ---------- task form ---------- */
function currentDirection() {
  return document.querySelector('#p-direction input:checked')?.value;
}
function setDirection(value) {
  document.querySelectorAll('#p-direction input').forEach(input => { input.checked = input.value === value; });
}
function resetTiming() {
  const now = new Date();
  now.setSeconds(0, 0);
  $('p-valid-until').value = localInput(new Date(now.getTime() + 2 * 86400000));
}
function sample() {
  const generated = new Date();
  generated.setMinutes(0, 0, 0);
  const at = offset => {
    let time = generated.getTime();
    let remaining = Math.abs(offset);
    while (remaining) {
      time += Math.sign(offset) * 86400000;
      const weekday = new Date(time).getUTCDay();
      if (weekday !== 0 && weekday !== 6) remaining--;
    }
    return new Date(time).toISOString();
  };
  const prediction = {
    schema_version: '1', prediction_id: 'console-mock-' + generated.toISOString(), subject: 'DEMO.SZ',
    generated_at: generated.toISOString(), valid_until: at(2), horizon: {value: 5, unit: 'trading_days'},
    direction: 'up', value: 11.2, value_unit: 'CNY', confidence: null, model_version: 'mock-v1',
    synthetic: true, metrics: {}
  };
  const observed = Array.from({length: 12}, (_, i) => ({at: at(i - 12), value: 9.4 + i * .09}));
  const forecast = [1, 3, 5].map((offset, i) => ({at: at(offset), value: [10.6, 10.9, 11.2][i], lower: 10 + i * .15, upper: 11.3 + i * .2}));
  const backtest = observed.slice(-6).map((point, i) => ({at: point.at, issued_at: at(i - 7), value: point.value + .08}));
  const chart_data = {
    unit: 'CNY',
    series: {
      observed: {source: 'Mock 历史数据', points: observed},
      forecast: {source: 'Mock 上游模型', points: forecast},
      backtest: {source: 'Mock 历史预测', points: backtest}
    }
  };
  const factsSample = [
    {id: 'F-01', name: '示例价格', value: 10.58, unit: 'CNY', source: 'Mock 行情快照', observed_at: generated.toISOString(), available_at: generated.toISOString()},
    {id: 'F-02', name: '示例成交量', value: 32000, unit: '手', source: 'Mock 行情快照', observed_at: generated.toISOString(), available_at: generated.toISOString()}
  ];
  return {
    prediction,
    context: {schema_version: '1', context_id: 'console-demo', subject: 'DEMO.SZ', facts: factsSample},
    chart_data
  };
}
function applySample() {
  setNumericPrediction(null);
  const data = sample();
  $('p-subject').value = data.prediction.subject;
  $('p-model-version').value = data.prediction.model_version;
  setDirection(data.prediction.direction);
  $('p-horizon-value').value = data.prediction.horizon.value;
  $('p-horizon-unit').value = data.prediction.horizon.unit;
  $('p-confidence').value = '';
  $('p-valid-until').value = localInput(new Date(data.prediction.valid_until));
  $('p-synthetic').checked = true;
  facts = data.context.facts.map(f => ({...f}));
  renderFacts();
  $('task-data').value = JSON.stringify(data, null, 2);
  window.ForecastUI?.restore(data);
}
function readPrediction() {
  const subject = $('p-subject').value.trim();
  const confidence = $('p-confidence').value;
  const value = Number($('p-horizon-value').value);
  const generated = new Date();
  generated.setSeconds(0, 0);
  return {
    schema_version: '1',
    prediction_id: 'console-' + generated.toISOString(),
    subject,
    generated_at: generated.toISOString(),
    valid_until: isoFromLocal($('p-valid-until').value) || new Date(generated.getTime() + 2 * 86400000).toISOString(),
    horizon: {value: Number.isInteger(value) ? value : parseInt(value, 10) || 5, unit: $('p-horizon-unit').value},
    direction: currentDirection(),
    confidence: confidence === '' ? null : Number(confidence),
    model_version: $('p-model-version').value.trim(),
    synthetic: $('p-synthetic').checked,
    metrics: {}
  };
}
let numericPrediction = null;
function setNumericPrediction(prediction) {
  numericPrediction = Number.isFinite(prediction?.value) && !prediction.direction ? prediction : null;
  const status = $('numeric-prediction');
  status.hidden = !numericPrediction;
  status.textContent = numericPrediction ? `${numericPrediction.value} · ${numericPrediction.value_unit}。重新导入可更新预测。` : '';
  document.querySelectorAll('#prediction-editor [id^="p-"], #prediction-editor input[name="p-dir"]').forEach(field => {
    if (field.matches('input, select')) field.disabled = Boolean(numericPrediction);
  });
}
function syncJSON() {
  let chart = null;
  try {
    const previous = JSON.parse($('task-data').value || '{}');
    chart = previous.chart_data || null;
  } catch (error) { chart = null; }
  const prediction = numericPrediction || readPrediction();
  const payload = {prediction, context: facts.length ? {
    schema_version: '1',
    context_id: 'console-ctx',
    subject: prediction.subject,
    facts: facts.map(f => ({
      id: f.id, name: f.name, value: Number.isNaN(Number(f.value)) || f.value === '' ? String(f.value) : Number(f.value),
      unit: f.unit, source: f.source,
      observed_at: f.observed_at || new Date().toISOString(),
      available_at: f.available_at || f.observed_at || new Date().toISOString()
    }))
  } : null};
  if (chart) payload.chart_data = chart;
  $('task-data').value = JSON.stringify(payload, null, 2);
  window.ForecastUI?.restore(payload);
}
function syncForm(quiet = false) {
  let data;
  try { data = JSON.parse($('task-data').value); } catch (error) { throw new Error('JSON 无法解析：' + error.message); }
  const p = data.prediction;
  if (!p) throw new Error('JSON 里没有 prediction 对象');
  $('p-subject').value = p.subject ?? '';
  $('p-model-version').value = p.model_version ?? '';
  setDirection(p.direction || '');
  $('p-horizon-value').value = p.horizon?.value ?? 5;
  $('p-horizon-unit').value = p.horizon?.unit ?? 'trading_days';
  $('p-confidence').value = p.confidence ?? '';
  $('p-valid-until').value = p.valid_until ? localInput(new Date(p.valid_until)) : '';
  $('p-synthetic').checked = Boolean(p.synthetic);
  facts = (data.context?.facts || []).map(f => ({...f}));
  renderFacts();
  setNumericPrediction(p);
  window.ForecastUI?.restore(data);
  if (!quiet) notice('已按 JSON 回填表单。');
}
document.querySelectorAll('#task-form input, #task-form select').forEach(el => {
  if (!el.id.startsWith('p-') && el.name !== 'p-dir') return;
  el.addEventListener('change', syncJSON);
  el.addEventListener('input', event => {
    if (event.target.type === 'number' || event.target.type === 'text' || event.target.type === 'email') syncJSON();
  });
});
$('form-to-json').onclick = () => { syncJSON(); notice('已用表单内容覆盖 JSON。'); };
$('json-to-form').onclick = () => { try { syncForm(); } catch (error) { notice(error.message, true); } };
$('prediction-import').onchange = async event => {
  const field = event.currentTarget, file = field.files[0];
  if (!file) return;
  const selected = $('conversation-id').value;
  const scope = AnalysisMode.capture();
  try {
    if (file.size > 1024 * 1024) throw new Error('预测文件须小于 1 MiB。');
    const prediction = JSON.parse(await file.text());
    if (!AnalysisMode.current(scope) || selected !== $('conversation-id').value) return;
    if (prediction?.schema_version !== '1' || typeof prediction.subject !== 'string' || !prediction.subject.trim() ||
        !prediction.horizon || !(Date.parse(prediction.valid_until) > Date.now()) ||
        (!Number.isFinite(prediction.value) && !['up', 'down', 'flat'].includes(prediction.direction))) {
      throw new Error('请选择有效期内的 v1 预测文件。');
    }
    const previous = JSON.parse($('task-data').value || '{}');
    const context = previous.context?.subject === prediction.subject ? previous.context : null;
    $('task-data').value = JSON.stringify({prediction, context}, null, 2);
    syncForm(true);
    draftSchedule();
    window.AnalysisInput?.update();
    notice('预测已导入，请填写分析问题并发送。');
  } catch (error) { if (AnalysisMode.current(scope)) notice(error.message, true); }
  finally { field.value = ''; }
};
$('load-mock').onclick = () => { applySample(); notice('已填入示例预测与两条事实，可以直接提交。'); };

/* ---------- reusable prediction defaults ---------- */
const PREDICTION_TEMPLATE_KEY = 'stock_predict_mailer.console.prediction_template.v1';
const PREDICTION_TEMPLATE_DEFAULTS = {
  'p-model-version': '',
  'p-horizon-value': '5',
  'p-horizon-unit': 'trading_days',
  'task-complexity': 'auto',
  'task-goal': 'overview',
  'task-effort': '',
  'conversation-format': '',
};
function validTemplateHorizon(value) {
  const length = Number(value);
  return Number.isInteger(length) && length >= 1 && length <= 365;
}
function readPredictionTemplate() {
  try {
    const saved = AnalysisMode.read('template');
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return null;
    const template = {...PREDICTION_TEMPLATE_DEFAULTS};
    for (const id of Object.keys(template)) {
      const value = saved[id], field = $(id);
      if (typeof value !== 'string') continue;
      if (id === 'p-horizon-value' && !validTemplateHorizon(value)) continue;
      if (field.options && !Array.from(field.options).some(option => option.value === value)) continue;
      template[id] = value;
    }
    return template;
  } catch (_) { return null; }
}
function updatePredictionTemplate() {
  const template = readPredictionTemplate();
  $('prediction-template-label').textContent = `填写模板 · ${template ? '我的默认' : '系统默认'}`;
  $('prediction-template-reset').disabled = !template;
  return template || PREDICTION_TEMPLATE_DEFAULTS;
}
$('prediction-template-save').onclick = () => {
  const template = Object.fromEntries(Object.keys(PREDICTION_TEMPLATE_DEFAULTS).map(id => [id, $(id).value.trim()]));
  if (!validTemplateHorizon(template['p-horizon-value'])) {
    $('p-horizon-value').focus();
    notice('模板的周期长度须为 1 到 365 的整数。', true);
    return;
  }
  try {
    AnalysisMode.write('template', template);
    updatePredictionTemplate();
    notice('已保存填写模板，新建分析时会自动套用。');
  } catch (_) { notice('当前浏览器无法保存填写模板，请检查本地存储设置。', true); }
};
$('prediction-template-reset').onclick = () => {
  try {
    AnalysisMode.write('template', null);
    updatePredictionTemplate();
    notice('新建分析将使用系统模板。');
  } catch (_) { notice('当前浏览器无法清除填写模板。', true); }
};
function resetPredictionInput() {
  setNumericPrediction(null);
  for (const [id, value] of Object.entries(updatePredictionTemplate())) $(id).value = value;
  $('p-subject').value = '';
  setDirection('');
  $('p-confidence').value = '';
  $('p-synthetic').checked = false;
  taskControlsDirty = false;
  facts = [];
  renderFacts();
  resetTiming();
  $('task-data').value = '{}';
  syncJSON();
  window.AnalysisInput?.update();
}

/* ---------- draft：没提交的输入不该因为刷新或切页丢掉 ---------- */
const DRAFT_KEY = 'stock_predict_mailer.console.draft.v1';
const draftKey = (id = $('conversation-id').value) => 'draft.' + (id || 'new');
let draftTimer = null;
const draftWrite = (value, id, mode) => AnalysisMode.write(draftKey(id), value, mode);
const predictionFields = ['p-subject', 'p-model-version', 'p-horizon-value', 'p-horizon-unit', 'p-confidence', 'p-valid-until'];
function draftSnapshot() {
  return {
    data: $('task-data').value,
    notify: $('task-notify').checked,
    recipient: $('task-recipient').value,
    complexity: $('task-complexity').value,
    goal: $('task-goal').value,
    effort: $('task-effort').value,
    message: $('conversation-message').value,
    constraints: $('conversation-constraints').value,
    format: $('conversation-format').value,
    remember: $('remember-text').value,
    remember_format: $('remember-format').value,
    form: Object.fromEntries(predictionFields.map(id => [id, $(id).value])),
    direction: currentDirection(),
    synthetic: $('p-synthetic').checked,
    facts: structuredClone(facts),
    numeric: numericPrediction,
    controls_dirty: taskControlsDirty,
    knowledge: window.KnowledgeUI && {...window.KnowledgeUI.selection(), scope: window.KnowledgeUI.taskScope()},
    saved_at: new Date().toISOString()
  };
}
function draftSchedule() {
  clearTimeout(draftTimer);
  if (AnalysisMode.active() === 'legacy' || window.DesktopInteractions?.draftBlocked()) return;
  const scope = AnalysisMode.capture(), cid = $('conversation-id').value;
  draftTimer = setTimeout(() => {
    if (AnalysisMode.current(scope) && cid === $('conversation-id').value && !window.DesktopInteractions?.draftBlocked()) draftWrite(draftSnapshot());
  }, 400);
}
function draftBanner(message) {
  if (!message) { $('draft-note').hidden = true; return; }
  $('draft-text').textContent = message;
  $('draft-note').hidden = false;
}
function draftRestore() {
  const stored = AnalysisMode.read(draftKey());
  if (!stored || typeof stored.data !== 'string') { draftBanner(null); return false; }
  let payload = {};
  try { payload = JSON.parse(stored.data) || {}; } catch (_) { /* Keep an unfinished JSON edit. */ }
  $('task-data').value = stored.data;
  if (stored.form) {
    for (const id of predictionFields) $(id).value = stored.form[id] ?? '';
    setDirection(stored.direction);
    $('p-synthetic').checked = Boolean(stored.synthetic);
    facts = stored.facts || [];
    renderFacts();
    setNumericPrediction(stored.numeric);
    window.ForecastUI?.restore(payload);
  } else if (payload.prediction) syncForm(true);
  else window.ForecastUI?.restore(payload);
  $('conversation-message').value = stored.message || '';
  $('conversation-constraints').value = stored.constraints || '';
  $('conversation-format').value = stored.format || '';
  $('remember-text').value = stored.remember || '';
  $('remember-format').value = stored.remember_format || '';
  taskControlsDirty = Boolean(stored.controls_dirty);
  if (stored.knowledge) window.KnowledgeUI?.restore(stored.knowledge);
  $('task-notify').checked = Boolean(stored.notify);
  $('task-recipient').value = stored.recipient || '';
  if (stored.complexity) $('task-complexity').value = stored.complexity;
  if (stored.goal) $('task-goal').value = stored.goal;
  if (typeof stored.effort === 'string') $('task-effort').value = stored.effort;
  const until = new Date(payload.prediction?.valid_until || NaN);
  const expired = !isNaN(until.getTime()) && until <= new Date();
  draftBanner(`已恢复 ${stored.saved_at ? fmt(stored.saved_at) : '上次'} 的输入${expired ? '；预测已过期，请核对并更新有效期' : ''}。`);
  window.AnalysisInput?.update();
  return true;
}
function draftClear() {
  clearTimeout(draftTimer);
  draftWrite(null);
  draftBanner(null);
  for (const id of ['conversation-message', 'conversation-constraints', 'conversation-format', 'remember-text', 'remember-format', 'task-recipient']) $(id).value = '';
  $('task-notify').checked = false;
  window.KnowledgeUI?.reset();
  resetPredictionInput();
  notice('已清空本地草稿，表单回到默认值。');
}
$('task-form').addEventListener('input', draftSchedule);
$('task-form').addEventListener('change', draftSchedule);
$('draft-clear').onclick = draftClear;

/* ---------- status + report ---------- */
function statusline(task) {
  const host = $('task-status');
  host.replaceChildren();
  const result = task.artifacts?.[0]?.parts?.[0]?.data;
  const mail = result?.mail;
  const items = [
    [TASK_STATE[task.status.state] || task.status.state, task.status.state === 'failed' ? 'warn' : task.status.state === 'completed' ? 'ok' : 'warn'],
    ['分析 ' + (result?.analysis ? (result.analysis.status === 'degraded' ? '降级' : '正常') : '尚未产出'),
      result?.analysis ? (result.analysis.status === 'degraded' ? 'warn' : 'ok') : 'off'],
    ['邮件 ' + (MAIL_STATE[mail?.status] || (mail ? mail.status : '未请求通知')), mail && mail.status !== 'not_requested' && mail.status !== 'simulated' ? 'warn' : 'off']
  ];
  for (const [label, dot] of items) {
    const span = document.createElement('span');
    const d = document.createElement('i');
    d.className = 'dot ' + dot;
    span.append(d, document.createTextNode(label));
    host.append(span);
  }
  const sep = document.createElement('span');
  sep.className = 'sep';
  sep.textContent = '|';
  host.append(sep);
  const id = document.createElement('span');
  id.className = 'mono';
  id.textContent = task.id;
  host.append(id);
  host.hidden = false;
}
let reportSections = [];
function block(title, hint, key) {
  const el = document.createElement('div');
  el.className = 'block';
  if (key) {
    el.id = 'sec-' + key;
    reportSections.push({key, title, el});
  }
  text(el, 'h3', title);
  if (hint) text(el, 'p', hint, 'hint');
  $('report').append(el);
  return el;
}
function reportToc(anchor) {
  if (reportSections.length < 3) return;
  const nav = document.createElement('nav');
  nav.className = 'report-toc';
  nav.setAttribute('aria-label', '报告章节');
  for (const section of reportSections) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = section.title;
    button.onclick = () => {
      section.el.scrollIntoView({block: 'start', behavior: 'smooth'});
      section.el.classList.add('flash');
      setTimeout(() => section.el.classList.remove('flash'), 1200);
    };
    nav.append(button);
  }
  anchor.after(nav);
}
function renderReport(task) {
  const host = $('report');
  host.replaceChildren();
  reportSections = [];
  const result = task.artifacts?.[0]?.parts?.[0]?.data;
  if (task.status.state === 'failed') {
    const err = task.metadata?.error;
    const help = err && ERROR_HELP[err.code];
    const note = document.createElement('div');
    note.className = 'note danger';
    text(note, 'h4', help ? `任务没有跑完：${help.title}` : '任务失败');
    text(note, 'p', help ? help.why : (err?.message || '没有可用产物，检查输入与配置后重新提交。'));
    if (err) {
      const code = text(note, 'p', `${err.code} · ${err.message || '没有细节'}`, 'err-code');
      code.title = '这是服务端返回的原始错误，排查时给维护者看。';
    }
    const fixes = document.createElement('div');
    fixes.className = 'actions mt-12';
    for (const item of help?.fix || [{label: '回到表单', view: 'analysis'}]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn tiny';
      button.textContent = item.label;
      button.onclick = () => {
        if (item.sample) { $('try-sample').click(); return; }
        showView(item.view);
        if (item.panel) showPanel(item.panel);
      };
      fixes.append(button);
    }
    note.append(fixes);
    host.append(note);
    return;
  }
  if (!result) return;
  if (result.workflow_debug || !result.analysis) {
    text(host, 'pre', JSON.stringify(result.workflow_debug ? result.summary : result, null, 2));
    return;
  }

  const analysis = result.analysis;
  const p = analysis.prediction || {};
  const dirLabel = {up: '上涨', down: '下跌', flat: '持平'}[p.direction] || '—';
  const dirColor = {up: 'var(--up)', down: 'var(--down)'}[p.direction] || 'inherit';

  const head = document.createElement('div');
  head.className = 'report-head';
  const h = document.createElement('h2');
  h.append(document.createTextNode(`${p.subject || '未标注标的'} `));
  const dir = document.createElement('span');
  dir.textContent = p.direction ? dirLabel : '数值预测';
  dir.style.color = dirColor;
  h.append(dir);
  head.append(h);
  const row = document.createElement('div');
  row.className = 'row';
  const unit = {trading_days: '个交易日', calendar_days: '个自然日', hours: '小时'}[p.horizon?.unit] || '';
  for (const item of [
    `周期 ${p.horizon?.value ?? '—'} ${unit}`,
    `模型 ${p.model_version || '—'}`,
    `有效期至 ${p.valid_until ? fmt(p.valid_until) : '—'}`,
    p.synthetic ? '合成数据（synthetic）' : '真实数据'
  ]) text(row, 'span', item);
  head.append(row);
  host.append(head);

  const meta = document.createElement('div');
  meta.className = 'report-meta';
  text(meta, 'span', `生成于 ${fmt(analysis.generated_at)}`);
  text(meta, 'span', `分析 ${analysis.analysis_id || '—'}`);
  text(meta, 'span', `模式 ${analysis.mode || '—'}`);
  host.append(meta);

  if (analysis.forecast_evidence) {
    const archive = block('事前预测归档', '本轮已固定评价口径，未来观测不会改变这份报告。', 'forecast');
    text(archive, 'p', `目标 ${analysis.forecast_evidence.definition.target_at} · ${analysis.forecast_evidence.definition.metric}`);
    const tid = task.id;
    archive.append(action('查看预测归档与到期状态', () => window.ForecastUI?.openTask(tid)));
  }

  const pred = block('上游预测', '数值与方向由上游模型给出，本系统只做解读。', 'prediction');
  const kv = document.createElement('dl');
  kv.className = 'kv';
  const rows = [['方向', dirLabel], ['置信度', null]];
  if (p.value !== null && p.value !== undefined) rows.push(['预测值', `${p.value}${p.value_unit ? ' ' + p.value_unit : ''}`]);
  for (const [key, value] of rows) {
    text(kv, 'dt', key);
    const dd = document.createElement('dd');
    if (key === '置信度') {
      if (p.confidence === null || p.confidence === undefined) {
        const slot = document.createElement('span');
        slot.className = 'empty-slot';
        slot.textContent = '上游未提供';
        dd.append(slot);
      } else {
        dd.textContent = `${Math.round(p.confidence * 100)}%`;
      }
    } else {
      dd.textContent = value;
    }
    kv.append(dd);
  }
  pred.append(kv);

  const factBlock = block('客观事实', '来源是上游声明，系统没有独立核实能力。', 'facts');
  const list = document.createElement('ul');
  list.className = 'fact-list';
  if (!analysis.facts?.length) {
    text(factBlock, 'p', '本次没有提供客观事实。', 'small muted');
  } else {
    for (const f of analysis.facts) {
      const li = document.createElement('li');
      li.dataset.id = f.id;
      text(li, 'span', f.id, 'fid');
      const wrap = document.createElement('span');
      text(wrap, 'span', `${f.name} ${f.value}${f.unit ? ' ' + f.unit : ''}`);
      text(wrap, 'span', `${f.source} · 观测于 ${fmt(f.observed_at)}`, 'src');
      li.append(wrap);
      list.append(li);
    }
    factBlock.append(list);
  }

  const infer = block('Agent 推断', '每条推断都标明它依据的事实编号。', 'inferences');
  if (!analysis.inferences?.length) text(infer, 'p', '没有形成推断。', 'small muted');
  for (const item of analysis.inferences || []) {
    const claim = document.createElement('div');
    claim.className = 'claim';
    text(claim, 'span', item.code || '—', 'fid');
    const bodyEl = document.createElement('span');
    bodyEl.append(document.createTextNode(item.text + ' '));
    for (const ref of item.evidence_ids || []) {
      const a = document.createElement('a');
      a.className = 'ref';
      a.textContent = ref.replace(/^fact:/, '');
      a.href = '#';
      a.onclick = event => {
        event.preventDefault();
        const target = ref.startsWith('prediction:') ? pred
          : [...host.querySelectorAll('.fact-list li')].find(item => item.dataset.id === ref.replace(/^fact:/, ''));
        if (target) {
          target.scrollIntoView({block: 'center'});
          target.style.textDecoration = 'underline';
          setTimeout(() => { target.style.textDecoration = ''; }, 1600);
        }
      };
      bodyEl.append(a, document.createTextNode(' '));
    }
    claim.append(bodyEl);
    infer.append(claim);
  }

  if (analysis.recommendations?.length) {
    const rec = block('建议', null, 'advice');
    const ul = document.createElement('ul');
    ul.className = 'plain';
    for (const item of analysis.recommendations) text(ul, 'li', item);
    rec.append(ul);
  }
  if (analysis.risks?.length) {
    const risk = block('风险', null, 'risks');
    const ul = document.createElement('ul');
    ul.className = 'plain';
    for (const item of analysis.risks) text(ul, 'li', item);
    risk.append(ul);
  }
  if (analysis.limitations?.length) {
    const lim = block('限制与未知', null, 'limits');
    const ul = document.createElement('ul');
    ul.className = 'plain';
    for (const item of analysis.limitations) text(ul, 'li', item);
    lim.append(ul);
  }
  if (analysis.status === 'degraded') {
    const note = document.createElement('div');
    note.className = 'note warn';
    text(note, 'h4', '这份分析是降级结果');
    text(note, 'p', '部分角色没有正常完成，结论由主 Agent 在可用信息内补写。请对照下方执行过程确认缺了哪一步。');
    host.append(note);
  }
  if (result.conflicts?.length) {
    const c = block('已排除的冲突', '这些结论互相矛盾，没有并入上面的主结论。', 'conflicts');
    const ul = document.createElement('ul');
    ul.className = 'plain';
    for (const item of result.conflicts) text(ul, 'li', `${roles[item.role] || item.role} · ${item.code} · ${item.reason}`);
    c.append(ul);
  }

  const coop = block('协作与用量', null, 'usage');
  const kv2 = document.createElement('dl');
  kv2.className = 'kv';
  const usage = result.usage || {};
  const childState = {completed: '已完成', failed: '失败', degraded: '降级', timeout: '超时', canceled: '已取消'};
  for (const [key, value] of [
    ['参与角色', (result.children || []).map(ch => `${roles[ch.role] || ch.role} ${childState[ch.status] || ch.status}`).join(' / ') || '仅主 Agent'],
    ['调用次数', String(usage.calls ?? '—')],
    ['费用预留', `$${usage.reserved_usd ?? 0}（预留，非账单）`],
    ['预算上限', `$${usage.budget_usd ?? '—'}`]
  ]) {
    text(kv2, 'dt', key);
    text(kv2, 'dd', value);
  }
  coop.append(kv2);

  const mail = block('邮件回执', null, 'mail');
  if (!result.mail) {
    text(mail, 'p', '本次没有请求通知，因此没有投递记录。', 'small');
  } else {
    const kv3 = document.createElement('dl');
    kv3.className = 'kv';
    for (const [key, value] of [
      ['状态', `${MAIL_STATE[result.mail.status] || result.mail.status}（${result.mail.status}）`],
      ['收件人', result.mail.recipients?.join('、') || result.mail.recipient || taskBrief(task).recipient || '—'],
      ['尝试次数', String(result.mail.attempts ?? '—')],
      ['下一步', MAIL_NOTE[result.mail.status] || '未知状态，按原始状态码处理，不要假定成功。']
    ]) {
      text(kv3, 'dt', key);
      text(kv3, 'dd', value);
    }
    mail.append(kv3);
    for(const delivery of result.mail.deliveries||[])text(mail,'p',`${delivery.recipient}：${MAIL_STATE[delivery.status]||delivery.status}${delivery.error?' · '+delivery.error:''}`,'small');
    if (result.mail.status === 'uncertain' && !result.mail.deliveries) {
      text(mail, 'p', '确认后只更新回执状态，不会触发重发；要重发请重新提交一次任务。', 'hint mt-10');
      const actions = document.createElement('div');
      actions.className = 'actions mt-10';
      for (const [label, delivered] of [['确认已送达', true], ['确认未送达', false]]) {
        actions.append(action(label, async () => {
          if (!window.confirm(`${label}？这只会更新回执状态，不会重发邮件。`)) return;
          const scope = AnalysisMode.capture();
          await api(`tasks/${task.id}/mail/resolve`, 'POST', {delivered}, undefined, {...scope, mode: taskMode(task)});
          if (!AnalysisMode.current(scope) || currentTask !== task.id) return;
          showTask(await api('tasks/' + task.id));
          notice('回执状态已更新。');
        }));
      }
      mail.append(actions);
    }
  }
  reportToc(meta);
}

function showTask(task) {
  $('task-output').textContent = JSON.stringify(task, null, 2);
  statusline(task);
  renderReport(task);
  const finished = ['completed', 'failed', 'canceled'].includes(task.status.state);
  $('task-cancel').hidden = finished || taskMode(task) === 'legacy';
  renderRunviz(task.status.state);
  window.Workbench?.task(task);
  window.PonyOffice?.sync(task, null);
  window.DesktopReport?.render(task);
  window.DesktopWorkbench?.observe(task);
  return finished;
}

/* ---------- 运行图：跑到哪一步，以及还在不在跑 ---------- */
/* 两个问题必须同时看得见：阶段轨答「到哪一步」，事件节律答「还在动吗」。
   数据全部来自已有的 /events 流，不新增请求；任务结束就定格，不留动画。 */
const RUN_STATE_LABEL = {
  submitted: '已提交，等待执行', working: '运行中',
  completed: '已完成', failed: '运行失败', canceled: '已取消'
};
const runviz = {started: 0, lastAt: 0, watching: false, events: 0, order: [], status: new Map(), samples: [], lastCount: 0};
const PULSE_SLOTS = 60;

function runvizReset(watching = false) {
  window.PonyOffice?.reset(currentTask, !watching);
  runviz.started = 0;
  runviz.lastAt = 0;
  runviz.watching = watching;
  runviz.events = 0;
  runviz.order = [];
  runviz.status.clear();
  runviz.samples = [];
  runviz.lastCount = 0;
  $('runviz').dataset.state = 'submitted';
  $('runviz').classList.add('live');
  $('runviz-rail').replaceChildren();
  $('runviz-labels').replaceChildren();
  $('runviz-bars').replaceChildren();
  $('runviz-elapsed').textContent = '0.0s';
  $('runviz-events').textContent = '0';
  $('runviz-steps').textContent = '0 / 0';
  $('runviz-label').textContent = RUN_STATE_LABEL.submitted;
}

function runvizAddStep(step) {
  if (runviz.status.has(step.id)) return;
  runviz.status.set(step.id, 'pending');
  runviz.order.push({id: step.id, label: roles[step.label] || step.label});
  const rail = $('runviz-rail');
  const labels = $('runviz-labels');
  const seg = document.createElement('span');
  seg.className = 'seg';
  seg.dataset.status = 'pending';
  rail.append(seg);
  const name = document.createElement('span');
  name.dataset.status = 'pending';
  name.textContent = roles[step.label] || step.label;
  name.title = name.textContent;
  labels.append(name);
}

function runvizStep(id, status) {
  if (!runviz.status.has(id)) return;
  runviz.status.set(id, status);
  const index = runviz.order.findIndex(step => step.id === id);
  const seg = $('runviz-rail').children[index];
  const label = $('runviz-labels').children[index];
  if (seg) seg.dataset.status = status;
  if (label) label.dataset.status = status;
}

function runvizEvent(event) {
  runviz.events += 1;
  // 起点取首条事件的时间戳，回看历史任务也能给出真实耗时；没有时间戳才退回本机时钟。
  const at = event?.timestamp ? Date.parse(event.timestamp) : NaN;
  if (at) {
    if (!runviz.started) runviz.started = at;
    runviz.lastAt = at;
  } else if (!runviz.started && runviz.watching) {
    runviz.started = Date.now();
  }
}

function runvizSample() {
  runviz.samples.push(Math.max(0, runviz.events - runviz.lastCount));
  runviz.lastCount = runviz.events;
  if (runviz.samples.length > PULSE_SLOTS) runviz.samples.shift();
}

function renderRunviz(state) {
  const host = $('runviz');
  if (!host) return;
  const current = state || host.dataset.state || 'working';
  const live = !['completed', 'failed', 'canceled'].includes(current);
  host.dataset.state = current;
  host.classList.toggle('live', live);
  $('runviz-label').textContent = RUN_STATE_LABEL[current] || current;

  // 只有从表单提交时才用本机时钟兜底；回看历史任务时用最后一条事件时间定格。
  if (live && runviz.watching && !runviz.started) runviz.started = Date.now();
  const end = live ? Date.now() : runviz.lastAt;
  $('runviz-elapsed').textContent = runviz.started && end
    ? `${Math.max(0, (end - runviz.started) / 1000).toFixed(1)}s` : '—';
  $('runviz-events').textContent = String(runviz.events);
  const done = [...runviz.status.values()].filter(value => value === 'completed').length;
  $('runviz-steps').textContent = `${done} / ${runviz.order.length}`;

  // 始终画满整条基线：空槽留 0.6px 的“刻度”，比只画已有采样更像一张图。
  const bars = $('runviz-bars');
  bars.replaceChildren();
  const max = Math.max(1, ...runviz.samples);
  const width = 120 / PULSE_SLOTS;
  const offset = PULSE_SLOTS - runviz.samples.length;
  for (let slot = 0; slot < PULSE_SLOTS; slot += 1) {
    const index = slot - offset;
    const value = index >= 0 ? runviz.samples[index] : 0;
    const height = Math.max(value ? 1.6 : 0.6, (value / max) * 23);
    const bar = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    bar.setAttribute('x', (slot * width).toFixed(2));
    bar.setAttribute('y', (26 - height).toFixed(2));
    bar.setAttribute('width', Math.max(0.7, width - 0.7).toFixed(2));
    bar.setAttribute('height', height.toFixed(2));
    const recent = index >= 0 && index >= runviz.samples.length - 10 ? ' recent' : '';
    const active = value && index === runviz.samples.length - 1 ? ' active' : '';
    bar.setAttribute('class', `bar${recent}${active}`);
    bars.append(bar);
  }
}

/* ---------- progress events ---------- */
let eventCursor = 0;
const stepRows = new Map();
const progressStates = {pending: '待执行', running: '运行中', completed: '已完成', failed: '失败',
  skipped:'已跳过', degraded:'降级', canceled:'已取消'};
function addPlanStep(step) {
  if (stepRows.has(step.id)) return;
  const row = document.createElement('li');
  const marker = stepRows.get('charts');
  if (marker && ['prediction', 'risk', 'advice', 'merge'].includes(step.id)) marker.before(row);
  else $('execution-plan').append(row);
  row.textContent = `${roles[step.label] || step.label} · 待执行`;
  row.dataset.status = 'pending';
  stepRows.set(step.id, row);
  runvizAddStep(step);
}
function showEvent(event) {
  for (const step of event.steps || []) addPlanStep(step);
  if (event.execution) {
    const {label, limits, native_reasoning_effort: native, model} = event.execution;
    $('effective-effort').textContent = `${label} · ${model || '确定性分析'} · 原生推理 ${native || '未配置'} · ${limits.max_steps} 步 / ${limits.max_calls} 次调用 / ${limits.timeout_seconds} 秒`;
  }
  if (event.kind === 'step' && stepRows.has(event.step)) {
    const row = stepRows.get(event.step);
    row.dataset.status = event.status;
    row.textContent = `${event.label} · ${progressStates[event.status] || event.status}`;
    runvizStep(event.step, event.status);
  }
  runvizEvent(event);
  const localTime = new Date(event.timestamp).toLocaleTimeString('zh-CN');
  const row = document.createElement('li');
  row.dataset.status = event.status || event.kind;
  const time = document.createElement('time');
  time.textContent = localTime;
  row.append(time);
  const body = document.createElement('span');
  body.textContent = `${event.label || event.step || event.kind}${event.code ? ' · ' + event.code : ''}`;
  row.append(body);
  if (event.summary?.length) text(body, 'small', event.summary.join(' / '));
  if (event.kind === 'model') text(body, 'small', `温度 ${event.temperature ?? '由服务决定'} · 原生推理 ${event.native_reasoning_effort || '未配置'}`);
  $('execution-events').append(row);
  if (event.preview) {
    const preview = $('analysis-preview');
    preview.replaceChildren();
    text(preview, 'h3', event.kind === 'report' ? '报告摘要' : '阶段分析');
    for (const item of event.preview.inferences) text(preview, 'p', item.text, 'small');
    for (const note of event.preview.limitations || []) text(preview, 'p', note, 'small muted');
  }
  if (event.kind === 'chart') {
    const figure = document.createElement('figure');
    const image = document.createElement('img');
    image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(event.svg);
    image.alt = event.label;
    figure.append(image);
    text(figure, 'figcaption', event.caption, 'hint');
    $('chart-preview').append(figure);
  }
  window.DesktopWorkbench?.event(event);
}
async function poll(id) {
  if (window.DesktopPoll?.active()) return window.DesktopPoll.request(id);
  if (currentTask !== id) return;
  const scope = AnalysisMode.capture(), context = {...scope, mode: displayedTaskMode()};
  const same = () => currentTask === id && AnalysisMode.current(scope);
  try {
    const task = await api('tasks/' + id, 'GET', undefined, undefined, context);
    if (!same() || taskMode(task) !== context.mode) return;
    const progress = await api(`tasks/${id}/events?after=${eventCursor}`, 'GET', undefined, undefined, context);
    if (!same()) return;
    for (const event of progress.events) {
      if (event.seq <= eventCursor) continue;
      showEvent(event);
      eventCursor = event.seq;
    }
    runvizSample();
    window.PonyOffice?.sync(task, progress.events);
    if (!showTask(task) || progress.events.length === 100) setTimeout(() => { if (same()) poll(id); }, 700);
    else {
      overviewTask = task;
      renderSteps();
      if (memoryKey) refreshMemory().catch(error => { if (same()) notice(error.message, true); });
    }
  } catch (error) {
    if (same()) {
      window.PonyOffice?.disconnected();
      setTimeout(() => { if (same()) poll(id); }, 2500);
      notice(error.message, true);
    }
  }
}
$('task-form').onsubmit = async event => {
  event.preventDefault();
  const button = $('analysis-send') || event.currentTarget.querySelector('[type=submit]');
  const start = AnalysisMode.capture();
  if (button.disabled || event.currentTarget.inert || start.mode === 'legacy' || pendingSubmissions.has(start.mode)) return;
  const revision = window.Workbench?.revision(start.mode);
  const sameSelection = () => revision === window.Workbench?.revision(start.mode);
  submitErrors.delete(start.mode);
  pendingSubmissions.add(start.mode);
  button.disabled = true;
  let extension, pendingRun;
  try {
    window.AnalysisInput?.validate();
    window.ForecastUI?.validate();
    const input = JSON.parse($('task-data').value);
    const conversationId = $('conversation-id').value;
    const controls = {complexity: $('task-complexity').value, goal: $('task-goal').value, reasoning_effort: $('task-effort').value || null};
    const request = conversationId && !input.prediction && !taskControlsDirty ? {...input} : {...input, ...controls};
    {
      request.message = $('conversation-message').value;
      if ($('conversation-constraints').value.trim()) request.constraints = lines($('conversation-constraints').value);
      if ($('conversation-format').value) request.report_format = $('conversation-format').value;
      const remember = [];
      const format = $('remember-format').value;
      if (format) remember.push({kind: 'preference', tags: ['报告格式'], content: format === 'brief' ? '偏好简版报告' : '偏好标准版报告', report_format: format});
      if ($('remember-text').value.trim()) remember.push({kind: 'user_statement', tags: ['用户明确要求'], content: $('remember-text').value});
      if (remember.length) request.remember = remember;
    }
    if (window.KnowledgeUI) Object.assign(request, window.KnowledgeUI.selection());
    const chosenModel = AnalysisMode.read('model');
    if (chosenModel) request.model_id = chosenModel;
    if (AnalysisMode.read('tools')) request.tools = AnalysisMode.tools();
    const recipients=window.MailRecipients?.values();
    const payload = {...request, notify: $('task-notify').checked, recipient: recipients?.[0] || $('task-recipient').value || null, ...(recipients?.length>1?{recipients}:{})};
    extension = window.DesktopWorkbench?.workflowPayload(payload);
    const snapshot = draftSnapshot();
    await ensureBrowserMemory();
    const scope = {...start, key: start.key || memoryKey};
    if (scope.key !== memoryKey) return;
    const cid = conversationId || (await api('conversations', 'POST', {}, undefined, scope)).id;
    if (!conversationId && sameSelection() && scope.key === memoryKey) {
      const here = AnalysisMode.active() === scope.mode && !$('conversation-id').value;
      const draft = here ? draftSnapshot() : AnalysisMode.read(draftKey(''), scope.mode) || snapshot;
      draftWrite(draft, cid, scope.mode);
      if (here) window.Workbench?.attachConversation(cid);
      AnalysisMode.write('position', {conversation:cid}, scope.mode);
    }
    pendingRun = {conversation:cid, request:crypto.randomUUID()};
    if (sameSelection()) AnalysisMode.write('pending-run', pendingRun, scope.mode);
    const task = await api('tasks', 'POST', {...payload, conversation_id: cid, ...extension}, undefined, scope);
    recordLoaded = false;
    if (taskMode(task) !== scope.mode || !sameSelection() || scope.key !== memoryKey) return;
    const visible = AnalysisMode.active() === scope.mode && $('conversation-id').value === cid;
    if (!visible) {
      AnalysisMode.write('position', {conversation:cid, task:task.id}, scope.mode);
      if (scope.mode === 'professional') window.DesktopWorkbench?.queueWorkflow();
      return;
    }
    const live = draftSnapshot();
    delete live.saved_at; delete snapshot.saved_at;
    const unchanged = JSON.stringify(live) === JSON.stringify(snapshot);
    window.Workbench?.attachConversation(cid);
    draftWrite(live, cid, scope.mode);
    document.body.classList.remove('report-dismissed');
    displayTask(task);
    window.AnalysisInput?.open('progress');
    window.Workbench?.submitted(unchanged);
    window.DesktopWorkbench?.acceptWorkflow(task);
  } catch (error) {
    if ((!start.key || start.key === memoryKey) && sameSelection()) {
      if (AnalysisMode.active() === start.mode) {
        if (extension?.workflow) window.DesktopWorkbench.explainError(error);
        notice(error.message, true);
      } else submitErrors.set(start.mode, error.message);
    }
  } finally {
    if (pendingRun && AnalysisMode.read('pending-run', start.mode)?.request === pendingRun.request) {
      AnalysisMode.write('pending-run', null, start.mode);
    }
    pendingSubmissions.delete(start.mode);
    if (AnalysisMode.active() === start.mode) {
      button.disabled = false;
      window.AnalysisInput?.update();
    }
  }
};
$('task-cancel').onclick = async () => {
  const desktop=window.DesktopPoll?.active(),token=desktop?window.DesktopPoll.beginCancel():null;
  if(desktop&&!token)return;
  const scope = AnalysisMode.capture(), id = currentTask, context = {...scope, mode: displayedTaskMode()};
  if (!id || context.mode === 'legacy') return;
  const same = () => AnalysisMode.current(scope) && currentTask === id;
  try {
    const task = await api(`tasks/${id}/cancel`, 'POST', {}, undefined, context);
    if (same() && taskMode(task) === context.mode) {
      if (token) await window.DesktopPoll.cancelled(task,token);
      else showTask(task);
    }
  }
  catch (error) { if(same() && (!token||window.DesktopPoll.valid(token)))notice(error.message, true); }
  finally { if(desktop)window.DesktopPoll.endCancel(token); }
};

/* ---------- records ---------- */
let recordLoaded = false, recordCursor = null, recordBusy = false, recordTimer = null;
let records = [], recordFilter = 'all', recordQuery = '';
const RECORD_FILTER = {all: '全部', active: '进行中', completed: '已完成', failed: '失败'};
const shortTime = value => {
  const date = new Date(value);
  if (isNaN(date.getTime())) return '—';
  const pad = n => String(n).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
};
// 子 Agent 任务的 contextId 指向父任务，只有主任务自己等于自己。
const topLevel = task => !task.contextId || task.contextId === task.id;
function taskBrief(task) {
  const meta = task.metadata?.request || {};
  const data = task.artifacts?.[0]?.parts?.[0]?.data;
  const p = data?.analysis?.prediction || {};
  return {
    subject: meta.subject || p.subject || '',
    direction: meta.direction || p.direction || '',
    horizon: meta.horizon || p.horizon || null,
    notify: meta.notify ?? Boolean(data?.mail),
    recipient: meta.recipients?.join(', ') || meta.recipient || '',
    conversation_id: meta.conversation_id || '',
    mail: data?.mail || null
  };
}
const HORIZON_UNIT = {trading_days: '交易日', calendar_days: '自然日', hours: '小时'};
const horizonText = horizon => horizon && horizon.value !== undefined && horizon.value !== null
  ? `${horizon.value} ${HORIZON_UNIT[horizon.unit] || ''}`.trim() : '—';
function recordsPlaceholder(message) {
  const host = $('record-list');
  host.replaceChildren();
  return text(host, 'p', message, 'empty');
}
const recordGroup = state => state === 'completed' ? 'completed'
  : (state === 'failed' || state === 'canceled') ? 'failed' : 'active';
function recordMatches(task) {
  if (recordFilter !== 'all' && recordGroup(task.status.state) !== recordFilter) return false;
  if (!recordQuery) return true;
  const brief = taskBrief(task);
  const hay = [brief.subject, task.metadata?.error?.code, MAIL_STATE[brief.mail?.status], TASK_STATE[task.status.state]]
    .filter(Boolean).join(' ').toLowerCase();
  return hay.includes(recordQuery);
}
function renderRecords() {
  if (window.DesktopRecords?.render({items: records, filter: recordFilter, query: recordQuery, cursor: recordCursor})) return;
  const host = $('record-list');
  host.replaceChildren();
  const counts = {all: records.length, active: 0, completed: 0, failed: 0};
  for (const task of records) counts[recordGroup(task.status.state)] += 1;
  for (const chip of $('record-chips').querySelectorAll('[data-filter]')) {
    const key = chip.dataset.filter;
    chip.textContent = counts[key] ? `${RECORD_FILTER[key]} ${counts[key]}` : RECORD_FILTER[key];
    chip.classList.toggle('active', key === recordFilter);
    chip.classList.toggle('is-empty', counts[key] === 0);
  }
  if (!records.length) {
    const hint = recordsPlaceholder('暂无任务记录。');
    const go = document.createElement('button');
    go.type = 'button';
    go.className = 'btn tiny mt-12';
    go.textContent = '开始分析';
    go.onclick = () => showView('analysis');
    hint.after(go);
    $('record-count').textContent = '还没有任务';
  } else {
    const shown = records.filter(recordMatches);
    if (!shown.length) {
      recordsPlaceholder(`已载入的 ${records.length} 条里没有匹配。${recordCursor ? '可以继续载入更早的记录，或' : ''}清空筛选再看。`);
    } else {
      for (const task of shown) host.append(recordRow(task));
    }
    $('record-count').textContent = shown.length === records.length
      ? `已载入 ${records.length} 条${recordCursor ? ' · 还有更早的' : ''}`
      : `筛出 ${shown.length} 条 · 已载入 ${records.length} 条`;
  }
  $('record-more-wrap').hidden = !recordCursor;
  window.DesktopLibrary?.records();
}
async function loadRecords(reset = false) {
  if (recordBusy) return;
  recordBusy = true;
  clearTimeout(recordTimer);
  const desktop = window.DesktopRecords?.active();
  if (desktop && !recordLoaded) reset = true;
  const recordEpoch = desktop ? window.DesktopRecords.revision() : null;
  const before = reset ? null : recordCursor;
  if (reset && !desktop) recordCursor = null;
  const host = $('record-list');
  if (desktop) window.DesktopRecords.loading();
  else if (reset || !records.length) recordsPlaceholder('正在读取任务记录…');
  try {
    const page = await api(`tasks?order=desc&limit=30${before ? '&before=' + before : ''}`);
    if (desktop && recordEpoch !== window.DesktopRecords.revision()) return;
    // 子 Agent 的中间任务与主任务同表，contextId 指向父任务；它们不是用户提交的记录。
    const fresh = page.items.filter(task => topLevel(task) && !deletedRecords.has(task.id));
    if (desktop) {
      const updated = await window.DesktopRecords.page({existing: records, fresh, cursor: recordCursor, pageCursor: page.next_before, reset});
      if (recordEpoch !== window.DesktopRecords.revision()) return;
      records = updated.items.filter(task => !deletedRecords.has(task.id)); recordCursor = updated.cursor;
      window.DesktopRecords.loaded(updated.warning);
    } else { records = reset ? [...fresh] : [...records, ...fresh]; recordCursor = page.next_before; }
    recordLoaded = true;
    renderRecords();
    if (records.some(task => recordGroup(task.status.state) === 'active')) {
      // 只在记录页可见时继续刷新，离开页面就停，避免后台空转。
      recordTimer = setTimeout(() => {
        if (!$('record-list').closest('[data-view-pane]')?.hidden) loadRecords(true);
      }, 3000);
    }
  } catch (error) {
    if (desktop && recordEpoch !== window.DesktopRecords.revision()) return;
    if (desktop) window.DesktopRecords.failed(error.message);
    else if (!host.childElementCount) recordsPlaceholder('记录读取失败：' + error.message);
    notice(error.message, true);
  } finally {
    if (!desktop || recordEpoch === window.DesktopRecords.revision()) {
      recordBusy = false;
      if (desktop) window.DesktopRecords.finished();
    }
  }
}
const deletedRecords = new Set();
function forgetRecord(id) {
  deletedRecords.add(id);
  records = records.filter(task => task.id !== id);
  recordLoaded = false;
}
function recordRow(task) {
  const brief = taskBrief(task);
  const state = task.status.state;
  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'task-row';
  row.dataset.state = state;
  row.dataset.taskId = task.id;
  row.dataset.mode = taskMode(task);
  row.dataset.recordedAt = task.status.timestamp || '';

  text(row, 'span', shortTime(task.status.timestamp), 'when');

  const subject = document.createElement('span');
  subject.className = 'subject';
  text(subject, 'b', brief.subject || '未标注标的');
  if (brief.direction) {
    const dir = document.createElement('i');
    dir.className = 'dir';
    dir.dataset.dir = brief.direction;
    dir.textContent = {up: '上涨', down: '下跌', flat: '持平'}[brief.direction] || brief.direction;
    subject.append(dir);
  }
  row.append(subject);

  const error = task.metadata?.error;
  const extra = text(row, 'span', state === 'failed' && error ? error.code : horizonText(brief.horizon), 'span');
  if (state === 'failed' && error) {
    extra.classList.add('is-error');
    extra.title = `${error.code} · ${error.message || '没有细节'}`;
  }

  const status = document.createElement('span');
  status.className = 'state';
  const dot = document.createElement('i');
  dot.className = 'dot ' + (state === 'completed' ? 'ok' : state === 'failed' ? 'warn' : state === 'canceled' ? 'off' : 'warn');
  status.append(dot, document.createTextNode(TASK_STATE[state] || state));
  row.append(status);

  text(row, 'span', brief.mail ? (MAIL_STATE[brief.mail.status] || brief.mail.status) : (brief.notify ? '待投递' : '未请求'),
    'mail');

  text(row, 'span', '查看 →', 'go');
  row.onclick = () => openRecord(task);
  return row;
}
function openRecord(task) {
  if (task.metadata?.workflow?.flow?.id && window.WorkflowChat) return window.WorkflowChat.openTask(task);
  if (taskMode(task) === 'professional') window.WorkflowChat?.showCanvas();
  return window.Workbench?.record(task);
}
function displayTask(task) {
  window.DesktopPoll?.stop();
  if (recordTimer) clearTimeout(recordTimer);
  currentTask = task.id;
  eventCursor = 0;
  stepRows.clear();
  for (const id of ['execution-plan', 'execution-events', 'chart-preview', 'analysis-preview']) $(id).replaceChildren();
  $('task-progress').hidden = false;
  $('effective-effort').textContent = '正在读取执行过程';
  runvizReset(true);
  showTask(task);
  poll(task.id);
}
$('record-refresh').onclick = () => loadRecords(true);
$('record-more').onclick = () => loadRecords();
$('record-chips').onclick = event => {
  const button = event.target.closest('[data-filter]');
  if (!button) return;
  recordFilter = button.dataset.filter;
  renderRecords();
};
$('record-query').oninput = () => {
  recordQuery = $('record-query').value.trim().toLowerCase();
  renderRecords();
};

/* ---------- overview actions ---------- */
$('start-analysis').onclick = () => {
  showView('analysis');
  if (!profiles.length || !settings.default_model_id) {
    notice('分析需要先有一个默认模型。点「用示例预测试一遍」会自动创建 Mock 模型。', true);
  }
};
async function ensureMockModel() {
  let model = profiles.find(item => item.provider === 'mock' && item.enabled);
  if (!model) {
    model = await api('models', 'POST', {name: 'Mock 分析模型', provider: 'mock'});
    await refresh();
  }
  return model.id;
}
$('try-sample').onclick = async () => {
  const button = $('try-sample');
  const scope = AnalysisMode.capture();
  button.disabled = true;
  try {
    const model = await ensureMockModel();
    if (!AnalysisMode.current(scope)) return;
    AnalysisMode.write('model', model);
    applySample();
    showView('analysis');
    notice('已为当前模式选择 Mock，并准备好示例预测与事实。点「提交分析」即可。');
  } catch (error) {
    if (AnalysisMode.current(scope)) notice(error.message, true);
  } finally {
    button.disabled = false;
  }
};

/* ---------- boot ---------- */
(async () => {
  try {
    // The following bundle installs the workbench and composer. A fast local
    // Wait for the deferred bundle before restoring the browser's memory space.
    if (document.readyState === 'loading' || document.readyState === 'interactive') {
      await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, {once:true}));
    }
    const initial = location.hash.replace('#', '');
    await ensureBrowserMemory().catch(() => { /* The memory page shows the status and recovery action. */ });
    await refresh();
    renderSteps();
    await window.Workbench?.init();
    window.WorkflowChat?.init();
    const view = initial === 'mcp' ? 'tools' : ['overview', 'analysis', 'records', 'settings', 'memory', 'knowledge', 'tools'].includes(initial) ? initial : 'analysis';
    showView(view);
    const panel = {models: 'models', collab: 'settings'}[initial];
    if (panel) {
      showView('settings');
      showPanel(panel);
    }
  } catch (error) {
    notice(error.message, true);
  }
})();
