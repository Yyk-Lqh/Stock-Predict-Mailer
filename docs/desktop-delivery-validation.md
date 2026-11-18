# 桌面交付验收

日期：2026-11-17。承接桌面UI优化一至四阶段，执行本地整体验收和真实服务配置核对。用户确认先完成本地验收，真实服务另行配置。本轮未改手机界面，也不安排手机浏览器验收。

随后用户明确启动真实联调，已实际完成模型、项目MCP和邮件测试，结果见 [真实联调记录](real-integration-validation.md)。本文的外部服务未执行说明保留为该阶段当时的范围。

## 可复用检查入口

在包含项目全部可选依赖及Ruff的Python环境中执行。本机使用项目 `.venv`，系统默认Python缺少部分依赖，不适合全量验收。

```powershell
# 静态检查；不运行模型、邮件或浏览器
.venv/Scripts/python.exe scripts/check_desktop_delivery.py

# 另执行现有Node逻辑回归和完整Python测试
.venv/Scripts/python.exe scripts/check_desktop_delivery.py --full
```

跨平台也可在准备好锁定依赖后执行 `uv run --locked --all-extras python scripts/check_desktop_delivery.py --full`。脚本自身不安装、升级依赖，不读取真实配置，不调用实际供应商或发送邮件。测试使用现有临时工作区和回环协议服务。

静态检查包含Ruff、Python编译、Schema和运行图生成同步、控制台生成同步/资源预算、命名、仓库卫生、diff空白，以及控制台模块、两个前端和浏览器验收脚本的JavaScript语法。完整模式额外执行13套既有Node逻辑回归和 `unittest discover -s tests -v`。

每次运行将 `summary.json` 与逐步日志保存至忽略目录 `.tmp/desktop-delivery/checks/<run>/`，记录执行模式、Python版本、实际执行命令数、退出码与耗时。首个失败步骤结束后停止，进程返回非零；中断会记录为 `interrupted`。浏览器验收需按下节单独执行，不包含在此脚本中。

仓库卫生增加 `--include-untracked`，把尚未加入Git、且不被忽略的新文件也纳入检查；默认既有CI行为保持不变。私有工作区、凭据等已忽略文件不进入候选集合。新增回归验证：未跟踪的合成 `.pem` 会被拒绝，忽略目录不被误纳入；没有仓库时，候选文件检查不能静默通过。

已实测缺少Ruff的系统Python会在首步返回失败并保留日志，没有执行后续步骤；不能将缺失依赖当成检查通过。

## 桌面浏览器复验

浏览操作全部通过gstack `/browse`。以下服务均创建临时目录，退出后清理；不要把验收脚本用于实际业务服务。

1. `python tests/browser_console_fixture.py --port 8769 --forecast-fixtures`：分别执行 `tests/browser_desktop_archive.js`（4组，`data-desktop-archive-check`）与 `tests/browser_desktop_library.js`（6组，`data-desktop-library-check`）。
2. 退出上一个8769服务，再启动 `python tests/browser_console_fixture.py --port 8769 --record-fixtures`：执行 `tests/browser_desktop_records.js`（6组，`data-desktop-records-test`）。
3. `python tests/browser_intake_fixture.py --port 8788`：执行 `tests/browser_desktop_intake.js`（8组，`data-desktop-intake-test`）。

控制台每次重新导航后先等待 `body[data-view="analysis"]`，接入中心等待 `#intake-theme`，再执行脚本。本轮使用1440×900、1280×720和1280×800桌面窗口。归档和任务记录使用各自独立的种子数据；混用会改变固定分页总数，使验收条件失效。

必须检查gstack每一步的退出码、结果字段非空、可解析、没有 `error`，并核对预期检查数量。等待超时或读取到空字段即为失败，不能继续算作通过。更早的键盘层级、原生输入和Esc驱动步骤保留在 [工作台验收说明](console-workbench.md)。

本轮4类浏览器验收合计24组通过，覆盖实际合成上传、审阅/批准/发布、版本切换、只读观测预览、70条HTTP任务分页、刷新/重试、身份隔离、数据清洗和逐批次发布回执。没有新增产品界面缺陷；首轮混用种子/未等待初始化的验收操作错误已纠正，不计为成功结果。

## 本地执行结果

初次直接执行完整Python回归：785项，783通过、2项因Windows符号链接权限不足跳过，耗时301.973秒。现有13套Node逻辑回归通过；新加的仓库卫生2项回归通过。静态入口9个步骤通过，JavaScript语法覆盖66个文件。

统一入口最终完整模式通过：787项Python测试，785通过、2项因Windows符号链接权限不足跳过，测试自身耗时294.198秒；13套Node逻辑回归及全部9个静态步骤通过。两项跳过分别属于诊断的外部数据库链接和预测归档/锁文件链接检查，不以普通路径用例替代。最初的既有邮件集成测试出现一次已关闭socket的ResourceWarning，没有失败项；该警告不作为真实邮件联调结果。

本机完整模式结果为 `.tmp/desktop-delivery/checks/20261117T134632Z-5a6811ec/summary.json`，状态 `passed`，同目录保留每步日志；这些结果位于忽略目录，不纳入版本控制。缺依赖的预期失败检查另行保存，未混入成功结果。远程CI矩阵仍待执行。先前一轮的58组桌面交互检查与3个完整Mock/文件投递流程见 [优化计划](desktop-frontend-optimization-plan.md)。

## 真实服务准备情况

仅对本机TOML所指向的候选工作区做不解密的只读数据库快照核对，未构造会写库的Store对象、未修改业务配置、未启动MCP命令。该结果不证明正在运行的服务身份或外部连通性。

- 候选正式库：默认Mock，无MCP配置，邮件为文件模拟。
- 候选开发库：两个兼容模型，其中一个有已存凭据标记；无MCP配置，邮件为文件模拟。凭据标记不代表密钥有效或连接通过。
- 本次检查进程未提供正式主密钥，没有读取或展示任何凭据，也没有改用另一把密钥打开正式库。

真实联调后续需要选定配置库/模型、手动报价及单次预算；为MCP指定服务与只读权限；邮件需选定实际通道和明确的测试收件人。用户本轮选择先完成本地验收，因此以上外部调用均未执行。

本轮不执行Git提交、推送、远程CI、部署，也不新增会话重命名、置顶或全局搜索。业务上的正式投递结果与模型输出质量仍须在真实环境中单独验证。
