# Stock-Predict-Mailer

[![CI](https://github.com/Yyk-Lqh/Stock-Predict-Mailer/actions/workflows/ci.yml/badge.svg)](https://github.com/Yyk-Lqh/Stock-Predict-Mailer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

本机运行的日频股票研究工具：数据接入与清洗 → 时点正确的研究基线 → 可安装的模型包 → 个人重训练与公平比较 → 带引用的分析报告与邮件预览。

当前版本 **0.4.0**，单用户本机运行，不自动下单、不承诺预测效果。

## 当前状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| 阶段 1–5 离线范围 | 完成 | 快照与时点校验、统计/Ridge/LightGBM 基线、本地文本检索、模板报告、邮件预览与 SMTP 组件 |
| 阶段 6A 自采数据接入 | 完成 | 多格式识别、中文列名映射、清洗与问题隔离、显式发布快照 |
| 阶段 6B 真实数据联调 | 待数据 | 缺真实授权数据、公司行动、真实交易日历与影子运行 |
| 模型阶段 A 固定契约与独立推理 | 完成 | 固定基准/股票池/特征顺序/标签，训练与预测分离 |
| 模型阶段 B 签名演示包 | 完成 | Ed25519 签名、外部公钥信任、无训练数据安装推理 |
| 模型阶段 C 私有队列与个人版本（第一批） | 完成 | 快照用途授权、训练队列、owner 命名空间、共同测试集比较、显式切换 |
| 模型阶段 C 剩余 / D / E / F | 未开始 | 残差适配、LightGBM 继续训练、stable 发布、生成 API 与邮件闭环、共享服务隔离 |

50 项回归测试通过。所有模型能力目前仅覆盖 synthetic/demo 通道与演示数据，**不是**可用的实盘模型。

## 快速开始

需要 Python 3.11+，推荐 uv。所有命令在仓库根目录执行。

```powershell
uv sync --extra trees
uv run python -m unittest discover -s tests -q
uv run stock-mailer --config config/example.toml init
uv run stock-mailer --config config/example.toml demo-run --cutoff 2026-10-24T20:00:00+08:00 --trees
```

`demo-run` 使用合成数据跑完离线链路，输出快照、实验、报告与邮件队列 ID，**不发送邮件**，结果写入 `data/local`。测试使用标准库 unittest，项目未配置 pytest。

## 上传自己的数据

```powershell
uv run stock-mailer uploads
```

打开 http://127.0.0.1:8765 上传 CSV/TSV、XLSX、JSON/JSONL、Parquet、只读 SQLite 或文本。自动识别业务类型、规范化中文字段、删除完全重复、隔离冲突与异常行并显示待确认项，原件保留。也可把文件放进 `data/local/intake/incoming` 后用 `scan-incoming` 扫描。格式检查通过不等于数据授权，详见 [数据接入中心使用说明](docs/数据接入中心使用说明.md)。

## 主要命令

| 目标 | 命令 |
| --- | --- |
| 生成演示数据 / 导入行情 | `demo-data`、`import-csv <path>`、`snapshot <id>` |
| 旧研究入口（等权标签，实验用） | `research <snapshot_id> --cutoff <iso>` |
| 契约检查 | `contract-check config/task-demo.json` |
| 平台训练与发布（演示通道） | `model-train`、`model-evaluate`、`model-publish`、`model-select --allow-demo` |
| 只读预测 | `model-predict <snapshot_id> --cutoff <iso> --allow-demo` |
| 签名包 | `model-keygen`、`model-export`、`model-install --trust-key <pub>` |
| 数据授权 | `dataset-auth <id>`、`dataset-authorize <id> --platform --note "..."` |
| 个人重训练 | `train-submit`、`train-worker`、`train-status`、`train-list`、`train-cancel` |
| 个人模型比较与切换 | `model-compare <candidate> --baseline <parent> ...`、`model-select --confirm-personal`、`model-predict --allow-personal` |
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
- **公平比较**：只在晚于双方训练标签结束的共同日期上成对比较，逐日 Rank IC 差值按日区块 bootstrap 给区间；区间跨零记为「未证明改善」，比较结果不自动切换模型。

设计目标见 [平台基础模型与用户自主训练方案](docs/平台基础模型与用户自主训练方案.md)，推进顺序见 [模型能力下一步实施计划](docs/模型能力下一步实施计划.md)。

## 文档索引

| 文档 | 内容 |
| --- | --- |
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

项目采用**公开仓库 + fork / Pull Request**：任何人都可以 fork 后提 PR，合并由维护者执行。有 Write 权限的协作者可以自行合并，但 `main` 受 Ruleset 保护，必须经过 PR 且 CI 通过。

```powershell
uv sync --extra trees --extra dev
uv run ruff check src tests scripts
uv run python -m unittest discover -s tests -q   # 基线 50 项通过
python scripts/check_repo_hygiene.py
```

流程、代码约定（禁止 pickle 推理、契约变更须升版本、不得绕过训练授权门禁）、文档同步要求和权限说明见 [CONTRIBUTING.md](CONTRIBUTING.md)；想从哪开始可以看 [待认领任务](docs/待认领任务.md)。安全漏洞请按 [SECURITY.md](SECURITY.md) 私密上报，参与即表示同意 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

[MIT](LICENSE) © 2026 Yyk-Lqh。可自由使用、修改与再分发，需保留版权与许可声明；软件按"现状"提供，不附带任何担保。

## 数据与凭证

GitHub 仓库只保存代码、配置示例、文档与非敏感评估摘要。真实行情、私有文档、模型产物、报告、签名私钥、运行数据库与日志均被 `.gitignore` 排除，提交前仍需人工检查。签名私钥保存在 `workspace/secrets/model-signing/`，Windows 下建议用账户权限保护该目录。

## 使用边界

- 本机 CLI 的 principal 是受信操作配置，**不是**登录身份；上传页面仅限回环地址，不开放模型发布、训练或任意模型执行入口。
- 演示数据与 synthetic 模型只用于验证链路，不能解释为真实市场预测；成本诊断不等于可交易回测。
- 真实数据认证、公司行动、历史股票池、真实交易日历、十交易日影子运行、生成 API 联调与正式 SMTP 发送均未完成，不据此宣称开箱即用。
- 数据授权、供应商能力与市场规则需在正式实施前独立核验；本项目用于研究，不构成投资建议。
