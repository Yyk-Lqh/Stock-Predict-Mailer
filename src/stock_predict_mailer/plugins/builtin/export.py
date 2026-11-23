"""Built-in dataset exporters.

Every exporter writes the columns the snapshot already validated, in the same
order. None of them renames, reorders or coerces: the format decides the
encoding, never the meaning.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ...core import atomic_write
from ..contract import declare

FIELDS = ("date", "security_id", "open", "high", "low", "close", "volume", "available_at", "source")


def _pick(rows):
    return [{name: row[name] for name in FIELDS} for row in rows]


class CsvExporter:
    manifest = declare(id="export_csv", kind="exporter", label="CSV 导出", capabilities=("csv",))

    @staticmethod
    def export(rows, path):
        target = Path(path)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(_pick(rows))
        return {"format": "csv", "path": str(target), "rows": len(rows)}


class JsonLinesExporter:
    manifest = declare(id="export_jsonl", kind="exporter", label="JSON Lines 导出", capabilities=("json",))

    @staticmethod
    def export(rows, path):
        target = Path(path)
        with target.open("w", encoding="utf-8") as handle:
            for row in _pick(rows):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"format": "json", "path": str(target), "rows": len(rows)}


class ParquetExporter:
    manifest = declare(id="export_parquet", kind="exporter", label="Parquet 导出", capabilities=("parquet",),
                       requires=("pyarrow",), extra="research")

    @staticmethod
    def export(rows, path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        target = Path(path)
        pq.write_table(pa.Table.from_pylist(_pick(rows)), target)
        return {"format": "parquet", "path": str(target), "rows": len(rows)}


class DeclarativeExporter:
    def __init__(self, manifest, settings):
        self.manifest = manifest
        self.settings = settings

    def export(self, rows, path):
        fmt = self.settings["format"]
        if fmt == "csv":
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=FIELDS,
                                    delimiter=self.settings.get("delimiter", ","))
            writer.writeheader()
            writer.writerows(_pick(rows))
            raw = stream.getvalue().encode("utf-8-sig" if self.settings.get("bom") else "utf-8")
        else:
            raw = (json.dumps(_pick(rows), ensure_ascii=False, indent=self.settings.get("indent") or None,
                              allow_nan=False) + "\n").encode("utf-8")
        atomic_write(Path(path), raw)
        return {"format": fmt, "path": str(path), "rows": len(rows)}
