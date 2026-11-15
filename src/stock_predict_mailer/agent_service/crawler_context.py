"""Read disclosed financial snapshots using only standard-library dependencies."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from ..core import digest
from .contracts import ServiceError, decode, fail, instant, keys, number, prediction, utcnow
from .input_evidence import fingerprint, freeze

METRICS = {"ROE": "净资产收益指标", "net_margin": "净利润率指标", "gross_margin": "毛利率指标",
           "eps_ttm": "滚动每股收益指标", "main_revenue": "主营收入指标", "net_profit_yoy": "净利润同比指标",
           "attrib_net_profit_yoy": "归母净利润同比指标", "eps_yoy": "每股收益同比指标",
           "debt_to_asset": "资产负债指标", "current_ratio": "流动比率指标",
           "current_asset_ratio": "流动资产占比指标", "non_current_asset_ratio": "非流动资产占比指标"}
WARNINGS = ["基本面来源为 baostock 声明，未独立核实；未接入行情时间和计价规则尚未核验的目录价格。",
            "指标保留来源原生单位，未转换为百分比、货币或统一口径。",
            "报告期末及披露日采用上海时区日终；事实年龄仍按原报告期计算。",
            "事后修订及历史股票池未验证，该视图不能直接作为无未来信息的历史回测输入。",
            "交易所按采集请求路由声明匹配，未经独立来源认证；全历史数据覆盖范围仍未知。"]


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        fail("基本面日期须为 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        fail("基本面日期无效")


def _end(day):
    return datetime.combine(day, time(23, 59, 59), ZoneInfo("Asia/Shanghai"))


def _subject(subject):
    if not isinstance(subject, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", subject):
        fail("采集上下文标的须为六位数字.SH/SZ/BJ")
    return subject[:6]


def context_from_source(source, subject):
    keys(source, ("filename", "csv_sha256", "metadata_sha256", "metadata", "record", "row_number", "fact_fields", "warnings"))
    code = _subject(subject)
    meta, row = source["metadata"], source["record"]
    if not isinstance(meta, dict) or not isinstance(row, dict):
        fail("来源元数据或记录无效")
    for field in ("csv_sha256", "metadata_sha256"):
        if not isinstance(source[field], str) or not re.fullmatch(r"[a-f0-9]{64}", source[field]):
            fail("来源摘要无效")
    filename = source["filename"]
    if not isinstance(filename, str) or not filename or len(filename) > 255 or any(x in filename for x in ("/", "\\", "\r", "\n")):
        fail("证据文件名称无效")
    if type(source["row_number"]) is not int or source["row_number"] < 2:
        fail("来源行号无效")
    if source["metadata_sha256"] != fingerprint(meta) or source["csv_sha256"] != meta.get("csv_sha256"):
        fail("来源元数据摘要不匹配")
    complete = meta.get("completeness") == "complete" or (meta.get("completeness") == "partial" and meta.get("scope_limited") is True)
    if meta.get("source") != "baostock" or meta.get("run_complete") is not True or not complete:
        raise ServiceError("UNVERIFIED_CONTEXT", "采集任务未完整完成，不能作为单标的上下文")
    selected, processed = meta.get("selected_count"), meta.get("processed_count")
    if (type(selected) is not int or type(processed) is not int or selected < 0 or selected != processed
            or type(meta.get("scope_limited")) is not bool):
        fail("采集完成数量或限量标记无效")
    if meta.get("point_in_time_verified") is not False or meta.get("historical_pool_verified") is not False:
        fail("来源缺少历史修订与股票池限制声明")
    if row.get("code") != code or row.get("publication_verified") not in (True, "True", "true"):
        raise ServiceError("UNVERIFIED_CONTEXT", "标的不匹配或披露字段未经验证")
    if row.get("provider_symbol") != subject[-2:].lower() + "." + code:
        raise ServiceError("UNVERIFIED_CONTEXT", "采集交易所路由缺失或与预测标的不匹配")
    report, pub, cutoff = _day(row.get("report_date")), _day(row.get("pub_date")), _day(meta.get("request_as_of"))
    if report.isoformat()[5:] not in ("03-31", "06-30", "09-30", "12-31") or not report <= pub <= cutoff:
        fail("报告期、披露日与截止日不一致")
    quarter = (cutoff.month - 1) // 3
    end_year, end_quarter = (cutoff.year, quarter) if quarter else (cutoff.year - 1, 4)
    if (report.year, (report.month - 1) // 3 + 1) > (end_year, end_quarter):
        fail("报告期超出来源截止季度")
    now = utcnow()
    collected, generated = instant(row.get("collected_at")), instant(meta.get("generated_at"))
    if cutoff > now.astimezone(ZoneInfo("Asia/Shanghai")).date() or collected > generated or generated > now:
        fail("来源采集或生成时间在未来或顺序无效")
    if collected.astimezone(ZoneInfo("Asia/Shanghai")).date() < pub:
        fail("原始采集时间早于披露日")
    available, observed = max(_end(pub), collected), _end(report)
    if available > now:
        raise ServiceError("CONTEXT_NOT_AVAILABLE", "披露日期只有日精度，当前尚未到保守可用时点")
    record_id = fingerprint(row)[:16]
    facts, fields = [], {}
    for field, name in METRICS.items():
        raw = row.get(field)
        if raw in (None, "", "-", "--"):
            continue
        try:
            value = number(float(raw)) if not isinstance(raw, bool) else number(raw)
        except (ValueError, TypeError, OverflowError):
            fail("基本面数值无效")
        fact_id = f"crawler-{record_id}-{field}"
        facts.append({"id": fact_id, "name": f"{name}（报告期 {report.isoformat()}）", "value": value,
                      "unit": f"source_native:{field}", "source": "baostock（来源声明）",
                      "observed_at": observed.astimezone(ZoneInfo("UTC")).isoformat(),
                      "available_at": available.astimezone(ZoneInfo("UTC")).isoformat()})
        fields[fact_id] = field
    if not facts:
        raise ServiceError("CONTEXT_UNAVAILABLE", "该标的记录没有可用数值")
    warnings = WARNINGS + (["本次采集仅覆盖明确限量的股票范围。"] if meta.get("scope_limited") else [])
    if fields != source["fact_fields"] or source["warnings"] != warnings:
        fail("来源字段映射或限制声明不匹配")
    return {"schema_version": "1", "context_id": fingerprint([subject, source["csv_sha256"], row]),
            "subject": subject, "facts": facts}


def _read(path, maximum):
    try:
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except OSError:
        raise ServiceError("LOCAL_IO", "无法读取采集上下文文件或元数据") from None
    if len(raw) > maximum:
        fail("采集上下文文件超过大小限制")
    return raw


class CrawlerContextAdapter:
    def __init__(self, path, upstream_prediction, max_prediction_age=86400):
        self.path, self.upstream = Path(path), upstream_prediction
        self.max_prediction_age = max_prediction_age

    def fetch(self):
        predicted = prediction(self.upstream, max_age=self.max_prediction_age)
        code = _subject(predicted["subject"])
        raw = _read(self.path, 64 * 1024 * 1024)
        meta = decode(_read(Path(str(self.path) + ".metadata.json"), 64 * 1024))
        if not isinstance(meta, dict) or meta.get("csv_sha256") != digest(raw):
            fail("采集 CSV 与元数据不匹配")
        csv_digest, metadata_digest = digest(raw), fingerprint(meta)
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
            headers = reader.fieldnames
            if not headers or len(headers) != len(set(headers)) or not {"code", "report_date", "pub_date", "collected_at"}.issubset(headers):
                fail("采集 CSV 表头缺失或重复")
            candidates = []
            seen = set()
            for row_number, record in enumerate(reader, 2):
                if record.get("code") != code:
                    continue
                if None in record or record["report_date"] in seen:
                    fail("采集记录列数无效或报告期重复")
                seen.add(record["report_date"])
                record_id = fingerprint(record)[:16]
                fields = {f"crawler-{record_id}-{field}": field for field in METRICS
                          if record.get(field) not in (None, "", "-", "--")}
                source = {"filename": self.path.name, "csv_sha256": csv_digest, "metadata_sha256": metadata_digest,
                          "metadata": meta, "record": record, "row_number": row_number, "fact_fields": fields,
                          "warnings": WARNINGS + (["本次采集仅覆盖明确限量的股票范围。"] if meta.get("scope_limited") else [])}
                try:
                    collected = context_from_source(source, predicted["subject"])
                except ServiceError as exc:
                    if exc.code == "CONTEXT_NOT_AVAILABLE":
                        continue
                    raise
                candidates.append((record["report_date"], collected, source))
        except (csv.Error, UnicodeError):
            fail("采集 CSV 编码或格式无效")
        if not candidates:
            raise ServiceError("CONTEXT_UNAVAILABLE", "没有匹配该标的且当前可用的基本面记录")
        _, collected, source = max(candidates, key=lambda item: item[0])
        return dict(collected, input_evidence=freeze(predicted, collected, source))
