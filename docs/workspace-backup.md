# 工作区加密备份与隔离恢复

`backup plan/create/verify/restore` 用于本机工作区的数据保护。实际 create/restore 都是显式动作；工具不会停止服务、切换密钥、执行采集、启动模型或发送邮件。

## 备份范围与一致性

包含 TOML 指定的应用工作区、指定/默认采集工作区的普通文件，以及当前 CLI TOML 的参考副本。应用和采集工作区必须相互分离；采集目录默认规则与现有 crawler 相同。引用到工作区以外的模型、预测输入、证书或其他配置不自动跟随，需要另外备份。

排除 `.runtime`、业务锁、日志、SHM、待发布临时文件、backups、.git、.venv、.uv-cache、__pycache__ 等。符号链接、重解析点、特殊文件、网络共享/设备路径、路径冲突和孤立 WAL 明确拒绝。WAL 纳入来源摘要，最终包只存合并后可独立打开的 SQLite，不恢复进程身份、旧 PID 租约或停止请求。

本批为**停止写入后的完整快照**，不是在线跨库事务。先停止所有来源写入者，包括旧版本服务、外部脚本及研究训练进程。预演检查登记组件、业务锁及指定控制台端口；已有阻断时延期深度数据库/密钥检查，解决后应重新预演。create 再取得组件/启动/业务互斥，按清单复制并比较前后 SHA 和文件集合。

不打开源 SQLite；只在用户私有临时克隆中合并 WAL、运行 SQLite backup/quick_check 和 schema 校验。因此不会在源库创建 SHM 或执行 recovery/checkpoint。来源已存在的未提交回滚日志需先单独处理。副本自洽和摘要稳定检查不能替代停止不遵守锁的外部写入者，也不构成跨文件在线原子快照承诺。

plan 不写来源或最终输出。create 会创建必要的互斥锁和空控制目录，但不修改来源业务内容。临时目录包含原始资料与开发密钥，正常完成/错误时清理；强制中止可能留有临时目录，应在受保护存储上操作并核对残留。

## 独立备份密钥

最终 `.spmbak` 是整体 Fernet 认证加密包，内含 manifest、文件摘要和数据。默认从 `STOCK_PREDICT_MAILER_BACKUP_KEY` 读取独立密钥，也可使用 `--key-env` 指定引用。工具不生成、打印或保存该值，不自动复用 MASTER_KEY。

首次建立备份系列时可生成新密钥并注入当前 PowerShell；随后应保存到工作区外的可靠秘密存储，已有包必须保留并使用原值，不能每次运行都重建：

```powershell
$env:STOCK_PREDICT_MAILER_BACKUP_KEY = (& .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").Trim()
```

加密包包含开发库时，会携带原 `control-development.key` 并验证 vault_check；正式库需要当前外部 MASTER_KEY 验证，环境中的 MASTER_KEY **不写入包**。两个库都存在时两套配套要求都检查。缺标记、缺密钥或错误密钥会阻止创建/恢复，不猜测或生成替代密钥。备份密钥和正式主密钥均需分别保管，归档本身不能替代它们。

## 先预演，再创建

```powershell
# 先通过原方式或 runtime stop 显式停止相关写入者。
# 8767 若为未登记旧服务，工具不会接管或杀进程。
$snapshotPlan = & .\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml backup plan --crawler-workspace 'D:\data\crawler' --port 8767 | ConvertFrom-Json
$snapshotPlan

# ready=true 后审阅来源、files、counts、vaults 和 plan_id。
New-Item -ItemType Directory -Path '.\backups' -Force | Out-Null
& .\.venv\Scripts\stock-predict-mailer.exe --config config/agent-example.toml backup create --crawler-workspace 'D:\data\crawler' --port 8767 --output '.\backups\manual-20261115.spmbak' --expected-plan $snapshotPlan.plan_id
```

plan 的 files/bytes 是**原始来源清单**，可能包括 WAL；create 输出 files 是最终合并镜像的文件数，因此可能更少。plan_id 绑定来源路径、端口、配置及文件内容；修改任何来源后必须重新审阅。输出必须位于来源之外的已有目录，不能覆盖已有包。文件系统不支持安全的不可覆盖发布时会明确失败，不降级为覆盖写入。

成功返回 archive、archive_sha256、plan_id、文件数量和 vault 配套要求。包在完整写入、同步并加密后才发布，失败不留下可被当作完整包的输出。预演输出含本机文件路径和摘要，应按本地元数据保管；不会输出正文、解密配置或密钥值。

## 校验与隔离恢复

verify/restore 不要求原 TOML 仍存在，也不构造 Store/Worker；只需要安装的命令、归档、备份密钥，以及归档要求的正式主密钥。

```powershell
& .\.venv\Scripts\stock-predict-mailer.exe backup verify --archive '.\backups\manual-20261115.spmbak'

# 父目录必须已存在，target 本身必须从未存在；不能复用空目录。
& .\.venv\Scripts\stock-predict-mailer.exe backup restore --archive '.\backups\manual-20261115.spmbak' --target '.\data\restore-check-20261115'
```

先认证解密，再检查清单、版本/平台、大小上限、ZIP 普通文件类型、重复/越界/Windows 特殊路径、文件 SHA、数据库结构及密钥配套。恢复在目标旁的私有暂存目录完成，以不可覆盖的目录发布；目标即使在发布前被其他操作创建，也不会被替换。已有源目录、目标及原始加密包保持不变。

成功后包含：

- `app/`、`crawler/`：恢复的数据副本。
- `reference/original-agent.toml`：原配置参考，可能仍含原绝对路径，**不要直接当作恢复配置运行**。
- `restored-agent.toml`：指向新 app 的安全配置，使用明确的 Mock/file，不连接原 SMTP 或预测服务。
- `restore-receipt.json`：归档 SHA、版本、vault 要求、隔离数量、原文件/恢复后文件摘要；数据库因隔离处理变化会保留两份摘要。

可以只读检查新副本：

```powershell
& .\.venv\Scripts\stock-predict-mailer.exe --config '.\data\restore-check-20261115\restored-agent.toml' doctor --crawler-workspace '.\data\restore-check-20261115\crawler' --skip-port-check
```

根据 receipt/verify 的 vaults 选择开发或正式模式；当前进程 MASTER_KEY 会影响以后启动控制台时选择哪个库。恢复不会自动设置环境变量，也不会把原配置的外部路径改指向新数据。需要真实输入/SMTP 时，应另建经过核对的配置。

## 恢复后的任务默认暂停

- 新/旧邮件 pending/retry/sending 变为 uncertain，保留原 EML、ID、attempts 与绑定；已有 completed/submitted/simulated 历史不重发。新 Core 另记 restored_quarantine 审计。
- 采集 queued/running/cancelling 变为 interrupted（有取消请求则 cancelled），保留参数、检查点与尝试次数，清除旧 owner。
- 研究 training_jobs 的 queued/preparing/training/cancelling 同样暂停，清除旧 PID/心跳；成功模型记录保留。
- 知识 pending/processing 变为 failed，并标记 RESTORED_REVIEW_REQUIRED，原解析与索引资料保留。
- 如存在知识库 workers 进度表，其行改为 stopped 并清空 current，保留计数；恢复的旧心跳不作为仍在线证据。
- 未完成分析变为 failed；旧 MCP 未决回执变为 uncertain；旧运行记录不作为仍在运行的证据。

只有人工核对后才按原接口 retry/resume/重新提交或确认邮件结果。恢复旧备份时，原工作区可能已经完成了备份时尚未完成的动作；因此不能仅凭旧 pending 状态重新发送。启动恢复副本也不会自动领取这些已隔离任务。本工具本身不启动任何服务。

## 上限和错误处理

本批最多 10000 文件、单文件 64 MiB、总数据 128 MiB；规范化和恢复后文件也受限。控制台任务额外限制为 10000 行、单行 JSON 1 MiB、合计 16 MiB。超限明确停止，不把截断结果当作完整备份。采用完整内存加密，不支持流式、增量或自动跨版本/跨平台迁移。

plan ready=true 和成功操作退出 0；阻断/错误退出 2。常见 code：BACKUP_BLOCKED、BACKUP_PLAN_CHANGED、BACKUP_SOURCE_CHANGED、BACKUP_KEY、BACKUP_VAULT_KEY、BACKUP_AUTH、BACKUP_FORMAT、BACKUP_INTEGRITY、BACKUP_VERSION、BACKUP_LIMIT、BACKUP_EXISTS、BACKUP_TARGET、BACKUP_PUBLISH。底层存储故障沿用 LOCAL_IO；不包含原异常文本或密钥值。

BACKUP_AUTH 表示备份密钥不匹配或包受损；BACKUP_VAULT_KEY 表示内部数据库缺少正确的配套密钥。两者不同，不应删除旧 key 或重新生成替代值。发布/恢复失败后应保留原包、检查错误并重新预演，不手工搬移暂存文件冒充完整恢复。

实现范围与验收结果见[备份阶段计划](workspace-backup-plan.md)。本批只在临时合成资料上实际演练，真实工作区仅预演，没有实际生成备份、恢复或修改服务。
