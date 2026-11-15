# 单标的输入、报告与本地通知

本阶段提供 CLI 闭环：第二阶段基本面截止日视图 + 上游 v1 预测 → 分析 → 报告 → 本地邮件。读取已生成资料只需要基础安装；没有自动采集、模型训练或控制台界面接入，行情目录价格暂不作为事实输入。

## 准备与运行

1. 准备有效上游预测 JSON。标的为六位数字加 `.SH`、`.SZ` 或 `.BJ`，必须包含预测 ID、模型版本、生成时间、有效期、周期及方向或数值。缺失预测不能以默认 Mock 代替。
2. 准备第二阶段 `fundamental_as_of_<date>.csv` 及 `.metadata.json`。本阶段新增 `run_complete=true` 表明选定采集任务完整，行内 `provider_symbol` 记录实际采集路由（例如 sz.000001）。明确限量的单标的任务可用，历史全集仍标为 unknown。旧视图缺这些信息时须重新采集对应行并生成视图，不要手动伪造完成或交易所标记。
3. 按 [agent-crawler-example.toml](../config/agent-crawler-example.toml) 修改输入路径，尤其是视图日期。相对路径均相对于配置文件。

```powershell
uv sync --locked
uv run stock-predict-mailer --config config/agent-crawler-example.toml run
# 上一条生成报告并入队；--send 执行配置中的投递。
uv run stock-predict-mailer --config config/agent-crawler-example.toml run --send
```

示例 transport=file，`--send` 仅生成本地 EML，状态 simulated。SMTP 仍沿用原授权及不确定状态处理，本阶段未做真实邮箱验收。已有知识库/研究环境用 `uv sync --all-extras --locked` 保留全部可选功能；读取 CSV 本身不需要 crawler 依赖。

## 时间、单位与错误

按六位代码筛选并核对 provider_symbol 与预测中的交易所，选择最新可用报告期。缺路由不会按代码推断，路由声明也不等于独立认证。重复报告期、重复/缺失表头、非有限数值、哈希不符、未验证披露、任务残缺或未来来源时间均明确报错。

- observed_at：报告期末上海时区 23:59:59。
- available_at：披露日上海日终与原始 collected_at 的较晚者。只有日精度时不会在当日日终前提前使用该行。
- unit：`source_native:<字段>`，不推断百分比、金额或可比口径。
- source：baostock 来源声明，不代表独立认证。

复制或读取文件不会刷新事实年龄。季度数据通常超出默认一天，示例显式设 `max_context_age_seconds=31536000`；仅该配置上限扩大到 315360000 秒，其他超时与预测时效上限不变。未配置时仍使用原默认值。

没有匹配可用资料返回 CONTEXT_UNAVAILABLE，任务未完整结束返回 UNVERIFIED_CONTEXT，旧事实返回 STALE_CONTEXT。原生单位、日期精度、事后修订、历史股票池及来源限制贯穿报告和邮件；不能把此视图直接用于声称无未来信息泄漏的历史回测。

## 冻结输入与引用

CLI 成功结果包含 `input_snapshot` 路径。工作区文件：

```text
input-snapshots/<snapshot_id>.json
analysis/<analysis_id>/analysis.json
analysis/<analysis_id>/report.html
agent-outbox/<message_id>.eml
sent/<message_id>.eml
```

快照保存标准化预测、完整输入上下文、所选原始行、元数据和字段映射。snapshot_id 是其内部 snapshot 对象规范 JSON 的 SHA256；CSV 摘要针对实际读入字节，元数据摘要针对规范 JSON 内容。多标的源文件不整份复制进归档，只保留全文件哈希引用与所选行号。

每条事实关联原始字段；报告显示来源文件名、行号、报告期、披露日、采集时刻。JSON、HTML、纯文本/HTML 邮件使用相同快照 ID 与引用。模型即使未选某些事实，完整输入仍留在归档。

相同预测、源文件和元数据复用快照及邮件。来源内容改变会产生新版本，包括源 CSV 中其他标的改变。已归档文件被修改时拒绝覆盖。哈希用于追溯及损坏检测，不代表来源签名或文件系统写保护。

CSV 上限 64 MiB、sidecar 64 KiB、证据 256 KiB。可选 HTTP Agent 仍只接收原预测与事实契约，不发送整份 CSV 或本地路径。

## 验证

```powershell
uv run python -m unittest discover -s tests -p test_crawler_analysis.py -v
```

测试使用合成来源格式与 synthetic 预测，运行实际 CLI、报告保存及 file transport，不连接真实行情、模型或邮箱。阶段范围及结果见[实施计划](single-symbol-plan.md)。
