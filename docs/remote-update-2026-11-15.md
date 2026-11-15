# 远程更新与兼容适配记录（2026-11-15）

本地 main 已从 `28b7419` 快进到 `origin/main` 的 `bb8c104`（PR #6），共新增 18 个提交（含合并提交），上游差异涉及 44 个文件、4,245 行新增及 357 行删除。获取远程后先审查差异，再保存本地修改、快进和恢复；未创建提交或推送。

## 上游更新

- 合并两套知识库实现：旧命令和报告经 `knowledge_api.py` 使用加密私有知识库。新增 principal→owner 映射，旧 `knowledge.py` 被删除；历史明文知识库不会自动导入。
- 资料目录分页、状态过滤、版本历史和下架；上传可补来源、可用日、失效日、主体/行业/主题/股票代码。
- 批量导入 `knowledge-import`，支持目录、CSV 清单、试灌数量、预演及导入后处理；新增标注集评测 `knowledge-eval`。
- 队列深度、失败项优先展示、知识库 Worker 心跳与处理计数。
- 检索按资料版本槽位分组，标注有效性；增加别名展开与主体锚定；控制台支持带来源的规则汇总回答。
- A2A 只读知识检索，按角色资料域白名单及独立记忆身份限制；`knowledge-acl` 管理角色授权，默认拒绝。
- PDF 按版式空间还原表格列；新增受控词表、种子库试灌/扩容记录和评测样例。上游样例成绩是其语料基线，本轮没有对真实用户语料重新评测。

## 本地适配

1. 恢复本地采集、MailCore、诊断、组件管理、备份及结构计划等全部优化。README、CLI、控制台服务自动合并；唯一文本冲突为知识库 Worker，手工合并其业务行为。
2. Worker 同时保留 Component 实例身份、进程指纹、协作停止和上游知识库进度心跳。先取得业务锁再构造/恢复库；当前任务结束后响应停止；退出写 stopped 和已处理计数。SQLite 进度心跳供页面展示，不能替代运行管理的归属验证；长任务或数据库忙可能使该展示心跳过期。
3. 结构目录升至 revision 2：增加 `knowledge.workers` 已知空表升级与可选 `control.knowledge_owners`；保留被删除模块的历史 legacy 结构识别，不自动迁移旧正文或 ACL。生成器识别模块级静态 DDL 常量，仍不导入业务服务。
4. 隔离恢复时把知识库 workers 行设为 stopped，清除 current，保留历史计数，避免旧备份的忙碌心跳冒充仍在线。无 workers 表的旧备份保持兼容。
5. 缺少生产主密钥时，在构造 Store 前拒绝访问，防止失败路径创建新的开发数据库/密钥。
6. `knowledge-import --dry-run` 在一次性元数据/密钥副本中运行构造器及去重检查，源 DB/WAL 不通过 SQLite 打开，不初始化来源工作区/密钥/owner。不复制文档原件。`owner_is_preview=true` 表示预演身份，不能据此假设新 owner 已存在；成功和异常退出清理临时目录。
7. PDF 提取器返回 None 时仍进入 OCR/人工复核错误，避免空页触发 AttributeError；本机 HTTP 测试不读取代理环境配置，避免请求被误送代理。

## 验证

- 完整 Python 回归：645 项，644 通过、1 项已有 Windows 符号链接权限跳过，254.227 秒。随后仅调整两项 HTTP 测试的代理隔离，相关基础环境知识库 80 项再次通过。
- 仅 wheel 的 Python 3.12 基础环境：知识库 80、结构计划 34、A2A 6、备份 40、生命周期 36、PDF 8，共 204 项；200 通过、4 个 PDF 可选依赖用例跳过。numpy/sklearn/pandas/requests/baostock 未安装。
- 源码外安装命令验收：dry-run 不创建来源目录；合成 TXT 导入、Worker once、knowledge-eval 和两个数据库结构查询成功。wheel 带完整知识库新模块和结构 JSON。
- gstack `/browse` 对一次性本机资料库验收：目录及 stopped Worker、主体检索分组、保留原文来源的汇总回答通过；1280 宽度无横向溢出、无控制台消息。截图 `.tmp/pull-knowledge-ui.png`，结果 `.tmp/pull-browser-result.json`。行情替身禁用联网，测试服务器已协作退出并删除临时库。
- 五组 Node 几何/通行/大盘数据回归、JS 语法、前端 bundle、Ruff、compile、结构目录、命名、卫生及空白检查通过。
- 初次基础 HTTP 测试受沙箱代理影响，两项失败；显式 trust_env=false 并在宿主环境复验通过。gstack 初次在沙箱找不到已有 Chromium，改用宿主已安装浏览器；会话随调用清理，最终在同一次调用中完成导航、交互及结果保存。均未修改用户浏览器配置。

## 保留与真实数据

拉取前 86 个本地改动文件已保存为 `.tmp/remote-update-20261115-222416/local-work.zip`、`tracked.patch`、`manifest.json`，并保留 Git stash：`codex preserve local optimizations before origin-main update 2026-11-15`。恢复后所有文件仍在；未适配文件仅有 Git 行尾规范化差异，实质修改均在合并与兼容范围。

真实应用/采集工作区与原配置共 38 个文件、2,928,252 字节，其文件集合和 SHA 与拉取前备份计划完全一致。仅运行只读结构查询：邮件绑定组和知识库 workers 组各有一项已知升级计划，正式/开发 control 匹配，legacy/crawler 未初始化。未实际升级、备份/恢复、导入用户语料、采集、调用模型或发送邮件；现有服务未接管或重启。核对记录 `.tmp/pull-preservation-check.json`、`.tmp/schema-workspace-readonly-check.json`。

当前源码已兼容并经上述验证；运行中的旧进程不会自动载入新源码。后续实际结构升级继续按 D2 的备份、停写、事务及版本登记方案推进。
