# v1 联调契约

本文件描述 Python/CLI 和 HTTP 适配器共用的 JSON 数据结构，不要求团队同时部署网络服务。未知字段拒绝；所有必填字符串非空，数字必须有限且不能为布尔值。输入大小上限 1 MiB。schema_version 固定为字符串 `1`。

## 共同约定

时间为 ISO 8601（RFC3339 常用子集），必须含 Z 或 UTC offset，接入后转 UTC；展示按配置时区。generated_at/observed_at/available_at 不得晚于当前时刻，available_at 不早于 observed_at。valid_until 必须晚于 generated_at，当前时间到达 valid_until 或超出 max_age_seconds 即过期。预测周期由上游定义，不由本系统推算交易日。

错误统一为 `{"error":{"code":"INVALID_INPUT","message":"…","retryable":false}}`，不包含原始 HTTP 响应、凭据、内部路径或异常文本。CLI 成功退出 0，错误退出 2；邮件 retry/not_due/uncertain/failed 退出 2。代码：INVALID_INPUT、STALE_RESULT、STALE_CONTEXT、UPSTREAM_UNAVAILABLE、AGENT_UNAVAILABLE、AGENT_INVALID、CONFIG_ERROR、LOCAL_IO、MAIL_CONFIG。HTTP 网络故障 retryable=true，格式错误及过期 false。HTTP 适配器只 GET 配置的地址（不添加 query），可从指定环境变量取 Bearer token，不跟随重定向；非 2xx / 非 JSON 均明确报错。部署端负责认证、限流和 HTTPS。预测服务不接受本系统加载模型文件的请求。

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

分析结果由 `AnalysisAgent.analyze(prediction, context)` 生成。必填 schema_version、analysis_id（规范内容摘要）、generated_at（沿用预测生成时间以稳定幂等）、status（ok/degraded）、mode、prediction（完整标准化契约）、facts、inferences、recommendations、limitations、risks。facts 为已校验客观数据；inferences 每条含 code、text、evidence_ids；recommendations/limitations/risks 为字符串数组。报告摘要及时间显示不修改预测含义。degraded 明确说明 Agent 故障；confidence 缺失显示“未提供”，不推测。

邮件调用 `MailService.enqueue(analysis, recipient)` → `{id,status,attempts,next_attempt,error}`；收件人必填且为单一邮箱，发件人来自配置，禁止头部换行。`deliver(id)` 返回相同状态。邮件内容由分析对象渲染 JSON + HTML，并生成 text/plain + text/html MIME；只接受通过分析输出验证的对象，内容摘要必须匹配。邮件状态：pending → sending → submitted（SMTP 接收）/simulated（file）/retry/failed/uncertain。下一次到期调用 send 重试；无内置后台调度器。消息以分析内容+收发件人+传输方式幂等，相同内容重复调用不会重新发送。分析身份不含邮件配置，同一分析可投递多个收件人。

## 可选 HTTP Agent 策略接口

POST 配置地址，输入 `{"prediction":<v1>,"context":<v1或null>}`；输出严格为 `{"evidence_ids":["f1"],"inference_codes":["MODEL_UP"],"recommendation_codes":["VERIFY"]}`。允许推断 MODEL_UP/MODEL_DOWN/MODEL_FLAT/INSUFFICIENT；方向推断必须匹配输入方向。建议只允许 VERIFY/DIVERSIFY/WAIT。不允许任意生成的数值或文本进入报告。无 facts 时 evidence_ids 为空。HTTP 请求/响应均 1 MiB 上限，超时可配置；错误回退确定性分析且 status=degraded。此接口可由团队选择的 LLM 网关实现，网关需要自行约束模型输出。

## 团队联调交付

数据成员提供有来源、单位、观测和可用时间的事实，以及缺失/延迟样例。模型成员提供目标含义、周期、版本、有效期、预测数值单位，说明 confidence 是否校准、metrics 定义；不得把 score 当 confidence。共同确认对象编码、时区、交易日定义和新鲜度配置。Agent 成员维护本文件及 Mock；邮件管理员提供测试 SMTP、发件地址和凭据环境变量。本地文件投递及测试 SMTP 验收不等于真实邮箱到达验收。
