"""Residual adaptation on top of a frozen parent model.

This is **not** weight fine-tuning. The parent stays byte-identical; a small
adapter is fitted on the parent's residuals and added to its score at prediction
time. Two rules make the result honest:

* only dates strictly after ``parent.train_label_end`` are used, so the adapter
  never fits a row the parent already memorised;
* the adapter is validated by time-ordered cross-fitting with a purge gap of one
  horizon, so the reported out-of-sample number comes from dates the adapter
  itself never saw.

The comparison that decides whether the adapter is worth anything is a separate
command (``model-compare``) against a same-recipe retrain on the same test window.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

from . import dataset_auth
from .calendar import market_context
from .contracts import contract_id, dataset_compatible, prepare_rows, validate_contract
from .core import Config, atomic_write, connect, digest, now, write_json
from .data import load_snapshot
from .model_registry import get_model, model_scores, personal_model_folder
from .model_registry import schema as registry_schema
from .native_models import ARTIFACTS, DERIVED

MIN_FIT_DATES = 40
MIN_FIT_SECURITIES = 3
MIN_FOLDS = 3
MAX_FOLDS = 8
DEFAULT_FOLDS = 4
DEFAULT_ALPHA = 10.0
PURGE_DAYS = 1  # one label horizon of embargo between folds


def _standardise(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    return mean, scale


def _ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, float]:
    design = np.hstack([x, np.ones((x.shape[0], 1))])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[-1, -1] = 0.0  # never penalise the intercept
    solution = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return solution[:-1], float(solution[-1])


def _daily_rank_ic(rows: list[dict], scores: np.ndarray) -> dict[str, float]:
    groups: dict[str, list[tuple[float, float]]] = {}
    for row, score in zip(rows, scores, strict=True):
        groups.setdefault(row["date"], []).append((row["y"], float(score)))
    result = {}
    for day, group in groups.items():
        if len(group) < 3:
            continue
        target, predicted = np.array(group).T
        if np.std(predicted) > 0 and np.std(target) > 0:
            result[day] = float(np.corrcoef(rankdata(target), rankdata(predicted))[0, 1])
    return result


def _folds(dates: list[str], count: int) -> list[list[str]]:
    """Contiguous date blocks, so every fold is a genuine forward period."""
    return [block.tolist() for block in np.array_split(np.asarray(dates), count) if block.size]


def fit_residual_adapter(cfg: Config, parent_version: str, snapshot: str, cutoff: str, *,
                         folds: int = DEFAULT_FOLDS, alpha: float = DEFAULT_ALPHA,
                         shrink: float = 1.0, allow_unverified_real: bool = False) -> dict:
    if type(folds) is not int or not MIN_FOLDS <= folds <= MAX_FOLDS:
        raise ValueError(f"folds must be an integer in {MIN_FOLDS}..{MAX_FOLDS}")
    if not 0.0 < alpha <= 1e6:
        raise ValueError("alpha must be a positive regularisation strength")
    if not 0.0 < shrink <= 1.0:
        raise ValueError("shrink must be in (0, 1]; a full adapter is 1.0")
    parent, parent_payload, parent_state = get_model(cfg, parent_version)
    if parent["algorithm"] in DERIVED:
        raise ValueError("stacking adapters on adapters is not supported; adapt to an original parent model")
    if parent_state["status"] not in ("published", "ready"):
        raise ValueError("parent model must be a published demo or a completed personal version")
    dataset_auth.require(cfg, snapshot, "personal_training")
    data_manifest, raw = load_snapshot(cfg, snapshot)
    contract = validate_contract(parent["contract"])
    dataset_compatible(data_manifest, contract, allow_unverified_real)
    sessions, actions = market_context(cfg, contract)
    _, all_rows = prepare_rows(raw, contract, cutoff, sessions=sessions, actions=actions)
    boundary = parent["train_label_end"]
    rows = [row for row in all_rows if row["date"] > boundary]
    dates = sorted({row["date"] for row in rows})
    securities = {row["security_id"] for row in rows}
    if len(dates) < MIN_FIT_DATES or len(securities) < MIN_FIT_SECURITIES:
        raise ValueError(f"adapter needs at least {MIN_FIT_DATES} matured dates after the parent label end "
                         f"({boundary}) and {MIN_FIT_SECURITIES} securities; got {len(dates)} dates and "
                         f"{len(securities)} securities")
    x = np.asarray([row["x"] for row in rows], dtype=float)
    residual = np.asarray([row["y"] for row in rows], dtype=float) - np.asarray(
        model_scores(cfg, parent, parent_payload, rows), dtype=float)
    if not np.isfinite(residual).all():
        raise ValueError("parent produced nonfinite scores on the adapter window")

    # ---- time-ordered cross-fitting: every fold is predicted by an adapter
    # ---- fitted only on earlier-or-later blocks minus a one-horizon purge.
    blocks = _folds(dates, folds)
    fold_reports = []
    oos_scores = np.full(len(rows), np.nan)
    for index, block in enumerate(blocks):
        held = set(block)
        start = block[0]
        train_index = [i for i, row in enumerate(rows)
                       if row["date"] not in held and row["label_end"] < start]
        test_index = [i for i, row in enumerate(rows) if row["date"] in held]
        if len(train_index) < 50 or not test_index:
            fold_reports.append({"fold": index, "start": start, "end": block[-1], "status": "skipped",
                                 "reason": "not enough purged training rows before this block"})
            continue
        mean, scale = _standardise(x[train_index])
        coef, intercept = _ridge((x[train_index] - mean) / scale, residual[train_index], alpha)
        predicted = ((x[test_index] - mean) / scale) @ coef + intercept
        oos_scores[test_index] = predicted
        fold_reports.append({"fold": index, "start": start, "end": block[-1], "status": "fitted",
                             "train_rows": len(train_index), "test_rows": len(test_index),
                             "purge_before": start})
    covered = ~np.isnan(oos_scores)
    if covered.sum() < 60:
        raise ValueError("cross-fitting produced too few out-of-sample rows; extend the window or reduce folds")
    fold_rows = [row for row, keep in zip(rows, covered, strict=True) if keep]
    base_scores = np.asarray(model_scores(cfg, parent, parent_payload, fold_rows), dtype=float)
    adapted_scores = base_scores + shrink * oos_scores[covered]
    base_ic, adapted_ic = _daily_rank_ic(fold_rows, base_scores), _daily_rank_ic(fold_rows, adapted_scores)
    common = sorted(set(base_ic) & set(adapted_ic))
    if len(common) < 20:
        raise ValueError("cross-fitting needs at least 20 comparable dates to report an out-of-sample estimate")

    # ---- final adapter on the whole window the parent never saw
    mean, scale = _standardise(x)
    coef, intercept = _ridge((x - mean) / scale, residual, alpha)
    adapter = {"schema_version": 1, "features": contract["features"],
               "mean": mean.tolist(), "scale": scale.tolist(),
               "coef": (coef * shrink).tolist(), "intercept": float(intercept * shrink),
               "shrink": shrink, "alpha": alpha,
               "fit_start": dates[0], "fit_end": dates[-1], "fit_rows": len(rows),
               "parent_train_label_end": boundary,
               "method": "frozen parent plus ridge residual adapter"}
    payload = json.dumps(adapter, sort_keys=True, allow_nan=False).encode("utf-8")
    version = digest(uuid.uuid4().bytes)
    manifest = {
        "schema_version": 1, "version": version, "created_at": now(),
        "algorithm": "residual", "artifact": ARTIFACTS["residual"], "artifact_sha256": digest(payload),
        "contract": contract, "contract_id": contract_id(contract),
        "training_snapshot": snapshot, "training_cutoff": cutoff,
        "train_feature_start": dates[0], "train_feature_end": dates[-1],
        "train_label_end": max(row["label_end"] for row in rows), "training_rows": len(rows),
        "synthetic": bool(data_manifest["synthetic"]), "unverified_real": not data_manifest["synthetic"],
        "data_provenance": data_manifest.get("provenance", {}),
        "calendar_mode": "certified" if sessions else "benchmark_observed",
        "corporate_actions_applied": bool(actions),
        "scope": "personal", "owner": cfg.principal, "parent_version": parent_version,
        "residual_of": parent_version, "method": "residual_adapter",
        "parent_artifact_sha256": parent["artifact_sha256"],
        "cross_fit": {"folds": folds, "purge_days": PURGE_DAYS, "folds_detail": fold_reports,
                      "oos_rows": int(covered.sum()), "oos_dates": len(common),
                      "rank_ic_before": float(np.mean([base_ic[day] for day in common])),
                      "rank_ic_after": float(np.mean([adapted_ic[day] for day in common])),
                      "note": "out-of-sample estimate from time-ordered folds; the final adapter is refitted on the full window"},
        "implementation_sha256": digest(b"".join(p.name.encode() + p.read_bytes()
                                                 for p in sorted(Path(__file__).parent.glob("*.py")))),
        "limitations": ["The adapter corrects the parent's residuals; it never changes parent weights",
                        "Only dates after the parent training label end are used, so no leakage into the parent window",
                        "The cross-fitted estimate is not a market-constrained backtest",
                        "A residual adapter is not a new algorithm and must be compared against a same-recipe retrain"],
    }
    folder = personal_model_folder(cfg, cfg.principal, version)
    atomic_write(folder / ARTIFACTS["residual"], payload)
    write_json(folder / "manifest.json", manifest)
    with connect(cfg) as con:
        registry_schema(con)
        con.execute("INSERT INTO registry_models VALUES (?, ?, ?, 'personal', 'trained', 'ready', NULL, ?, NULL)",
                    (version, cfg.principal, cfg.principal, digest((folder / "manifest.json").read_bytes())))
    return {"model_version": version, "parent_version": parent_version, "status": "ready",
            "scope": "personal", "fit_dates": len(dates), "fit_rows": len(rows),
            "fit_start": dates[0], "fit_end": dates[-1], "parent_train_label_end": boundary,
            "cross_fit": manifest["cross_fit"], "auto_switched": False,
            "next_step": "compare it with a same-recipe retrain via model-compare before selecting"}


def residual_scores(cfg: Config, manifest: dict, payload: bytes, rows: list[dict]) -> np.ndarray:
    """Parent score plus the stored adapter; the parent payload is re-verified on load."""
    from .native_models import native_predict

    adapter = json.loads(payload)
    if adapter.get("schema_version") != 1 or adapter.get("features") != manifest["contract"]["features"]:
        raise ValueError("residual adapter metadata mismatch")
    parent, parent_payload, _ = get_model(cfg, manifest["residual_of"])
    if parent["artifact_sha256"] != manifest["parent_artifact_sha256"]:
        raise ValueError("parent artifact changed after the adapter was fitted")
    if date.fromisoformat(adapter["fit_start"]) <= date.fromisoformat(parent["train_label_end"]):
        raise ValueError("adapter window overlaps the parent training window")
    x = np.asarray([row["x"] for row in rows], dtype=float)
    mean = np.asarray(adapter["mean"], dtype=float)
    scale = np.asarray(adapter["scale"], dtype=float)
    coef = np.asarray(adapter["coef"], dtype=float)
    if not all(array.shape == (len(manifest["contract"]["features"]),) for array in (mean, scale, coef)):
        raise ValueError("invalid residual adapter state")
    if np.any(scale <= 0) or not np.isfinite(adapter["intercept"]):
        raise ValueError("invalid residual adapter scale or intercept")
    base = np.asarray(native_predict(parent["algorithm"], parent_payload, rows), dtype=float)
    scores = base + (((x - mean) / scale) @ coef + float(adapter["intercept"]))
    if not np.isfinite(scores).all():
        raise ValueError("residual adapter produced nonfinite predictions")
    return scores
