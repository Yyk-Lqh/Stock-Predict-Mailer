# 控制台配置、MCP 与 A2A 接口 v1

这是现有 [预测/事实/分析契约](interfaces.md) 的扩展。所有接口仅在本机服务开放；JSON UTF-8，请求/业务响应最大 1 MiB；未知配置字段拒绝。时间沿用 UTC offset/Z 约定。错误为 `{"error":{"code":"…","message":"已脱敏说明","retryable":false}}`。HTTP 400 表示输入/配置/服务调用失败，403 越权，404 不存在；任务失败使用其 status/metadata，不把 failed 当成 HTTP 成功分析。

## 配置 API 与会话

访问 GET `/` 建立 HttpOnly/SameSite=Strict Cookie。GET `/api/session` 返回 csrf_token；所有 POST/PUT/DELETE 都需要同源 Cookie 及 `X-CSRF-Token`。不开放 CORS；校验 Host/Origin，拒绝 DNS rebinding。控制台假设本机账户可信，不是多租户登录系统，不应反向代理到公网。

- GET `/api/{models|mcp|agents}`：列出配置；POST 同路径创建，返回 201。
- GET `/api/{collection}/{id}`：查看；PUT 完整替换配置，未提交的凭据保留；DELETE 删除，无引用才允许。
- POST `/api/models/{id}/test`：用 Mock 预测实际请求 Chat Completions 并校验结果；有调用及费用预算。
- POST `/api/mcp/{id}/test`：MCP initialize + tools/list + resources/list，返回工具输入/输出 Schema、资源及协商版本。此操作不赋予工具调用权限。
- POST `/api/mcp/{id}/call`：`{"tool":"get_context","arguments":{"subject":"DEMO.SZ"}}`，仅允许被用户标记 read 的白名单工具。
- POST `/api/mcp/{id}/read`：`{"uri":"stock://demo/contract"}`，精确 URI 白名单。
- GET/PUT `/api/settings`：默认模型、角色覆盖、温度、运行限额、邮件授权。
- POST `/api/settings/reset-temperature`：全局恢复 0.2，清空全部角色温度覆盖；模型 profile.parameters 中显式温度保留，可在模型编辑中清除。

配置 id 为服务端生成的 UUID hex。响应增加 id、has_secret、secret_mask、env_keys，绝不返回 api_key/auth_token/env 内容。PUT 时凭据为空字符串/null/未提交均保留；`clear_secrets:["api_key"]` 或 `["auth_token","env"]` 明确清除。API Key 仅在写入请求出现，经服务端 Fernet 加密保存，主密钥不存入数据库。原有数据和环境凭据不迁移。

## 模型配置结构

必填 name；其他字段默认值见 [示例](../examples/control-model.json)。provider 为 mock/openai_compatible；base_url 为 HTTPS 基础地址（例如 `https://api.openai.com/v1`，本机 HTTP 例外）；model 非空；timeout_seconds 1..120，retries 0..3，enabled 布尔。api_key 为写入专用字段。

supported_parameters 声明允许参数，当前支持 temperature、top_p、max_tokens、max_completion_tokens、response_format、seed、presence_penalty、frequency_penalty；parameters 为实际参数映射，须属于支持清单。输出上限 max_tokens 或 max_completion_tokens 必须且只能设置一个（1..32768）。response_format 仅支持 json_object；不支持时通过提示词要求 JSON 并严格解析。不支持任意透传工具调用或未知参数。

temperature_min/max 在 0..2 且 min≤max；不支持温度时从 supported_parameters 排除 temperature，适配器不发送它。实际温度优先级：角色覆盖 > 模型 parameters.temperature > global_temperature。全局默认 0.2，角色 null 表示继承；越界或对不支持模型设置角色覆盖会报 PARAMETER_UNSUPPORTED。模型能力来自用户按厂商资料声明和连接测试，不声称能自动发现所有厂商能力。温度只控制生成随机性，与股票置信度或准确率无关。

input_usd_per_million/output_usd_per_million 仅真实服务必需（每百万 token 的美元单价，非自动报价）；两者缺失时禁止真实推理。每次请求和重试预留 `(UTF8请求字节数+1024)*输入价 + 输出token上限*输出价` / 1e6，不回收预留预算，宁可提前降级。模型输入上限 16 KiB。此为应用侧保守额度，不是厂商账单/实际 token 保证，应同时配置服务商账户限额。

请求 POST `<base_url>/chat/completions`，Bearer API Key；system 指令固定，预测/事实/工具文本/同伴产物只出现在 user 数据中。模型必须输出 `{"conclusion_codes":["MODEL_UP"],"evidence_ids":["prediction:pred-001"],"uncertainty_codes":["MODEL_UNVERIFIED"],"delegate_roles":["prediction","risk","advice"]}`。允许的结论为 MODEL_UP/DOWN/FLAT、INSUFFICIENT、DATA_LIMITED、MARKET_RISK、VERIFY、WAIT、DIVERSIFY；不确定性为 NO_CONFIDENCE/NO_CONTEXT/MODEL_UNVERIFIED。未知内容和证据拒绝，自由文本不进入最终结论；方向冲突记录并排除。无效凭据不重试，429/5xx/网络超时仅在次数/时间/预算范围内重试。

## MCP 配置结构及授权

name 必填；transport=streamable_http（默认）或 stdio；前者 url 必填且是 HTTPS/本机 HTTP，可写 auth_token；后者 command 必填，args 字符串数组，env 字符串映射（写入专用、加密），不执行 shell，stdio 子进程在会话退出/超时后由 SDK 回收。命令行参数不是凭据字段，不应放密钥。timeout_seconds 默认 15，范围 1..120。

enabled 默认 true；allowed_tools 和 allowed_resources 默认空数组。effects 是工具名到 read/email/deny 的映射，未声明等价 deny。工具白名单和效果类型必须同时匹配；角色工具权限必须是服务授权的子集。主 Agent tools 使用 `<server_id>:<tool_name>`，当前仅主 Agent 调用 read 工具，固定传 `{"subject":预测对象}` 并要求返回现有 v1 上下文契约；不同参数/结果结构的服务需要薄适配器。子 Agent 当前只获得预测/校验事实，无工具、无密钥，也不能再委派。这是比配置最大深度更严格的叶子角色限制。

官方 SDK 负责 MCP initialize、版本协商、stdio/Streamable HTTP 会话、SSE 和回收。发现分页最多 10 页；输入/输出按 JSON Schema 校验，不接受会触发外部网络读取的 Schema 引用。支持 structuredContent 或单个 JSON text 对象；非 JSON 文本不能用作事实。资源内容按受限 JSON 包装返回 UI，作为不可信数据展示，不进入 system 指令。工具 schema/描述不授予权限，服务声明 readOnlyHint 也不替代用户授权。服务配置本身可启停/编辑/删除，停用后调用拒绝。

MCP 邮件工具须接受 `recipient,subject,text,html,idempotency_key`，返回 `{status:"submitted"|"sent"|"simulated"}`；其他状态按 uncertain 处理。工具不匹配此契约时需服务端薄适配，不假装通用服务都能发送。邮件调用同时要求工具白名单、effects=email、settings.mail 指定此服务/工具、recipient_allowlist 精确匹配和 synthetic 授权；每个任务最多一封。持久化发送标记避免重复；MCP 异常结果不确定时不自动重发。file/smtp 沿用原邮件 outbox 重试；普通 API 通过原适配器接入，不能在 MCP 配置里假称已经支持协议。

## 协作配置与任务 API

settings.default_model_id 可空（运行时将明确降级），agents 包含 main/prediction/risk/advice，每项为 model_id、endpoint_id、temperature（均可 null）和 tools 数组。main 固定本机编排，子 Agent 可指定外部 endpoint。外部 agents 配置必填 name/url，可选 enabled、timeout_seconds（默认20）、cost_ceiling_usd（默认0.01）、auth_token（加密）。远端调用按配置费用上限预留，向远端传同一额度，远端必须同意执行相应预算；不把第三方自报费用当可强制控制的账单。

limits 默认 `{max_subagents:3,max_depth:1,max_calls:8,timeout_seconds:90,child_timeout_seconds:20,budget_usd:0.1}`。支持最多3个叶子子 Agent、总深度上限0..3（当前叶子禁止递归，因此有效深度最多1），全局最多4个同时运行的主任务。所有模型尝试、MCP 工具及外部 A2A 委派均计入调用预算；发现/读取为用户直接操作，以各自超时控制；其连接测试单独计预算。子任务顺序执行以便共享预算与审计，失败降级；主模型仅对复杂任务请求委派，简单任务忽略委派建议。auto 在事实多于1条或 metrics 非空时视为复杂，complex 允许主 Agent 自行决定，simple 强制不委派。

- POST `/api/tasks`：必填 prediction（v1）；可选 context=null、complexity=auto/simple/complex、notify=false、recipient=null、depth=0。返回202 A2A Task；状态持久化。
- GET `/api/tasks/{id}`：任务与产物。POST `/api/tasks/{id}/cancel`：取消，终态不可再次取消。进程重启将中断任务标 failed/INTERRUPTED，不自动重新产生外部效果。

Task 为 `{kind:"task",id,contextId,status:{state,timestamp},artifacts:[]}`。state 为 submitted/working/completed/failed/canceled；失败有 metadata.error。completed 产物 DataPart 含 analysis（原契约，mode=orchestrated_bounded）、children（每项角色/状态/依据/不确定性）、conflicts（排除的冲突）、usage（调用数和费用预留）、mail、report_path。analysis.status=degraded 是明确的降级结果，不伪装成正常 LLM 输出。

## A2A 0.3 互操作子集

发现 GET `/.well-known/agent-card.json`（main）或 `/a2a/{role}/agent-card.json`；JSON-RPC POST `/a2a/{main|prediction|risk|advice}`。Agent Card 声明 protocolVersion=0.3.0、preferredTransport=JSONRPC、streaming=false、pushNotifications=false。不声称兼容 A2A 1.0 或完整协议实现。

支持 `message/send`、`tasks/get`、`tasks/cancel`；TaskIdParams `{id}`。message/send.params.message 为 `{kind:"message",role:"user",messageId,contextId?,parts:[{kind:"data",data:…}]}`。main data 为 TaskRequest；子角色 data 为 `{role,prediction,facts,depth:1,tools:[],cost_ceiling_usd?}`，返回 completed Task，其 artifact DataPart 是模型输出结构，经主 Agent再次校验。主任务非阻塞返回 submitted/working，调用 tasks/get 查询。子任务是同步非流式执行，有明确超时和结构化失败，不开放任意主机上的 Agent 创建。

JSON-RPC 错误 -32600 请求不合法、-32601 未支持方法、-32602 参数错误、-32001 找不到任务、-32002 不可取消；不包含内部异常正文。浏览器使用会话/CSRF；外部 A2A 客户端使用服务端环境 SPM_A2A_TOKEN 对应的 Bearer token（未设置则不开放 Bearer 通道）。A2A 凭据是单独配置，不复用模型 Key。当前监听本机，外部远程部署需要另行实现 HTTPS、身份与网络隔离。

## 官方依据与兼容边界

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)：兼容请求结构与生成参数。温度支持须按具体模型声明。
- [MCP 官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)：本项目锁定 1.30.0，通过本地已安装 SDK 源码和真实会话测试核对 ClientSession、stdio、Streamable HTTP；主分支已出现不同版本接口，不混用。
- [A2A v0.3 规范](https://a2a-protocol.org/v0.3.0/specification/)：JSON-RPC、Agent Card、Message/DataPart、Task/Artifact 与生命周期。按此明确版本实现有限子集。


## 2026-11-08 修复后的接口补充

本节优先于旧版“未实现”说明；前端文件未修改。仍为可信本机同源 session/CSRF 模型。会话任务的以下所有资源均要求原 owner 的 X-Memory-Key；无会话任务属于本机控制台操作者。

- GET `/api/tasks?after=0&limit=50`：`{items:[Task],next_after:整数或null}`。after 是任务存储游标，递增读取，limit 1..100；过滤其他 owner 的任务。不是按更新时间排序的状态订阅，列表中的状态需重新读取。
- GET `/api/tasks/{id}/report`：UTF-8 HTML 正式报告，浏览器可读取或另存；GET `/api/tasks/{id}/analysis`：同份结构化 analysis JSON。服务端从任务持久化产物渲染，不接受路径参数，不开放磁盘目录。未完成返回400/NOT_READY，未知任务404，其他 owner 403。
- GET `/api/tasks/{id}/mail`：当前 file/smtp 邮件公共状态（id/status/attempts/next_attempt/error），MCP 返回持久标记状态；未请求邮件为 `{status:"not_requested"}`。submitted 仅表示提交，不表示收件。
- POST `/api/tasks/{id}/mail/resolve`：`{delivered:布尔}`，仅 file/smtp uncertain 状态可人工留痕确认；不发邮件、不改写 EML。MCP 人工恢复和三队列统一管理仍按 mail-core-plan 独立迭代；没有浏览器批量 drain/send 接口。
- GET `/api/conversations/{id}?before=N&limit=20`：messages 按时间正序展示本页，next_before 非空时继续读取更早消息；before 为排他的 seq，limit 1..100，默认最后20条。
- GET `/api/{memory|conversations}?before=N&limit=100`：分页响应 `{items,next_before}`，limit 1..100，before 是排他的存储游标。没有查询参数时保留旧版数组响应。会话列表分页按创建存储顺序，不保证 updated 排序。
- DELETE `/api/conversations/{id}`：删除消息、摘要/检查点、待写记忆；运行中的会话返回 BUSY，先取消任务。已写长期记忆保留并可单独删除；任务归属绑定保留，删除会话不会公开私人报告。GET `/api/conversations/{id}/export` 返回完整消息 JSON（id/messages）；DELETE `/api/memory/access` 撤销当前访问密钥，运行中的私人任务会返回 BUSY。撤销不等于删除资料，不返回新密钥；应先完成导出和清理。pending 队列分页已补齐，见下节。

任务字段补全：prediction/context（无会话首次必需 prediction）；complexity=auto/simple/complex；notify=false、recipient=null、depth=0；reasoning_effort=null（继承默认五档）；chart_data=null；goal=overview/risk/comparison；conversation_id=null；message 最多4000字符；constraints 最多12项；report_format=null/brief/standard；remember 最多10个 MemoryEntry；fresh_context=false；knowledge_query 最多4000字符；knowledge_to_model=false。未知字段拒绝，知识检索需会话与私有密钥。不是上游任意JSON的透传口。

事件恢复：GET `/api/tasks/{id}/events?after=N` 每页最多100，客户端保存已处理的最后seq，循环排空，重连沿用游标。另读任务 status 判断 completed/failed/canceled；step completed 不代表任务成功。重启中断为 failed/INTERRUPTED；不要自动重发任务或邮件。不是 SSE/WebSocket。

知识证据：主模型只接收服务端从有权检索结果中选择、重新校验版本hash/元数据的完整片段；证据数组最多4000 UTF-8字节，并为主输入预留空间。放不下的片段整体跳过，KNOWLEDGE_BUDGET 明示；不截断财务句子、不移除来源定位。source_material 为不可信资料，模型仍只能选择预定义结论代码，只有包内 citation_id 加入主模型白名单。analysis.knowledge_evidence 包含 as_of/results/used_ids，HTML和邮件共用该快照。知识声明仍不等于独立验证事实，不能用于训练发布。超长用户约束、近期会话本身仍可能触发上下文限制，真实厂商token预算另待验。

上游模型仍需交付 docs/interfaces.md 中严格 v1 prediction 和可选同标的 facts/chart_data；不交付任意权重让默认入口加载。真实模型、Embedding、第三方MCP/A2A与邮箱收件均未验证。上传继续是 JSON base64，不是 multipart；知识最大原件10MiB、上传请求15MiB，其他JSON请求1MiB。错误继续使用 `{error:{code,message,retryable}}`。


## 2026-11-08 续轮：pending记忆分页

GET `/api/memory/pending?limit=100` 返回 `{items:[待写条目],next_before:整数或null}`，使用原同源session和X-Memory-Key授权。条目保留 id/source_conversation/source_message 与记忆内容。limit默认100、范围1..100；before默认2^63−1、范围0..2^63−1，是排他的数据库行游标。按游标倒序读取，next_before非空时用于下一页；为空表示本次扫描已到末尾。读取不消费记录，不触发向量写入或模型调用。

无查询参数时兼容旧数组响应（最早100条），前端应使用带limit的分页形式获取全部待写记录。只接受单个before、limit；未知、重复、空值、非整数和越界参数返回400/INVALID_INPUT。会话列表和长期记忆分页采用相同严格参数检查。游标只对当前owner过滤后的记录有效，不能用于越权。队列不是冻结快照：后台写入成功会移除待写记录；扫描中新加入的较大游标记录从下一次首页刷新获取，删除的记录不返回。

HTTP联调覆盖205条记录、多页去重与完整性、删除后续读、新增后刷新、跨owner隔离、读取不消费和非法参数。超16KiB知识检索的预算回归与正式HTML/analysis JSON/本地模拟EML引用链路已补验。真实外部模型与邮箱收件仍不在本轮验证范围。
