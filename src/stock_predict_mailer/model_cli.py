from __future__ import annotations

import json
from pathlib import Path

from .core import tracked_run

COMMANDS = {"contract-check", "model-train", "model-evaluate", "model-publish", "model-list", "model-select", "model-predict",
            "model-keygen", "model-export", "model-install", "model-compare", "model-drift", "drift-history",
            "residual-fit", "model-retention", "retention-log",
            "prediction-report", "shadow-record", "shadow-evaluate", "shadow-status",
            "stable-promote", "stable-revoke", "release-status", "key-revoke", "key-status",
            "dataset-authorize", "dataset-auth",
            "train-submit", "train-worker", "train-list", "train-status", "train-cancel"}


def add_commands(sub):
    check = sub.add_parser("contract-check", help="Validate fixed model feature and label contract")
    check.add_argument("contract", type=Path)
    train = sub.add_parser("model-train", help="Trusted local platform publisher: train a candidate, never publish automatically")
    train.add_argument("snapshot_id")
    train.add_argument("--contract", type=Path, required=True)
    train.add_argument("--cutoff", required=True)
    train.add_argument("--algorithm", choices=("ridge", "lightgbm", "zero", "momentum"), default="ridge")
    train.add_argument("--confirm-platform-data", action="store_true")
    train.add_argument("--allow-unverified-real", action="store_true")
    evaluate = sub.add_parser("model-evaluate", help="Evaluate only after the model's training-label cutoff")
    evaluate.add_argument("model_version")
    evaluate.add_argument("snapshot_id")
    evaluate.add_argument("--cutoff", required=True)
    evaluate.add_argument("--allow-unverified-real", action="store_true")
    publish = sub.add_parser("model-publish", help="Publish own evaluated synthetic candidate to DEMO only")
    publish.add_argument("model_version")
    publish.add_argument("--evaluation", required=True)
    sub.add_parser("model-list", help="List visible published models and own candidates")
    select = sub.add_parser("model-select", help="Select a published demo or an explicitly confirmed personal version")
    select.add_argument("model_version")
    select.add_argument("--allow-demo", action="store_true")
    select.add_argument("--confirm-personal", action="store_true", help="Explicitly switch to a compared personal version")
    predict = sub.add_parser("model-predict", help="Load selected native model and infer; never fit")
    predict.add_argument("snapshot_id")
    predict.add_argument("--cutoff", required=True)
    predict.add_argument("--model")
    predict.add_argument("--allow-demo", action="store_true")
    predict.add_argument("--allow-personal", action="store_true")
    sub.add_parser("model-keygen", help="Create a local publisher signing key; never overwrite an existing key")
    export = sub.add_parser("model-export", help="Sign an evaluated published platform DEMO; contains no raw training data")
    export.add_argument("model_version")
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--signing-key", type=Path)
    install = sub.add_parser("model-install", help="Verify and install a signed DEMO without training")
    install.add_argument("package", type=Path)
    install.add_argument("--trust-key", type=Path, required=True, help="Publisher public key obtained independently of the archive")
    compare = sub.add_parser("model-compare", help="Paired comparison on dates later than both training label ends")
    compare.add_argument("candidate_version")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--snapshot", required=True)
    compare.add_argument("--cutoff", required=True)
    compare.add_argument("--segments", action="store_true", help="Also split by liquidity and market phase")
    residual = sub.add_parser("residual-fit", help="Fit a residual adapter on a frozen parent, then compare it")
    residual.add_argument("parent_version")
    residual.add_argument("--snapshot", required=True)
    residual.add_argument("--cutoff", required=True)
    residual.add_argument("--folds", type=int, default=4)
    residual.add_argument("--alpha", type=float, default=10.0)
    residual.add_argument("--shrink", type=float, default=1.0)
    residual.add_argument("--allow-unverified-real", action="store_true")
    authorize = sub.add_parser("dataset-authorize", help="Record this identity's usage decision for one snapshot")
    authorize.add_argument("snapshot_id")
    authorize.add_argument("--platform", action="store_true", help="Grant platform training use (requires confirmed rights)")
    authorize.add_argument("--revoke-platform", action="store_true")
    authorize.add_argument("--revoke-personal", action="store_true")
    authorize.add_argument("--replay", action="store_true", help="Grant historical replay for drift diagnostics")
    authorize.add_argument("--revoke-replay", action="store_true")
    authorize.add_argument("--note", default="")
    drift = sub.add_parser("model-drift", help="Compare the training feature distribution with a current window")
    drift.add_argument("model_version")
    drift.add_argument("--snapshot", required=True)
    drift.add_argument("--cutoff", required=True)
    drift.add_argument("--window-days", type=int, default=60)
    sub.add_parser("drift-history", help="List recorded drift reports")
    retention = sub.add_parser("model-retention", help="Plan or apply local artifact retention")
    retention.add_argument("--keep", type=int, default=5, help="Newest personal versions to keep")
    retention.add_argument("--apply", action="store_true", help="Actually delete; default is a dry run")
    sub.add_parser("retention-log", help="List recorded retention actions")
    brief = sub.add_parser("prediction-report", help="Freeze a prediction into a report with locked identifiers")
    brief.add_argument("prediction_id")
    brief.add_argument("--query", default="风险 策略 模型")
    brief.add_argument("--generate", action="store_true", help="Allow an allow-listed generator; template otherwise")
    shadow_record = sub.add_parser("shadow-record", help="Record a prediction for later shadow scoring")
    shadow_record.add_argument("prediction_id")
    shadow_eval = sub.add_parser("shadow-evaluate", help="Score shadow records whose labels matured")
    shadow_eval.add_argument("--cutoff")
    shadow_state = sub.add_parser("shadow-status", help="Show matured shadow days for a model")
    shadow_state.add_argument("--model")
    promote = sub.add_parser("stable-promote", help="Promote a model after an authorised shadow run")
    promote.add_argument("model_version")
    promote.add_argument("--authorize", action="store_true")
    promote.add_argument("--note", default="")
    revoke = sub.add_parser("stable-revoke", help="Revoke a stable release")
    revoke.add_argument("model_version")
    revoke.add_argument("--reason", default="")
    sub.add_parser("release-status", help="List stable releases and revocations")
    key_revoke = sub.add_parser("key-revoke", help="Add a publisher key fingerprint to the revocation list")
    key_revoke.add_argument("fingerprint")
    key_revoke.add_argument("--reason", default="")
    sub.add_parser("key-status", help="List revoked publisher keys")
    auth = sub.add_parser("dataset-auth", help="Show this identity's snapshot authorization record")
    auth.add_argument("snapshot_id")
    submit = sub.add_parser("train-submit", help="Queue one owner-scoped retraining from a parent model")
    submit.add_argument("parent_version")
    submit.add_argument("--snapshot", required=True)
    submit.add_argument("--cutoff", required=True)
    submit.add_argument("--method", choices=("full_retrain", "continue_train"), default="full_retrain")
    submit.add_argument("--rounds", type=int, default=50, help="Additional boosting rounds for continue_train")
    submit.add_argument("--priority", type=int, default=0, help="Claim order only; never preempts a running job")
    submit.add_argument("--timeout", type=int, default=300, help="Hard budget in seconds (2..3600)")
    submit.add_argument("--max-rows", type=int, default=200000)
    submit.add_argument("--allow-unverified-real", action="store_true")
    worker = sub.add_parser("train-worker", help="Run the single local training worker")
    worker.add_argument("--once", action="store_true", help="Process at most one job")
    worker.add_argument("--poll", type=float, default=0.2)
    worker.add_argument("--workers", type=int, default=1, help="Parallel local workers (1..8)")
    sub.add_parser("train-list", help="List this identity's training jobs")
    status = sub.add_parser("train-status", help="Show one training job with stage progress")
    status.add_argument("job_id")
    cancel = sub.add_parser("train-cancel", help="Cancel a queued or running training job")
    cancel.add_argument("job_id")


def dispatch(cfg, args):
    from .contracts import contract_id, read_contract
    from .model_registry import evaluate_model, list_models, predict_snapshot, publish_demo, select_model, train_platform
    with tracked_run(cfg, args.command):
        if args.command in ("model-keygen", "model-export", "model-install"):
            from .model_packages import export_package, generate_key, install_package
            if args.command == "model-keygen":
                result = generate_key(cfg)
            elif args.command == "model-export":
                result = export_package(cfg, args.model_version, args.output, args.signing_key)
            else:
                result = install_package(cfg, args.package, args.trust_key)
        elif args.command == "dataset-authorize":
            from . import dataset_auth
            if args.platform and args.revoke_platform:
                raise ValueError("cannot grant and revoke platform training in one call")
            if args.replay and args.revoke_replay:
                raise ValueError("cannot grant and revoke replay in one call")
            if args.platform and not args.note.strip():
                raise ValueError("granting platform training requires --note recording the confirmed data rights")
            result = dataset_auth.set_authorization(
                cfg, args.snapshot_id,
                personal=False if args.revoke_personal else None,
                platform=True if args.platform else False if args.revoke_platform else None,
                replay=True if args.replay else False if args.revoke_replay else None,
                note=args.note)
        elif args.command == "dataset-auth":
            from . import dataset_auth
            result = dataset_auth.describe(cfg, args.snapshot_id)
        elif args.command == "model-drift":
            from .drift import feature_drift
            result = feature_drift(cfg, args.model_version, args.snapshot, args.cutoff, args.window_days)
        elif args.command == "drift-history":
            from .drift import drift_history
            result = drift_history(cfg)
        elif args.command == "model-retention":
            from .retention import apply_retention, plan_retention
            plan = plan_retention(cfg, args.keep)
            result = apply_retention(cfg, plan) if args.apply else plan
        elif args.command == "retention-log":
            from .retention import retention_log
            result = retention_log(cfg)
        elif args.command == "prediction-report":
            from .generation import generate_brief
            from .prediction_report import build_prediction_report, load_prediction
            prediction = load_prediction(cfg, args.prediction_id)
            from .knowledge import retrieve
            evidence = retrieve(cfg, args.query, prediction["cutoff"])
            brief = generate_brief(cfg, prediction, evidence, allow_generation=args.generate)
            result = build_prediction_report(cfg, args.prediction_id, args.query, generation=brief)
        elif args.command == "shadow-record":
            from .shadow import record_shadow
            result = record_shadow(cfg, args.prediction_id)
        elif args.command == "shadow-evaluate":
            from .shadow import evaluate_shadow
            result = evaluate_shadow(cfg, args.cutoff)
        elif args.command == "shadow-status":
            from .shadow import shadow_status
            result = shadow_status(cfg, args.model)
        elif args.command == "stable-promote":
            from .shadow import promote_stable
            result = promote_stable(cfg, args.model_version, authorize=args.authorize, note=args.note)
        elif args.command == "stable-revoke":
            from .shadow import revoke_stable
            result = revoke_stable(cfg, args.model_version, args.reason)
        elif args.command == "release-status":
            from .shadow import release_status
            result = release_status(cfg)
        elif args.command == "key-revoke":
            from .keys import revoke_key
            result = revoke_key(cfg, args.fingerprint, args.reason)
        elif args.command == "key-status":
            from .keys import revoked_keys
            result = revoked_keys(cfg)
        elif args.command == "train-submit":
            from .model_training import submit_training
            result = submit_training(cfg, args.parent_version, args.snapshot, args.cutoff, method=args.method,
                                     additional_rounds=args.rounds, priority=args.priority,
                                     timeout_seconds=args.timeout, max_rows=args.max_rows,
                                     allow_unverified_real=args.allow_unverified_real)
        elif args.command == "train-worker":
            from .model_training import run_worker
            result = run_worker(cfg, once=args.once, poll=args.poll, workers=args.workers)
        elif args.command == "train-list":
            from .model_training import train_list
            result = train_list(cfg)
        elif args.command == "train-status":
            from .model_training import train_status
            result = train_status(cfg, args.job_id)
        elif args.command == "train-cancel":
            from .model_training import train_cancel
            result = train_cancel(cfg, args.job_id)
        elif args.command == "model-compare":
            from .model_training import compare_models
            result = compare_models(cfg, args.candidate_version, args.baseline, args.snapshot, args.cutoff,
                                    segments=args.segments)
        elif args.command == "residual-fit":
            from .residual import fit_residual_adapter
            result = fit_residual_adapter(cfg, args.parent_version, args.snapshot, args.cutoff,
                                          folds=args.folds, alpha=args.alpha, shrink=args.shrink,
                                          allow_unverified_real=args.allow_unverified_real)
        elif args.command == "contract-check":
            contract = read_contract(args.contract)
            result = {"contract_id": contract_id(contract), "contract": contract}
        elif args.command == "model-train":
            result = train_platform(cfg, args.snapshot_id, read_contract(args.contract), args.cutoff, args.algorithm,
                                    confirm_platform_data=args.confirm_platform_data, allow_unverified_real=args.allow_unverified_real)
        elif args.command == "model-evaluate":
            result = evaluate_model(cfg, args.model_version, args.snapshot_id, args.cutoff, allow_unverified_real=args.allow_unverified_real)
        elif args.command == "model-publish":
            result = publish_demo(cfg, args.model_version, args.evaluation)
        elif args.command == "model-select":
            result = select_model(cfg, args.model_version, allow_demo=args.allow_demo, confirm_personal=args.confirm_personal)
        elif args.command == "model-list":
            result = list_models(cfg)
        else:
            result = predict_snapshot(cfg, args.snapshot_id, args.cutoff, args.model,
                                      allow_demo=args.allow_demo, allow_personal=args.allow_personal)
        print(json.dumps(result, ensure_ascii=False, indent=2))
