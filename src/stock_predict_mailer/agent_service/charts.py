"""Validated time series and a deterministic chart shared by reports and mail."""
from __future__ import annotations

from .contracts import fail, instant, keys, number, string


def chart_data(raw, prediction):
    if raw is None:
        return None
    keys(raw, ("unit", "series"))
    unit = string(raw["unit"])
    series = raw["series"]
    if not isinstance(series, dict) or not series or set(series) - {"observed", "forecast", "backtest"}:
        fail("图表 series 须包含已知序列")
    issued = instant(prediction["generated_at"])
    normalized = {}
    for kind, item in series.items():
        keys(item, ("source", "points"))
        if not isinstance(item["points"], list) or not 1 <= len(item["points"]) <= 120:
            fail("每条图表序列需包含 1 至 120 个点")
        points = []
        for point in item["points"]:
            required = ("at", "value", "issued_at") if kind == "backtest" else ("at", "value")
            keys(point, required, ("lower", "upper") if kind == "forecast" else ())
            at = instant(point["at"])
            if (kind == "forecast") != (at > issued):
                fail("图表时间与预测生成时间不一致")
            value = number(point["value"])
            if abs(value) > 10**12:
                fail("图表值超出范围")
            row = {"at": at.isoformat(), "value": value}
            if kind == "backtest":
                made = instant(point["issued_at"])
                if made >= at:
                    fail("历史预测须早于对应实际值")
                row["issued_at"] = made.isoformat()
            if "lower" in point or "upper" in point:
                lower, upper = number(point.get("lower")), number(point.get("upper"))
                if not -10**12 <= lower <= value <= upper <= 10**12:
                    fail("预测区间须包含预测值")
                row.update(lower=lower, upper=upper)
            points.append(row)
        points.sort(key=lambda point: point["at"])
        if len({point["at"] for point in points}) != len(points):
            fail("图表时间点重复")
        normalized[kind] = {"source": string(item["source"]), "points": points}
    if "forecast" in normalized and "value" in prediction:
        if unit != prediction["value_unit"] or normalized["forecast"]["points"][-1]["value"] != prediction["value"]:
            fail("预测曲线末值及单位须与报告预测一致")
    return {"unit": unit, "series": normalized}


def build_charts(data):
    if not data:
        return [], ["缺少 chart_data.unit 与时间序列，无法绘制预测走势图。"]
    series = data["series"]
    charts, notes = [], []
    trend = {k: series[k] for k in ("observed", "forecast") if k in series}
    if sum(len(s["points"]) for s in trend.values()) >= 2:
        charts.append({"title": "历史观测与预测", "unit": data["unit"], "series": trend,
                       "caption": "展示已提供的历史观测与未来预测点。时间跨度取自输入，预测变化仍受模型与数据限制。"})
    else:
        notes.append("走势至少需要两个观测或预测时间点。")
    if not any("lower" in p for p in series.get("forecast", {}).get("points", [])):
        notes.append("未提供预测点的 lower/upper，未绘制预测区间。")
    actual = {p["at"]: p["value"] for p in series.get("observed", {}).get("points", [])}
    pairs = [p for p in series.get("backtest", {}).get("points", []) if p["at"] in actual]
    if pairs:
        paired = {p["at"] for p in pairs}
        mae = sum(abs(actual[p["at"]] - p["value"]) for p in pairs) / len(pairs)
        charts.append({"title": "实际值与历史预测", "unit": data["unit"],
                       "series": {"observed": {**series["observed"], "points": [p for p in series["observed"]["points"] if p["at"] in paired]},
                                  "backtest": {**series["backtest"], "points": pairs}},
                       "caption": f"同时间点配对 {len(pairs)} 组，平均绝对误差 {mae:.6g} {data['unit']}。结果仅覆盖配对样本。"})
    else:
        notes.append("缺少时间匹配的 observed/backtest，未计算历史预测误差。")
    return charts, notes
