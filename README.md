# Stock-Predict-Mailer

预测分析 Agent + 邮件通知服务。接收其他成员提供的模型预测结果和客观上下文，生成区分预测、事实、推断、风险与建议的报告，并可靠地投递邮件。行情采集、预测模型训练和模型运行由上游团队负责；用户私有文档与表格由本机独立清洗 Agent 整理并建立可追溯的知识库。

Python 3.11+，本机单用户工具。默认使用动态 Mock、确定性分析和本地邮件文件投递，不需要真实模型、LLM API 或邮箱凭据。

```powershell
uv sync
uv run stock-mailer --config config/agent-example.toml run --send
```

命令输出报告路径、分析状态及邮件 ID。默认 `simulated` 表示邮件写入 `data/agent-local/sent/`；真实 SMTP 返回 `submitted` 表示邮件服务器已接受。重复运行相同输入不会重复投递。使用 `run` 可仅生成报告并入队；`send <mail.id>` 可执行发送或到期重试；`mail-drain` 批量推进所有到期消息，供计划任务周期调用；`mail-resolve <mail.id> [--delivered]` 对 `uncertain` 邮件做留痕的人工确认。

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
  private_knowledge/ # 多格式解析、独立清洗、Embedding、私有复核和检索
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

## 私有知识库与独立清洗 Agent

支持数字 PDF、DOCX、UTF-8 TXT/Markdown/CSV/JSON 与 XLSX。原文件按用户加密保留，更新生成新版本；知识资料与对话记忆分开存储，复用私有访问密钥做权限隔离。检索结合关键词、可选 Embedding 和带来源及有效期的关系表，返回页码、段落或单元格位置。

```powershell
uv sync --all-extras
# 两个终端须沿用同一配置和已有的 SPM_MASTER_KEY，避免丢失已有凭据访问能力。
uv run stock-mailer --config config/local.toml console
uv run stock-mailer --config config/local.toml knowledge-worker --poll 2
# 只处理当前队列：
uv run stock-mailer --config config/local.toml knowledge-worker --once
```

上传和管理当前通过后端 `/api/knowledge` 接口完成，前端暂未增加知识库页面。上传成功表示已排队，不代表完成入库。

模型分别配置，按需启用：

- **规则清洗**无需任何模型，保留数值、单位、统计周期和来源；提供关键词与结构化关系检索。
- **Embedding**支持 Ollama `/api/embed` 和 OpenAI 兼容 `/embeddings`，用于语义检索；更换模型需先重建新索引再切换。
- **语义清洗聊天模型**支持 Ollama 原生聊天与 OpenAI 兼容聊天接口，默认关闭。启用后提取实体、关系、事件和财务指标候选，校验原文引文、日期与数值单位；候选经私有审批后才发布，失败、拒绝或待复核时旧版本继续可用。
- **股票分析模型**沿用分析配置。任务显式选择后，才将检索资料作为待分析来源发送给主模型；清洗模型不拥有训练发布或邮件权限。

清洗模型和 Embedding 凭据加密保存且不回显；向远程服务发送资料需单独允许。调用预算、逐批检查点、批准/拒绝、重试和重提取接口已提供。

完整配置、API 和验收资料：

- [私有知识库：导入、索引、检索和删除](docs/private-knowledge.md)
- [语义清洗：模型配置、证据校验与审批](docs/cleaning-agent.md)
- [清洗模型实施计划与边界](docs/cleaning-model-plan.md)

扫描件 OCR、复杂版式与表格的自动准确解析、简称消歧和真实模型准确率仍需后续验证；当前协议验收使用本地模拟服务与合成资料。单机工作区的片段和全文索引为明文，应保留本机磁盘访问控制，不宣称互联网多租户隔离或磁盘取证级擦除。

交付检查：

```powershell
uv run ruff check src tests scripts
uv run python -m compileall -q src scripts
uv run python -m unittest discover -s tests -q
python scripts/check_repo_hygiene.py
```
