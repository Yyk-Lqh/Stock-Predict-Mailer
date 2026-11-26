async function refreshMemory() {
  const active = Boolean(memoryKey);
  if (!active) {
    $('memory-details').hidden = true;
    $('conversation-fields').hidden = true;
    return;
  }
  const [conversations, entries, config, pending] = await Promise.all([
    api('conversations'), api('memory'), api('memory/settings'), api('memory/pending')
  ]);
  $('memory-details').hidden = false;
  $('conversation-fields').hidden = false;
  const selector = $('conversation-id');
  const selected = selector.value;
  selector.replaceChildren(new Option('独立任务', ''));
  for (const conversation of conversations) {
    selector.append(new Option(conversation.subject || '空会话', conversation.id));
  }
  selector.value = selected;
  $('memory-enabled').checked = config.enabled;
  $('memory-threshold').value = config.context_bytes;
  $('memory-recent').value = config.recent_turns;
  $('memory-pending').textContent = pending.length ? `待保存 ${pending.length} 条。继续对应会话时会重试。` : '待写队列为空';
  const list = $('memory-entries');
  list.replaceChildren();
  if (!entries.length) text(list, 'p', '暂无长期记忆。');
  for (const item of entries) {
    const card = document.createElement('article');
    card.className = 'execution-panel';
    text(card, 'h3', `${item.kind} · ${item.tags.join(' / ')}`);
    text(card, 'p', [item.subject, item.applies_at, item.data_version, item.recorded_at].filter(Boolean).join(' · '));
    const field = document.createElement('textarea');
    field.value = item.content;
    field.maxLength = 800;
    field.setAttribute('aria-label', '记忆内容');
    card.append(field);
    const format = document.createElement('select');
    format.setAttribute('aria-label', '报告格式偏好');
    for (const [value, label] of [['', '普通偏好'], ['brief', '简版'], ['standard', '标准版']]) {
      format.append(new Option(label, value));
    }
    format.value = item.report_format || '';
    if (item.kind === 'preference') card.append(format);
    card.append(action('保存更正', async () => {
      const {id, owner, recorded_at, source_conversation, source_message, ...body} = item;
      await api('memory/' + id, 'PUT', {...body, content:field.value, report_format:format.value || null});
      await refreshMemory();
    }), action('删除记忆', async () => {
      if (window.confirm('删除这条长期记忆？')) {
        await api('memory/' + item.id, 'DELETE');
        await refreshMemory();
      }
    }));
    list.append(card);
  }
  window.Workbench?.sessions().catch(error => notice(error.message, true));
}

async function useMemoryKey(key) {
  window.DesktopPoll?.stop();
  window.DesktopSessions?.identityChanged();
  window.ForecastUI?.identityChanged();
  window.DesktopRecords?.identityChanged();
  const previous = memoryKey;
  memoryKey = key;
  try {
    await refreshMemory();
    currentTask = null;
    $('conversation-id').value = '';
    sessionStorage.setItem('spm_memory_key', memoryKey);
    window.Workbench?.identityChanged();
  } catch (error) {
    memoryKey = previous;
    window.DesktopSessions?.identityChanged();
    window.DesktopRecords?.identityChanged();
    await refreshMemory();
    window.DesktopPoll?.resume();
    throw error;
  }
}

let browserMemoryReady;
const memoryRestartHint = '当前控制台还在运行旧版本。请用原启动方式重启服务，再重新加载本页。';

function showMemoryStatus(message, reload = false) {
  $('memory-status').hidden = !message;
  $('memory-status-text').textContent = message;
  $('memory-reload').hidden = !reload;
}

$('memory-reload').onclick = () => location.reload();

function ensureBrowserMemory() {
  if (!browserMemoryReady) {
    showMemoryStatus('正在打开记忆空间…');
    browserMemoryReady = (async () => {
      const session = await api('session');
      csrf = session.csrf_token;
      if (!session.browser_memory_access) {
        // Older servers read static files from disk but need restarting to add new API routes.
        if (!memoryKey) throw new Error(memoryRestartHint);
        await refreshMemory();
        showMemoryStatus('已打开当前标签页的记忆。重启控制台后，新标签页也能自动恢复。', true);
        return;
      }
      const restore = () => api('memory/browser-access', 'POST');
      // Coordinate the first visit if the same workspace opens in several tabs.
      const access = await (navigator.locks ? navigator.locks.request('spm-browser-memory', restore) : restore());
      if (access.key === memoryKey) await refreshMemory();
      else await useMemoryKey(access.key);
      showMemoryStatus('');
    })().catch(error => {
      browserMemoryReady = null;
      showMemoryStatus(error.message === memoryRestartHint ? memoryRestartHint : '暂时无法打开记忆空间。请重新加载本页重试。', true);
      throw error;
    });
  }
  return browserMemoryReady;
}
$('memory-settings-actions').append(action('保存记忆设置', async () => {
  await api('memory/settings', 'PUT', {
    enabled:$('memory-enabled').checked, context_bytes:Number($('memory-threshold').value),
    recent_turns:Number($('memory-recent').value)
  });
  await refreshMemory();
  notice('记忆设置已保存。');
}));
$('conversation-actions').append(action('新建会话', async () => {
  const conversation = await api('conversations', 'POST', {});
  await refreshMemory();
  $('conversation-id').value = conversation.id;
  $('conversation-summary').textContent = '已创建会话，请先提交预测输入。';
}), action('沿用上轮输入', async () => {
  const id = $('conversation-id').value;
  if (!id) throw new Error('请先选择已有会话');
  const session = await api('conversations/' + id);
  if (!session.messages.length) throw new Error('此会话还没有预测输入');
  $('task-data').value = '{}';
  $('conversation-summary').textContent = '将沿用最近一轮预测和约束，并校验其有效期。';
}));
$('conversation-id').onchange = async event => {
  const id = event.target.value;
  if (!id) {
    $('conversation-summary').textContent = '';
    return;
  }
  try {
    const session = await api('conversations/' + id);
    $('conversation-summary').textContent = `近期消息 ${session.messages.length} 轮 · 已压缩摘要 ${session.summary.length} 条 · 最近检查点 ${session.completed_step || '暂无'}`;
  } catch (error) {
    notice(error.message, true);
  }
};
