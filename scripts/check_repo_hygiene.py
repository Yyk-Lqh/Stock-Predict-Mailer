#!/usr/bin/env python
"""Reject tracked files that must never enter the repository.

Runs on every pull request. It only inspects paths and small text files, so it
cannot false-positive on generated data inside a local workspace (which is
ignored by git anyway).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".txt", ".yml", ".yaml", ".cfg", ".ini", ".ps1", ".sh"}
FORBIDDEN_DIRS = {"data", "secrets", "workspace", "reports", "logs", "backups", "artifacts", "models"}
FORBIDDEN_SUFFIXES = {
    ".parquet", ".pkl", ".pickle", ".zip", ".eml", ".sqlite", ".sqlite3",
    ".key", ".pem", ".p12", ".pfx", ".log", ".csv", ".xlsx", ".xls", ".db",
}
FORBIDDEN_NAMES = {".env", "publisher.key", "publisher.pub", "id_ed25519", "id_rsa"}
# Split so this file does not match its own rule.
KEY_HEADER = "-----BEGIN " + "PRIVATE KEY-----"


def tracked_files() -> list[Path]:
    try:
        raw = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        print("hygiene: git not available, skipping")
        return []
    return [Path(name) for name in raw.decode("utf-8", "replace").split("\0") if name]


def problem(path: Path) -> str | None:
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
    if size > MAX_BYTES:
        return f"file larger than {MAX_BYTES // (1024 * 1024)} MiB ({size} bytes)"
    if path.suffix.lower() in TEXT_SUFFIXES and size < 1024 * 1024:
        if KEY_HEADER in path.read_text(encoding="utf-8", errors="ignore"):
            return "embedded private key material"
    return None


def main() -> int:
    files = tracked_files()
    violations: list[tuple[Path, str]] = []
    for path in files:
        reason = problem(path)
        if reason:
            violations.append((path, reason))
    if not violations:
        print(f"hygiene: {len(files)} tracked files look clean")
        return 0
    print("hygiene: refusing these tracked files", file=sys.stderr)
    for path, reason in violations:
        print(f"  - {path}: {reason}", file=sys.stderr)
    print("Remove them from the index (git rm --cached) and add a .gitignore rule.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
