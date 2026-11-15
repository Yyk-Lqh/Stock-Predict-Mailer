# 第五阶段 D1：结构识别与只读迁移预演（2026-11-15）

沿用已授权下一步，交付数据库结构报告、已知升级计划和隔离副本演练。本批没有 apply 命令，不给真实库写 user_version/版本表，也不移除现有构造器的兼容逻辑。

## 实施步骤与选择

1. 建立随 wheel 发布的静态 schema catalogue，来自当前项目已知 CREATE/INDEX 及少量明确历史 ALTER。相比调用服务构造器识别，不会自动建库、生成密钥、恢复任务或导入研究依赖；相比仅看列名，比较列类型/顺序/默认/主键、唯一和普通索引、外键及规范化定义摘要。
2. 六处存储：agent-mail、正式/开发 control、private-knowledge、legacy state、crawler-jobs。按必需基础组及惰性可选功能组识别；未使用的研究/记忆/归档组不强制创建。非空的不完整可选组、未知对象或已知对象不兼容定义均阻断，避免把损坏当升级。
3. 版本报告区分库内 user_version/application_id 与结构推断。现存 0 只是未登记版本，不等于某个软件版本；非零但未登记的标记不猜测。每功能组返回 inferred_revision，整体 current/upgrade_available/blocked/missing。
4. 只允许明确增加字段/空结构：知识库 cleaner/extraction/review/origin/claim；训练 additional_rounds/priority；dataset replay_enabled；B1 MailCore 到完整绑定三表。dataset 的现有兼容代码还会给已有 platform_training 授权回填 replay_enabled=1，计划明确列为授权数据变化，不伪装成纯 DDL，也不在源执行。
5. 默认只读读取来源的原始 DB/WAL、克隆后在私有临时目录合并 WAL 并 quick_check。源 SHA/文件集合前后必须稳定，SHM/密钥/业务行不读取输出；不使用忽略 WAL 的 immutable。每库单文件 64 MiB、DB+WAL 合计 128 MiB 和查询预算，超限/热日志/链接明确阻断。
6. `db status [--store ...]` 返回元数据及结构指纹；`db plan` 返回绑定 catalogue/app 版本、源指纹、目标结构和固定 SQL 的 plan_id。默认仅展示，不执行迁移 SQL。缺失库只标记尚未初始化，不生成初始化计划。未知定义不回显原 SQL/默认内容，用摘要标识。
7. `db plan --rehearse --expected-plan ...` 先重验当前计划，再只在私有克隆上以事务执行白名单计划。比较演练前后与目标结构、检查外键和 quick_check，返回 SQL/改动计数，不写出克隆，不修改来源任务/授权或 metadata。演练成功不等于已授权或完成真实升级。
8. 维护目录生成器及 --check，使源码 CREATE 变化不能静默落后于 catalogue；基础 CI 加专项及目录检查。覆盖当前实际服务布局、历史列/权限回填、约束漂移、部分组、未知版本、WAL、只读性、计划漂移、事务失败、私密默认值和基础 wheel。

## 边界与验收

- 结构识别是明确的推断，不声称所有业务内容有效。表级 CHECK/索引定义变化也必须识别为未知，不能仅按列名判为已兼容。
- plan_id 绑定源数据文件指纹，源写入会使计划失效；结构指纹只描述 schema，行数据变化不应改变结构识别结果。各库分别取稳定副本，不承诺跨库同一时点。
- 预演临时目录包含来源数据，完成/错误时清理；不输出正文、密钥、profiles 值或未知 SQL 文本。无需 MASTER_KEY，也不解密业务列。
- 不阻止当前服务运行、不接管占用端口、不自动做备份/停止/升级。真实升级将是 D2 的显式动作，须先有正确备份、停写和事务/版本登记设计。

## 实施与验证结果

- 已交付静态目录/生成器及源码摘要检查、六库功能组结构推断、只读 status/plan 和 plan_id 匹配的副本事务演练。CI 增加专项与目录一致性检查；操作说明见 [手册](schema-planning.md)。
- 新增 32 项专项通过；完整回归 553 项，552 通过、1 项已有 Windows 符号链接权限跳过，耗时 295.771 秒。覆盖真实构造器生成的当前布局、旧知识库/训练/邮件、授权回填、未知结构/标记、约束/索引、WAL/SHM、来源变化、失败回滚、限制和隐私。
- 仅 wheel 的 Python 3.12 基础环境 32 项通过；确认缺少 numpy/sklearn/pandas/requests/baostock。在源码外运行安装后的 status/plan/rehearse 命令成功，合成来源字节未变。wheel 包含 13 个 operations 文件（含 JSON 目录）；Ruff、compile、目录检查、命名、仓库卫生和 diff 空白检查通过。
- 真实工作区仅 status/plan：邮件库识别到一组可增加的空绑定表，正式/开发 control 和知识库当前，legacy/crawler 尚无数据库。38 个文件 / 2,928,252 字节的文件集合与 SHA 摘要前后相同；记录位于 `.tmp/schema-workspace-report.json`、`.tmp/schema-workspace-plan.json`、`.tmp/schema-workspace-readonly-check.json`。
- 未对真实库演练或升级，未备份/恢复、启停组件或触发模型/采集/邮件。D2 的实际升级仍需单独实现并验证，不能据此声称生产迁移已完成。
