# MailCore 合并方案（待单独迭代）

本文件是方案，尚未实施数据库迁移或替换投递路径。

## 进度

- 步骤 1（三条旧路径的契约测试）已完成：
  - `tests/test_delivery.py` 补 EML 被篡改后拒绝投递、`outbox` 按 principal 隔离、`.invalid` 预览地址不能走 SMTP；
  - `tests/test_control.py` 补 MCP 崩溃标记：`mcp_mail` 停在 `sending` 时再次请求返回 `uncertain` 且不重发；
  - `tests/test_agent_service.py` 已覆盖队列幂等、payload 哈希校验、`sending` 恢复为 `uncertain` 与 `mail_audit` 审计。
- 步骤 2 起（MailCore 提取、迁移命令、切换调用方）尚未实施。

## 现状与选择

delivery.py 的 state.sqlite3/outbox 保存旧报告、principal 和 EML；控制台的 mcp_mail 只保存 ID/status；agent-mail.sqlite3/mail 保存分析、信封地址、重试状态与 payload_hash。当前 MCP 身份还包含服务器和工具，不等同于新邮件四元组身份。

推荐以 agent-mail.sqlite3 扩展为唯一 MailCore 存储，保留旧入口兼容适配器。相比同时改写三种调用方，这样可以分步验收；相比直接把 MCP marker 复制进 mail，显式迁移能保留其缺失信息与不确定状态。

## 接口和状态

MailCore 负责 enqueue/list/get/claim/resolve/audit 和冻结 EML；file/smtp/mcp transport 只执行一次已授权的外部动作并返回明确结果。SMTP 凭据仅在执行时从进程环境变量读取。控制台 MCP 调用保留异步取消语义，并在外部动作前重查授权。

新邮件 ID 固定为 sha256 的现有 identity([analysis_id, recipient, sender_address, transport])；显示名、图片字节、MCP 端点不参与。端点与工具属于冻结投递配置，不允许重试时偷偷切换。EML 只生成一次，旧 EML、payload_hash 和 Message-ID 原样保留。

统一 pending/retry/sending/failed/uncertain/submitted/simulated；超时、取消、崩溃或未知结果均不得产生 submitted。sending 恢复为 uncertain；只有人工审计 resolve 可退出 uncertain。重试仅适用于已明确未接受的临时错误。file 成功只能是 simulated。

## 迁移步骤与边界

1. 先为三条旧路径固化契约测试，覆盖幂等、授权、取消、崩溃与 EML 完整性。
2. 提取 MailCore 与 transport 协议，让 agent_service.MailService 成为兼容外观，保持 CLI 行为。
3. 增加显式、可重复执行的 dry-run/import 命令与 migration ledger；旧库仅只读，导入事务提交后才切换入口。禁止自动发送导入记录。
4. 旧 outbox 使用 source_namespace/source_id 映射，保留 principal、report_id、旧 ID 和原始 EML，不伪造 analysis_id。新旧 ID 分别唯一，重复迁移返回既有映射。
5. MCP 历史 marker 缺少收件地址和 payload，存入 legacy receipt 记录，只读展示，sending 映射 uncertain。不能虚构字段或把 submitted 当作已送达；重发需新建完整消息并显式确认。
6. 分别切换 legacy CLI 与控制台到统一核心，移除旧写入口；至少保留旧库和映射供回退查询，回退不重复发送。

## 验收与发布

stdlib unittest 覆盖三 transport 的相同状态契约、重复迁移、事务中断、旧 EML 可读、锁竞争与取消。逐步运行仓库四项检查。合并不声称 exactly-once 或进收件箱，真实投递另行验证。
