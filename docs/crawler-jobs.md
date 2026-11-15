# 持久化采集任务与独立 Worker

提交只写本机 SQLite，不联网；Worker 需要显式启动。目录与基本面都支持任务模式，旧同步工具保留并共用工作区写锁。管理任务只需要基础安装，执行采集仍需要 crawler 依赖。

## 使用

```powershell
# 保留知识库/研究等全部可选功能；仅需采集时也可选择 --extra crawler。
uv sync --all-extras --locked
$env:STOCK_PREDICT_MAILER_CRAWLER_WORKSPACE = 'D:\python\Stock-Predict-Mailer\data\crawler'
$crawlerCommand = '.\.venv\Scripts\stock-predict-mailer-crawler.exe'

# 股票池需要事先生成并校验；本条只入队，不调用来源。
$submitted = & $crawlerCommand jobs submit --kind fundamental --parameters '{"max_stocks":1}' --request-key fundamental-first | ConvertFrom-Json
$jobId = $submitted.result.id
& $crawlerCommand jobs status $jobId

# 显式执行至多一条排队任务；空队列立即返回。
& $crawlerCommand worker --once
& $crawlerCommand jobs events $jobId --after 0
& $crawlerCommand jobs list --limit 20
```

连续 Worker 使用 `worker --poll 2`。MCP 和 Worker 分别启动，使用同一工作区；启动 MCP 不自动启动 Worker。模块入口也支持 `python -m mcp_server.server jobs ...` 和 `worker ...`。

Worker CLI 现在会在 `.runtime/crawler_worker` 登记实例和心跳，包括显式空 `worker --once`；空队列不会因此创建任务库或触发采集。只读运行状态、显式后台启动、协作停止及日志见[运行管理手册](runtime-lifecycle.md)。停止会在原检查点中断，不自动 resume。

目录参数为 force_refresh/max_cache_age_seconds/allow_stale；基本面参数为 max_stocks/end_date/allow_unverified_pool，具体语义沿用[采集手册](crawler-service.md)。end_date 在提交时固定，跨日恢复不改变截止日。强刷仍须遵守来源限流，失败不会自动重试。

同 request_key、同规范参数复用任务；不同参数报 JOB_KEY_CONFLICT。跨日默认日期变化也会冲突，需新 key 或显式原截止日。不传 key 则每次新建任务。任务参数不保存模型或 SMTP 凭据。

## 取消、状态与恢复

```powershell
& $crawlerCommand jobs cancel $jobId
& $crawlerCommand jobs resume $jobId
& $crawlerCommand worker --once
```

状态为 queued/running/cancelling/completed/partial/failed/cancelled/interrupted。completed 表示选定执行范围完成，不保证全历史完整，结果继续保留 scope_limited、completeness 和 run_complete。仅 partial/failed/cancelled/interrupted 可恢复；成功任务需重新提交，不能以 resume 重发。

运行中取消是持久请求，不根据 PID 杀进程。请求/季度/股票边界及等待期间检查取消，等待约每半秒检查；在途调用受原 SDK/网络超时影响，不能保证立即退出。已发出的请求和已落盘的数据不能撤销。Ctrl+C 停止 Worker，不继续领取下一条任务。

异常退出后查询可能仍显示 running。下一次 Worker 先获得 OS 写锁，再将遗留状态标为 interrupted（已有取消请求则 cancelled），不会自动重新执行它。显式 resume 才重新排队。注意 worker --once 在恢复遗留状态后还会执行一条已排队任务，它不是只读诊断命令。

旧写入者持锁时返回 WORKSPACE_BUSY，不凭 PID 或时间抢占。不要删除 `.crawler.lock`：OS 在进程退出时释放锁，文件留存正常。Worker 应作为独立进程运行，隔离采集库全局配置；不要嵌入正处理其他业务的 Web/MCP 进程。

## 检查点

基本面冻结股票池摘要、截止日、选定股票和增量范围；每只股票文件保存后写检查点。恢复只补失败/未处理股票。冻结内容没变时允许继续原股票选择，即使缓存年龄已增长，结果仍保留实际 stale 状态。

股票池变动返回 INPUT_CHANGED；输出被删除或其他任务改写返回 CHECKPOINT_CONFLICT；文件/sidecar 不匹配仍是 INVALID_DATA。应核对备份与事件，必要时新建任务，不能手改检查点跳过数据。

文件原子替换与 SQLite 不是同一事务；恰在文件、元数据、检查点之间崩溃时，恢复可能拒绝执行并需要人工核对。系统不静默跳过丢失数据，也不强制覆盖不一致文件。目录是动态分页，重试重新取完整快照，不复用半页结果；部分分页仍不覆盖有效股票池。

## MCP 与保存位置

新增 submit_crawler_job、get_crawler_job、list_crawler_jobs、cancel_crawler_job、resume_crawler_job、crawler_job_events 六个管理工具。提交示例：

```json
{"kind":"fundamental","parameters":{"max_stocks":1},"request_key":"fundamental-first"}
```

成功返回 `ok=true,result=...`；错误保留明确错误码。事件每页最多 100 条，按 seq 递增，将最后一条 seq 作为 after 继续。列表和状态读取不创建数据库、不加载采集依赖。工具仍需显式授权，注册不等于自动授予客户端权限。

工作区新增 `jobs/crawler-jobs.sqlite3` 和 `data/.crawler.lock`。事件包含对象、计数、状态和检查点摘要；完整检查点不在每条事件中重复保存。Worker 日志到 stderr，CLI stdout 为 JSON。每次尝试使用独立 ownership token，拒绝旧执行者写回新尝试。

本阶段完成第四阶段 A，邮件存储与发送语义没有迁移。[MailCore](mail-core-plan.md)在第四阶段 B 单独实施。测试使用合成采集器、临时文件和本机子进程，没有真实采集或邮箱投递。
