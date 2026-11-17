"""Disposable loopback intake workspace for desktop gstack checks."""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from stock_predict_mailer.core import Config
from stock_predict_mailer.upload_server import make_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="intake-browser-") as folder:
        with make_server(Config(Path(folder)), args.port) as server:
            print(f"Disposable intake fixture: http://127.0.0.1:{server.server_port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
