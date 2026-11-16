"""Predeclared forecast targets and strictly matched, point-in-time observations."""
from datetime import date, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import decode, fail, instant, keys, number, prediction, string, utcnow
from .input_evidence import canonical, fingerprint


def forecast_id(p):
    return fingerprint({k: p[k] for k in ("prediction_id", "subject", "model_version")})


def registration(raw):
    """Validate a self-contained receipt at its registration time, without I/O."""
    value = decode(canonical(raw))
    keys(value, ("schema_version", "forecast_id", "registered_at", "prediction", "definition", "content_id", "integrity_id"))
    at = instant(value["registered_at"])
    p = prediction(value["prediction"], now=at)
    d = definition(value["definition"], p, at)
    if (value["schema_version"] != "1" or value["forecast_id"] != forecast_id(p)
            or fingerprint(value["prediction"]) != fingerprint(p)
            or value["content_id"] != fingerprint({"prediction": p, "definition": d})
            or value["integrity_id"] != fingerprint({k: v for k, v in value.items() if k != "integrity_id"})):
        fail("预测注册记录的内容或摘要无效")
    return value


def binding(raw, predicted):
    """Reconstruct the archived prediction using the report's exact input."""
    keys(raw, ("schema_version", "forecast_id", "registered_at", "definition", "content_id", "integrity_id"))
    record = registration({**raw, "prediction": predicted})
    if instant(record["registered_at"]) > utcnow():
        fail("报告不能引用未来的注册记录")
    return {k: v for k, v in record.items() if k != "prediction"}


def definition(raw, predicted, registered_at):
    keys(raw, ("schema_version", "target_at", "timezone", "metric", "unit", "reference", "flat_tolerance"), ("calendar",))
    if raw["schema_version"] != "1":
        fail("评价定义版本无效")
    d = {**raw, "metric": string(raw["metric"]), "unit": string(raw["unit"]), "timezone": string(raw["timezone"])}
    try:
        zone = ZoneInfo(d["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        fail("评价定义需要有效的 IANA 时区")
    target, generated = instant(d["target_at"]), instant(predicted["generated_at"])
    if target <= registered_at or target <= generated:
        fail("目标时点须晚于注册与预测生成时点")
    d["target_at"] = target.isoformat()
    d["flat_tolerance"] = number(d["flat_tolerance"])
    if d["flat_tolerance"] < 0:
        fail("平盘阈值不能为负")
    if "value" in predicted and predicted["value_unit"] != d["unit"]:
        fail("数值预测与评价定义的单位不同")
    keys(d["reference"], ("value", "observed_at", "available_at", "source", "synthetic"))
    r = dict(d["reference"])
    r["value"], r["source"] = number(r["value"]), string(r["source"])
    observed, available = instant(r["observed_at"]), instant(r["available_at"])
    if observed > available or available > generated:
        fail("基准观测在预测生成时尚不可用")
    if type(r["synthetic"]) is not bool or r["synthetic"] != predicted["synthetic"]:
        fail("基准与预测的合成标记不一致")
    r.update(observed_at=observed.isoformat(), available_at=available.isoformat())
    d["reference"] = r
    h = predicted["horizon"]
    if h["unit"] == "hours":
        if target != generated + timedelta(hours=h["value"]):
            fail("小时目标必须精确匹配预测周期")
    elif h["unit"] == "calendar_days":
        if target.astimezone(zone).date() != generated.astimezone(zone).date() + timedelta(days=h["value"]):
            fail("目标日期与所声明时区的自然日周期不匹配")
    else:
        calendar = d.get("calendar")
        keys(calendar, ("source", "sessions"))
        source, sessions = string(calendar["source"]), calendar["sessions"]
        if not isinstance(sessions, list) or len(sessions) != h["value"]:
            fail("必须声明与预测周期等长的后续交易日清单")
        try:
            days = [date.fromisoformat(s) for s in sessions]
            if any(day.isoformat() != s for day, s in zip(days, sessions, strict=True)):
                raise ValueError()
        except (ValueError, TypeError):
            fail("交易日必须为 YYYY-MM-DD")
        if (days != sorted(set(days)) or days[0] <= generated.astimezone(zone).date()
                or target.astimezone(zone).date() != days[-1]):
            fail("声明日历须严格递增且目标日匹配末日")
        d["calendar"] = {"source": source, "sessions": list(sessions)}
    if h["unit"] != "trading_days" and "calendar" in d:
        fail("非交易日周期不接受交易日清单")
    return d


def observation(raw, record):
    keys(raw, ("schema_version", "subject", "metric", "unit", "value", "observed_at", "available_at", "source", "synthetic"))
    p, d = record["prediction"], record["definition"]
    result = dict(raw)
    for field in ("subject", "metric", "unit", "source"):
        result[field] = string(result[field])
    if (result["schema_version"] != "1" or result["subject"] != p["subject"] or result["metric"] != d["metric"]
            or result["unit"] != d["unit"] or type(result["synthetic"]) is not bool or result["synthetic"] != p["synthetic"]):
        fail("观测版本、对象、指标、单位或合成标记不匹配")
    result["value"] = number(result["value"])
    observed, available = instant(result["observed_at"]), instant(result["available_at"])
    if observed != instant(d["target_at"]) or available < observed:
        fail("观测必须精确匹配事前目标时点，且可用时间不早于观测")
    result.update(observed_at=observed.isoformat(), available_at=available.isoformat())
    return result


def score(record, actual):
    p, d = record["prediction"], record["definition"]
    # Compare the declared decimal values, so 0.4-0.1 at tolerance 0.3 stays
    # flat instead of moving up because of a binary floating-point residue.
    with localcontext() as context:
        context.prec = 1024
        change_decimal = Decimal(str(actual["value"])) - Decimal(str(d["reference"]["value"]))
        threshold = Decimal(str(d["flat_tolerance"]))
        realized = "up" if change_decimal > threshold else "down" if change_decimal < -threshold else "flat"
        signed_error = Decimal(str(actual["value"])) - Decimal(str(p["value"])) if "value" in p else None
    change = number(float(change_decimal))
    result = {"unit": d["unit"], "change_from_reference": change, "realized_direction": realized,
              "direction_correct": realized == p["direction"] if "direction" in p else None}
    if "value" in p:
        result["signed_error"] = number(float(signed_error))
        result["absolute_error"] = abs(result["signed_error"])
    return result
