"""Standalone report pages rendered from the existing validated analysis."""
from html import escape

from ..contract import declare
from .report import html_figures, lines

STYLE = """<style>
*{box-sizing:border-box}body{margin:0;padding:clamp(14px,4vw,48px);font:15px/1.65 system-ui,sans-serif;background:#edf3f1;color:#183638}
main{max-width:1040px;margin:auto}header,section,figure{background:#fff;border:1px solid #d8e3df;border-radius:14px;padding:clamp(14px,3vw,27px);margin:0 0 16px}
header{border-top:5px solid #17634d}h1,h2{line-height:1.3;margin:0 0 12px}p{margin:0 0 8px;overflow-wrap:anywhere}
dl{margin:12px 0 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px}dt{color:#435951;font-size:13px}dd{margin:2px 0;overflow-wrap:anywhere}
svg,img{display:block;max-width:100%;height:auto}figcaption{color:#435951;margin-top:8px}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{text-align:left;padding:8px;border-bottom:1px solid #d8e3df;overflow-wrap:anywhere}th{font-size:13px}
</style>"""


def _document(view, title, opening):
    analysis = view["analysis"]
    prediction = analysis["prediction"]
    subject = escape(prediction["subject"])
    marker = '<p>合成演示数据</p>' if prediction["synthetic"] else ''
    details = "".join(f"<p>{escape(line)}</p>" for line in lines(analysis, view["timezone"]))
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{title}</title>{STYLE}<body class="rendered-report-page"><main><header><h1>{subject} · {title}</h1>{marker}'
            f'{opening}</header>{html_figures(analysis, view["charts"], color_labels=False)}'
            f'<section><h2>完整分析报告</h2>{details}</section></main></body></html>').encode("utf-8")


class DashboardPage:
    manifest = declare(id="report_dashboard", kind="report_renderer", label="分析概览页", capabilities=("html",))

    @staticmethod
    def render(view):
        analysis = view["analysis"]
        prediction = analysis["prediction"]
        stats = [("上游模型", prediction["model_version"]), ("事实记录", len(analysis["facts"])),
                 ("生成图表", len(analysis.get("charts", [])))]
        opening = "<dl>" + "".join(f"<div><dt>{label}</dt><dd>{escape(str(value))}</dd></div>" for label, value in stats) + "</dl>"
        return _document(view, "分析概览", opening)


class EvidencePage:
    manifest = declare(id="report_evidence", kind="report_renderer", label="来源核对页", capabilities=("html",))

    @staticmethod
    def render(view):
        facts = view["analysis"]["facts"]
        rows = "".join("<tr>" + "".join(f"<td>{escape(str(fact[key]))}</td>" for key in
                                        ("name", "source", "observed_at")) + "</tr>" for fact in facts)
        opening = ('<h2>客观事实来源</h2><p>来源由上游声明，未经独立核实。</p>'
                   '<table><thead><tr><th>事实</th><th>来源</th><th>观测时间</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table>') if rows else '<p>本轮没有可展示的客观事实。</p>'
        return _document(view, "来源核对", opening)
