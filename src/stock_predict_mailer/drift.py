"""Feature drift between a model's training window and the current window.

Both windows are re-derived from stored snapshots, which means this module
*replays* historical rows. That is why it demands an explicit ``replay`` grant on
every snapshot it reads: revoking replay must stop the diagnostic immediately,
not just hide its output.
"""
from __future__ import annotations

import json

import numpy as np

from . import dataset_auth
from .calendar import market_context
from .contracts import FEATURE_ORDER, prepare_rows
from .core import Config, atomic_write, connect, digest, now
from .data import load_snapshot
from .model_registry import get_model, identifier, owner_key

DEFAULT_WINDOW_DAYS = 60
PSI_BINS = 10
PSI_EPSILON = 1e-6


def schema(con) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS drift_reports (
        drift_id TEXT PRIMARY KEY, owner TEXT NOT NULL, model_version TEXT NOT NULL,
        reference_snapshot TEXT NOT NULL, current_snapshot TEXT NOT NULL, cutoff TEXT NOT NULL,
        window_days INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
    """)


def _quantile_edges(reference: np.ndarray, bins: int = PSI_BINS) -> np.ndarray:
    probabilities = np.linspace(0.0, 1.0, bins + 1)[1:-1]
    edges = np.unique(np.quantile(reference, probabilities))
    return edges if edges.size else np.asarray([], dtype=float)


def _distribution(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    counts, _ = np.histogram(values, bins=np.concatenate(([-np.inf], edges, [np.inf])))
    shares = counts / max(counts.sum(), 1)
    return np.clip(shares, PSI_EPSILON, None)


def population_stability(reference: np.ndarray, current: np.ndarray) -> float:
    """PSI with bins fixed from the reference window, so it is deterministic."""
    edges = _quantile_edges(reference)
    expected = _distribution(reference, edges)
    actual = _distribution(current, edges)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def _matrix(rows: list[dict]) -> np.ndarray:
    return np.asarray([row["x"] for row in rows], dtype=float)


def _window_rows(cfg: Config, snapshot: str, contract: dict, cutoff: str, dates: list[str] | None) -> list[dict]:
    data_manifest, raw = load_snapshot(cfg, snapshot)
    sessions, actions = market_context(cfg, contract)
    _, rows = prepare_rows(raw, contract, cutoff, sessions=sessions, actions=actions)
    if dates is not None:
        keep = set(dates)
        rows = [row for row in rows if row["date"] in keep]
    return rows


def feature_drift(cfg: Config, model_version: str, snapshot: str, cutoff: str,
                  window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    if type(window_days) is not int or not 5 <= window_days <= 500:
        raise ValueError("window_days must be an integer in 5..500")
    manifest, _, _ = get_model(cfg, model_version)
    contract = manifest["contract"]
    reference_snapshot = manifest["training_snapshot"]
    # Replaying either window needs a current grant on both snapshots.
    dataset_auth.require(cfg, reference_snapshot, "replay")
    dataset_auth.require(cfg, snapshot, "replay")

    reference_rows = _window_rows(cfg, reference_snapshot, contract, manifest["training_cutoff"], None)
    reference_rows = [row for row in reference_rows if manifest["train_feature_start"] <= row["date"] <= manifest["train_feature_end"]]
    if len(reference_rows) < 20:
        raise ValueError("training window has too few feature rows to build stable reference bins")
    current_all = _window_rows(cfg, snapshot, contract, cutoff, None)
    if not current_all:
        raise ValueError("no feature-complete rows at the requested cutoff")
    days = sorted({row["date"] for row in current_all})[-window_days:]
    keep = set(days)
    current_rows = [row for row in current_all if row["date"] in keep]
    if len({row["security_id"] for row in current_rows}) < 3:
        raise ValueError("current window needs at least three securities")

    reference = _matrix(reference_rows)
    current = _matrix(current_rows)
    features = {}
    for index, name in enumerate(FEATURE_ORDER):
        base, live = reference[:, index], current[:, index]
        scale = float(np.std(base)) or 1.0
        features[name] = {"psi": population_stability(base, live),
                          "mean_reference": float(np.mean(base)), "mean_current": float(np.mean(live)),
                          "mean_shift_in_sd": float((np.mean(live) - np.mean(base)) / scale),
                          "std_ratio": float(np.std(live) / scale)}
    worst = max(features.items(), key=lambda item: item[1]["psi"])
    if worst[1]["psi"] >= 0.25:
        verdict = "major_shift"
    elif worst[1]["psi"] >= 0.1:
        verdict = "moderate_shift"
    else:
        verdict = "stable"
    identity = {"schema_version": 1, "owner": cfg.principal, "model_version": model_version,
                "reference_snapshot": reference_snapshot, "current_snapshot": snapshot,
                "cutoff": cutoff, "window_days": window_days}
    drift_id = digest(json.dumps(identity, sort_keys=True).encode())
    folder = cfg.workspace / "registry" / "drift" / owner_key(cfg.principal)
    path = folder / f"{identifier(drift_id)}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    report = {**identity, "drift_id": drift_id, "created_at": now(),
              "reference_rows": len(reference_rows), "current_rows": len(current_rows),
              "current_start": days[0], "current_end": days[-1],
              "features": features, "worst_feature": worst[0], "worst_psi": worst[1]["psi"],
              "verdict": verdict,
              "method": "PSI on reference quantile bins, bins fixed from the training window",
              "limitations": ["Drift is a description of the input distribution, not evidence that the model still works",
                              "A stable PSI does not rule out a change in the label relationship",
                              "The reference window is replayed from the training snapshot, so a revoked replay grant blocks this report"]}
    raw = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    atomic_write(path, raw)
    with connect(cfg) as con:
        schema(con)
        con.execute("INSERT OR REPLACE INTO drift_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (drift_id, cfg.principal, model_version, reference_snapshot, snapshot, cutoff,
                     window_days, digest(raw), report["created_at"]))
    return report


def drift_history(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        schema(con)
        rows = con.execute("""SELECT drift_id, model_version, reference_snapshot, current_snapshot,
            cutoff, window_days, created_at FROM drift_reports WHERE owner=? ORDER BY created_at DESC""",
                           (cfg.principal,)).fetchall()
    return [dict(row) for row in rows]
