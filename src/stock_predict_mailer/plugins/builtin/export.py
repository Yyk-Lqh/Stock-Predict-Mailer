"""Built-in dataset exporters.

Every exporter writes the columns the snapshot already validated, in the same
order. None of them renames, reorders or coerces: the format decides the
encoding, never the meaning.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

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
