"""Local immutable model registry. Trusted CLI identities are not web authentication."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from . import dataset_auth
from .calendar import market_context
from .contracts import contract_id, dataset_compatible, prepare_rows, validate_contract
from .core import Config, atomic_write, connect, digest, now, write_json
from .data import load_snapshot
from .native_models import ARTIFACTS, LOADABLE, fit_native, native_predict
from .research import cost_diagnostics, metrics


def schema(con):
    con.executescript("""
      CREATE TABLE IF NOT EXISTS registry_models (
        version TEXT PRIMARY KEY, owner TEXT NOT NULL, created_by TEXT NOT NULL,
        scope TEXT NOT NULL, origin TEXT NOT NULL, status TEXT NOT NULL,
        channel TEXT, manifest_sha256 TEXT NOT NULL, publication_sha256 TEXT);
      CREATE TABLE IF NOT EXISTS registry_evaluations (
        id TEXT PRIMARY KEY, model_version TEXT NOT NULL, owner TEXT NOT NULL,
        sha256 TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS registry_selection (
        owner TEXT PRIMARY KEY, model_version TEXT NOT NULL, selected_at TEXT NOT NULL);
    """)


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("invalid registry identifier")
    return value


def model_folder(cfg: Config, model_version: str) -> Path:
    return cfg.workspace / "registry" / "versions" / identifier(model_version)


def owner_key(owner: str) -> str:
    return digest(owner.encode())


def personal_model_folder(cfg: Config, owner: str, model_version: str) -> Path:
    """Personal artifacts live only under the owner's namespace, never in platform versions."""
    return cfg.workspace / "registry" / "personal" / owner_key(owner) / "versions" / identifier(model_version)


def get_model(cfg: Config, model_version: str) -> tuple[dict, bytes, dict]:
    with connect(cfg) as con:
        schema(con)
        row = con.execute("""SELECT * FROM registry_models WHERE version=? AND
            (created_by=? OR (scope='platform' AND status='published'))""", (model_version, cfg.principal)).fetchone()
        if row is None:
            raise ValueError("unknown or unauthorized model")
        row = dict(row)
    folder = (model_folder(cfg, model_version) if row["scope"] == "platform"
              else personal_model_folder(cfg, row["owner"], model_version))
    raw = (folder / "manifest.json").read_bytes()
    if digest(raw) != row["manifest_sha256"]:
        raise ValueError("model manifest integrity check failed")
    manifest = json.loads(raw)
    contract = validate_contract(manifest["contract"])
    if manifest["version"] != model_version or contract_id(contract) != manifest["contract_id"]:
        raise ValueError("model contract identity mismatch")
    algorithm = manifest["algorithm"]
    if algorithm not in LOADABLE:
        raise ValueError("unsupported native model")
    if manifest["artifact"] != ARTIFACTS[algorithm]:
        raise ValueError("unsupported native model artifact")
    if algorithm == "residual" and not manifest.get("residual_of"):
        raise ValueError("derived model must record its frozen parent")
    payload = (folder / ARTIFACTS[algorithm]).read_bytes()
    if digest(payload) != manifest["artifact_sha256"]:
        raise ValueError("model artifact integrity check failed")
    if row["status"] == "published":
        publication = (folder / "publication.json").read_bytes()
        if digest(publication) != row["publication_sha256"]:
            raise ValueError("publication integrity check failed")
        manifest = {**manifest, "publication": json.loads(publication)}
    return manifest, payload, row


def model_scores(cfg: Config, manifest: dict, payload: bytes, rows: list[dict]):
    """Score rows with any loadable model, including derived adapters.

    Derived formats need the registry, so every scoring path funnels through here
    instead of calling ``native_predict`` directly.
    """
    if manifest["algorithm"] == "residual":
        from .residual import residual_scores

        return residual_scores(cfg, manifest, payload, rows)
    return native_predict(manifest["algorithm"], payload, rows)


def train_platform(cfg: Config, snapshot: str, contract: dict, cutoff: str, algorithm: str = "ridge",
                   *, confirm_platform_data: bool = False, allow_unverified_real: bool = False) -> dict:
    if not confirm_platform_data:
        raise ValueError("publisher must explicitly confirm platform training rights; uploaded user data is not auto-authorized")
    contract = validate_contract(contract)
    data_manifest, raw = load_snapshot(cfg, snapshot)
    denied = dataset_auth.platform_denied(cfg, snapshot)
    if denied is not None:
        raise ValueError("snapshot is not authorized for platform training; uploaded user data is not auto-authorized "
                         "(the owner may grant it with dataset-authorize --platform)")
    dataset_compatible(data_manifest, contract, allow_unverified_real)
    sessions, actions = market_context(cfg, contract)
    _, rows = prepare_rows(raw, contract, cutoff, sessions=sessions, actions=actions)
    dates = {row["date"] for row in rows}
    if len(dates) < 60 or len({row["security_id"] for row in rows}) < 3:
        raise ValueError("need at least 60 matured feature dates and 3 securities")
    filename, payload = fit_native(algorithm, rows)
    model_version = digest(uuid.uuid4().bytes)
    manifest = {"schema_version": 1, "version": model_version, "created_at": now(),
                "algorithm": algorithm, "artifact": filename, "artifact_sha256": digest(payload),
                "contract": contract, "contract_id": contract_id(contract),
                "training_snapshot": snapshot, "training_cutoff": cutoff,
                "train_feature_start": min(dates), "train_feature_end": max(dates),
                "train_label_end": max(row["label_end"] for row in rows), "training_rows": len(rows),
                "synthetic": data_manifest["synthetic"], "unverified_real": not data_manifest["synthetic"],
                "data_provenance": data_manifest.get("provenance", {}),
                "scope": "platform", "parent_version": None, "method": "full_retrain",
                "implementation_sha256": digest(b"".join(p.name.encode() + p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))),
                "dependencies": {name: version(name) for name in ("numpy", "scikit-learn")},
                "limitations": ["Benchmark-observed calendar is not a certified exchange calendar",
                   "No certified corporate actions, historical universe or executable backtest",
                   "No stable release certification; demo only for synthetic data"]}
    if algorithm == "lightgbm":
        manifest["dependencies"]["lightgbm"] = version("lightgbm")
    folder = model_folder(cfg, model_version)
    atomic_write(folder / filename, payload)
    write_json(folder / "manifest.json", manifest)
    with connect(cfg) as con:
        schema(con)
        con.execute("INSERT INTO registry_models VALUES (?, 'platform', ?, 'platform', 'trained', 'draft', NULL, ?, NULL)",
                    (model_version, cfg.principal, digest((folder / "manifest.json").read_bytes())))
    return manifest


def evaluate_model(cfg: Config, model_version: str, snapshot: str, cutoff: str, *, allow_unverified_real: bool = False) -> dict:
    manifest, payload, _ = get_model(cfg, model_version)
    data_manifest, raw = load_snapshot(cfg, snapshot)
    dataset_compatible(data_manifest, manifest["contract"], allow_unverified_real)
    sessions, actions = market_context(cfg, manifest["contract"])
    _, all_rows = prepare_rows(raw, manifest["contract"], cutoff, sessions=sessions, actions=actions)
    rows = [row for row in all_rows if row["date"] > manifest["train_label_end"]]
    if len({row["date"] for row in rows}) < 30:
        raise ValueError("need 30 matured evaluation dates strictly after training label end")
    scores = model_scores(cfg, manifest, payload, rows)
    evaluation_id = digest(uuid.uuid4().bytes)
    result = {"evaluation_id": evaluation_id, "model_version": model_version,
              "contract_id": manifest["contract_id"], "snapshot_id": snapshot,
              "created_at": now(), "cutoff": cutoff,
              "feature_start": min(row["date"] for row in rows), "feature_end": max(row["date"] for row in rows),
              "label_end": max(row["label_end"] for row in rows), "train_label_end": manifest["train_label_end"],
              "metrics": metrics(rows, scores), "cost_diagnostics": cost_diagnostics(rows, scores, cfg),
              "securities": len({row["security_id"] for row in rows}), "synthetic": manifest["synthetic"],
              "limitations": ["Forward holdout relative to this model; repeated evaluation can cause selection bias",
                              "Cost diagnostics are not a market-constrained executable backtest"]}
    folder = cfg.workspace / "registry" / "evaluations"
    write_json(folder / f"{evaluation_id}.json", result)
    with connect(cfg) as con:
        schema(con)
        con.execute("INSERT INTO registry_evaluations VALUES (?, ?, ?, ?)",
                    (evaluation_id, model_version, cfg.principal, digest((folder / f"{evaluation_id}.json").read_bytes())))
    return result


def get_evaluation(cfg: Config, evaluation_id: str) -> dict:
    identifier(evaluation_id)
    with connect(cfg) as con:
        schema(con)
        row = con.execute("SELECT * FROM registry_evaluations WHERE id=? AND owner=?", (evaluation_id, cfg.principal)).fetchone()
    if row is None:
        raise ValueError("unknown or unauthorized evaluation")
    payload = (cfg.workspace / "registry" / "evaluations" / f"{evaluation_id}.json").read_bytes()
    if digest(payload) != row["sha256"]:
        raise ValueError("evaluation integrity check failed")
    return json.loads(payload)


def publish_demo(cfg: Config, model_version: str, evaluation_id: str) -> dict:
    manifest, _, row = get_model(cfg, model_version)
    if row["created_by"] != cfg.principal or row["origin"] != "trained" or row["scope"] != "platform":
        raise ValueError("only the trusted local publisher can publish its own trained candidate")
    if not manifest["synthetic"]:
        raise ValueError("real stable/experimental publication is not yet certified")
    evaluation = get_evaluation(cfg, evaluation_id)
    if evaluation["model_version"] != model_version or evaluation["contract_id"] != manifest["contract_id"]:
        raise ValueError("evaluation does not belong to this model")
    if row["status"] == "published":
        if manifest["publication"]["evaluation"]["evaluation_id"] != evaluation_id:
            raise ValueError("published versions are immutable; create another version")
        return manifest["publication"]
    publication = {"channel": "demo", "published_at": now(), "evaluation": evaluation,
                   "model_card": {"purpose": "Synthetic pipeline demonstration only; not investment evidence",
                                  "market": manifest["contract"]["market"], "horizon": manifest["contract"]["horizon"],
                                  "benchmark": manifest["contract"]["benchmark_id"], "limitations": manifest["limitations"]}}
    with connect(cfg) as con:
        schema(con)
        con.execute("BEGIN IMMEDIATE")
        current = con.execute("SELECT status,publication_sha256 FROM registry_models WHERE version=?", (model_version,)).fetchone()
        path = model_folder(cfg, model_version) / "publication.json"
        if current["status"] == "published":
            raw_publication = path.read_bytes()
            existing = json.loads(raw_publication)
            if digest(raw_publication) != current["publication_sha256"] or existing["evaluation"]["evaluation_id"] != evaluation_id:
                raise ValueError("published versions are immutable")
            return existing
        if current["status"] != "draft":
            raise ValueError("model is not a publishable draft")
        write_json(path, publication)
        con.execute("UPDATE registry_models SET status='published',channel='demo',publication_sha256=? WHERE version=? AND status='draft'",
                    (digest(path.read_bytes()), model_version))
    return publication


def list_models(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        schema(con)
        return [dict(row) for row in con.execute("SELECT version,owner,scope,status,channel,origin FROM registry_models WHERE created_by=? OR (scope='platform' AND status='published') ORDER BY rowid DESC", (cfg.principal,))]


def _store_selection(cfg: Config, owner: str, model_version: str) -> None:
    with connect(cfg) as con:
        schema(con)
        con.execute("INSERT INTO registry_selection VALUES (?, ?, ?) ON CONFLICT(owner) DO UPDATE SET model_version=excluded.model_version,selected_at=excluded.selected_at",
                    (owner, model_version, now()))


def select_model(cfg: Config, model_version: str, *, allow_demo: bool = False, confirm_personal: bool = False) -> dict:
    _, _, row = get_model(cfg, model_version)
    if row["scope"] == "personal":
        if row["owner"] != cfg.principal:
            raise ValueError("personal versions are visible only to their owner")
        if row["status"] != "ready":
            raise ValueError("personal candidate is not a completed version")
        if not confirm_personal:
            raise ValueError("selecting a personal version requires explicit --confirm-personal")
        from .model_training import latest_comparison
        comparison = latest_comparison(cfg, model_version)
        if comparison is None:
            raise ValueError("compare the personal candidate with a baseline before selecting it")
        _store_selection(cfg, cfg.principal, model_version)
        return {"owner": cfg.principal, "model_version": model_version, "scope": "personal", "channel": None,
                "comparison": {"comparison_id": comparison["comparison_id"], "verdict": comparison["verdict"],
                               "test_days": comparison["test_days"]},
                "auto_switched": False}
    if row["status"] != "published" or row["channel"] != "demo" or not allow_demo:
        raise ValueError("selection requires a published demo and explicit --allow-demo; stable models are not available")
    _store_selection(cfg, cfg.principal, model_version)
    return {"owner": cfg.principal, "model_version": model_version, "channel": row["channel"]}


def selected_model(cfg: Config) -> str | None:
    with connect(cfg) as con:
        schema(con)
        row = con.execute("SELECT model_version FROM registry_selection WHERE owner=?", (cfg.principal,)).fetchone()
    return row["model_version"] if row is not None else None


def predict_snapshot(cfg: Config, snapshot: str, cutoff: str, model_version: str | None = None, *,
                     allow_demo: bool = False, allow_personal: bool = False) -> dict:
    if model_version is None:
        model_version = selected_model(cfg)
        if model_version is None:
            raise ValueError("no model selected for this local identity")
    manifest, payload, state = get_model(cfg, model_version)
    if state["scope"] == "personal":
        if state["owner"] != cfg.principal:
            raise ValueError("personal versions are usable only by their owner")
        if state["status"] != "ready" or not allow_personal:
            raise ValueError("prediction requires a completed personal version and explicit --allow-personal")
        channel = "personal"
    else:
        if state["status"] != "published" or state["channel"] != "demo" or not allow_demo:
            raise ValueError("prediction requires published model and explicit demo allowance")
        channel = state["channel"]
    data_manifest, raw = load_snapshot(cfg, snapshot)
    dataset_compatible(data_manifest, manifest["contract"])
    sessions, actions = market_context(cfg, manifest["contract"])
    features, _ = prepare_rows(raw, manifest["contract"], cutoff, sessions=sessions, actions=actions)
    if not features:
        raise ValueError("no feature-complete rows available at the requested cutoff")
    latest = max(row["date"] for row in features)
    rows = [row for row in features if row["date"] == latest]
    scores = model_scores(cfg, manifest, payload, rows)
    missing = sorted(set(manifest["contract"]["universe"]) - {row["security_id"] for row in rows})
    identity = {"model_version": model_version, "snapshot": snapshot, "cutoff": cutoff,
                "owner": cfg.principal, "top_k": cfg.top_k, "contract_id": manifest["contract_id"]}
    prediction_id = digest(json.dumps(identity, sort_keys=True).encode())
    rankings = sorted([{"security_id": row["security_id"], "date": row["date"], "score": float(score)} for row, score in zip(rows, scores, strict=True)], key=lambda r: (-r["score"], r["security_id"]))
    result = {**identity, "prediction_id": prediction_id, "created_at": now(), "synthetic": bool(manifest["synthetic"]),
              "channel": channel, "model_scope": state["scope"], "data_date": latest, "missing_securities": missing,
              "feature_complete_securities": len(rows), "predictions": rankings[:cfg.top_k],
              "stale_calendar_days": (datetime.now(timezone.utc).date() - datetime.fromisoformat(latest).date()).days,
              "training_performed": False, "limitations": manifest["limitations"]}
    owner_key = digest(cfg.principal.encode())
    write_json(cfg.workspace / "registry" / "predictions" / owner_key / f"{prediction_id}.json", result)
    return result
