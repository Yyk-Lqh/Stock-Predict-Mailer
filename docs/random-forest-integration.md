# 随机森林接入

`predict-rf` 读取训练方交付的随机森林和一只股票的月频特征，导出已有的 v1 预测 JSON。CLI 使用原有 `file` 适配器读取结果，分析工作台通过「分析资料 → 预测 → 导入上游预测 JSON」读取同一文件。模型加载限定为已交付的 SHA-256 文件，使用锁定的 scikit-learn 1.9.1。

默认模型为 [random_forest_monthly.pkl](../src/数据面/random_forest_monthly.pkl)。[训练脚本](../src/数据面/train_random_forest.py) 将重新训练的模型保存为 `random_forest_monthly_candidate.pkl`，以便与交付模型区分。

从仓库根目录运行示例：

```powershell
uv run --locked --extra research stock-predict-mailer predict-rf --features examples/rf-features.json --output data/agent-rf-local/prediction.json
uv run --locked stock-predict-mailer --config config/agent-rf-example.toml run
```

示例使用合成特征，报告走本地文件投递配置。接入实盘时，由数据面提供与训练一致的九列有限数值、标的、特征截面日期 `as_of`，并标记 `synthetic: false`。字段模板见 [rf-features.json](../examples/rf-features.json)。估值和财务分位需要在同一截面股票池中计算，财务因子须沿用训练脚本的公告日对齐口径。已同步的仓库尚缺训练脚本引用的量价及财务 CSV，因此当前验证使用合成特征。

模型分数对应特征月份的下一月，表示该股在同一股票池的下月收益排名进入前 30% 的模型概率。v1 使用 `value` 和 `value_unit` 保存分数及口径，`confidence` 留空。`horizon` 用目标月的日数表达月频周期，`target_month_yyyymm` 标注具体目标月。报告会保留特征日期、模型版本和合成标记。超过有效期或目标月已结束的实盘输入应重新生成。
