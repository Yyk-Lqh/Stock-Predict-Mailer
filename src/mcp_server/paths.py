"""Writable crawler paths, independent of the Python installation directory."""
import os
from pathlib import Path


def workspace() -> Path:
    configured = os.environ.get("STOCK_PREDICT_MAILER_CRAWLER_WORKSPACE")
    return Path(configured).expanduser().resolve() if configured else Path.cwd() / "data" / "crawler"


def data_dir() -> Path:
    return workspace() / "data"
