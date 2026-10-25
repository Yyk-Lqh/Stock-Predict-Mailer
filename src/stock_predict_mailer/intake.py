"""Local upload archive, versioned cleaning jobs and gated snapshot publication."""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
from pathlib import Path

from .core import Config, atomic_write, digest, now, timestamp, write_json
from .data import import_csv
from .intake_clean import KINDS, clean_table
from .intake_readers import MAX_BYTES, IntakeError, read_tables

BASES = {"unknown", "unadjusted", "forward_adjusted", "backward_adjusted", "total_return"}
UNITS = {"unknown", "shares", "lots"}


def intake_paths(cfg: Config) -> Path:
    root = cfg.workspace / "intake"
    for name in ("incoming", "archive", "jobs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def valid_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise IntakeError("无效记录编号")
    return value


def options_checked(options: dict | None) -> dict:
    options = dict(options or {})
    allowed = {"kind", "source", "price_basis", "volume_unit", "available_at", "column_map"}
    if set(options) - allowed:
        raise IntakeError("不支持的处理选项")
    if options.get("kind", "auto") not in KINDS:
        raise IntakeError("不支持的业务类型")
    if options.get("price_basis", "unknown") not in BASES or options.get("volume_unit", "unknown") not in UNITS:
        raise IntakeError("价格口径或成交量单位无效")
    if not isinstance(options.get("column_map", {}), dict):
        raise IntakeError("字段映射必须是 JSON 对象，格式为 标准字段:原始列名")
    if not isinstance(options.get("source", ""), str) or len(options.get("source", "")) > 200:
        raise IntakeError("来源应为不超过 200 字的文本")
    if options.get("available_at"):
        timestamp(str(options["available_at"]))
    return options


def job_path(cfg: Config, upload_id: str) -> Path:
    return intake_paths(cfg) / "archive" / valid_id(upload_id)


def upload(cfg: Config, name: str, raw: bytes, options: dict | None = None) -> dict:
    if not raw or len(raw) > MAX_BYTES:
        raise IntakeError("文件为空或超过 50MB")
    # Never use a submitted name as a filesystem path.
    name = str(name).replace("\\", "/").split("/")[-1][:180]
    if not name or any(ord(c) < 32 for c in name):
        raise IntakeError("文件名无效")
    upload_id = digest(raw)
    folder = job_path(cfg, upload_id)
    if not (folder / "metadata.json").exists():
        atomic_write(folder / "original", raw)
        write_json(folder / "metadata.json", {"upload_id": upload_id, "filename": name, "bytes": len(raw), "received_at": now()})
    return process(cfg, upload_id, options)


def process(cfg: Config, upload_id: str, options: dict | None = None) -> dict:
    options = options_checked(options)
    original_folder = job_path(cfg, upload_id)
    metadata = json.loads((original_folder / "metadata.json").read_text(encoding="utf-8"))
    path = original_folder / "original"
    if digest(path.read_bytes()) != upload_id:
        raise IntakeError("原始文件完整性检查失败")
    # Each processing attempt is immutable; upload identity remains content-addressed.
    job_id = digest(f"{upload_id}:{uuid.uuid4().hex}".encode())
    folder = intake_paths(cfg) / "jobs" / job_id
    report = {**metadata, "job_id": job_id, "processed_at": now(), "options": options,
              "format": "unknown", "status": "rejected", "tables": [], "issues": [],
              "limitations": ["来源、时点、价格口径和单位均仅为用户提供，不构成独立认证", "不补造缺失时间、复权因子或市场成交约束"]}
    try:
        info, tables, document = read_tables(path, metadata["filename"])
        report.update(info)
        if document is not None:
            atomic_write(folder / "document.txt", document.encode("utf-8"))
            report["kind"] = "document"
            report["status"] = "needs_attention"
            report["needs_confirmation"] = ["知识库权限及资料发表与可用时间；当前仅归档，未自动入库"]
            report["document_preview"] = document[:3000]
        else:
            for index, table in enumerate(tables):
                if not table.rows:
                    continue
                summary, cleaned, issues = clean_table(table, options)
                summary["index"] = index
                summary["preview"] = cleaned[:8]
                report["tables"].append(summary)
                report["issues"].extend({"table": table.name, **issue} for issue in issues)
                write_json(folder / f"table-{index}.json", cleaned)
                if cleaned:
                    import pyarrow as pa
                    import pyarrow.parquet as pq
                    # Generic columns can contain mixed input types. Preserve typed records
                    # in JSON; normalize heterogeneous nonnumeric columns to strings in Parquet.
                    keys = list(dict.fromkeys(k for row in cleaned for k in row))
                    arrays = {}
                    for key in keys:
                        values = [row.get(key) for row in cleaned]
                        present = [v for v in values if v is not None]
                        if present and not (all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present) or all(isinstance(v, str) for v in present)):
                            values = [str(v) if v is not None else None for v in values]
                        arrays[key] = pa.array(values)
                    stream = pa.BufferOutputStream()
                    pq.write_table(pa.table(arrays), stream)
                    atomic_write(folder / f"table-{index}.parquet", stream.getvalue().to_pybytes())
            statuses = [t["status"] for t in report["tables"]]
            report["status"] = "ready" if statuses and all(s == "ready" for s in statuses) else "needs_attention" if any(s != "rejected" for s in statuses) else "rejected"
    except Exception as exc:
        # Reader/parser failure is a visible quarantined job; original is retained.
        report["status"] = "rejected"
        message = str(exc)[:240] if isinstance(exc, (IntakeError, ValueError)) else "解析失败，请检查文件完整性或转换格式"
        report["error"] = {"type": type(exc).__name__, "message": message}
    report["issue_count"] = len(report["issues"])
    write_json(folder / "issues.json", report["issues"])
    # API previews stay bounded. Full issue details remain on disk.
    report["issues"] = report["issues"][:200]
    write_json(folder / "report.json", report)
    write_json(original_folder / "latest.json", {"job_id": job_id})
    return report


def latest(cfg: Config, upload_id: str) -> dict:
    pointer = json.loads((job_path(cfg, upload_id) / "latest.json").read_text(encoding="utf-8"))
    return json.loads((intake_paths(cfg) / "jobs" / valid_id(pointer["job_id"]) / "report.json").read_text(encoding="utf-8"))


def list_uploads(cfg: Config) -> list[dict]:
    root = intake_paths(cfg) / "archive"
    result = []
    for path in root.glob("*/latest.json"):
        row = latest(cfg, path.parent.name)
        result.append({key: row[key] for key in ("upload_id", "filename", "bytes", "received_at", "processed_at", "status", "format", "issue_count")})
    return sorted(result, key=lambda r: r["processed_at"], reverse=True)


def scan_incoming(cfg: Config) -> list[dict]:
    results = []
    root = intake_paths(cfg) / "incoming"
    for path in sorted(root.iterdir()):
        if path.is_file() and not path.is_symlink() and not path.name.startswith(".") and not path.name.endswith((".part", ".tmp")):
            if path.stat().st_size > MAX_BYTES:
                results.append({"filename": path.name, "status": "rejected", "error": "超过 50MB"})
                continue
            upload_id = digest(path.read_bytes())
            if (job_path(cfg, upload_id) / "latest.json").exists():
                results.append(latest(cfg, upload_id))
            else:
                results.append(upload(cfg, path.name, path.read_bytes()))
    return results


def publish_bars(cfg: Config, upload_id: str, table_index: int) -> dict:
    report = latest(cfg, upload_id)
    table = next((t for t in report["tables"] if t["index"] == table_index), None)
    if table is None or table["kind"] != "bars" or table["status"] != "ready" or report["status"] == "rejected":
        raise IntakeError("该表不是已通过检查的行情，请先处理待确认项及异常行")
    if report["options"].get("volume_unit") == "lots":
        raise IntakeError("当前训练使用股数；手数转股依赖市场与交易品种，请先确认转换规则")
    folder = intake_paths(cfg) / "jobs" / report["job_id"]
    rows = json.loads((folder / f"table-{table_index}.json").read_text(encoding="utf-8"))
    from .data import FIELDS
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    path = folder / f"publish-{table_index}.csv"
    atomic_write(path, stream.getvalue().encode("utf-8"))
    provenance = {"intake_upload_id": upload_id, "intake_job_id": report["job_id"],
                  "table": table["name"], "price_basis": report["options"].get("price_basis", "unknown"),
                  "volume_unit": report["options"].get("volume_unit", "unknown"),
                  "availability": "supplied_not_independently_verified"}
    return import_csv(cfg, path, provenance=provenance)
