# Stock-Predict-Mailer

[![CI](https://github.com/Yyk-Lqh/Stock-Predict-Mailer/actions/workflows/ci.yml/badge.svg)](https://github.com/Yyk-Lqh/Stock-Predict-Mailer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

本机运行的日频股票研究工具：数据接入与清洗 → 时点正确的研究基线 → 可安装的模型包 → 个人重训练与公平比较 → 带引用的分析报告与邮件预览。

当前版本 **0.5.0**，单用户本机运行，不自动下单、不承诺预测效果。

## 当前状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| 阶段 1–5 离线范围 | 完成 | 快照与时点校验、统计/Ridge/LightGBM 基线、本地文本检索、模板报告、邮件预览与 SMTP 组件 |
| 阶段 6A 自采数据接入 | 完成 | 多格式识别、中文列名映射、清洗与问题隔离、显式发布快照 |
| 阶段 6B 真实数据联调 | 待数据 | 缺真实授权数据、公司行动、真实交易日历与影子运行 |
| 模型阶段 A 固定契约与独立推理 | 完成 | 固定基准/股票池/特征顺序/标签，训练与预测分离 |
| 模型阶段 B 签名演示包 | 完成 | Ed25519 签名、外部公钥信任、无训练数据安装推理 |
| 模型阶段 C 私有队列与个人版本 | 完成 | 快照用途授权、训练队列、owner 命名空间、共同测试集比较、显式切换 |
| C 剩余：残差适配、多 worker、保留策略、分段比较 | 完成 | 时间交叉拟合适配器、优先级与并行 worker、审计式清理、流动性与市场阶段分段 |
| 模型阶段 D 继续训练与回放权利 | 完成 | 算法能力声明、有上限的 `init_model` 追加训练、回放授权与特征漂移报告 |
| 自采数据 F：日历、公司行动、增量更新、影子运行 | 完成 | 认证交易日历、复权因子、append-only 增量更新与新鲜度门禁、十日影子运行与 stable 治理 |
| 预测闭环 E | 报告与生成接口完成 | 预测固化报告、生成接口白名单与降级；**邮件发送按用户要求留待后续** |
| 共享服务隔离 | 未开始 | 需要真正的身份与会话层，本机 principal 不能替代 |

103 项回归测试通过。所有模型能力目前仅覆盖 synthetic/demo 通道与演示数据，**不是**可用的实盘模型。

## 快速开始

需要 Python 3.11+，推荐 uv。所有命令在仓库根目录执行。

```powershell
uv sync --extra trees
uv run python -m unittest discover -s tests -q
uv run stock-mailer --config config/example.toml init
uv run stock-mailer --config config/example.toml demo-run --cutoff 2026-10-24T20:00:00+08:00 --trees
```

`demo-run` 使用合成数据跑完离线链路，输出快照、实验、报告与邮件队列 ID，**不发送邮件**，结果写入 `data/local`。测试使用标准库 unittest，项目未配置 pytest。

不想看演示、想直接用自己的行情训练，请跳到下面的[目录地图](#目录地图数据放哪里产物在哪)与[从原始文件到可训练快照](#从原始文件到可训练快照)。

## 目录地图：数据放哪里，产物在哪

默认配置是 `config/example.toml`，它把 `workspace` 指向 `data/local`（相对配置文件所在目录）。**所有数据、模型、报告的读写都发生在 workspace 里，`data/` 整个目录被 `.gitignore` 排除**，不会被提交到 GitHub。

```text
data/local/
├── intake/                          ← 你的原始文件只有这里需要手动放
│   ├── incoming/                    ← ★ 把 CSV / TSV / XLSX / JSON / Parquet / SQLite 丢进这里
│   ├── archive/<upload_id>/         ← 清洗用原件与报告（自动生成，保留可追溯）
│   └── jobs/<job_id>/               ← 清洗后的表、问题清单、publish-*.csv（自动生成）
├── snapshots/<snapshot_id>/         ← 不可变快照：manifest.json + bars.parquet + source.csv
├── state.sqlite3                    ← 运行记录、数据授权、训练队列、报告、影子记录、密钥撤销
├── registry/
│   ├── versions/<version>/          ← 平台候选与已发布的 demo（manifest + model.json/model.txt）
│   └── personal/<owner_key>/versions/<version>/   ← 你自己的训练产物
└── secrets/model-signing/           ← Ed25519 私钥，绝不提交、不外发
```

| 你要做的事 | 具体位置 / 命令 | 实现文件 |
| --- | --- | --- |
| 放训练数据 | 文件放进 `data/local/intake/incoming/`，或用浏览器上传 | — |
| 清洗数据 | `scan-incoming` / `ingest-file` / 上传页面 | `src/stock_predict_mailer/intake_readers.py`（读格式）、`intake_clean.py`（列名映射与清洗规则） |
| 把清洗结果发布成快照 | 上传页面点“发布”，或对规整 CSV 直接用 `import-csv` | `intake.py`（`publish_bars`）、`data.py`（`import_csv`、`validate_rows`） |
| 训练模型 | `train-submit` + `train-worker`，或 `model-train` | `model_training.py`（队列与训练）、`training_child.py`（训练子进程） |
| 定义特征与标签 | 改契约 JSON，不改代码 | `contracts.py`、`config/task-demo.json` |
| 每日增量行情 | `update-bars` | `marketdata.py` |
| 交易日历与复权 | `calendar-import` / `actions-import` | `calendar.py` |

配置文件都在 `config/` 下，全部可提交、不含凭证：

| 文件 | 用途 |
| --- | --- |
| `config/example.toml` | 默认配置。`workspace` 决定上面整棵目录树的位置，`principal` 是本机操作者标识 |
| `config/task-demo.json` | 任务契约：基准、股票池、特征顺序、持有期、时区、价格口径 |
| `config/client-demo.toml` | 独立安装工作区的示例（验证签名包时用） |
| `config/intake-example.json` | `ingest-file --options` 的元数据模板 |

`config/local.toml` 已被 `.gitignore` 排除，适合放你自己的覆盖项。**注意：`principal` 决定了个人版本的命名空间 `owner_key = sha256(principal)`，改成别的值会让你此前所有个人版本在新身份下“看不见”**（文件仍在 `registry/personal/<旧哈希>/` 里）。

## 从原始文件到可训练快照

### 第 1 步：把文件放进去

CSV 至少要能映射出这些列（中英文列名都认，别名表在 `intake_clean.py`）：`日期`、`股票代码`、`开盘`、`最高`、`最低`、`收盘`、`成交量`。`来源` 与 `可用时间` 可在页面上确认。

一个可用于试跑的最小文件 `data/local/intake/incoming/sample.csv`：

```csv
日期,股票代码,开盘,最高,最低,收盘,成交量
2026-10-20,600000,10.0,10.5,9.9,10.2,120000
2026-10-21,600000,10.2,10.3,9.8,10.0,90000
2026-10-21,000001,12.0,12.4,11.9,12.3,300000
2026-10-22,600000,10.0,10.6,9.95,10.45,140000
```

### 第 2 步：清洗

```powershell
uv run stock-mailer scan-incoming              # 扫描 incoming 目录里的全部文件
uv run stock-mailer ingest-file <某个文件> --options opts.json   # 只处理一个文件，并带上元数据
```

清洗会做这些事，并且**逐行留痕**：识别业务类型（行情/财务/新闻/宏观/表格/文档）、把中文列名映射到标准字段、删除完全重复行、剔除价格非正或成交量负数或开高低收矛盾的行、统计缺失值、列出仍需人工确认的元数据。

实测输出（5 行输入，含 1 条重复与 1 条高低价矛盾）：

```json
{"status": "needs_attention",
 "tables": [{"kind": "bars", "input_rows": 5, "output_rows": 3,
             "duplicates_removed": 1, "excluded_rows": 1,
             "needs_confirmation": ["价格复权口径", "历史实际可用时间 available_at",
                                    "成交量单位（股或手）", "数据来源"]}],
 "issues": [{"row": 3, "code": "exact_duplicate", "message": "删除一条完全重复记录"},
            {"row": 4, "code": "invalid_ohlcv", "message": "价格非正、成交量为负或开高低收关系矛盾"}]}
```

`opts.json` 用来一次性给出元数据，避免每次都手填：

```json
{"kind": "bars", "source": "自行采集 券商导出",
 "price_basis": "unadjusted", "volume_unit": "shares",
 "available_at": "2026-10-22T18:00:00+08:00"}
```

给了元数据后 `needs_confirmation` 会清空。**只要还有被剔除或存疑的行，状态就是 `needs_attention`，不能发布**——异常行不会静默进入训练集，必须先修源文件。

### 第 3 步：发布成快照

```powershell
uv run stock-mailer uploads --port 8765
```

打开 http://127.0.0.1:8765，找到刚清洗完的文件，确认四项元数据后点发布。发布后写出 `snapshots/<snapshot_id>/`，其中 `manifest.json` 记录行数、证券数、起止日期、来源与原始哈希，`bars.parquet` 带哈希校验。**服务只绑定回环地址**，不对外暴露。

如果你手上的 CSV 已经是规整的九列数据（`date, security_id, open, high, low, close, volume, available_at, source`），可以跳过清洗直接导入：

```powershell
uv run stock-mailer import-csv data/local/intake/incoming/bars.csv
```

注意这是**严格校验**而不是清洗：完全重复、OHLC 矛盾、负价、`available_at` 早于交易日、缺列都会直接报错，不会替你修。`available_at` 必须带时区（如 `2026-10-22T18:00:00+08:00`），表示这条记录在当时真正可用的时间。

### 第 4 步：告诉系统这份数据能用来做什么

```powershell
uv run stock-mailer dataset-auth <snapshot_id>                                   # 查看当前记录
uv run stock-mailer dataset-authorize <snapshot_id> --replay --note "允许回放做漂移诊断"   # 需要漂移/影子评分时
uv run stock-mailer dataset-authorize <snapshot_id> --platform --note "已确认平台训练权利" # 仅当你确实有权时才做
```

自己导入的数据在导入时就是 `personal_training=true`、`platform_training=false`、`replay=false`。所以**个人训练什么都不用授权**；`--platform` 用于把这份数据变成平台候选的训练来源，`--replay` 用于 `model-drift` 与 `shadow-evaluate`。任何一项都可撤回，撤回立即生效。

## 训练模型

先用契约锁定“训练什么”。`config/task-demo.json` 固定了基准 `SYN000`、股票池 `SYN001–SYN005`、五个特征顺序与开盘到开盘五日超额收益标签。**换成自己的股票池要改这个文件**（`universe` 至少 3 只、不能包含基准、基准必须是数据里连续有行情的那只），改完 `contract-check` 会给出新的 `contract_id`，旧模型因契约不匹配自动失效：

```powershell
uv run stock-mailer contract-check config/task-demo.json
```

训练有两条路线，产物落在不同命名空间，互不覆盖。

### 路线 A：平台候选（演示通道，适合验证链路）

```powershell
uv run stock-mailer demo-data --days 900 --stocks 16      # 或用自己的 snapshot_id
uv run stock-mailer model-train <snapshot_id> --contract config/task-demo.json --cutoff 2021-06-01T20:00:00+08:00 --algorithm lightgbm --confirm-platform-data
uv run stock-mailer model-evaluate <model_version> <snapshot_id> --cutoff 2023-06-14T20:00:00+08:00
uv run stock-mailer model-publish <model_version> --evaluation <evaluation_id>
uv run stock-mailer model-select <model_version> --allow-demo
uv run stock-mailer model-predict <snapshot_id> --cutoff 2023-06-14T20:00:00+08:00 --allow-demo
```

算法可选 `ridge`、`lightgbm`、`zero`、`momentum`。训练要求至少 60 个成熟特征日与 3 只证券；评价要求至少 30 个成熟特征日，且必须严格晚于该模型全部训练标签的结束日期，否则直接拒绝。

### 路线 B：个人重训练与比较（自采数据的正式路线）

```powershell
uv run stock-mailer train-submit <parent_version> --snapshot <snapshot_id> --cutoff 2026-10-24T20:00:00+08:00 --method full_retrain --priority 5
uv run stock-mailer train-worker --once
uv run stock-mailer train-status <job_id>
uv run stock-mailer model-compare <candidate_version> --baseline <parent_version> --snapshot <snapshot_id> --cutoff 2026-10-24T20:00:00+08:00 --segments
uv run stock-mailer model-select <candidate_version> --confirm-personal
uv run stock-mailer model-predict <snapshot_id> --cutoff 2026-10-24T20:00:00+08:00 --allow-personal
```

`train-submit` 把父版本、快照、契约、切分时间与预算一起固化，相同规格的排队任务会合并；`train-worker` 在清洗过环境变量的子进程里训练，产物校验通过后原子落入 `registry/personal/<owner_key>/`。取消、超时、子进程异常、心跳过期都不产生版本，也不会改写你当前的选择。`model-compare` 只写比较记录，**不会自动切换模型**。

## 每日增量

```powershell
uv run stock-mailer update-bars data/local/intake/incoming/bars_20261027.csv --base <昨天快照> --cutoff 2026-10-27T20:00:00+08:00 --market CN
uv run stock-mailer update-history
```

`update-bars` 在基准快照上追加新交易日并**写出新快照，改写旧快照是不可能的**。它拒绝三类输入：与基准冲突的重述、跨文件重复、超过 `--max-staleness-days`（默认 5 天）的过期数据。每次更新都记进 `data_updates`，含基准快照、结果快照、文件、最新交易日、滞后天数与判定。

## 主要命令

| 目标 | 命令 |
| --- | --- |
| 生成演示数据 / 导入行情 | `demo-data`、`import-csv <path>`、`snapshot <id>` |
| 旧研究入口（等权标签，实验用） | `research <snapshot_id> --cutoff <iso>` |
| 契约检查 | `contract-check config/task-demo.json` |
| 平台训练与发布（演示通道） | `model-train`、`model-evaluate`、`model-publish`、`model-select --allow-demo` |
| 只读预测 | `model-predict <snapshot_id> --cutoff <iso> --allow-demo` |
| 签名包 | `model-keygen`、`model-export`、`model-install --trust-key <pub>` |
| 数据授权 | `dataset-auth <id>`、`dataset-authorize <id> --platform --note "..."`、`--replay/--revoke-replay` |
| 交易日历与公司行动 | `calendar-import <csv> --market <m> --source "..."`、`calendar-status`、`actions-import <csv>` |
| 自采增量更新 | `update-bars <files...> --cutoff <iso>`、`update-history` |
| 漂移诊断 | `model-drift <version> --snapshot <id> --cutoff <iso>`、`drift-history` |
| 个人重训练 | `train-submit [--method continue_train --rounds N] [--priority N]`、`train-worker [--workers N]`、`train-status`、`train-list`、`train-cancel` |
| 残差适配 | `residual-fit <parent> --snapshot <id> --cutoff <iso>` |
| 个人模型比较与切换 | `model-compare <candidate> --baseline <parent> ... [--segments]`、`model-select --confirm-personal`、`model-predict --allow-personal` |
| 预测报告与影子运行 | `prediction-report <prediction_id> [--generate]`、`shadow-record`、`shadow-evaluate`、`shadow-status` |
| 发布治理 | `stable-promote --authorize --note "..."`、`stable-revoke --reason "..."`、`release-status`、`key-revoke`、`key-status` |
| 产物保留 | `model-retention --keep N [--apply]`、`retention-log` |
| 知识库与报告 | `kb-add`、`kb-search`、`kb-revoke`、`report <experiment_id>` |
| 邮件 | `queue-mail`、`outbox`、`send-mail <outbox_id>` |

完整的命令顺序、门禁条件与限制见 [平台模型命令与验收](docs/平台模型命令与验收.md)；安装与路径约定见 [本地运行手册](docs/本地运行手册.md)。

## 模型能力要点

- **固定契约**：基准证券、允许股票池、开盘到开盘持有期、时区、特征截止时间、特征顺序、价格口径与股数单位全部固定，标签不随上传股票池改变。
- **训练与推理分离**：预测只加载原生模型（Ridge 系数 JSON、LightGBM 原生文本），不加载 pickle，不调用 `fit`。
- **签名分发**：发布包含模型、契约、模型卡、评估摘要与清单，用 Ed25519 签名；安装必须显式指定包外可信公钥，校验成员白名单、大小、签名与哈希。私钥与训练原文不入包、不入库。
- **授权先行**：快照导入即绑定 owner。用户导入数据默认禁止平台训练，平台训练需 `dataset-authorize --platform` 并记录备注；撤回立即生效。
- **私有队列**：训练规格（父版本/数据/契约/切分/预算）不可变并可合并去重；单 worker 在清洗过环境变量的子进程中执行，报告阶段进度，支持取消、超时、失败与心跳中断，四种情况都不产生版本、不改写当前选择。
- **命名空间隔离**：个人产物只写 `registry/personal/<owner_key>/versions`，平台 `registry/versions` 不接受个人写入；他人版本不可见、不可取消、不可加载。
- **公平比较**：只在晚于双方训练标签结束的共同日期上成对比较，逐日 Rank IC 差值按日区块 bootstrap 给区间；区间跨零记为「未证明改善」，比较结果不自动切换模型。分段比较同时给出流动性高低与市场阶段两组结论，比较次数超出预算即降级为「证据不足」。
- **残差适配**：父模型字节不变，只在父模型没见过的日期上拟合适配器，并做带 purge 的时间交叉拟合；产物写入 owner 命名空间，必须与同配方重训练在同一测试集比较，不宣称权重微调。
- **继续训练**：只有声明支持部分训练状态的算法（当前仅 LightGBM）可排队，追加轮次有上限，父子版本不可变，且必须与完整重训练比较。
- **自采数据可追溯**：增量更新生成新快照而非覆盖，重述冲突与过期行情显式拒绝；认证日历缺日跳过而不压缩，复权因子只对调整口径契约生效。
- **报告冻结**：预测报告锁定模型版本、契约、快照与预测 ID，之后切换模型不会改写历史报告。
- **发布治理**：stable 发布需至少十个成熟影子日 + 显式授权 + 备注，可撤销；发布者密钥可加入撤销列表，撤销后不能再安装新包。

设计目标见 [平台基础模型与用户自主训练方案](docs/平台基础模型与用户自主训练方案.md)，推进顺序见 [模型能力下一步实施计划](docs/模型能力下一步实施计划.md)。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [接手与移交指南](docs/接手与移交指南.md) | 新接手人从哪里开始：环境复现、阅读顺序、交接清单与常见坑 |
| [实施阶段与验收](docs/实施阶段与验收.md) | 各阶段交付与验收口径 |
| [阶段验收记录](docs/阶段验收记录.md) | 已验收范围、测试与实测记录 |
| [本地运行手册](docs/本地运行手册.md) | 安装、配置与运行入口 |
| [数据契约](docs/数据契约.md) | 九字段日线契约与校验规则 |
| [数据接入中心设计](docs/数据接入中心设计.md) / [使用说明](docs/数据接入中心使用说明.md) | 多格式接入与清洗 |
| [研究验证说明](docs/研究验证说明.md) | 时点切分、指标与成本诊断 |
| [平台模型命令与验收](docs/平台模型命令与验收.md) | 契约、训练、发布、安装、队列、比较 |
| [平台基础模型与用户自主训练方案](docs/平台基础模型与用户自主训练方案.md) | 交付形态、授权与隔离设计 |
| [模型能力下一步实施计划](docs/模型能力下一步实施计划.md) | A–F 阶段范围与剩余工作 |
| [知识库与报告](docs/知识库与报告.md) / [邮件与调度](docs/邮件与调度.md) | 检索、引用、报告与发信边界 |
| [自采数据接入与待办](docs/自采数据接入与待办.md) | 真实数据联调前置条件 |
| [待认领任务](docs/待认领任务.md) | 未完成工作的拆分、依赖与验收口径 |

## 参与贡献

项目采用**公开仓库 + fork / Pull Request**：任何人都可以 fork 后提 PR，合并由维护者执行。

> **注意**：`main` 的 Ruleset 保护目前**尚未在仓库设置中启用**。约定上要求经过 PR 且 CI 通过，但在规则集真正建好之前，任何有 Write 权限的协作者都能直接强推覆盖 `main`（2026 年 10 月已发生过一次）。启用方式见[接手与移交指南](docs/接手与移交指南.md)。

```powershell
uv sync --extra trees --extra dev
uv run ruff check src tests scripts
uv run python -m unittest discover -s tests -q   # 基线 103 项通过
python scripts/check_repo_hygiene.py
```

流程、代码约定（禁止 pickle 推理、契约变更须升版本、不得绕过训练授权门禁）、文档同步要求和权限说明见 [CONTRIBUTING.md](CONTRIBUTING.md)；想从哪开始可以看 [待认领任务](docs/待认领任务.md)。如果你是**整体接手这个项目**（而不是只提一个 PR），请先读 [接手与移交指南](docs/接手与移交指南.md)，它包含不走 Git 的资产移交清单与交接完成判定标准。安全漏洞请按 [SECURITY.md](SECURITY.md) 私密上报，参与即表示同意 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

[MIT](LICENSE) © 2026 Yyk-Lqh。可自由使用、修改与再分发，需保留版权与许可声明；软件按"现状"提供，不附带任何担保。

## 数据与凭证

GitHub 仓库只保存代码、配置示例、文档与非敏感评估摘要。真实行情、私有文档、模型产物、报告、签名私钥、运行数据库与日志均被 `.gitignore` 排除，提交前仍需人工检查。签名私钥保存在 `workspace/secrets/model-signing/`，Windows 下建议用账户权限保护该目录。

## 使用边界

- 本机 CLI 的 principal 是受信操作配置，**不是**登录身份；上传页面仅限回环地址，不开放模型发布、训练或任意模型执行入口。
- 演示数据与 synthetic 模型只用于验证链路，不能解释为真实市场预测；成本诊断不等于可交易回测。
- 真实数据认证、公司行动、历史股票池、真实交易日历、十交易日影子运行、生成 API 联调与正式 SMTP 发送均未完成，不据此宣称开箱即用。
- 数据授权、供应商能力与市场规则需在正式实施前独立核验；本项目用于研究，不构成投资建议。
