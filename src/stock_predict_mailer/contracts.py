"""Versioned feature/target contract for published models, independent of upload universe."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from .core import digest, timestamp

FEATURE_ORDER = ("return_1", "return_5", "return_20", "volatility_20", "relative_volume")
KEYS = {"schema_version", "market", "benchmark_id", "universe", "features", "horizon", "timezone",
        "feature_cutoff", "price_basis", "volume_unit", "calendar", "target"}


def validate_contract(raw: dict) -> dict:
    if not isinstance(raw, dict) or set(raw) != KEYS:
        raise ValueError("task contract has missing or unsupported fields")
    result = json.loads(json.dumps(raw, allow_nan=False))
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise ValueError("unsupported contract schema")
    if result["features"] != list(FEATURE_ORDER):
        raise ValueError("feature order or feature implementation is incompatible")
    if type(result["horizon"]) is not int or not 1 <= result["horizon"] <= 60:
        raise ValueError("horizon must be an integer in 1..60")
    for key in ("market", "benchmark_id"):
        if not isinstance(result[key], str) or not result[key].strip() or len(result[key]) > 100:
            raise ValueError(f"invalid {key}")
    universe = result["universe"]
    if not isinstance(universe, list) or not 3 <= len(universe) <= 2000 or any(not isinstance(v, str) or not v.strip() for v in universe):
        raise ValueError("contract needs 3..2000 distinct nonempty security ids")
    if len(set(universe)) != len(universe) or result["benchmark_id"] in universe:
        raise ValueError("universe must be unique and exclude the benchmark")
    result["universe"] = sorted(universe)
    ZoneInfo(result["timezone"])
    cutoff = time.fromisoformat(result["feature_cutoff"])
    if cutoff.tzinfo is not None:
        raise ValueError("feature_cutoff uses the contract timezone")
    if result["price_basis"] not in ("unadjusted", "forward_adjusted", "backward_adjusted", "total_return") or result["volume_unit"] != "shares":
        raise ValueError("explicit supported price basis and shares volume required")
    if result["calendar"] != "benchmark_sessions" or result["target"] != "open_to_open_excess_return":
        raise ValueError("unsupported calendar or target")
    return result


def contract_id(contract: dict) -> str:
    return digest(json.dumps(validate_contract(contract), sort_keys=True, separators=(",", ":")).encode())


def read_contract(path: Path) -> dict:
    return validate_contract(json.loads(path.read_text(encoding="utf-8")))


def prepare_rows(raw: list[dict], contract: dict, cutoff: str) -> tuple[list[dict], list[dict]]:
    contract = validate_contract(contract)
    instant = timestamp(cutoff)
    zone = ZoneInfo(contract["timezone"])
    last_date = instant.astimezone(zone).date().isoformat()
    rows = [row for row in raw if row["date"] <= last_date and timestamp(row["available_at"]) <= instant]
    lookup = {(r["date"], r["security_id"]): r for r in rows}
    calendar = sorted({r["date"] for r in rows if r["security_id"] == contract["benchmark_id"]})
    if not calendar:
        raise ValueError("fixed benchmark is missing; cannot infer a benchmark from uploaded stocks")
    feature_time = time.fromisoformat(contract["feature_cutoff"])
    features, labelled = [], []
    for i in range(20, len(calendar)):
        day = calendar[i]
        feature_cutoff = datetime.combine(date.fromisoformat(day), feature_time, zone)
        if feature_cutoff > instant:
            continue
        for security in contract["universe"]:
            window = [lookup.get((d, security)) for d in calendar[i - 20:i + 1]]
            if any(r is None or timestamp(r["available_at"]) > feature_cutoff for r in window):
                continue
            close = np.array([r["close"] for r in window], dtype=float)
            volumes = np.array([r["volume"] for r in window], dtype=float)
            x = [close[-1] / close[-2] - 1, close[-1] / close[-6] - 1,
                 close[-1] / close[0] - 1, float(np.std(np.diff(np.log(close)))),
                 volumes[-1] / max(float(np.mean(volumes[:-1])), 1.0)]
            feature = {"date": day, "security_id": security, "cutoff": feature_cutoff.isoformat(), "x": x}
            features.append(feature)
            end = i + contract["horizon"] + 1
            if end >= len(calendar):
                continue
            entry_day, exit_day = calendar[i + 1], calendar[end]
            entry, exit_bar = lookup.get((entry_day, security)), lookup.get((exit_day, security))
            if entry is None or exit_bar is None:
                continue
            benchmark_entry = lookup[(entry_day, contract["benchmark_id"])]
            benchmark_exit = lookup[(exit_day, contract["benchmark_id"])]
            gross = exit_bar["open"] / entry["open"] - 1
            reference = benchmark_exit["open"] / benchmark_entry["open"] - 1
            labelled.append({**feature, "entry_date": entry_day, "label_end": exit_day,
                             "gross_return": gross, "benchmark_return": reference, "y": gross - reference})
    return features, labelled


def dataset_compatible(manifest: dict, contract: dict, allow_unverified_real: bool = False) -> None:
    if bool(manifest["synthetic"]) != (contract["market"] == "synthetic"):
        raise ValueError("synthetic/real dataset does not match the contract market")
    if not manifest["synthetic"] and not allow_unverified_real:
        raise ValueError("real data requires explicit exploratory allowance; stable certification is not implemented")
    provenance = manifest.get("provenance", {})
    for field in ("price_basis", "volume_unit"):
        value = provenance.get(field)
        if value and value != "unknown" and value != contract[field]:
            raise ValueError(f"dataset {field} conflicts with the task contract")
