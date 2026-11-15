# 变更记录

## 未发布（分支 `scene/56-agent-app`）

- 新增 `knowledge-eval`：用标注用例集给检索打分，输出可重复的通过率、MRR 与按域分布。
  - 用例文件为 `{"version":1,"cases":[...]}`，支持 `expect.logical`（可写前缀）、`expect.domains`、`expect.keywords`、`expect.relation`/`inference`/`conflict`、`min_recall`、`critical`；未知字段与重复 id 直接报错，避免拼错键被当成未命中。
  - 语料里没有的槽位记为 `blocked` 并排除在通过率之外，与 `fail` 分开：补语料与调检索是相反的修法。`blocked` 区分 `absent`、`pending` 等真实状态。
  - `gates` 单独断言时点过滤：任何返回片段的 `available_date` 晚于 `as_of` 即判 `unsafe`，因为泄漏意味着回测无法复现，不该只是扣分。
  - `critical` 用例失败即整轮 `fail`；退出码 0 仅对应 `pass`，其余返回 2，可直接进流水线。
  - `--answer` 改评 `answer()`，额外校验 `mode=evidence_extract`、推断与冲突字段；判分全部是字符串匹配，不调用模型。
  - 附 `examples/knowledge-eval/cases.json`：种子库清单模板第八节 20 条查询的机器可读版本，其中 3/6/7/20 标为 `critical`。
  - 323 项 unittest 通过（新增 20 项：槽位前缀、域不符、部分召回、blocked 三态、待处理修订不遮蔽活动版本、泄漏门、关系与推断断言、阈值与 critical 判定、用例与代码校验、示例集可解析）。
- 新增 A2A 只读知识检索 `knowledge/search`，按角色白名单限定可读的一级域。
  - `POST /a2a/{main|prediction|risk|advice}` 新增 JSON-RPC 方法，参数与 `/api/knowledge/search` 同名同义；返回体额外回显 `role`、`effect="read"`、`domains`。
  - 三道门：必须带 `X-Memory-Key`（Bearer 令牌不携带资料身份）、角色白名单非空（默认为空即拒绝）、白名单只能由 `knowledge-acl` 改（请求里带 `domains` 报 INVALID_PARAMS）。
  - 域过滤发生在排名与 `limit` 之前，越权资料不占名额，`logical_total`/`groups` 只统计允许的版本；拒绝不返回空结果，避免对端误判「库里没有」。
  - 新增 `knowledge-acl` 命令查看/设置角色域白名单（`--domains ""` 收回权限）；`RoleConfig` 增加 `knowledge_domains` 字段并校验格式。
  - Agent Card 增加 `knowledge.search` 技能声明，描述里写明需要 `X-Memory-Key` 与角色授权。
  - 303 项 unittest 通过（新增 7 项：全员默认拒绝、域收窄、限额只数允许版本、未知角色/缺密钥/错密钥、参数校验、Card 声明、service 层 `domains` 过滤与空列表语义）。
- 控制台新增「汇总并回答」入口：`POST /api/knowledge/answer` 早就实现但没有界面，现在与检索共用筛选条件。
  - 结果拆成四段而不是一段文字：关系证据（含有效期与来源片段）、条件性推断（逐条列 `evidence_ids`，可展开依据原文）、冲突候选（不自动择一）、警告。
  - 明确标注 `mode=evidence_extract`「规则汇总，非模型生成」：没有配置聊天模型也能用；检索为空时只说证据不足，不补造引用。
  - 底部两个折叠项：复用分组视图的「展开 N 段来源原文」、可直接粘进报告的「纯文本」。
  - 296 项 unittest 通过（新增 1 项接口契约：`mode`/`relations`/`inferences`/`conflicts` 字段与空查询、`limit=0` 的 400）。
- 检索证据界面补齐时间范围、返回上限与按版本槽位分组。
  - `POST /api/knowledge/search` 结果新增 `logical`、`expired` 与 `groups`（`filename`/`document_date`/`available_date`/`valid_to`/`expired`/`hits`/`shown`），并回显 `as_of`/`start_date`/`limit`、给出 `logical_total`。
  - 选片改为「先给每个版本一个名额，再按分数补齐」：一份多切片的长资料不再占满 `limit`，另一来源却被挤掉；`limit` 仍严格生效，组内顺序仍是分数序。
  - `expired` 指 `valid_to < as_of`，只标记不排除——时点回放常需要过期资料；界面显示「已于 X 失效」，条目保留「仅作历史参考」警告。
  - 控制台新增「文档日期不早于」与「返回片段数」（5/8/12/20），结果按 `logical` 分组渲染，命中多于显示时写明「命中 N 段，显示 M 段」，底部提示「另有 N 个版本命中」。
  - 295 项 unittest 通过（新增 6 项：长资料不挤占、组内分数序、隐藏版本计数、过期标记、参数回显、空结果）。
- 知识库队列与 worker 在线状态接入控制台：新增 `GET /api/knowledge/queue` 与 `workers` 心跳表。
  - worker 在每轮循环写心跳（`idle` / `busy` / `stopped`，含正在处理的资料与本次已处理份数），空闲时 10 秒节流一次；`--once` 退出前也写 `stopped`，因此「跑完即退」同样能解释队列为何不再推进。
  - 判定：`state != stopped` 且心跳在 90 秒内为在线。「从未启动」与「无响应」分开呈现——前者给命令，后者提示查进程；离线而仍有排队时，状态条直接给出 `knowledge-worker` 命令。
  - 控制台「资料与版本」顶部显示 排队 / 处理中 / 待审阅 / 失败 / 已发布 与最近心跳、本次处理份数；失败与待审阅条目可跳到详情。原先那句「当前页面无法确认它是否在线」随之删除。
  - 心跳写失败只吞异常，不阻断导入；`busy` 时仅当正在处理的资料属于当前 owner 才显示名称。
  - 289 项 unittest 通过（新增 8 项：计数与 owner 隔离、失败原因、心跳三态、静默判定、跨 owner 隐藏、`--limit` 边界、`--once` 心跳、HTTP 路由）。
- 新增 `docs/知识库受控词表.md`：把 `logical` 与 8 个标签键的取值固定下来，作为种子库录入的唯一来源。
  - 8 个一级域的二级键、第三级命名规则与正反例；一条判定规则——「修订版该覆盖还是该并存」，用于区分「报告期（允许）」与「获取日期（禁止）」。
  - `topics` 受控 30 词（6 组，含含义边界与互斥对）、`industries` 采用申万一级 31 个、`source` 按「类别+机构」。
  - 明确不覆盖宏观指标名、公司名、行业名，避免词表变成摘要库；`制度`、`方法` 两域默认留空 `topics`。
  - 词表外写法视为录入错误；变更走月度评审，不回填历史文档（回填会触发新版本）。
- 新增批量导入入口 `knowledge-import`：按目录或 CSV 清单一次导入整批资料，支持 `--dry-run`、`--limit`、`--write-manifest`、`--process`。
  - 清单列 `path,logical,source,document_date,available_date,valid_to,companies,industries,topics,stock_codes`，与 `metadata()` 白名单一致；未知列直接报错，避免拼写错误静默丢标签。
  - `available_date` 不会静默取当天：清单 → `--available` → `document_date` 依次兜底，三者皆无则逐文件失败；`--assume-available-today` 才用当天并计入 `warnings.available_date_inferred`。理由是该字段事后无法修复，填错会污染回测。
  - 提供清单时以其为准：未登记文件跳过、登记但缺失的文件报失败，清单本身即入库台账。
  - 幂等按 `(logical, 内容哈希)`：重复导入跳过，内容变化则成为同一槽位的新版本。
  - `logical` 留空时按目录路径推导；超过 200 字符报错并提示用清单简写。
  - 281 项 unittest 通过（新增 11 项：清单解析与权威性、日期兜底与失败、幂等、试运行、清单骨架拒绝覆盖、版本递进、`--limit`）。

- 知识库资料列表改为分页：`GET /api/knowledge/documents` 支持 `limit`（1–500，缺省 50）、`offset`、`status`，响应改为 `{items,total,review,limit,offset}`；控制台列表按页加载并提供「加载更多」。
  - 原实现逐篇调用 `document()`，而它每次都执行 `ensure()` 的 `INSERT OR IGNORE` 写事务；200 篇资料实测 426 ms，400 篇 843 ms，且每次切换页签都会触发。改为单页一次查询后，首页 4.6 ms / 6.4 ms（约 90–130 倍）。
  - `Knowledge.catalog()` 为新增分页接口，`listing()` 保留原签名与返回形状（全部版本），供既有调用方使用。
- 知识库下架与版本历史接入控制台：新增 `POST /api/knowledge/documents/{id}/retire` 与 `GET /api/knowledge/documents/{id}/versions`。
  - 此前控制台只有「删除」，走的是 `DELETE`：会 unlink 加密原件并清除片段/索引，不可恢复。现在「下架」为默认出口（保留原件、仅退出检索），永久删除改为需输入资料 ID 前 8 位确认的二步操作。
  - 详情页显示失效日期与版本历史，并注明「检索按截止日期选用当时有效版本，下架不退回旧版本」。
- 270 项 unittest 通过（新增 3 项：分页装配与参数校验、版本历史与下架保留原件、HTTP 路由与分页报错）。

- 合并两套知识库实现：删除 `knowledge.py`（`state.sqlite3` 明文片段库），新增 `knowledge_api.py` 作为兼容门面，`kb-add` / `kb-search` / `kb-revoke` 与报告链路全部改落私有知识库，`state.sqlite3` 的知识表停用留档。
  - 门面保留原有四个函数签名，`report.py`、`prediction_report.py`、`model_cli.py`、`legacy_cli.py` 各只改一行 import；`upload` 只入队，门面负责推完流水线并同步返回。
  - `private_knowledge` 新增 `retire()`：撤销停用但保留加密原件（`delete` 不可恢复，语义过重）；新增 `versions()` 按逻辑槽位列版本。
  - 行为变化：`kb-add` 支持七种格式、耗时变为秒级、需要 `knowledge` 可选依赖；多 `--allow` 生成多份加密副本；时间比较改为日粒度（最坏情况同日内资料提前约 1 天可用，与引擎口径一致，避免「检出却校验失败」）；64 位旧 `citation_id` 明确报错而不是静默引用错误文本。
  - 未经 `MASTER_KEY` 而工作区已用主密钥建库时，命令行直接报错，不再静默切到空库。
  - 267 项 unittest 通过（原 269 项中 2 项重复用例已并入 `tests/test_knowledge_api.py`）。

- 项目名统一为 **Stock-Predict-Mailer**：新增 `naming.py` 作为专有名 / 发行名 / 导入名 / 环境变量前缀的唯一来源；
  `pyproject.toml` 改为从包内读取版本并使用 `stock-predict-mailer` 入口（旧的短命令别名退役）；
  环境变量前缀改为 `STOCK_PREDICT_MAILER_*`（旧 `SPM_*` 仍可读取）、会话 Cookie 与浏览器本地键同步改名；
  控制台与数据接入中心品牌、A2A 卡片名一并更正；新增 `scripts/check_naming.py` 与 `tests/test_naming.py` 防止回退。
- 控制台改为高黑（石墨）视觉：深底四层明度 + 发丝描边 + 单一黄铜强调，替换原纸感浅色；数据接入中心同步换色。
- 分析运行时新增实时运行图：状态、已运行时长、事件与阶段计数、分段阶段轨、事件节律图，数据全部来自既有轮询。
- 窄屏修整：导航在自身内部横向滚动而非撑宽页面；事实行在 390px 下折成小卡。
- 记录页与概览只显示主任务：子 Agent 的中间任务（`contextId` 指向父任务）不再以「未标注标的」的空行出现。
- 运行图的「已运行」改用首条事件时间戳起算、末条事件定格，回看历史任务时不再显示成「打开页面到现在的秒数」。
- 邮件回执的收件人回退到提交时的 `recipient`，不再恒为「—」。
- 大厅行情墙接入真实报价：新增 `control/market_feed.py` 与 `GET /api/market/snapshot`，从公开行情页读取上证指数、深证成指、创业板指与沪深300，校验后缓存；页面每 10 秒轮询，按来源、来源时间与时区展示，`data/agent-local/market.json` 可覆盖标的与刷新间隔、`enabled: false` 可关闭。腾讯不可用回退新浪；长时间无新快照显示「行情暂未更新」，从未取到数据时保留演示行情而不伪造价格。报价只用于显示，不进入任务、预测或模型输入，自采数据链路仍无采集端。

## 0.5.0 后端修复（2026-11-08）

- 拒绝重复JSON键和歧义Word表头，修正金额与证券代码识别，支持已发布知识版本的历史回放和原件删除失败重试。
- 为受限主分析建立有来源/版本校验与预算限制的知识引用包，统一analysis JSON、HTML和邮件证据附录，连接测试沿用运行推理参数。
- 新增受权报告/邮件状态、任务列表、会话与记忆分页（含pending）、会话消息导出/删除、访问密钥撤销及file/SMTP人工确认接口。
- 补充后端审查、接口和前端交接文档；231项unittest及本地HTTP/模拟EML验证通过。前端、统一MailCore和真实外部集成未包含。

## 0.5.0

- 发布审阅补强：相同文件并发上传在事务中去重，重试不能覆盖新状态；向量导入/重建在每批发送前重查外发授权和资料状态，撤权或删除后停止后续批次。CI 同时覆盖无研究依赖与完整知识库依赖。

- 私有知识库新增独立语义清洗模型配置（OpenAI 兼容/Ollama），严格候选 schema、引文/日期/数值单位校验、持久调用预算、批次恢复和私有审批接口。候选批准后才发布，否定/不确定关系不作肯定边，未来事件不支持当时已发生的风险推断；财务候选按同主体/周期/单位比较来源差异。默认关闭，真实模型准确率和 OCR 未验证。

- 新增用户私有知识库后端与独立 `knowledge-worker`：支持数字 PDF/DOCX/TXT/Markdown/CSV/XLSX/JSON、版本与检查点、关键词/Embedding/时态关系混合检索、来源定位和条件性供应链风险回答。可选 knowledge 依赖；Ollama/OpenAI 兼容向量接口、分代索引切换和用户隔离。扫描件/OCR 与复杂表格自动准确解析不在首期保证范围，前端暂不实现。

- 邮件图表改为纯标准库确定性 PNG（inline/attachment），HTML 展示图例与说明，保持 CID 和既有队列 EML。
- 新增 `mail-list`：按最新入队顺序列出邮件，支持 limit 与状态筛选，JSON 输出包含信封地址、传输方式及重试信息。
- 支持可选 `mail.sender_name` From 显示名及 CRLF 校验，显示名不参与幂等 ID，信封地址保持不变。

- 自采数据：新增认证交易日历（`calendar-import`、`calendar-status`）与公司行动因子（`actions-import`）。缺交易所交易日时按窗口跳过而不是压缩相邻日；复权口径只对 `backward_adjusted` 契约生效，`forward_adjusted` 明确拒绝。
- 自采增量更新（`update-bars`、`update-history`）：把每日文件合并为**新**快照而不覆盖旧快照，同值重复记为无变更，改写历史的重述直接拒绝，超出新鲜度阈值需 `--allow-stale` 才记录为过期更新。
- 数据回放权利：授权记录新增 `replay` 用途并与既有库就地迁移；撤回后立即停止回放。新增特征漂移报告（`model-drift`、`drift-history`），按训练窗口分位分箱计算 PSI，分箱固定因此可复现。
- 残差适配（`residual-fit`）：父模型字节不变，只在晚于父模型标签结束的日期上拟合 ridge 适配器；按日切分做带一行purge的时间交叉拟合，报告样本外 Rank IC 前后对比；用 `model-compare` 与同配方重训练比较，不宣称权重微调。
- 队列能力：算法能力声明（只有 LightGBM 支持继续训练）；`train-submit --method continue_train --rounds N` 用 `init_model` 做有上限的追加轮次，父子版本不可变；`train-submit --priority` 与 `train-worker --workers` 支持优先级与并行领取，同一任务不会被重复执行。
- 产物保留（`model-retention`、`retention-log`）：已选、已发布、被其他版本依赖的版本永不清理；默认 dry-run，删除前先写审计记录。
- 比较增强（`model-compare --segments`）：按流动性与市场阶段分段，记录比较次数与预算，预算耗尽后结论降级为 `insufficient_evidence`。
- 预测闭环：`prediction-report` 把预测固化为报告，锁定 model_version、contract_id、snapshot 与预测 ID，切换模型不改写历史报告；无证据不补造引用。
- 生成接口（`--generate`）：默认确定性模板；只有显式开关 + 环境变量指定 + 允许清单内的提供方才会被调用，只发送结构化排序与引用编号，失败/空结果/未列入清单一律降级为模板。
- 影子运行与 stable 治理：`shadow-record`、`shadow-evaluate`、`shadow-status` 记录并评分已成熟的预测；`stable-promote` 要求至少十个成熟影子日 + 显式授权 + 备注，`stable-revoke` 可撤销；发布者密钥撤销列表（`key-revoke`、`key-status`）使已撤销密钥不能再安装新包。
- 邮件闭环补口：新增 `mail-drain` 按到期顺序批量推进重试，单条消息的配置或完整性错误不中断整批，仍有未结清消息时退出码为 2；新增 `mail-resolve` 用"先写审计再改状态"的人工确认把 `uncertain` 收口为 retry 或 submitted，确认未送达后的重发仍可能重复，不宣称 exactly-once。`mail.recipient_allowlist` 非空时成为入队硬闸门，命令行覆盖也受约束；`mail.chart_delivery` 此前只能由控制台注入，现可由配置指定。邮件补 `Date` 头。
- 演示链路带图：Mock 上下文提供 `chart_data`（observed/forecast/backtest 合成序列），`AnalysisAgent` 在上下文契约之外单独接收并校验图表数据，非法图表数据直接报错不静默降级；`run` 的演示邮件内嵌两张确定性 PNG 图表（历史观测与预测、实际值与历史预测），`examples/context.json` 同步给出静态契约样例。
- 跨平台用例补强：原子替换在有并发读者时仍完成且不残留暂存文件、中文含空格路径、非契约时区的截止时间映射、天真时间戳拒绝。
- 回归测试 50 → 103 项；真实 SMTP 仅完成一次投递验证（QQ 邮箱 465/SSL，服务器返回 `submitted`，未人工确认到达），送达率、退信与配额边界仍未验证。

- 新增《接手与移交指南》：给出接手方从环境复现、代码阅读顺序、模型链路演练到交接判定清单的完整路径，并单独列出不走 Git 的资产（签名私钥、数据授权、SMTP、仓库 Admin）与已知的不可宣称事项。
- README 重写使用说明：新增目录地图（原始文件放 `data/local/intake/incoming`、清洗产物在 `archive`/`jobs`、快照在 `snapshots`、个人版本在 `registry/personal/<owner_key>`）、四步接入流程（投放 → 清洗 → 发布 → 授权）、两条训练路线的完整命令、每日增量流程，以及“想改哪块改哪个源文件”的映射表。修正此前文档中的 `data/incoming` 错误路径。

## 0.4.0

- 模型阶段 C（第一批）：增加快照 owner 与用途授权记录，用户导入数据默认只允许个人训练，平台训练需显式授权备注。
- 增加持久训练队列、不可变训练规格（父版本/数据/契约/切分/预算）、单 worker 受控子进程、阶段进度、取消、超时、失败与中断处理。
- 个人模型只写入 owner 命名空间，平台版本目录不可被个人训练写入；旧模型在失败、取消或超时后继续可用。
- 增加共同测试集成对比较：仅使用晚于双方训练标签结束的日期，区块 bootstrap 给出差值区间与结论，不自动切换模型。
- 个人候选需显式确认且已有比较记录才可选择，预测需显式允许；残差适配、继续训练、多用户认证与真实行情仍未完成。
- 开源协作治理：MIT 许可证、贡献指南、行为准则、安全策略、PR 与 Issue 模板、双平台 CI（Linux/Windows × Python 3.11/3.13）、ruff 与 editorconfig、仓库卫生检查脚本，并统一修复既有 lint 问题。

## 0.3.0

- 模型阶段 B：增加 Ed25519 发布签名、显式外部公钥信任、原生模型包导出与独立工作区安装。
- 安装校验模型包成员、签名、哈希、契约与评价时点；拒绝不可信序列化、版本覆盖或自动切换。
- 当前仅 synthetic/demo 发布；正式稳定版、个人训练队列与真实行情自动更新仍未完成。

## 模型阶段 A

- 增加固定基准、股票池、特征顺序、标签周期及口径契约。
- 增加原生 Ridge/LightGBM 模型、独立训练、严格向前评价、演示发布及只读预测。
- 增加不可变模型版本、完整性校验和按本机身份独立选择；不宣称多用户认证或正式 stable 发布完成。

## 后续设计

- 补充平台预训练与用户自主训练方案，明确算法继续训练差异、数据模型隔离、共同测试集与模型发布路线；当前仅为设计，未新增训练能力。

## 0.2.0

- 增加仅本机访问的数据接入页面、文件投放目录、格式与业务种类识别。
- 支持 CSV/TSV、XLSX 多工作表、JSON/JSONL、Parquet、只读 SQLite 及文本归档。
- 增加中文字段映射、日期数值规范化、完全重复删除、冲突隔离、元数据确认和版本化清洗报告。
- 通过检查的行情可显式发布为现有训练快照，保留来源口径及上传血缘，不自动补造历史时间。

## 0.1.0

- 建立本地 Python 项目与可追溯运行基础。
- 明确六阶段实施边界、逐阶段验收与推送要求。
- 阶段 2：增加日线 CSV 契约、不可变快照、时点过滤、合成数据及完整性验证。
- 阶段 3：增加五日标签、时序隔离、统计与 Ridge 基线、可选 LightGBM、独立保留集及研究成本诊断。
- 阶段 4：增加本地文档 ACL、时点过滤、混合检索、引用完整性与转义 HTML 模板报告。
- 阶段 5：增加一键离线演示、操作系统互斥、邮件预览与 Outbox、保守 SMTP 重试和 Windows 调度脚本。
- 阶段 6A：按用户自采数据要求增加显式未认证真实数据探索训练入口、风险标记与接入清单，6B 实际联调待数据。
