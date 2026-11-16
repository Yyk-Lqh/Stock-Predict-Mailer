"""Pure preview from one task-authorized archive snapshot; no receipt writes."""
from ..agent_service.contracts import instant
from ..agent_service.forecast_contracts import score
from ..agent_service.observation_input import parse
from .forecast_views import Reader, bounded, fail


def preview(store, tid, request):
    """Caller applies session, CSRF and task-owner guards before this function."""
    reader = Reader(store)
    with store.db() as con:
        key = reader.key(con, tid)
    if key is None:
        fail("NOT_FOUND", "此任务没有关联的预测归档")
    record = reader.view(key)["record"]
    # Validate even a not-yet-due observation; never hide malformed inputs
    # behind a maturity state or substitute the reference for actual data.
    imported = parse(request, record)
    at = instant(request["as_of"]) if "as_of" in request else reader.now
    if at > reader.now:
        fail("INVALID_INPUT", "预览截止不能晚于现在")
    if at < instant(record["registered_at"]):
        fail("FORECAST_NOT_YET_REGISTERED", "截止时点该预测尚未注册")
    result = {"task_id": tid, "forecast_id": key, "forecast_content_id": record["content_id"],
              "forecast_record_id": record["integrity_id"], "as_of": at.isoformat(), "computed_at": reader.now.isoformat(),
              "persisted": False, "synthetic": record["prediction"]["synthetic"], **imported,
              "limitations": ["仅预览，未保存评估回执；来源与其时间为提供方声明，未独立认证。",
                              "这些指标不代表交易收益或置信度校准。"]}
    if at < instant(record["definition"]["target_at"]):
        result["state"] = "not_due"
    elif at < instant(imported["observation"]["available_at"]):
        result["state"] = "awaiting_observation"
    else:
        result.update(state="ready", metrics=score(record, imported["observation"]))
    return bounded(result)
