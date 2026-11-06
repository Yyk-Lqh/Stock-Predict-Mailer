# 混合执行与进度接口

主 Agent 根据任务目标、输入与获准工具生成阶段计划。工具阶段使用受限的 ReAct 循环，根据结构化观察决定重试、补查或继续。事件展示操作和结果摘要。简单任务走单 Agent 路径。

档位依次为 light、medium、high、extreme、ultra。默认 extreme 延续既有复杂任务的协作行为。档位预算与管理员限额取交集。模型原生参数由配置明确声明映射，温度独立解析。

实施顺序为执行预算与事件存储、受限工具循环及 A2A、图表与报告、控制台交互、Mock 验收。

## 档位与设置

`GET/PUT /api/settings` 支持 `default_reasoning_effort`。任务提交可用 `reasoning_effort` 覆盖，省略或传 null 时继承默认值。任务 `goal` 可选 `overview`、`risk` 或 `comparison`，用于设置分析焦点及图表展示优先顺序。

- 轻度 `light` 上限为 7 步、1 次 MCP、3 次调用、20 秒、0 个子 Agent。
- 中 `medium` 上限为 8 步、2 次 MCP、5 次调用、45 秒、0 个子 Agent。
- 高 `high` 上限为 10 步、3 次 MCP、8 次调用、75 秒、0 个子 Agent。
- 极高 `extreme` 上限为 14 步、5 次 MCP、12 次调用、120 秒、3 个子 Agent。
- `ultra` 上限为 18 步、8 次 MCP、24 次调用、240 秒、3 个子 Agent。

步骤包含计划阶段和 A2A 子步骤。工具重试和 MCP 邮件占 MCP 额度，也计入总调用次数。总调用、时限与子 Agent 数再受管理员限制。费用、委派深度和子任务超时继承原配置。极高和 Ultra 仅在复杂任务中采纳主 Agent 的委派选择。原生推理能力由模型配置 `reasoning_effort_map` 声明，如 `{"high":"medium","ultra":"xhigh"}`。未映射的档位使用应用预算，模型请求省略该参数。每个本机模型调用事件记录实际使用的温度和映射。外部 A2A 对端按其自身模型配置执行，并受委派预算与时限约束。
