/* Explicit per-turn definitions and task-authorized, read-only archive views. */
window.ForecastUI = (() => {
  const enabled = $('evaluation-enabled'), fields = $('evaluation-fields');
  const names = {target_at:'target', timezone:'timezone', metric:'metric', unit:'unit', flat_tolerance:'tolerance'};
  const labels = {pending:'待到期', due:'已到期，待观测', evaluated:'已评估'};
  let base = {}, rows = new Map(), cursor = null, epoch = 0, detailEpoch = 0, busy = false;
  const input = () => JSON.parse($('task-data').value || '{}');
  const put = value => { $('task-data').value = JSON.stringify(value, null, 2); draftSchedule(); };
  const value = id => $('evaluation-' + id).value.trim();
  const number = id => value(id) === '' ? null : Number(value(id));
  function paint() {
    fields.hidden = !enabled.checked; fields.disabled = !enabled.checked;
    let p; try { p = input().prediction; } catch (_) { /* invalid JSON remains editable */ }
    $('evaluation-calendar').hidden = p?.horizon?.unit !== 'trading_days';
    const marker = Object.hasOwn(base.reference || {}, 'synthetic') ? base.reference.synthetic : p?.synthetic;
    $('evaluation-synthetic').textContent = p ? marker !== p.synthetic ? '导入定义的基准合成标记与预测不一致，请核对并重新导入定义。' : `基准数据标记与本轮预测一致：${p.synthetic ? '合成数据' : '真实数据'}。` : '请先填写本轮预测；沿用会话预测时，请先重新导入要归档的完整预测。';
  }
  function restore(payload) {
    const d = payload?.evaluation_definition;
    base = d && typeof d === 'object' && !Array.isArray(d) ? d : {};
    enabled.checked = Boolean(d);
    for (const [key, id] of Object.entries(names)) $('evaluation-' + id).value = base[key] ?? '';
    for (const [key, id] of Object.entries({value:'reference', observed_at:'observed', available_at:'available', source:'source'})) $('evaluation-' + id).value = base.reference?.[key] ?? '';
    $('evaluation-calendar-source').value = base.calendar?.source ?? '';
    $('evaluation-sessions').value = Array.isArray(base.calendar?.sessions) ? base.calendar.sessions.join('\n') : '';
    paint();
  }
  function write() {
    try {
      const payload = input(), p = payload.prediction;
      if (!enabled.checked) delete payload.evaluation_definition;
      else {
        const d = {...base, schema_version:'1', target_at:value('target'), timezone:value('timezone'), metric:value('metric'), unit:value('unit'),
          flat_tolerance:number('tolerance'), reference:{...base.reference, value:number('reference'), observed_at:value('observed'),
            available_at:value('available'), source:value('source'), synthetic:Object.hasOwn(base.reference || {}, 'synthetic') ? base.reference.synthetic : p?.synthetic}};
        if (p?.horizon?.unit === 'trading_days') d.calendar = {source:value('calendar-source'), sessions:lines(value('sessions'))};
        else delete d.calendar;
        payload.evaluation_definition = d;
      }
      put(payload); paint(); $('evaluation-status').textContent = '已更新本轮定义；发送时将校验周期、时点与基准。';
    } catch (_) { $('evaluation-status').textContent = '原始 JSON 无法解析，请先修正原始输入。'; }
  }
  function reset() {
    try { const payload = input(); delete payload.evaluation_definition; put(payload); } catch (_) { /* preserve malformed input */ }
    restore({});
  }
  function invalid(id, message) {
    window.AnalysisInput?.open('input'); const field = $('evaluation-' + id);
    field.setAttribute('aria-invalid', 'true'); field.setCustomValidity?.(message); field.focus(); field.reportValidity?.();
    throw Error(message);
  }
  function validate() {
    const payload = input(), d = payload.evaluation_definition;
    if (d == null) return;
    if (!enabled.checked) restore(payload);
    if (!payload.prediction) return invalid('target', '归档需要本轮完整预测，请先导入预测再填写定义。');
    for (const [key, id] of Object.entries(names)) if (key !== 'flat_tolerance' && (typeof d[key] !== 'string' || !d[key].trim())) return invalid(id, '请填写完整的目标、时区、指标和单位。');
    if (!Number.isFinite(d.flat_tolerance) || d.flat_tolerance < 0) return invalid('tolerance', '平盘阈值须为不小于零的有限数字。');
    if (!Number.isFinite(d.reference?.value)) return invalid('reference', '请填写有限的基准值。');
    if (typeof d.reference.synthetic !== 'boolean' || d.reference.synthetic !== payload.prediction.synthetic) return invalid('source', '基准合成标记与预测不同，请核对并重新导入定义。');
    for (const [at, id] of [[d.target_at, 'target'], [d.reference?.observed_at, 'observed'], [d.reference?.available_at, 'available']]) {
      if (typeof at !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/i.test(at) || !Number.isFinite(Date.parse(at))) return invalid(id, '时点需要有效的日期时间及 Z 或 +08:00 等明确时区。');
    }
    if (Date.parse(d.target_at) <= Date.now()) return invalid('target', '目标时点必须晚于现在，请核对本轮定义。');
    if (!d.reference?.source?.trim()) return invalid('source', '请填写基准来源。');
    if (payload.prediction.horizon?.unit === 'trading_days' && (!d.calendar?.source?.trim() || d.calendar?.sessions?.length !== payload.prediction.horizon.value)) return invalid('sessions', '请填写日历来源及与预测周期等长的后续交易日。');
  }
  enabled.onchange = write;
  fields.addEventListener('input', event => { if (event.target.id !== 'evaluation-import') write(); });
  $('evaluation-import').onchange = async event => {
    const field = event.currentTarget, file = field.files[0];
    if (!file) return;
    try {
      const cid = $('conversation-id').value, prediction = JSON.stringify(input().prediction);
      if (file.size > 1024 * 1024) throw Error('评价定义文件须小于 1 MiB。');
      const d = JSON.parse(await file.text());
      if (cid !== $('conversation-id').value || prediction !== JSON.stringify(input().prediction)) return;
      if (!d || d.schema_version !== '1' || !d.reference || Array.isArray(d)) throw Error('请选择完整的 v1 评价定义文件。');
      const payload = {...input(), evaluation_definition:d}; put(payload); restore(payload);
      notice('评价定义已导入，仅用于本轮归档。');
    } catch (error) { notice(error.message, true); } finally { field.value = ''; }
  };
  $('task-data').addEventListener('change', () => { try { restore(input()); } catch (_) { /* raw editor owns error */ } });
  function clearList() {
    window.ObservationPreview?.clear();
    ++epoch; ++detailEpoch; rows.clear(); cursor = null; busy = false;
    $('forecast-list').replaceChildren(); $('forecast-detail').replaceChildren(); $('forecast-detail').hidden = true;
    $('forecast-more').hidden = true; $('forecast-refresh').disabled = false;
    $('forecast-list-status').textContent = '尚未读取，请刷新预测。';
    window.DesktopLibrary?.forecasts(null); window.DesktopLibrary?.forecastClosed();
  }
  function renderRows() {
    const host = $('forecast-list'); host.replaceChildren();
    for (const r of rows.values()) {
      const row = document.createElement('article'); row.className = 'forecast-row'; row.dataset.forecast = r.forecast_id;
      const main = document.createElement('div');
      text(main, 'h3', r.subject); text(main, 'p', `${labels[r.state]} · ${r.synthetic ? '合成数据' : '真实数据'}`, 'hint');
      text(main, 'p', `目标 ${fmt(r.target_at)} · ${r.metric} (${r.unit})`, 'hint');
      row.append(main, action('查看预测详情', () => openTask(r.task_id, false))); host.append(row);
    }
    window.DesktopLibrary?.forecasts({items:[...rows.values()], state:$('forecast-state').value, cursor});
  }
  async function load(resetPage = false) {
    if (resetPage) clearList(); else if (busy || cursor == null) return;
    const current = ++epoch, key = memoryKey; busy = true;
    $('forecast-refresh').disabled = true; $('forecast-more').disabled = true; $('forecast-list-status').textContent = '正在读取可访问任务的预测…';
    try {
      const page = await api(`forecasts?limit=20&state=${$('forecast-state').value}${cursor == null ? '' : '&before=' + cursor}`);
      if (current !== epoch || key !== memoryKey) return;
      for (const item of page.items) if (!rows.has(item.forecast_id)) rows.set(item.forecast_id, item);
      cursor = page.next_before; renderRows(); $('forecast-more').hidden = cursor == null;
      $('forecast-list-status').textContent = rows.size ? `已载入 ${rows.size} 条不同预测；最近读取 ${fmt(page.as_of)}。刷新从最新任务重新读取。` : cursor != null ? '本页任务没有符合条件的预测，可继续载入更早任务。' : '没有符合条件的预测。可在分析资料中启用本轮归档，或切换状态筛选。';
    } catch (error) {
      if (current === epoch && key === memoryKey) { $('forecast-list-status').textContent = `读取失败：${error.message}。请刷新重试。`; $('forecast-more').hidden = cursor == null; }
    } finally { if (current === epoch) { busy = false; $('forecast-refresh').disabled = false; $('forecast-more').disabled = false; } }
  }
  async function openTask(tid, navigate = true) {
    if (navigate) showView('records');
    window.ObservationPreview?.clear();
    window.DesktopLibrary?.forecastClosed();
    const current = ++detailEpoch, key = memoryKey, host = $('forecast-detail');
    host.hidden = false; host.replaceChildren(); text(host, 'p', '正在读取预测详情…', 'hint');
    try {
      const view = await api(`tasks/${encodeURIComponent(tid)}/forecast`);
      if (current !== detailEpoch || key !== memoryKey) return;
      host.replaceChildren(); const r = view.record, d = r.definition, p = r.prediction;
      text(host, 'h3', `${p.subject} · ${labels[view.state]}`);
      text(host, 'p', p.synthetic ? '合成数据，仅用于演示' : '真实数据，来源为上游声明', 'hint');
      const dl = document.createElement('dl'); dl.className = 'kv'; host.append(dl);
      for (const [label, v] of [['预测归档', r.forecast_id], ['注册时间', fmt(r.registered_at)], ['目标时点', `${d.target_at} · ${d.timezone}`],
        ['评价口径', `${d.metric} (${d.unit})`], ['比较基准', `${d.reference.value} ${d.unit} · ${d.reference.source}`],
        ['基准观测 / 可用', `${d.reference.observed_at} / ${d.reference.available_at}`], ['平盘阈值', `${d.flat_tolerance} ${d.unit}（含边界）`]]) { text(dl, 'dt', label); text(dl, 'dd', v); }
      if (d.calendar) text(host, 'p', `声明日历：${d.calendar.source}；${d.calendar.sessions.join('、')}`, 'hint');
      if (!view.evaluations.length) text(host, 'p', view.state === 'pending' ? '目标尚未到期，暂无评估结果。' : '已到期，尚无匹配观测的评估回执。到期不代表预测已验证。', 'hint mt-14');
      for (const receipt of view.evaluations) {
        const m = receipt.metrics, section = document.createElement('section'); section.className = 'forecast-receipt'; host.append(section);
        text(section, 'h4', `评估回执 · ${fmt(receipt.evaluated_at)}`);
        text(section, 'p', `观测 ${receipt.observation.value} ${m.unit}；来源声明：${receipt.observation.source}`);
        text(section, 'p', `实际方向：${{up:'上涨', down:'下跌', flat:'持平'}[m.realized_direction]}；方向匹配：${m.direction_correct == null ? '未提供方向预测' : m.direction_correct ? '是' : '否'}`);
        if (m.absolute_error != null) text(section, 'p', `绝对误差：${m.absolute_error} ${m.unit}；有符号误差：${m.signed_error} ${m.unit}`);
        text(section, 'p', `观测可用：${receipt.observation.available_at}；评价截止：${receipt.as_of}`, 'hint');
      }
      text(host, 'p', '已保存的档案与回执只读。来源与日历未独立认证，摘要仅用于核对一致性。', 'hint mt-14');
      window.ObservationPreview?.mount(host, tid, view, () => current === detailEpoch && key === memoryKey && !host.hidden);
      host.append(action('收起详情', close));
      window.DesktopLibrary?.forecastDetail(tid, view);
      host.focus(); host.scrollIntoView({block:'nearest'});
    } catch (error) { if (current === detailEpoch && key === memoryKey) { host.replaceChildren(); text(host, 'p', `读取失败：${error.message}`, 'hint'); host.append(action('重试详情', () => openTask(tid, false))); } }
  }
  function close() { ++detailEpoch; window.ObservationPreview?.clear(); $('forecast-detail').hidden = true; window.DesktopLibrary?.forecastClosed(); }
  $('forecast-refresh').onclick = () => load(true); $('forecast-more').onclick = () => load(); $('forecast-state').onchange = () => load(true);
  restore(input());
  return {restore, reset, validate, load, openTask, close, identityChanged:clearList};
})();
