# 后端修复计划与实施记录
基线8166881。原有忽略的task_plan.md/progress.md属于此前清洗迭代，保留其内容；本次使用本文件记录。

设计：保留固定工具链与结论白名单，解析歧义拒绝，知识引用使用服务端授权版本快照，整段证据在预算内选择，报告与邮件共用analysis，下载不接受磁盘路径。

1. F01/F02完成：嵌套重复JSON键、DOCX重复/空字段/列不齐拒绝；显式证券字段识别裸代码，正文金额不推断。原基线函数独立复现保留于.tmp/backend-baseline-reproduction.json。
2. F03/F05完成受限实现：授权版本检查、完整片段预算、主模型引用白名单、JSON/HTML/邮件渲染；不保证任意用户输入或真实模型token预算。
3. F04/F10/F12完成主要接口：任务列表、受权报告/分析/邮件状态、file/smtp人工确认；会话历史/列表与记忆分页、消息导出、会话删除与访问密钥撤销；接口文档更新。pending队列分页未纳入，旧接口最多100条，尚需后续补齐。
4. F06/F08/F09完成：连接测试effort/envelope一致；as_of选择已发布历史版本；deleting持久状态保留Windows删除重试追踪。
5. 隔离HTTP验证完成：任务生成报告、越权403、路径穿越404、列表过滤、模拟邮件状态；CLI两次run --send退出0、相同ID、仅一条simulated。全量复验进行中。

独立延期：F11按mail-core-plan分层迁移repository/transport/管理面，保留原ID/EML，另做MCP uncertain人工恢复；上游服务配置测试尚无接口；OCR/复杂版式/图数据库/真实模型与邮箱验收/前端不在本次实现范围。

验证环境与错误：全局uv缓存与沙箱临时目录拒绝访问，改用仓库隔离cache/temp与获准本地测试进程。新增分页曾错误使用sqlite字段名（现有连接返回tuple），全量失败证据保留，已修复并重新执行；无跳过测试。

最终验证：ruff通过；compileall通过；全量228项unittest通过（123.095秒，.tmp/backend-final-acceptance.log）；hygiene检查152个tracked文件通过；git diff --check通过。实际本地HTTP与隔离CLI均通过。未提交、推送或合并，未修改前端。pending记忆队列分页仍未完成，旧接口上限100；其余独立延期及真实外部验收边界见上。


## 续轮计划（用户选择：分页与验证；MailCore继续独立迭代）
1. 先以HTTP回归复现pending超过100条时无法续读、游标被忽略的问题。
2. 共用受owner限制的分页实现，新增 /api/memory/pending?before=&limit=；无参数保留原数组/顺序，分页使用排他rowid倒序及next_before。严格拒绝非法、空、重复与未知分页参数。
3. 回归覆盖多页无重复/遗漏、其他owner、删除续读与新增记录的游标稳定性、错误参数；验证读取不消费待写记录。
4. 补长知识证据预算及正式邮件引用验证，沿用Mock/file transport，无真实服务。
5. 更新API/审查修复状态，执行ruff、compileall、完整unittest、hygiene与diff检查。不提交。

续轮验收完成：计划1—5均完成。uv run ruff check src tests scripts、uv run python -m compileall -q src scripts、uv run python -m unittest discover -s tests -q（231项，122.252秒）及python scripts/check_repo_hygiene.py（152个tracked文件）全部通过；git diff --check通过。全量日志：.tmp/backend-pending-final.log。保留先失败后通过证据；无跳过测试、无训练并发失败。此前pending分页未完成的记录为历史状态，现已关闭。MailCore/真实外部验收按用户本轮选择继续独立保留，不属于本轮已完成范围；未自动提交或改前端。
