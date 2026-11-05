# 模型、工具与 Agent 控制台使用手册

## 启动与凭据保存

先 `uv sync` 安装锁定的 MCP SDK、加密与 Schema 校验依赖。第一次配置时，用秘密管理工具为服务进程设置 SPM_MASTER_KEY（Fernet 32字节 URL-safe Base64 key），并将同一主密钥持久保管于工作区之外。可在当前 PowerShell 会话生成，不将其打印到终端：

```powershell
$env:SPM_MASTER_KEY = (uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").Trim()
uv run stock-mailer --config config/agent-example.toml console --port 8767
```

然后打开 `http://127.0.0.1:8767`。上面的赋值只在当前进程环境有效，不能作为持久保管方案；**已有配置时不要每次生成新 key**。重启需由同一外部秘密存储注入原 key；遗失后无法解密已有 API Key。缺少/错误主密钥会明确报错，不会回退明文存储。不修改现有 SMTP 环境变量或签名私钥。

控制台使用 `config/agent-example.toml` 的 workspace，配置数据库为 `<workspace>/control.sqlite3`，独立于原研究与邮件数据库。API Key/MCP token/stdio env 由服务端 Fernet 认证加密保存，GET 仅返回固定掩码和是否设置，界面保存后立即清空密钥输入。工作区已被 Git 忽略；主密钥不得写入代码、配置示例、日志或版本库。控制台 HTTP 仅本机，不对公网开放，可信本机账户可以访问控制台；多人部署需另建认证和 HTTPS。

## 配置模型

在“模型服务”添加 Mock 模型，即可离线测试；配置真实服务时选择 OpenAI 兼容 API，填写基础地址、模型名称、API Key、超时/重试和服务实际支持的生成参数。地址包含 /v1 时保留，不追加 /chat/completions。未支持的参数不要写进支持清单；支持清单是用户按提供方文档声明，不是系统对厂商能力的保证。可保存多个配置、测试、启停、编辑、清除密钥和删除未被引用的配置。

真实模型须填服务商提供的输入/输出美元单价，连接测试会产生一次真实推理请求及可能费用；Mock 不计模型费用。未知价格会禁止执行，不能假装费用为零。密钥留空编辑表示保留；删除密钥用明确的“清除密钥”。

设为默认后，主 Agent 与各子 Agent 默认继承该模型；在“协作与授权”可分别选择角色模型。不同厂商可通过新增 provider adapter 扩展，不修改 MCP/A2A 协议代码。

温度默认 0.2，角色可独立覆盖；探索任务可调高但不提高股票预测准确率。界面根据所选模型声明显示范围或禁用控件；不支持温度时后端不会发送 temperature。切换不支持温度的模型时，保存角色配置会清除旧覆盖。恢复默认按钮重置全局和角色，模型参数中的显式 temperature 需在模型编辑页清除。详见 API 文档中的优先级。

## 添加 MCP 服务

HTTP Mock 服务可在另一个终端启动：

```powershell
uv run python -m stock_predict_mailer.control.mock_services --transport streamable-http --port 8766
```

控制台添加 Streamable HTTP 地址 `http://127.0.0.1:8766/mcp`，或使用 [MCP 示例](../examples/control-mcp.json) 经 API 添加。stdio 不需预先启动服务：启动程序填实际 Python 解释器完整路径，参数为 `["-m","stock_predict_mailer.control.mock_services"]`；认证使用单独加密的 env 字段，不把凭据写进启动参数。

保存后点“测试与发现”，会通过真正 MCP 协议发现 get_context、send_email 和 stock://demo/contract。允许工具填写 `get_context,send_email`，权限类型设 `{"get_context":"read","send_email":"email"}`；资源 URI 逐行填写。工具发现不自动授权，工具的说明也不能赋予权限。服务可启停、编辑、清除凭据及解除引用后删除。

角色工具引用 `<服务ID>:get_context`，服务 ID 可由配置 API GET /api/mcp 获得（界面工具输入也会给出示例）。主 Agent 调用 read 工具时传 subject 并要求 v1 上下文，服务返回的文本只能成为已校验数据，不能变成系统指令。其他工具参数/结果不同需薄适配，不将普通 API 冒充 MCP。现有普通预测 API 仍由原 adapters.py 接入。

## 完整 Mock 验收操作

1. 添加 Mock 模型并设为默认，连接测试通过。
2. 添加上面的 MCP 服务，测试发现工具，配置工具白名单及权限。
3. “协作与授权”主 Agent 读取工具填 `<服务ID>:get_context`；子 Agent 保持继承默认模型，不授予工具。
4. 邮件选择 MCP，指定同一服务和 send_email，允许收件地址填 `preview@example.invalid`，勾选允许合成报告。保存授权。也可改用 file，生成本地 .eml；真实 SMTP 使用服务端 SMTP_USER/SMTP_PASSWORD 环境变量。
5. “分析任务”载入 Mock 输入，选择复杂任务，勾选通知并填授权收件人后提交。
6. 查看三个子 Agent、最终分析、风险、限制、预算和邮件 simulated 状态。Mock 邮件工具不发送真实邮件；file 模式在 `<workspace>/sent/` 生成 EML。

默认顺序执行3个子 Agent，主模型规划与汇总各1次，读取数据工具1次、邮件工具1次，总共7次调用，模型费用0。simple 不委派；complex 允许主 Agent 决定是否委派，不强制所有厂商模型都返回3个角色。相同有效输入与相同分析内容重复通知由持久化发送身份去重。

## A2A、预算与异常

外部子 Agent 在“A2A 外部 Agent”配置 JSON-RPC 地址、独立 token 和单次费用上限，随后在相应角色选择。主 Agent 编排仍在本机；对外提供 A2A 0.3 非流式子集（message/send、tasks/get、tasks/cancel、Agent Card）。外部客户端访问本控制台的 A2A 通道需另行注入 SPM_A2A_TOKEN；不使用模型 API Key。A2A 传递结构化消息，不负责创建系统进程，创建/取消/回收在 orchestrator.py。

设置最多子 Agent、深度、调用次数、子任务/总超时及费用预算；当前子角色为叶子，不递归委派，有效深度最多1，即使配置的上限更高也不会突破。预算覆盖模型重试、MCP读取/邮件及对端轮询；远端调用按声明费用上限预留，实际计费还需服务商账户限制。取消会取消在途异步模型/MCP调用；已经提交给 SMTP/邮件服务器的操作不能撤回，沿用 uncertain 处理而不自动重复发送。

无效模型 Key 显示 AUTH_FAILED；服务不可用显示 SERVICE_UNAVAILABLE/MCP_UNAVAILABLE；不支持参数显示 PARAMETER_UNSUPPORTED；子 Agent 超时和预算耗尽会生成带降级说明的分析。任务总超时/取消中断整个流程；授权不符直接拒绝通知；Agent 返回冲突、未知证据或注入文本不会直接进入结论。对端未完成任务时 A2A 客户端受限轮询 tasks/get，失败/超时尝试一次受限取消。进程重启不会自动重新运行中断任务。

当前模型输出为有约束 JSON 代码和证据，而非可任意编造市场事实的自由段落。业务文本由系统渲染为报告；真实 LLM 服务应满足该输出协议。本次使用兼容 OpenAI 的 Mock HTTP 服务验证请求结构，不代表验证了任何真实模型质量或供应商计费。

## 测试与开发入口

```powershell
uv sync --extra research --extra trees --extra dev
uv run python -m unittest discover -s tests -v
uv run ruff check src tests scripts
```

新模块在 `src/stock_predict_mailer/control/`：schemas/store 管理配置，models 管理模型和预算，mcp_layer 管理外部工具，a2a 负责通信，orchestrator 负责生命周期与校验，server/web 提供界面及 API，mock_services 提供真正协议的本地 Mock。原 CLI run、legacy、邮件队列和接口保持可用。

详见 [接口文档](control-api.md)、[设计与开发计划](control-plane-plan.md) 和 [验收记录](control-validation.md)。
