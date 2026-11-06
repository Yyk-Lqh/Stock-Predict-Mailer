# 会话记忆设计

会话状态与长期记忆以所有者为边界。由控制台创建独立访问密钥，服务端仅保存摘要。会话保留精确任务输入、近期消息、已校验的数据检查点和工作摘要。新对话用新的会话 ID，沿用同一所有者的检索范围。

长期记忆正文、向量和待写入记录保存在本机 SQLite，正文使用工作区密钥加密。索引采用本地特征向量并结合类型、主题、标的和有效期检索。模型只收到有限的背景片段。历史预测与事实保持来源及时间。

每次主模型调用前估算载荷。达到配置阈值时，先提交待保存记忆，再压缩早期内容。事务失败保留可重试记录和源消息。原文退出模型工作上下文，仍可按会话恢复。按会话串行执行任务，防止并发追问覆盖检查点。

## 控制台

在「会话记忆」创建访问密钥。将密钥保存在自己的安全位置，重新打开控制台时可以输入原密钥恢复。密钥在当前浏览器标签页使用 sessionStorage 保存。控制台的本机信任边界仍适用。用户归属由服务端从密钥解析，独立于浏览器提交的任何身份字段。

在「分析任务」新建会话，提交首次预测、问题与约束。追问时选择原会话并点击「沿用上轮输入」。输入框中的空对象会复用上轮预测、周期和执行条件，允许本轮明确覆盖。沿用的预测仍受有效期约束，过期后提交同标的新预测可保留会话约束。MCP 数据检查点按预测和已授权工具列表匹配，复用时重新验证事实时效。发送邮件须在本轮明确选择。

在任务表单可明确记住报告格式或其他事项。单句「请记住我偏好简版报告」也可结构化为偏好。简版会先呈现摘要，再提供完整依据和风险。本轮格式覆盖已召回偏好。记忆列表支持修改正文与格式、删除和关闭跨会话写入及召回。关闭期间会话仍可续接和压缩，已有待写记录暂停。更正或删除会一并处理同一条目的较早待写版本。

## 请求与存储

以下接口沿用本机 Cookie 和写操作的 CSRF 检查。

- `POST /api/memory/access` 创建所有者并一次性返回 `key`。后续记忆、会话和关联任务请求使用 `X-Memory-Key`。
- `GET/POST /api/conversations` 列出或新建会话。`GET /api/conversations/{id}` 查看近期原始消息、摘要与检查点。
- `POST /api/tasks` 支持 `conversation_id`、`message`、`constraints`、`report_format`、`fresh_context` 和 `remember`。有会话历史时可省略 `prediction`。传 `fresh_context: true` 可重新查询数据。清空约束时传 `constraints: []`。
- `GET /api/memory` 查看已保存条目。`PUT/DELETE /api/memory/{id}` 更正或删除。`GET /api/memory/pending` 查看待写条目和原消息引用。
- `GET/PUT /api/memory/settings` 管理 `enabled`、`context_bytes` 和 `recent_turns`。默认压缩阈值 10000 估算字节，保留最近 2 轮。模型载荷仍受原有硬上限约束。

`remember` 中每条包含 `content`、`kind` 和 `tags`，可加 `importance`（1 到 5）、`subject`、`applies_at`、`expires_at`、`data_version`、`confirmed`、`report_format`。kind 支持 user_statement、preference、watchlist、constraint、prediction、inference。历史预测和推断要求标的、原始时间及数据版本。预测条目提取当前经校验的预测内容。服务端补充所有者、记录时间及来源会话和消息。相同主题的偏好、约束和关注标的按条目更新。
