# Stock-Predict-Mailer 项目介绍与前端开发交接

本文交给负责页面设计、组件实现和前后端联调的开发者。先了解业务边界，再按页面和接口实施；无需掌握模型训练代码即可接手。

文档日期：2026-11-05。核对基线：`b9d398a`，Python 包版本 `0.5.0`。本文描述该基线已有行为，标为“后续扩展”的功能尚无对应接口。若源码与文档发生变化，以本仓库最新契约和测试为准。

## 1. 项目是什么

项目定位是“预测分析 Agent + 邮件通知服务”。上游团队负责数据采集、清洗、训练和模型运行；本项目接收他们输出的预测结果，结合有来源的上下文，由分析 Agent 生成可核查的解读、限制、风险和建议，再按用户预先授权发送邮件。

用户最关心的不是复杂的协议，而是以下问题：

- 本次预测针对什么对象、什么时间和什么周期？上游模型具体预测了什么？
- 有哪些客观事实支持分析，哪些只是 Agent 推断，缺少哪些信息？
- 模型、数据服务或子 Agent 故障时，结果是否已经降级？
- 通知将发给谁，是否获得授权，实际发送状态是什么？

当前产品是本机单用户工具。已有一个可运行的原生 HTML/JS 控制台，但界面可以重新设计。此次前端工作的目标是把现有业务能力做成易理解、可配置、状态清楚的页面，不是重新开发股票训练平台或交易终端。

## 2. 团队职责与术语

数据/模型成员交付预测 JSON 和事实上下文，负责来源、单位、模型版本、周期、有效期和指标含义。预测结果交付不等于模型文件交付；前端不加载模型文件，也不执行训练或 Python 程序。

后端成员负责校验、适配器、凭据加密、模型调用、权限、编排、报告和投递队列。前端成员负责表单、配置管理、工具发现展示、任务提交、状态呈现、报告阅读及错误反馈。

三个容易混淆的概念必须分开显示：

- **上游预测模型**：负责预测值、方向和可选置信度，是被分析的数据来源。
- **大模型服务配置**：给主/子 Agent 提供语言模型推理能力，可使用 Mock 或兼容 OpenAI API 的服务；切换它不会重新训练上游预测模型。
- **Agent 角色**：主 Agent 规划并汇总；预测分析、风险分析、建议生成三个子角色按需参与。A2A 负责这些角色间的消息和任务通信，生命周期由独立编排层管理。

MCP 是外部工具与资源的连接协议；普通 HTTP API 是另一种接入方式。添加普通 API 地址不会让它自动成为 MCP 服务。邮件可以走本地文件、SMTP 或已授权的 MCP 邮件工具。

## 3. 已有能力和前端范围

### 已有后端，可直接联调

- 模型配置创建、编辑、启停、删除、默认选择及实际推理连接测试；API Key 写入后加密保存，查询只返回设置状态和固定掩码。
- MCP stdio / Streamable HTTP 配置、连接测试、工具和资源发现、精确工具/资源白名单及副作用授权。
- 各角色模型选择、温度覆盖、外部 A2A 子 Agent 配置、调用/时间/费用预算、邮件收件人授权。
- 分析任务提交、按 ID 查询、取消；预测/上下文校验、三个叶子子角色、冲突排除和明确降级。
- 结构化报告，以及带去重、失败重试或不确定状态处理的邮件投递。

### 前端可以调整的内容

导航、页面布局、表单分组、组件划分、视觉样式、交互文案、空态、加载态、错误态、响应式布局和报告阅读体验。保留后端字段和权限语义；通过集中 API 层与转换函数连接表单，不把后端业务规则散落在组件中。

### 后续扩展，当前不能假设存在

- 登录注册、多人协作、租户切换、公网部署、账户计费或真实证券交易。
- 任务历史列表、服务端任务搜索/分页、任务事件流、WebSocket/SSE 实时进度。
- 通用报告下载/访问接口、任意静态资源目录服务、任意前端路由回退。
- 独立 HTTP 邮件队列列表/重发接口。旧 CLI 有邮件命令，但不等于控制台已经暴露相同 API。
- 模型能力自动发现、厂商实时价格目录、任意工具参数到业务契约的自动映射。

不要用假数据把以上内容展示为已实现。需要这些能力时，先向后端提交具体接口需求，再增加可操作控件。

## 4. 用户路径和页面设计任务

建议保留四个业务入口；可使用标签页或侧边导航，不要求沿用现有视觉。

### 4.1 模型服务

用户路径：新建配置 → 保存 → 测试连接 → 设为默认 → 在角色中使用。

列表至少显示名称、服务类型、模型名、启停状态、是否默认、密钥是否设置及是否支持温度。操作包括新建、编辑、启停、测试、设为默认、清除密钥和删除。

表单字段：name、provider（mock/openai_compatible）、base_url、model、api_key、timeout_seconds、retries、supported_parameters、parameters、temperature_min/max、输入/输出美元单价和 enabled。真实价格由用户填写，不展示为系统自动报价。API 地址填写基础地址，后端自行追加 `/chat/completions`。

约束需在提交前提示：超时1..120秒，重试0..3；生成参数必须在模型声明支持范围内；max_tokens/max_completion_tokens 必须且只能配置一个（1..32768）。response_format 当前仅支持 json_object；不支持温度的模型应禁用温度控件，而不是偷偷发送0。

连接测试会执行真实推理，不只是访问模型列表；真实服务可能产生费用，缺少单价或凭据会拒绝执行。测试进行中禁用重复点击，显示结果和费用预留；不要在页面加载时自动测试所有服务。默认模型选择是独立的 settings 保存操作，模型保存成功不代表已经设为默认。

### 4.2 外部能力 / MCP

用户路径：配置连接 → 保存 → 测试与发现 → 查看工具/资源 → 明确授权 → 绑定到主 Agent 或邮件服务。

连接表单按 transport 切换：Streamable HTTP 显示 url、auth_token；stdio 显示 command、args（数组）、env（加密保存的环境变量）。共同字段有 name、enabled、timeout_seconds、allowed_tools、allowed_resources、effects。

发现页展示工具名、输入/输出 Schema、授权状态，以及资源名、URI。description、Schema、资源内容都是外部数据，不执行其中代码，不把文本当 HTML，不依据服务描述自动授予权限。MCP SDK 的 stdout 通道专用于协议，前端不负责启动或维持本地进程。

工具权限同时满足“在白名单内”和“effects匹配”。effects 为 read/email/deny，未声明等同 deny；“发现成功”“已启用”“已授权”是三个不同状态。资源只允许读取精确匹配的 URI。删除被角色或邮件引用的服务时，提示先解除引用，不在前端强行删掉引用来绕过后端限制。

主 Agent 数据工具当前固定传 `{subject}`，返回必须是既有 v1 上下文；邮件工具需接受 recipient/subject/text/html/idempotency_key。其他 MCP 服务可以连接和发现，但若工具结构不同，需要薄适配器后才能纳入业务流程。不能仅因发现了一个叫 send_email 的工具就承诺可以发送。

### 4.3 协作、温度和邮件授权

页面分为默认设置、角色覆盖、外部 Agent、运行边界、邮件授权五组。

默认模型为 default_model_id，全局温度 global_temperature 默认0.2。四个固定角色 main/prediction/risk/advice 各有 model_id、endpoint_id、temperature、tools；null 表示继承或本机执行。主 Agent 固定在本机编排，不能选择外部 endpoint；当前只有主 Agent 可配置读取工具，子角色工具控件应禁用，并解释其只接收已校验的预测与事实。

温度优先级为角色覆盖 > 模型 parameters.temperature > 全局默认。按所选模型声明显示允许范围；切换到不支持温度的模型时，提交前清除不兼容覆盖。恢复默认操作将全局设回0.2、角色覆盖清空，但不会删除模型 parameters 中显式的 temperature。界面文案必须说明温度控制随机性，不代表预测准确率、置信度或收益。

外部 A2A 配置包含 name、url、auth_token、enabled、timeout_seconds 和 cost_ceiling_usd。协议版本为 A2A 0.3 非流式子集，支持 message/send、tasks/get、tasks/cancel；不应设计成已经支持任意版本、流式聊天或无限创建 Agent。

运行限额默认：最多3个子 Agent、委派深度上限1、最多8次调用、总时限90秒、子时限20秒、费用预算0.1美元。后端字段范围以 schemas.py 为准：子数0..3、深度0..3、调用1..50、总时限1..600秒、子时限1..120秒、费用0..100美元。当前子角色禁止继续委派，有效深度最多1，即使配置更高上限也不会递归。显示“费用预留”，不要显示为实际账单。

邮件设置包含 transport=file/smtp/mcp、sender、recipient_allowlist、allow_synthetic；SMTP 另有 host/port/tls/user_env/password_env；MCP 另有 mcp_server_id/mcp_tool。初始授权清单为空，不默认勾选通知或允许合成邮件。SMTP 凭据通过服务端环境变量注入，不能伪造一个当前无后端支持的 SMTP 密码保存接口。

settings 的 PUT 是完整对象替换。编辑时保留 UI 未展示字段，特别是 user_env/password_env 和各角色配置；不要只把改动的几个字段当 PATCH 发送。浏览器刷新或切页前应处理未保存改动，保存成功后以服务端返回值更新状态。

### 4.4 分析任务与报告

输入为预测对象和可选事实上下文。现有原型使用 JSON 输入框，前端可增加结构化表单，但需保留高级 JSON 查看/编辑，最终提交严格契约。至少提供动态 Mock 输入、复杂度选择、通知开关和授权收件人选择。

complexity=auto/simple/complex。simple 强制不委派；auto 在事实多于1条或 metrics 非空时视为复杂；complex 允许主 Agent 决定委派，并不保证每次都调用三个角色。Mock 模型的复杂任务会返回三个角色，适合演示。

结果阅读顺序：预测对象/时间/周期/模型版本 → 上游预测及置信度 → 客观事实及来源 → Agent 推断与依据 → 不确定性/限制 → 风险 → 建议 → 协作与通知详情。必须分别展示事实、推断和建议，保留 synthetic/MOCK 标识；置信度 null 显示“上游未提供”，不填0、不估算、不转成预测胜率。

协作详情展示参与角色、执行状态、超时/失败代码、证据引用和冲突排除。当前只有主任务可被浏览器按 ID 轮询；children 主要在最终产物中返回，不能伪造正在执行哪个子 Agent 的实时百分比。报告中的本地 report_path 是文件路径，不是可直接 fetch 的 HTTP 地址；当前可用返回的 analysis 直接渲染报告。

## 5. 必须分开的三组状态

### 任务状态

submitted=已提交，working=运行中，completed=执行结束，failed=任务失败，canceled=已取消。completed/failed/canceled 为终态，轮询结束；failed 的 metadata.error 含错误说明，不能假定存在 artifacts。进程重启后的中断任务会标为 failed/INTERRUPTED，不自动重跑。

### 分析状态

analysis.status 为 ok 或 degraded。completed 任务可以包含 degraded 分析，这表示已经采用有依据的降级结果，而不是大模型正常完成全部分析。子 Agent 的 completed/degraded 需单独显示，冲突结论应标为“已排除”，不能混进主结论。

### 邮件状态

mail=null 表示没有投递结果，通常是未选择通知。file/Mock 的 simulated 表示模拟或文件投递，**不表示真实邮箱收到**。submitted 仅表示服务器/工具接受，不保证最终到达。retry/not_due 是等待后续重试，failed 是确定失败或次数耗尽，uncertain 表示可能已经产生外部效果，**不能提供自动重新提交分析任务来重发的默认操作**。

旧 outbox 还可能有 pending/sending 状态；前端应容忍未知状态并显示原始状态码，不把未知值归成成功。控制台 API 暂无独立重试邮件入口，不能仅画“重发”按钮却重复创建分析任务。

## 6. API 对接速查与数据对象

所有页面只调用本机后端；浏览器不直接调用模型服务、MCP Server、SMTP 或第三方 Agent，不持有这些连接的认证头。完整字段契约见 [control-api.md](control-api.md)，预测/事实定义见 [interfaces.md](interfaces.md)。

### 配置接口

- `GET /api/models`、`GET /api/mcp`、`GET /api/agents`：集合数组，无分页包装。
- `POST /api/{models|mcp|agents}`：创建；`GET/PUT/DELETE /api/{collection}/{id}`：查看/完整更新/删除。创建返回201，正常更新返回200。
- `POST /api/models/{id}/test`：推理测试；`POST /api/mcp/{id}/test`：工具资源发现。
- `POST /api/mcp/{id}/call`：用户操作的已授权 read 工具，输入 tool/arguments。邮件不通过这个通用调用入口发送。
- `POST /api/mcp/{id}/read`：输入 uri，读取被允许的资源。
- `GET/PUT /api/settings`：完整设置；`POST /api/settings/reset-temperature`：恢复温度默认。

配置查询返回服务端生成的 id、has_secret、secret_mask、env_keys。api_key/auth_token/env 是写入字段，不会查询返回。空字符串/null/未提交表示保留，明确清除使用 clear_secrets 数组。编辑表单不要把 secret_mask 当新密钥提交；env_keys 只有变量名，不能据此生成空值映射覆盖已有值。

### 任务接口

- `POST /api/tasks`：必填 prediction；可选 context=null、complexity=auto、notify=false、recipient=null、depth=0，返回202及 Task。
- `GET /api/tasks/{id}`：按 ID 查询，非任务列表。
- `POST /api/tasks/{id}/cancel`：取消；终态返回不可取消错误。

任务封装的关键路径：

```text
task.id / task.contextId
task.status.state / task.status.timestamp
task.metadata.error                         # 失败时可能存在
task.artifacts[0].parts[0].data               # 完成后读取前先检查存在性
  analysis: {schema_version, analysis_id, generated_at, status, mode,
             prediction, facts, inferences, recommendations, limitations, risks}
  children: [{id, role, status, depth, tools, data_fields, result?, error?}]
  conflicts: [{role, code, reason}]
  usage: {calls, reserved_usd, budget_usd}
  mail: null | {id, status, attempts?, next_attempt?, error?}
  report_path
```

children.result 包含 role、status、conclusions（代码数组）、evidence_ids、uncertainty（代码数组）及 delegate_roles。顶层 analysis 的 inferences 则是 code/text/evidence_ids 对象数组；两者不要用同一个展示类型强行解析。框架组件应对可选字段和空数组有明确分支。

### 时间、数值与错误

时间输入必须带 Z 或 UTC offset，接入后规范化 UTC；显示可用 Asia/Shanghai，并在时间旁标出时区。拒绝未来可用事实、过期结果和不匹配的对象。valid_until 是硬有效期；静态 examples 中的时间可能已经过期，不能直接用作长期演示。

数值须有限且不能为布尔值；confidence 为0..1或null。horizon.value 为1..365整数，unit 为 trading_days/calendar_days/hours；不要把交易日自行换成日历日。context.facts 每项至少有 id/name/value/unit/source/observed_at/available_at，id 在批内唯一，source 是上游声明而非系统独立核实。

HTTP 错误一般为400/403/404/500，格式如下；外部模型认证失败也可能由本机后端包装成 HTTP400，需看 error.code，而不是只判断 HTTP401。

```json
{"error":{"code":"AUTH_FAILED","message":"凭据无效或权限不足","retryable":false}}
```

应为这些错误提供可执行指引：AUTH_FAILED 检查凭据；PARAMETER_UNSUPPORTED/INVALID_CONFIG 检查模型参数；CONFIG_IN_USE 先解除引用；PERMISSION_DENIED 检查工具/邮件授权；STALE_RESULT/STALE_CONTEXT 获取新数据；BUDGET_EXHAUSTED 调整额度或减少调用；CALL_TIMEOUT/MCP_UNAVAILABLE 检查服务；FORBIDDEN 重新建立同源会话。retryable 不意味着前端可以自动重复发送邮件或重新提交任务。

## 7. 前端请求与部署约束

现有后端只监听127.0.0.1，校验 Host/Origin，无 CORS。先访问 `/` 建立 HttpOnly、SameSite=Strict Cookie，再请求 `/api/session` 获取 csrf_token。写操作带 X-CSRF-Token；浏览器用同源 Cookie，不能改成把服务端模型 Key 放到 Authorization。

可以参考以下同源 API 封装；它运行在已经通过 `/` 建立会话的浏览器页面中：

```javascript
let csrfToken = '';
async function request(path, method = 'GET', body) {
  const response = await fetch(`/api/${path}`, {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message || '请求失败');
    error.code = data.error?.code || 'HTTP_ERROR';
    throw error;
  }
  return data;
}
async function initializeSession() {
  csrfToken = (await request('session')).csrf_token;
}
```

任务提交后建议每约1秒查询，终态/组件卸载时停止；避免重叠请求，网络错误可以提示恢复查询，但不能自动重新 POST 任务。取消会尝试停止在途工作，已经发生的邮件效果无法撤回，取消后继续短暂查询确认状态。

现有静态路由只有 `/`、`/app.js`、`/style.css`，CSP 禁止内联脚本、eval 和外部 CDN。若更换前端框架，必须先落实构建产物与后端静态路由：优先产出这三个文件且不分包，或由后端明确增加受限资源路由。浏览器 history 路由刷新、带 hash 的 chunk、字体/图标/CDN、开发服务器跨端口访问都不会天然可用。不要为方便开发直接关闭 Host/Origin/CSRF/CSP 校验。

## 8. 安全与体验要求

- API Key、token、stdio env 不写入 URL、localStorage、埋点、console 或错误上报；保存后清空输入。HTTP 响应中的固定掩码是状态展示，不是可恢复密钥。
- SPM_MASTER_KEY 由运行服务的人在服务端注入，不提供浏览器编辑/查询入口；已有工作区重启必须使用原 key。未配置主密钥时服务不能启动，页面应提示联系运行者，不伪装成凭据已重置。
- 外部文本、预测对象名、工具描述和资源内容使用文本节点呈现，禁止直接 innerHTML。若新增 Markdown/富文本渲染，先实现可验证的过滤方案。
- 删除配置、清除凭据、取消任务和授予外部发送权限应有明确的对象与影响说明。保存授权与发送通知是两个独立操作，不在后台保存时顺带发邮件。
- 使用真实 label、键盘焦点和 aria-live；状态不仅靠颜色区分。窄屏表单不横向溢出，长 ID/URL/Schema 可换行或局部滚动。
- 首次空态给出“添加 Mock 模型”等具体下一步；加载、成功、空结果、不可用、权限不足和分析降级都要可区分。未保存配置与服务端配置分开维护。

## 9. 接手后的启动与 Mock 联调

需要 Python3.11+。从仓库根目录执行 `uv sync`。服务端运行者应从外部秘密管理方式注入 SPM_MASTER_KEY；仅首次创建一次性演示工作区时，可按 [控制台手册](control-console.md) 的命令生成会话内 key，不打印、不提交，且后续重启不要重新生成覆盖。

```powershell
uv run stock-mailer --config config/agent-example.toml console --port 8767
```

打开 `http://127.0.0.1:8767`，先确认现有控制台可用。MCP HTTP Mock 可在另一个终端启动：

```powershell
uv run python -m stock_predict_mailer.control.mock_services --transport streamable-http --port 8766
```

也可使用 stdio，command 填该项目 Python 完整路径，args 填 `["-m","stock_predict_mailer.control.mock_services"]`；不要同时把 stdio 进程当作一个已运行 HTTP 地址连接。

最短业务闭环：

1. 新建 provider=mock 的模型并设为默认，测试连接；创建 MCP 服务并发现工具/资源。
2. 授权 get_context=read、send_email=email，主 Agent 绑定 `<服务ID>:get_context`；邮件选 MCP、指定 send_email、收件人白名单 `preview@example.invalid`，明确允许 synthetic。保存完整 settings。
3. 用动态 Mock 输入提交 complex 任务，并选通知；查询至终态。期望3个子角色 completed、analysis 有独立的风险/限制、mail.status=simulated。总调用通常7次、费用预留0；这不代表真实邮箱收到邮件。

以下输入工厂可直接用于页面 Mock 按钮，时间动态生成，不会因文档日期过期。只有用户在本地明确授权后再覆盖 notify/recipient：

```javascript
function createMockTask() {
  const generated = new Date();
  generated.setUTCMinutes(0, 0, 0);
  const time = generated.toISOString();
  return {
    prediction: {
      schema_version: '1', prediction_id: `frontend-mock-${time}`, subject: 'DEMO.SZ',
      generated_at: time, valid_until: new Date(generated.getTime() + 86400000).toISOString(),
      horizon: { value: 5, unit: 'trading_days' }, direction: 'up', confidence: null,
      model_version: 'mock-v1', synthetic: true, metrics: {}
    },
    context: null, complexity: 'complex', notify: false, recipient: null, depth: 0
  };
}
```

前端离线 Mock 也应沿用相同对象/响应封装，并准备降级、失败、取消、空上下文、无置信度、方向冲突、预算不足和邮件 uncertain 等样例。不要把Mock transport 的成功截图当作真实服务质量证明。

## 10. 实施顺序与验收清单

推荐按可联调的增量交付，不一次性重写所有页面：

1. 建立应用布局、同源请求层、错误展示与配置类型；确认静态资源和 CSP 兼容。
2. 完成模型配置、凭据编辑语义、温度能力和连接测试。
3. 完成 MCP 配置、工具资源发现及白名单编辑。
4. 完成角色模型/温度、外部 Agent、预算及邮件授权；确认 PUT 不丢隐藏字段。
5. 完成动态 Mock 任务、轮询/取消、报告阅读和协作/邮件状态；通过完整业务闭环。
6. 补齐响应式、可访问性、故障场景与交接说明，再提交合并。

页面验收至少满足：

- [ ] 无真实上游、无真实模型 Key、无真实 SMTP 也可完成 Mock 闭环。
- [ ] 密钥保存不回显，留空保留和显式清除均正确；控制台/存储/请求日志不泄露凭据。
- [ ] 不支持温度、越界参数、无效凭据、服务不可用和引用中配置删除均有明确反馈。
- [ ] 未授权工具/资源/收件人被拒绝，界面不自动扩大授权或发送邮件。
- [ ] 任务完成与分析降级/邮件失败正确区分；失败无产物不崩溃；取消与停止轮询可用。
- [ ] 缺失事实/置信度、过期时间、子超时、预算耗尽和方向冲突不会显示成完整可信预测。
- [ ] 真实邮箱到达未验证时，只展示 simulated/submitted 等准确状态；uncertain 不自动重发。
- [ ] 桌面和约390px窄屏无关键控件溢出，键盘可操作；外部文本不能执行脚本。
- [ ] 控制台静态文件可随 wheel 分发，原 CLI run/legacy 行为不被页面改造破坏。

现有后端回归基线为160项测试，详见 [control-validation.md](control-validation.md)。前端交付应另带实际页面交互验证记录，而不只复用后端测试数量。文档变更本身不改变这条历史基线。

## 11. 代码入口和协作交付物

- `src/stock_predict_mailer/control/web/index.html`：已有四个页面与字段，适合作为功能清点依据。
- `src/stock_predict_mailer/control/web/app.js`：现有请求封装、表单映射、模型/MCP操作、任务轮询与 Mock。
- `src/stock_predict_mailer/control/web/style.css`：当前响应式样式，可替换视觉但保留交互语义。
- `src/stock_predict_mailer/control/server.py`：静态路由、会话/CSRF/CSP 与全部控制台 HTTP API。
- `src/stock_predict_mailer/control/schemas.py`、`store.py`：字段类型/默认/范围、凭据语义和引用检查。
- `src/stock_predict_mailer/control/orchestrator.py`、`a2a.py`、`mcp_layer.py`、`models.py`：任务状态、委派、权限、预算及外部连接。
- `src/stock_predict_mailer/agent_service/`：既有预测/事实校验、报告和邮件队列。
- `tests/test_control.py`：配置/API/协议/异常的可运行行为依据；`tests/test_agent_service.py` 是基础链路回归。

前端人员应交付：页面/组件源文件、字段与API映射、构建启动方式、部署资源约定、Mock场景、功能与故障验收记录，以及仍需后端配合的具体端点/字段需求。已有本地数据库、密钥、EML和私有数据不应随交接代码提交。

建议分支按功能创建PR；在PR中列出涉及页面、实际接口、状态变化和验证。涉及前后端契约时同时更新本文件与专题接口文档，避免只改截图或展示假状态。

## 12. 交接阅读顺序

先读本文，再阅读 [运行手册](control-console.md) 完成一次 Mock 操作；联调时查 [配置/MCP/A2A接口](control-api.md) 和 [预测/事实/分析契约](interfaces.md)。配置样例位于 [control-model.json](../examples/control-model.json)、[control-mcp.json](../examples/control-mcp.json)，已有实现状态见 [开发计划](control-plane-plan.md) 与 [验收记录](control-validation.md)。

仍需团队后续提供：真实预测和事实样例、拟接入MCP工具的具体参数结构、真实服务的模型能力/价格声明，以及用于真实到达验收的测试邮箱与授权。页面开发可以先用现有Mock独立推进，无需等待这些真实服务。
