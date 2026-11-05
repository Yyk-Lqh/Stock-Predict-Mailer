# 配置控制台与协议扩展验收（2026-11-05）

## 已交付

- 原生 HTML/JS 本机界面：模型服务 CRUD/连接测试/默认模型、MCP CRUD/启停/工具资源发现、角色模型与温度覆盖、运行预算、邮件预授权、分析任务状态及结果展示。
- 后端配置 API、Fernet 加密凭据存储及启动密钥校验；GET 永不返回凭据。Host/Origin、HttpOnly/SameSite Cookie、CSRF、请求大小限制及脱敏异常。
- OpenAI Chat Completions 兼容适配器和 Mock；明确生成参数支持范围、温度继承、超时重试、真实模型费用预留。
- MCP 官方 SDK 1.30.0 的 stdio/Streamable HTTP 接入、工具/资源发现、JSON Schema 校验及精确权限。普通 API 仍走普通适配器。
- A2A 0.3 非流式 JSON-RPC/Agent Card，message/send、tasks/get、tasks/cancel，外部对端认证、异步轮询与受限清理；独立编排层创建本机角色任务、管理超时/取消/回收与持久化状态。
- 主 Agent 对子结果做证据、不确定性和方向冲突检查。子角色只读所需预测/事实，无凭据、无工具、无递归委派；邮件仅在服务/工具/收件人/synthetic 授权范围执行。

## 实际验证

新增 35 项测试覆盖配置/加密/更新保留与清除/错误主密钥、温度范围/继承/不支持、默认引用、费用与调用上限、真实 MCP stdio/Streamable HTTP 会话、工具/资源权限、MCP 认证失败/不可用/超时、输入 Schema、兼容 OpenAI HTTP 请求/401/400/503重试/超时/预算不足、简单与复杂任务、子 Agent 数量/深度/超时、冲突/注入、邮件授权/去重、A2A 通信/轮询/取消、控制台会话/CSRF/同源防护。

旧加新完整回归曾通过 157 项；补充最终异常检查后，35 项新增测试再次全部通过。最终完整回归结果见本文件末尾的执行记录。测试只使用 Mock 与本机协议服务，不调用真实模型、不发送外部邮件。

gstack 浏览器实际完成：通过表单配置 Mock 模型和假密钥 → 推理连接测试 → stdio MCP 服务配置 → 工具与资源发现 → 角色工具/收件人授权 → Mock 复杂任务 → 三子 Agent 完成 → 邮件 simulated。输出总调用7次、费用预留0、密钥未回显；无浏览器控制台错误。已查看1280宽桌面及390宽移动截图，布局可用。截图仅在本机 `.tmp/control-desktop.png`、`.tmp/control-mobile.png`。

Ruff、Python 编译、JS 语法、Git diff 空白和依赖锁检查通过；CI 已加入不带 research 的控制台测试及 JS 语法检查，未声称远程 CI 已运行。

## 实际限制与后续计划

- 此为本机可信用户控制台，不是公网多用户平台；远程部署需 HTTPS/用户身份/权限隔离。主密钥须由用户外部秘密管理工具持续保管与注入，未实现密钥轮换 UI。
- A2A 为0.3明确子集，不提供streaming/push、不宣称A2A1.0兼容。子 Agent 为3种叶子角色，当前实际深度最多1，顺序执行；配置更高深度上限不自动开放递归。
- 工具发现支持通用 MCP；进入预测流程的数据工具必须适配 v1 上下文，邮件工具须适配 recipient/subject/text/html/idempotency_key。其他返回结构需团队实现薄适配器。资源只作为不可信数据展示，不自动加入 system 指令。
- 费用预留取决于用户填写价格及远端承诺，并不是厂商账单的严格控制；需配合服务商账户限额。外部服务运行/产生效果后不能保证撤回。
- 真实供应商、真实MCP服务、实际邮件到达和模型输出质量仍需授权联调。现有预测模型的准确性不由温度、Agent数或协议支持决定。

接口/配置示例见 control-api.md、control-console.md 和 examples/control-*.json；原预测、上下文和邮件契约保持兼容。

## 最终执行记录

Windows / Python 3.11：完整 `unittest discover -s tests -q` 共160项通过，耗时88.190秒；最后 MCP 认证 retryable 标志与 A2A 服务端费用预留修正后再次复验35项新增测试。完整回归仍出现旧邮件测试的单条已关闭 socket ResourceWarning，不影响结果；async unittest 的慢任务调试输出不属于失败。没有使用真实模型 Key 或真实 SMTP。

离线 wheel 构建通过，已检查包含控制台 HTML/JS/CSS，未夹带本地数据、数据库或构建缓存。临时 QA 控制台只使用临时主密钥和 Mock 凭据，验收后关闭；实际使用请按控制台手册注入长期保管的主密钥后启动。
