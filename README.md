# Stock-Predict-Mailer

预测分析 Agent + 邮件通知服务。接收其他成员提供的模型预测结果和客观上下文，生成区分预测、事实、推断、风险与建议的报告，并可靠地投递邮件。数据采集、处理、训练和模型运行由上游团队负责。

Python 3.11+，本机单用户工具。默认使用动态 Mock、确定性分析和本地邮件文件投递，不需要真实模型、LLM API 或邮箱凭据。

```powershell
uv sync
uv run stock-mailer --config config/agent-example.toml run --send
```

命令输出报告路径、分析状态及邮件 ID。默认 `simulated` 表示邮件写入 `data/agent-local/sent/`；真实 SMTP 返回 `submitted` 表示邮件服务器已接受。重复运行相同输入不会重复投递。使用 `run` 可仅生成报告并入队；`send <mail.id>` 可执行发送或到期重试。

模型/MCP/A2A 配置控制台已提供。设置服务端 `SPM_MASTER_KEY` 后运行 `uv run stock-mailer console --port 8767`，打开本机页面管理模型、加密凭据、工具授权、角色温度和分析任务。启动及完整 Mock 验收见 [控制台手册](docs/control-console.md)，后端接口见 [配置与协议 API](docs/control-api.md)。默认 CLI `run` 继续独立可用。

目录结构：

```text
src/stock_predict_mailer/
  agent_service/
    contracts.py   # 预测/事实/错误契约与时效校验
    adapters.py    # Mock / file / HTTP 接入
    analysis.py    # 确定性 Agent / 受约束 HTTP Agent
    reporting.py   # JSON、HTML 与邮件正文
    mail.py        # 独立 SQLite outbox、SMTP、重试和去重
    config.py      # TOML 配置，凭据仅引用环境变量
  cli.py           # 新默认入口
  legacy_cli.py    # 旧研究、训练、上传兼容入口
  control/         # 配置界面/API、凭据库、模型/MCP/A2A、编排与预算
  core.py          # 复用原子文件写入等基础设施
config/agent-example.toml
examples/prediction.json
examples/context.json
tests/test_agent_service.py
docs/
```

- [接口契约、字段及示例](docs/interfaces.md)：采集 → 系统、预测 → Agent、分析 → 邮件及可选 HTTP Agent 协议。
- [项目介绍与前端开发交接](docs/frontend-handoff.md)：业务边界、页面任务、字段与接口、状态展示、同源部署约束及 Mock 验收，供接手前端的开发者优先阅读。
- [混合执行与图表进度](docs/hybrid-execution.md)记录五档推理预算、时间序列契约、进度接口和邮件图表配置。
- [会话记忆](docs/conversation-memory.md)介绍追问续接、上下文压缩、向量检索和管理接口。
- [运行与邮件配置](docs/mail-and-running.md)：真实 SMTP、环境变量、新鲜度、失败处理及真实上游适配。
- [重构方案与清理说明](docs/refactor-plan.md)、[保留文件清单](docs/inventory.md)。
- [验收记录](docs/refactor-validation.md)：测试结果、边界及待团队配合事项。

Agent 不补造缺失置信度或事实；数据过期或接口不合规会报错；HTTP Agent 失败会明确标记降级。默认分析不调用 LLM；可选 HTTP Agent 只能选择已提供证据及预定义推断/建议，详见契约。股票分析不保证收益。

历史数据、模型、签名材料及旧模块全部保留。训练等依赖移到 `research` 可选组；需要旧功能时安装 `uv sync --extra research --extra trees --extra dev`，再使用 `stock-mailer legacy ...`。旧文档见 [归档说明](docs/legacy-readme.md)。

新链路测试：

```powershell
uv run python -m unittest discover -s tests -p test_agent_service.py -v
```

完整回归需要 research/trees 可选依赖；执行 `uv run python -m unittest discover -s tests -v`。项目继续使用 unittest，不引入新的服务框架。
