"""Disposable loopback console for gstack browser checks; never calls a real model.

Run: uv run python tests/browser_console_fixture.py --port 8768
"""
from __future__ import annotations

import argparse
import tempfile
import threading
from pathlib import Path

from cryptography.fernet import Fernet

from stock_predict_mailer.control.market_feed import MarketFeed
from stock_predict_mailer.control.server import make_server
from test_cleaning_agent import RELATION, FakeCleaner, candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    stopped = threading.Event()
    with tempfile.TemporaryDirectory(prefix="console-browser-") as folder:
        server = make_server(Path(folder), args.port, Fernet.generate_key(), MarketFeed(fetchers=()))
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
