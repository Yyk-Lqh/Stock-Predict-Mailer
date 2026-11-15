# 股票采集 MCP 服务

采集模块是可选组件，与主控制台分开启动。启动、工具发现和 `crawler_status` 不发起外部采集，也不依赖 pandas、requests 或 baostock；调用采集工具前安装 crawler 依赖。

## 安装与运行

长时间采集推荐使用[持久化任务与独立 Worker](crawler-jobs.md)，支持排队、进度、取消和显式恢复。原同步工具保留，并与 Worker 共用工作区写锁。

在项目根目录执行：

```powershell
uv sync --extra crawler
uv run --extra crawler stock-predict-mailer-crawler
# HTTP，本机端点 http://127.0.0.1:8000/mcp
uv run --extra crawler stock-predict-mailer-crawler --http --port 8000
```

已有知识库/研究环境可使用 `uv sync --all-extras --locked` 保留全部可选功能。`uv sync` 会将环境同步到选定的依赖组，未选择的可选依赖可能被移除。

模块入口是 `python -m mcp_server.server`。兼容旧用法 `python src/mcp_server/server.py`；wheel 同样包含此模块和命令入口。

控制台添加 stdio MCP 服务时，启动程序选择项目 `.venv/Scripts/python.exe` 的绝对路径，参数填写 `["-m", "mcp_server.server"]`。建议通过加密 env 配置明确设置下面的工作区变量。HTTP 模式使用 Streamable HTTP URL `http://127.0.0.1:8000/mcp`。按现有工具授权机制仅授予实际需要的工具。

## 工作区与已有数据

默认目录是服务进程当前工作目录下的 `data/crawler`。推荐在启动前指定绝对路径：

```powershell
$env:STOCK_PREDICT_MAILER_CRAWLER_WORKSPACE = 'D:\python\Stock-Predict-Mailer\data\crawler'
uv run --extra crawler stock-predict-mailer-crawler --http --port 8000
```

工作区结构：

```text
data/crawler/
  data/stock_data117.csv
  data/stock_data117.csv.metadata.json
  data/fundamental_quarterly_new.csv
  data/fundamental_quarterly_new.csv.metadata.json
  data/fundamental_as_of_<date>.csv
  data/fundamental_as_of_<date>.csv.metadata.json
  data/重采进度.log
  sessions/cache_stock_data.json
```

旧版本使用 `src/数据面2/` 和 `src/sessions/`。新版本不会自动移动或覆盖这些文件。需要续采时，停止采集服务并备份旧文件，将旧股票池与基本面 CSV 显式复制到新工作区的 `data/`，目录缓存复制到 `sessions/`；检查状态工具返回的路径后再启动采集。保留旧文件用于核对。更改工作区变量后须重启服务。

## 工具及边界

- `crawler_status`：只读文件状态及元数据完整性，缺文件不创建目录；不加载采集依赖。
- `crawl_stock_catalog(force_refresh=false, max_cache_age_seconds=300, allow_stale=false)`：首次无缓存会联网；已有缓存过期后默认报错，不自动请求来源。强刷前须遵守来源限流要求。
- `collect_fundamental_data(max_stocks=0, end_date=null, allow_unverified_pool=false)`：基于股票池增量采集。`0` 是全量长任务；默认拒绝旧版或过期股票池，显式允许时结果保留未验证标记。负数与未来日期拒绝执行。

成功和失败均返回 JSON 文本。失败具有 `ok=false` 和 `error.code/message`，异常还提供 hint/details。缺依赖为 `DEPENDENCY_MISSING`；过期缓存为 `CACHE_STALE`，旧版无时间缓存为 `CACHE_UNVERIFIED`；分页缺失为 `PARTIAL_DATA`，未经验证股票池为 `POOL_UNVERIFIED`，格式或校验损坏为 `INVALID_DATA`。工具名称及原主要参数保持不变，新增参数均可选。

## 时间、缓存与完整性

默认截止日期现在取上海时区当天，移除了原固定日期。季度仍取截止日所在季度的前一季度，例如 9 月 30 日截止 Q2、10 月 1 日截止 Q3。显式 `end_date` 使用 YYYY-MM-DD，用于生成截止日基本面视图；目录来源只提供当前快照，不支持伪造历史行情请求。

`crawl_date`/`request_as_of` 是请求截止日，`fetched_at` 是本机取回数据的时间；当前目录来源没有可核验的行情时间，因此 `source_as_of=null`、`source_time_verified=false`，抓取成功不会被标为实时行情。多来源基本面主文件含不同时刻的行，元数据只给生成时间，不将文件更新时间当成所有行的抓取时间。

目录缓存采用 `cache_version=1`，默认有效期 300 秒，工具可指定 0 至 86400 秒。过期缓存和旧版无时间缓存默认拒绝；显式 `allow_stale=true` 可以导出资料，但会标注 stale/unverified，且 `analysis_eligible=false`。fresh/complete 时的 `analysis_eligible` 只表示通过本阶段的结构、缓存年龄和分页检查，不代表已经核验行情时效。

分页按唯一代码计数，数量变化、重复造成缺口、空页或后续页失败均标 partial，不覆盖上一份有效缓存和股票池。非法代码、非有限数值、负价格/成交量和高低价倒置拒绝；来源的空值保留为空。价格暂保留旧适配器 /100 转换并在元数据中注明，成交量仅标为 source_native，尚未重新核验来源当前字段的计价规则。

CSV 与 sidecar 通过 SHA256 绑定，每个文件以原子替换写入；两文件之间意外中断时，哈希不一致将被下游拒绝，不宣称跨文件事务。旧版没有 sidecar 的文件保持未验证，不能靠文件修改时间推断抓取时间。

## 基本面截止日视图

主 CSV 保存采集基线；`fundamental_as_of_<date>.csv` 单独筛选截止季度内、已于截止日披露且披露字段可验证的行，不删除主文件中的较新记录。每行记录报告期、披露日期、publication_verified 和新采集行的 collected_at。合并表中任一非空表缺披露日期，该行不进入已验证视图；旧行没有验证标记时也不会被默认为已验证。

第三阶段额外记录 `provider_symbol`（实际采集交易所路由）和视图 `run_complete`（选定任务是否完整完成），供[单标的分析](single-symbol-analysis.md)核对对象和采集结果。旧行缺路由时不会按代码猜测，应重新采集对应行；本阶段没有自动重采或迁移旧资料。

视图元数据始终包含 `point_in_time_verified=false` 和 `historical_pool_verified=false`：当前来源可能返回事后修订值，当前股票池也不代表当时的证券全集，因此该视图不能直接作为无未来信息泄漏的历史回测输入。字段单位沿用来源，不统一虚构为百分比或金额。

限量采集、失败或中断时 `completeness=partial`；`ok` 只表示选定任务是否完成，`dataset_completeness=unknown` 保留对整个历史覆盖范围的限制。主文件损坏或与已有 sidecar 不符时停止续采，不再静默从头覆盖。

基本面模块仍含来源专用 socket 配置。新任务路径在独立 Worker 执行，具备跨进程写锁、股票检查点和协作取消；旧同步工具不自动转换成后台任务，但参与相同互斥。文件原子替换不等于跨文件/SQLite 事务，异常时仍可能需要核对数据。

## 离线验证

```powershell
uv run --extra crawler stock-predict-mailer-crawler-verify
uv run --extra crawler python -m unittest discover -s tests -p test_crawler_service.py -v
uv run --extra crawler python -m unittest discover -s tests -p test_crawler_quality.py -v
```

验证使用临时合成缓存，不读取或改写业务 CSV，不发起行情请求。测试使用本机回环网络验证实际 stdio/HTTP 工具发现及状态调用，未调用真实采集工具。

`stock-predict-mailer-crawler-verify --online` 会另行执行一次 baostock 登录及预检查询并退出登录，可能创建本地日志；它不是全市场采集，也不能证明来源长期可用。本轮未执行该选项。
