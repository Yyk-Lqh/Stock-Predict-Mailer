"""Bounded native model formats; no pickle loading in the published-model path."""
from __future__ import annotations

import json

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from .contracts import FEATURE_ORDER

ALGORITHMS = ("zero", "momentum", "ridge", "lightgbm")
# Derived formats are loadable but never fitted by ``fit_native``: they wrap a
# frozen parent model instead of training from rows.
DERIVED = ("residual",)
LOADABLE = ALGORITHMS + DERIVED
ARTIFACTS = {algorithm: ("model.txt" if algorithm == "lightgbm" else "model.json") for algorithm in ALGORITHMS}
ARTIFACTS["residual"] = "adapter.json"

# Declared capabilities, not aspirations: a method that is not listed here cannot
# be queued, so "continue training" is never offered for a format that cannot do it.
MAX_ADDITIONAL_ROUNDS = 200
CAPABILITIES = {
    "zero": {"family": "constant", "supports_continue": False, "native_format": "json"},
    "momentum": {"family": "rule", "supports_continue": False, "native_format": "json"},
    "ridge": {"family": "linear", "supports_continue": False, "native_format": "json",
              "reason": "a closed-form linear fit has no partially trained state to continue"},
    "lightgbm": {"family": "boosted_trees", "supports_continue": True, "native_format": "text",
                 "max_additional_rounds": MAX_ADDITIONAL_ROUNDS},
    "residual": {"family": "adapter", "supports_continue": False, "native_format": "json"},
}


def capability(algorithm: str) -> dict:
    if algorithm not in CAPABILITIES:
        raise ValueError("unsupported model algorithm")
    return {"algorithm": algorithm, **CAPABILITIES[algorithm]}


def fit_native(algorithm: str, rows: list[dict]) -> tuple[str, bytes]:
    if algorithm not in ALGORITHMS:
        raise ValueError("unsupported model algorithm")
    x = np.asarray([r["x"] for r in rows], dtype=float)
    y = np.asarray([r["y"] for r in rows], dtype=float)
    if x.shape != (len(rows), len(FEATURE_ORDER)) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("invalid training matrix")
    state = {"algorithm": algorithm, "features": list(FEATURE_ORDER)}
    if algorithm == "ridge":
        scaler = StandardScaler().fit(x)
        model = Ridge(alpha=100.0).fit(scaler.transform(x), y)
        state.update(mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(), coef=model.coef_.tolist(), intercept=float(model.intercept_))
    if algorithm == "lightgbm":
        import lightgbm as lgb
        dataset = lgb.Dataset(x, label=y, feature_name=list(FEATURE_ORDER))
        model = lgb.train({"objective": "regression", "num_leaves": 7, "max_depth": 3,
                           "min_data_in_leaf": 30, "learning_rate": 0.03, "num_threads": 2,
                           "verbosity": -1, "seed": 42, "deterministic": True, "force_col_wise": True},
                          dataset, num_boost_round=100)
        return "model.txt", model.model_to_string().encode("utf-8")
    return "model.json", json.dumps(state, sort_keys=True, allow_nan=False).encode("utf-8")


def continue_native(algorithm: str, parent_payload: bytes, rows: list[dict], additional_rounds: int) -> tuple[str, bytes]:
    """Bounded continuation of a native LightGBM model.

    Only boosted trees have a partially trained state worth continuing. The round
    budget is capped so "continue" can never silently become a second full fit.
    """
    declared = capability(algorithm)
    if not declared.get("supports_continue"):
        raise ValueError(f"{algorithm} cannot continue training")
    if type(additional_rounds) is not int or not 1 <= additional_rounds <= declared["max_additional_rounds"]:
        raise ValueError(f"additional rounds must be in 1..{declared['max_additional_rounds']}")
    if not parent_payload:
        raise ValueError("missing parent artifact")
    import lightgbm as lgb

    parent = lgb.Booster(model_str=parent_payload.decode("utf-8"))
    if parent.feature_name() != list(FEATURE_ORDER):
        raise ValueError("parent native model feature order mismatch")
    x = np.asarray([r["x"] for r in rows], dtype=float)
    y = np.asarray([r["y"] for r in rows], dtype=float)
    if x.shape != (len(rows), len(FEATURE_ORDER)) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("invalid training matrix")
    dataset = lgb.Dataset(x, label=y, feature_name=list(FEATURE_ORDER))
    continued = lgb.train({"objective": "regression", "num_leaves": 7, "max_depth": 3,
                           "min_data_in_leaf": 30, "learning_rate": 0.03, "num_threads": 2,
                           "verbosity": -1, "seed": 42, "deterministic": True, "force_col_wise": True},
                          dataset, num_boost_round=additional_rounds, init_model=parent)
    return "model.txt", continued.model_to_string().encode("utf-8")


def native_predict(algorithm: str, payload: bytes, rows: list[dict]) -> np.ndarray:
    if len(payload) > 50 * 1024 * 1024:
        raise ValueError("model exceeds size limit")
    x = np.asarray([r["x"] for r in rows], dtype=float)
    if x.shape != (len(rows), len(FEATURE_ORDER)) or not np.isfinite(x).all():
        raise ValueError("incompatible prediction matrix")
    if algorithm == "lightgbm":
        import lightgbm as lgb
        model = lgb.Booster(model_str=payload.decode("utf-8"))
        if model.feature_name() != list(FEATURE_ORDER):
            raise ValueError("native model feature order mismatch")
        scores = model.predict(x, num_threads=2)
    else:
        state = json.loads(payload)
        if state.get("algorithm") != algorithm or state.get("features") != list(FEATURE_ORDER):
            raise ValueError("native model metadata mismatch")
        if algorithm == "zero":
            scores = np.zeros(len(rows))
        elif algorithm == "momentum":
            scores = x[:, 2]
        elif algorithm == "ridge":
            arrays = [np.asarray(state[name], dtype=float) for name in ("mean", "scale", "coef")]
            if any(a.shape != (len(FEATURE_ORDER),) or not np.isfinite(a).all() for a in arrays):
                raise ValueError("invalid native linear model state")
            mean, scale, coef = arrays
            if np.any(scale <= 0) or not np.isfinite(float(state["intercept"])):
                raise ValueError("invalid native scaler or intercept")
            scores = ((x - mean) / scale) @ coef + float(state["intercept"])
        else:
            raise ValueError("unsupported model algorithm")
    if not np.isfinite(scores).all():
        raise ValueError("model produced nonfinite predictions")
    return np.asarray(scores)
