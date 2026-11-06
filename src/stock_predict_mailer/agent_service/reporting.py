"""Readable escaped HTML and plain text from the same structured result."""
from __future__ import annotations

from html import escape
from zoneinfo import ZoneInfo

from ..core import atomic_write, write_json
from .charts import chart_svg
from .contracts import instant


def render(analysis, timezone="Asia/Shanghai", *, charts="inline"):
    p = analysis["prediction"]
    time = instant(p["generated_at"]).astimezone(ZoneInfo(timezone)).isoformat()
    lines = ["预测分析报告" + (" [MOCK 合成演示]" if p["synthetic"] else ""),
             f"状态：{analysis['status']}；分析模式：{analysis['mode']}", f"预测对象：{p['subject']}；时间：{time}",
             f"模型版本：{p['model_version']}；周期：{p['horizon']['value']} {p['horizon']['unit']}",
             "模型预测", f"方向：{p.get('direction', '未提供')}；数值：{p.get('value', '未提供')} {p.get('value_unit', '')}",
             f"置信度（上游）：{p['confidence'] if p['confidence'] is not None else '未提供'}",
             f"相关指标（上游）：{p['metrics']}", "客观数据（上游声明，未独立核实）"]
    lines += [f"[{f['id']}] {f['name']}：{f['value']} {f['unit']}；来源：{f['source']}；观测：{f['observed_at']}；可用：{f['available_at']}"
              for f in analysis["facts"]] or ["无可用上下文。"]
    lines += ["Agent 推断"] + [f"{i['text']}（依据：{', '.join(i['evidence_ids'])}）" for i in analysis["inferences"]]
    if analysis.get("user_constraints"):
        lines += ["本轮用户约束", *analysis["user_constraints"]]
    for title, key in (("不确定性与限制", "limitations"), ("风险提示", "risks"), ("建议（不作收益保证）", "recommendations")):
        lines += [title] + analysis[key]
    figures = analysis.get("charts", [])
    text = "\n\n".join(lines + [f"{chart['title']}：{chart['caption']}" for chart in figures])
    html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>预测分析报告</title><body>'
    html += "".join(f"<p>{escape(line)}</p>" for line in lines)
    for idx, chart in enumerate(figures):
        visual = chart_svg(chart) if charts == "inline" else f'<img src="cid:chart-{idx}@stock-predict-mailer.local" alt="{escape(chart["title"])}">' if charts == "cid" else ""
        html += f"<figure><h2>{escape(chart['title'])}</h2>{visual}<figcaption>{escape(chart['caption'])}</figcaption></figure>"
    return text, html + "</body></html>"


def save_report(workspace, analysis, timezone="Asia/Shanghai"):
    folder = workspace / "analysis" / analysis["analysis_id"]
    write_json(folder / "analysis.json", analysis)
    _, html = render(analysis, timezone)
    atomic_write(folder / "report.html", html.encode())
    return folder
