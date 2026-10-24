"""Synthetic-only research harness. No claims of market execution fidelity."""
from __future__ import annotations

import json
import pickle
import platform
import subprocess
from importlib.metadata import version
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import rankdata
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .core import Config, atomic_write, digest, now, timestamp, write_json
from .data import asof_rows, load_snapshot

FEATURES = ("return_1", "return_5", "return_20", "volatility_20", "relative_volume")


def feature_rows(rows: list[dict], cfg: Config) -> list[dict]:
    by_security = defaultdict(list)
    for row in rows:
        by_security[row["security_id"]].append(row)
    result = []
    for security, bars in by_security.items():
        bars.sort(key=lambda r: r["date"])
        for i in range(20, len(bars)):
            cutoff = datetime.combine(datetime.fromisoformat(bars[i]["date"]).date(), time(20), ZoneInfo(cfg.timezone))
            window = bars[i - 20:i + 1]
            if any(timestamp(r["available_at"]) > cutoff for r in window):
                continue
            close = np.array([r["close"] for r in window], dtype=float)
            volume = np.array([r["volume"] for r in window], dtype=float)
            x = [close[-1] / close[-2] - 1, close[-1] / close[-6] - 1,
                 close[-1] / close[0] - 1, np.std(np.diff(np.log(close))),
                 volume[-1] / max(float(np.mean(volume[:-1])), 1.0)]
            result.append({"date": bars[i]["date"], "security_id": security,
                           "cutoff": cutoff.isoformat(), "x": x})
    return sorted(result, key=lambda r: (r["date"], r["security_id"]))


def label_rows(rows: list[dict], features: list[dict], horizon: int) -> list[dict]:
    dates = sorted({r["date"] for r in rows})
    index = {day: i for i, day in enumerate(dates)}
    lookup = {(r["date"], r["security_id"]): r for r in rows}
    result = []
    for feature in features:
        i = index[feature["date"]]
        if i + horizon + 1 >= len(dates):
            continue
        entry_day, exit_day = dates[i + 1], dates[i + horizon + 1]
        entry = lookup.get((entry_day, feature["security_id"]))
        exit_bar = lookup.get((exit_day, feature["security_id"]))
        if entry is None or exit_bar is None:
            continue
        result.append({**feature, "entry_date": entry_day, "label_end": exit_day,
                       "gross_return": exit_bar["open"] / entry["open"] - 1})
    # Synthetic equal-weight benchmark. Not an externally licensed index.
    grouped = defaultdict(list)
    for row in result:
        grouped[row["date"]].append(row)
    for group in grouped.values():
        benchmark = float(np.mean([r["gross_return"] for r in group]))
        for row in group:
            row["benchmark_return"] = benchmark
            row["y"] = row["gross_return"] - benchmark
    return result


def purged_before(rows: list[dict], boundary: str) -> list[dict]:
    return [r for r in rows if r["date"] < boundary and r["label_end"] < boundary]


def estimator(kind: str):
    if kind == "ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=100.0))
    if kind == "lightgbm":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(n_estimators=100, num_leaves=7, max_depth=3, min_child_samples=100,
                             learning_rate=0.03, n_jobs=2, random_state=42, verbosity=-1)
    raise ValueError("unknown estimator")


def fit_model(kind: str, rows: list[dict]):
    if kind in ("zero", "momentum"):
        return None
    model = estimator(kind)
    model.fit(np.array([r["x"] for r in rows]), np.array([r["y"] for r in rows]))
    return model


def predict(kind: str, model, rows: list[dict]) -> np.ndarray:
    if kind == "zero":
        return np.zeros(len(rows))
    if kind == "momentum":
        return np.array([r["x"][2] for r in rows])
    return model.predict(np.array([r["x"] for r in rows]))


def metrics(rows: list[dict], scores: np.ndarray) -> dict:
    groups = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        groups[row["date"]].append((row["y"], float(score)))
    ics = []
    for group in groups.values():
        target, predicted = np.array(group).T
        if len(group) >= 3 and np.std(predicted) > 0 and np.std(target) > 0:
            ics.append(float(np.corrcoef(rankdata(target), rankdata(predicted))[0, 1]))
    return {"mae": float(np.mean(np.abs(np.array([r["y"] for r in rows]) - scores))),
            "rank_ic": float(np.mean(ics)) if ics else None,
            "days": len(groups), "rows": len(rows)}


def cost_diagnostics(rows: list[dict], scores: np.ndarray, cfg: Config) -> list[dict]:
    groups = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        groups[row["date"]].append({**row, "score": float(score)})
    costs = sorted({10.0, float(cfg.cost_bps), 50.0})
    selected_returns = []
    next_entry = ""
    for day in sorted(groups):
        cohort = groups[day]
        if cohort[0]["entry_date"] < next_entry:
            continue
        top = sorted(cohort, key=lambda r: (-r["score"], r["security_id"]))[:cfg.top_k]
        selected_returns.append(float(np.mean([r["y"] for r in top])))
        next_entry = cohort[0]["label_end"]
    return [{"round_trip_cost_bps": cost, "cohorts": len(selected_returns),
             "mean_net_excess_return": float(np.mean(selected_returns)) - cost / 10000}
            for cost in costs]


def experiment(cfg: Config, snapshot: str, cutoff: str, *, trees: bool = False, allow_unverified_real: bool = False) -> dict:
    manifest, raw = load_snapshot(cfg, snapshot)
    if not manifest["synthetic"] and not allow_unverified_real:
        raise ValueError("real-data research is gated until corporate actions, calendar and universe are certified")
    rows = asof_rows(raw, cutoff)
    features = feature_rows(rows, cfg)
    labelled = label_rows(rows, features, cfg.horizon)
    dates = sorted({r["date"] for r in labelled})
    if len(dates) < 100:
        raise ValueError("at least 100 labelled dates required")
    val_start, test_start = dates[int(len(dates) * 0.6)], dates[int(len(dates) * 0.8)]
    train = purged_before(labelled, val_start)
    validation = [r for r in labelled if val_start <= r["date"] < test_start and r["label_end"] < test_start]
    test = [r for r in labelled if r["date"] >= test_start]
    kinds = ["zero", "momentum", "ridge"] + (["lightgbm"] if trees else [])
    val_metrics = {}
    for kind in kinds:
        val_metrics[kind] = metrics(validation, predict(kind, fit_model(kind, train), validation))
    # Selection on validation only. Zero remains eligible: avoid forcing a signal.
    selected = max(kinds, key=lambda k: val_metrics[k]["rank_ic"] if val_metrics[k]["rank_ic"] is not None else 0.0)
    development = purged_before(labelled, test_start)
    holdout_model = fit_model(selected, development)
    test_scores = predict(selected, holdout_model, test)
    rolling = []
    dev_dates = sorted({r["date"] for r in development})
    for fraction in (0.5, 0.65, 0.8):
        start = dev_dates[int(len(dev_dates) * fraction)]
        end_index = min(int(len(dev_dates) * (fraction + 0.15)), len(dev_dates) - 1)
        end = dev_dates[end_index]
        history = purged_before(development, start)
        future = [r for r in development if start <= r["date"] < end and r["label_end"] < end]
        if future:
            rolling.append({"start": start, "end_exclusive": end,
                            **metrics(future, predict(selected, fit_model(selected, history), future))})
    # Deployment fit may include holdout after evaluation; keep artifacts distinct.
    live_model = fit_model(selected, labelled)
    latest = max(r["date"] for r in features)
    latest_features = [r for r in features if r["date"] == latest]
    latest_scores = predict(selected, live_model, latest_features)
    rankings = sorted([{"security_id": r["security_id"], "score": float(s), "date": r["date"]}
                       for r, s in zip(latest_features, latest_scores, strict=True)], key=lambda r: (-r["score"], r["security_id"]))
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unavailable"
    definition = {"snapshot": snapshot, "cutoff": cutoff, "horizon": cfg.horizon,
                  "top_k": cfg.top_k, "cost_bps": cfg.cost_bps, "trees": trees,
                  "allow_unverified_real": allow_unverified_real,
                  "features": FEATURES, "code_commit": commit, "schema": 1,
                  "timezone": cfg.timezone,
                  "source_sha256": digest(b"".join(p.name.encode() + p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))),
                  "dependencies": {name: version(name) for name in ("numpy", "scikit-learn", "duckdb", "pyarrow")}}
    if trees:
        definition["dependencies"]["lightgbm"] = version("lightgbm")
    experiment_id = digest(json.dumps(definition, sort_keys=True).encode())
    folder = cfg.workspace / "experiments" / experiment_id
    payload = pickle.dumps(live_model)
    atomic_write(folder / "deployment_model.pkl", payload)
    evaluation_payload = pickle.dumps(holdout_model)
    atomic_write(folder / "holdout_model.pkl", evaluation_payload)
    result = {"experiment_id": experiment_id, "created_at": now(), "synthetic": manifest["synthetic"],
              "unverified_real": not manifest["synthetic"],
              "definition": definition, "python": platform.python_version(),
              "selected": selected, "validation": val_metrics,
              "holdout": metrics(test, test_scores), "rolling_development_diagnostics": rolling,
              "split": {"validation_start": val_start, "test_start": test_start,
                        "train_max_label_end": max(r["label_end"] for r in train),
                        "development_max_label_end": max(r["label_end"] for r in development)},
              "cost_diagnostics": cost_diagnostics(test, test_scores, cfg),
              "predictions": rankings, "latest_data_date": latest,
              "model_sha256": digest(payload), "holdout_model_sha256": digest(evaluation_payload),
              "limitations": ["SYNTHETIC DATA ONLY" if manifest["synthetic"] else "UNVERIFIED REAL DATA: research only, not a certified strategy",
                 "No corporate action, point-in-time universe or exchange calendar certification",
                 "Horizon uses observed dataset dates; missing market dates may distort real-data labels",
                 "Cost diagnostics are nonoverlapping top-K excess returns, not an executable backtest",
                 "No volume limits, suspension, limit-up/down or market-specific execution rules",
                 "Rolling diagnostics share model selection history and are not an independent holdout",
                 "Deployment model refits all matured labels after holdout evaluation",
                 "No probability calibration or verified predictive advantage"]}
    write_json(folder / "result.json", result)
    return result
