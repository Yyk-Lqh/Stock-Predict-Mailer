/* Only run against the disposable browser_console_fixture.py service. */
(async () => {
  const $ = id => document.getElementById(id), checks = [];
  const assert = (ok, text) => { if (!ok) throw Error(text); };
  const wait = async (fn, label) => {
    for (let index = 0; index < 150; index++) { if (fn()) return; await new Promise(resolve => setTimeout(resolve, 100)); }
    throw Error('Timeout: ' + label);
  };
  const set = (id, value) => { $(id).value = value; $(id).dispatchEvent(new Event('input', {bubbles:true})); $(id).dispatchEvent(new Event('change', {bubbles:true})); };
  assert(innerWidth > 760, 'Desktop viewport required');
  $('new-analysis').click(); await wait(() => !$('new-analysis').disabled && $('conversation-id').value, 'conversation');
  $('desktop-sample').click(); await wait(() => !$('desktop-sample').disabled && $('task-data').value.includes('console-mock'), 'sample');
  set('conversation-message', '报告阅读验收：核对依据与风险。');
  $('analysis-send').click(); await wait(() => $('result-summary').textContent.includes('报告已生成'), 'report');
  const original = JSON.parse($('task-output').textContent);
  const data = original.artifacts[0].parts[0].data.analysis;
  $('desktop-result').click();
  assert($('desktop-report-overview').textContent.includes(data.inferences[0].text), 'Overview must quote actual inference');
  assert($('desktop-report-overview').textContent.includes('合成数据'), 'Synthetic marker missing');
  assert($('inspector-actions').textContent.includes('下载 HTML 报告'), 'Original downloads missing');
  checks.push('real Mock report overview matches source, synthetic marker and original downloads retained');

  document.querySelector('[data-report-mode="overview"]').click();
  assert(getComputedStyle($('sec-facts')).display === 'none', 'Overview mode did not hide full sections');
  const ref = $('desktop-report-overview').querySelector('.desktop-summary-ref:not(:disabled)');
  assert(ref, 'No report reference to verify'); ref.click();
  assert(getComputedStyle($('sec-facts')).display !== 'none', 'Reference must reveal full report');
  assert($('sec-prediction').classList.contains('desktop-evidence-selected'), 'Reference did not locate actual prediction');
  const trail = document.querySelector('.desktop-evidence-trail');
  trail.querySelector('button').click();
  assert(document.activeElement === ref, 'Return path did not restore summary reference');
  checks.push('summary reference reveals and locates the actual upstream prediction, then returns to origin');

  assert(!$('report').querySelector('.desktop-fact-return'), 'Do not invent inference links for unreferenced facts');
  const linked = structuredClone(original); linked.id = 'desktop-fact-link-boundary';
  linked.artifacts[0].parts[0].data.analysis.inferences[0].evidence_ids.push('fact:' + data.facts[0].id);
  window.showTask(linked);
  const reverse = $('report').querySelector('.desktop-fact-return');
  assert(reverse, 'No reverse reference'); reverse.click();
  assert(document.activeElement.classList.contains('claim'), 'Fact did not locate referring inference');
  trail.querySelector('button').click();
  assert(document.activeElement === reverse, 'Reverse navigation lost return point');
  const mainRef = $('sec-inferences').querySelector('a.ref'); mainRef.click();
  assert(!$('report').querySelector('.desktop-evidence-trail') && !trail.hidden, 'Main report ref not integrated');
  checks.push('fact-to-inference and original report refs have return navigation');

  $('report-expand').click();
  assert(document.body.classList.contains('desktop-report-reading'), 'Focused reading not entered');
  assert(getComputedStyle($('analysis-composer')).visibility === 'hidden' && document.querySelector('.pony-office').inert, 'Background remains interactive');
  const bounds = $('report-inspector').getBoundingClientRect();
  assert(Math.abs(bounds.bottom - innerHeight) < 2 && bounds.width >= innerWidth - 2, 'Reading panel does not use viewport');
  $('analysis-tab-input').click();
  assert(!document.body.classList.contains('desktop-report-reading') && !document.querySelector('.pony-office').inert, 'Switching tabs did not restore workspace');
  $('analysis-tab-report').click();
  checks.push('focused reading fills viewport, blocks hidden background and restores on tab change');

  // Explicit UI boundary fixture: no external model, email or stored record mutation.
  const fixture = structuredClone(original); fixture.id = 'desktop-report-boundary';
  const result = fixture.artifacts[0].parts[0].data;
  result.analysis.status = 'degraded';
  result.analysis.inferences[0].text = '<img src=x onerror=alert(1)> 必须作为文本呈现';
  result.analysis.risks = ['边界风险原文']; result.analysis.limitations = ['边界限制原文'];
  result.mail = {status: 'unknown_boundary_state'};
  window.showTask(fixture);
  assert($('desktop-report-overview').textContent.includes('分析已降级'), 'Degradation warning missing');
  assert($('desktop-report-overview').textContent.includes('<img src=x') && !$('desktop-report-overview').querySelector('img'), 'Source text executed as HTML');
  assert($('desktop-report-overview').textContent.includes('unknown_boundary_state') && $('desktop-report-overview').textContent.includes('不假定成功'), 'Unknown mail status treated as success');
  assert(document.querySelector('.desktop-evidence-trail').hidden && !$('report').querySelector('.desktop-evidence-selected'), 'Evidence selection leaked into another task');
  window.showTask(original); $('analysis-tab-report').click();
  checks.push('degraded and unknown mail states stay explicit; untrusted text safe; task switches clear references');

  const oldClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{writeText:async () => { throw Error('synthetic clipboard restriction'); }}});
  document.querySelector('.desktop-report-copy').click();
  await wait(() => $('report').querySelector('.desktop-copy-fallback'), 'copy fallback');
  const copied = $('report').querySelector('.desktop-copy-fallback').value;
  assert(copied.includes(data.inferences[0].text) && copied.includes('摘自当前报告'), 'Copy fallback not actual report text');
  if (oldClipboard) Object.defineProperty(navigator, 'clipboard', oldClipboard); else delete navigator.clipboard;
  checks.push('clipboard restriction has a selectable, source-based text fallback');

  let rejectCopy;
  Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{writeText:() => new Promise((_, reject) => { rejectCopy = reject; })}});
  document.querySelector('.desktop-report-copy').click();
  window.showTask(fixture); rejectCopy(Error('late synthetic clipboard failure'));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert(!$('report').querySelector('.desktop-copy-fallback'), 'Stale clipboard failure inserted old report into a different task');
  if (oldClipboard) Object.defineProperty(navigator, 'clipboard', oldClipboard); else delete navigator.clipboard;
  window.showTask(original); $('analysis-tab-report').click();
  checks.push('late clipboard failure cannot insert previous task text after switching reports');

  $('report-close').click();
  document.querySelector('[data-view="records"]').click();
  await wait(() => $('record-list').querySelector(`[data-task-id="${original.id}"]`), 'history record');
  set('record-query', 'DEMO');
  document.querySelector('[data-filter="completed"]').click();
  const row = $('record-list').querySelector(`[data-task-id="${original.id}"]`);
  assert(row && $('desktop-record-scope').textContent.includes('已载入'), 'Loaded-only scope missing');
  window.scrollTo(0, 160); const scroll = window.scrollY;
  row.click(); await wait(() => !$('task-form').inert && document.querySelector('.desktop-report-back') && !document.querySelector('.desktop-report-back').hidden, 'history report');
  $('analysis-tab-report').click(); document.querySelector('.desktop-report-back').click();
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  assert(document.body.dataset.view === 'records' && $('record-query').value === 'DEMO', 'History query not restored');
  assert(document.querySelector('[data-filter="completed"]').classList.contains('active'), 'History status filter lost');
  assert(document.activeElement.dataset.taskId === original.id && Math.abs(window.scrollY - scroll) < 3, 'History row or scroll lost');
  await new Promise(resolve => setTimeout(resolve, 250));
  assert($('report-inspector').hidden, 'Late task polling reopened report over history');
  checks.push('history return retains loaded query, status filter, selected record and scroll');
  assert(document.documentElement.scrollWidth <= innerWidth, 'Horizontal overflow');
  document.body.dataset.desktopReportCheck = JSON.stringify({checks});
})().catch(error => { document.body.dataset.desktopReportCheck = JSON.stringify({error:error.message}); });
