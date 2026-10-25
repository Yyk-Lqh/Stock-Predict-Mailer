"""Owner-scoped private training queue, single local worker and paired comparison.

Design boundaries:

* the persisted spec is immutable and carries parent version, snapshot, contract,
  split and budget, so a retry cannot silently change the recipe;
* one worker claims one job at a time and runs it in a sanitized child process;
  the child only writes its staging folder, the parent promotes the artifact into
  the owner's namespace;
* a finished candidate is never selected automatically, and every comparison is
  restricted to matured dates later than both models' training label ends.

The configured principal is a trusted local operator identity, not web
authentication, so this queue must not be exposed as a multi-user service.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time as clock
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

from . import dataset_auth
from .contracts import contract_id, dataset_compatible, prepare_rows, validate_contract
from .core import Config, atomic_write, connect, digest, now, timestamp, write_json
from .data import load_snapshot
from .model_registry import get_model, identifier, owner_key, personal_model_folder, schema as registry_schema
from .native_models import ALGORITHMS, native_predict
from .research import metrics

MIN_TRAIN_DATES = 60
MIN_TRAIN_SECURITIES = 3
MIN_COMPARE_DATES = 30
MIN_TIMEOUT_SECONDS = 2
MAX_TIMEOUT_SECONDS = 3600
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_ROWS = 200_000
MAX_ROWS_LIMIT = 2_000_000
STALE_HEARTBEAT_SECONDS = 120
METHODS = ("full_retrain",)


def schema(con) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS training_specs (
        spec_id TEXT PRIMARY KEY, owner TEXT NOT NULL, spec_sha256 TEXT NOT NULL,
        parent_version TEXT NOT NULL, snapshot_id TEXT NOT NULL, contract_id TEXT NOT NULL,
        contract TEXT NOT NULL, method TEXT NOT NULL, algorithm TEXT NOT NULL,
        train_cutoff TEXT NOT NULL, max_seconds INTEGER NOT NULL, max_rows INTEGER NOT NULL,
        allow_unverified_real INTEGER NOT NULL, created_at TEXT NOT NULL,
        UNIQUE (owner, spec_sha256));
      CREATE TABLE IF NOT EXISTS training_jobs (
        job_id TEXT PRIMARY KEY, spec_id TEXT NOT NULL, owner TEXT NOT NULL,
        status TEXT NOT NULL, stage TEXT NOT NULL, progress TEXT,
        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, heartbeat_at TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0, worker_pid INTEGER,
        error_category TEXT, error_message TEXT, result_version TEXT, result_sha256 TEXT);
      CREATE TABLE IF NOT EXISTS model_comparisons (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, candidate TEXT NOT NULL, baseline TEXT NOT NULL,
        snapshot_id TEXT NOT NULL, cutoff TEXT NOT NULL, verdict TEXT NOT NULL,
        sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
    """)


def training_folder(cfg: Config, owner: str, job_id: str) -> Path:
    return cfg.workspace / "registry" / "training" / owner_key(owner) / identifier(job_id)


def _row(cfg: Config, sql: str, args: tuple) -> dict | None:
    with connect(cfg) as con:
        schema(con)
        row = con.execute(sql, args).fetchone()
    return dict(row) if row is not None else None


def _rows(cfg: Config, sql: str, args: tuple) -> list[dict]:
    with connect(cfg) as con:
        schema(con)
        return [dict(row) for row in con.execute(sql, args)]


def _update(cfg: Config, job_id: str, **fields) -> None:
    allowed = {"status", "stage", "progress", "started_at", "finished_at", "heartbeat_at",
               "cancel_requested", "worker_pid", "error_category", "error_message",
               "result_version", "result_sha256"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unsupported job fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{name}=?" for name in fields)
    with connect(cfg) as con:
        schema(con)
        con.execute(f"UPDATE training_jobs SET {assignments} WHERE job_id=?", (*fields.values(), job_id))


def _visible_job(cfg: Config, job_id: str, *, prefix: str = "") -> dict:
    job = _row(cfg, "SELECT * FROM training_jobs WHERE job_id=? AND owner=?", (identifier(job_id), cfg.principal))
    if job is None:
        raise ValueError(f"unknown{prefix} training job for this identity")
    return job


def _spec(cfg: Config, spec_id: str) -> dict:
    spec = _row(cfg, "SELECT * FROM training_specs WHERE spec_id=?", (spec_id,))
    if spec is None:
        raise ValueError("training job has no persisted spec")
    return spec


def submit_training(cfg: Config, parent_version: str, snapshot: str, cutoff: str, *, method: str = "full_retrain",
                    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS, max_rows: int = DEFAULT_MAX_ROWS,
                    allow_unverified_real: bool = False) -> dict:
    if method not in METHODS:
        raise ValueError("only same-recipe full retraining is implemented; residual adaptation needs time "
                         "cross-fitting and is not part of this batch")
    if type(timeout_seconds) is not int or not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout budget must be an integer in {MIN_TIMEOUT_SECONDS}..{MAX_TIMEOUT_SECONDS} seconds")
    if type(max_rows) is not int or not 1000 <= max_rows <= MAX_ROWS_LIMIT:
        raise ValueError(f"row budget must be an integer in 1000..{MAX_ROWS_LIMIT}")
    timestamp(cutoff)
    parent, _, state = get_model(cfg, parent_version)
    if state["status"] not in ("published", "ready"):
        raise ValueError("parent model must be a published demo or a completed personal version")
    if state["status"] == "published" and state["channel"] != "demo":
        raise ValueError("only demo-channel parents are supported")
    dataset_auth.require(cfg, snapshot, "personal_training")
    data_manifest, raw = load_snapshot(cfg, snapshot)
    dataset_compatible(data_manifest, parent["contract"], allow_unverified_real)
    features, rows = prepare_rows(raw, parent["contract"], cutoff)
    dates = {row["date"] for row in rows}
    securities = {row["security_id"] for row in rows}
    if len(dates) < MIN_TRAIN_DATES or len(securities) < MIN_TRAIN_SECURITIES:
        raise ValueError(f"training needs at least {MIN_TRAIN_DATES} matured feature dates and "
                         f"{MIN_TRAIN_SECURITIES} securities; got {len(dates)} dates and {len(securities)} securities")
    if len(rows) > max_rows:
        raise ValueError("training matrix exceeds the declared row budget; split the window or raise --max-rows")
    contract = validate_contract(parent["contract"])
    spec = {"schema_version": 1, "owner": cfg.principal, "parent_version": parent_version,
            "snapshot_id": snapshot, "contract": contract, "contract_id": contract_id(contract),
            "method": method, "algorithm": parent["algorithm"], "train_cutoff": cutoff,
            "max_seconds": timeout_seconds, "max_rows": max_rows,
            "allow_unverified_real": bool(allow_unverified_real),
            "parent_train_label_end": parent["train_label_end"],
            "synthetic": bool(data_manifest["synthetic"])}
    spec_sha256 = digest(json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    existing_spec = _row(cfg, "SELECT * FROM training_specs WHERE owner=? AND spec_sha256=?", (cfg.principal, spec_sha256))
    spec_id = existing_spec["spec_id"] if existing_spec else digest(uuid.uuid4().bytes)
    job_id = digest(uuid.uuid4().bytes)
    warnings = []
    if parent["train_label_end"] >= max(dates):
        warnings.append("training window ends at or before the parent label end; a later common test window is required before comparison")
    if len(features) == 0:
        warnings.append("no feature rows were prepared; prediction after training may be limited")
    with connect(cfg) as con:
        schema(con)
        registry_schema(con)
        con.execute("BEGIN IMMEDIATE")
        if existing_spec is None:
            con.execute("""INSERT INTO training_specs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (spec_id, cfg.principal, spec_sha256, parent_version, snapshot, spec["contract_id"],
                         json.dumps(contract, sort_keys=True), method, spec["algorithm"], cutoff,
                         timeout_seconds, max_rows, int(bool(allow_unverified_real)), now()))
        previous = con.execute("""SELECT job_id, status FROM training_jobs WHERE spec_id=?
            ORDER BY created_at DESC LIMIT 1""", (spec_id,)).fetchone()
        if previous is not None and previous["status"] in ("queued", "preparing", "training", "succeeded"):
            return {"job_id": previous["job_id"], "spec_id": spec_id, "status": previous["status"],
                    "merged": True, "reason": "an identical spec is already queued, running or completed",
                    "parent_version": parent_version, "warnings": warnings}
        con.execute("""INSERT INTO training_jobs (job_id, spec_id, owner, status, stage, progress,
            created_at, cancel_requested) VALUES (?, ?, ?, 'queued', 'queued', NULL, ?, 0)""",
                    (job_id, spec_id, cfg.principal, now()))
    folder = training_folder(cfg, cfg.principal, job_id)
    write_json(folder / "spec.json", {**spec, "spec_id": spec_id, "spec_sha256": spec_sha256, "job_id": job_id})
    return {"job_id": job_id, "spec_id": spec_id, "status": "queued", "merged": False,
            "parent_version": parent_version, "algorithm": spec["algorithm"], "method": method,
            "snapshot_id": snapshot, "train_cutoff": cutoff, "budget": {"max_seconds": timeout_seconds, "max_rows": max_rows},
            "maturity_rows": len(rows), "maturity_dates": len(dates), "warnings": warnings}


def train_status(cfg: Config, job_id: str) -> dict:
    job = _visible_job(cfg, job_id)
    spec = _spec(cfg, job["spec_id"])
    folder = training_folder(cfg, job["owner"], job["job_id"])
    progress = None
    if (folder / "progress.json").exists():
        progress = json.loads((folder / "progress.json").read_text(encoding="utf-8"))
    return {"job": job, "progress": progress,
            "spec": {key: spec[key] for key in ("parent_version", "snapshot_id", "contract_id", "method",
                                                "algorithm", "train_cutoff", "max_seconds", "max_rows")},
            "result_version": job["result_version"]}


def train_list(cfg: Config) -> list[dict]:
    return _rows(cfg, """SELECT job_id, spec_id, status, stage, created_at, started_at, finished_at,
        error_category, result_version FROM training_jobs WHERE owner=? ORDER BY created_at DESC""", (cfg.principal,))


def train_cancel(cfg: Config, job_id: str) -> dict:
    job = _visible_job(cfg, job_id)
    if job["status"] == "queued":
        _update(cfg, job_id, status="cancelled", stage="cancelled", finished_at=now(),
                error_category="cancelled", error_message="cancelled by owner before a worker claimed it")
        return {"job_id": job_id, "status": "cancelled", "worker_notified": False}
    if job["status"] in ("preparing", "training"):
        _update(cfg, job_id, cancel_requested=1)
        (training_folder(cfg, job["owner"], job_id) / "cancel.flag").write_text("cancel\n", encoding="utf-8")
        return {"job_id": job_id, "status": "cancelling", "worker_notified": True}
    return {"job_id": job_id, "status": job["status"], "worker_notified": False,
            "reason": "job is no longer cancellable"}


def recover_stale(cfg: Config, stale_seconds: int = STALE_HEARTBEAT_SECONDS) -> list[str]:
    """Mark jobs whose worker stopped heartbeating as interrupted, never as succeeded."""
    limit = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
    stale = []
    for job in _rows(cfg, "SELECT job_id, heartbeat_at, started_at FROM training_jobs WHERE status IN ('preparing','training')", ()):
        stamp = job["heartbeat_at"] or job["started_at"] or job["job_id"]
        try:
            beat = timestamp(stamp)
        except (ValueError, TypeError):
            continue
        if beat <= limit:
            stale.append(job["job_id"])
    for job_id in stale:
        _update(cfg, job_id, status="interrupted", stage="interrupted", finished_at=now(),
                error_category="worker_lost", error_message="worker heartbeat expired; the job was interrupted and no artifact was published")
    return stale


def _claim_next(cfg: Config) -> dict | None:
    with connect(cfg) as con:
        schema(con)
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM training_jobs WHERE status='queued' ORDER BY created_at, rowid LIMIT 1").fetchone()
        if row is None:
            return None
        changed = con.execute("""UPDATE training_jobs SET status='preparing', stage='preparing',
            started_at=?, heartbeat_at=? WHERE job_id=? AND status='queued'""", (now(), now(), row["job_id"]))
        if changed.rowcount != 1:
            return None
        return dict(row)


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(10)


def _child_env(folder: Path) -> dict:
    # Drop SMTP credentials, API keys and other ambient secrets from the child.
    allowed = {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "PYTHONIOENCODING"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env["TEMP"] = env["TMP"] = str(folder)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _finish_failure(cfg: Config, job: dict, status: str, category: str, message: str) -> dict:
    folder = training_folder(cfg, job["owner"], job["job_id"])
    (folder / "model.bin").unlink(missing_ok=True)
    _update(cfg, job["job_id"], status=status, stage=status, finished_at=now(), heartbeat_at=now(),
            error_category=category, error_message=message[:300])
    return {"job_id": job["job_id"], "status": status, "error_category": category, "error_message": message[:300]}


def _finalize(cfg: Config, job: dict, spec: dict, folder: Path) -> dict:
    result = _read_json(folder / "result.json")
    if result is None:
        return _finish_failure(cfg, job, "failed", "missing_result", "child exited without a result record")
    manifest = result.get("manifest") or {}
    try:
        version = identifier(manifest["version"])
        contract = validate_contract(manifest["contract"])
    except (KeyError, ValueError):
        return _finish_failure(cfg, job, "failed", "invalid_manifest", "child produced an invalid model manifest")
    payload = (folder / "model.bin").read_bytes() if (folder / "model.bin").exists() else b""
    if not payload or digest(payload) != result.get("artifact_sha256") or manifest.get("artifact_sha256") != result.get("artifact_sha256"):
        return _finish_failure(cfg, job, "failed", "artifact_integrity", "staged artifact hash does not match the result record")
    if manifest.get("scope") != "personal" or manifest.get("owner") != job["owner"] or manifest.get("job_id") != job["job_id"]:
        return _finish_failure(cfg, job, "failed", "namespace_violation", "child manifest does not target this owner and job")
    if manifest.get("contract_id") != contract_id(contract) or spec["contract_id"] != manifest.get("contract_id"):
        return _finish_failure(cfg, job, "failed", "contract_mismatch", "child changed the persisted task contract")
    if manifest.get("parent_version") != spec["parent_version"] or manifest.get("training_snapshot") != spec["snapshot_id"]:
        return _finish_failure(cfg, job, "failed", "spec_mismatch", "child output does not match the persisted spec")
    target = personal_model_folder(cfg, job["owner"], version)
    if target.exists():
        return _finish_failure(cfg, job, "failed", "version_collision", "target personal version already exists")
    atomic_write(target / manifest["artifact"], payload)
    write_json(target / "manifest.json", manifest)
    manifest_bytes = (target / "manifest.json").read_bytes()
    with connect(cfg) as con:
        schema(con)
        registry_schema(con)
        con.execute("INSERT INTO registry_models VALUES (?, ?, ?, 'personal', 'trained', 'ready', NULL, ?, NULL)",
                    (version, job["owner"], job["owner"], digest(manifest_bytes)))
    _update(cfg, job["job_id"], status="succeeded", stage="done", finished_at=now(), heartbeat_at=now(),
            result_version=version, result_sha256=digest(manifest_bytes), error_category=None, error_message=None)
    return {"job_id": job["job_id"], "status": "succeeded", "model_version": version,
            "algorithm": manifest["algorithm"], "train_label_end": manifest["train_label_end"],
            "forward_evaluation": result.get("forward_evaluation"), "holdout_days": result.get("holdout_days"),
            "auto_switched": False}


def _execute(cfg: Config, job: dict, *, poll: float, child_command: list[str] | None) -> dict:
    job_id, owner = job["job_id"], job["owner"]
    folder = training_folder(cfg, owner, job_id)
    spec_record = _read_json(folder / "spec.json")
    if spec_record is None:
        return _finish_failure(cfg, job, "failed", "spec_missing", "queued job has no immutable spec on disk")
    write_json(folder / "child-config.json", {
        "workspace": str(cfg.workspace), "principal": owner, "timezone": cfg.timezone,
        "horizon": cfg.horizon, "top_k": cfg.top_k, "cost_bps": cfg.cost_bps, "job_folder": str(folder)})
    (folder / "cancel.flag").unlink(missing_ok=True)
    command = child_command or [sys.executable, "-m", "stock_predict_mailer.training_child",
                                "--job", job_id, "--config", str(folder / "child-config.json")]
    started = clock.monotonic()
    with open(folder / "stdout.log", "wb") as log:
        process = subprocess.Popen(command, cwd=str(folder), env=_child_env(folder),
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    _update(cfg, job_id, worker_pid=process.pid, heartbeat_at=now())
    cancelled = timed_out = False
    last_stage = "preparing"
    while True:
        progress = _read_json(folder / "progress.json") or {}
        stage = progress.get("stage")
        if isinstance(stage, str) and stage != last_stage:
            last_stage = stage
            _update(cfg, job_id, status="training", stage=stage,
                    progress=json.dumps({"stage": stage, "detail": progress.get("detail", "")}, ensure_ascii=False))
        _update(cfg, job_id, heartbeat_at=now())
        current = _row(cfg, "SELECT cancel_requested FROM training_jobs WHERE job_id=?", (job_id,))
        if current is not None and current["cancel_requested"]:
            (folder / "cancel.flag").write_text("cancel\n", encoding="utf-8")
            cancelled = True
            break
        if clock.monotonic() - started > spec_record["max_seconds"]:
            timed_out = True
            break
        if process.poll() is not None:
            break
        clock.sleep(poll)
    if cancelled:
        _stop(process)
        return _finish_failure(cfg, job, "cancelled", "cancelled", "cancelled by owner while the worker was running")
    if timed_out:
        _stop(process)
        return _finish_failure(cfg, job, "timeout", "timeout",
                               f"training exceeded its {spec_record['max_seconds']}s budget and was stopped")
    try:
        process.wait(10)  # ensure the child released the inherited log handle before promotion
    except subprocess.TimeoutExpired:
        _stop(process)
    if process.returncode != 0:
        error = _read_json(folder / "error.json") or {}
        return _finish_failure(cfg, job, "failed", str(error.get("category", "child_exit"))[:60],
                               str(error.get("message", f"training child exited with code {process.returncode}"))[:300])
    return _finalize(cfg, job, spec_record, folder)


def run_worker(cfg: Config, *, once: bool = True, poll: float = 0.2, child_command: list[str] | None = None,
               stale_seconds: int = STALE_HEARTBEAT_SECONDS) -> dict:
    """Run the single local training worker.

    ``child_command`` exists for supervisor tests only and is never reachable from
    the CLI; production calls always use the isolated training child module.
    """
    recovered = recover_stale(cfg, stale_seconds)
    executed = []
    while True:
        job = _claim_next(cfg)
        if job is None:
            break
        executed.append(_execute(cfg, job, poll=poll, child_command=child_command))
        if once:
            break
    return {"executed": executed, "recovered": recovered}


# ---------------------------------------------------------------- comparison

def _daily_rank_ic(rows: list[dict], scores: np.ndarray) -> dict[str, float]:
    groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        groups[row["date"]].append((row["y"], float(score)))
    result = {}
    for day, group in groups.items():
        if len(group) < 3:
            continue
        target, predicted = np.array(group).T
        if np.std(predicted) > 0 and np.std(target) > 0:
            result[day] = float(np.corrcoef(rankdata(target), rankdata(predicted))[0, 1])
    return result


def _block_bootstrap(differences: list[float], *, block_days: int = 5, rounds: int = 2000, seed: int = 20261025) -> dict:
    values = np.asarray(differences, dtype=float)
    if values.size == 0:
        raise ValueError("no paired differences to bootstrap")
    blocks = [values[start:start + block_days] for start in range(0, values.size, block_days)]
    rng = np.random.default_rng(seed)
    means = np.empty(rounds)
    for index in range(rounds):
        pick = rng.integers(0, len(blocks), len(blocks))
        means[index] = float(np.concatenate([blocks[value] for value in pick]).mean())
    low, high = np.percentile(means, [5, 95])
    return {"mean": float(values.mean()), "low": float(low), "high": float(high),
            "rounds": rounds, "block_days": block_days, "seed": seed}


def _comparison_path(cfg: Config, comparison_id: str) -> Path:
    return cfg.workspace / "registry" / "comparisons" / owner_key(cfg.principal) / f"{identifier(comparison_id)}.json"


def compare_models(cfg: Config, candidate_version: str, baseline_version: str, snapshot: str, cutoff: str) -> dict:
    candidate, candidate_payload, candidate_state = get_model(cfg, candidate_version)
    baseline, baseline_payload, baseline_state = get_model(cfg, baseline_version)
    if candidate["contract_id"] != baseline["contract_id"] or validate_contract(candidate["contract"]) != validate_contract(baseline["contract"]):
        raise ValueError("models with different labels, features, benchmark or universe cannot be compared")
    if candidate["algorithm"] not in ALGORITHMS or baseline["algorithm"] not in ALGORITHMS:
        raise ValueError("unsupported model algorithm")
    data_manifest, raw = load_snapshot(cfg, snapshot)
    dataset_compatible(data_manifest, candidate["contract"])
    _, rows = prepare_rows(raw, candidate["contract"], cutoff)
    boundary = max(candidate["train_label_end"], baseline["train_label_end"])
    test = [row for row in rows if row["date"] > boundary]
    days = sorted({row["date"] for row in test})
    if len(days) < MIN_COMPARE_DATES:
        raise ValueError(f"need at least {MIN_COMPARE_DATES} matured test dates strictly after both training label "
                         f"ends ({boundary}); got {len(days)} days")
    candidate_scores = native_predict(candidate["algorithm"], candidate_payload, test)
    baseline_scores = native_predict(baseline["algorithm"], baseline_payload, test)
    candidate_ic = _daily_rank_ic(test, candidate_scores)
    baseline_ic = _daily_rank_ic(test, baseline_scores)
    common = sorted(set(candidate_ic) & set(baseline_ic))
    if len(common) < MIN_COMPARE_DATES:
        raise ValueError(f"need at least {MIN_COMPARE_DATES} comparable cross-section dates; got {len(common)}")
    differences = [candidate_ic[day] - baseline_ic[day] for day in common]
    bootstrap = _block_bootstrap(differences)
    if bootstrap["low"] > 0:
        verdict = "candidate_improved"
    elif bootstrap["high"] < 0:
        verdict = "candidate_degraded"
    else:
        verdict = "inconclusive"
    identity = {"schema_version": 1, "owner": cfg.principal, "candidate": candidate_version,
                "baseline": baseline_version, "snapshot": snapshot, "cutoff": cutoff}
    comparison_id = digest(json.dumps(identity, sort_keys=True).encode())
    path = _comparison_path(cfg, comparison_id)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        return existing
    record = {**identity, "comparison_id": comparison_id, "created_at": now(),
              "test_start": common[0], "test_end": common[-1], "test_days": len(common),
              "securities": len({row["security_id"] for row in test}),
              "test_rows": len(test), "label_end_boundary": boundary,
              "maturity_start": min(row["date"] for row in test),
              "metrics": {"candidate": metrics(test, candidate_scores),
                          "baseline": metrics(test, baseline_scores)},
              "rank_ic_difference": bootstrap, "verdict": verdict,
              "model_scope": {"candidate": candidate_state["scope"], "baseline": baseline_state["scope"]},
              "auto_switched": False,
              "limitations": ["Only data later than both training label ends is used; earlier dates are excluded",
                              "Paired rank-IC differences with a block bootstrap are not a market-constrained backtest",
                              "Repeated comparisons on the same window can still overfit the test period",
                              "Scores from different algorithms are not calibrated probabilities"]}
    raw_record = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    atomic_write(path, raw_record)
    with connect(cfg) as con:
        schema(con)
        con.execute("INSERT INTO model_comparisons VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (comparison_id, cfg.principal, candidate_version, baseline_version, snapshot, cutoff,
                     verdict, digest(raw_record), record["created_at"]))
    return record


def latest_comparison(cfg: Config, model_version: str) -> dict | None:
    rows = _rows(cfg, """SELECT id, sha256 FROM model_comparisons WHERE owner=? AND candidate=?
        ORDER BY created_at DESC LIMIT 1""", (cfg.principal, model_version))
    if not rows:
        return None
    path = _comparison_path(cfg, rows[0]["id"])
    if not path.exists():
        return None
    raw = path.read_bytes()
    if digest(raw) != rows[0]["sha256"]:
        raise ValueError("comparison integrity check failed")
    return json.loads(raw)
