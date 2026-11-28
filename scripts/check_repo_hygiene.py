#!/usr/bin/env python
"""Reject tracked files, or nonignored local candidates, that must not enter the repository.

Runs on every pull request. It only inspects paths and small text files, so it
cannot false-positive on generated data inside a local workspace (which is
ignored by git anyway).
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
GENERATED_CONSOLE_BUNDLE = Path("src/stock_predict_mailer/control/web/memory.js")
GENERATED_CONSOLE_BUNDLE_MAX_BYTES = 2_288_000
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".txt", ".yml", ".yaml", ".cfg", ".ini", ".ps1", ".sh"}
FORBIDDEN_DIRS = {"data", "secrets", "workspace", "reports", "logs", "backups", "artifacts", "models"}
FORBIDDEN_SUFFIXES = {
    ".parquet", ".pkl", ".pickle", ".zip", ".eml", ".sqlite", ".sqlite3",
    ".key", ".pem", ".p12", ".pfx", ".log", ".csv", ".xlsx", ".xls", ".db",
}
FORBIDDEN_NAMES = {".env", "publisher.key", "publisher.pub", "id_ed25519", "id_rsa"}
# Split so this file does not match its own rule.
KEY_HEADER = "-----BEGIN " + "PRIVATE KEY-----"
# Training delivery d6cc73f. The inference adapter accepts this same artifact.
DELIVERED_MODEL = Path("src/数据面/random_forest_monthly.pkl")
DELIVERED_MODEL_SHA256 = "03c9b627004c39b9a60f292770417aaf561bc34fb2d41f829be5baf07f850dda"
# 周频相对强弱模型，由 相对市场跌涨/出名单.py 产出并复用；hash 留空表示只按路径放行。
DELIVERED_WEEKLY_MODEL = Path("src/数据面（大股池）/相对市场跌涨/周频模型_相对强弱.pkl")
DELIVERED_WEEKLY_MODEL_SHA256 = ""
APPROVED_MODELS = {DELIVERED_MODEL: DELIVERED_MODEL_SHA256,
                   DELIVERED_WEEKLY_MODEL: DELIVERED_WEEKLY_MODEL_SHA256}


def tracked_files(include_untracked: bool = False) -> list[Path]:
    try:
        command = ["git", "ls-files", "-z"]
        if include_untracked:
            command.extend(["--cached", "--others", "--exclude-standard"])
        raw = subprocess.run(command, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        if include_untracked:
            raise SystemExit("hygiene: git is required to check local candidate files") from None
        print("hygiene: git not available, skipping")
        return []
    return [Path(name) for name in raw.decode("utf-8", "replace").split("\0") if name]


def problem(path: Path) -> str | None:
    if path in APPROVED_MODELS:
        expected = APPROVED_MODELS[path]
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return "delivered model missing or larger than the approved artifact"
        if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            return "delivered model differs from the approved artifact"
        return None
    parts = path.parts
    if any(part in FORBIDDEN_DIRS for part in parts[:-1]):
        return f"forbidden directory: {path.parent}"
    if path.name in FORBIDDEN_NAMES or path.name.startswith(".env"):
        return "forbidden file name (credentials or key material)"
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return f"forbidden file type: {path.suffix}"
    if not path.is_file():
        return None
    size = path.stat().st_size
    limit = GENERATED_CONSOLE_BUNDLE_MAX_BYTES if path == GENERATED_CONSOLE_BUNDLE else MAX_BYTES
    if size > limit:
        return f"file larger than {limit} bytes ({size} bytes)"
    if path.suffix.lower() in TEXT_SUFFIXES and size < 1024 * 1024:
        if KEY_HEADER in path.read_text(encoding="utf-8", errors="ignore"):
            return "embedded private key material"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-untracked", action="store_true", help="Also check nonignored new files before staging")
    args = parser.parse_args()
    files = tracked_files(args.include_untracked)
    violations: list[tuple[Path, str]] = []
    for path in files:
        reason = problem(path)
        if reason:
            violations.append((path, reason))
    if not violations:
        scope = "local candidate" if args.include_untracked else "tracked"
        print(f"hygiene: {len(files)} {scope} files look clean")
        return 0
    scope = "local candidate" if args.include_untracked else "tracked"
    print(f"hygiene: refusing these {scope} files", file=sys.stderr)
    for path, reason in violations:
        print(f"  - {path}: {reason}", file=sys.stderr)
    if args.include_untracked:
        print("Keep these files out of version control; unstage tracked files and add appropriate ignore rules.", file=sys.stderr)
    else:
        print("Remove them from the index (git rm --cached) and add a .gitignore rule.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
