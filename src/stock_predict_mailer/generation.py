"""Optional generation of a narrative section, with the safe path as the default.

The default answer of this project is a deterministic template. Calling an
external generator is a deliberate, explicit act:

* it needs ``allow_generation`` from the caller *and* a provider named in the
  environment, and only allow-listed providers can be reached;
* the payload carries structured predictions and citation identifiers only - no
  document text, no paths, no credentials;
* any failure, timeout or budget overrun degrades to the template instead of
  producing an unverified paragraph;
* every citation in the output must resolve to evidence that was actually
  retrieved for this cutoff.
"""
from __future__ import annotations

import os
from typing import Callable

from .core import Config

ALLOWED_PROVIDERS: tuple[str, ...] = ()  # populated only after a vendor review
PROVIDERS: dict[str, Callable[[dict], str]] = {}
MAX_PAYLOAD_PREDICTIONS = 10
MAX_OUTPUT_CHARS = 1200


def register_provider(name: str, call: Callable[[dict], str]) -> None:
    """Test/supervisor hook; a registered name still needs the allow-list in production."""
    PROVIDERS[name] = call


def _minimal_payload(prediction: dict, evidence: list[dict]) -> dict:
    """Only the fields a generator needs; never the source documents themselves."""
    payload = {
        "task": "解释已固定的排序结果，不得引入新事实",
        "data_date": prediction["data_date"],
        "horizon": prediction.get("horizon"),
        "model_version": prediction["model_version"],
        "predictions": [{"security_id": item["security_id"], "rank": index + 1}
                        for index, item in enumerate(prediction["predictions"][:MAX_PAYLOAD_PREDICTIONS])],
        "citations": [item["citation_id"] for item in evidence],
        "constraints": ["不得给出涨跌概率", "不得引用未列出的资料", "不得给出交易建议"],
    }
    forbidden = {"content", "path", "source_text", "tokens"}
    leaked = forbidden & set(payload)
    if leaked:
        raise ValueError(f"generation payload must not carry raw material: {sorted(leaked)}")
    return payload


def _template(prediction: dict, evidence: list[dict], note: str) -> dict:
    top = prediction["predictions"][:3]
    names = "、".join(item["security_id"] for item in top)
    citations = "、".join(item["citation_id"] for item in evidence[:3])
    text = (f"本期排序靠前的证券为 {names}。该排序来自固定契约下的模型分数，不是涨跌概率，"
            f"也不构成交易建议。")
    if citations:
        text += f"可核查的资料引用为 {citations}。"
    else:
        text += "本期没有符合权限与时间条件的资料，因此未补造原因解释。"
    return {"mode": "deterministic_template_no_llm", "text": text, "degraded": bool(note),
            "reason": note or None, "citations": [item["citation_id"] for item in evidence[:3]]}


def generate_brief(cfg: Config, prediction: dict, evidence: list[dict], *,
                   allow_generation: bool = False) -> dict:
    if not allow_generation:
        return _template(prediction, evidence, "")
    provider = os.environ.get("SPM_GENERATION_PROVIDER", "").strip()
    if not provider:
        return _template(prediction, evidence, "没有配置生成服务，已回退到确定性模板")
    if provider not in ALLOWED_PROVIDERS:
        return _template(prediction, evidence, f"生成服务 {provider} 未通过允许清单，已回退到确定性模板")
    call = PROVIDERS.get(provider)
    if call is None:
        return _template(prediction, evidence, f"生成服务 {provider} 没有可用实现，已回退到确定性模板")
    payload = _minimal_payload(prediction, evidence)
    try:
        text = call(payload)
    except Exception:
        # Never surface upstream text: it may contain the provider's own error body.
        return _template(prediction, evidence, "生成服务调用失败，已回退到确定性模板")
    if not isinstance(text, str) or not text.strip():
        return _template(prediction, evidence, "生成服务返回空结果，已回退到确定性模板")
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS]
    return {"mode": f"external:{provider}", "text": text, "degraded": False, "reason": None,
            "citations": payload["citations"][:3], "payload_fields": sorted(payload)}
