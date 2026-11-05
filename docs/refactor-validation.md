# Agent 重构验收（2026-11-05）

## 已验证

- 完整回归：Windows / Python 3.11，`python -m unittest discover -s tests -q`，125 项通过，约 67 秒；103 项原有测试继续保留，新增 22 项。
- 新增测试覆盖必填字段、数值范围、时区、未来时间、过期预测/上下文、缺失上下文/置信度、JSON 重复字段/超大输入、报告转义、Agent 失败与无依据响应、邮件输出校验、幂等、失败退避与上限、发送中断与不确定状态、合成报告门禁、凭据缺失。
- 本地 socket HTTP：有效结果接入、503 明确报错；本地 socket SMTP：Mock → 分析 → 报告 → multipart MIME → SMTP DATA 接收。测试专用 SMTP 工厂跳过本地服务的 TLS/auth；生产实现强制 TLS 与认证。Fake SMTP 另覆盖超时、451/550、断线、发送次数和重试停止。
- 默认配置实际执行 `python -m stock_predict_mailer --config config/agent-example.toml run --send`，输出 analysis_status=ok、mail.status=simulated、attempts=1，并生成 JSON、HTML、EML 和独立队列数据库；重复执行验证相同 ID、attempts 不增加。
- `ruff check src tests scripts`、`compileall`、`git diff --check`、仓库 hygiene 检查通过；新默认 CLI 导入未加载 numpy/sklearn/duckdb/pyarrow/cryptography。uv.lock 已由 uv 重新生成，`uv lock --check --offline` 通过。
- 最终数值/HTTP 异常处理和线程关闭修正后，22 项新增测试再次全部通过。CI 新增不安装 research 的 Agent 专用任务（Windows/Linux），原有完整回归任务继续安装 research/trees；远端 CI 尚未执行。

## 环境说明

默认隔离环境的系统临时目录和回环网络受限，最初文件与 socket 测试失败；改用项目 .tmp 并获准在隔离环境外运行回归后通过。uv 默认缓存不可写及隔离网络不可达，改用项目 .uv-cache 并获准访问 PyPI 后更新成功。首次 SMTP 测试退出时有线程关闭竞态，已改为 shutdown 后 join。完整回归曾输出一条旧 socket 资源 ResourceWarning，但结果通过；不将其视为外部邮件验收。

## 清理与保留

旧训练依赖从默认安装移到 research 可选组，旧 CLI 迁移为 legacy_cli，新默认入口不导入研究模块。旧 README 归档，运行脚本切换新 Mock 链路，CI 保留全依赖回归。未发现可证明无依赖的业务模块，不删除旧代码。历史数据、模型、密钥、私有配置和本机工具状态均保留；详见 inventory.md 和 refactor-plan.md。

## 尚需联调

1. 数据负责人按接口提交真实事实样例，确认来源、单位、对象编码和可用时间语义。
2. 模型负责人提供预测服务/JSON，明确预测目标、周期、有效期、模型版本、confidence 与 metrics 含义；其团队决定模型文件的运行和托管方式。
3. 如需大模型解读，选择供应商并实现受约束 HTTP Agent 网关，评估真实数据质量。当前 deterministic 模式没有调用 LLM，HTTP 模式只接受契约规定的证据/推断/建议代码。
4. 邮件管理员提供测试 SMTP 与环境变量注入方式，在指定测试邮箱验证 TLS、认证、投递与退信。此次未使用真实凭据或发送外部邮件。
5. 当前为本机单用户工具，不包含 REST 入站服务、多用户认证、后台重试守护进程或批量证券任务编排；可通过 Python 接口和 CLI 独立联调。

本地 Mock 全流程及 SMTP 协议链路已完成，真实采集、训练、LLM 和外部 SMTP 的可用性不在本次验证范围。
