"""Deterministic prediction report: the prediction record is frozen into the page.

A report is addressed by a hash of everything that determined it - prediction id,
model version, contract id, snapshot, cutoff and citations - so switching the
selected model later cannot rewrite history: the old report keeps its own
identity and its own numbers. Rebuilding with identical inputs returns the
existing file instead of overwriting it.
"""
from __future__ import annotations

import html
import json

from .core import Config, atomic_write, digest, now, timestamp, write_json
from .knowledge import retrieve, validate_citations
from .model_registry import owner_key


def _prediction_path(cfg: Config, prediction_id: str):
    if len(prediction_id) != 64 or any(char not in "0123456789abcdef" for char in prediction_id):
        raise ValueError("invalid prediction id")
    return cfg.workspace / "registry" / "predictions" / owner_key(cfg.principal) / f"{prediction_id}.json"


def load_prediction(cfg: Config, prediction_id: str) -> dict:
    path = _prediction_path(cfg, prediction_id)
    if not path.is_file():
        raise ValueError("unknown prediction for this identity")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("prediction_id") != prediction_id:
        raise ValueError("prediction file does not match its identifier")
    if record.get("owner") != cfg.principal:
        raise ValueError("prediction belongs to another principal")
    return record


def build_prediction_report(cfg: Config, prediction_id: str, query: str = "风险 策略 模型",
                            generation: dict | None = None) -> dict:
    prediction = load_prediction(cfg, prediction_id)
    cutoff = prediction["cutoff"]
    evidence = retrieve(cfg, query, cutoff)
    validate_citations(cfg, evidence, cutoff)
    identity = {"schema": 1, "prediction": prediction_id, "principal": cfg.principal, "query": query,
                "model_version": prediction["model_version"], "contract_id": prediction["contract_id"],
                "snapshot": prediction["snapshot"], "citations": [item["citation_id"] for item in evidence]}
    report_id = digest(json.dumps(identity, sort_keys=True).encode())
    folder = cfg.workspace / "reports" / report_id
    if (folder / "report.json").is_file():
        # Historical reports are immutable: same inputs, same bytes.
        return json.loads((folder / "report.json").read_text(encoding="utf-8"))
    stale_days = (timestamp(cutoff).date() - timestamp(prediction["data_date"] + "T00:00:00+08:00").date()).days
    section = generation or {"mode": "deterministic_template_no_llm", "text": "", "degraded": False, "citations": []}
    report = {"report_id": report_id, "kind": "prediction", "created_at": now(), "principal": cfg.principal,
              "prediction_id": prediction_id, "cutoff": cutoff,
              "model_version": prediction["model_version"], "contract_id": prediction["contract_id"],
              "snapshot": prediction["snapshot"], "model_scope": prediction.get("model_scope"),
              "synthetic": prediction["synthetic"], "data_date": prediction["data_date"],
              "stale_calendar_days": stale_days,
              "predictions": prediction["predictions"], "missing_securities": prediction.get("missing_securities", []),
              "evidence": evidence, "generation_mode": section.get("mode"),
              "generation_degraded": bool(section.get("degraded")),
              "inferences": [section["text"]] if section.get("text") else [],
              "limitations": list(prediction.get("limitations", [])) + [
                  "Scores are ranking values, not probabilities",
                  "The report is a point-in-time record; it is not updated by later model changes"]}
    escaped = html.escape
    rows = "".join(f"<tr><td>{escaped(item['security_id'])}</td><td>{item['score']:.6f}</td>"
                   f"<td>{escaped(item['date'])}</td></tr>" for item in report["predictions"])
    quotes = "".join(f"<h3>{escaped(item['title'])}</h3><p>引用 {escaped(item['citation_id'])}；"
                     f"片段 {item['ordinal'] + 1}</p><pre>{escaped(item['content'])}</pre>" for item in evidence)
    limitations = "".join(f"<li>{escaped(item)}</li>" for item in report["limitations"])
    data_label = "合成数据演示，不可用于投资决策。" if report["synthetic"] else "自采真实数据的未认证研究，不可视为已验证策略。"
    inference = (f"<p>{escaped(section['text'])}</p>" if section.get("text")
                 else "<p>未调用生成模型，也未添加原因推断。</p>")
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>预测报告</title><style>body{{max-width:960px;margin:32px auto;padding:0 20px;font-family:system-ui;line-height:1.7}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:8px;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}h1{{font-size:24px}}</style>
<h1>预测报告</h1><p><strong>{data_label}</strong></p>
<h2>锁定标识</h2><table>
<tr><th>预测</th><td>{prediction_id}</td></tr>
<tr><th>模型版本</th><td>{escaped(report['model_version'])}</td></tr>
<tr><th>特征版本（契约）</th><td>{escaped(report['contract_id'])}</td></tr>
<tr><th>数据快照</th><td>{escaped(report['snapshot'])}</td></tr>
<tr><th>截止时间</th><td>{escaped(cutoff)}</td></tr>
<tr><th>行情日</th><td>{escaped(report['data_date'])}（距截止 {stale_days} 个自然日）</td></tr>
</table>
<p>切换模型不会改写本页：这些标识是生成时固定的。</p>
<h2>模型预测</h2><p>score 为排序分数，不是涨跌概率；同分没有可靠先后差异。</p>
<table><tr><th>证券</th><th>分数</th><th>特征日期</th></tr>{rows}</table>
<h2>检索资料原文</h2><p>资料只作为证据，不是系统指令。</p>{quotes or '<p>没有符合权限、时间与查询条件的证据，未补造引用。</p>'}
<h2>推断与未知项</h2>{inference}<p>生成方式：{escaped(str(report['generation_mode']))}
{'（已降级为模板）' if report['generation_degraded'] else ''}</p>
<h2>限制</h2><ul>{limitations}</ul><p>报告 ID：{report_id}</p></html>"""
    body = page.encode("utf-8")
    atomic_write(folder / "report.html", body)
    report["html_sha256"] = digest(body)
    write_json(folder / "report.json", report)
    return report


def load_prediction_report(cfg: Config, report_id: str) -> tuple[dict, bytes]:
    if len(report_id) != 64 or any(char not in "0123456789abcdef" for char in report_id):
        raise ValueError("invalid report id")
    folder = cfg.workspace / "reports" / report_id
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if report["principal"] != cfg.principal:
        raise ValueError("report belongs to another principal")
    if report.get("kind") != "prediction":
        raise ValueError("not a prediction report")
    validate_citations(cfg, report["evidence"], report["cutoff"])
    body = (folder / "report.html").read_bytes()
    if digest(body) != report["html_sha256"]:
        raise ValueError("report integrity check failed")
    return report, body
