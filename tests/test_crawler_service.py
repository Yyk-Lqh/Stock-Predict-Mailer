"""Crawler contracts and local MCP transports; never contact a market provider."""
import asyncio
import builtins
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from mcp_server import server

ENV_KEY = "STOCK_PREDICT_MAILER_CRAWLER_WORKSPACE"


class CrawlerContractTests(unittest.TestCase):
    def test_status_is_read_only_and_does_not_import_optional_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "not-created"
            original = builtins.__import__

            def guarded(name, *args, **kwargs):
                if name.split(".")[0] in {"pandas", "requests", "baostock"}:
                    raise AssertionError(f"Unexpected import: {name}")
                return original(name, *args, **kwargs)

            with patch.dict(os.environ, {ENV_KEY: str(target)}), patch("builtins.__import__", side_effect=guarded):
                status = json.loads(server.crawler_status())
            self.assertEqual(Path(status["pool_file"]), target.resolve() / "data" / "stock_data117.csv")
            self.assertFalse(status["pool_exists"])
            self.assertEqual(status["date_policy"], "current_date")
            self.assertFalse(target.exists())

    def test_missing_dependency_returns_actionable_json(self):
        original = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "mcp_server.catalog_crawler":
                raise ModuleNotFoundError("No module named requests")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded):
            result = json.loads(server.crawl_stock_catalog())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "DEPENDENCY_MISSING")

    def test_invalid_limits_are_rejected_before_import_or_collection(self):
        result = json.loads(server.collect_fundamental_data(-1))
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_cli_configures_loopback_and_transport_via_actual_sdk(self):
        with patch.object(server.FastMCP, "run", autospec=True) as run:
            server.main(["--http", "--port", "18765"])
        instance = run.call_args.args[0]
        self.assertEqual(instance.settings.host, "127.0.0.1")
        self.assertEqual(instance.settings.port, 18765)
        self.assertEqual(run.call_args.kwargs, {"transport": "streamable-http"})

    def test_cli_rejects_invalid_port(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit) as caught:
            server.main(["--port", "65536"])
        self.assertEqual(caught.exception.code, 2)

    def test_legacy_script_help(self):
        script = Path(server.__file__)
        result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(all(importlib.util.find_spec(n) for n in ("pandas", "requests", "baostock")), "requires crawler extra")
    def test_offline_verification_preserves_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / "data" / "stock_data117.csv"
            sentinel.parent.mkdir()
            sentinel.write_bytes(b"must remain unchanged")
            env = dict(os.environ, **{ENV_KEY: str(root)})
            result = subprocess.run([sys.executable, "-m", "mcp_server.verify"],
                                    env=env, capture_output=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertEqual(json.loads(result.stdout)["mode"], "offline_synthetic")
            self.assertEqual(sentinel.read_bytes(), b"must remain unchanged")
            self.assertEqual(sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()),
                             ["data/stock_data117.csv"])


class CrawlerTransportTests(unittest.IsolatedAsyncioTestCase):
    async def check_session(self, streams, target):
        async with ClientSession(streams[0], streams[1]) as client:
            await client.initialize()
            tools = await client.list_tools()
            self.assertEqual({t.name for t in tools.tools},
                             {"crawler_status", "crawl_stock_catalog", "collect_fundamental_data",
                              "submit_crawler_job", "get_crawler_job", "list_crawler_jobs",
                              "cancel_crawler_job", "resume_crawler_job", "crawler_job_events"})
            result = await client.call_tool("crawler_status", {})
            self.assertFalse(result.isError)
            status = json.loads(result.content[0].text)
            self.assertEqual(Path(status["pool_file"]), target.resolve() / "data" / "stock_data117.csv")
            self.assertFalse(status["pool_exists"])
            self.assertFalse(target.exists())

    async def test_stdio_discovery_and_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "not-created"
            parameters = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                               env=dict(os.environ, **{ENV_KEY: str(target)}))
            async with asyncio.timeout(25), stdio_client(parameters) as streams:
                await self.check_session(streams, target)

    async def test_http_discovery_and_status(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "not-created"
            env = dict(os.environ, **{ENV_KEY: str(target)})
            with tempfile.TemporaryFile() as log:
                process = subprocess.Popen([sys.executable, "-m", "mcp_server.server", "--http", "--port", str(port)],
                                           env=env, stdout=log, stderr=log)
                try:
                    async with asyncio.timeout(30), httpx.AsyncClient(trust_env=False, timeout=3) as http:
                        url = f"http://127.0.0.1:{port}/mcp"
                        deadline = time.monotonic() + 15
                        while True:
                            if process.poll() is not None:
                                log.seek(0)
                                self.fail(log.read().decode(errors="replace"))
                            try:
                                await http.get(url)
                                break
                            except httpx.ConnectError:
                                if time.monotonic() >= deadline:
                                    raise
                                await asyncio.sleep(0.1)
                        async with streamable_http_client(url, http_client=http) as streams:
                            await self.check_session(streams, target)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
