"""Static whitelist of plugins: a table in this file, never a runtime discovery.

``Registry`` only answers for ids declared here. Nothing reads an entry point, an
environment variable or a path from configuration, so installing a package is
never enough to become a plugin. That is the whole security model for in-process
extensions, and it is deliberately dull.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
from collections.abc import Callable, Sequence
from pathlib import Path

from .builtin.eastmoney import EastmoneySource
from .builtin.export import CsvExporter, JsonLinesExporter, ParquetExporter
from .builtin.market import SinaSource, TencentSource
from .builtin.report import HtmlReport, TextReport
from .contract import API_VERSION, KINDS, validate_manifest
from .errors import PluginError, PluginIncompatible, PluginKindMismatch, PluginMissingDependency, PluginNotFound

_REQUIRED_METHODS = {"market_source": ("quotes",), "report_renderer": ("render",), "notifier": ("send",),
                     "exporter": ("export",)}
_OPTIONAL_METHODS = {"market_source": ("candles", "bars")}
_NOT_FOUND = "未声明的插件：{id}（只接受内置白名单中的 id）"


def _absent(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is None
    except (ImportError, ValueError):
        return True


def _module_digest(adapter) -> str | None:
    """sha256 of the module file a plugin lives in; ``None`` when it cannot be read.

    This identifies the *file*, not the class: two plugins declared side by side
    share one fingerprint. That is stated plainly rather than papered over.
    """
    try:
        path = inspect.getsourcefile(type(adapter))
    except TypeError:
        return None
    if not path:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


class Registry:
    """Ordered, validated, immutable-after-import set of declared plugins."""

    def __init__(self, adapters: Sequence = ()):
        self._order = []
        self._index = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter) -> None:
        manifest = validate_manifest(getattr(adapter, "manifest", None))
        if manifest.id in self._index:
            raise PluginError(f"插件 id 重复：{manifest.id}")
        for method in _REQUIRED_METHODS[manifest.kind]:
            if not callable(getattr(adapter, method, None)):
                raise PluginIncompatible(f"插件 {manifest.id} 缺少方法 {method}")
        for method in _OPTIONAL_METHODS.get(manifest.kind, ()):
            if method in manifest.capabilities and not callable(getattr(adapter, method, None)):
                raise PluginIncompatible(f"插件 {manifest.id} 声明了 {method} 能力却没有实现该方法")
        self._order.append(adapter)
        self._index[manifest.id] = adapter

    def select(self, kind: str) -> tuple:
        """Declared plugins of one kind, in declaration order."""
        if kind not in KINDS:
            raise PluginIncompatible(f"不支持的插件类型：{kind}")
        return tuple(adapter for adapter in self._order if adapter.manifest.kind == kind)

    def resolve(self, plugin_id: str, kind: str | None = None):
        """One plugin, refusing an undeclared id, a wrong kind or a missing extra."""
        adapter = self._index.get(plugin_id)
        if adapter is None:
            raise PluginNotFound(_NOT_FOUND.format(id=plugin_id))
        if kind is not None and adapter.manifest.kind != kind:
            raise PluginKindMismatch(f"插件 {plugin_id} 的用途是 {adapter.manifest.kind}，不是 {kind}")
        missing = self.missing_dependencies(plugin_id)
        if missing:
            raise PluginMissingDependency(
                f"插件 {plugin_id} 需要可选依赖 {list(missing)}，请安装 .[{adapter.manifest.extra}] 后重试")
        return adapter

    def resolve_many(self, kind: str, plugin_ids: Sequence[str]) -> tuple:
        """Resolve an explicit chain in order, refusing to skip an unavailable plugin."""
        return tuple(self.resolve(plugin_id, kind) for plugin_id in plugin_ids)

    def missing_dependencies(self, plugin_id: str) -> tuple[str, ...]:
        adapter = self._index.get(plugin_id)
        if adapter is None:
            raise PluginNotFound(_NOT_FOUND.format(id=plugin_id))
        return tuple(name for name in adapter.manifest.requires if _absent(name))

    def available(self, plugin_id: str) -> bool:
        return not self.missing_dependencies(plugin_id)

    def describe(self) -> dict:
        return {
            "api_version": API_VERSION,
            "kinds": list(KINDS),
            "plugins": [{"id": adapter.manifest.id, "kind": adapter.manifest.kind, "label": adapter.manifest.label,
                         "capabilities": list(adapter.manifest.capabilities),
                         "requires": list(adapter.manifest.requires), "extra": adapter.manifest.extra,
                         "available": self.available(adapter.manifest.id),
                         "module": type(adapter).__module__,
                         "module_digest": _module_digest(adapter)}
                        for adapter in self._order],
        }

    def identity(self, plugin_id: str) -> dict:
        """What a frozen artifact records: the declared id, its module and that module's digest."""
        adapter = self._index.get(plugin_id)
        if adapter is None:
            raise PluginNotFound(_NOT_FOUND.format(id=plugin_id))
        return {"id": plugin_id, "module": type(adapter).__module__, "module_digest": _module_digest(adapter)}


BUILTIN = Registry((TencentSource(), SinaSource(), EastmoneySource(), CsvExporter(), JsonLinesExporter(),
                     ParquetExporter(), TextReport(), HtmlReport()))
# Declaring a source does not put it in the display chain: only these ids are
# contacted unless ``market.json`` names another set explicitly.
DEFAULT_MARKET_SOURCES = ("market_tencent", "market_sina")


def select(kind: str) -> tuple:
    return BUILTIN.select(kind)


def resolve(plugin_id: str, kind: str | None = None):
    return BUILTIN.resolve(plugin_id, kind)


def describe() -> dict:
    """Declared plugins, plus which market sources the default chain would contact."""
    body = BUILTIN.describe()
    body["default_chain"] = list(DEFAULT_MARKET_SOURCES)
    for entry in body["plugins"]:
        if entry["kind"] == "market_source":
            entry["default"] = entry["id"] in DEFAULT_MARKET_SOURCES
    return body


def identity(plugin_id: str) -> dict:
    return BUILTIN.identity(plugin_id)


def market_fetchers(source_ids: Sequence[str] | None = None) -> tuple[tuple[str, Callable], ...]:
    """The display fallback chain, primary source first."""
    ids = DEFAULT_MARKET_SOURCES if source_ids is None else source_ids
    return tuple((adapter.manifest.label, adapter.quotes) for adapter in BUILTIN.resolve_many("market_source", ids))


def market_candles(source_ids: Sequence[str] | None = None) -> Callable:
    """The first selected source that declares the overview chart's daily bars."""
    ids = DEFAULT_MARKET_SOURCES if source_ids is None else source_ids
    for adapter in BUILTIN.resolve_many("market_source", ids):
        if "candles" in adapter.manifest.capabilities:
            return adapter.candles
    raise PluginNotFound("选定的行情源都没有声明 candles 能力，无法绘制概览图")


def exporter(fmt: str):
    """The declared exporter for one output format, refusing an undeclared format."""
    for adapter in BUILTIN.select("exporter"):
        if fmt in adapter.manifest.capabilities:
            return adapter
    raise PluginNotFound(f"没有声明 {fmt} 导出能力的插件")
