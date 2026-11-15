# 本机运行诊断

`doctor` 在不启动业务的情况下汇总工作区、数据库、队列、密钥和本机端口的检查结果。新工作区也能执行；不会初始化数据库、生成开发密钥、恢复任务、采集数据、调用模型或发送邮件。

## 使用

```powershell
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml doctor

# 完全跳过套接字检查，指定另一个采集工作区：
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml doctor --skip-port-check --crawler-workspace 'D:\data\crawler'

# 检查准备启动的新控制台实例是否能使用另一个端口：
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml doctor --port 8768
```

应用工作区来自 TOML；采集工作区优先使用 `--crawler-workspace`，否则沿用 `STOCK_PREDICT_MAILER_CRAWLER_WORKSPACE`，再否则使用**当前命令目录**下的 `data/crawler`，与现有采集入口一致。两个工作区可以不同。`--config` 放在子命令之前。

输出为 JSON，包含 `schema_version`、版本、检查时间、工作区路径、整体 `status`、`summary`、`checks` 和限制说明。每项包含 component/code/status/message/details；需要处理时附 action。code 可供脚本识别，message/action 为阅读提示。输出只有聚合计数和状态，不包含收发邮箱、文档名、任务内容、API Key、SMTP 密码或原始异常文本。

退出码：0 表示本次预检未发现待处理问题；1 表示 warning，需要查看检查项；2 表示 error 或配置错误。warning 可能是未初始化工作区、待执行队列、未知运行状态或延期检查，不表示数据已损坏。0 也不表示外部业务已经验证成功。

## 能检查什么

- 工作区是否存在且为目录。为保持源目录不变，不通过写文件验证写权限。
- pandas/requests/baostock/numpy/sklearn 是否可发现，只查安装状态，不导入这些可选模块。执行采集的依赖缺失且已有排队任务时会提示安装。
- CLI TOML 选择 SMTP 时，其 user_env/password_env 引用是否非空。只检查是否配置，不记录值、不登录 SMTP；控制台内另存的邮件策略不在这项检查范围内。
- 已存在的 agent-mail、正式/开发 control、旧 state、私有知识库和 crawler-jobs 数据库：quick_check、诊断所需的表/列、任务状态计数、未决邮件、待处理资料/采集及历史 MCP 回执。不会运行应用构造函数或 schema 迁移。
- 密钥模式遵循当前进程 MASTER_KEY 环境变量，与控制台一致；开发模式核对配套 `control-development.key`。只验证已有 vault_check，不读 profiles 的凭据列。没有 marker 时显示 unverified，存在正式库但当前选择开发模式时明确提醒，避免误以为配置丢失。
- 已有 pipeline.lock、私有知识库 pipeline.lock 和采集 .crawler.lock 的瞬时共享锁状态。绝不创建/删除锁文件，不根据文件存在就判定 Worker 存活。升级后的三个前台组件会另行登记身份/心跳，doctor 可结合 OS 创建标识与终身锁校验，见[运行管理手册](runtime-lifecycle.md)。
- 默认在 127.0.0.1 短暂 bind 后立即关闭，检查新实例的端口可用性；不 listen、不 connect、不发送 HTTP。端口占用也可能是正确运行的原控制台，或系统保留端口，不会自动换端口、结束进程或冒认服务身份。

## 常见结果与处理

- `DB_NOT_INITIALIZED`：可选数据库尚未创建。诊断不会代替初始化。
- `DB_SCHEMA_INCOMPATIBLE`：已有库缺少预期表/列。核对软件版本和备份，单独制定迁移；不要删除库重新运行。
- `DB_BUSY`：锁竞争导致只读检查无法完成。稍后重试，不能据此抢占写入者。
- `DB_CORRUPT` / `DB_UNREADABLE`：检查未通过。停止额外写入后核对存储、权限与备份，工具不会修复。
- `DB_WAL_CHECK_DEFERRED`：检测到 WAL 模式或 sidecar，本次**没有打开这个数据库**。只读 SQLite 连接仍可能创建/修改协调文件；使用 immutable 又会忽略尚未 checkpoint 的 WAL 提交。因此本批明确延期，不报告虚假的“空队列/健康”。后续快照/备份工具负责进一步核对；不要删除 WAL/SHM，旧 state 库正常也可能出现此提示。
- `TASK_SCAN_LIMIT`：控制台任务计数不完整。最多扫描 1000 行，每行最多 1 MiB JSON、总计最多 8 MiB；不能以截断计数推断全部任务都完成。异常 JSON/状态计入 unknown。
- `WORKER_REQUIRED` / `ANALYSIS_RUNTIME_UNKNOWN`：有持久化任务，但不能确认对应运行进程。查看正确工作区的 Worker/控制台；启动 Worker 可能立即执行真实任务，需要单独显式操作。
- `INTERRUPTION_SUSPECTED`：有活动状态记录，但当前未观察到持锁写入者。它是待核对迹象，不是自动恢复指令。采集任务按[Worker 手册](crawler-jobs.md)处理；知识导入按原 Worker 流程处理。
- `MAIL_OUTCOME_REVIEW` / `MAIL_BINDING_REVIEW` / `MCP_HISTORY_PRESENT`：按[邮件手册](mail-core-migration.md)先核对来源与发送结果，再执行明确的人工步骤。已完成的旧邮件不会因缺少端点而被要求重新绑定。
- `VAULT_KEY_MISSING` / `VAULT_KEY_INVALID` / `VAULT_KEY_MISMATCH`：恢复原配套密钥，勿为旧数据库生成替代密钥。密钥在当前诊断进程可用，也不代表后台进程继承了它。
- `PORT_UNAVAILABLE`：新实例不能占用指定端口。先确认已有服务和系统保留规则；要启动另一个实例时显式选端口。

建议都是文字，不会作为命令执行。诊断不会输出进程命令行、读取外部服务凭据或调用探测接口。

## 验证范围与后续

SQLite 检查使用只读连接、query_only、独立事务、200 ms busy timeout 和每库约 2 秒 SQLite VM 查询预算；预算不是底层磁盘 I/O 的硬超时。各库分别取快照，没有跨库一致性保证；检查期间不要改 journal 模式或替换数据库文件。WAL 库明确延期。

升级后通过原 CLI 或 runtime start 运行的组件具有独立心跳；未重新启动的旧进程和直接调用库函数的进程仍没有登记。知识 Worker 在轮询时持续持业务锁，采集 Worker 只在执行时持业务锁；因此不能仅用业务锁区分 idle 与未启动。COMPONENT_VERIFIED/WORKER_CONFIRMED 表示实例证据通过，仍不代表任务有进展；未登记或无法核对时继续显示 unknown/not_available。不能把 available 当作进程已退出，也不能仅把 busy 当作目标 Worker 已确认正常。

第五阶段 B 已提供组件归属/Worker 心跳、受控启停和日志轮转；之后提供一致性备份清单及独立目录恢复演练。doctor 本身仍不会变更正在运行的服务，也不验证真实模型质量或邮箱收件。
