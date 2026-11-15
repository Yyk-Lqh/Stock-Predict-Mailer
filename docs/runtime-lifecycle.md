# 组件运行、实例心跳与受控启停

管理三个固定组件：`console`、`knowledge_worker`、`crawler_worker`。每次运行都有独立实例 ID、PID 创建标识和心跳；运行目录为各自工作区的 `.runtime/<component>/`。状态查询不会初始化业务库。现有前台入口仍可用，升级后重新启动的入口也会登记。

## 只读状态与日志

```powershell
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml runtime status console
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml runtime logs console --limit 30
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml doctor
```

`verified` 表示登记的主机、工作区、实例、OS 进程创建标识、终身锁与新鲜心跳一致；同时看 `phase`，starting 不等于已经可以处理请求。Windows 核对进程创建时间，Linux 核对 boot ID 与 /proc starttime；不支持的系统或权限不足时返回 unknown。**仅 PID 相同不算身份匹配**。

心跳默认每秒刷新，超过 5 秒标为 stale；它证明登记仍有更新，不证明某个任务或外部服务有进展。其他状态包括 not_registered、stopped、failed、dead、pid_reused、different_host、clock_skew、unknown、invalid_record。异常记录不自动覆盖，不从旧记录接管进程。

doctor 同时显示实例证据和原业务锁。已登记的空闲采集 Worker 可以被确认，未登记库函数调用和升级前的旧进程仍显示未知。登记控制台报告使用检查端口时，会显示 PORT_REGISTERED_COMPONENT；这不是 HTTP 健康检查。

logs 只读取经过验证的结构化生命周期事件，不显示供应商正文、环境变量值、原始异常或子进程输出。每组件当前日志 256 KiB，加 3 份轮转，总量约 1 MiB；最多返回 200 条。已有日志超出预期大小时明确拒绝，不擅自搬移未知大文件。这些日志不替代完整业务调试日志。

## 显式后台启动

```powershell
# 只启动控制台；不会顺带启动 Worker。
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml runtime start console --port 8767

# 以下命令可能立即处理已有队列、联网或调用已授权服务，按实际需要单独执行。
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml runtime start knowledge_worker --poll 2
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml runtime start crawler_worker --poll 2 --crawler-workspace 'D:\data\crawler'
```

console/knowledge_worker 使用 TOML 的工作区；crawler_worker 使用显式 crawler-workspace，否则依次沿用采集环境变量或当前目录下 data/crawler。查询、启动和停止时必须选择同一工作区。

start 使用当前 Python 解释器、调用方的工作目录及进程环境，在 Windows 隐藏窗口运行。所有路径使用绝对值传给固定 launcher；不接受任意 shell 命令。启动 ID 必须与实际组件内部登记匹配，不把 Windows venv 引导进程的 PID 当作实际 Worker。

相同工作区、组件及公开参数已经运行时返回原实例和 already_running=true；参数不同、实例正在停止或归属不明时拒绝。端口不可用时不抢占旧进程、不自动换端口。已有未登记的 8767 监听者不会被接管；应通过原启动方式自行处理它，不能因为端口占用就调用本工具停止未知进程。

启动最多等待 15 秒确认。失败只返回固定错误与生命周期记录；后台 stdout/stderr 丢弃，不采集进日志。需要细查配置时，使用原前台命令查看结构化错误。启动超时只尝试向自己这次已验证的实例发协作停止请求，仍应查询状态；没有强制杀进程行为。

**重复 start 不会更新运行进程的环境变量或工作目录。** 更换 SMTP 凭据、MASTER_KEY 或目录设置时，先明确停止旧实例，再从正确环境启动。后台进程启动时继承环境，运行登记只保存 vault 模式等公开字段，不持久化密钥值或命令行。现有业务配置/邮件端点冻结规则仍有效。

## 匹配实例后停止

先从 status 或 start 的输出取得 instance，再提交停止请求：

```powershell
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml runtime stop console --instance '<instance_id>' --wait 10
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml runtime stop knowledge_worker --instance '<instance_id>' --wait 10
.\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml runtime stop crawler_worker --instance '<instance_id>' --wait 10 --crawler-workspace 'D:\data\crawler'
```

stop 只写属于该 instance 的 stop.json。旧请求不能停止新实例，工作区不匹配、PID 被复用、主机不同或身份未知时拒绝；从不使用 kill/taskkill 或按 PID 发送信号。

- 知识 Worker 在当前 process_one 结束后停止，不再领取下一个任务；任务边界也同步读取停止请求，不只依赖心跳轮询。
- 采集通过现有 JobControl 检查点中断，任务保留 interrupted，继续运行需要原 resume 命令，不自动恢复。不可取消的来源请求可能要等到下次检查点。
- 控制台停止接收新的分析任务，关闭监听并取消/等待已活动任务收尾。生命周期租约和 stopping 心跳持续保留，直到任务清空，避免宣称已经停止但邮件动作还在退出。

`--wait` 范围 0–30 秒；0 只确认请求已写入，返回 stop_requested。正数超时返回 stopping/timed_out=true，表示**尚未确认停止完成**；不是进程已退出，也不会自动升级为强制终止。状态变化后再次查询；不要删除租约锁文件或重放业务任务。

正常结束保留 stopped 登记；异常结束可保留 failed 或 dead。OS 会释放终身锁。确认死进程后，显式新 start 可创建新实例；stale/unknown 不是安全抢占依据。

## 前台与兼容行为

原 `console`、`knowledge-worker` 和采集 `worker` CLI 会登记身份与生命周期事件。显式空采集 `worker --once` 现在会留下 `.runtime/crawler_worker`，但不创建采集任务库、不采集。`jobs list/status`、runtime status/logs 和 doctor 仍保持只读；直接调用 run_once 的程序没有登记心跳，保留原业务锁行为。

本机可写工作区的账户是信任边界，登记不是跨用户认证。当前没有开机自启、自动重启、任意进程托管或强制停止；备份/恢复属于后续独立迭代。测试和实现记录见[阶段计划](runtime-lifecycle-plan.md)。
