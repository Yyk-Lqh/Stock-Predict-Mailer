/* Run in gstack /browse against browser_console_fixture.py --knowledge-source-fixtures. */
window.knowledgeImportQA = (() => {
  const el = selector => document.querySelector(selector);
  const wizard = () => el('.knowledge-create-main');
  const button = (name, scope = wizard()) => [...scope.querySelectorAll('button')].find(item =>
    item.textContent.trim() === name && !item.disabled && item.getClientRects().length);
  const wait = async (condition, note) => {
    for (let i = 0; i < 100; ++i) {
      const result = condition();
      if (result) return result;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw Error(note + ' · ' + wizard()?.innerText?.slice(-500));
  };
  const click = async (name, scope) => (await wait(() => button(name, scope), name)).click();
  const field = name => [...wizard().querySelectorAll('.field')].find(label =>
    label.querySelector('span')?.textContent === name)?.querySelector('input, textarea');
  function fill(control, value) {
    control.value = value;
    control.dispatchEvent(new Event('input', {bubbles: true}));
  }
  function files(element, event, ...entries) {
    const transfer = new DataTransfer();
    for (const [name, content] of entries) transfer.items.add(new File([content], name, {type: 'text/plain'}));
    if (event === 'change') {
      element.files = transfer.files;
      element.dispatchEvent(new Event('change', {bubbles: true}));
    } else {
      element.dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: transfer}));
    }
  }
  const expectText = item => wait(() => wizard().innerText.includes(item), item);
  const ready = name => wait(() => [...wizard().querySelectorAll('.knowledge-import-row')].some(row =>
    row.querySelector('strong').textContent === name && row.querySelector('.tag').textContent === '可检索'), name);
  const source = key => el('[data-knowledge-source="' + key + '"]').click();
  return {
    async create() {
      (await wait(() => el('#knowledge-create-landing'), '知识库目录')).click();
      await expectText('创建空知识库');
      fill(field('知识库名称'), '独立研究资料');
      fill(field('描述（可选）'), '用于验证来源、队列和召回归属');
      await click('创建空知识库');
      await wait(() => !el('#knowledge-documents-add').closest('.knowledge-documents-main')?.hidden &&
        el('#knowledge-documents-add').getClientRects().length, '文档页');
      el('#knowledge-documents-add').click();
      await expectText('目标知识库 · 独立研究资料');
      return wizard().innerText.slice(0, 220);
    },
    async upload() {
      await wait(() => el('#knowledge-create-file'), '文件选择器');
      files(el('#knowledge-create-file'), 'change', ['仓位策略.txt', 'LocalRiskSource 仓位上限与调仓规则。']);
      await ready('仓位策略.txt');
      await click('继续添加资料');
      files(el('.knowledge-dropzone'), 'drop', ['组合跟踪.md', '# 组合跟踪\n\nLocalRiskDrag 对冲跟踪。'],
        ['空文件.txt', ''], ['不支持.exe', 'data']);
      await expectText('文件为空');
      await expectText('文件格式不支持');
      await ready('组合跟踪.md');
      return wizard().innerText;
    },
    async notionUnbound() {
      await click('继续添加资料');
      const upload = el('[data-knowledge-source=upload]');
      upload.focus();
      upload.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}));
      await expectText('Notion 未绑定');
      if (document.activeElement !== el('[data-knowledge-source=notion]')) throw Error('键盘切换焦点');
      return wizard().innerText;
    },
    async notionBind() {
      await click('去绑定');
      await click('取消配置');
      await expectText('配置已取消');
      await click('去绑定');
      fill(field('Notion 集成令牌'), 'fixture-source-token');
      await click('保存并测试');
      await expectText('组合风控笔记');
      return wizard().innerText;
    },
    async notionImport() {
      wizard().querySelector('.knowledge-source-pages input').click();
      await click('读取所选页面');
      await click('下一步');
      await click('查看分段预览');
      await expectText('NotionRiskAlpha');
      await click('开始导入');
      await ready('组合风控笔记');
      return wizard().innerText;
    },
    async webUnconfigured() {
      await click('继续添加资料');
      source('web');
      await expectText('Jina Reader 未配置');
      if (!wizard().innerText.includes('Firecrawl · 暂未接入')) throw Error('工具状态');
      return wizard().innerText;
    },
    async webImport() {
      if(!field('Reader API Key'))await click('配置工具');
      fill(field('Reader API Key'), 'fixture-source-token');
      await click('保存并测试');
      const urls = await wait(() => field('公开网页地址（每行一个，最多 5 个）'), '网页地址');
      fill(urls, 'https://example.com/article\nhttps://example.com/retry');
      const fetch = window.fetch;
      let release, started = false;
      const gate = new Promise(resolve=>{release=resolve;});
      window.fetch = async (input, options) => {
        const response = fetch.call(window, input, options);
        if (String(input).endsWith('/sources/jina/preview')) { started = true; await gate; }
        return response;
      };
      try {
        await click('读取网页预览');
        await wait(()=>started,'网页预览请求');
        source('notion');
        await expectText('组合风控笔记');
        release();
        await wait(()=>el('[data-knowledge-source=notion]')?.getAttribute('aria-pressed')==='true','旧响应后仍选中 Notion');
      } finally {
        release();window.fetch=fetch;
      }
      source('web');
      await expectText('读取来源超时');
      await click('重试读取失败项');
      await wait(() => wizard().querySelectorAll('.knowledge-import-row .tag').length === 2 &&
        [...wizard().querySelectorAll('.knowledge-import-row .tag')].every(tag => tag.textContent === '待确认'), '两个网页可确认');
      wizard().querySelector('details summary').click();
      await expectText('WebRiskBeta');
      await click('下一步');
      await click('开始导入');
      await wait(() => wizard().querySelectorAll('.knowledge-import-row .tag').length === 2 &&
        [...wizard().querySelectorAll('.knowledge-import-row .tag')].every(tag => tag.textContent === '可检索'), '两个网页已索引');
      return wizard().innerText;
    },
    async afterRefresh() {
      await expectText('目标知识库 · 独立研究资料');
      await expectText('可检索');
      await click('召回测试');
      const query = await wait(() => el('#knowledge-query')?.getClientRects().length && el('#knowledge-query'), '召回测试');
      fill(query, 'WebRiskBeta');
      query.closest('form').requestSubmit();
      await wait(() => el('.kb-hit')?.innerText.includes('WebRiskBeta'), '召回命中');
      await click('打开文档', el('.kb-hit'));
      await wait(() => el('#knowledge-detail')?.innerText.includes('打开原始来源'), '来源详情');
      return el('#knowledge-detail').innerText.slice(0, 260);
    },
    async existingLibrary() {
      (await wait(() => [...document.querySelectorAll('[data-knowledge-back]')].find(control =>
        control.getClientRects().length), '返回知识库')).click();
      (await wait(() => el('#knowledge-open-card')?.getClientRects().length && el('#knowledge-open-card'), '默认知识库')).click();
      await wait(() => el('#knowledge-documents-add').getClientRects().length, '默认库文档');
      el('#knowledge-documents-add').click();
      await expectText('目标知识库 · 预测资料库');
      const custom = el('.knowledge-import-custom input');
      custom.click();
      files(el('#knowledge-create-file'), 'change', ['默认库专用.txt', 'DefaultOnlyRiskAlpha 回归专用资料。']);
      await click('查看分段预览');
      await expectText('DefaultOnlyRiskAlpha');
      await click('开始导入');
      await ready('默认库专用.txt');
      await click('继续添加资料');
      source('web');
      await expectText('Jina Reader 已配置');
      return wizard().innerText;
    },
    async lateUpload() {
      el('#knowledge-create-landing').click();
      fill(field('知识库名称'), '延迟导入的资料库');
      const fetch=window.fetch;
      let release, receipt;
      const gate=new Promise(resolve=>{release=resolve;});
      window.fetch=async (input,options)=>{
        const response=await fetch.call(window,input,options);
        if(String(input).endsWith('/knowledge/documents')&&options.method==='POST'){
          receipt=await response.clone().json();
          await gate;
        }
        return response;
      };
      try {
        files(el('#knowledge-create-file'),'change',['延迟回执.txt','LateUploadRiskAlpha 文档。']);
        const uploaded=await wait(()=>receipt?.id&&receipt,'服务器已接收文件');
        await click('← 返回知识库');
        el('#knowledge-create-landing').click();
        fill(field('知识库名称'),'另一份新建草稿');
        release();
        await wait(()=>{
          const state=AnalysisMode.read('knowledge.import.local.library.'+
            [...document.querySelectorAll('#knowledge-library-cards button')].find(item=>
              item.textContent.includes('延迟导入的资料库'))?.dataset.libraryId+'.local','shared');
          return state?.jobs?.upload?.items?.some(item=>item.doc===uploaded.id);
        },'迟到回执归入原库');
        if(field('知识库名称').value!=='另一份新建草稿')throw Error('新草稿被旧回执覆盖');
        return field('知识库名称').value;
      }finally{
        release();window.fetch=fetch;
      }
    }
  };
})();
