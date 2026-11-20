"""Built-in report formatters: one content builder, two output formats.

The sentence list is the shared part; escaping, chart SVG and mail-safe image
references are the per-format part. A renderer decides how the report reads,
never what it says — the analysis contract stays the only source of content.
"""
from __future__ import annotations

from html import escape
from zoneinfo import ZoneInfo

from ...agent_service.charts import chart_svg
from ...agent_service.contracts import instant
from ...agent_service.input_evidence import fingerprint
from ..contract import declare

LEGEND = {"observed": ("历史观测", "#17634d"), "forecast": ("模型预测", "#2356a3"),
          "backtest": ("历史预测", "#a64b29")}


def lines(analysis, timezone):
    """Ordered sentences shared by every format; no markup, no escaping."""
    p = analysis["prediction"]
    time = instant(p["generated_at"]).astimezone(ZoneInfo(timezone)).isoformat()
    result = ["预测分析报告" + (" [MOCK 合成演示]" if p["synthetic"] else ""),
              f"状态：{analysis['status']}；分析模式：{analysis['mode']}", f"预测对象：{p['subject']}；时间：{time}",
              f"模型版本：{p['model_version']}；周期：{p['horizon']['value']} {p['horizon']['unit']}",
              "模型预测", f"方向：{p.get('direction', '未提供')}；数值：{p.get('value', '未提供')} {p.get('value_unit', '')}",
              f"置信度（上游）：{p['confidence'] if p['confidence'] is not None else '未提供'}",
              f"相关指标（上游）：{p['metrics']}", "客观数据（上游声明，未独立核实）"]
    result += [f"[{f['id']}] {f['name']}：{f['value']} {f['unit']}；来源：{f['source']}；观测：{f['observed_at']}；"
               f"可用：{f['available_at']}" for f in analysis["facts"]] or ["无可用上下文。"]
    result += ["Agent 推断"] + [f"{i['text']}（依据：{', '.join(i['evidence_ids'])}）" for i in analysis["inferences"]]
    if analysis.get("forecast_evidence"):
        evidence = analysis["forecast_evidence"]
        d, r = evidence["definition"], evidence["definition"]["reference"]
        result += ["事前预测归档与评价定义", f"预测归档 ID：{evidence['forecast_id']}；注册：{evidence['registered_at']}",
                   f"目标时点：{d['target_at']}；时区：{d['timezone']}；指标：{d['metric']}；单位：{d['unit']}",
                   f"比较基准：{r['value']} {d['unit']}；来源声明：{r['source']}；观测：{r['observed_at']}；可用：{r['available_at']}",
                   f"平盘阈值（含边界）：{d['flat_tolerance']} {d['unit']}",
                   f"预测与定义内容摘要：{evidence['content_id']}；注册记录摘要：{evidence['integrity_id']}",
                   "此报告仅包含事前定义，未读取事后观测或评估结果；摘要不代表来源认证。"]
        if "calendar" in d:
            result += [f"交易日历声明来源：{d['calendar']['source']}；后续交易日：{', '.join(d['calendar']['sessions'])}"]
    if analysis.get("user_constraints"):
        result += ["本轮用户约束", *analysis["user_constraints"]]
    for title, key in (("不确定性与限制", "limitations"), ("风险提示", "risks"), ("建议（不作收益保证）", "recommendations")):
        result += [title] + analysis[key]
    if analysis.get("input_evidence"):
        evidence = analysis["input_evidence"]
        snapshot = evidence["snapshot"]
        source = snapshot["source"]
        result += ["输入快照与来源追溯（摘要不代表来源认证）", f"快照 ID：{evidence['snapshot_id']}",
                   f"上游预测 ID：{snapshot['prediction']['prediction_id']}；预测内容摘要：{fingerprint(snapshot['prediction'])}",
                   f"上下文摘要：{fingerprint(snapshot['context'])}",
                   f"来源文件：{source['filename']}；CSV SHA256：{source['csv_sha256']}",
                   f"来源元数据内容摘要：{source['metadata_sha256']}；原始行摘要：{fingerprint(source['record'])}"]
        for fact in analysis["facts"]:
            result += [f"[{fact['id']}] 来源行：{source['row_number']}；字段：{source['fact_fields'][fact['id']]}；"
                       f"报告期：{source['record']['report_date']}；披露日：{source['record']['pub_date']}；"
                       f"原始采集时间：{source['record']['collected_at']}"]
    evidence = analysis.get("knowledge_evidence")
    if evidence:
        result += ["私有资料证据（来源声明，未独立核实）", "资料截止：" + evidence["as_of"]]
        for item in evidence["results"]:
            result += [f"[{item['citation_id']}] {item['filename']}；位置：{item['location']}；"
                       f"版本校验：{item['source_hash']}；日期：{item['metadata']}",
                       item["text"], "；".join(item["warnings"]) or "来源内容需核实"]
    if analysis.get("report_format") == "brief":
        headline = ["简版摘要", f"{p['subject']} · {p['horizon']['value']} {p['horizon']['unit']}",
                    *[item["text"] for item in analysis["inferences"]], "完整依据与风险见下方。"]
        result = headline + result
    return result


def _chart_labels(chart):
    labels = "".join(f'<p style="color:{LEGEND[key][1]}">{LEGEND[key][0]} · {escape(series["source"])}</p>'
                     for key, series in chart["series"].items())
    points = [p for series in chart["series"].values() for p in series["points"]]
    labels += f'<p>单位：{escape(chart["unit"])}；{escape(min(p["at"] for p in points))} — {escape(max(p["at"] for p in points))}</p>'
    if any("lower" in p for p in points):
        labels += "<p>浅蓝竖线：上游预测区间</p>"
    return labels


class TextReport:
    manifest = declare(id="report_text", kind="report_renderer", label="纯文本报告", capabilities=("text",))

    @staticmethod
    def render(view):
        analysis, timezone = view["analysis"], view["timezone"]
        figures = analysis.get("charts", [])
        text = "\n\n".join(lines(analysis, timezone) + [f"{chart['title']}：{chart['caption']}" for chart in figures])
        return text.encode("utf-8")


class HtmlReport:
    manifest = declare(id="report_html", kind="report_renderer", label="HTML 报告", capabilities=("html",))

    @staticmethod
    def render(view):
        analysis, timezone, charts = view["analysis"], view["timezone"], view["charts"]
        html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>预测分析报告</title><body>'
        html += "".join(f"<p>{escape(line)}</p>" for line in lines(analysis, timezone))
        for idx, chart in enumerate(analysis.get("charts", [])):
            visual = (chart_svg(chart) if charts == "inline"
                      else f'<img src="cid:chart-{idx}@stock-predict-mailer.local" alt="{escape(chart["title"])}">'
                      if charts == "cid" else "")
            html += (f"<figure><h2>{escape(chart['title'])}</h2>{visual}"
                     f"<figcaption>{escape(chart['caption'])}{_chart_labels(chart)}</figcaption></figure>")
        return (html + "</body></html>").encode("utf-8")
