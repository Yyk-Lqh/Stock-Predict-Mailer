"""The single source of truth for this project's name.

The project is called **Stock-Predict-Mailer**. Three mechanical forms of that
one name are legitimate, and each is fixed by an external rule rather than by
taste:

===============  ======================  =========================================
constant         value                   where it must be used
===============  ======================  =========================================
PROJECT_NAME     ``Stock-Predict-Mailer``  prose, titles, UI, log banners, docs
DISTRIBUTION     ``stock-predict-mailer``  package index / ``uv`` / ``pip`` names
PACKAGE          ``stock_predict_mailer``  import path and directory name
COMMAND          ``stock-predict-mailer``  the console entry point
===============  ======================  =========================================

Two derived identifiers follow the same prefix so no fourth spelling appears:

* environment variables are ``STOCK_PREDICT_MAILER_<KEY>`` (see :func:`env`);
* the legacy prefix ``SPM_`` is still *read* so existing local ``.env`` files keep
  working, but it is never written, documented as current, or emitted.

Anything outside this module that hardcodes the name is a bug; ``scripts/check_naming.py``
fails the build when a stray variant (space-separated, underscore-separated) shows up.
"""
from __future__ import annotations

import os

PROJECT_NAME = "Stock-Predict-Mailer"
DISTRIBUTION_NAME = "stock-predict-mailer"
PACKAGE_NAME = "stock_predict_mailer"
COMMAND = "stock-predict-mailer"

ENV_PREFIX = "STOCK_PREDICT_MAILER"
LEGACY_ENV_PREFIX = "SPM"

SUMMARY_ZH = "预测分析 Agent + 邮件通知服务"
SUMMARY_EN = "Prediction analysis agent and reliable email notification service"


def env(name: str, default: str = "") -> str:
    """Read ``STOCK_PREDICT_MAILER_<name>``, falling back to the legacy ``SPM_<name>``.

    The fallback exists only so a machine configured before 0.5.1 keeps starting;
    new documentation and new configuration must use the canonical prefix.
    """
    key = f"{ENV_PREFIX}_{name}"
    value = os.environ.get(key)
    if value is None:
        value = os.environ.get(f"{LEGACY_ENV_PREFIX}_{name}")
    return default if value is None else value


def env_key(name: str) -> str:
    """Canonical variable name for ``name``, for messages and documentation."""
    return f"{ENV_PREFIX}_{name}"


def version() -> str:
    from . import __version__

    return __version__


def banner() -> str:
    return f"{PROJECT_NAME} {version()}"
