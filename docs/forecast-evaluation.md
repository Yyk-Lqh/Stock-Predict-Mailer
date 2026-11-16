# 预测归档与到期评估

`forecast register/list/show/evaluate` 提供离线闭环：在预测仍有效、目标尚未到达时固定评价口径，到期后用明确提供的观测计算误差。工具不采集行情、不调用模型、不发送邮件，也不会自动导入既有 analysis 目录。

## 使用顺序

```powershell
uv run stock-predict-mailer --config config/local.toml forecast register --prediction prediction.json --definition definition.json
uv run stock-predict-mailer --config config/local.toml forecast list --limit 50 --offset 0
uv run stock-predict-mailer --config config/local.toml forecast show <forecast_id>
uv run stock-predict-mailer --config config/local.toml forecast evaluate <forecast_id> --observation observation.json --dry-run
uv run stock-predict-mailer --config config/local.toml forecast evaluate <forecast_id> --observation observation.json
```

`prediction.json` 使用现有严格 v1 预测合同，可来自上游预测文件。注册仍采用默认 24 小时新鲜度校验；注册后读取旧记录以实际 registered_at 校验，不会因当前时间已过有效期而无法到期评估。过期预测不能事后补注册；已有记录到期后请用 show，不重复 register。

注册返回 forecast_id（subject/model_version/prediction_id 的摘要）、固定预测/定义和内容摘要。同一身份与相同内容的有效期内重复注册会复用首次记录；预测或定义变化返回 FORECAST_CONFLICT，不能替换已归档口径。新口径须使用新的预测 ID。

## 事前评价定义

以下只演示字段格式。示例时间会过期，不能把真实旧预测改写为“现在”绕过校验。

```json
{
  "schema_version": "1",
  "target_at": "2026-11-16T10:00:00Z",
  "timezone": "Asia/Shanghai",
  "metric": "close_unadjusted",
  "unit": "CNY",
  "flat_tolerance": 0.1,
  "reference": {
    "value": 100,
    "observed_at": "2026-11-16T08:00:00Z",
    "available_at": "2026-11-16T09:00:00Z",
    "source": "synthetic-reference",
    "synthetic": true
  }
}
```

此定义对应生成于 09:00Z、horizon=1 hours 的合成预测。metric 的实际含义由上游/操作者事前声明，例如未复权收盘价和复权价格不得混用；工具不推测预测数值究竟是价格、收益率还是评分。数值预测的 value_unit 必须与定义一致，reference 也按该指标与单位提供。错误口径不能靠单位校验自动识别。

reference 的观测和可用时点必须不晚于预测生成时点；target_at 必须晚于实际注册时点。flat_tolerance 是同单位的非负绝对变化阈值，必须事前固定。预测、基准和结果的 synthetic 必须一致，合成记录不会被表述为真实验证。

预测的 valid_until 表示接收/使用有效期，**不是目标到期时间**。目标与 horizon 的匹配规则：

- hours：target_at 精确等于 generated_at 加指定小时数。
- calendar_days：在定义的 IANA 时区中，目标日期等于生成日期加指定天数；目标当天的具体时刻必须显式选择。跨 DST 可相差 23/25 小时，不固定当作 24 小时。
- trading_days：额外提供 `calendar: {"source":"日历来源声明","sessions":["YYYY-MM-DD", ...]}`。数量须等于 horizon.value，严格递增、全部晚于生成时点在该时区的日期，末日等于目标日期。清单是所声明的后续交易日；工具不联网认证其是否遗漏休市/交易日，不自行按周末规则猜测。

本批只接受以上相对生成时点/日期的周期口径。以月末、特征截止日等其他锚点定义目标的上游预测，以及概率/截面排名事件，需要后续专门适配，不能直接拿模型概率与价格比较或改写日期/周期来凑。应先由上游明确新版本的目标与观测含义。

## 观测与评分

观测 JSON 必填 schema_version、subject、metric、unit、value、observed_at、available_at、source、synthetic。示例：

```json
{"schema_version":"1","subject":"DEMO.SZ","metric":"close_unadjusted","unit":"CNY","value":112,"observed_at":"2026-11-16T10:00:00Z","available_at":"2026-11-16T10:05:00Z","source":"synthetic-observation","synthetic":true}
```

对象、指标、单位、合成标记须匹配，observed_at 必须精确对应已登记的 target_at；不能挑选其他日期或更晚价格作为目标结果。available_at 不早于观测且不晚于查询 as_of 才可评分。数据来源和时间仍是提供方声明，不代表独立来源认证。

尚未到期返回 not_due，到期但未提供/尚无可用观测返回 awaiting_observation，均不输出指标或保存回执。成功评估计算 actual-reference 的变化及 realized_direction；变化绝对值不超过 flat_tolerance 时为 flat。预测有 direction 时提供 direction_correct，无 direction 则为 null。有数值预测时提供 signed_error=actual-predicted 与 absolute_error，单位沿用定义；缺失项不伪造。溢出、布尔值或非有限数字拒绝。confidence 和上游 metrics 只归档，不转为概率校准、交易收益或模型可靠性承诺。

`--dry-run` 只计算，不创建回执或写锁。正式 evaluate 保存完整观测、其摘要、预测内容引用、指标、首次请求 as_of 和实际 evaluated_at。同一标准化观测重复评估复用首次回执，即使后来请求的 as_of 不同；响应顶层 as_of 是本次截止，回执内保留首次值。修订观测追加新回执，不能抹掉旧结果。回执摘要与预测内容绑定；来源文字变化也属于新观测版本。

## 查询、历史时点与状态

list/show/evaluate 支持带时区的 `--as-of`，不能晚于现在。注册晚于该截止的记录不可见；show 返回 FORECAST_NOT_YET_REGISTERED，list 忽略它。list/show 只展示 evaluated_at 不晚于截止的回执，状态为 pending/due/evaluated。

evaluate 是当前发起的计算，允许用历史 as_of 限定当时已可用的观测，但新回执 evaluated_at 仍为当前实际时间，不能冒充历史系统当时已有评分。查看历史系统状态用 list/show；注册时间和上游时间都不是数字签名证明。

列表支持 limit=1..100、offset=0..1000，返回 total/returned/next_offset。这些是时点可见记录数量，不是已评估样本统计；本批不提供跨合成/真实样本混合的总胜率或排名。退出码：成功/普通查询 0；not_due/awaiting_observation 1；输入、冲突、损坏或本地错误 2。

## 存储与边界

文件位于 workspace/forecasts/records 和 forecasts/evaluations。只读查询缺目录时不初始化；注册和正式评估复用工作区 pipeline.lock，与业务写入和备份屏障互斥。原子发布使用临时文件和不可覆盖硬链接；文件系统不支持时明确失败，不降级为覆盖写入。

拒绝 ID 路径穿越、归档目录/文件/锁的符号链接、重解析点及特殊文件。单文件 1 MiB，归档读取最多 1000 条预测、每预测 32 份评估，每次读取预算 16 MiB；大档案需后续索引/分页方案，不无限扫描。检测到结构/摘要损坏会阻断，不跳过后统计。该对象按单次 CLI 操作使用；不要共享同一 ForecastArchive 实例给并发读取线程。

摘要用于识别版本和意外篡改，不阻止同一操作系统用户重写文件并重算全部摘要或修改时钟。合法写入不会覆盖，但本地访问权限仍须由操作者维护。来源和日历未独立认证；没有自动外部适配器或定时评估。

现有加密备份包含这些普通 JSON 文件；隔离恢复保留其字节，只恢复记录，不生成评估或触发 Worker。6B 已提供日常 `run` 与控制台任务 API 的[显式联动](forecast-tasks.md)，使用每次请求提供的定义，将同次预测绑定到报告/邮件；默认不开启。6C 已提供[网页编辑表单和到期列表](forecast-console.md)，观测适配器留待后续。

## 验证记录（2026-11-16）

- 新增32项专项：31通过、1项 Windows 符号链接权限跳过。覆盖周期/DST/声明交易日、事前基准/目标、历史时点、阈值/数值范围、幂等/并发/篡改/路径/限制、CLI闭环和加密备份/隔离恢复。
- 完整回归714项，712通过、2项权限跳过，387.557秒。最后修正十进制阈值边界后，最终专项和基础wheel均再次执行32项，31通过、1项权限跳过。
- 源码目录外使用安装后的实际CLI验证注册、分页查询、show和not_due；通过测试API模拟成熟时钟验证计分。实际CLI不提供绕过当前时间的参数。
- Ruff、compile、命名、目录同步、diff及71个本地文档链接检查通过。无UI改动，未启动真实控制台或浏览器验收服务。
- 真实工作区只读list返回0条归档，不新建归档目录；42个来源文件前后摘要一致。没有导入真实预测/观测、模型调用、采集、SMTP、实际备份恢复或数据库升级。
