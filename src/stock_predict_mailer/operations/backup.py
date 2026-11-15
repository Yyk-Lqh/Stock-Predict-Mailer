"""Authenticated workspace snapshots and non-overwriting, quarantined restore."""
from __future__ import annotations

import ctypes
import io
import json
import os
import re
import sqlite3
import stat
import tempfile
import zipfile
import zlib
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..agent_service.contracts import ServiceError, decode, instant, utcnow
from ..core import digest
from ..naming import env_key, version
from . import backup_inventory as inv
from .backup_quarantine import quarantine, validate_databases
from .lifecycle import selected_root

MAX_ENCRYPTED = 2 * inv.MAX_TOTAL + 8 * 1024 * 1024
MAX_MANIFEST = 12 * 1024 * 1024


def _key(name=None):
    name = name or env_key("BACKUP_KEY")
    if not isinstance(name, str) or not re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", name):
        inv.fail("INVALID_INPUT", "备份密钥环境变量引用无效")
    try:
        return Fernet(os.environ[name].encode())
    except (KeyError, ValueError, TypeError):
        inv.fail("BACKUP_KEY", "缺少或无效的独立备份密钥环境变量")


def _scan(cfg, config_path, crawler_workspace, port):
    return inv.inventory(cfg["workspace"], selected_root(cfg, "crawler_worker", crawler_workspace), config_path, port)


def _image(plan, root):
    inv.copy_sources(plan, root)
    inv.normalize(root, plan["files"])
    validate_databases(root)
    vaults = inv.validate_vaults(root)
    files = [{"path": item["path"], "kind": item["kind"], **inv.fingerprint(root / item["path"])}
             for item in plan["files"] if item["kind"] != "wal"]
    if sum(item["size"] for item in files) > inv.MAX_TOTAL:
        inv.fail("BACKUP_LIMIT", "规范化后的数据超过总量上限")
    return files, vaults


def plan(cfg, config_path, *, crawler_workspace=None, port=8767):
    source = _scan(cfg, config_path, crawler_workspace, port)
    blockers, vaults = inv.quiescence(source), {}
    if not blockers:
        try:
            with tempfile.TemporaryDirectory(prefix="stock-backup-plan-") as folder:
                _, vaults = _image(source, Path(folder))
                if _scan(cfg, config_path, crawler_workspace, port)["plan_id"] != source["plan_id"]:
                    inv.fail("BACKUP_SOURCE_CHANGED", "预演期间来源清单变化")
        except ServiceError as exc:
            blockers.append({"code": exc.code, "message": exc.message})
    return {**source, "ready": not blockers, "blockers": blockers, "vaults": vaults, "mode": "read_only_plan",
            "counts": {"files": len(source["files"]), "bytes": sum(item["size"] for item in source["files"])},
            "limits": {"files": inv.MAX_FILES, "single_file_bytes": inv.MAX_FILE, "total_bytes": inv.MAX_TOTAL},
            "exclusions": ["runtime/locks/logs/SHM/pending", ".git/.venv/.uv-cache/__pycache__/backups", "external referenced files", "external MASTER_KEY"],
            "consistency": "quiesced_sources_with_before_after_hashes", "sends_mail": False}


def _output(output, source):
    raw = Path(output).absolute()
    if os.path.lexists(raw):
        inv.fail("BACKUP_EXISTS", "备份输出已存在，不覆盖")
    output = raw.resolve()
    if not output.parent.is_dir() or any(output.is_relative_to(Path(root)) for root in source["origins"].values()):
        inv.fail("BACKUP_TARGET", "备份输出须位于已有的来源外目录")
    return output


def _publish_file(path, payload):
    fd, temporary = tempfile.mkstemp(prefix=".backup-", suffix=".pending", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            inv.fail("BACKUP_EXISTS", "发布时输出已存在，不覆盖")
        except OSError:
            inv.fail("BACKUP_PUBLISH", "文件系统不能安全发布不可覆盖的备份")
    finally:
        temporary.unlink(missing_ok=True)


def create(cfg, config_path, output, expected_plan, *, crawler_workspace=None, port=8767, key_env=None):
    cipher = _key(key_env)
    if not isinstance(expected_plan, str) or not re.fullmatch("[a-f0-9]{64}", expected_plan):
        inv.fail("INVALID_INPUT", "创建备份需要已审阅的 expected-plan")
    reviewed = plan(cfg, config_path, crawler_workspace=crawler_workspace, port=port)
    if reviewed["plan_id"] != expected_plan:
        inv.fail("BACKUP_PLAN_CHANGED", "来源与已审阅计划不同")
    if not reviewed["ready"]:
        inv.fail("BACKUP_BLOCKED", "预演存在运行者、密钥或数据阻断项")
    output = _output(output, reviewed)
    with inv.barriers(reviewed), tempfile.TemporaryDirectory(prefix="stock-backup-create-") as temporary:
        current = _scan(cfg, config_path, crawler_workspace, port)
        if current["plan_id"] != expected_plan:
            inv.fail("BACKUP_PLAN_CHANGED", "加锁后来源与计划不同")
        root = Path(temporary)
        files, vaults = _image(current, root)
        if _scan(cfg, config_path, crawler_workspace, port)["plan_id"] != expected_plan:
            inv.fail("BACKUP_SOURCE_CHANGED", "复制期间来源发生变化，未发布备份")
        manifest = {"schema_version": "1", "app_version": version(), "platform": os.name, "created_at": utcnow().isoformat(),
                    "plan_id": expected_plan, "origins": current["origins"], "files": files, "vaults": vaults}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
            for item in files:
                archive.write(root / item["path"], item["path"])
        encrypted = cipher.encrypt(buffer.getvalue())
        if len(encrypted) > MAX_ENCRYPTED:
            inv.fail("BACKUP_LIMIT", "加密包超过大小上限")
        _publish_file(output, encrypted)
    return {"archive": str(output), "archive_sha256": digest(encrypted), "plan_id": expected_plan, "files": len(files),
            "encrypted": True, "vaults": vaults, "sends_mail": False}


def _manifest(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "app_version", "platform", "created_at", "plan_id", "origins", "files", "vaults"}:
        inv.fail("BACKUP_FORMAT", "备份清单结构无效")
    if value["schema_version"] != "1" or value["app_version"] != version() or value["platform"] != os.name:
        inv.fail("BACKUP_VERSION", "备份格式、平台或应用版本不兼容")
    try:
        instant(value["created_at"])
    except ServiceError:
        inv.fail("BACKUP_FORMAT", "备份时间格式无效")
    if not isinstance(value["plan_id"], str) or not re.fullmatch("[a-f0-9]{64}", value["plan_id"]):
        inv.fail("BACKUP_FORMAT", "计划摘要无效")
    origins = value["origins"]
    if not isinstance(origins, dict) or set(origins) != {"app", "crawler"} or any(
            not isinstance(p, str) or len(p) > 4096 or not Path(p).is_absolute() or p.startswith(("\\\\", "//"))
            or any(ord(c) < 32 for c in p) or os.path.normpath(p) != p for p in origins.values()):
        inv.fail("BACKUP_FORMAT", "备份来源范围无效")
    if not isinstance(value["files"], list) or not 1 <= len(value["files"]) <= inv.MAX_FILES or not isinstance(value["vaults"], dict):
        inv.fail("BACKUP_FORMAT", "备份文件清单无效")
    names, total = set(), 0
    for item in value["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256", "kind"}:
            inv.fail("BACKUP_FORMAT", "备份文件条目无效")
        path = inv.safe_name(item["path"])
        if (any(part.casefold() in {d.casefold() for d in inv.EXCLUDED_DIRS} for part in path.parts[1:-1]) or inv.excluded(path.name.lower())
                or item["kind"] not in ("file", "database") or (path.suffix.lower() in inv.DB_SUFFIXES) != (item["kind"] == "database")):
            inv.fail("BACKUP_FORMAT", "备份包含运行状态或不一致的文件类型")
        if path.parts[0] == "reference" and item["path"] != "reference/original-agent.toml":
            inv.fail("BACKUP_FORMAT", "不支持的外部参考文件")
        if type(item["size"]) is not int or not 0 <= item["size"] <= inv.MAX_FILE or not isinstance(item["sha256"], str) or not re.fullmatch("[a-f0-9]{64}", item["sha256"]):
            inv.fail("BACKUP_FORMAT", "备份文件大小或摘要无效")
        name = item["path"].casefold()
        if name in names:
            inv.fail("BACKUP_PATH", "备份存在重复或大小写冲突路径")
        names.add(name)
        total += item["size"]
    if total > inv.MAX_TOTAL:
        inv.fail("BACKUP_LIMIT", "备份展开总量超过 128 MiB")
    if "reference/original-agent.toml" not in names or any(str(parent).casefold() in names for name in names for parent in inv.safe_name(name).parents):
        inv.fail("BACKUP_PATH", "备份路径冲突或缺少配置参考")
    return value


def _unseal(archive, key_env):
    with Path(archive).open("rb") as stream:
        encrypted = stream.read(MAX_ENCRYPTED + 1)
    if len(encrypted) > MAX_ENCRYPTED:
        inv.fail("BACKUP_LIMIT", "加密包超过大小上限")
    try:
        plain = _key(key_env).decrypt(encrypted)
    except InvalidToken:
        inv.fail("BACKUP_AUTH", "备份密钥不匹配或加密包已损坏")
    try:
        with zipfile.ZipFile(io.BytesIO(plain)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(infos) > inv.MAX_FILES + 1 or len(set(name.casefold() for name in names)) != len(names) or "manifest.json" not in names:
                inv.fail("BACKUP_FORMAT", "备份包文件列表无效")
            for item in infos:
                mode = stat.S_IFMT(item.external_attr >> 16)
                limit = MAX_MANIFEST if item.filename == "manifest.json" else inv.MAX_FILE
                if mode not in (0, stat.S_IFREG) or item.is_dir() or item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or item.file_size > limit:
                    inv.fail("BACKUP_FORMAT", "备份包包含特殊文件、异常压缩或超限条目")
            manifest = _manifest(decode(archive.read("manifest.json"), max_bytes=MAX_MANIFEST))
            if set(names) != {"manifest.json", *[item["path"] for item in manifest["files"]]}:
                inv.fail("BACKUP_FORMAT", "备份包与清单文件不一致")
            payloads = {}
            for item in manifest["files"]:
                raw = archive.read(item["path"])
                if len(raw) != item["size"] or digest(raw) != item["sha256"]:
                    inv.fail("BACKUP_INTEGRITY", "备份正文与清单摘要不一致")
                if item["kind"] == "database" and (len(raw) < 100 or raw[:16] != b"SQLite format 3\x00" or raw[18:20] != b"\x01\x01"):
                    inv.fail("BACKUP_DATABASE", "备份数据库不是已合并的独立快照")
                payloads[item["path"]] = raw
    except (zipfile.BadZipFile, ValueError, TypeError, KeyError, RecursionError, RuntimeError, zlib.error):
        inv.fail("BACKUP_FORMAT", "认证后的备份包格式无法验证")
    return manifest, payloads, digest(encrypted)


def _materialize(root, manifest, payloads):
    for name, raw in payloads.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
        if name == "app/control-development.key":
            path.chmod(0o600)
    for item in manifest["files"]:
        if item["kind"] == "database":
            con = None
            try:
                con = inv.connect(root / item["path"], True)
                if con.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                    inv.fail("BACKUP_DATABASE", "备份数据库完整性校验失败")
            except sqlite3.Error:
                inv.fail("BACKUP_DATABASE", "备份数据库无法验证")
            finally:
                if con is not None:
                    con.close()
    validate_databases(root)
    if inv.validate_vaults(root) != manifest["vaults"]:
        inv.fail("BACKUP_VAULT_KEY", "备份密钥配套声明与数据不符")


def verify(archive, *, key_env=None):
    manifest, payloads, archive_hash = _unseal(archive, key_env)
    with tempfile.TemporaryDirectory(prefix="stock-backup-verify-") as folder:
        _materialize(Path(folder), manifest, payloads)
    return {"valid": True, "archive_sha256": archive_hash, "plan_id": manifest["plan_id"], "files": len(payloads), "vaults": manifest["vaults"], "sends_mail": False}


def _publish_directory(source, target):
    if os.name == "nt":
        os.rename(source, target)  # Windows refuses an existing destination.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        inv.fail("BACKUP_PUBLISH", "平台不支持不可覆盖的目录发布")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        inv.fail("BACKUP_PUBLISH", "目标已出现或目录无法安全发布，未覆盖")


def restore(archive, target, *, key_env=None):
    raw_target = Path(target).absolute()
    if os.path.lexists(raw_target):
        inv.fail("BACKUP_EXISTS", "恢复目标已存在，不能覆盖或复用")
    target = raw_target.resolve()
    if not target.parent.is_dir():
        inv.fail("BACKUP_TARGET", "恢复目标的父目录必须存在")
    manifest, payloads, archive_hash = _unseal(archive, key_env)
    for origin in manifest["origins"].values():
        # Origins are authenticated metadata, never filesystem traversal inputs.
        # Compare lexically; resolving an archive-supplied UNC path could access a remote host.
        origin = Path(os.path.normcase(origin))
        compared_target = Path(os.path.normcase(str(target)))
        if compared_target == origin or compared_target.is_relative_to(origin) or origin.is_relative_to(compared_target):
            inv.fail("BACKUP_TARGET", "恢复目标必须与原来源分离")
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=target.parent) as temporary:
        root = Path(temporary) / "bundle"
        root.mkdir(mode=0o700)
        _materialize(root, manifest, payloads)
        counts = quarantine(root)
        (root / "app").mkdir(exist_ok=True)
        (root / "crawler").mkdir(exist_ok=True)
        config = '# Safe isolated restore configuration; original TOML is reference only.\nworkspace="app"\n[prediction]\nadapter="mock"\n[context]\nadapter="none"\n[mail]\ntransport="file"\nsender="preview@example.invalid"\nrecipient="preview@example.invalid"\n'
        (root / "restored-agent.toml").write_text(config, encoding="utf-8")
        receipt = {"schema_version": "1", "app_version": version(), "platform": os.name, "vaults": manifest["vaults"],
                   "archive_sha256": archive_hash, "plan_id": manifest["plan_id"], "restored_at": utcnow().isoformat(),
                   "quarantined": counts, "services_started": 0, "files": [{"path": item["path"], "source_sha256": item["sha256"],
                       "restored_sha256": inv.fingerprint(root / item["path"])["sha256"]} for item in manifest["files"]]}
        (root / "restore-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            _publish_directory(root, target)
        except OSError:
            inv.fail("BACKUP_PUBLISH", "恢复目标已出现或无法安全发布，未覆盖")
    return {"target": str(target), "archive_sha256": archive_hash, "vaults": manifest["vaults"], "quarantined": counts, "services_started": 0, "sends_mail": False,
            "config": str(target / "restored-agent.toml")}
