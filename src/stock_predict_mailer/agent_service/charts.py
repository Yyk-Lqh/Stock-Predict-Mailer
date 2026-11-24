"""Validated time series and a deterministic chart shared by reports and mail."""
from __future__ import annotations

from html import escape

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


def chart_svg(chart):
    from ..plugins.registry import resolve

    return resolve(chart.get("renderer", "chart_line"), "chart_renderer").render(chart)


def chart_geometry(points, *, bars=False):
    times = [instant(p["at"]).timestamp() for p in points]
    values = [v for p in points for v in (p["value"], p.get("lower", p["value"]), p.get("upper", p["value"]))]
    start, end, low, high = min(times), max(times), min(values), max(values)
    if bars:
        low, high = min(0, low), max(0, high)
    inset = 24 if bars else 0
    def x(at):
        ratio = (instant(at).timestamp() - start) / (end - start) if end != start else .5
        return 72 + inset + (590 - 2 * inset) * ratio
    def y(value):
        return 232 - 174 * ((value - low) / (high - low) if high != low else .5)
    return x, y, low, high


def bar_width(points, x, series_count):
    positions = sorted({x(p["at"]) for p in points})
    spacing = min((b - a for a, b in zip(positions, positions[1:], strict=False)), default=590)
    return min(15, spacing / (series_count + 1))


def render_svg(chart, *, bars=False):
    """Render only server-built chart data. Labels are escaped, never interpreted as markup."""
    palette = {"observed": ("历史观测", "#17634d"), "forecast": ("模型预测", "#2356a3"),
               "backtest": ("历史预测", "#a64b29")}
    points = [p for s in chart["series"].values() for p in s["points"]]
    x, y, low, high = chart_geometry(points, bars=bars)
    def label(px, py, value):
        return f'<text x="{px}" y="{py}">{escape(str(value))}</text>'
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 350" width="720" height="350" role="img">',
           '<rect width="720" height="350" fill="white"/>',
           '<g font-family="sans-serif" font-size="12" fill="#183638">', label(24, 24, chart["title"]),
           '<path d="M72 55V232H662" fill="none" stroke="#829392"/>',
           label(24, 47, chart["unit"]), label(5, 65, f"{high:.5g}"), label(5, 230, f"{low:.5g}"),
           label(72, 250, min(p["at"] for p in points)[:16] + " UTC"),
           label(505, 250, max(p["at"] for p in points)[:16] + " UTC")]
    if bars:
        series_count = len(chart["series"])
        width = bar_width(points, x, series_count)
        baseline = y(0)
        svg.append(f'<path d="M72 {baseline:.2f}H662" fill="none" stroke="#829392"/>')
    for idx, (kind, series) in enumerate(chart["series"].items()):
        name, color = palette[kind]
        offset = (idx - (series_count - 1) / 2) * width if bars else 0
        coords = [(x(p["at"]) + offset, y(p["value"])) for p in series["points"]]
        dash = ' stroke-dasharray="5 3"' if kind != "observed" else ""
        intervals = [f'<path d="M{px:.2f} {y(point["lower"]):.2f}V{y(point["upper"]):.2f}" stroke="#88b2ec" stroke-width="{4 if bars else 6}"/>'
                     for point, (px, _) in zip(series["points"], coords, strict=True) if "lower" in point]
        if bars:
            svg.extend(f'<rect x="{px - width * .4:.2f}" y="{min(py, baseline):.2f}" '
                       f'width="{width * .8:.4f}" height="{abs(py - baseline):.2f}" fill="{color}"/>' for px, py in coords)
            svg.extend(intervals)
        else:
            svg.extend(intervals)
            xy = " ".join(f"{px:.2f},{py:.2f}" for px, py in coords)
            svg.append(f'<polyline points="{xy}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')
            svg.extend(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="3" fill="{color}"/>' for px, py in coords)
        py = 272 + idx * 18
        svg.append(f'<path d="M24 {py - 4}h14" stroke="{color}" stroke-width="3"{dash}/>')
        svg.append(label(45, py, f"{name} · {series['source'][:90]}"))
    if any("lower" in p for p in points):
        svg.append(label(45, 332, "浅蓝竖线：上游预测区间"))
    return "".join(svg) + "</g></svg>"
