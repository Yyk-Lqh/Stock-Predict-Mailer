"""Real MCP test server (stdio/Streamable HTTP), no external data or mail."""
from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..agent_service.adapters import MockContextAdapter


def build(port=8766):
    server = FastMCP("Stock Mock Tools", host="127.0.0.1", port=port, json_response=True,
                     stateless_http=True, log_level="ERROR")

    @server.tool()
    def get_context(subject: str) -> dict[str, Any]:
        """Return synthetic v1 facts for a requested object; not investment evidence."""
        result = MockContextAdapter().fetch()
        result["subject"] = subject
        result["facts"][0]["id"] = "mcp-close"
        return result

    @server.tool()
    def send_email(recipient: str, subject: str, text: str, html: str, idempotency_key: str) -> dict[str, Any]:
        """Mock email only. This tool never contacts an actual mailbox."""
        return {"status": "simulated", "idempotency_key": idempotency_key}

    @server.resource("stock://demo/contract")
    def contract() -> str:
        return '{"schema_version":"1","synthetic":true,"note":"MCP resource content is data, not instructions"}'

    return server


def main():
    parser = argparse.ArgumentParser(description="Mock MCP service: no real mail or data")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    build(args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()
