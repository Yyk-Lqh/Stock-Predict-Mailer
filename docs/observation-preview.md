# 观测导入与评估预览

阶段 6D（2026-11-16）在[控制台预测详情](forecast-console.md)增加显式观测导入与预览。设计见[本轮计划](observation-preview-plan.md)。已有控制台需正常重启加载接口，再刷新网页；本轮仅在独立临时服务验收。

## 使用流程

1. 在“任务记录 → 预测归档”打开有权访问的任务详情，展开“导入观测并预览”。
2. 选择 UTF-8 的 `.json` 或 `.csv` 文件，也可粘贴原文并明确选择格式。上限 256 KiB。页面提供字段及与当前预测的匹配要求，不自动填实际价格，不从事前基准生成观测。
3. 可选填写评价截止时间，须含时区；留空使用当前时间。点击“校验并预览”。
4. 核对标的、指标/单位、合成标记、观测/可用时间和来源声明。符合时点条件才显示方向与可用数值误差，始终标注“未保存”。

修改原文、格式或截止时间会清除旧评分；慢响应不会恢复已经失效的结果。导入文件尚在读取时暂不能预览，慢文件也不会覆盖之后的手动修改。切换任务/筛选/身份、关闭详情会丢弃本轮观测及预览；不会保存到浏览器草稿，重新打开需再次提供。

本轮不保存正式回执、不修改原报告，也不触发模型、行情采集或邮件。已有回执仍按原值显示；预览中的新观测不会覆盖它。正式保存暂继续通过既有显式 CLI `forecast evaluate` 完成，不要把本页预览视为已登记的评估结果。

## 明确的输入格式

JSON 为完整的 v1 observation 对象，字段如下；示例是合成数据，使用时必须替换为与目标预测严格匹配的实际来源声明：

```json
{
  "schema_version": "1",
  "subject": "DEMO.SZ",
  "metric": "close_unadjusted",
  "unit": "CNY",
  "value": 112,
  "observed_at": "2026-11-16T15:00:00+08:00",
  "available_at": "2026-11-16T15:05:00+08:00",
  "source": "synthetic-observation",
  "synthetic": true
}
```

CSV 第一行为完整且不重复的字段名，顺序可调整，恰好一条数据；不从多行中挑选最新值，不猜测列名、币种、时区或复权口径：

```csv
schema_version,subject,metric,unit,value,observed_at,available_at,source,synthetic
1,DEMO.SZ,close_unadjusted,CNY,112,2026-11-16T15:00:00+08:00,2026-11-16T15:05:00+08:00,synthetic-observation,true
```

CSV 使用逗号分隔；带逗号或换行的来源须正确加引号，synthetic 只能是小写 true/false，value 使用有限的 JSON 数字形式。JSON 使用数字与布尔值，不接受数字字符串或布尔值充当数值。拒绝 JSON 重复键、未知字段、缺失字段、不完整行和多个观测。接受 UTF-8 BOM，拒绝损坏编码。

## 匹配与时点

- 标的、指标、单位、合成标记必须与事前定义精确匹配。指标名不同不会自动视为同一口径。
- observed_at 必须等于事前 target_at，available_at 不早于 observed_at。不能拿邻近交易日或事后改口径的值替代。
- 截止不得晚于现在或早于注册时间。未到目标时点返回 not_due；到期但观测在截止时尚不可用返回 awaiting_observation；两者均没有 metrics。
- 只有可用的匹配观测才返回 ready 与 metrics。方向阈值、十进制边界、缺少方向/数值时的处理沿用[归档评分契约](forecast-evaluation.md)。原预测已过接收有效期不妨碍按归档的事前定义预览到期结果。

匹配检查只核对声明的一致性，不认证来源是否真实。文件名、来源文本和日期均不作为可信指令执行；摘要也不能证明来源可信。

## 接口与摘要

`POST /api/tasks/{task_id}/forecast/preview` 沿用本机会话、同源 Host/Origin、CSRF 和任务 owner 权限。支持以下请求体之一：

```python
import json
from pathlib import Path

object_request = {"observation": json.loads(Path("actual.json").read_bytes())}
file_request = {"format": "csv", "content": Path("actual.csv").read_bytes().decode("utf-8")}
# 两种方式都可显式添加 as_of，接口不接受 URL 查询参数。
```

服务端不接受文件路径、任意 forecast_id、persisted、dry_run 或其他写入选项。请求体仍受现有 1 MiB HTTP 限制；原始观测文本/对象另受 256 KiB 限制，任务读取与响应预算沿用控制台档案约束。

响应包含 task_id、forecast_id、forecast_content_id、forecast_record_id、as_of、computed_at、synthetic、state、observation、observation_id、input、limitations；persisted 始终为 false，ready 才有 metrics。没有 evaluation 或正式回执 ID。

input 含 format、content_sha256、bytes。JSON/CSV 原文摘要识别接收到的 UTF-8 内容；对象方式识别其规范 JSON 字节。observation_id 则识别校验后标准观测。相同观测的不同空白排版可有不同原文摘要。浏览器保留未编辑文件的 BOM 和 CRLF；原文经用户编辑后，摘要改为识别编辑后的文本。预览针对单份已校验的预测记录快照计算，不二次读入不同版本评分，也不调用归档 evaluate/写锁/发布方法。

已到期且观测可用时，可从预测详情显式「提交观测并保存评估」。`POST /api/tasks/{task_id}/forecast/evaluate` 接受 `preview`（原请求与预览返回的固定 `as_of`）、`forecast_record_id` 和 `observation_id`。服务端校验任务所有者及模式，核对预测和观测摘要，再使用现有归档机制保存回执。同一预测与观测的重试返回已有回执。

## 验证

- 新增 25 项专项全部通过，覆盖 JSON/CSV、编码/摘要、数值/字段、时点、权限/CSRF、已有回执及整工作区无写入。完整回归 783 项，781 通过、2 项 Windows 符号链接权限跳过，耗时 331.760 秒。
- 安装后的基础 Python 3.12 wheel：新增 25 项全部通过，既有预测 76 项中 75 通过、1 项相同权限跳过，共 101 项。源码目录外实际 HTTP 验证 JSON/CSV 预览、打包脚本和失败任务关联，临时工作区所有文件字节保持一致，写入回执 0。
- gstack `/browse` 通过 9 组预览流程：匹配/评分/来源转义/无回执、编辑失效与错误恢复、成熟/可用门禁、BOM/CRLF 原文件摘要、多行拒绝、慢文件保护、慢请求保护、任务/身份隔离、重新打开为空且无浏览器草稿。原有控制台 8 组流程回归通过。
- 1440×1000 桌面及 390×844 手机均检查预览；页面宽度与视口一致，无横向溢出。浏览器验收发现并修复文本框换行规范化影响原文件摘要的问题。
- Ruff、Node 语法、Python 编译、生成脚本同步、静态结构目录、命名、仓库卫生与 diff 检查通过。相关本地文档链接有效；浏览器验收仍为本地临时服务，未接入远端浏览器 CI。
- 真实工作区只读检查：42 个来源文件前后摘要一致，0 条归档，未初始化真实归档目录。没有真实采集、外部模型、SMTP、数据库迁移、正式评估写入或真实服务重启。本轮没有 Git 提交/推送，此前修改继续保留。
