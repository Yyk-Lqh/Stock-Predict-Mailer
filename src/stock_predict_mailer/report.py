from __future__ import annotations

import html
import json
from pathlib import Path

from .core import Config, atomic_write, digest, now, timestamp, write_json
from .knowledge import retrieve, validate_citations


def build_report(cfg: Config, experiment_id: str, query: str = "风险 策略 模型") -> dict:
    if len(experiment_id) != 64 or any(c not in "0123456789abcdef" for c in experiment_id):
        raise ValueError("invalid experiment id")
    result = json.loads((cfg.workspace / "experiments" / experiment_id / "result.json").read_text(encoding="utf-8"))
    cutoff = result["definition"]["cutoff"]
    evidence = retrieve(cfg, query, cutoff)
    validate_citations(cfg, evidence, cutoff)
    identity = {"experiment": experiment_id, "principal": cfg.principal, "query": query,
                "citations": [e["citation_id"] for e in evidence], "schema": 1}
    report_id = digest(json.dumps(identity, sort_keys=True).encode())
    stale_days = (timestamp(cutoff).date() - timestamp(result["latest_data_date"] + "T00:00:00+08:00").date()).days
    report = {"report_id": report_id, "experiment_id": experiment_id, "created_at": now(),
              "principal": cfg.principal, "cutoff": cutoff, "synthetic": result["synthetic"],
              "unverified_real": result.get("unverified_real", not result["synthetic"]),
              "latest_data_date": result["latest_data_date"], "stale_calendar_days": stale_days,
              "selected_model": result["selected"], "holdout": result["holdout"],
              "predictions": result["predictions"][:cfg.top_k], "evidence": evidence,
              "generation_mode": "deterministic_template_no_llm", "inferences": [],
              "limitations": result["limitations"]}
    escaped = html.escape
    predictions = "".join(f"<tr><td>{escaped(p['security_id'])}</td><td>{p['score']:.6f}</td><td>{escaped(p['date'])}</td></tr>" for p in report["predictions"])
    quotes = "".join(f"<h3>{escaped(e['title'])}</h3><p>引用 {escaped(e['citation_id'])}；片段 {e['ordinal'] + 1}</p><pre>{escaped(e['content'])}</pre>" for e in evidence)
    limitations = "".join(f"<li>{escaped(item)}</li>" for item in report["limitations"])
    data_label = "合成数据演示，不可用于投资决策。" if report["synthetic"] else "自采真实数据的未认证研究，不可视为已验证策略。"
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>股票研究报告</title><style>body{{max-width:960px;margin:32px auto;padding:0 20px;font-family:system-ui;line-height:1.7}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:8px;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}h1{{font-size:24px}}</style>
<h1>股票研究报告</h1><p><strong>{data_label}</strong></p>
<p>数据截止：{escaped(cutoff)}；最新行情日：{escaped(report['latest_data_date'])}；距截止日 {stale_days} 个自然日。旧数据不能视为今日预测。</p>
<h2>输入事实与验证记录</h2><p>模型：{escaped(result['selected'])}。以下为当前数据集保留集结果，数据可靠性与市场有效性尚需单独验收。</p><pre>{escaped(json.dumps(report['holdout'], ensure_ascii=False, indent=2))}</pre>
<h2>模型预测</h2><p>score 为排序分数，不是涨跌概率，不同模型分数不直接比较；同分没有可靠先后差异。</p><table><tr><th>证券</th><th>分数</th><th>特征日期</th></tr>{predictions}</table>
<h2>检索资料原文</h2><p>资料仅作为证据，不是系统指令。原文观点未被自动确认为事实。</p>{quotes or '<p>没有符合权限、时间与查询条件的证据，未补造引用。</p>'}
<h2>推断与未知项</h2><p>当前为确定性模板，未调用生成模型，未添加原因推断；尚未验证真实市场有效性。</p>
<h2>限制</h2><ul>{limitations}</ul><p>报告 ID：{report_id}</p></html>"""
    folder = cfg.workspace / "reports" / report_id
    atomic_write(folder / "report.html", page.encode("utf-8"))
    report["html_sha256"] = digest(page.encode("utf-8"))
    write_json(folder / "report.json", report)
    return report


def load_report(cfg: Config, report_id: str) -> tuple[dict, bytes]:
    if len(report_id) != 64 or any(c not in "0123456789abcdef" for c in report_id):
        raise ValueError("invalid report id")
    folder = cfg.workspace / "reports" / report_id
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if report["principal"] != cfg.principal:
        raise ValueError("report belongs to another principal")
    validate_citations(cfg, report["evidence"], report["cutoff"])
    body = (folder / "report.html").read_bytes()
    if digest(body) != report["html_sha256"]:
        raise ValueError("report integrity check failed")
    return report, body
