"""Deterministic, provenance-preserving document tools; no model execution."""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

from ..agent_service.contracts import ServiceError

FORMATS = (".txt", ".md", ".csv", ".json", ".docx", ".xlsx", ".pdf")


def parse(filename, raw):
    suffix = "." + filename.rsplit(".", 1)[-1].lower()
    pieces, warnings = [], []

    def add(text, location, fields=None):
        if str(text).strip():
            pieces.append({"original": str(text), "location": location, "fields": fields or {}})

    if suffix in (".txt", ".md"):
        for index, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
            add(line, {"line": index})
    elif suffix == ".csv":
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if not reader.fieldnames or any(not field for field in reader.fieldnames):
            raise ServiceError("PARSE_INVALID", "CSV 需要非空字段名")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            warnings.append("重复字段名：需要原表复核")
            raise ServiceError("REVIEW_REQUIRED", "CSV 字段名重复，无法可靠映射列")
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ServiceError("REVIEW_REQUIRED", "CSV 行列数不一致")
            add("；".join(f"{key}: {value}" for key, value in row.items()), {"row": reader.line_num}, row)
    elif suffix == ".json":
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ServiceError("REVIEW_REQUIRED", "JSON 含重复键，请对照原件修正")
                result[key] = value
            return result
        value = json.loads(raw.decode("utf-8-sig"), parse_float=str, parse_int=str, object_pairs_hook=unique)
        rows = value if isinstance(value, list) else [value]
        for index, row in enumerate(rows):
            add(json.dumps(row, ensure_ascii=False), {"json_pointer": f"/{index}" if isinstance(value, list) else ""},
                row if isinstance(row, dict) else None)
    elif suffix in (".docx", ".xlsx"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024 or len(archive.infolist()) > 10000:
                raise ServiceError("FILE_LIMIT", "压缩文档展开后超出限制")
            if suffix == ".docx":
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                root = ET.fromstring(archive.read("word/document.xml"))
                for index, element in enumerate(root.findall(".//w:body/*", ns), 1):
                    if element.tag.endswith("}tbl"):
                        rows = element.findall("w:tr", ns)
                        headers = None
                        warnings.append("Word 表格：首行为字段名假设，请复核周期、单位和合并单元格")
                        for row_number, row in enumerate(rows, 1):
                            cells = ["".join(t.text or "" for t in cell.findall(".//w:t", ns))
                                     for cell in row.findall("w:tc", ns)]
                            if headers is None:
                                headers = cells
                                if any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
                                    raise ServiceError("REVIEW_REQUIRED", f"Word 表格 {index} 首行字段为空或重复，请对照原件修正")
                                continue
                            if len(cells) != len(headers):
                                raise ServiceError("REVIEW_REQUIRED", f"Word 表格 {index} 行 {row_number} 列数不一致")
                            fields = {headers[i] if i < len(headers) else f"列{i + 1}": v for i, v in enumerate(cells)}
                            add("；".join(f"{k}: {v}" for k, v in fields.items()), {"table_block": index, "row": row_number}, fields)
                    else:
                        add("".join(t.text or "" for t in element.findall(".//w:t", ns)), {"paragraph": index})
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ServiceError("PARSER_MISSING", "请安装 knowledge 可选依赖以解析 PDF") from None
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or len(reader.pages) > 500:
            raise ServiceError("REVIEW_REQUIRED", "加密或超过 500 页 PDF 需另行处理")
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if not text.strip():
                warnings.append(f"第 {number} 页无可提取文本，需要 OCR")
            for paragraph, part in enumerate(text.split("\n\n"), 1):
                add(part, {"page": number, "paragraph": paragraph})
        warnings.append("PDF 复杂表格未结构化，需对照原页复核；不保证阅读顺序")
    else:
        raise ServiceError("FORMAT_UNSUPPORTED", "不支持的文件格式")
    if suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ServiceError("PARSER_MISSING", "请安装 knowledge 可选依赖以解析 Excel") from None
        book = load_workbook(io.BytesIO(raw), data_only=False)
        try:
            if any(sheet.max_row > 50000 or sheet.max_column > 200 for sheet in book):
                raise ServiceError("FILE_LIMIT", "工作表超出 50000 行或 200 列")
            for sheet in book:
                if sheet.merged_cells.ranges:
                    warnings.append(f"{sheet.title} 含合并单元格，字段与单位需复核")
                rows = iter(sheet.iter_rows())
                first = next(rows, [])
                headers = [str(c.value) if c.value is not None else f"未命名列{c.column}" for c in first]
                if len(set(headers)) != len(headers):
                    raise ServiceError("REVIEW_REQUIRED", "Excel 重复字段名需人工修正")
                for row in rows:
                    fields = {headers[i]: str(cell.value) if cell.value is not None else "[缺失]" for i, cell in enumerate(row)}
                    if all(cell.value is None for cell in row):
                        continue
                    if any(cell.data_type == "f" for cell in row):
                        warnings.append(f"{sheet.title} 第 {row[0].row} 行含公式，保留公式不猜测计算值")
                    add("；".join(f"{k}: {v}" for k, v in fields.items()),
                        {"sheet": sheet.title, "cells": f"{row[0].coordinate}:{row[-1].coordinate}"}, fields)
        finally:
            book.close()
    if not pieces:
        raise ServiceError("REVIEW_REQUIRED", "没有可提取文本；扫描件需要 OCR")
    if len(pieces) > 50000 or sum(len(p["original"]) for p in pieces) > 10_000_000:
        raise ServiceError("FILE_LIMIT", "解析内容超出本机处理限制")
    return {"pieces": pieces, "warnings": sorted(set(warnings))}


def clean(parsed):
    chunks, seen, heading = [], {}, ""
    for piece in parsed["pieces"]:
        original = piece["original"]
        # NFC preserves financial symbols and numeric units; no inferred values.
        text = unicodedata.normalize("NFC", original).replace("\x00", "").strip()
        if not text:
            continue
        if text.startswith("#"):
            heading = text.lstrip("# ")[:240]
        key = (text, json.dumps(piece["fields"], sort_keys=True, ensure_ascii=False))
        if key in seen:
            for chunk in seen[key]:
                chunk["occurrences"].append(piece["location"])
            continue
        seen[key] = []
        if len(json.dumps(piece["fields"], ensure_ascii=False)) > 20000:
            raise ServiceError("REVIEW_REQUIRED", "单行表格内容过长，请先拆分字段并保留周期单位")
        offset = 0
        while offset < len(original):
            end = min(len(original), offset + 1600)
            if end < len(original):
                boundary = max(original.rfind(mark, offset + 800, end) for mark in ("。", "；", "\n", ". "))
                if boundary >= 0:
                    end = boundary + 1
            excerpt = original[offset:end]
            content = unicodedata.normalize("NFC", excerpt).replace("\x00", "").strip()
            # Full structured fields accompany each table slice, retaining period/unit context.
            normalized = {}
            for field, value in piece["fields"].items():
                if isinstance(value, str):
                    candidate = value.strip()
                    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", candidate):
                        candidate = candidate.replace("/", "-")
                    normalized[field] = candidate
                else:
                    normalized[field] = value
            data_date = None
            for date_key in ("data_date", "date", "日期", "数据日期"):
                if normalized.get(date_key):
                    try:
                        data_date = date.fromisoformat(normalized[date_key]).isoformat()
                    except (TypeError, ValueError):
                        parsed["warnings"].append(f"{piece['location']} 的日期无法规范，保留原值")
                    break
            chunk = {"data_date": data_date, "text": content, "original": excerpt, "heading": heading, "normalized_fields": normalized,
                     "location": {**piece["location"], "extracted_text_offset": offset}, "fields": piece["fields"],
                     "occurrences": [piece["location"]]}
            chunks.append(chunk)
            seen[key].append(chunk)
            offset = end if end == len(original) else max(offset + 1, end - 160)
    return {"chunks": chunks, "warnings": sorted(set(parsed["warnings"]))}
