(() => {
  if (location.hostname !== '127.0.0.1' || Number(location.port) < 18775) throw Error('Use the catalog fixture');
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async (test, message) => { for (let i=0; i<180; i++) { const value=test(); if (value) return value; await new Promise(resolve => setTimeout(resolve, 60)); } throw Error(message); };
  const button = (host, label) => [...host.querySelectorAll('button')].find(node => node.textContent === label && !node.disabled);
  window.workflowCatalogQA = {state:'running'};
  (async () => {
    await wait(() => window.WorkflowChat && memoryKey && document.querySelector('#workflow-canvas-nav'), 'Catalog did not mount');
    if (sessionStorage.getItem('workflow-catalog-refresh')) {
      await wait(() => !document.querySelector('.workflow-catalog').hidden, 'Catalog did not restore after reload');
      const card = await wait(() => [...document.querySelectorAll('.wfcat-card')].find(node => node.textContent.includes('图像流程')), 'Saved card missing after reload');
      button(card, '打开画布').click();
      await wait(() => !document.querySelector('#desktop-focus').hidden && document.querySelector('[data-workflow-node="report"]'), 'Saved graph did not restore after reload');
      sessionStorage.removeItem('workflow-catalog-refresh');
      window.workflowCatalogQA = {state:'passed-refresh', restored:true};
      return;
    }
    window.DesktopWorkbench.setMode('focus'); document.querySelector('#workflow-canvas-nav').click();
    await wait(() => !document.querySelector('.workflow-catalog').hidden, 'Canvas directory did not open');
    assert(document.querySelector('.wfcat-create'), 'Create card missing');
    assert(!document.querySelector('.wfcat-header'), 'Directory banner is still rendered');
    button(document.querySelector('.wfcat-create'), '分析模板').click();
    await wait(() => !document.querySelector('#desktop-focus').hidden, 'New canvas did not open');
    const saveAs = [...document.querySelectorAll('.desktop-flow-toolbar-actions button')].find(node => node.textContent === '保存为可选流程');
    saveAs.click();
    const saveDialog = await wait(() => document.querySelector('dialog.workflow-chat-dialog[open]'), 'Save panel did not open');
    saveDialog.querySelector('[name="name"]').value = '图像流程';
    saveDialog.querySelector('[name="description"]').value = '用于卡片目录验证';
    saveDialog.querySelector('form').requestSubmit();
    await wait(() => !document.querySelector('dialog.workflow-chat-dialog[open]') && !document.querySelector('.workflow-catalog').hidden, 'Save did not return to directory');
    const card = await wait(() => [...document.querySelectorAll('.wfcat-card')].find(node => node.textContent.includes('图像流程')), 'Saved card missing');
    assert(card.querySelector('.wfcat-default-image'), 'Default card image missing');
    const count = document.querySelectorAll('.wfcat-card:not(.wfcat-create)').length;
    button(card, '打开画布').click();
    await wait(() => !document.querySelector('#desktop-focus').hidden, 'Saved card did not reopen canvas');
    const label = document.querySelector('#desktop-workflow-inspector [name="label"]');
    document.querySelector('[data-workflow-node="main"]')?.click();
    await wait(() => document.querySelector('#desktop-workflow-inspector [name="label"]'), 'Node inspector did not open');
    document.querySelector('#desktop-workflow-inspector [name="label"]').value = '已更新分析';
    document.querySelector('#desktop-workflow-inspector [name="label"]').dispatchEvent(new Event('input', {bubbles:true}));
    button(document.querySelector('#desktop-workflow-inspector'), '保存节点')?.click();
    document.querySelector('[data-workflow-action="save"]')?.click();
    await wait(() => !document.querySelector('.workflow-catalog').hidden && document.querySelectorAll('.wfcat-card:not(.wfcat-create)').length === count, 'Editing duplicated the card');
    const updated = [...document.querySelectorAll('.wfcat-card')].find(node => node.textContent.includes('图像流程'));
    button(updated, '在对话中使用').click();
    await wait(() => !document.querySelector('#workflow-chat').hidden && document.querySelector('#workflow-chat-title').textContent === '图像流程', 'Card did not select flow in chat');
    window.WorkflowChat.showDirectory();
    await wait(() => !document.querySelector('.workflow-catalog').hidden, 'Directory did not reopen after chat selection');
    sessionStorage.setItem('workflow-catalog-refresh', '1');
    window.workflowCatalogQA = {state:'passed', cards:count, name:'图像流程', image:true, chat:true};
  })().catch(error => { window.workflowCatalogQA = {state:'failed', error:error.message, stack:error.stack}; });
  return 'Workflow catalog checks started';
})()
