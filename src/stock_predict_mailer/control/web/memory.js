async function refreshMemory() {
  const active = Boolean(memoryKey);
  $('memory-details').hidden = !active;
  $('conversation-fields').hidden = !active;
  if (!active) return;
  const [conversations, entries, config, pending] = await Promise.all([
    api('conversations'), api('memory'), api('memory/settings'), api('memory/pending')
  ]);
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
}
