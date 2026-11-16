/* Explicit local imports; preview responses never become archive receipts. */
window.ObservationPreview = (() => {
  let active = null;
  const MAX = 256 * 1024;
  function clear() { if (active) { ++active.version; active.root.remove(); active = null; } }
  function mount(host, tid, view, current) {
    clear();
    const root = document.createElement('details'); root.className = 'observation-preview';
    text(root, 'summary', '导入观测并预览');
    text(root, 'p', '提供完整观测 JSON 或固定字段的单行 CSV，校验后查看评分预览。预览不保存评估回执。', 'hint mt-14');
    const form = document.createElement('div'); form.className = 'stack mt-14'; root.append(form);
    const field = (label, tag, id) => { const box = text(form, 'label', '', 'field'); text(box, 'span', label); const node = document.createElement(tag); node.id = id; box.append(node); return node; };
    const file = field('选择观测文件（UTF-8，最大 256 KiB）', 'input', 'observation-file'); file.type = 'file'; file.accept = '.json,.csv,application/json,text/csv';
    const format = field('观测格式', 'select', 'observation-format');
    for (const [value, label] of [['json','完整观测 JSON'],['csv','单条观测 CSV']]) format.add(new Option(label, value));
    const raw = field('观测原文', 'textarea', 'observation-content'); raw.rows = 8; raw.spellcheck = false; raw.className = 'mono'; raw.maxLength = MAX;
    const contract = document.createElement('details'); contract.className = 'advanced'; form.append(contract);
    text(contract, 'summary', '查看观测字段与匹配要求');
    text(contract, 'p', 'schema_version,subject,metric,unit,value,observed_at,available_at,source,synthetic', 'mono');
    const r = view.record, d = r.definition;
    text(contract, 'p', `需要匹配：${r.prediction.subject}；${d.metric}；${d.unit}；观测时点 ${d.target_at}；${r.prediction.synthetic ? '合成数据' : '真实数据'}。`, 'hint');
    text(contract, 'p', 'JSON 使用布尔值；CSV 第一行使用上述字段名，只提供一条数据，synthetic 为小写 true 或 false。来源与可用时间须由提供方明确声明。', 'hint');
    const cutoff = field('评价截止时点（可留空，填写时须含时区）', 'input', 'observation-as-of'); cutoff.placeholder = '留空使用现在；或填写带 Z / +08:00 的时间';
    const button = document.createElement('button'); button.type = 'button'; button.className = 'btn'; button.id = 'observation-preview'; button.textContent = '校验并预览'; form.append(button);
    const status = text(form, 'p', '尚未预览。请选择文件或粘贴完整观测。', 'hint'); status.id = 'observation-status'; status.setAttribute('role', 'status');
    const output = document.createElement('section'); output.id = 'observation-result'; output.hidden = true; output.setAttribute('aria-label', '观测评估预览'); form.append(output);
    const state = {root, version:0, busy:false, loading:false, importVersion:0, imported:null}; active = state; host.append(root);
    const live = () => active === state && current() && root.isConnected;
    const message = (value, error = false) => { status.textContent = value; status.classList.toggle('observation-error', error); };
    function invalidate() {
      ++state.version; output.replaceChildren(); output.hidden = true;
      message(state.busy ? '输入已变化；当前请求结束后可重新预览。' : '输入已变化，请重新校验并预览。');
    }
    raw.addEventListener('input', () => { state.imported = null; invalidate(); });
    for (const node of [cutoff, format]) node.addEventListener('input', invalidate);
    format.addEventListener('change', invalidate);
    file.onchange = async () => {
      const selected = file.files[0]; if (!selected) return;
      invalidate(); const version = state.version;
      const importVersion = ++state.importVersion; state.loading = true; button.disabled = true;
      message('正在读取观测文件…');
      try {
        const kind = /\.json$/i.test(selected.name) ? 'json' : /\.csv$/i.test(selected.name) ? 'csv' : null;
        if (!kind) throw Error('请选择 .json 或 .csv 观测文件。');
        if (selected.size > MAX) throw Error('单次观测导入不得超过 256 KiB。');
        // Preserve a UTF-8 BOM as part of the imported text/hash, and reject
        // invalid encodings instead of silently replacing source characters.
        const content = new TextDecoder('utf-8', {fatal:true, ignoreBOM:true}).decode(await selected.arrayBuffer());
        if (!live() || version !== state.version) return;
        raw.value = content; format.value = kind;
        // Textareas normalize CRLF to LF. Keep the exact decoded file until
        // the user edits it, so the input hash still identifies file bytes.
        state.imported = {content, display:raw.value};
        message(`已导入 ${selected.name}，请点击校验并预览。`);
      } catch (error) { if (live() && version === state.version) message(error instanceof TypeError ? '观测文件必须使用有效 UTF-8 编码。' : error.message, true); }
      finally { file.value = ''; if (live() && importVersion === state.importVersion) { state.loading = false; button.disabled = state.busy; } }
    };
    button.onclick = async () => {
      if (state.busy || state.loading || !live()) return;
      invalidate(); const version = state.version;
      try {
        if (!raw.value.trim()) throw Error('请先导入或粘贴完整观测。');
        const content = state.imported?.display === raw.value ? state.imported.content : raw.value;
        if (new TextEncoder().encode(content).length > MAX) throw Error('单次观测导入不得超过 256 KiB。');
        const request = {format:format.value, content};
        if (cutoff.value.trim()) request.as_of = cutoff.value.trim();
        state.busy = true; button.disabled = true; message('正在校验观测并计算预览…');
        const result = await api(`tasks/${encodeURIComponent(tid)}/forecast/preview`, 'POST', request);
        if (!live() || version !== state.version) return;
        output.replaceChildren(); output.hidden = false;
        const label = {ready:'评分预览（未保存）',not_due:'目标尚未到期，未评分',awaiting_observation:'观测在截止时点尚不可用，未评分'}[result.state];
        text(output, 'h4', label);
        text(output, 'p', '观测字段与事前定义匹配；来源仍为提供方声明。', 'hint');
        const actual = result.observation, dl = document.createElement('dl'); dl.className = 'kv'; output.append(dl);
        for (const [name, value] of [['标的与口径', `${actual.subject} · ${actual.metric} (${actual.unit})`],['观测值', `${actual.value} ${actual.unit}`],
          ['来源声明', actual.source],['数据标记', actual.synthetic ? '合成数据' : '真实数据'],['观测时点', actual.observed_at],['可用时点', actual.available_at],['评价截止',result.as_of]]) { text(dl, 'dt', name); text(dl, 'dd', value); }
        if (result.metrics) {
          const m = result.metrics;
          text(output, 'p', `实际方向：${{up:'上涨',down:'下跌',flat:'持平'}[m.realized_direction]}；方向匹配：${m.direction_correct == null ? '未提供方向预测' : m.direction_correct ? '是' : '否'}`);
          text(output, 'p', `相对事前基准的变动：${m.change_from_reference} ${m.unit}`);
          if (m.absolute_error != null) text(output, 'p', `绝对误差：${m.absolute_error} ${m.unit}；有符号误差：${m.signed_error} ${m.unit}`);
        }
        const hashes = document.createElement('details'); hashes.className = 'advanced mt-14'; output.append(hashes); text(hashes, 'summary', '核对内容摘要');
        for (const [name, value] of [['导入文本',result.input.content_sha256],['标准观测',result.observation_id],['预测与定义',result.forecast_content_id]]) text(hashes, 'p', `${name}：${value}`, 'mono');
        for (const note of result.limitations) text(output, 'p', note, 'hint mt-14');
        message('预览完成，未保存回执。原归档状态保持不变。');
      } catch (error) { if (live() && version === state.version) message(`预览失败：${error.message}`, true); }
      finally { state.busy = false; if (live()) button.disabled = state.loading; }
    };
  }
  return {mount, clear};
})();
