"""Read-only readiness check: will the display wall start, and what is unusable.

The console builds ``MarketFeed`` once at startup, so a bad ``sources`` value does
not degrade gracefully — it prevents the wall from coming up at all. This module
answers "would that config start?" before anyone restarts the console.
"""
from __future__ import annotations

from pathlib import Path

from ..control import market_feed
from . import github, registry
from .errors import PluginError


def _plugin_rows(root):
    rows = []
    for entry in registry.describe()["plugins"]:
        problems = []
        missing = registry.BUILTIN.missing_dependencies(entry["id"])
        if missing:
            problems.append(f"缺少可选依赖 {list(missing)}，请安装 .[{entry['extra']}] 后重试")
        rows.append({**entry, "problems": problems})
    return rows if root is None else rows + github.describe(root)


def check(market_root=None):
    """Return a report; a plugin or config problem becomes data, not an exception."""
    problems = []
    try:
        selected = market_feed.source_chain(market_root)
    except (PluginError, ValueError) as exc:
        selected, problems = None, [str(exc)]
    ids = list(registry.DEFAULT_MARKET_SOURCES if selected is None else selected)
    chain, candles_from = [], None
    if not problems:
        for plugin_id in ids:
            try:
                adapter = registry.resolve(plugin_id, "market_source")
            except PluginError as exc:
                problems.append(str(exc))
                continue
            chain.append(plugin_id)
            if candles_from is None and "candles" in adapter.manifest.capabilities:
                candles_from = plugin_id
        if candles_from is None and not problems:
            problems.append("选中的行情源都没有 candles 能力，概览图无法绘制")
    return {
        "ok": not problems,
        "market_file": str(Path(market_root) / "market.json") if market_root else None,
        "source_chain": chain,
        "candles_from": candles_from,
        "problems": problems,
        "plugins": _plugin_rows(market_root),
    }
