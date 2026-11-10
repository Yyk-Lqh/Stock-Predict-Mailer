#!/usr/bin/env python
"""Fail when a stray spelling of the project name appears in the repository.

The project is called **Stock-Predict-Mailer**. ``src/stock_predict_mailer/naming.py``
explains which mechanical form belongs where; this script is the enforcement.

Checks, in order of how often they actually break:

1. misspellings of the proper name (``Stock Predict Mailer``, ``Stock_Predict_Mailer``);
2. the retired CLI alias ``stock-mailer`` (the command is ``stock-predict-mailer``);
3. the retired UI brand ``Signal Desk``;
4. the legacy env prefix ``SPM_`` outside the two places that are allowed to know
   about it (``naming.py`` defines it, ``tests/`` proves the fallback works).

Historical archives are skipped on purpose: rewriting an old README would make the
record claim something that never happened.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_PREFIXES = (".git/", ".workbuddy/", "data/", "artifacts/", "node_modules/", "__pycache__/", ".tmp")
SKIP_FILES = {"docs/legacy-readme.md", "scripts/check_naming.py", "tests/test_naming.py"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".html", ".js", ".css", ".txt", ".cfg", ".ini", ".ps1", ".sh"}

# Why each rule exists, printed with the finding so the fix is obvious.
RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("proper-name", re.compile(r"Stock[ _]Predict[ _]Mailer|StockPredictMailer(?!\w)"),
     "prose must read Stock-Predict-Mailer (hyphenated, three capitals)"),
    ("old-command", re.compile(r"(?<![\w-])stock-mailer(?![\w-])"),
     "the CLI entry point is stock-predict-mailer"),
    ("old-brand", re.compile(r"Signal Desk"),
     "the UI brand is Stock-Predict-Mailer"),
    ("legacy-env", re.compile(r"(?<![\w])SPM_[A-Z]"),
     "environment variables are STOCK_PREDICT_MAILER_<KEY>"),
]
LEGACY_ENV_ALLOWED = ("src/stock_predict_mailer/naming.py", "tests/")


def repository_files() -> list[str]:
    try:
        tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        untracked = subprocess.run(["git", "ls-files", "-z", "--others", "--exclude-standard"],
                                   cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        print("naming: git not available, skipping")
        return []
    names = (tracked + untracked).decode("utf-8", "replace").split("\0")
    return [name for name in names if name]


def main() -> int:
    findings: list[str] = []
    for name in repository_files():
        if name in SKIP_FILES or name.startswith(SKIP_PREFIXES):
            continue
        path = ROOT / name
        if path.suffix not in TEXT_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for rule, pattern, hint in RULES:
                if not pattern.search(line):
                    continue
                if rule == "legacy-env" and name.startswith(LEGACY_ENV_ALLOWED):
                    continue
                findings.append(f"{name}:{lineno}: [{rule}] {line.strip()[:110]}\n    → {hint}")
    if findings:
        print("\n".join(findings))
        print(f"\nnaming: {len(findings)} stray reference(s); see src/stock_predict_mailer/naming.py")
        return 1
    print("naming: Stock-Predict-Mailer is spelled consistently")
    return 0


if __name__ == "__main__":
    sys.exit(main())
