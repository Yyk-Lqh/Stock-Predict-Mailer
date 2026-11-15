"""Disclosed-by-cutoff exports, without claiming historical point-in-time accuracy."""
import csv
import io
from datetime import date

from .quality import DataQualityError, code_of, cutoff_date, number, previous_quarter, utc_now, write_snapshot


def normalize_row(row, metrics):
    result = dict(row)
    result["code"] = code_of(row.get("code"))
    try:
        report = date.fromisoformat(row.get("report_date", ""))
        if report.isoformat()[5:] not in ("03-31", "06-30", "09-30", "12-31"):
            raise ValueError()
        pub = row.get("pubDate", "")
        if pub and date.fromisoformat(pub) < report:
            raise ValueError()
    except (TypeError, ValueError) as exc:
        raise DataQualityError("INVALID_DATA", "基本面报告期或披露日期无效") from exc
    for field in metrics:
        result[field] = number(row.get(field))
    result["publication_verified"] = row.get("publication_verified") in (True, "True", "true")
    return result


def write_cutoff_view(path, rows, as_of, names, run_metadata):
    cutoff = cutoff_date(as_of)
    year, quarter = previous_quarter(cutoff.isoformat())
    last_period = (year, quarter)
    selected, excluded = {}, {"missing_disclosure": 0, "after_cutoff": 0}
    for row in rows:
        row = normalize_row(row, [key for key in names if key != "pubDate"])
        pub = row.get("pubDate")
        report = date.fromisoformat(row["report_date"])
        if not pub or not row["publication_verified"]:
            excluded["missing_disclosure"] += 1
        elif date.fromisoformat(pub) > cutoff or (report.year, (report.month - 1) // 3 + 1) > last_period:
            excluded["after_cutoff"] += 1
        else:
            selected[(row["code"], row["report_date"])] = row
    fields = ["code", "report_date", *names.values(), "publication_verified", "collected_at", "provider_symbol"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for key in sorted(selected):
        row = selected[key]
        renamed = {names.get(k, k): value for k, value in row.items()}
        writer.writerow({field: renamed.get(field) for field in fields})
    metadata = dict(run_metadata, source="baostock", generated_at=utc_now().isoformat(), fetched_at=None,
                    request_as_of=cutoff.isoformat(), date_policy=run_metadata.get("date_policy", "historical_cutoff"),
                    report_end_quarter=f"{year}Q{quarter}", row_count=len(selected), excluded=excluded,
                    point_in_time_verified=False, historical_pool_verified=False,
                    source_as_of=None, value_units="provider_native_per_field")
    return write_snapshot(path, output.getvalue().encode("utf-8-sig"), metadata)
