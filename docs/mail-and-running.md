# 本地运行、邮件与适配联调

## 开始

Python 3.11+，在仓库根目录执行：

```powershell
uv sync
uv run stock-mailer --config config/agent-example.toml run --send
```

无 uv 时可以 `python -m pip install -e .` 后 `python -m stock_predict_mailer run --send`。已有 .venv 可直接 `.venv/Scripts/python.exe -m stock_predict_mailer run --send`。

默认 Mock 每小时产生一份稳定结果，重复调用相同内容不重复发送；跨小时产生新通知。这是演示 ID 策略，真实上游应使用自身预测批次 ID。静态 examples/*.json 用于契约阅读，会按有效期过期；需要文件演示时由上游更新所有时间与 ID。Mock 收盘价纯属合成数据。

Mock 上下文还携带 `chart_data`（observed / forecast / backtest 三条合成序列，forecast 带预测区间）。它不进上下文契约，由分析层单独校验后渲染，因此演示邮件内嵌两张 PNG 图表：历史观测与预测、实际值与历史预测（含配对 MAE）。邮件客户端不渲染内联 SVG，图表一律以 PNG 附件或 CID 引用出现；每张约 0.75 MB，一封演示邮件约 2 MB。

产物在 `data/agent-local/`：`analysis/<analysis_id>/analysis.json`、`report.html`；`agent-outbox/<id>.eml` 入队 MIME；`sent/<id>.eml` 为 file 模拟投递结果；`agent-mail.sqlite3` 为新邮件状态，独立于旧 state.sqlite3；`pipeline.lock` 是 OS 锁文件，文件存在本身不表示进程占锁。JSON 保留 UTC，HTML 显示配置时区。

`run` 仅生成报告并入队；`run --send` 按配置执行一次投递。命令输出 mail.id，可随后执行：

```powershell
uv run stock-mailer --config config/agent-example.toml mail-status <mail.id>
uv run stock-mailer --config config/agent-example.toml send <mail.id>
```

file 的 simulated 表示本机文件已投递，绝不表示真实邮箱收到。SMTP 的 submitted 表示服务器已接受邮件，最终到达仍由邮件服务器决定。

### 到期重试与人工确认

退避只在被再次调用时才推进，进程不会自己醒来。`mail-drain` 扫描所有到期消息，由计划任务周期执行：

```powershell
uv run stock-mailer --config config/agent-example.toml mail-drain --limit 20
./scripts/mail-drain.ps1
```

它只处理 `pending`/`retry` 且 `next_attempt` 已到的消息，按到期顺序逐条投递；单条消息的配置或完整性问题不会中断整批，而是随该条结果返回错误码。存在未结清（retry/failed/uncertain）消息时退出码为 2，便于计划任务发现异常，不把部分失败当成功。

`uncertain` 不会自动重发。核对邮件服务器日志或收件箱后，用 `mail-resolve` 写入一次审计再决定后续：

```powershell
uv run stock-mailer --config config/agent-example.toml mail-resolve <mail.id>              # 确认未送达，回到 retry
uv run stock-mailer --config config/agent-example.toml mail-resolve <mail.id> --delivered  # 确认已送达，记为 submitted
```

审计写在工作区 `agent-mail.sqlite3` 的 `mail_audit` 表，且先写审计再改状态。非 `uncertain` 状态的邮件不接受确认，避免把已结清的消息再次推进队列。确认未送达后的重发仍可能造成重复邮件，SMTP 没有 exactly-once 保证。

## 配置真实邮件

复制 `config/agent-example.toml` 为被忽略的 `config/local.toml`。使用该路径时必须传 `--config config/local.toml`。设置 mail.transport="smtp"，填写管理员提供的 host、port、sender、recipient；tls 为 starttls（常见 587）或 ssl（常见 465）。两种模式都验证 TLS 证书，不提供明文 SMTP 生产选项。

凭据通过当前进程的 SMTP_USER、SMTP_PASSWORD 环境变量提供；user_env/password_env 可指定其他变量名。密码使用邮箱服务的 SMTP 授权凭据。不要将真实值写入配置或提交；本次不修改任何已有凭据。避免将凭据写入终端历史，按本机秘密管理方式注入进程。发送合成测试邮件还必须显式 allow_synthetic=true；真实预测应由上游标 synthetic=false。

调用 `run --send --recipient <收件邮箱>` 覆盖单个收件人。每个地址单独入队，多收件人由调用方逐个调用，避免部分成功语义。`mail.recipient_allowlist` 非空时是硬闸门：命令行覆盖也必须命中名单，否则入队即被拒绝，配置文件或控制台改不动这一条。SMTP 与 file 使用不同幂等身份，切换传输方式后需重新 run，不能对原有队列更换传输。

安全失败最多尝试 max_attempts 次（默认 3，配置上限 10）；等待 retry_seconds * 2^(attempts-1) 秒后才能重试，默认 60/120/240 秒。没有常驻后台 worker；到期消息由 `mail-drain` 或 `send` 显式推进，调度器负责周期调用前者。pending/retry 投递前重新检查预测和上下文新鲜度；已过期结果应重新请求上游，而非强行发送。

failed 为确定失败或重试耗尽；uncertain 为 DATA 期间断线或发送中进程中断，可能已经送达。系统不会自动重发 uncertain。应先查服务端日志或收件箱，再用 `mail-resolve` 记录结论并决定是否回到 retry；这个过程不判断服务端真实状态，只固化人工判断并留痕。Message-ID 与 `Date` 头稳定，但 SMTP 无严格 exactly-once 保证。

日志/错误只记录异常类型，不回显服务端错误正文、认证信息。SQLite、EML 和报告均含用户数据，工作区应按本机账户权限保管；本系统是单用户本机工具，没有多租户身份认证。

## 切换真实上游与 Agent

prediction.adapter="http" 并填 url（GET 返回预测契约）；context.adapter="http" 并填上下文地址，或使用 file/path。所有相对文件路径均相对于配置文件，而非当前目录。token_env 可指向 Bearer token 环境变量。HTTP 超时默认 15 秒，不盲目重试不合规输入。需多证券或动态查询时，在独立适配器中实现并逐条交给相同 Agent，避免更改核心邮件逻辑。

缺少上下文时显式设 context.adapter="none"；配置了上下文但服务故障时流程报错，不静默装作上下文为空。max_age_seconds/max_context_age_seconds 独立配置新鲜度，valid_until 是上游有效期硬限制。

agent.provider="http" 时调用 [接口文档](interfaces.md) 的有约束策略服务；默认 deterministic 不调用大模型。为防编造，当前 HTTP 协议只支持选择证据和预定义推断/建议代码，不接受自由文本市场结论。可由其他供应商 LLM 网关实现该协议。事实显示为上游声明，不将收盘价自动解释为预测涨跌的原因；上下文中的提示词也不会作为命令执行。

## 旧功能与测试

旧研究、上传、训练和模型包仍保留。安装 `uv sync --extra research --extra trees --extra dev`，旧命令在 stock-mailer 后加 legacy，例如 `uv run stock-mailer legacy --config config/example.toml init`。旧操作手册见 [归档 README](legacy-readme.md)，其中命令需要相同 legacy 前缀。旧模块 Python 导入路径不变（旧 CLI 为 legacy_cli）。不再默认训练，也不默认加载模型文件。

仅验证新链路可 `uv run python -m unittest discover -s tests -p test_agent_service.py -v`；完整回归需 research/trees 依赖，再执行 `uv run python -m unittest discover -s tests -v`；lint 为 `uv run ruff check src tests scripts`。协议测试只用本机回环 HTTP/SMTP，不接真实模型或外部邮箱；测试 SMTP 工厂跳过 TLS/auth，生产路径强制 TLS/auth。

待成员配合：按接口交付成功/缺失/过期样例、确定周期单位与预测指标含义、提供带认证的服务地址；邮件管理员提供测试 SMTP 并验收真实到达；选定 LLM 后实现有约束网关及模型输出质量评估。部署、后台重试 worker、多用户服务和自由文本 LLM 解读未包含在本阶段。

### 邮件图表兼容性

新入队邮件的 inline 与 attachment 图表均使用标准库生成的确定性 PNG；inline 保持原 CID。图例、来源、单位、时间范围和预测区间说明由 HTML 渲染。网页报告仍保留 SVG。已入队 EML 不重新生成。PNG 不含时间戳或文本元数据。

### 查询队列

`uv run stock-mailer --config config/local.toml mail-list --limit 20 --status pending` 输出 JSON 数组，最新入队优先。省略 status 列出所有状态；limit 为 1–1000（默认 20）。每行含 id/recipient/sender/transport/status/attempts/next_attempt/error，空列表也返回 0。仅查询，不触发投递。

`[mail].sender_name` 可选，例如 `sender_name = "研究报告"`，通过标准库 formataddr 编码 From 显示名。拒绝 CR/LF；不改变 SMTP 信封地址、幂等 ID 或已入队 EML。
