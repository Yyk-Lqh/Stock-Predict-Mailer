# MailCore 兼容提取与迁移预演

MailService 的公共入口仍可使用，内部由 mail_core.MailCore 实现。新建的分析、legacy CLI 和控制台 MCP 邮件均写入 agent-mail.sqlite3/mail，附带冻结的端点绑定。legacy 通过别名保留旧 ID、principal/report_id 与原始 EML；旧 outbox/mcp_mail 表只读，历史资料不会自动进入新队列。代码切换不等于已重启运行中的旧进程，启用前须停止旧写入者。

## 默认只读预演

```powershell
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml mail-migrate
# 或指定来源工作区及旧 outbox 的 principal：
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml mail-migrate --source-workspace 'D:\path\to\source' --principal owner
```

预演只输出 JSON，不构造凭据库、不读取 profiles/secrets，也不创建目标数据库、业务锁或发送消息。按来源库的只读事务分别扫描四处邮件表：agent-mail.sqlite3/mail、state.sqlite3/outbox、control.sqlite3/mcp_mail、control-development.sqlite3/mcp_mail。输出 plan_id、来源命名空间、原 ID、拟归档状态、EML 摘要、数量及阻断项。

principal 筛选旧 outbox 和新 Core 的 legacy 绑定；原有 agent/MCP 记录没有该字段，保留 null，不补造所有者。它是本机单用户迁移工具，不是跨租户授权界面。预演会展示收发地址等邮件元数据，报告应保留在本机。

Message-ID、收发信息、原始 EML 哈希和 agent 分析内容绑定均检查。旧 sending 计划映射为 uncertain，但不修改来源记录。MCP 缺正文、收发信息、模型分析和端点时仅成为只读 receipt。submitted 保留“服务器已接受”含义，不能显示成已进收件箱。

损坏/缺失 EML、未知状态、非法 ID、信封不匹配、分析摘要错误均阻止导入；不静默丢弃。历史分析过期不会触发新模型调用，也不因此禁止保留已存在的 EML。

## 显式隔离归档

先审阅预演，停止来源写入者并再次检查计划。来源和目标必须是不同工作区，目标可选一个独立目录：

```powershell
# 将 <plan_id> 替换为刚审阅的摘要；本命令只归档，不进入待发队列。
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml mail-migrate --apply --target-workspace 'D:\path\to\mail-archive' --expected-plan '<plan_id>'
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml mail-archive --target-workspace 'D:\path\to\mail-archive'
```

来源与预演不符报 MIGRATION_PLAN_CHANGED；有阻断项报 MIGRATION_BLOCKED；源目标相同报 MIGRATION_TARGET。参数必须与预演相同，包括 source-workspace/principal/limit。分库读取不等于跨库事务，切换旧写入口前仍须静止写入并单独验收。

目标新增 agent-mail.sqlite3 中的 mail_archive 与 mail_migration_ledger。archive 区分 message/receipt，delivery_disabled 固定为 1；正文使用原字节 BLOB，映射与正文在同一 SQLite 事务提交。没有新增活跃 mail 记录，mail-drain 不会发送导入资料。

同来源命名空间/原 ID/内容再次导入只复用映射。来源根目录参与身份，避免不同工作区 ID 混淆；已导入来源内容变化、归档状态或正文被改动时报 MIGRATION_CONFLICT，不覆盖历史。来源 ID、principal、report_id、Message-ID 和原始 EML 均保留，不伪造新的 analysis_id。

空计划不创建目标；失败的显式导入可能留下空表/锁文件，但不会留下半批邮件或 ledger。无需也不应删除来源库或 EML。隔离 archive 没有激活投递命令；下述 legacy 绑定只针对原始旧 outbox，不针对归档。

## 端点冻结与审阅

新入队即冻结可用 SMTP 主机、端口、TLS、超时、凭据环境变量名称，或 MCP 服务/工具、公开路由和加密配置修订摘要。邮件信封、正文摘要、分析/来源资料和请求正文共同绑定。SMTP 密码值仅在投递时读取，不写入队列；同一环境变量下轮换值不会改变绑定。MCP 配置重新保存可能重新加密，修订变化会要求审阅。

端点漂移报 MAIL_ENDPOINT_CHANGED。已有尝试但无绑定的历史分析邮件报 MAIL_BINDING_REQUIRED；未尝试且缺主机的旧/新消息允许在显式首次 send 前初始化。更改配置后，先审阅再确认，两个命令均不发送：

```powershell
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml mail-binding-plan '<core_message_id>'
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml mail-bind '<core_message_id>' --expected-plan '<plan_id>'
```

计划包含正文摘要、状态、尝试次数及新旧端点，变化后旧 plan_id 失效。bind 保留 attempts、uncertain 与退避，不自动重试；sending 转为 uncertain。submitted/simulated 禁止重新绑定。更改绑定后仍需按原授权入口显式投递，取消授权随时有效。`mail-resolve` 记录人工确认，不能猜测 unknown 已送达。

legacy 新邮件仍由 `legacy ... send-mail` 投递，保留合成报告/过期报告显式许可与 principal 校验；通用 send/mail-drain 不处理 legacy/MCP。`legacy ... outbox` 返回兼容旧 ID，增加 core_id 供核心状态查询/人工确认使用。旧 outbox 与 Core 同时存在时优先显示绑定后的 Core 状态，不双向更新旧表。

历史旧 outbox 的 pending/retry 不能直接发送，先核对原始 EML、principal 和当前 SMTP 环境配置，再显式绑定：

```powershell
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml legacy-binding-plan '<old_outbox_id>' --principal owner
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml legacy-bind '<old_outbox_id>' --principal owner --expected-plan '<plan_id>'
```

这里使用 SMTP_HOST/PORT/MODE 的进程环境设置，而非分析邮件的 TOML 端点。绑定保留原始字节、Message-ID、旧 ID、报告关联、状态及尝试次数；原表不变，sending 变 uncertain。已完成/终止记录不能激活；旧 uncertain 绑定后仍为 uncertain。之后的端点变更使用 core_id 和 mail-binding-plan/mail-bind，附同一 principal。

## MCP 历史切换界限

新 MCP 邮件使用 analysis_id/收件人/发件人/transport 四元组 ID，端点不参与身份；请求正文和幂等键被冻结。实际连接前、发现工具后再次核对端点与授权，发送期间持工作区进程锁。取消、异常或未知结果保留 uncertain，禁止自动重发。邮件工具仍只由已授权控制台调用。

匹配旧 endpoint-dependent key 的回执只读返回，sending 显示 uncertain。其他历史 marker 无法反推出收发地址/正文，因此默认报 MAIL_HISTORY_REVIEW_REQUIRED；修改端点不会绕过防重放。停止旧写入者后，管理员审阅 marker 快照并选择切换时间界限：

```powershell
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml mail-history-plan
# 时间必须含时区、不在未来；替换为实际切换界限，不能用任意早期时间绕过旧预测隔离。
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml mail-history-ack --expected-plan '<plan_id>' --not-before '<ISO8601_cutover_time>'
```

ack 只记录审阅，不迁移或发送。仅 generated_at 不早于界限的新预测可进入新 MCP 队列；旧 marker 后续变化会使审阅失效。原预测时间缺失时不猜测，也不能证明跨外部系统 exactly-once。

## 大小与后续边界

默认 limit=1000，最多 10000 条；单 EML 上限 32 MiB，批次 EML 合计 128 MiB、邮件元数据合计 16 MiB。超过上限明确停止，不将截断结果当作完整迁移；大历史库需要先按 principal/来源快照拆分，后续再增加精细分批策略。

真实工作区没有执行绑定、历史 ack、导入或发送。旧进程、外部邮件服务器和真实邮箱接收仍需独立部署验收；代码不会为此自动重启服务或重放任务。旧版本软件不认识新 Core 状态，回退前必须停写并核对已提交/uncertain 消息，不能直接恢复旧发送器处理同一历史队列。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mail_core.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mail_cutover.py -v
```

使用合成历史演练，覆盖重复导入、事务中断、原字节、来源漂移、损坏、隔离及未知回执；真实工作区仅执行只读预演。B1 结果见[提取计划](mail-core-implementation.md)，B2 结果见[切换计划](mail-cutover-plan.md)。
