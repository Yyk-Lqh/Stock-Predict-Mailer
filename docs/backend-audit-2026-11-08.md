# 后端全面审查与运行验证（2026-11-08）

**审查基线：8166881；Python 3.11 / Windows；只读业务代码。**

## 结论与证据等级

后端具备本机、同源、受限 Mock 联调条件；不具备完整真实业务验收条件。预测 JSON 接入、五档编排、MCP、PNG 模拟邮件、私有资料管理和记忆基础链路可运行。但正式报告/邮件引用、前端报告与邮件管理接口，以及财务数据解析正确性仍有阻塞。真实模型/上游/邮箱/第三方 Agent 的可靠性需另行验证。

本轮不修改实现、不自动修复、不提交、不推送，不读取真实业务配置或发送真实邮件。所有启动、写库、上传与删除探针使用隔离临时工作区；报告及 .tmp 下证据是新增审查产物。

“已实现并验证通过”仅指注明的本地范围。真实本地 HTTP、MCP stdio 会话可以承载 Mock 模型和合成资料，不能据此证明第三方模型质量、真实行情或收件箱送达。其余状态严格使用“部分实现”“仅有 Mock 或占位”“未实现”“受环境限制待验证”。

## 本轮实际运行结果

- `uv run ruff check src tests scripts`：通过。
- `uv run python -m compileall -q src scripts`：通过。
- `uv run python -m unittest discover -s tests -q`：219 项通过，121.301 秒。
- `python scripts/check_repo_hygiene.py`：152 个已跟踪文件检查通过。
- 独立 control 专项：40 项通过，30.523 秒（子审阅验证）；已包含在全量，不相加为 259 项。
- 从 POST /api/tasks 实际提交五档 complex 任务：全部 completed/analysis ok/file mail simulated；light/medium/high 各 0 个子 Agent、21 条事件；extreme/ultra 各 3 个叶子子 Agent、35 条事件。
- 各任务有本地报告且 EML 包含 image/png。极高任务成功检索 1 条私有资料附录。事件游标续读无重复。
- 独立后端通过 HTTP 完成模型 Mock test、真实本地 MCP 发现和资源读取、上传→worker→搜索；非法预测 400，跨源 Origin 403。
- 重启隔离服务后，1 个模型配置、用户密钥对应身份和 1 份资料保持可用；客户端需重新建立 session。
- CLI 真实入口两次 run --send 均退出 0，邮件 ID 相同；mail-list simulated 只有 1 条，证明本地幂等。

复现命令（工作区根目录，保持 all-extras 已安装；探针不使用真实服务）：

```powershell
uv run python .tmp/audit-20261108/http_probe.py
uv run python .tmp/audit-20261108/cli_probe.py
uv run python .tmp/audit-20261108/issues_probe.py
uv run python .tmp/audit-model-probe.py
uv run python .tmp/audit-api-memory.py
uv run python .tmp/audit-model-context.py
```

原始证据：`.tmp/audit-20261108/unittest.log`、`http-evidence.json`、`cli-evidence.json`、`issues-evidence.json`；附加 `.tmp/audit-api-memory-result.json`、`.tmp/audit-model-context-result.json`、`.tmp/audit-control-elevated.log`。这些忽略目录文件本轮保留在本机，不随 Git 自动分发；复验前提是对应服务端口可用、uv 环境就绪。

## 需求—实现—验证对应清单

### R01 模型配置/API Key/温度
- 状态：**已实现并验证通过**。
- 代码/文档：`control/schemas.py:36；control/store.py:82；control/models.py:41`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：配置、加密、脱敏、清除、温度继承/不支持参数测试通过；真实服务另列待验。

### R02 模型连接测试
- 状态：**部分实现**。
- 代码/文档：`control/models.py:157`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：HTTP 接口和本地模拟 Chat 协议可运行；默认档位原生推理参数在 test 路径遗漏，见 F06。

### R03 五档推理强度与协作门槛
- 状态：**已实现并验证通过**。
- 代码/文档：`control/execution.py:9；control/orchestrator.py:396`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：真实 HTTP 入口五档均 completed；前三档 0 子 Agent，extreme/ultra 各 3。档位主要是本地预算包络，非保证模型能力等级。

### R04 默认预测/聊天/工具样例数据
- 状态：**仅有 Mock 或占位**。
- 代码/文档：`agent_service/adapters.py:75；control/models.py:102；control/mock_services.py:15`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：默认数据合成、Mock 模型确定性返回代码；不能作为真实行情、模型推理质量或收件箱证据。

### R05 真实聊天模型与原生推理参数兼容性
- 状态：**受环境限制待验证**。
- 代码/文档：`control/models.py:112`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：兼容适配器及模拟 HTTP 测试存在；没有实际厂商凭据/模型，本轮不调用真实服务。

### R06 Plan-and-Execute + ReAct
- 状态：**部分实现**。
- 代码/文档：`control/orchestrator.py:291；control/orchestrator.py:336`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：有计划事件、固定工具链、观察错误后重试/继续/停止；不是通用 LLM 工具选择、任意计划重排或自由行动 Agent。

### R07 MCP 管理、发现、权限、调用、资源读取
- 状态：**已实现并验证通过**。
- 代码/文档：`control/mcp_layer.py；control/server.py:271`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：真实本地 stdio/Streamable HTTP 协议测试通过；主探针通过管理 API 完成发现和资源读取，任务实际调用获准工具。

### R08 MCP 任意工具/资源进入分析
- 状态：**部分实现**。
- 代码/文档：`control/orchestrator.py:291`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：分析工具固定传 subject 且返回 v1 context，需适配不兼容 Schema；管理资源 read 可用，但任务 collect 没有自动资源读取。

### R09 真实第三方 MCP 服务
- 状态：**受环境限制待验证**。
- 代码/文档：`tests/test_control.py:122`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：本地协议真实，数据与服务为合成；第三方权限、稳定性及契约需要实际服务验证。

### R10 A2A/叶子子 Agent/汇总/预算取消
- 状态：**已实现并验证通过**。
- 代码/文档：`control/a2a.py；control/orchestrator.py:240`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：本机协议和外部模拟服务轮询测试通过，子 Agent 串行执行，禁止继续委派和工具，汇总失败可降级；协议为 A2A 0.3 有限子集。

### R11 真实远程 Agent 互操作
- 状态：**受环境限制待验证**。
- 代码/文档：`docs/control-api.md`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：没有真实第三方 Agent；不声称完整 A2A 1.0、流式或并行执行。

### R12 短期记忆、压缩、归档、写入重试
- 状态：**已实现并验证通过**。
- 代码/文档：`control/memory.py:187；control/memory.py:310；tests/test_memory.py:40`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：强制压缩后保留 2 个近期轮次和 6 条摘要，25 条原消息仍在磁盘；向量写入失败保留源消息与待写记录。

### R13 长期记忆/召回/重要信息提取
- 状态：**部分实现**。
- 代码/文档：`control/memory.py:65；control/memory.py:96；control/memory.py:310`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：本地哈希稀疏向量及明确记住/偏好/约束可存取召回；不是通用语义 Embedding，也没有任意内容的 LLM 重要性判断；历史浏览有上限，见 F10。

### R14 多格式导入、版本、出处、私有隔离
- 状态：**部分实现**。
- 代码/文档：`private_knowledge/parsing.py；private_knowledge/service.py:239`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：七格式合成用例和 HTTP 上传/检索/重启通过；重复字段、股票代码误识别、历史版本筛选和文件删除问题见 F01/F02/F08/F09。

### R15 独立清洗 Agent/模型配置/审批
- 状态：**已实现并验证通过**。
- 代码/文档：`private_knowledge/cleaner.py；private_knowledge/worker.py；tests/test_cleaning_agent.py`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：独立 worker、受限结构化提取、引用/数值校验、审批、预算/断点/拒绝均有本地测试；默认关闭模型，不意味着真实模型抽取准确率已验。

### R16 Embedding/Ollama/兼容 API/切换/撤权
- 状态：**已实现并验证通过**。
- 代码/文档：`private_knowledge/embedding.py；private_knowledge/service.py:422；tests/test_knowledge_publication.py`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：本地协议模拟、维度检查、索引代切换和失败/每批撤权回归通过；可不使用 Embedding 进行词法检索。

### R17 真实 Embedding/清洗模型效果
- 状态：**受环境限制待验证**。
- 代码/文档：`docs/cleaning-agent.md`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：没有实际 Ollama 权重/第三方服务与授权真实资料；当前只证明协议、约束及合成标注样例行为。

### R18 OCR/复杂版式准确重建/自动消歧/图数据库
- 状态：**未实现**。
- 代码/文档：`docs/private-knowledge.md；docs/cleaning-agent.md`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：明确延后；扫描件需 OCR，复杂表格/公式标记复核，关系表一至两跳不等于完整自动知识图谱。

### R19 知识库用于主分析并进入报告/邮件引用
- 状态：**部分实现**。
- 代码/文档：`control/orchestrator.py:386；control/orchestrator.py:495；control/orchestrator.py:510`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：独立 answer 可引用，task knowledge 附录可返回；主模型 KB 引用白名单、上下文预算和正式导出链未完整连接，见 F03/F05。

### R20 上游预测 v1 适配与校验
- 状态：**已实现并验证通过**。
- 代码/文档：`agent_service/adapters.py:50；agent_service/contracts.py:73；tests/test_agent_service.py`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：File/HTTP/Mock、UTC 归一、方向或数值、单位、置信度缺省/范围、指标有限性、版本和过期拒绝有测试；真实模型输出另待验。

### R21 上游服务配置/测试的前端 HTTP API
- 状态：**未实现**。
- 代码/文档：`control/server.py:223；control/server.py:246`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：可直接 POST tasks 传预测 JSON，或用 CLI TOML/file/http 适配；没有浏览器里的上游适配配置、拉取与测试接口。

### R22 实际上游模型联调
- 状态：**受环境限制待验证**。
- 代码/文档：`docs/interfaces.md`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：未提供真实上游服务/样本；不能宣称主要配置已对任意厂商或任意结果 Schema 通用。

### R23 本地报告/图表/邮件 PNG
- 状态：**已实现并验证通过**。
- 代码/文档：`agent_service/reporting.py；agent_service/charts.py；agent_service/png.py`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：HTTP 业务探针五档均生成报告文件和 image/png 邮件部分；CLI 两次同输入相同邮件 ID、仅一条 simulated 记录。

### R24 报告下载与邮件状态/操作 HTTP API
- 状态：**未实现**。
- 代码/文档：`control/server.py:223–246；agent_service/mail.py:64`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：本地 report_path、CLI mail-list/status/drain/resolve 存在，但浏览器无法通过已注册路由获取报告或管理邮件队列，见 F04。

### R25 SMTP 重试/不确定状态/幂等
- 状态：**已实现并验证通过**。
- 代码/文档：`agent_service/mail.py:119；tests/test_agent_service.py`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：本轮仅模拟 SMTP/本地测试接收端及 file transport；超时、不确定、重试上限、完整性、人工确认有测试。

### R26 真实邮件送达/退信/评分/配额
- 状态：**受环境限制待验证**。
- 代码/文档：`docs/mail-validation-notes.md`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：本轮不做真实投递；项目历史仅一次 QQ 465/SSL submitted，未人工确认收件，不是送达率验证。

### R27 统一 MailCore 与全部 transport 管理
- 状态：**未实现**。
- 代码/文档：`delivery.py；control/orchestrator.py:525；docs/mail-core-plan.md`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：旧 outbox、新 agent-mail 与 mcp_mail 仍是三条路径；有设计方案，未合并。

### R28 实时事件、游标恢复、任务终态
- 状态：**已实现并验证通过**。
- 代码/文档：`control/execution.py:28；control/store.py:193；control/server.py:235`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：事件持久化、按 task+after 轮询，每页最多 100；本轮五档有 21/35 条事件且续读为空。必须另读 task.status 判断终态；不是 SSE/WebSocket。

### R29 错误/超时/取消/重启与配置持久化
- 状态：**已实现并验证通过**。
- 代码/文档：`control/orchestrator.py:83；control/orchestrator.py:194；control/store.py`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：全量测试含超时、取消、重试、费用、主密钥错误和中断恢复；隔离服务重启后模型、用户身份和知识资料均保留。

### R30 会话/记忆/任务完整管理界面所需后端
- 状态：**部分实现**。
- 代码/文档：`control/memory.py:174；control/server.py:209–246`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：新增/读写部分可用；缺任务列表、分页归档、会话删除/导出及 owner 撤销等生命周期接口。

### R31 同源认证/用户归属/文件传输
- 状态：**已实现并验证通过**。
- 代码/文档：`control/server.py:47；control/server.py:123`（代码路径位于 src/stock_predict_mailer 下）。
- 证据与边界：session+CSRF+X-Memory-Key、Host/Origin 检查可用；原文件 base64 上传/下载，非 multipart。跨域被拒绝是当前约定，不是已配置跨域部署。

## 按优先级排序的问题与复现

P1 表示完整前端/知识业务验收前应先解决；P2 为重要正确性、契约或可用性缺口。没有通过猜测宣称 P0 或已验证公网安全。这里只记录问题，不执行修复。

### F01 [P1] 重复 JSON 键或 DOCX 表头导致财务值丢失
- 位置：`private_knowledge/parsing.py:41,64`。
- 触发/复现：导入 {"revenue":12,"revenue":13}，或 DOCX 两个“收入”列分别为 12、13。
- 实际与预期：实际只剩 13；JSON 无警告，DOCX 只有笼统表格复核提示。预期拒绝重复标签或保留按列位置区分的所有原值。
- 影响：原文件仍保留，但解析结果和清洗前对照已不完整，可能影响金额检索/模型依据。
- 建议：与 CSV/XLSX 同等检测重复键/列名，或保留带原始列位置的数组；建立金额不丢失回归。
- 证据：.tmp/audit-20261108/issues_probe.py / issues-evidence.json。

### F02 [P1] 六位金额被当作股票代码
- 位置：`private_knowledge/service.py:39–44,389,545`。
- 触发/复现：导入 CSV：公司,营业收入(元) / 甲公司,600000；按 stock_code=600000.SH 搜索甲公司。
- 实际与预期：实际命中并标记股票代码 600000.SH；预期金额不能生成证券标识。
- 影响：按股票过滤结果与实体关联可能串标的，是用于真实股票资料前的数据正确性阻塞。
- 建议：裸六位数字仅从明确股票代码字段/股票代码上下文识别；正文要求市场后缀或可信标识来源。
- 证据：.tmp/audit-20261108/issues_probe.py / issues-evidence.json。

### F03 [P1] 知识库引用未接入主分析及正式导出
- 位置：`control/orchestrator.py:61,386–387,495,510；agent_service/reporting.py:50–55`。
- 触发/复现：给主模型提供 KB citation_id，并让其在 evidence_ids 中引用；另查看有 knowledge 附录任务的报告导出字段。
- 实际与预期：模型结果因 INVALID_AGENT_RESULT 被拒；报告保存只接收 analysis，KB 只在 task 顶层，HTML/analysis JSON/EML 没有该引用附录。
- 影响：独立知识问答可用，但“资料→主分析→正式报告→邮件”的有据分析闭环不能验收。
- 建议：在权限与时间校验后建立 KB 引用白名单和证据结构，并让导出引用相同快照；保留现有受限结论校验。
- 证据：.tmp/audit-model-context-result.json；代码调用链。

### F04 [P1] 前端无法下载正式报告或管理邮件状态
- 位置：`control/server.py:223–246；docs/frontend-handoff.md:110`。
- 触发/复现：建立完成任务后 GET /api/reports、/api/tasks/{id}/report、/analysis/.../report.html、/api/mail。
- 实际与预期：已认证请求均 404；result.report_path 是服务器本地路径。预期有按任务/用户授权的报告、附件及邮件状态路由。
- 影响：完整报告页与邮件管理页联调受阻；源码文件存在并不等于浏览器可访问。
- 建议：增加受权报告内容/下载与邮件查询/操作接口；禁止任意磁盘路径访问。原交接文档已承认此限制，不将它误报为新回归。
- 证据：.tmp/audit-20261108/http-evidence.json；.tmp/audit-api-memory-result.json。

### F05 [P2] 正常规模的知识检索结果超主模型上下文上限
- 位置：`control/orchestrator.py:386–387；control/models.py:124–126`。
- 触发/复现：构造 8 条各 1600 中文字符的合法资料结果，启用 knowledge_to_model。
- 实际与预期：实际在网络前 INPUT_TOO_LARGE；会话路径也可能更早 CONTEXT_LIMIT。预期在可用上下文预算内选择证据。
- 影响：开启知识辅助反而常走降级路径；Mock 模型在大小检查前返回，不能覆盖这一风险。
- 建议：生成受预算约束的证据包，减少重复字段/原文，保留 citation_id、时间和出处；与记忆预算统一计算。
- 证据：.tmp/audit-model-context-result.json。

### F06 [P2] 连接测试与真实任务原生推理参数不一致
- 位置：`control/models.py:116,157–164；control/orchestrator.py:196–198`。
- 触发/复现：默认 extreme，映射 extreme→xhigh，使用本地模拟 Chat 接收端运行模型 test。
- 实际与预期：测试返回 ok，但请求没有 reasoning_effort；运行任务会解析并发送。预期 test 与实际默认配置一致。
- 影响：可能出现测试通过、实际任务被服务拒绝。
- 建议：共用运行时配置解析和 envelope；测试显式覆盖当前档位与映射参数。
- 证据：.tmp/audit-model-probe.py；审阅代理已在本地 HTTP 接收端复现。

### F07 [P2] ReAct 和 MCP 资源到任务的能力是受限子集
- 位置：`control/orchestrator.py:291–334`。
- 触发/复现：检查 collect 调用链，配置多个 MCP 工具和资源。
- 实际与预期：分析按固定工具列表顺序调用 subject 参数；管理资源 read 可用但任务不读取；模型不自主生成工具行动。
- 影响：如需求意指通用 LLM ReAct/资源知识推理，目前只完成固定计划、重试、继续和停止。
- 建议：先明确受限产品契约；如需完整 ReAct，增加结构化行动、工具 Schema 映射及逐步权限/预算校验。
- 证据：代码审查；test_react_retry_and_continue_without_tool_data。

### F08 [P2] as_of 不能回放被替换的知识版本
- 位置：`private_knowledge/service.py:531–532`。
- 触发/复现：10 月版本在 10 月截止查询可见；以 11 月版本更新同一 logical，再查询 10 月截止。
- 实际与预期：命中数 1→0，因为只选 active=1。预期若要求历史回放，应选择当时可用的历史版本。
- 影响：不引入未来证据，但历史研究召回缺失；当前 as_of 是活动语料过滤，不是时点语料快照。
- 建议：按 logical 与可用时间选择版本，定义删除/撤销和历史授权规则，再补回放测试。
- 证据：.tmp/audit-20261108/issues_probe.py / issues-evidence.json。

### F09 [P2] Windows 原文件删除失败后无法恢复清理
- 位置：`private_knowledge/service.py:501–517`。
- 触发/复现：在文件占用条件下让 Path.unlink 抛 PermissionError。
- 实际与预期：DB 删除已提交、.bin 仍存在；再次 delete 返回 NOT_FOUND。预期可追踪并重试物理清理。
- 影响：检索已清理，但私有文件残留，API 不再可见，不满足完整删除承诺。
- 建议：增加持久删除/tombstone 状态和重试清理，不先丢掉唯一文件追踪记录。
- 证据：.tmp/audit-20261108/issues_probe.py / issues-evidence.json。

### F10 [P2] 长期记忆和会话档案缺分页及生命周期接口
- 位置：`control/memory.py:165,232,236,242；control/server.py:194–221`。
- 触发/复现：建立 25 轮消息和 101 条长期记忆；请求会话、memory 及 before 参数。
- 实际与预期：API 只返回最近 20 轮/100 条记忆，before 被忽略；会话 DELETE 为 404。原 25 轮仍在磁盘，不是磁盘数据丢失。
- 影响：较长使用后的前端历史浏览/导出/删除不完整。
- 建议：增加游标、总数/下一页及受权归档导出、会话删除和 owner 撤销。
- 证据：.tmp/audit-api-memory-result.json。

### F11 [P2] 邮件三队列和 MCP 不确定结果管理未统一
- 位置：`delivery.py；agent_service/mail.py:64,224；control/orchestrator.py:525–547`。
- 触发/复现：对照 file/smtp 的 agent-mail 与 MCP marker、旧 outbox 数据库路径及管理入口。
- 实际与预期：CLI 管理新 MailService；MCP uncertain 保留且不自动重发，但未接统一查询/人工确认管理链。
- 影响：运维状态分散；不能把 file/smtp 的 resolve 能力等同全部 transport 都可恢复。
- 建议：按 mail-core-plan 单独迭代统一 MailCore/transport，保留旧 ID/EML 和人工审计。
- 证据：代码审查；test_mcp_marker_recovers_as_uncertain_without_resend；未新增真实 MCP 邮件故障投递。

### F12 [P2] 前端 API 文档不完整且分散
- 位置：`docs/control-api.md；docs/hybrid-execution.md；docs/conversation-memory.md；docs/private-knowledge.md；control/server.py`。
- 触发/复现：仅按 control-api 的 TaskRequest/产物字段开发客户端，再对照运行请求。
- 实际与预期：主 API 页缺后续 conversation/knowledge 等字段全表，进度和知识能力散落多份文档；任务列表/上游适配/报告路由缺失。
- 影响：容易误判字段、不知道只支持同源、文件使用 base64、完成需读 task.status。
- 建议：合并维护可执行契约或 OpenAPI/JSON Schema 与 API 用例，明确缺失路由而不虚构示例。
- 证据：文档与注册路由逐项对照；HTTP 探针。

## 四条实际调用链

1. **预测→工具/协作→报告→邮件**：POST tasks → prepare/v1 校验 → execution envelope → collect MCP → 主模型受限结论 → 仅极高/Ultra 复杂任务委派叶子 A2A → 再校验/汇总 → AnalysisAgent → charts → save_report → MailService 或 MCP 邮件。此链本地 Mock+file 邮件通过；实际第三方数据/模型/SMTP 未验。报告文件能生成，但浏览器下载断在 F04。
2. **资料→清洗→Embedding/索引→分析引用**：upload → 独立 worker → parsed/chunked → 可选模型 extraction → review/批准 → 索引发布 → knowledge.answer。后续 task.knowledge 已接通；knowledge_to_model 受 F05 预算限制，模型引用受 F03 白名单限制；导出报告/EML 没有完整证据附录。
3. **对话→压缩→长期记忆→召回**：private key → conversation_turns 加密归档 → context 阈值压缩 → summary/recent/recalled。明确记住和偏好等通过本地稀疏哈希召回；写失败保留待写记录。不是一般意义上的 LLM 自动重要性识别。原消息保留，但 API 浏览受 F10 限制。
4. **运行事件→前端**：Progress.emit → store.append_event → GET tasks/{id}/events?after=N → 前端轮询；每次最多100条，客户端应循环排空并保存最后 seq。事件没有统一 task_completed 终态消息，任务关联由 URL 保证，必须再 GET tasks/{id} 判断 completed/failed/canceled；重启时旧 working/submitted 变 failed/INTERRUPTED。不是 SSE/WebSocket；禁止把最后一个 step completed 当作任务成功。

## 前端接口核对结果

- **认证/跨域**：GET / 建立同源 HttpOnly session；GET /api/session 取 csrf_token；变更需 X-CSRF-Token；私有会话/记忆/知识库需 X-Memory-Key。全局配置属于可信本机操作者，不能据此承诺互联网多租户账户隔离。跨端口/域名 Origin 被拒绝，若前端独立域部署，应先确定同源代理或实现明确 CORS 与身份方案，不可直接全放开。
- **配置**：models/mcp/agents 的 GET/POST/PUT/DELETE 与 models test、mcp test/call/read、settings/reset-temperature 均注册；凭据 write-only，响应脱敏。PUT 是完整配置语义，清除凭据需专门字段，不能假设空字符串清除。
- **任务**：POST tasks、GET tasks/{id}、POST cancel、GET events 已注册；无 GET tasks 列表、无报告或邮件下载/队列接口。任务返回202不是运行成功，completed 可以伴随 analysis.status=degraded，必须查看降级原因、children 和 mail 状态。
- **记忆**：memory/access、conversations 创建/列出/取详情、memory settings/pending/entries 更改删除已注册；无分页、会话删除/导出、owner 撤销。不能仅凭读取成功认定已获取完整档案。
- **知识库**：documents 上传/列表/详情/删除、original base64、retry/reextract/review、config/test/indexes/rebuild、cleaner config/test、search/answer/citations 均注册。上传只接受 JSON base64，原件10MiB、请求15MiB；不是 multipart；上传202可能仍是 pending。worker 必须另行启动且沿用同一主密钥/工作区。review 需 digest 防旧批次审批，无效候选不可批准。当前 rebuild 是同步请求，前端应容忍耗时并观察索引状态，不能当作已实现异步重建 job。
- **报告/图表/邮件**：任务/事件中有图表 SVG 和分析预览、任务中有本地 report_path 与 mail 概览；邮件 PNG 仅在 EML 中。不能直接 fetch Windows 本地 report_path，也没有通用图表文件下载/报告管理 API。
- **错误**：ServiceError 为 {error:{code,message,retryable}}，403/404/400 区分；意外异常500为安全通用信息。调用方需解析业务 code，不得只以 HTTP200 认定真实推理成功。缺失路由404有实测证据。
- **文档**：control-api 是基础配置/A2A 契约；hybrid-execution、conversation-memory、private-knowledge、cleaning-agent 补充后续字段。frontend-handoff 已明确本地报告不可 HTTP 读取。建议统一接口目录并加入真实请求示例、完整 TaskRequest/结果/事件 Schema 和未实现清单。

## 上游预训练/预测模型交付契约

本项目的默认 Agent 入口接收**推理结果**，不加载上游预训练权重。可选 FileAdapter 读 UTF-8 JSON、HttpAdapter 发 GET（可从进程环境读取 Bearer token），或上游直接 POST tasks 的 prediction 字段。历史研究模块虽保留训练功能，不能与默认结果消费接口混为一谈。

- v1 必需：schema_version="1"、prediction_id、subject、generated_at、valid_until、horizon.value/unit、model_version、synthetic；direction 或 value 至少一个。
- direction 只支持 up/down/flat；value 必须有限且有 value_unit；置信度缺省为 null，提供时须在0..1；metrics 是命名到有限数值的映射，不支持任意嵌套结构。未知字段被拒绝，不能任意增加 provenance 并假定透传。
- horizon 支持 trading_days/calendar_days/hours，1..365。时间必须带时区，归一 UTC；过期、过老、未来生成或失效顺序错误会拒绝。默认 CLI 新鲜度由 TOML 控制，控制台 TaskRequest 路径不等同直接继承 CLI agent TOML 的所有参数。
- context 需要相同 subject、schema_version/context_id/facts；fact 需 id/name/value/unit/source/observed_at/available_at，限制与预测时间一致。不接受上游任意文章或自由结构替代 facts。
- 图表需要独立 chart_data.unit/series，observed/forecast/backtest 时间与 generated_at 匹配；区间必须包含预测值，历史预测 issued_at 早于对应实际时间。CLI AnalysisAgent 会拆出 context 携带的 chart_data；控制台任务优先使用顶层 chart_data，普通 context 字段仍按严格事实契约校验，不应盲目套用工具返回包装。
- 重复 POST task 会生成不同任务 ID，并非任务提交幂等；稳定 analysis 内容与信封/transport 的邮件去重另外处理。变更 generated_at、模型版本或预测 ID 会影响分析标识。不能把“邮件幂等”描述为所有模型调用、工具动作、任务提交都恰好执行一次。
- 错误协议有 INVALID_INPUT/STALE_RESULT/UPSTREAM_UNAVAILABLE 等；HTTP适配不做任意格式转换，非200与网络故障有明确返回/可重试标记，不能将HTTP200但不合规正文当成功。

模型开发人员联调前需确认：证券/公司标识及市场、数值单位/复权与币种、方向和置信度的定义与校准、交易日历与 horizon 起算点、generated_at 与数据可用时点、有效期与默认新鲜度、model_version/预测 ID 的稳定规则、metrics 名称与类型、合成标志、图表三类序列和区间含义、鉴权方式及错误/限流语义。建议先交付一份新鲜的真实 v1 JSON，再测试 file 和本地 HTTP 服务，最后接实际推理服务；不必为加载权重改动 Agent，但非 v1 输出需要薄适配器。

## 下一阶段修复顺序与补验条件

1. 先修 F01/F02 财务资料不丢值与证券标识正确性，并加真实格式回归；否则不应把财务资料检索作为真实分析依据。
2. 联通 F03/F04/F05：授权引用结构、预算化证据包、报告/邮件导出附录与按任务受权的前端 HTTP 下载/状态管理。完成后验收资料→报告→邮件完整链。
3. 修模型 test 参数一致性、历史版本回放和删除残留重试，再完善分页/会话生命周期、统一文档与邮件队列。通用 ReAct 是否需要扩展应单独确认产品边界，不为满足名字开放任意工具。
4. 用实际可用且明确授权的模型、Embedding、MCP 与 A2A 服务，验证鉴权失败、429/5xx、超时取消、重试费用、断线恢复与原文引用。私有资料外发需独立许可；本轮没有对应真实服务证据。
5. 使用人工标注真实公告/财报测试代码/金额/单位/周期/否定/传闻/时间，统计引用正确率和错误接受率；合成用例不能替代模型质量结论。真实邮件另授权测试邮箱和批量规模，分开记录 submitted、实际收件、垃圾箱、退信和未知，禁止沿用“submitted=送达”的假设。

最终判断：**可开始受限本机配置、任务、工具、进度和 JSON 上游的 Mock 联调；完整前端功能、统一知识来源报告和真实上游业务验收尚不具备无阻塞条件。** 本报告没有把上述问题修复，也没有把既有训练并发偶发问题归因于本轮改动；219项通过只代表本次未观察到该历史偶发失败。


## 后续修复记录（2026-11-08，保留以上原始发现）

以下为工作区修复状态，不修改原基线审查结论，也不声称真实外部服务验收完成。

- F01：修复。JSON object_pairs_hook 对任意深度重复键拒绝 REVIEW_REQUIRED；DOCX 重复/空表头及列数不一致拒绝。原件保留；回归 test_duplicate_json_keys_rejected_at_any_depth / test_duplicate_docx_headers_rejected。
- F02：修复。正文仅识别带市场后缀证券代码，裸六位仅由明确股票代码字段或显式元数据/查询标识解析。回归 test_amount_is_not_stock_identifier。
- F03：接通受限主分析引用及正式导出。重新验证owner、版本hash/metadata，包内citation_id进入主模型白名单；保留所有结论代码及方向约束；同一knowledge_evidence快照进入analysis JSON/HTML/邮件render。test_knowledge_reference_requires_explicit_allowlist、test_opt_in_knowledge_context_and_private_task（模型实际返回引用ID，导出含ID）。未做真实模型效果和真实含引用邮件收件验收。
- F04：提供按任务授权report/analysis/mail读取、file/smtp uncertain人工确认、任务列表。报告从持久产物渲染，无任意磁盘路径入口。HTTP回归覆盖完成任务、下载、私人403、列表隔离、路径穿越404、file simulated邮件状态；跨transport统一管理仍见F11。
- F05：主模型不再接收全量检索，采用完整片段预算选择，数组上限4000 UTF-8字节并为主输入预留空间；不适配的片段整体跳过，KNOWLEDGE_BUDGET明确告知。复杂长会话/用户约束本身仍可能达到上下文限制；真实厂商token预算及长资料信息覆盖率仍需后续评估。
- F06：修复。连接测试使用默认effort和与任务相同的envelope，并由同一generate解析映射。test_model_test_uses_default_execution_effort先观察None而非extreme，再通过。
- F07：维持受限固定工具链，未扩大任意Agent执行能力。
- F08：修复历史已发布版本回放。logical当前须仍有活动版本；按截止日前可用时间、uploaded/id选版本。删除当前版本不复活旧版。不是录入时间的双时态快照；历史版本可能仅词法检索。test_as_of_replays_published_version先复现空结果，再通过。
- F09：修复。先持久deleting并撤销检索，再unlink，成功后删索引/记录。失败DELETE_PENDING可重试，保留文件追踪。test_locked_original_keeps_retryable_record先复现NOT_FOUND，再通过。
- F10：增加会话消息/会话列表/长期记忆分页、会话删除、完整消息导出、密钥撤销；保留任务owner绑定，禁止借删除会话公开报告。HTTP回归覆盖25轮翻页无重叠、101记忆翻页、导出、删除、撤销。pending队列分页仍未补齐。
- F11：按用户范围独立延期。已阅读mail-core-plan；下一迭代依次引入兼容原ID/EML的repository层、三transport适配、MCP uncertain人工审计与统一查询，再迁移旧队列。此次不合并数据库，不重写EML、不改变幂等算法。
- F12：control-api补充现有字段、实际路由、认证、上传、错误和游标恢复；frontend-handoff/private-knowledge同步。没有虚构上游配置测试或SSE能力。

运行证据（忽略目录，本机保留）：基线F01/F02 `.tmp/backend-baseline-reproduction.json`；先前全量224项通过 `.tmp/backend-fixes-tests.log`、227项通过 `.tmp/backend-final-tests.log`；新增记忆分页回归曾暴露tuple索引错误（不是训练并发），保留于 `.tmp/backend-delivery-tests.log`，已修正为显式列与tuple取值。最终复验另记。隔离CLI run --send两次退出0、相同ID且仅一条simulated（`.tmp/audit-20261108/cli-evidence.json`）。全部使用Mock/file、本地协议与临时数据库，无收费模型、真实服务或SMTP收件承诺。

验证环境：系统uv缓存和沙箱临时目录存在权限问题，使用仓库 `.tmp/uv-cache`、`.tmp/test-temp` 及已安装环境 `uv run --no-sync`；本地服务测试通过获准的沙箱外进程运行。未跳过测试；未观察到训练并发偶发失败。完整前端验收仍依赖前端页面、真实上游样本及另行授权的模型/Embedding/MCP/A2A与邮箱收件验证。上游交付严格v1 prediction/facts/chart_data，详见interfaces.md。

最终验证：ruff通过；compileall通过；全量228项unittest通过（123.095秒，.tmp/backend-final-acceptance.log）；hygiene检查152个tracked文件通过；git diff --check通过。实际本地HTTP与隔离CLI均通过。未提交、推送或合并，未修改前端。pending记忆队列分页仍未完成，旧接口上限100；其余独立延期及真实外部验收边界见上。


### 续轮修复状态（保留前述历史状态）
用户选择完成分页及验证，MailCore仍保留独立迭代。F10遗留pending分页已完成：兼容旧数组、新增owner内排他游标页，严格参数检查且读取不消费队列。先复现10个失败断言（`.tmp/pending-before.log`），修复后6项记忆HTTP测试通过（`.tmp/pending-after.log`）。新回归使用205条待写记录并验证跨owner、增删续读、非法/重复参数。
F03/F05补验：实际HTTP上传→本地worker→任务→受权报告/analysis JSON→file transport模拟EML，解析EML的plain/html部分均包含相同citation_id及原始金额；独立长资料回归确认完整检索超过16KiB，主模型数据低于预算，放不下片段明确KNOWLEDGE_BUDGET，无静默截断。此为本地Mock/协议证据，不是实际模型质量或收件证明。

续轮验收完成：计划1—5均完成。uv run ruff check src tests scripts、uv run python -m compileall -q src scripts、uv run python -m unittest discover -s tests -q（231项，122.252秒）及python scripts/check_repo_hygiene.py（152个tracked文件）全部通过；git diff --check通过。全量日志：.tmp/backend-pending-final.log。保留先失败后通过证据；无跳过测试、无训练并发失败。此前pending分页未完成的记录为历史状态，现已关闭。MailCore/真实外部验收按用户本轮选择继续独立保留，不属于本轮已完成范围；未自动提交或改前端。

发布复验记录：首次231项运行中，test_session_csrf_origin_and_no_secret_response在本地HTTP拒绝请求时发生一次WinError10053连接中止（.tmp/github-release-tests.log）；不是训练并发失败，根因尚未确认，不归因于本轮修复。原用例未修改、未跳过，独立复验1项通过（.tmp/github-csrf-recheck.log），随后重新运行完整测试。

发布完整复验：231项通过，124.583秒（.tmp/github-release-recheck.log）。未修改或跳过CSRF用例，未掩盖首次连接中止记录。
