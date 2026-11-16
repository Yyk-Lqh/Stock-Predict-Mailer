# v1 联调契约

本文件描述 Python/CLI 和 HTTP 适配器共用的 JSON 数据结构，不要求团队同时部署网络服务。未知字段拒绝；所有必填字符串非空，数字必须有限且不能为布尔值。输入大小上限 1 MiB。schema_version 固定为字符串 `1`。

## 共同约定

时间为 ISO 8601（RFC3339 常用子集），必须含 Z 或 UTC offset，接入后转 UTC；展示按配置时区。generated_at/observed_at/available_at 不得晚于当前时刻，available_at 不早于 observed_at。valid_until 必须晚于 generated_at，当前时间到达 valid_until 或超出 max_age_seconds 即过期。预测周期由上游定义，不由本系统推算交易日。

错误统一为 `{"error":{"code":"INVALID_INPUT","message":"…","retryable":false}}`，不包含原始 HTTP 响应、凭据、内部路径或异常文本。CLI 成功退出 0，错误退出 2；邮件 retry/not_due/uncertain/failed 退出 2。代码：INVALID_INPUT、STALE_RESULT、STALE_CONTEXT、UPSTREAM_UNAVAILABLE、AGENT_UNAVAILABLE、AGENT_INVALID、CONFIG_ERROR、LOCAL_IO、MAIL_CONFIG。HTTP 网络故障 retryable=true，格式错误及过期 false。HTTP 适配器只 GET 配置的地址（不添加 query），可从指定环境变量取 Bearer token，不跟随重定向；非 2xx / 非 JSON 均明确报错。部署端负责认证、限流和 HTTPS。预测服务不接受本系统加载模型文件的请求。

运行诊断 `doctor` 使用独立的版本化预检报告：`{schema_version,version,generated_at,mode,workspace,crawler_workspace,status,summary,checks,limitations}`，逐项 `checks` 包含 component/code/status/message/details/action（action 可选）。诊断会按本机工具用途展示工作区路径，不包含任务内容或凭据。退出码 ok=0、warning=1、error=2；未完成检查明确为 warning/error，不能视为服务健康承诺。参数、WAL/Worker 边界见[运行诊断手册](runtime-diagnostics.md)。

`runtime status/start/stop/logs <component>` 仅支持 console/knowledge_worker/crawler_worker。状态包含 state/ownership、已登记时的 instance/pid/phase/configuration/时间等公开字段；logs 返回白名单 events。stop 必须携带 `--instance`，只写实例匹配请求，不使用 PID 信号；非阻塞返回 stop_requested，等待超时返回 stopping/timed_out。正常/未登记/停止退出 0，未知/切换/等待超时退出 1，身份冲突/失败/非法记录及操作错误退出 2。登记和操作边界见[运行管理手册](runtime-lifecycle.md)。

`backup plan/create/verify/restore` 提供独立数据保护入口。plan 返回 ready/blockers、文件范围/摘要、counts/limits/vaults 与 plan_id；create 必须携带 --expected-plan，仅发布不可覆盖的整体认证加密包。verify/restore 不依赖原 TOML，restore 仅支持全新隔离目录并暂停未决队列。备份密钥来自独立环境引用，外部 MASTER_KEY 不导出；成功退出 0，阻断/错误退出 2。范围、错误和容量限制见[备份恢复手册](workspace-backup.md)。

`db status/plan` 返回独立的 schema_version=1 报告，包含 app_version/catalogue_id/sqlite_version、state/ready/changes、逐库 source_id/schema_id、结构推断 features 和已知固定 operations。未知结构/版本阻断；缺失库不创建。plan 增加 plan_id/requires_permission_review/ready_for_apply=false；`--rehearse --expected-plan` 只在一次性副本内事务执行、验证并回滚，返回 committed=false/source_writes=0。当前/缺失/演练成功退出 0，已知升级退出 1，阻断/错误退出 2。完整语义见[数据库结构手册](schema-planning.md)。

数据库 `db preflight` 使用独立的 `read_only_migration_preflight` 报告：ready/blockers、schema_plan_id/backup_plan_id、backup_verified、认证包 archive_sha256、成功时 preflight_id、changes/requires_permission_review 和 source_writes=0。只支持全部库；ready_for_apply 始终 false。通过退出 0，阻断或错误退出 2；语义见[迁移就绪检查](migration-preflight.md)。

显式 `db migrate` 必须单选 store，携带 archive、expected-plan、expected-preflight，授权回填另需 accept-authorization-change。成功返回 mode=single_store_migration、state=migrated/ already_current、committed/source_writes、摘要与操作行数；真实提交还返回 application_id/user_version、schema_before/after 和 receipt_id。成功退出 0，错误退出 2；提交不明和已提交后失败使用独立错误码，不能当作无修改。参见[迁移手册](database-migration.md)。

`forecast register/list/show/evaluate` 为独立文件归档入口，沿用 v1 prediction；definition 和 observation 使用严格 schema_version=1。注册返回 created/record，record 包含 forecast_id/registered_at、固定 prediction/definition、content_id/integrity_id。list 支持 as-of/limit/offset，返回 total/returned/next_offset 及 pending/due/evaluated 视图。evaluate 输出 not_due/awaiting_observation/evaluated、synthetic/as_of/persisted，成功评分含完整观测、metrics 和回执时间/摘要。未到期或缺可用观测退出1；成功0，错误2。具体时间、日历、十进制阈值和不可覆盖约定见[预测归档与评估](forecast-evaluation.md)。

`run --evaluation-definition PATH` 和 `POST /api/tasks` 的可选 `evaluation_definition` 对象显式启用分析任务归档。接收/执行时校验定义，执行时使用同一次经过 v1 校验的预测注册，随后才调用上下文工具、知识检索和分析模型。冲突或归档失败阻断后续操作；已注册记录在后续失败/取消时保留。分析可选 `forecast_evidence` 字段严格包含 schema_version/forecast_id/registered_at/definition/content_id/integrity_id，通过与 analysis.prediction 重建完整记录校验摘要，不需要磁盘读取。CLI 输出额外 forecast.created 及证据；任务进度 forecast 事件含 forecast_id/created。定义不从会话继承。见[任务联动](forecast-tasks.md)。

控制台只读 `GET /api/forecasts` 按可访问任务分页，接受 limit/before/state，返回 items/as_of/scanned_tasks/next_before；状态筛选与任务游标分页独立，空页可继续。`GET /api/tasks/{id}/forecast` 沿用任务 owner 权限，返回完整记录与回执，不接受任意 forecast_id，也不暴露 CLI 独立档案。两者没有写方法，响应上限 2 MiB；详细权限、读取预算及表单行为见[控制台归档](forecast-console.md)。

`POST /api/tasks/{id}/forecast/preview` 沿用同源本机会话、CSRF 与任务 owner 权限，只接受 observation 对象，或 format=json/csv 与 content 原文，可附 as_of；导入上限 256 KiB。不接受文件路径和保存选项。先严格校验匹配，再按同份归档快照计算 ready/not_due/awaiting_observation；persisted 恒 false，仅 ready 有 metrics，没有正式 evaluation 回执。返回标准观测/原文/预测内容摘要，来源声明未认证。见[观测导入与预览](observation-preview.md)。

## 采集模块 → 系统

顶层必填 schema_version、context_id、subject、facts。facts 为数组，可为空。每项必填 id（本批唯一）、name、value（有限数字或非空字符串）、unit、source、observed_at、available_at；无可选字段。subject 必须与预测对象一致。每条事实独立做 max_context_age_seconds 检查，不允许未来可用信息或静默丢弃过期事实。

```json
{"schema_version":"1","context_id":"ctx-001","subject":"DEMO.SZ","facts":[{"id":"f1","name":"收盘价","value":10.2,"unit":"CNY","source":"mock","observed_at":"2026-11-05T07:00:00Z","available_at":"2026-11-05T07:01:00Z"}]}
```

这仅是已处理事实接口；原始采集文件可继续交给旧 intake 模块，清洗和指标计算由上游负责。source 是上游声明，系统不声称独立核实其真实性。

## 预测服务 → Agent

必填 schema_version、prediction_id、subject、generated_at、valid_until、horizon、model_version、synthetic。horizon 必填 value（1..365 正整数）、unit（trading_days/calendar_days/hours）。可选 direction（up/down/flat）、value（数值）、value_unit（提供 value 时必填）、confidence（0..1 或 null）、metrics（字符串键到有限数值的映射，默认 {}）。direction/value 至少一项。prediction_id 标识上游结果版本，内容变化应使用新 ID。synthetic 是布尔值，不能省略或猜测。

```json
{"schema_version":"1","prediction_id":"pred-001","subject":"DEMO.SZ","generated_at":"2026-11-05T07:05:00Z","valid_until":"2026-11-06T07:05:00Z","horizon":{"value":5,"unit":"trading_days"},"direction":"up","confidence":null,"model_version":"team-model-v1","synthetic":true,"metrics":{}}
```

支持 mock、file、http 预测适配器；上下文支持 none/mock/file/http。静态示例会过期，日常演示用动态 Mock。模型文件交付属于其他成员的运行服务职责：预处理、特征顺序、依赖及版本由其服务封装，本阶段不接收或反序列化模型二进制文件。

## Agent → 邮件服务

上下文另支持本地 `crawler` 适配器，读取有哈希元数据及完整任务标记的基本面视图；需要显式 file/http 预测。用法见[单标的分析](single-symbol-analysis.md)。可选 `input_evidence` 与 chart_data 一样位于严格 v1 context 之外，进入 analysis 后绑定原始预测、上下文和来源字段，参与 analysis_id 摘要并在报告与邮件中显示引用。原有 v1 字段与 file/http 行为保持兼容。

分析结果由 `AnalysisAgent.analyze(prediction, context)` 生成。必填 schema_version、analysis_id（规范内容摘要）、generated_at（沿用预测生成时间以稳定幂等）、status（ok/degraded）、mode、prediction（完整标准化契约）、facts、inferences、recommendations、limitations、risks。facts 为已校验客观数据；inferences 每条含 code、text、evidence_ids；recommendations/limitations/risks 为字符串数组。报告摘要及时间显示不修改预测含义。degraded 明确说明 Agent 故障；confidence 缺失显示“未提供”，不推测。

邮件调用 `MailService.enqueue(analysis, recipient)` → `{id,status,attempts,next_attempt,error}`；收件人必填且为单一邮箱，发件人来自配置，禁止头部换行。`deliver(id)` 返回相同状态。邮件内容由分析对象渲染 JSON + HTML，并生成 text/plain + text/html MIME；只接受通过分析输出验证的对象，内容摘要必须匹配。邮件状态：pending → sending → submitted（SMTP 接收）/simulated（file）/retry/failed/uncertain。下一次到期调用 send 重试；无内置后台调度器。消息以分析内容+收发件人+传输方式幂等，相同内容重复调用不会重新发送。分析身份不含邮件配置，同一分析可投递多个收件人。

新消息冻结公开端点和凭据引用，漂移返回 MAIL_ENDPOINT_CHANGED；已有尝试但缺绑定的历史消息返回 MAIL_BINDING_REQUIRED。`binding_plan(id)` 只读，`bind(id, expected_plan)` 显式更新绑定且不发送、不清除 uncertain/attempts。legacy/MCP 新写入口共用 MailCore，保留原授权入口；通用 deliver/drain 不代替它们发送。旧 outbox/mcp_mail 只读，历史激活/回执时间界限须显式审阅。完整命令、边界及新增错误见[MailCore 手册](mail-core-migration.md)。

## 可选 HTTP Agent 策略接口

POST 配置地址，输入 `{"prediction":<v1>,"context":<v1或null>}`；输出严格为 `{"evidence_ids":["f1"],"inference_codes":["MODEL_UP"],"recommendation_codes":["VERIFY"]}`。允许推断 MODEL_UP/MODEL_DOWN/MODEL_FLAT/INSUFFICIENT；方向推断必须匹配输入方向。建议只允许 VERIFY/DIVERSIFY/WAIT。不允许任意生成的数值或文本进入报告。无 facts 时 evidence_ids 为空。HTTP 请求/响应均 1 MiB 上限，超时可配置；错误回退确定性分析且 status=degraded。此接口可由团队选择的 LLM 网关实现，网关需要自行约束模型输出。

## 团队联调交付

数据成员提供有来源、单位、观测和可用时间的事实，以及缺失/延迟样例。模型成员提供目标含义、周期、版本、有效期、预测数值单位，说明 confidence 是否校准、metrics 定义；不得把 score 当 confidence。共同确认对象编码、时区、交易日定义和新鲜度配置。Agent 成员维护本文件及 Mock；邮件管理员提供测试 SMTP、发件地址和凭据环境变量。本地文件投递及测试 SMTP 验收不等于真实邮箱到达验收。
