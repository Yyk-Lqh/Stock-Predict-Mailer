# 在分析任务中固定预测与评价定义

阶段 6B（2026-11-16）在日常分析入口接入 6A 归档。只在本次请求显式提供评价定义时启用；不会从配置、模型输出、会话或长期记忆推断评价口径。设计见[实施计划](forecast-task-plan.md)，定义格式与离线评估见[归档手册](forecast-evaluation.md)。

## CLI

为当前配置的 file/http 预测准备匹配的 definition.json，再执行：

```powershell
uv run stock-predict-mailer --config config/local.toml run --evaluation-definition definition.json
```

命令首先读取并校验上游预测，然后注册该预测与定义，再获取上下文、分析、保存报告及入队邮件。`--send` 延续原有明确交付选项；不加此选项只入队。未提供 `--evaluation-definition` 时不创建归档，分析内容及身份规则保持原样。默认 Mock 的生成时间/身份可能随调用变化；复现同一注册应使用固定的 file/http 预测。

成功输出增加 `forecast`，包含 created、forecast_id、registered_at、definition、content_id 和 integrity_id 等字段。重复提交完全相同的预测与定义会复用首次注册时间和记录；相同预测身份改变内容或口径会返回 `FORECAST_CONFLICT`。合法的新预测应使用新的 prediction_id，不能为了覆盖同一预测的定义改写旧档案。

定义 JSON 限制 1 MiB，拒绝重复键与非有限数字。文件缺失、非法定义、目标已过、锁占用及发布失败均以既有结构化错误返回，不进入本次分析或邮件交付。

## 控制台任务 API

沿用现有本机认证、CSRF、私有会话及收件人权限规则，在 `POST /api/tasks` 请求中增加可选对象 evaluation_definition。可使用已有完整契约文件组装请求体：

```python
import json
from pathlib import Path

body = {
    "prediction": json.loads(Path("prediction.json").read_text(encoding="utf-8")),
    "evaluation_definition": json.loads(Path("definition.json").read_text(encoding="utf-8")),
    "notify": False,
}
# 将 body 发送到已有授权会话的 POST /api/tasks。
```

接收请求时纯校验定义；执行归档前再次检查预测和目标时效。因此排队期间过期的请求也会失败，不继续调用知识检索、MCP、模型或邮件。未获准收件人的请求在接收阶段拒绝，不产生注册记录。

进度增加“固定预测与评价定义”步骤及 `forecast` 事件，事件包含 forecast_id 和 created。完成结果的 `analysis.forecast_evidence` 保存绑定证据。多轮会话下一轮若仍需绑定，必须再次显式传递 evaluation_definition；即便沿用相同预测也不自动继承。6B 为 CLI/API 接入，后续 6C 已提供[网页定义表单与到期列表](forecast-console.md)。

## 报告、邮件与失败恢复

`forecast_evidence` 包含注册记录除 prediction 以外的字段；校验时使用分析自身的完整 prediction 重建注册记录，检查身份、内容摘要、注册摘要和时间/定义约束。报告 HTML、纯文本与冻结邮件显示同一归档编号、目标时点、指标/单位、基准来源及平盘阈值；交易日周期同时展示声明日历。

本轮不读取观测或到期评估结果，不把事后信息用于原分析，也不自动执行评估。摘要用于核对一致性，不能认证来源或抵御本地用户重写内容并重算全部摘要。未来注册记录不能用于当前报告。

注册、报告和邮件不是单个事务。归档失败会阻断后续流程；注册成功后，即便随后上下文失败、任务取消或保存失败，原预测记录仍保留，避免丢弃未成功分析的样本。可通过 `forecast list/show` 查询，再按原预测与定义重试。任务中断不会自动重跑；已有邮件仍遵循原来的幂等和不确定状态处理。

邮件冻结了完整的分析及绑定证据，后续投递不依赖读取归档目录，也不会因后续追加评估而改变邮件。邮件投递继续受预测有效期、收件人授权和合成标记等原有约束限制。

## 验证

- 新增 27 项集成测试全部通过，覆盖精确绑定及篡改、输入边界、默认兼容、CLI 重复运行、API 收件人拒绝、目标过期、锁冲突、取消前后行为、多轮不继承、报告 HTML 转义、声明日历及文件邮件证据一致性。
- 完整回归执行 741 项，739 通过、2 项 Windows 符号链接权限跳过，耗时 289.150 秒。
- 离线构建 wheel，在仅有基础依赖的 Python 3.12 环境安装后执行归档与联动测试共 59 项，58 通过、1 项相同权限跳过。源码目录外确认 numpy/pandas/sklearn/requests/baostock 均不存在，实际 CLI 完成归档、报告、文件模拟邮件及重复任务幂等验证；cp1252 环境中输出仍可解析为 UTF-8 JSON。
- Ruff、compileall、静态结构目录、命名、仓库卫生、diff 检查通过；相关 7 份文档的 70 个本地链接有效。没有修改前端表单，本轮通过本机 HTTP 测试任务 API，未做浏览器 UI 验收。
- 真实工作区只读检查：42 个来源文件前后摘要一致，0 条预测归档，没有创建归档目录。本轮未调用真实行情/模型/SMTP，未进行实际数据库迁移、备份恢复、服务重启或 Git 提交/推送；前几轮尚未提交的修改继续保留。
