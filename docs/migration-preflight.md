# D2A：实际迁移前的只读就绪检查

本批连接已完成的结构计划、加密备份和运行状态检查。`db preflight` 没有实际迁移入口，不修改 SQLite、授权或版本登记，不创建备份、恢复目录或启动组件。

实施顺序：先验证完整来源清单和已审阅结构摘要；检查组件/业务锁与控制台端口；认证解密并验证现有备份；比较备份的来源 plan_id；重新检查全部来源文件和停写状态。任何一步不匹配即阻断，不输出底层异常或正文。

```powershell
uv run stock-predict-mailer --config config/local.toml db plan --crawler-workspace data/crawler
uv run stock-predict-mailer --config config/local.toml db preflight --crawler-workspace data/crawler --archive D:/backups/snapshot.spmbak --expected-plan <结构计划的plan_id>
```

实际检查前，应按[备份手册](workspace-backup.md)停止写入者并显式创建加密备份。备份密钥来自默认 BACKUP_KEY 的规范环境引用或 `--key-env`；生产主密钥仍须在终端环境可用。应用/采集目录、原 TOML 路径、文件内容和控制台端口均须与备份清单匹配。检查整个工作区，不支持只选某个库以忽略其他库的变化。

成功退出 0，阻断或错误退出 2。成功结果包含 `preflight_id`、结构/备份摘要、认证包摘要、操作数量及权限变化提示；`ready=true` 仅指此次检查通过，`ready_for_apply=false` 始终保留。不存在升级步骤时返回 `state=no_changes`。授权回填的 `requires_permission_review` 仍须在 db migrate 实际迁移入口显式审阅。

`SCHEMA_PLAN_CHANGED` 需要重新审阅结构计划；`MIGRATION_BACKUP_MISMATCH` 表示当前工作区与认证备份不是同一清单；`MIGRATION_SOURCE_CHANGED` 表示检查期间来源变化。BACKUP_COMPONENT_ACTIVE/BACKUP_WRITER_BUSY/BACKUP_PORT_UNAVAILABLE 等沿用备份的阻断语义。备份包本身有效不意味着它对应当前工作区，因此不能只运行 backup verify 就认定满足迁移前提。

就绪检查不取得会创建锁目录的停写屏障，也不承诺跨库同一时点、阻止不遵守锁的外部写入者，或保证返回后状态不会变化。前后摘要检测用于发现检查期间的变化；临时副本仍按现有备份校验流程清理。D2B 的[单库事务迁移](database-migration.md)执行时会重新取得屏障并核对摘要，不复用检查时的运行状态。

## 2026-11-16 验收

- 13 项新增专项通过，覆盖匹配/过期/错工作区/错端口备份、结构漂移、损坏认证包、检查期间数据变化和新写入者、CLI 退出码及来源不变。
- 完整回归 659 项，658 通过、1 项已有 Windows 符号链接权限跳过，349.963 秒。基础 wheel 中同样 13 项通过；源码目录外确认安装的新模块和 CLI 入口可用。Ruff、compile、目录同步、命名和 diff 空白检查通过。
- 真实工作区只做结构读取；本轮采样的 42 个来源文件在只读检查前后保持一致，仍有 2 项已知结构增量。前一日 38 文件基线与当前数据已有差异，未据此归因或修改来源。实际数据未创建备份、解密预检、恢复或迁移，未启停现有服务、采集或发送邮件。
