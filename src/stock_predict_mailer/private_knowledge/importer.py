"""Bulk import of a folder tree, driven by a reviewable CSV manifest.

The console uploads one file at a time and asks for the tags in a form, which does
not scale to a seed corpus of fifty to eighty documents. This module keeps every
service-level guarantee of that path: the queue stays the only write path,
``upload()`` stays idempotent on (logical, content hash), and the encrypted
original stays the only copy. What it adds is planning - a dry run, a manifest a
reviewer can edit in a spreadsheet, and a per-file reason for every skip.

Two rules are deliberately strict, because both mistakes are permanent:

* ``available_date`` is never guessed silently. It comes from the manifest, from
  ``--available``, or from ``document_date``; a file with none of them fails
  instead of defaulting to today, since "today" is what corrupts a backtest.
* A manifest is authoritative. When one is supplied, files it does not list are
  skipped rather than imported with invented metadata, and rows that name a
  missing file are reported as failures.
"""
from __future__ import annotations

import csv
import hashlib
import re
import sys
from pathlib import Path

from ..agent_service.contracts import ServiceError, utcnow
from ..knowledge_api import open_store
from ..naming import env, env_key
from .parsing import FORMATS

COLUMNS = ("path", "logical", "source", "document_date", "available_date", "valid_to",
           "companies", "industries", "topics", "stock_codes")
TAGS = ("companies", "industries", "topics", "stock_codes")
DATES = ("document_date", "available_date", "valid_to")
SPLIT = re.compile(r"[;,|、，；]")
MAX_BYTES = 10 * 1024 * 1024
SKIP_DIRS = {"__pycache__", "private-knowledge"}


def _posix(folder, path):
    return path.relative_to(folder).as_posix()


def _files(folder, recursive, exclude):
    found = folder.rglob("*") if recursive else folder.glob("*")
    return [item for item in sorted(found)
            if item.is_file() and item.resolve() not in exclude
            and not any(part.startswith(".") or part in SKIP_DIRS for part in item.relative_to(folder).parts)]


def _logical(rel):
    # Slot identity: the tree the operator already sorted, minus the extension.
    return rel.rsplit(".", 1)[0] if "." in Path(rel).name else rel


def _split(value):
    return [part.strip() for part in SPLIT.split(value or "") if part.strip()]


def _read_manifest(path):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        raise ServiceError("INVALID_INPUT", f"清单不可读：{path}") from None
    reader = csv.DictReader(text.splitlines())
    fields = reader.fieldnames or []
    unknown = set(fields) - set(COLUMNS)
    if unknown:
        raise ServiceError("INVALID_INPUT", f"清单含未知列：{'、'.join(sorted(unknown))}；允许 {', '.join(COLUMNS)}")
    if "path" not in fields:
        raise ServiceError("INVALID_INPUT", "清单缺少 path 列")
    rows = {}
    for number, row in enumerate(reader, start=2):
        rel = (row.get("path") or "").strip().replace("\\", "/")
        if not rel:
            continue
        if rel in rows:
            raise ServiceError("INVALID_INPUT", f"清单第 {number} 行的 path 重复：{rel}")
        rows[rel] = {key: (row.get(key) or "").strip() for key in COLUMNS}
    return rows


def _write_manifest(path, folder, files, source):
    if path.exists():
        raise ServiceError("INVALID_INPUT", f"清单已存在，避免覆盖已填写的标签：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"path": _posix(folder, item), "logical": _logical(_posix(folder, item)), "source": source}
            for item in files if item.suffix.lower() in FORMATS]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})
    return len(rows)


def _metadata(row, *, source, available, assume_today, today):
    meta = {"source": row.get("source") or source,
            "document_date": row.get("document_date") or None,
            "valid_to": row.get("valid_to") or None}
    available_date = row.get("available_date") or available
    inferred = False
    if not available_date and meta["document_date"]:
        # Dated today is a known wrong answer; dated as published is an honest guess.
        available_date, inferred = meta["document_date"], True
    if not available_date:
        if not assume_today:
            raise ServiceError("INVALID_INPUT",
                               "缺少可用日期：请填 available_date 或传 --available；确有当日可用依据时用 --assume-available-today")
        available_date, inferred = today, True
    meta["available_date"] = available_date
    for key in TAGS:
        meta[key] = _split(row.get(key, ""))
    return meta, inferred


def _existing(kb, owner, logical, fingerprint):
    with kb.db() as con:
        row = con.execute("SELECT id,status FROM documents WHERE owner=? AND logical=? AND hash=?",
                          (owner, logical, fingerprint)).fetchone()
    return dict(row) if row else None


def run(workspace, folder, *, principal="owner", manifest=None, write_manifest=None, source="本地导入",
        available=None, assume_available_today=False, dry_run=False, limit=None, recursive=True,
        progress=True, process=False):
    folder = Path(folder)
    if not folder.is_dir():
        raise ServiceError("INVALID_INPUT", "目录不存在或不是目录")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ServiceError("INVALID_INPUT", "--limit 须为正整数")
    today = utcnow().date().isoformat()
    pending, target = (Path(manifest).resolve() if manifest else None), (Path(write_manifest).resolve() if write_manifest else None)
    files = _files(folder, recursive, {item for item in (pending, target) if item})

    if target:
        rows = _write_manifest(target, folder, files, source)
        return {"folder": str(folder), "manifest": str(target), "rows": rows,
                "next": f"填写 {', '.join(COLUMNS[1:])} 后运行：knowledge-import {folder} --manifest {target} --dry-run"}

    rows = _read_manifest(pending) if pending else {}
    kb, owner = open_store(workspace, principal)
    summary = {"folder": str(folder), "manifest": str(pending) if pending else None,
               "principal": principal, "owner": owner, "dry_run": bool(dry_run), "scanned": len(files),
               "queued": [], "skipped": [], "failed": [], "warnings": {"available_date_inferred": 0}}
    tell = (lambda text: print(text, file=sys.stderr)) if progress else (lambda text: None)
    seen, done = set(), 0

    for path in files:
        rel = _posix(folder, path)
        if pending and rel not in rows:
            summary["skipped"].append({"path": rel, "reason": "清单未登记；清单存在时以其为准"})
            continue
        if path.suffix.lower() not in FORMATS:
            summary["skipped"].append({"path": rel, "reason": f"不支持的格式，支持 {', '.join(FORMATS)}"})
            continue
        if not 1 <= path.stat().st_size <= MAX_BYTES:
            summary["skipped"].append({"path": rel, "reason": "空文件或超过 10 MiB"})
            continue
        if limit is not None and done >= limit:
            summary["skipped"].append({"path": rel, "reason": f"超出 --limit {limit}"})
            continue
        seen.add(rel)
        done += 1
        tell(f"[{done}] {rel}")
        try:
            row = rows.get(rel, {})
            logical = row.get("logical") or _logical(rel)
            if len(logical) > 200:
                raise ServiceError("INVALID_INPUT", "逻辑名称超过 200 字符，请在清单里用 logical 列简写")
            meta, inferred = _metadata(row, source=source, available=available,
                                       assume_today=assume_available_today, today=today)
            raw = path.read_bytes()
            fingerprint = hashlib.sha256(raw).hexdigest()
            found = _existing(kb, owner, logical, fingerprint)
            if found:
                summary["skipped"].append({"path": rel, "reason": f"内容已存在（{found['status']}），未重复写入"})
                continue
            summary["warnings"]["available_date_inferred"] += int(inferred)
            if dry_run:
                summary["queued"].append({"path": rel, "logical": logical, "metadata": meta, "status": "planned"})
                continue
            item = kb.upload(owner, path.name, raw, meta, logical)
            summary["queued"].append({"path": rel, "logical": logical, "metadata": meta,
                                      "document_id": item["id"], "status": item["status"]})
        except ServiceError as exc:
            summary["failed"].append({"path": rel, "error": exc.message})
        except OSError as exc:
            summary["failed"].append({"path": rel, "error": f"读取失败：{exc.strerror or exc}"})

    for rel in rows:
        if rel not in seen and not any(item["path"] == rel for item in summary["skipped"]):
            summary["failed"].append({"path": rel, "error": "清单登记但文件不存在"})

    if process and not dry_run and summary["queued"]:
        from .worker import run as run_worker
        summary["worker"] = {"exit": run_worker(workspace, once=True)}
    summary["totals"] = {"queued": len(summary["queued"]), "skipped": len(summary["skipped"]),
                         "failed": len(summary["failed"])}
    if not env("KB_KEY"):
        summary["note"] = (f"本次写入 owner {owner}；若控制台看不到资料，请用 {env_key('KB_KEY')}=<控制台密钥> 重新导入，"
                           "或用同一 config 的 principal")
    return summary
