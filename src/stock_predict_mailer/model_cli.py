from __future__ import annotations

import json
from pathlib import Path

from .core import tracked_run

COMMANDS = {"contract-check", "model-train", "model-evaluate", "model-publish", "model-list", "model-select", "model-predict"}


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
    select = sub.add_parser("model-select", help="Select a published model for this local identity")
    select.add_argument("model_version")
    select.add_argument("--allow-demo", action="store_true")
    predict = sub.add_parser("model-predict", help="Load selected native model and infer; never fit")
    predict.add_argument("snapshot_id")
    predict.add_argument("--cutoff", required=True)
    predict.add_argument("--model")
    predict.add_argument("--allow-demo", action="store_true")


def dispatch(cfg, args):
    from .contracts import contract_id, read_contract
    from .model_registry import evaluate_model, list_models, predict_snapshot, publish_demo, select_model, train_platform
    with tracked_run(cfg, args.command):
        if args.command == "contract-check":
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
            result = select_model(cfg, args.model_version, allow_demo=args.allow_demo)
        elif args.command == "model-list":
            result = list_models(cfg)
        else:
            result = predict_snapshot(cfg, args.snapshot_id, args.cutoff, args.model, allow_demo=args.allow_demo)
        print(json.dumps(result, ensure_ascii=False, indent=2))
