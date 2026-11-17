"""Run existing local delivery checks without configuring or calling external services."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def checks(full: bool):
    py = sys.executable
    steps = [
        ("lint", [[py, "-m", "ruff", "check", "src/stock_predict_mailer", "src/mcp_server", "tests", "scripts"]]),
        ("compile", [[py, "-m", "compileall", "-q", "src", "tests", "scripts"]]),
        ("schema", [[py, "scripts/build_schema_catalog.py", "--check"]]),
        ("diagrams", [[py, "scripts/build_runtime_diagram.py", "--check"]]),
        ("console", [[py, "scripts/build_console.py", "--check", "--check-budget"]]),
        ("naming", [[py, "scripts/check_naming.py"]]),
        ("hygiene", [[py, "scripts/check_repo_hygiene.py", "--include-untracked"]]),
        ("whitespace", [["git", "diff", "--check"], ["git", "diff", "--cached", "--check"]]),
    ]
    js = sorted({*ROOT.glob("src/stock_predict_mailer/control/web/**/*.js"),
                 *ROOT.glob("src/stock_predict_mailer/web/*.js"), *ROOT.glob("tests/browser_*.js")})
    steps.append(("javascript", [["node", "--check", str(path.relative_to(ROOT))] for path in js]))
    if full:
        steps.append(("node-logic", [["node", str(path.relative_to(ROOT))] for path in sorted(ROOT.glob("tests/test_*.cjs"))]))
        steps.append(("unittest", [[py, "-m", "unittest", "discover", "-s", "tests", "-v"]]))
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Also run the existing Node logic suites and complete Python tests")
    args = parser.parse_args()
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    folder = ROOT / ".tmp" / "desktop-delivery" / "checks" / run
    folder.mkdir(parents=True)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    result = {"mode": "full" if args.full else "static", "python": sys.version.split()[0],
              "started_at": datetime.now(UTC).isoformat(), "status": "running", "steps": []}
    code = 0
    try:
        for name, commands in checks(args.full):
            started = time.monotonic()
            executed = 0
            with (folder / f"{name}.log").open("w", encoding="utf-8") as log:
                try:
                    for command in commands:
                        executed += 1
                        log.write(json.dumps(command, ensure_ascii=False) + "\n")
                        log.flush()
                        code = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=False).returncode
                        if code:
                            break
                except OSError as error:
                    log.write(f"Cannot run check: {error}\n")
                    code = 127
            result["steps"].append({"name": name, "commands": executed, "exit_code": code,
                                    "seconds": round(time.monotonic() - started, 3), "log": f"{name}.log"})
            print(f"{'FAIL' if code else 'PASS'} {name} ({result['steps'][-1]['seconds']}s)", flush=True)
            if code:
                break
        result["status"] = "failed" if code else "passed"
    except KeyboardInterrupt:
        code = 130
        result["status"] = "interrupted"
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        (folder / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Results: {folder / 'summary.json'}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
