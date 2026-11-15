# 数据库结构识别与迁移演练

`db status` 和 `db plan` 可识别当前已知结构，展示旧库升级步骤。`--rehearse` 在一次性副本中执行并回滚步骤，验证升级后的结构。当前没有实际升级入口；不会给原库写版本号、创建数据库、生成密钥、修改授权或恢复任务。

## 查看与演练

在项目根目录执行，替换为实际使用的配置与采集工作区：

```powershell
uv run stock-predict-mailer --config config/agent-example.toml db status --crawler-workspace data/crawler
uv run stock-predict-mailer --config config/agent-example.toml db plan --store knowledge
uv run stock-predict-mailer --config config/agent-example.toml db plan --store knowledge --rehearse --expected-plan <上一条返回的plan_id>
```

`--store` 支持 `all`（默认）、`mail`、`control`、`development`、`knowledge`、`legacy`、`crawler`。应用根目录来自 TOML 的 workspace；采集目录来自参数或现有 crawler 环境变量/默认目录。参数不会持久化。演练须使用与计划相同的目录和参数。

退出码：0 表示结构当前、尚未初始化或演练成功；1 表示存在已知升级步骤；2 表示阻断或操作错误。演练成功仍保留来源的 `upgrade_available` 状态和 `ready_for_apply=false`，因为来源未升级。`ready=true` 只表示可以对副本演练，不表示允许实际迁移。

报告包含应用/SQLite 版本、目录摘要、每库状态、功能组推断版本、库内版本标记、结构摘要和来源摘要。`schema_id` 由结构决定；`source_id` 绑定路径及原 DB/WAL 字节。`plan_id` 绑定应用/目录/SQLite 版本、来源和固定步骤；即使只修改一行业务数据，也必须重新生成计划。`generated_at` 不参与摘要。

## 如何识别

六处数据库分别为应用目录下的 `agent-mail.sqlite3`、`control.sqlite3`、`control-development.sqlite3`、`private-knowledge/knowledge.sqlite3`、`state.sqlite3`，以及采集目录下的 `jobs/crawler-jobs.sqlite3`。

现有数据库没有集中登记版本，所以 `user_version=0` 只表示尚未登记。报告使用 `version_source=structural_inference`，按功能组推断 revision，不将其当作应用版本。非零但未登记的 user_version 或 application_id 均阻断，不覆盖原标记。

随安装包发布的静态结构目录来自项目已知 DDL。比较包含列顺序、类型、非空、默认值、主键、外键、索引、唯一约束和规范化 SQL 定义摘要；CHECK 或索引变化也会被发现。未知对象、缺失必需组、不完整的可选组、定义漂移均阻断。已知 FTS5 影子表包含在模型中，不按名称前缀忽略陌生表。

未使用的记忆、研究、邮件归档等可选功能组不会自动初始化。整个数据库缺失时只报告 `missing`。已使用旧 MailCore 且完整缺失绑定组时，可计划创建三张空表，不从历史邮件猜测端点。

已登记的增量包括：

- 知识库的 cleaner_config、extraction、review、origin、claim_id。
- 研究任务的 additional_rounds、priority。
- 数据授权的 replay_enabled，以及现有兼容逻辑对 platform_training=1 记录的回填。
- MailCore 的空 binding、alias、control 三表。
- 知识库的空 workers 进度表（远程 bb8c104 更新）；兼容门面的 kb_owner_map 为可选功能组。

授权回填会启用已有平台训练授权的历史回放权限，计划以 `requires_permission_review=true` 和明确的 `data_effect` 提示。副本演练返回影响行数，原授权保持原状。当前没有授权真实迁移的入口。

## 副本和隐私边界

工具只按字节读取来源 DB/WAL，不通过 SQLite 打开原库，避免只读连接也生成或改动 WAL/SHM。复制前后核对集合和摘要，随后只在临时目录合并 WAL、检查完整性和读取结构。来源在复制或演练期间变化会阻断；无需 MASTER_KEY，不解密业务列。

演练重验 plan_id 后再次取稳定副本，开启外键检查及显式事务，按目录中的固定语句执行，验证目标结构、foreign_key_check、quick_check，最后回滚并关闭删除临时文件。不能注入自定义 SQL，也不发布升级后副本。临时文件包含业务数据，应在可信本机环境运行；正常成功及异常退出会清理临时目录，进程被强制终止时不保证完成清理。

输出包含本机工作区路径、已知结构名和固定迁移 SQL。不会输出业务行、密钥、私密默认值、未知对象名/SQL 或底层数据库异常。`data_rows_changed` 是副本中的语句影响计数，不是来源变更。

每个源文件上限 64 MiB，每库 DB+WAL 合计 128 MiB；结构最多 256 个对象、每表 128 列、定义文本合计 512 KiB，SQLite 操作有时间预算。回滚日志、缺少主库的 WAL、路径链接/重解析点、损坏或超限均阻断。该工具不暂停写入者，各库分别取稳定副本，不能保证跨库同一时点或证明业务内容正确。

常见问题：`SCHEMA_SOURCE_CHANGED` 需待写入稳定后重试；`SCHEMA_PLAN_CHANGED` 需重新审阅当前计划；`UNREGISTERED_USER_VERSION`、`STRUCTURAL_DRIFT`、`UNKNOWN_SCHEMA_OBJECTS` 需核对来源和已有版本；`SCHEMA_JOURNAL`/`SCHEMA_WAL` 不应直接删文件，应先单独调查写入者与恢复状态。

## 维护与后续

修改结构源码后执行 `python scripts/build_schema_catalog.py`，审阅生成的 JSON，再运行 `--check`。生成器读取源码 AST，不导入业务服务或研究依赖；目录同时记录来源文件摘要，DDL/兼容升级所在模块变化会使检查失败。新增历史升级必须明确登记语句、数据影响和相应回归，不可只重生成目录。

目录 revision 2 已兼容统一知识库、进度表和 owner 映射，并保留旧 state.sqlite3 知识表的历史识别。历史识别不会自动把明文正文和授权转入新知识库。此次远程适配和验证见[更新记录](remote-update-2026-11-15.md)。

下一步 D2 才会设计已知版本的实际迁移：验证过的加密备份、可确认的停写边界、逐库事务、版本登记、权限变化显式审阅、失败恢复和跨版本测试。当前演练成功不代替这些条件。
