"""Frozen extension contracts: three narrow protocols and one declarative manifest.

A plugin is a plain object that satisfies one of the protocols structurally. It
does not inherit a base class, does not register hooks and cannot widen the task
contract: the manifest is data, and the registry reads nothing else.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .errors import PluginIncompatible

API_VERSION = 1
KINDS = ("market_source", "report_renderer", "notifier", "exporter", "chart_renderer")
KIND_CAPABILITIES = {
    "market_source": ("quotes", "candles", "bars"),
    "report_renderer": ("html", "text"),
    "notifier": ("send",),
    "exporter": ("csv", "json", "parquet"),
    "chart_renderer": ("line", "bar"),
}
PLUGIN_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
MAX_LABEL = 40


@dataclass(frozen=True)
class PluginManifest:
    """What a plugin claims before anyone calls it."""

    id: str
    kind: str
    label: str
    capabilities: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    extra: str = ""
    api_version: int = API_VERSION


def validate_manifest(manifest: PluginManifest) -> PluginManifest:
    """Reject a declaration that cannot be honoured; never repair it silently."""
    if not isinstance(manifest, PluginManifest):
        raise PluginIncompatible("插件声明必须是 PluginManifest")
    if type(manifest.api_version) is not int or manifest.api_version != API_VERSION:
        raise PluginIncompatible(f"插件 {manifest.id} 使用不兼容的接口版本 {manifest.api_version}，当前为 {API_VERSION}")
    if not isinstance(manifest.id, str) or not PLUGIN_ID.match(manifest.id):
        raise PluginIncompatible("插件 id 须为小写字母开头、下划线分隔的标识符")
    if manifest.kind not in KINDS:
        raise PluginIncompatible(f"插件 {manifest.id} 声明了不支持的用途：{manifest.kind}")
    if not isinstance(manifest.label, str) or not 1 <= len(manifest.label.strip()) <= MAX_LABEL:
        raise PluginIncompatible(f"插件 {manifest.id} 需要一个不超过 {MAX_LABEL} 字的显示名")
    if not isinstance(manifest.capabilities, tuple) or not manifest.capabilities:
        raise PluginIncompatible(f"插件 {manifest.id} 必须声明至少一项能力")
    if len(set(manifest.capabilities)) != len(manifest.capabilities):
        raise PluginIncompatible(f"插件 {manifest.id} 重复声明了能力")
    unknown = [name for name in manifest.capabilities if name not in KIND_CAPABILITIES[manifest.kind]]
    if unknown:
        raise PluginIncompatible(f"插件 {manifest.id} 声明了该用途不支持的能力：{sorted(unknown)}")
    if not isinstance(manifest.requires, tuple) or any(not MODULE_NAME.match(name) for name in manifest.requires):
        raise PluginIncompatible(f"插件 {manifest.id} 的依赖须为模块名元组")
    if len(set(manifest.requires)) != len(manifest.requires):
        raise PluginIncompatible(f"插件 {manifest.id} 重复声明了依赖")
    if manifest.requires and not manifest.extra:
        raise PluginIncompatible(f"插件 {manifest.id} 声明了可选依赖，必须同时声明安装它的 extra 名称")
    if manifest.extra and not MODULE_NAME.match(manifest.extra):
        raise PluginIncompatible(f"插件 {manifest.id} 的 extra 名称无效")
    return manifest


def declare(*, id: str, kind: str, label: str, capabilities: tuple[str, ...] = (),
            requires: tuple[str, ...] = (), extra: str = "") -> PluginManifest:
    """Build a validated manifest at class-definition time, so a typo fails on import."""
    return validate_manifest(PluginManifest(id=id, kind=kind, label=label, capabilities=capabilities,
                                            requires=requires, extra=extra))


class DataSourcePlugin(Protocol):
    """Read-only quote relay. ``quotes`` mirrors ``MarketFeed``'s fetcher signature.

    ``candles(symbol, timeout)`` and ``bars(symbol, start, end, timeout)`` are
    optional: a source declares them only when ``plugins-check`` will find a real
    implementation behind the name.
    """

    manifest: PluginManifest

    def quotes(self, instruments: Sequence[tuple[str, str]], timeout: float) -> list[dict]: ...


class ReportRenderer(Protocol):
    """Pure function over a frozen view: renders bytes, performs no IO of its own."""

    manifest: PluginManifest

    def render(self, view: Mapping[str, object]) -> bytes: ...


class ChartRenderer(Protocol):
    """Render a validated chart model as a standalone SVG."""

    manifest: PluginManifest

    def render(self, chart: Mapping[str, object]) -> str: ...


class Notifier(Protocol):
    """One delivery channel. Retry bookkeeping stays in the mail core, not here."""

    manifest: PluginManifest

    def send(self, message: Mapping[str, object]) -> Mapping[str, object]: ...


class Exporter(Protocol):
    """Write already-validated snapshot rows to one file.

    The format decides the encoding, never the meaning: column names, order and
    values come from the snapshot, and an exporter that would rewrite them is not
    an exporter.
    """

    manifest: PluginManifest

    def export(self, rows: Sequence[Mapping[str, object]], path) -> Mapping[str, object]: ...
