# Stock-Predict-Mailer

预测分析 Agent + 邮件通知服务。接收其他成员提供的模型预测结果和客观上下文，生成区分预测、事实、推断、风险与建议的报告，并可靠地投递邮件。行情采集、预测模型训练和模型运行由上游团队负责；用户私有文档与表格由本机独立清洗 Agent 整理并建立可追溯的知识库。

Python 3.11+，本机单用户工具。默认使用动态 Mock、确定性分析和本地邮件文件投递，不需要真实模型、LLM API 或邮箱凭据。

项目名统一为 **Stock-Predict-Mailer**：发行名 `stock-predict-mailer`，导入名 `stock_predict_mailer`，环境变量前缀 `STOCK_PREDICT_MAILER_`。三种形式的分工与检查脚本见 [命名约定](CONTRIBUTING.md#5-命名约定)，唯一来源是 `src/stock_predict_mailer/naming.py`。

```powershell
uv sync
uv run stock-predict-mailer --config config/agent-example.toml run --send
```

命令输出报告路径、分析状态及邮件 ID。默认 `simulated` 表示邮件写入 `data/agent-local/sent/`；真实 SMTP 返回 `submitted` 表示邮件服务器已接受。重复运行相同输入不会重复投递。使用 `run` 可仅生成报告并入队；`send <mail.id>` 可执行发送或到期重试；`mail-drain` 批量推进所有到期消息，供计划任务周期调用；`mail-resolve <mail.id> [--delivered]` 对 `uncertain` 邮件做留痕的人工确认。

模型/MCP/A2A 配置控制台已提供。运行 `uv run stock-predict-mailer console --port 8767` 即可启动；未设置 `STOCK_PREDICT_MAILER_MASTER_KEY` 时自动使用独立的本机开发配置库与开发密钥。设置该变量后使用原加密配置库。打开本机页面管理模型、加密凭据、工具授权、角色温度和分析任务。启动及完整 Mock 验收见 [控制台手册](docs/control-console.md)，后端接口见 [配置与协议 API](docs/control-api.md)。默认 CLI `run` 继续独立可用。

控制台现采用会话式工作台：左侧会话导航、中间分析与追问、右侧报告与证据，并提供知识资料上传、清洗审阅、检索及索引配置。使用与前端构建说明见 [会话式工作台](docs/console-workbench.md)。

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
  naming.py        # 项目名的唯一来源（专有名/发行名/导入名/环境变量前缀）
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
- [小马证券分析大厅](docs/securities-hall.md)：工位与通道、行情墙的真实/演示边界、本机行情中继的配置与状态。
- [会话记忆](docs/conversation-memory.md)介绍追问续接、上下文压缩、向量检索和管理接口。
- [运行与邮件配置](docs/mail-and-running.md)：真实 SMTP、环境变量、新鲜度、失败处理及真实上游适配。
- [重构方案与清理说明](docs/refactor-plan.md)、[保留文件清单](docs/inventory.md)。
- [验收记录](docs/refactor-validation.md)：测试结果、边界及待团队配合事项。

Agent 不补造缺失置信度或事实；数据过期或接口不合规会报错；HTTP Agent 失败会明确标记降级。默认分析不调用 LLM；可选 HTTP Agent 只能选择已提供证据及预定义推断/建议，详见契约。股票分析不保证收益。

历史数据、模型、签名材料及旧模块全部保留。训练等依赖移到 `research` 可选组；需要旧功能时安装 `uv sync --extra research --extra trees --extra dev`，再使用 `stock-predict-mailer legacy ...`。旧文档见 [归档说明](docs/legacy-readme.md)。

新链路测试：

```powershell
uv run python -m unittest discover -s tests -p test_agent_service.py -v
```

完整回归需要 research/trees 可选依赖；执行 `uv run python -m unittest discover -s tests -v`。项目继续使用 unittest，不引入新的服务框架。

启动排查可运行 `uv run stock-predict-mailer --config config/agent-example.toml doctor`，只读检查工作区、队列、密钥和端口。结果及处理边界见[运行诊断手册](docs/runtime-diagnostics.md)；诊断不会自动启动 Worker 或恢复、重发任务。

组件身份、心跳、显式后台启动、实例匹配停止和有界事件日志见[运行管理手册](docs/runtime-lifecycle.md)。可先使用 `runtime status console` 查询；未登记的旧进程不会被自动接管。

加密快照、WAL 合并、密钥配套及全新目录恢复见[备份恢复手册](docs/workspace-backup.md)。`backup plan` 默认只读，`create` 需要已审阅摘要；恢复会暂停未决任务，不自动启动或重发。

`db status` / `db plan` 可识别六处数据库的已知结构与升级步骤，`--rehearse --expected-plan` 只在副本中演练并回滚。参数和边界见[数据库结构手册](docs/schema-planning.md)；当前不提供原库升级操作。

2026-11-15 已同步远程知识库构建更新，并适配现有运行管理、备份和结构识别。功能变化及验证见[远程更新记录](docs/remote-update-2026-11-15.md)。批量导入的 `--dry-run` 使用临时副本，不初始化来源数据库；新 owner 仅为预演身份。

## 私有知识库与独立清洗 Agent

邮件统一内核、端点冻结、新旧入口兼容、历史绑定及隔离归档见[MailCore 手册](docs/mail-core-migration.md)。新邮件状态统一存储，历史记录不会自动进入待发队列。

采集长任务的提交、进度、取消和恢复见[独立 Worker 手册](docs/crawler-jobs.md)；提交不联网，执行需要显式启动 Worker。

单标的采集视图 → 上游预测 → 报告与本地通知的运行步骤见[单标的分析](docs/single-symbol-analysis.md)。

可选股票采集 MCP 服务的安装、工作区迁移及离线验证见[采集服务手册](docs/crawler-service.md)。分阶段优化范围及验收标准见[优化路线](docs/optimization-roadmap.md)。

支持数字 PDF、DOCX、UTF-8 TXT/Markdown/CSV/JSON 与 XLSX。原文件按用户加密保留，更新生成新版本；知识资料与对话记忆分开存储，复用私有访问密钥做权限隔离。检索结合关键词、可选 Embedding 和带来源及有效期的关系表，返回页码、段落或单元格位置。

```powershell
uv sync --all-extras
# 两个终端须沿用同一配置和已有的 STOCK_PREDICT_MAILER_MASTER_KEY，避免丢失已有凭据访问能力。
uv run stock-predict-mailer --config config/local.toml console
uv run stock-predict-mailer --config config/local.toml knowledge-worker --poll 2
# 只处理当前队列：
uv run stock-predict-mailer --config config/local.toml knowledge-worker --once
```

控制台的「知识库」页签可上传资料、检索证据、汇总回答、配置索引与下架版本；检索结果按版本槽位分组并标出已失效资料，「汇总并回答」把同一批证据排成「关系证据 → 条件性推断 → 冲突」——它是规则拼接（`evidence_extract`），不是大模型结论，没有证据时只说证据不足。顶部状态条显示队列深度与清洗进程是否在线（心跳 90 秒内视为在线，正常退出会写 `stopped`，被强杀则最多滞后 90 秒），离线而仍有排队时直接给出上面的 `knowledge-worker` 命令。后端接口是 `/api/knowledge`，上传成功表示已排队，不代表完成入库。整批导入用 `knowledge-import`（用法见 `docs/知识库与报告.md`）：先 `--write-manifest` 生成清单骨架，填好标签后 `--dry-run` 核对计划，再 `--process` 导入并处理。旧入口的 `kb-add` / `kb-search` / `kb-revoke`（须加 `legacy` 前缀）写入同一份存储，但会同步跑完流水线才返回，因此耗时从毫秒级变为秒级。外部 Agent 可按角色白名单只读检索：`POST /a2a/<role>` 的 `knowledge/search` 需要 `X-Memory-Key` 与 `knowledge-acl --role <role> --domains ...` 授权，默认全部拒绝。检索质量用 `knowledge-eval examples/knowledge-eval/cases.json` 打分：语料里缺的槽位记为 `blocked` 不计入通过率，时点泄漏直接判 `unsafe`，非 `pass` 返回码为 2。

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
- [试灌报告：10 份样本 × 7 种格式](docs/试灌报告.md)
- [语料扩容报告：70 份语料下的检索基线](docs/语料扩容报告.md)

扫描件 OCR、复杂版式与表格的自动准确解析、简称消歧和真实模型准确率仍需后续验证；当前协议验收使用本地模拟服务与合成资料。单机工作区的片段和全文索引为明文，应保留本机磁盘访问控制，不宣称互联网多租户隔离或磁盘取证级擦除。

交付检查：

```powershell
uv run ruff check src tests scripts
uv run python -m compileall -q src scripts
uv run python -m unittest discover -s tests -q
python scripts/check_repo_hygiene.py
```


## 后端修复与前端联调（2026-11-08）

当前后端已补齐按任务授权的 HTML 报告、analysis JSON、邮件状态与 file/SMTP 不确定状态的人工确认接口，以及任务列表、会话历史/长期记忆/待写记忆分页、会话导出与删除、私有访问密钥撤销。前端仍需自行实现页面，下载使用 `/api/tasks/{id}/report`，不能直接访问服务器本地 `report_path`。

知识资料进入分析前保留来源与版本校验，主模型仅能引用预算证据包内的 citation_id；同一快照进入报告 JSON、HTML 和邮件。重复 JSON 键、歧义 Word 表头会拒绝，裸六位金额不再推断为证券代码；历史查询支持已发布版本回放，Windows 原件删除失败保留可重试记录。

- [后端接口与分页、认证、事件恢复契约](docs/control-api.md)
- [前端联调交接](docs/frontend-handoff.md)
- [原始审查发现与逐项修复证据](docs/backend-audit-2026-11-08.md)
- [修复计划与实施记录](docs/backend-repair-plan-2026-11-08.md)

控制台原验收为231项 stdlib unittest 通过，并通过实际本地 HTTP、Mock 模型和 file transport 模拟 EML 链路；后续采集与邮件迭代结果见[优化路线](docs/optimization-roadmap.md)，不代表真实模型质量、第三方服务或邮箱收件已验证。MailCore 新写入口统一已实现，历史切换边界见[邮件计划](docs/mail-core-plan.md)。上游配置测试接口、OCR 与复杂版式能力尚未实现。默认入口消费严格 v1 预测结果，不加载上游权重，知识资料不自动进入训练快照。
