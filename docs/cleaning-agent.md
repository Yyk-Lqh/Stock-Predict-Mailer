# 语义清洗 Agent：模型接入、证据校验与复核

本轮只实现后端。清洗模型默认关闭，与 Embedding 和股票分析模型分别配置；复用现有私有访问密钥。独立 worker 不占分析子 Agent 名额，不运行文档中的工具指令，不发布行情训练快照，不修改预测模型，不获得邮件权限。

## 处理步骤

1. 上传和原文件版本保留沿用私有知识库接口。
2. 独立 `knowledge-worker` 解析、规则清洗并保存 parsed/chunked 检查点。
3. 启用清洗模型时，按长度分批发送资料，使用 JSON Schema 要求返回实体、关系、事件、财务指标候选。`unstructured` 模式跳过已有 subject/predicate/object 的结构化行，其余片段仍可提取；`always` 处理全部片段。模型不重写原文片段或数值。
4. 代码检查片段编号、逐字引文及 Python Unicode 字符起止位置，检查主体/客体原名、关系提示词、日期、原始指标名称、数值、单位和周期。数字不得四舍五入、换算或把年份冒充指标金额；时间必须能在引文中定位，不从上传时间猜事件日期。显式否定、传闻和不确定措辞不能丢失。被截断的模型输出、额外工具指令或错误 JSON 均失败。
5. 候选和校验错误进入 extraction 检查点，文档 status=review、step=extracted，旧活动版本继续使用。所有模型处理文档都需显式批准，包括空候选；无依据候选不能批准。代码校验只证明来源约束，不能保证事实真实、关系方向正确、指标口径完整，审阅者仍需核对。
6. 批准后状态转为 pending，worker 从审批检查点继续生成向量并事务发布。拒绝则 rejected，不发布；失败则 failed。中断不会变成 ready，重试复用已完成批次，不重复收费预留中已记录的成功调用。

持续或一次运行方式与之前相同：

```powershell
uv run stock-predict-mailer --config config/local.toml knowledge-worker --poll 2
uv run stock-predict-mailer --config config/local.toml knowledge-worker --once
```

`--once` 如果本批存在 failed 返回 2；待复核的 review 不是已入库，需读取文档状态后完成审批。worker 重启将 processing 标为失败，须显式 retry。批准后的发布失败会保留审批与提取结果，重试不会重新调用清洗模型。

## 独立模型配置

所有接口仍要求本机 session、私有 X-Memory-Key，以及写请求的 X-CSRF-Token。通过 `GET/PUT /api/knowledge/cleaner/config` 查询/保存。默认 provider=none；它保持先前规则清洗与结构化入库行为。清洗配置不自动继承分析模型，也不随 Embedding 切换。

Ollama 原生聊天配置示例：

```json
{
  "provider":"ollama",
  "base_url":"http://127.0.0.1:11434",
  "model":"your-cleaning-model",
  "version":"user-declared-v1",
  "mode":"unstructured",
  "allow_external":false,
  "timeout_seconds":30,
  "document_timeout_seconds":180,
  "max_calls":8,
  "max_input_chars":12000,
  "max_output_tokens":2500,
  "budget_usd":1.0,
  "input_usd_per_million":0.0,
  "output_usd_per_million":0.0
}
```

OpenAI 兼容聊天服务使用 `provider=openai_compatible`、`base_url=https://service.example/v1`、实际 model 名和独立认证 api_key。调用路径分别为 `/api/chat`、`/chat/completions`。温度固定为 0；Ollama 使用 format schema，兼容接口使用 response_format/json_schema。服务不支持此契约时直接报错，不静默降级为未约束文本。配置 version 是用户声明版本，不能自动识别服务端悄然更新权重。

api_key 写入时加密，查询只返回 has_secret；变更目的地址不继承旧凭据。清除认证可在 PUT 中显式传 `clear_secret=true`。只发送配置字段，不把查询响应中的 fingerprint/has_secret/review_policy 原样回传。远程地址必须 HTTPS，allow_external=true 才会发送资料；本机 loopback 可用 HTTP。拒绝跨地址重定向。保存 allow_external=false 可撤销外发，正在执行的请求无法撤回，但返回的结果不会绕过新的配置检查发布。

`POST /api/knowledge/cleaner/test` 只发送固定测试文本，验证连接和结构化输出，不能代表实际抽取准确率。模型须由操作者事先在服务端部署，本工具不自动下载模型。

max_calls、费用预留和模型调用耗时跨失败重试累计。费用使用配置的输入/输出单价和保守输入字节量、输出 token 上限计算，调用前先持久化预留，失败也不自动退回；这是预算预留而非服务账单。单价为 0 表示按免费服务核算，不能用于保证收费服务的真实账单。没有自动模型重试，预算耗尽须显式重置提取，不能无限循环。max_input_chars 限制单次资料 JSON 字符数，系统提示/schema 另计入费用预留；不截断原文。

## 审阅接口

- `GET /api/knowledge/documents/{id}`：包含状态、步骤、警告、extraction、review，以及原文与清洗结果。
- `GET /api/knowledge/documents/{id}/review`：返回 digest、完整候选、validated、validation_errors、原文位置、模型身份、提示词版本、调用和预算记录。
- `POST /api/knowledge/documents/{id}/review`：提交 decision/digest/approved_ids。只有当前 review 状态接受操作，digest 防止批准旧批次；其他用户不可读取或批准。
- `POST /api/knowledge/documents/{id}/retry`：重试失败处理；保留成功解析、切分和模型批次。
- `POST /api/knowledge/documents/{id}/reextract`：显式清除未发布版本的模型提取和审批检查点，再次入队。可用于更换模型、修改预算或拒绝后重提；保留原文件、解析和规则切分。活动版本不可原地重提，应上传新的源版本。

批准部分候选：

```json
{"decision":"approve","digest":"<GET 返回的 digest>","approved_ids":["<validated=true 的候选 ID>"]}
```

批准空列表表示仅批准原始清洗资料，模型候选全部不采纳。`decision=reject` 必须传空 approved_ids，并保留旧活动版本。缺失、重复或校验不通过的 ID 均拒绝。审阅决策留在 review_audit；资料删除同时清理提取、审批、关系、向量、片段与原文件，不复活旧版本。

## 候选与检索规则

候选字段包含 kind、chunk、quote、start/end、subject、predicate/object、assertion、valid_from/to、event_date、value/unit/period；nullable 字段也必须返回。起止位置针对清洗后的 chunk.text，原文件定位仍由该片段的页/行/段落/工作表等字段承接。

- entity 保留原文名称，不自动把简称合并为同一法人或进行人物消歧。
- relation 的 predicate 目前限供应商、客户、所属行业、任职、涉及事件、投资、合作。明确的 asserted 关系经人工批准后才进入正向关系表；negated/uncertain 候选保留引用声明，不当作肯定边遍历。关系生效期未知时不补造日期。
- event 必须保留原文事件类型和主体，发生时间未知或晚于查询截止日期时不支持“当时已经发生”的风险推断。事件只作为有来源的声明，不是已独立核实事实。
- metric 的 predicate 是原文财务指标名，value/unit/period 原样保留；要求原文中指标名后出现对应数值和单位。复杂叙述或复杂表格未通过此规则时需拒绝候选或更新原件，不绕过校验。

查询返回已批准 extractions、来源日期和定位。对于模型提取的供应链材料，条件性风险推断要求已批准、肯定、日期明确的关系与事件，两份证据同时引用。未来事件、传闻、否定声明不得触发肯定风险结论。财务冲突按同一主体/指标/周期/单位分组；使用 Decimal 比较数值但保留原始格式，12.30 与 12.300 不误判为冲突，不跨单位自动换算。原先规则路径保持独立，不能把所有文章提及风险词都当作确定事件。

## 验收与后续模型评估

合成标注样例位于 tests/test_cleaning_agent.py，包括明确供应商、否认供应商、可能供应商、带日期停产、未来停产、精确财务数值与同口径冲突。它们验证工程约束和本地 HTTP 模拟协议，不代表真实模型质量。

```powershell
uv run python -m unittest discover -s tests -p test_cleaning_agent.py -q
```

真实模型验收应使用操作者授权的公告、财报和事件资料，逐条标注主体、关系方向、肯定/否定/传闻、日期、数值单位周期和引用位置；记录模型/提示词版本、实体关系精确率与召回率、原文定位通过率、错误数字接受率、复核工作量和调用费用。分别比较模型，保留错误样例再调提示词。当前没有提供真实资料或服务，因此没有真实模型准确率结论。

后续按实际文件占比考虑 OCR/布局识别。独立图数据库、重排序模型、前端和自动训练发布均未在本迭代实现。
