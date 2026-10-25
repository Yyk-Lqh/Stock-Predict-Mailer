"""Conservative deterministic cleaning; never invent point-in-time metadata."""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime

from .core import timestamp
from .intake_readers import IntakeError, Table

ALIASES = {
    "date": ("日期", "交易日期", "交易日", "date", "trade_date", "tradedate"),
    "security_id": ("股票代码", "证券代码", "股票编码", "代码", "security_id", "symbol", "code", "ts_code", "ticker"),
    "open": ("开盘", "开盘价", "open"), "high": ("最高", "最高价", "high"),
    "low": ("最低", "最低价", "low"), "close": ("收盘", "收盘价", "close"),
    "volume": ("成交量", "volume", "vol"), "amount": ("成交额", "amount"),
    "source": ("来源", "数据来源", "source"),
    "available_at": ("可用时间", "首次可用时间", "available_at", "first_seen_at"),
    "published_at": ("发布时间", "公告时间", "披露时间", "published_at", "publish_time", "pubdate"),
    "report_period": ("报告期", "报告日期", "report_period", "report_date"),
    "revenue": ("营业收入", "营收", "revenue"), "net_profit": ("净利润", "net_profit"),
    "title": ("标题", "title", "headline"), "content": ("内容", "正文", "content", "body", "text"),
    "indicator": ("指标", "指标名称", "indicator", "series"), "value": ("数值", "指标值", "value"),
}
KINDS = {"auto", "bars", "financial", "news", "macro", "table", "document"}
NUMBERS = {"open", "high", "low", "close", "volume", "amount", "revenue", "net_profit", "value"}
EMPTY = {"", "null", "none", "nan", "n/a", "na", "--"}


def field_key(text: str) -> str:
    return re.sub(r"[\s_-]", "", str(text)).lower()


def field_mapping(headers: list[str], overrides: dict | None = None) -> tuple[dict, list[str]]:
    aliases = {field_key(alias): key for key, values in ALIASES.items() for alias in values}
    mapping, conflicts = {}, []
    for header in headers:
        canonical = aliases.get(field_key(header), header.strip())
        if canonical in mapping.values():
            conflicts.append(canonical)
        mapping[header] = canonical
    for canonical, original in (overrides or {}).items():
        if canonical not in ALIASES or original not in headers:
            raise IntakeError("手工字段映射必须使用存在的列名和支持的标准字段")
        for key, value in list(mapping.items()):
            if value == canonical:
                mapping[key] = key if key != canonical else f"original_{key}"
        mapping[original] = canonical
    duplicates = [key for key, count in Counter(mapping.values()).items() if count > 1]
    return mapping, duplicates


def identify(fields: set[str]) -> str:
    if {"date", "security_id", "open", "high", "low", "close", "volume"} <= fields:
        return "bars"
    if "security_id" in fields and fields & {"revenue", "net_profit", "report_period"}:
        return "financial"
    if {"title", "content"} <= fields:
        return "news"
    if {"indicator", "value"} <= fields:
        return "macro"
    return "table"


def day_value(value) -> str:
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", text):
        return datetime.strptime(text, "%Y/%m/%d").date().isoformat()
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}(?:T00:00:00)?", text):
        return datetime.strptime(text.split("T")[0], "%Y-%m-%d").date().isoformat()
    raise ValueError("日期需要 YYYY-MM-DD、YYYY/MM/DD 或 YYYYMMDD；不猜测日月顺序")


def number_value(value) -> float:
    if isinstance(value, bool):
        raise ValueError("布尔值不是数值")
    text = str(value).strip()
    if "," in text:
        if not re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
            raise ValueError("逗号格式含糊，不猜测小数或千分位")
        text = text.replace(",", "")
    result = float(text)
    if not math.isfinite(result):
        raise ValueError("不允许非有限数值")
    return result


def security_value(value) -> str:
    text = str(value).strip()
    if re.fullmatch(r"(?:SH|SZ|BJ)\.\d{6}", text, re.I):
        return text.lower()
    if re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", text, re.I):
        code, market = text.split(".")
        return f"{market.lower()}.{code}"
    return text  # no exchange or leading-zero inference


def clean_table(table: Table, options: dict) -> tuple[dict, list[dict], list[dict]]:
    headers = list(dict.fromkeys(key for row in table.rows for key in row))
    mapping, conflicts = field_mapping(headers, options.get("column_map"))
    kind = options.get("kind", "auto")
    if kind not in KINDS or kind == "document":
        raise IntakeError("表格类别无效")
    kind = identify(set(mapping.values())) if kind == "auto" else kind
    if conflicts:
        raise IntakeError("字段映射冲突，请手工映射重复含义的列：" + ",".join(conflicts))
    issues, cleaned, seen = [], [], set()
    duplicates = 0
    needs = set()
    if kind == "table":
        needs.add("无法可靠识别业务类别，请确认类型与字段映射")
    for number, raw in enumerate(table.rows, 2):
        row, invalid = {}, False
        for header, value in raw.items():
            key = mapping[header]
            value = value.strip() if isinstance(value, str) else value
            if value is None or isinstance(value, str) and value.lower() in EMPTY:
                row[key] = None
                continue
            try:
                if isinstance(value, str) and value.startswith("="):
                    raise ValueError("不执行 Excel 公式，请先导出实际值")
                if key in NUMBERS:
                    value = number_value(value)
                elif key in ("date", "report_period"):
                    value = day_value(value)
                elif key == "security_id":
                    value = security_value(value)
                    if value.isdigit() and len(value) < 6:
                        needs.add("证券代码不足六位，可能丢失前导零；请核对，程序不会补造")
                elif key in ("available_at", "published_at"):
                    value = timestamp(str(value)).isoformat()
            except (ValueError, TypeError, OverflowError) as exc:
                issues.append({"row": number, "field": key, "code": "invalid_value", "message": str(exc)[:180]})
                invalid = True
            row[key] = value
        if options.get("source") and not row.get("source"):
            row["source"] = str(options["source"]).strip()
        if options.get("available_at") and not row.get("available_at"):
            row["available_at"] = timestamp(str(options["available_at"])).isoformat()
        if not row.get("source"):
            needs.add("数据来源")
        if kind == "bars":
            required = {"date", "security_id", "open", "high", "low", "close", "volume"}
            missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
            if missing:
                issues.append({"row": number, "code": "missing_fields", "message": "缺少必需值：" + ",".join(sorted(missing))})
                invalid = True
            if not invalid:
                if min(row[k] for k in ("open", "high", "low", "close")) <= 0 or row["volume"] < 0 or row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]):
                    issues.append({"row": number, "code": "invalid_ohlcv", "message": "价格非正、成交量为负或开高低收关系矛盾"})
                    invalid = True
            if not row.get("available_at"):
                needs.add("历史实际可用时间 available_at")
            elif not invalid and timestamp(row["available_at"]).date() < date.fromisoformat(row["date"]):
                issues.append({"row": number, "code": "early_availability", "message": "完整日线不应在交易日期之前可用"})
                invalid = True
            if not invalid and row["high"] == row["low"]:
                issues.append({"row": number, "code": "single_price", "severity": "warning", "message": "全天单一价格，需结合停牌、涨跌停及成交约束核对"})
        if kind in ("financial", "news", "macro") and not row.get("available_at"):
            needs.add("历史实际可用时间 available_at")
        if invalid:
            continue
        identity = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if identity in seen:
            duplicates += 1
            issues.append({"row": number, "code": "exact_duplicate", "message": "删除一条完全重复记录"})
            continue
        seen.add(identity)
        cleaned.append((number, row))
    if kind == "bars":
        grouped = defaultdict(list)
        for number, row in cleaned:
            grouped[(row["date"], row["security_id"])].append((number, row))
        cleaned = []
        for group in grouped.values():
            if len(group) > 1:
                issues.extend({"row": number, "code": "conflicting_bar", "message": "同证券同日有不同记录，全部隔离，未自动选取版本"} for number, _ in group)
            else:
                cleaned.extend(group)
        if options.get("price_basis", "unknown") == "unknown":
            needs.add("价格复权口径")
        if options.get("volume_unit", "unknown") == "unknown":
            needs.add("成交量单位（股或手）")
    output = [row for _, row in cleaned]
    excluded = len(table.rows) - len(output) - duplicates
    status = "needs_attention" if needs or excluded else "ready"
    if not output:
        status = "rejected"
    summary = {"name": table.name, "kind": kind, "mapping": mapping, "input_rows": len(table.rows),
               "output_rows": len(output), "duplicates_removed": duplicates, "excluded_rows": excluded,
               "needs_confirmation": sorted(needs), "status": status,
               "warning_count": sum(i.get("severity") == "warning" for i in issues)}
    summary["missing_values"] = {key: sum(row.get(key) is None for row in output) for key in set(mapping.values())}
    if kind == "bars" and output:
        dates = sorted(row["date"] for row in output)
        summary["date_range"] = [dates[0], dates[-1]]
        summary["security_count"] = len({row["security_id"] for row in output})
    return summary, output, issues
