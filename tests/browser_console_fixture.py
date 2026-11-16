"""Disposable loopback console for gstack browser checks; never calls a real model.

Run: uv run python tests/browser_console_fixture.py --port 8768
"""
from __future__ import annotations

import argparse
import tempfile
import threading
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.analysis import AnalysisAgent
from stock_predict_mailer.agent_service.contracts import utcnow
from stock_predict_mailer.agent_service.forecast_archive import ForecastArchive
from stock_predict_mailer.control.market_feed import MarketFeed
from stock_predict_mailer.control.orchestrator import a2a_task
from stock_predict_mailer.control.server import make_server
from test_cleaning_agent import RELATION, FakeCleaner, candidate


def seed_forecasts(server):
    """Synthetic historical receipts for read-only browser state checks."""
    archive = ForecastArchive(server.engine.store.root)
    now = utcnow()
    for name, hours in (("pending", 0), ("due", 2), ("evaluated", 3)):
        generated = now - timedelta(hours=hours, minutes=1)
        p = {"schema_version": "1", "prediction_id": "browser-" + name, "subject": "DEMO.SZ", "generated_at": generated.isoformat(),
             "valid_until": (now + timedelta(hours=1)).isoformat(), "horizon": {"value": 1, "unit": "hours"},
             "model_version": "browser-synthetic", "synthetic": True, "direction": "up", "value": 110, "value_unit": "CNY"}
        d = {"schema_version": "1", "target_at": (generated + timedelta(hours=1)).isoformat(), "timezone": "Asia/Shanghai", "metric": "close_unadjusted",
             "unit": "CNY", "flat_tolerance": .1, "reference": {"value": 100, "observed_at": generated.isoformat(),
             "available_at": generated.isoformat(), "source": "<img src=x onerror=alert(1)>", "synthetic": True}}
        record = archive.register(p, d, now=generated + timedelta(seconds=10))["record"]
        analysis = AnalysisAgent().analyze(p, forecast_record=record)
        tid = "browser-" + name
        server.engine.store.task(tid, a2a_task(tid, "completed", result={"analysis": analysis, "children": [], "mail": None, "usage": {"calls": 0}}))
        if name == "evaluated":
            archive.evaluate(record["forecast_id"], {"schema_version": "1", "subject": p["subject"], "metric": d["metric"], "unit": d["unit"],
                "value": 112, "observed_at": d["target_at"], "available_at": d["target_at"], "source": "browser synthetic observation", "synthetic": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--forecast-fixtures", action="store_true")
    args = parser.parse_args()
    stopped = threading.Event()
    with tempfile.TemporaryDirectory(prefix="console-browser-") as folder:
        server = make_server(Path(folder), args.port, Fernet.generate_key(), MarketFeed(fetchers=()))
        if args.forecast_fixtures:
            seed_forecasts(server)
        server.engine.knowledge.cleaner = FakeCleaner([candidate(RELATION, valid_from="2026-01-01")])

        def worker():
            while not stopped.wait(.1):
                server.engine.knowledge.process_one()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        print(f"Disposable browser fixture: http://127.0.0.1:{args.port} (synthetic cleaner only)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stopped.set()
            thread.join(timeout=5)
            for task_id in list(server.engine.active):
                server.engine.cancel(task_id)
            server.server_close()


if __name__ == "__main__":
    main()
