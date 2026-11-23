"""Built-in read-only tools for the professional workflow."""
from ..agent_service.contracts import ServiceError
from .workflow_database import DEFAULTS, query


def _prediction(engine, state):
    value = state["request"]["prediction"]
    return {key: value.get(key) for key in ("subject", "model_version", "horizon", "generated_at", "valid_until", "synthetic",
                                            "confidence")}, value["confidence"] is not None


def _facts(engine, state):
    facts = state["facts"]
    return {
        "count": len(facts),
        "sources": sorted({fact["source"] for fact in facts})[:20],
        "latest_observation": max((fact["observed_at"] for fact in facts), default=None),
    }, bool(facts)


def _series(engine, state):
    data = state["series"] or {}
    entries = [{
        "kind": kind, "source": item["source"], "points": len(item["points"]),
        "first_at": item["points"][0]["at"], "last_at": item["points"][-1]["at"],
    } for kind, item in data.get("series", {}).items()]
    return {"unit": data.get("unit"), "series": entries}, bool(entries)


def _history(engine, state):
    result = query(engine.store, state["request"], {**DEFAULTS, "query": "archived", "limit": 5})
    return result, bool(result["rows"])


def _mail(engine, state):
    request = state["request"]
    policy = engine.store.settings()["mail"]
    recipients = request["recipients"]
    authorized = sum(address in policy["recipient_allowlist"] for address in recipients)
    allowed = not request["prediction"]["synthetic"] or policy["allow_synthetic"]
    ready = bool(request["notify"] and recipients and authorized == len(recipients) and allowed)
    return {"requested": request["notify"], "transport": policy["transport"], "recipients": len(recipients),
            "authorized": authorized, "synthetic_allowed": allowed}, ready


TOOLS = {
    "prediction_check": ("预测检查", "读取预测周期、有效期、上游模型及置信度", "上游未提供置信度", _prediction),
    "facts_audit": ("事实来源盘点", "统计已校验事实并列出来源和最近观测时间", "没有已校验事实", _facts),
    "series_audit": ("时间序列盘点", "检查已校验序列的来源、点数和覆盖时间", "没有已校验的时间序列", _series),
    "forecast_history": ("历史归档查询", "查询当前标的最近五条可访问的已归档分析", "当前标的没有可访问的归档分析", _history),
    "mail_check": ("邮件交付检查", "预检通知开关、当前收件人授权及合成数据策略", "当前任务不具备邮件交付条件", _mail),
}


def catalog():
    return {key: {"label": label, "detail": detail, "requirement": requirement}
            for key, (label, detail, requirement, _) in TOOLS.items()}


def validate(config):
    tool, required = config.get("tool"), config.get("required", False)
    if not isinstance(tool, str) or tool not in TOOLS or type(required) is not bool:
        raise ServiceError("WORKFLOW_TOOL", "请选择已登记的内置工具及有效的检查选项")
    return {"tool": tool, "required": required}


def call(engine, state, config, node):
    label, _, requirement, handler = TOOLS[config["tool"]]
    result, ready = handler(engine, state)
    if config["required"] and not ready:
        raise ServiceError("WORKFLOW_TOOL_NOT_READY", f"{node} · {requirement}")
    return {"tool": config["tool"], "label": label, "ready": ready, "reason": None if ready else requirement, **result}


def authorized_mcp(store):
    allowed = set(store.settings()["agents"]["main"]["tools"])
    bindings = {}
    for profile in store.list("mcp"):
        if profile["enabled"]:
            for tool in profile["allowed_tools"]:
                binding = f"{profile['id']}:{tool}"
                if binding in allowed and profile["effects"].get(tool) == "read":
                    bindings[binding] = f"{profile['name']} · {tool}"
    return bindings
