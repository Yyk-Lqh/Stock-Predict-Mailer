"""Grounded analysis: external agents select evidence and bounded conclusions."""
from __future__ import annotations

import json

from ..core import digest
from .adapters import http_json
from .contracts import ServiceError, context, fail, keys, prediction

INFERENCES = {
    "MODEL_UP": "模型方向为上行；这不是收益保证，也不能据此判断上涨概率。",
    "MODEL_DOWN": "模型方向为下行；需关注回撤风险，不能据此判断下跌概率。",
    "MODEL_FLAT": "模型方向为持平；仍可能出现显著波动。",
    "INSUFFICIENT": "现有信息不足以解释价格变化原因或评估预测可靠性。",
}
RECOMMENDATIONS = {
    "VERIFY": "核对模型适用范围、数据时效及独立资料后再作决策。",
    "DIVERSIFY": "结合个人风险承受能力评估集中持仓风险。",
    "WAIT": "在补充证据前避免仅凭单次预测采取行动。",
}


def identity(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


class AnalysisAgent:
    def __init__(self, settings=None):
        self.settings = settings or {}

    def analyze(self, raw_prediction, raw_context=None):
        p = prediction(raw_prediction, max_age=self.settings.get("max_age_seconds", 86400))
        c = context(raw_context, p["subject"], max_age=self.settings.get("max_context_age_seconds", 86400))
        facts = c["facts"] if c else []
        direction_code = "MODEL_" + p["direction"].upper() if "direction" in p else "INSUFFICIENT"
        selected = {"evidence_ids": [f["id"] for f in facts], "inference_codes": [direction_code],
                    "recommendation_codes": ["VERIFY", "WAIT"]}
        limitations = []
        if not facts:
            limitations.append("未提供客观上下文，无法解释预测原因或交叉验证模型结果。")
        if p["confidence"] is None:
            limitations.append("上游未提供置信度，未作估计。")
        else:
            limitations.append("置信度由上游提供，其校准方法尚未独立验证，不能直接理解为收益概率。")
        status, mode = "ok", "deterministic_no_llm"
        if self.settings.get("provider", "deterministic") == "http":
            try:
                selected = http_json(self.settings["url"], payload={"prediction": p, "context": c},
                                     timeout=self.settings.get("timeout_seconds", 15), token_env=self.settings.get("token_env", ""))
                keys(selected, ("evidence_ids", "inference_codes", "recommendation_codes"))
                for field, allowed in (("evidence_ids", [f["id"] for f in facts]),
                                       ("inference_codes", [direction_code, "INSUFFICIENT"]),
                                       ("recommendation_codes", RECOMMENDATIONS)):
                    values = selected[field]
                    if not isinstance(values, list) or any(not isinstance(v, str) or v not in allowed for v in values):
                        fail("Agent 返回了无依据的内容")
                if not selected["inference_codes"] or not selected["recommendation_codes"]:
                    fail("Agent 返回空分析")
                mode = "http_bounded_agent"
            except ServiceError as exc:
                selected = {"evidence_ids": [f["id"] for f in facts], "inference_codes": [direction_code],
                            "recommendation_codes": ["VERIFY", "WAIT"]}
                status = "degraded"
                code = "AGENT_UNAVAILABLE" if exc.code == "UPSTREAM_UNAVAILABLE" else "AGENT_INVALID"
                limitations.append(f"{code}：Agent 调用失败或响应不合规，已降级为确定性分析。")
        result = {"schema_version": "1", "generated_at": p["generated_at"], "status": status, "mode": mode,
                  "prediction": p, "facts": facts,
                  "inferences": [{"code": code, "text": INFERENCES[code], "evidence_ids": ["prediction:" + p["prediction_id"]]}
                                 for code in selected["inference_codes"]],
                  "recommendations": [RECOMMENDATIONS[code] for code in selected["recommendation_codes"]],
                  "limitations": limitations,
                  "risks": ["股票价格存在波动与损失风险；历史或模型表现不代表未来收益。",
                            "合成演示结果不能作为真实投资依据。" if p["synthetic"] else "模型可能存在偏差、分布漂移及未覆盖的市场风险。"]}
        # Selected facts remain visible as objective data; no causal claim is generated from them.
        result["facts"] = [f for f in facts if f["id"] in selected["evidence_ids"]]
        if facts and not result["facts"]:
            result["limitations"].append("Agent 未选取可用于交叉验证的上下文证据。")
        result["analysis_id"] = identity(result)
        return result


def validate_analysis(value, settings=None):
    settings = settings or {}
    keys(value, ("schema_version", "analysis_id", "generated_at", "status", "mode", "prediction", "facts", "inferences",
                 "recommendations", "limitations", "risks"))
    unsigned = {k: v for k, v in value.items() if k != "analysis_id"}
    if identity(unsigned) != value["analysis_id"] or value["schema_version"] != "1" or value["status"] not in ("ok", "degraded"):
        fail("分析摘要、版本或状态无效")
    prediction(value["prediction"], max_age=settings.get("max_age_seconds", 86400))
    context({"schema_version": "1", "context_id": "analysis", "subject": value["prediction"]["subject"], "facts": value["facts"]},
            value["prediction"]["subject"], max_age=settings.get("max_context_age_seconds", 86400))
    if value["generated_at"] != value["prediction"]["generated_at"] or value["mode"] not in ("deterministic_no_llm", "http_bounded_agent", "orchestrated_bounded"):
        fail("分析时间或模式无效")
    for field in ("inferences", "recommendations", "limitations", "risks"):
        if not isinstance(value[field], list):
            fail("分析输出字段必须为数组")
    for item in value["inferences"]:
        keys(item, ("code", "text", "evidence_ids"))
        code = item["code"]
        expected = "MODEL_" + value["prediction"].get("direction", "").upper()
        if code not in (expected, "INSUFFICIENT") or item["text"] != INFERENCES.get(code):
            fail("分析推断与预测不一致")
        if item["evidence_ids"] != ["prediction:" + value["prediction"]["prediction_id"]]:
            fail("分析依据不匹配")
    if any(v not in RECOMMENDATIONS.values() for v in value["recommendations"]):
        fail("分析建议不合规")
    if not value["inferences"] or not value["recommendations"] or not value["risks"]:
        fail("分析缺少推断、建议或风险")
    for field in ("recommendations", "limitations", "risks"):
        if any(not isinstance(v, str) or not v.strip() for v in value[field]):
            fail("分析文本无效")
    return value
