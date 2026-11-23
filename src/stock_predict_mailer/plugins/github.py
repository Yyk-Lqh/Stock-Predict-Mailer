"""Workspace-local declarative exporters imported from public GitHub repositories."""
from __future__ import annotations

import base64
import binascii
import re
import sqlite3
from contextlib import closing, contextmanager
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..agent_service.contracts import ServiceError, decode
from ..core import digest
from . import registry
from .builtin.export import DeclarativeExporter
from .contract import PLUGIN_ID, PluginManifest, validate_manifest
from .errors import PluginError, PluginIncompatible, PluginNotFound

MANIFEST_NAME = "stock-predict-mailer-plugin.json"
MAX_MANIFEST_BYTES = 8192
_REPOSITORY = re.compile(
    r"https://github\.com/([a-z0-9]+(?:-[a-z0-9]+)*)/([a-z0-9_.-]{1,100})/?", re.IGNORECASE | re.ASCII
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _download(repository: str) -> bytes:
    request = Request(
        f"https://api.github.com/repos/{repository}/contents/{MANIFEST_NAME}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Stock-Predict-Mailer"},
    )
    max_response = MAX_MANIFEST_BYTES * 3
    try:
        with build_opener(_NoRedirect()).open(request, timeout=8) as response:
            body = decode(response.read(max_response + 1), max_bytes=max_response)
        if (not isinstance(body, dict) or body.get("type") != "file" or body.get("encoding") != "base64"
                or type(body.get("size")) is not int or not 0 <= body["size"] <= MAX_MANIFEST_BYTES):
            raise PluginIncompatible("GitHub 仓库根目录需要一个不超过 8 KiB 的插件声明文件")
        raw = base64.b64decode(body.get("content", "").replace("\n", ""), validate=True)
        if len(raw) != body["size"]:
            raise PluginIncompatible("GitHub 返回的插件声明大小不一致")
        return raw
    except HTTPError as exc:
        try:
            if exc.code == 404:
                raise PluginNotFound(f"公开仓库默认分支的根目录中找不到 {MANIFEST_NAME}") from None
            if exc.code in (403, 429):
                raise ServiceError("GITHUB_UNAVAILABLE", "GitHub 拒绝了请求或已达到请求额度，请稍后重试") from None
            raise ServiceError("GITHUB_UNAVAILABLE", f"GitHub 获取失败（HTTP {exc.code}）") from None
        finally:
            exc.close()
    except (URLError, OSError, HTTPException):
        raise ServiceError("GITHUB_UNAVAILABLE", "无法连接 GitHub，请检查网络后重试") from None
    except (AttributeError, TypeError, ValueError, binascii.Error):
        raise PluginIncompatible("GitHub 返回了无效的插件声明") from None


def _parse(raw: bytes) -> DeclarativeExporter:
    body = decode(raw, max_bytes=MAX_MANIFEST_BYTES)
    if not isinstance(body, dict) or set(body) != {"id", "kind", "label", "api_version", "export"}:
        raise PluginIncompatible("插件声明需要且仅接受 id、kind、label、api_version 和 export")
    plugin_id, settings = body["id"], body["export"]
    if not isinstance(plugin_id, str) or len(plugin_id) > 64 or not PLUGIN_ID.fullmatch(plugin_id):
        raise PluginIncompatible("插件 id 须为不超过 64 字符的小写下划线标识符")
    if body["kind"] != "exporter" or not isinstance(settings, dict):
        raise PluginIncompatible("GitHub 声明式插件当前支持 exporter 类型")
    fmt = settings.get("format")
    if fmt == "csv":
        if (set(settings) - {"format", "delimiter", "bom"} or settings.get("delimiter", ",") not in (",", "\t", ";")
                or type(settings.get("bom", False)) is not bool):
            raise PluginIncompatible("CSV 导出仅支持逗号、制表符或分号分隔，以及可选的 UTF-8 BOM")
    elif fmt == "json":
        if (set(settings) - {"format", "indent"} or type(settings.get("indent", 0)) is not int
                or settings.get("indent", 0) not in range(5)):
            raise PluginIncompatible("JSON 数组导出的缩进须为 0 到 4")
    else:
        raise PluginIncompatible("声明式导出格式须为 csv 或 json")
    manifest = validate_manifest(PluginManifest(
        id=plugin_id, kind="exporter", label=body["label"], capabilities=(fmt,), api_version=body["api_version"],
    ))
    if re.search(r"[\x00-\x1f\ud800-\udfff]", manifest.label):
        raise PluginIncompatible("插件显示名包含无效字符")
    if any(adapter.manifest.id == plugin_id for kind in registry.KINDS for adapter in registry.select(kind)):
        raise PluginIncompatible(f"插件 id 已由内置插件使用：{plugin_id}")
    return DeclarativeExporter(manifest, settings)


def _database(root: Path) -> Path:
    return Path(root) / "github-plugins.sqlite3"


@contextmanager
def _open(path: Path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS plugins (
            id TEXT PRIMARY KEY, repository TEXT NOT NULL, manifest BLOB NOT NULL
        )""")
        yield db


def install(root: Path, url: str) -> dict:
    match = _REPOSITORY.fullmatch(url.strip()) if isinstance(url, str) and len(url) <= 256 else None
    if not match or match[2] in (".", "..") or len(match[1]) > 39:
        raise ServiceError("INVALID_INPUT", "请输入公开 GitHub 仓库地址，例如 https://github.com/owner/repo")
    repository = f"{match[1]}/{match[2]}".lower()
    raw = _download(repository)
    plugin = _parse(raw)
    with _open(_database(root)) as db:
        db.execute("INSERT OR IGNORE INTO plugins VALUES (?, ?, ?)", (plugin.manifest.id, repository, raw))
        saved = db.execute("SELECT repository, manifest FROM plugins WHERE id = ?", (plugin.manifest.id,)).fetchone()
        if saved != (repository, raw):
            raise PluginError(f"插件 id 已存在：{plugin.manifest.id}。更新前请先移除原插件")
    return _row(plugin, repository, raw)


def remove(root: Path, plugin_id: str) -> None:
    path = _database(root)
    if path.is_file():
        with _open(path) as db:
            if db.execute("DELETE FROM plugins WHERE id = ?", (plugin_id,)).rowcount:
                return
    raise PluginNotFound(f"未添加的 GitHub 插件：{plugin_id}")


def _row(plugin: DeclarativeExporter, repository: str, raw: bytes) -> dict:
    manifest = plugin.manifest
    return {"id": manifest.id, "kind": manifest.kind, "label": manifest.label,
            "capabilities": list(manifest.capabilities), "requires": [], "extra": "", "available": True,
            "problems": [], "github_url": f"https://github.com/{repository}", "manifest_sha256": digest(raw)}


def describe(root: Path) -> list[dict]:
    path = _database(root)
    if not path.is_file():
        return []
    with _open(path) as db:
        records = db.execute("SELECT repository, manifest FROM plugins ORDER BY id").fetchall()
    return [_row(_parse(raw), repository, raw) for repository, raw in records]


def export(root: Path, plugin_id: str, rows: list[dict], output: Path) -> dict:
    path = _database(root)
    if path.is_file():
        with _open(path) as db:
            record = db.execute("SELECT repository, manifest FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        if record:
            if output.resolve() == path.resolve():
                raise PluginError("导出路径不能覆盖 GitHub 插件库")
            repository, raw = record
            result = _parse(raw).export(rows, output)
            return {**result, "plugin_id": plugin_id, "github_url": f"https://github.com/{repository}",
                    "manifest_sha256": digest(raw)}
    raise PluginNotFound(f"未添加的 GitHub 插件：{plugin_id}")
