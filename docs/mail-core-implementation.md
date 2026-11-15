# 第四阶段 B1：MailCore 提取与迁移预演（2026-11-15）

本文保留 B1 当时的范围和验证记录；后续 B2 代码与安装验证已完成，当前状态见[切换计划](mail-cutover-plan.md)，使用见[迁移手册](mail-core-migration.md)。

用户授权规划并开始下一步，沿用已存在的 mail-core-plan.md。本轮完成内核提取、transport 协议和可审阅的迁移预演/隔离归档接口，不自动迁移实际用户数据，也不切换旧写入口。

## 实施顺序

1. 将 agent_service.MailService 实现移到 mail_core.MailCore，原类作为兼容外观。保持 agent-mail.sqlite3/mail 与 audit 的字段、邮件 ID、冻结 EML、重试/uncertain 状态及 CLI 行为。
2. 提取 File/SMTP 单次 transport 与 MCP 异步 transport，共用明确 outcome；策略、幂等、审计与队列状态留在调用方/核心。MCP 的授权复查、预算、取消及旧 marker 仍由控制台处理，不在本轮擅自替换它们。
3. 只读扫描四个已知来源：agent-mail.sqlite3/mail、state.sqlite3/outbox（按 principal）、control.sqlite3/mcp_mail、control-development.sqlite3/mcp_mail。只查询邮件列，不初始化凭据库、不读取 profiles/secrets；保持一致的只读 SQLite 事务视图。
4. 逐条核对状态、ID、收发地址、EML 哈希和原 Message-ID。sending 计划映射 uncertain。MCP 仅有 ID/status，明确标为缺少 payload/envelope 的只读回执，不伪造 analysis_id、发件人或收件人。
5. 输出确定性 plan_id、来源命名空间/原 ID/内容摘要/拟归档状态与阻断原因。默认预演只输出 JSON，不创建目标库、锁或报告文件。
6. 显式 --apply 必须携带 --expected-plan 和独立 target-workspace；重扫内容不符即拒绝。只写目标 MailCore 的隔离 archive（区分 message/receipt）与 ledger 表，不向 mail 活跃表导入、不自动投递。EML 原字节保存 BLOB，SQLite 事务提交映射与正文，重复导入复用映射，历史来源不变时不覆盖目标记录。来源和目标必须不同，避免归档改变来源文件。
7. 使用合成三路径资料验证只读性、principal 隔离、损坏/缺失资料、sending→uncertain、重复导入、来源漂移、事务回滚、旧 API/SMTP/MCP 兼容和 CLI。执行全量回归及基础 wheel 验证。

## 边界与取舍

- 相比立即替换三个队列，先保持原路径兼容、导入只读归档，迁移结果可核查且不会重复发送。相比仅复制文件，ledger 保留来源命名空间、原 ID、principal/report_id 与摘要，避免不同来源的 ID 混淆。
- 来源根目录参与来源身份；同一 ID 后续内容变化报冲突，不静默覆盖历史映射。预演按各库快照读取，不声称跨库事务；实际切换前仍须停止旧写入者并复验。
- 现有 SMTP 配置行为在本轮保持兼容，完整的端点冻结配置与旧队列绑定、统一活跃队列及 MCP 取消事务属于后续切换批次。不要将本轮内核提取说成三条队列已合并。
- 迁移不要求历史分析仍新鲜，不调用模型，不渲染新 EML，不尝试补齐历史缺失数据。submitted 仅代表服务器已接受，不代表进入收件箱。
- 本轮只在临时测试目录演练导入，真实用户资料保留原状。无前端修改、真实 SMTP/MCP 邮件发送或自动数据库迁移。

## 验证结果

- B1 实现完成，操作见 [MailCore 迁移手册](mail-core-migration.md)。原 MailService 兼容外观、共享核心、File/SMTP/MCP transport、默认 dry-run、显式隔离归档与只读归档列表均已提供；未切换 legacy/MCP 活跃存储。
- 新增 26 项专项全部通过，涵盖 EML 原字节、Message-ID、principal 筛选、MCP 缺字段回执、sending→uncertain、重复映射、来源漂移、事务中断、目标/正文篡改、过期历史、大小限制、CLI 和异步取消。
- 最终完整回归 379/379 通过，耗时 169.590 秒；包含原 Agent/legacy/控制台邮件契约。最终 wheel 在独立 Python 3.12 基础安装环境执行新增 26 项，全部通过。
- Ruff、compileall、命名、仓库卫生与 diff 空白检查通过；基础 CI 增加 MailCore 专项。
- 对当前本机配置工作区另外执行只读预演：5 条 message、0 条 receipt、0 条阻断，ready=true。本机报告为 `.tmp/mailcore-workspace-preview.json`；它是扫描时的快照，实际导入仍须复验 plan_id。未对这些用户记录执行 apply、迁移或发送。
- 显式导入仅在临时合成目录演练，来源与目标强制分离，归档 delivery_disabled=1。测试曾发现 SQLite 夹具提交后未关闭句柄，已修复并在 Windows 复验；沙箱异步套接字受限的挂起测试已终止，最终测试在允许本机回环的环境完成。
- B2 尚待实施：完整端点冻结/旧消息绑定、活跃队列切换和真实邮件验收。本轮不宣称 exactly-once、来源认证或实际收件成功。
