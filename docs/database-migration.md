# 单库事务迁移

`db migrate` 显式升级一个既有已知数据库，并在同一 SQLite 事务中登记结构版本。本入口会写来源库；`db status/plan/preflight` 和副本演练仍保持只读。

## 操作顺序

先停止所有写入者，包括旧版本进程、训练脚本和外部导入工具。按[备份手册](workspace-backup.md)显式创建并验证当前完整工作区的加密备份，再生成结构计划和[就绪检查](migration-preflight.md)：

```powershell
uv run stock-predict-mailer --config config/local.toml db plan --crawler-workspace data/crawler
uv run stock-predict-mailer --config config/local.toml db preflight --crawler-workspace data/crawler --archive D:/backups/before.spmbak --expected-plan <结构plan_id>
uv run stock-predict-mailer --config config/local.toml db migrate --store mail --crawler-workspace data/crawler --archive D:/backups/before.spmbak --expected-plan <结构plan_id> --expected-preflight <preflight_id>
```

参数中的配置、采集目录、端口、备份包及备份密钥引用必须与预检相同。可选 `--key-env` 指定备份密钥变量，`--port` 默认 8767。`--store` 必须且只能选择 mail/control/development/knowledge/legacy/crawler 之一；不支持 all，不初始化缺失库。

如果所选步骤包含旧平台训练授权的回放权限回填，会返回 `MIGRATION_AUTHORIZATION_REVIEW`；审阅 `db plan` 中的固定 UPDATE 和影响后，显式增加 `--accept-authorization-change` 才可执行。不把它当作普通字段变更静默通过。

本次代码开发和测试不会自动调用上述命令升级用户库。示例中的摘要占位值不可直接运行，需取自当前审阅结果。

## 执行与版本

命令先验证预检和认证备份，再取得组件启动/运行及业务锁；加锁后重新核对完整来源清单、结构计划、认证包。SQLite 以 mode=rw 打开来源，不创建缺失文件；取得 BEGIN IMMEDIATE 写锁后再次比较来源指纹和实际结构。

每条白名单 SQL 在同一事务中执行；检查目标结构、外键和 quick_check，通过后设置 application_id=1397771569（0x53504D31）及 user_version=1，再验证并提交。登记号描述当前已知结构契约，不能等同应用版本。版本目录 revision 3 会识别该成对标记，仍对全部结构/可选功能组做比较；单独设置某个标记、未来版本、缺表、未知对象或约束漂移均阻断。

成功返回 `committed=true`、`state=migrated`、所选库、操作/影响行数、前后结构摘要、版本标记和回执摘要；退出 0。授权确认不会出现在固定 SQL 之外触发额外操作。回执通过 JSON 输出，数据库内的持久记录是两个事务内版本标记，没有独立迁移历史表。

本库已登记且结构当前时，携带重新审阅的匹配备份和摘要会返回 `already_current`、`committed=false`、source_writes=0。旧摘要不会绕过校验或再次执行数据回填。

## 限制与故障处理

- 首版只支持 DELETE 日志模式；发现 WAL/SHM、WAL 头部模式或回滚日志会拒绝，不自动 checkpoint 或恢复。SQLite 写锁忙也会阻断。
- 一次只提交一个库。成功后原完整来源备份与现状不再匹配；升级下一个库必须重新备份、生成结构计划及预检，不能复用旧摘要。
- 事务内正常失败回滚本库；提交前会再次核对文件身份和所有已知其他来源文件。屏障只能约束配合的写入者，不保证外部程序不创建新文件，不提供跨文件或跨库原子事务。
- `MIGRATION_BLOCKED` 表示只读预检不通过，先运行 db preflight 查看具体阻断项；`MIGRATION_SOURCE_CHANGED`/`MIGRATION_PREFLIGHT_CHANGED` 要重新审阅来源和备份。
- `MIGRATION_COMMIT_OUTCOME_UNKNOWN` 表示提交阶段抛出异常；`MIGRATION_COMMITTED_RECHECK_REQUIRED` 表示事务已提交但清理失败。两者都应核对当前 db status、版本、完整性和原备份，不能假定没有修改或盲目重试。
- 突然退出可能留下回滚日志；只读报告不会代为打开原库恢复。先停写并保留原文件及匹配备份，再单独调查恢复。需要恢复备份时仍只恢复到全新隔离目录，不覆盖原库，不自动启动或重发任务。

该入口没有自定义 SQL、自动降级、覆盖恢复、服务接管或后台邮件功能。WAL 迁移、多库编排和完整迁移历史是后续范围。

原有服务构造器中的兼容建表/加列逻辑仍保留，本工具不拦截所有旧启动路径。不要在备份、预检和迁移之间重启这些写入者，否则来源会变化，原摘要必须作废后重新审阅。

## 验证记录（2026-11-16）

- 23 项新增专项通过：包括实际事务与版本登记、仅登记当前结构、授权确认、旧摘要拒绝、重复无写入、未知版本、DDL/目标失败回滚、提交结果不明、提交后清理失败、外部写锁、其他来源变化、WAL 阻断、崩溃日志及已登记备份恢复。
- 完整回归 682 项，681 通过、1 项已有 Windows 符号链接权限跳过，342.305 秒。最后补充库标识的输入类型校验后，23 项专项再次通过。
- 基础 wheel 的 23 项最终专项和 34 项结构测试通过；源码目录外使用安装的实际命令完成合成库迁移与版本识别。Ruff、compile、目录同步、命名及 diff 检查通过。
- 真实工作区仅只读检查：42 个来源文件在检查前后摘要一致、仍有 2 项已知升级；没有执行实际迁移、备份恢复或服务操作。本批操作手册不构成生产迁移验收。
