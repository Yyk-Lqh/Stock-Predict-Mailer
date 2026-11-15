# 第五阶段 A：只读运行诊断（2026-11-15）

本文保留 5A 的范围与当时验证。后续 5B 已实现组件身份/心跳和受控启停，见[阶段计划](runtime-lifecycle-plan.md)；doctor 仍保持只读。

沿用已授权优化路线和上一轮的下一步：先交付本机 doctor 命令，再做受控启停/日志，最后做备份恢复。本轮保持现有工作区和运行中的服务，不自动重启、采集、调用模型、发送或恢复任务。

## 设计选择与步骤

1. 独立 `doctor` 命令输出版本化 JSON，包括整体状态、逐项 code/status/message/details/action。相比把检查混入启动器，独立入口可在启动失败时使用；相比完整进程管理器，本批只读取证，避免提前引入进程归属、自动恢复和数据迁移。
2. 工作区来自现有 TOML；采集工作区遵循现有环境变量/当前目录规则，支持显式 `--crawler-workspace` 覆盖。检查缺失/非目录、基础与可选依赖、SMTP 凭据引用是否存在，输出不包含秘密值、邮箱、文档名、任务内容或原始异常。
3. 对已存在的六个已知数据库使用 SQLite `mode=ro`、query_only、短 busy timeout、查询时间预算和只读事务，检查 quick_check、必要列及队列状态。WAL 只读连接仍可能创建/修改协调文件，不能使用忽略 WAL 的 immutable 方式冒充最新快照；本批对 WAL header/sidecar 给出 DB_WAL_CHECK_DEFERRED，不打开，等待后续备份快照工具核对。缺失的可选库记录为尚未初始化，不创建任何目录、DB、表、密钥或业务锁。旧表/旧 schema 只说明，不升级。
4. 只读检查已有 OS 锁文件：不创建、删除或写入，短暂尝试共享锁后立即释放；区分 absent/available/busy/unknown。文件存在不代表进程存活，采集 idle Worker 没有心跳，因此只能报告运行证据/未知，不能宣称 Worker 已停止或安全抢占。遗留 running/processing/sending 只提示，绝不 claim/recover/resolve。
5. 默认只在 127.0.0.1 短暂 bind 检查控制台端口是否可供新实例启动，不监听、不发 HTTP、不探测外部地址。占用/保留不等于已确认是本项目，也不等于已有服务异常。提供 `--skip-port-check` 用于完全离线检查。
6. 按现有环境变量选择开发/正式 vault 模式。只检查密钥格式，并在已有 vault_check 上验证匹配；不构造 Store、不生成开发密钥、不读取 profiles.secrets。未选择的正式库存在时提示模式区别。缺 marker 时明确无法验证，不能声称凭据可恢复。
7. 对任务 JSON 设置行数/单行/总字节上限，超限报告不完整，不把截断计数当作完整健康结果。每个数据库独立快照；不宣称跨库一致或端点的实际业务健康。
8. 新增合成回归：空目录不创建、schema/corruption/lock/WAL、只读性、未知 Worker、密钥缺失/错误、不泄漏、端口冲突、CLI 状态码和无可选依赖的 wheel 安装。运行全量回归及真实工作区只读检查，更新操作手册。

## 验收

- CLI：`stock-predict-mailer --config ... doctor [--port 8767] [--skip-port-check] [--crawler-workspace ...]`；ok=0、warning=1、error=2。warning 不是“已损坏”，可能表示需要人工确认的运行状态。
- 无数据库也能执行，不初始化服务；有异常库时继续检查其他组件。所有建议仅展示，不执行。
- 严格区分端口可启动性、数据库可读性、锁状态和真实运行健康；未验证的项清楚说明。
- 不改变现有 CLI run/console/Worker 行为，不新增依赖或前端界面，不在真实数据上演练修复。

## 后续

5B：明确组件归属与 Worker 心跳，再实现启停、端口归属和有界日志轮转。5C：显式备份清单、数据库一致性快照、密钥配套检查及隔离目录恢复演练；不直接覆盖原工作区。

## 实施与验证结果

- 已提供独立 operations/probes 与 diagnostics、CLI doctor 和基础 CI 专项，无新增依赖或前端修改。使用见[诊断手册](runtime-diagnostics.md)。保留已有优化的未提交改动，本轮不提交或推送。
- 新增 33 项运行，32 通过、1 项因当前 Windows 账户不能创建符号链接而跳过；路径越界与解析失败另有不依赖符号链接权限的覆盖。包括空目录/旧库不初始化、WAL 不产生文件、锁竞争、查询预算、schema/corruption、恶意/过大 JSON、截断标记、密钥错配、不读 profiles 凭据、隐私输出、端口及 CLI 退出码。
- 全量执行 445 项，444 通过、1 项同上跳过，耗时 194.549 秒。随后补充每个数据库计数的 counts_complete 标记，并以最终 33 项专项复验（32 通过、1 跳过）。
- 最终 wheel 成功构建，包含 3 个 operations 文件，无缓存/临时数据打包。独立 Python 3.12 基础环境不含 pandas/requests/baostock/numpy/sklearn，同样 33 项运行，32 通过、1 跳过。在源码目录以外运行已安装 CLI，doctor 返回 ok/0，临时空工作区仍为空。
- Ruff、compileall、命名、仓库卫生、diff 空白检查通过。真实工作区仅执行诊断，对 6 个已有数据库/配套密钥/锁文件检查前后计算 SHA，内容和文件集合一致；本机报告保存为 `.tmp/runtime-diagnostics-local.json`。
- 当前本机诊断为 warning：当前终端没有 TOML 引用的 SMTP 凭据，存在但未选中的正式配置库，8767 不能供新实例启动。这些是诊断时当前进程环境及端口的观察结果，不等于现有控制台异常；没有自动改变密钥模式、结束进程、启动 Worker、恢复任务或发信。
- 实验确认 SQLite mode=ro 打开已 checkpoint、无 sidecar 的 WAL 库仍会创建 -wal/-shm；因此实现明确延期 WAL 检查，没有采用忽略 WAL 的 immutable 读取。真实业务验收、WAL 快照核对与 Worker 身份仍按后续范围推进。
