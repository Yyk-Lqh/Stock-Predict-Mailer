"""Isolated training child: fits one queued job, writes only to its staging folder.

The child never touches the registry, the platform version folder or the network.
It reports coarse stages through progress.json and fails with a bounded error
category instead of leaking exception text.
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from . import dataset_auth
from .calendar import market_context
from .contracts import contract_id, dataset_compatible, prepare_rows, validate_contract
from .core import Config, atomic_write, digest, now, write_json
from .data import load_snapshot
from .native_models import continue_native, fit_native, native_predict
from .research import metrics


class TrainingError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def _stage(folder: Path, stage: str, detail: str = "") -> None:
    payload = {"stage": stage, "detail": detail, "updated_at": now()}
    try:
        write_json(folder / "progress.json", payload)
        with open(folder / "stages.log", "a", encoding="utf-8") as trail:
            trail.write(f"{payload['updated_at']} {stage}\n")
    except OSError:
        # Progress is advisory; it must never fail a healthy training run.
        pass
    if (folder / "cancel.flag").exists():
        raise TrainingError("cancelled", "cancellation requested by owner")


def _dependencies() -> dict:
    from importlib.metadata import version
    names = ("numpy", "scikit-learn")
    result = {}
    for name in names:
        try:
            result[name] = version(name)
        except Exception:
            result[name] = "unknown"
    return result


def run(folder: Path, cfg: Config, job_id: str) -> dict:
    spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
    _stage(folder, "loading_data", f"snapshot {spec['snapshot_id']}")
    # Re-check the owner's permission so a revoked grant cannot be trained on.
    dataset_auth.require(cfg, spec["snapshot_id"], "personal_training")
    data_manifest, raw = load_snapshot(cfg, spec["snapshot_id"])
    contract = validate_contract(spec["contract"])
    if contract_id(contract) != spec["contract_id"]:
        raise TrainingError("contract_mismatch", "persisted contract does not match its recorded identity")
    dataset_compatible(data_manifest, contract, bool(spec["allow_unverified_real"]))
    _stage(folder, "preparing_features", "building point-in-time features and matured labels")
    sessions, actions = market_context(cfg, contract)
    _, rows = prepare_rows(raw, contract, spec["train_cutoff"], sessions=sessions, actions=actions)
    dates = {row["date"] for row in rows}
    securities = {row["security_id"] for row in rows}
    if len(dates) < 60 or len(securities) < 3:
        raise TrainingError("insufficient_data", "need at least 60 matured feature dates and 3 securities")
    if len(rows) > spec["max_rows"]:
        raise TrainingError("row_budget_exceeded", "training matrix exceeds the declared row budget")
    if spec.get("method") == "continue_train":
        rounds = int(spec.get("additional_rounds") or 0)
        _stage(folder, "training", f"continuing {spec['algorithm']} for {rounds} rounds on {len(rows)} rows")
        parent_path = folder / "parent.model.txt"
        if not parent_path.exists():
            raise TrainingError("parent_missing", "the staged parent artifact is missing")
        filename, payload = continue_native(spec["algorithm"], parent_path.read_bytes(), rows, rounds)
    else:
        _stage(folder, "training", f"fitting {spec['algorithm']} on {len(rows)} rows")
        filename, payload = fit_native(spec["algorithm"], rows)
    atomic_write(folder / "model.bin", payload)
    train_label_end = max(row["label_end"] for row in rows)
    _stage(folder, "evaluating", "forward check on rows later than this model's training label end")
    holdout = [row for row in rows if row["date"] > train_label_end]
    holdout_days = len({row["date"] for row in holdout})
    forward = metrics(holdout, native_predict(spec["algorithm"], payload, holdout)) if holdout_days >= 30 else None
    _stage(folder, "packaging", "writing manifest for parent verification")
    version = digest(uuid.uuid4().bytes)
    manifest = {
        "schema_version": 1, "version": version, "created_at": now(),
        "algorithm": spec["algorithm"], "artifact": filename, "artifact_sha256": digest(payload),
        "contract": contract, "contract_id": contract_id(contract),
        "training_snapshot": spec["snapshot_id"], "training_cutoff": spec["train_cutoff"],
        "train_feature_start": min(dates), "train_feature_end": max(dates),
        "train_label_end": train_label_end, "training_rows": len(rows),
        "synthetic": bool(data_manifest["synthetic"]), "unverified_real": not data_manifest["synthetic"],
        "data_provenance": data_manifest.get("provenance", {}),
        "calendar_mode": "certified" if sessions else "benchmark_observed",
        "corporate_actions_applied": bool(actions),
        "scope": "personal", "owner": cfg.principal, "parent_version": spec["parent_version"],
        "continued_from": spec["parent_version"] if spec.get("method") == "continue_train" else None,
        "additional_rounds": int(spec.get("additional_rounds") or 0),
        "method": spec["method"], "job_id": job_id, "spec_sha256": spec["spec_sha256"],
        "budget": {"max_seconds": spec["max_seconds"], "max_rows": spec["max_rows"]},
        "forward_evaluation_days": holdout_days,
        "implementation_sha256": digest(b"".join(p.name.encode() + p.read_bytes()
                                                 for p in sorted(Path(__file__).parent.glob("*.py")))),
        "dependencies": _dependencies(),
        "limitations": ["Personal retraining inherits the parent recipe; it does not inherit or fine-tune parent weights"
                        if spec.get("method") != "continue_train" else
                        f"Continued for {int(spec.get('additional_rounds') or 0)} bounded rounds from a frozen parent; "
                        "this is not a full retrain and must be compared against one",
                        "Calendar: " + ("owner-certified session list" if sessions else "benchmark-observed sessions, not a certified exchange calendar"),
                        "Corporate actions: " + ("applied from the owner factor file" if actions else "not applied"),
                        "No historical universe or executable backtest",
                        "Candidate is not selected automatically and is not a stable release"],
    }
    result = {"version": version, "artifact": filename, "artifact_sha256": manifest["artifact_sha256"],
              "manifest": manifest, "forward_evaluation": forward, "holdout_days": holdout_days}
    write_json(folder / "result.json", result)
    _stage(folder, "done", "staged artifact ready for parent promotion")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Isolated training child; writes only its staging folder")
    parser.add_argument("--job", required=True)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    cfg = Config(workspace=Path(config["workspace"]), timezone=config["timezone"], horizon=config["horizon"],
                 top_k=config["top_k"], cost_bps=config["cost_bps"], principal=config["principal"])
    folder = Path(config["job_folder"])
    try:
        run(folder, cfg, args.job)
    except TrainingError as exc:
        write_json(folder / "error.json", {"category": exc.category, "message": str(exc)[:300]})
        return 2
    except Exception as exc:  # do not persist upstream text: it may contain paths or credentials
        write_json(folder / "error.json", {"category": "internal_error", "message": type(exc).__name__})
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
