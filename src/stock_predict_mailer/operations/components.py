"""Instance-fenced leases, heartbeats and bounded structured lifecycle events."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import uuid
from logging.handlers import RotatingFileHandler

from ..agent_service.contracts import ServiceError, decode, instant, utcnow
from ..core import Config, atomic_write
from ..delivery import process_lock
from .probes import ProbeError, contained, lock_state
from .processes import birth, host_id

COMPONENTS = ("console", "knowledge_worker", "crawler_worker")
PHASES = {"starting", "running", "idle", "busy", "stopping", "stopped", "failed"}
EVENTS = {"starting", "running", "idle", "busy", "stopping", "stopped", "failed", "heartbeat_failed"}
HEARTBEAT_TTL = 5
MAX_RECORD = 8192
LOG_BYTES = 256 * 1024
LOG_BACKUPS = 3


def directory(root, component):
    if component not in COMPONENTS:
        raise ServiceError("INVALID_INPUT", "不支持该运行组件")
    result = root / ".runtime" / component
    try:
        contained(root, result)
        for name in ("state.json", "stop.json", "pipeline.lock", "launch/pipeline.lock", "events.jsonl", "events.jsonl.1", "events.jsonl.2", "events.jsonl.3"):
            contained(root, result / name)
    except ProbeError:
        raise ServiceError("RUNTIME_PATH", "组件运行目录越界或不可访问") from None
    return result


def configuration(value):
    if not isinstance(value, dict) or set(value) - {"port", "vault_mode", "poll_seconds", "once"}:
        raise ValueError()
    for name, item in value.items():
        if name == "port" and (type(item) is not int or not 0 <= item <= 65535):
            raise ValueError()
        if name == "vault_mode" and item not in ("development", "production"):
            raise ValueError()
        if name == "once" and type(item) is not bool:
            raise ValueError()
        if name == "poll_seconds" and (type(item) not in (int, float) or not math.isfinite(item) or not .1 <= item <= 60):
            raise ValueError()
    return dict(value)


def _read(path):
    with path.open("rb") as stream:
        return decode(stream.read(MAX_RECORD + 1), max_bytes=MAX_RECORD)


def _root(root):
    return os.path.normcase(str(root.resolve()))


def _valid_record(record, root, component):
    fields = {"schema_version", "component", "workspace", "instance", "pid", "birth", "host", "started_at", "updated_at", "phase", "configuration"}
    if not isinstance(record, dict) or set(record) != fields or record["schema_version"] != "1":
        raise ValueError()
    if record["component"] != component or record["workspace"] != _root(root):
        raise ValueError()
    if not isinstance(record["instance"], str) or not re.fullmatch("[a-f0-9]{32}", record["instance"]):
        raise ValueError()
    if type(record["pid"]) is not int or not 0 < record["pid"] < 2**32 or record["phase"] not in PHASES:
        raise ValueError()
    if not isinstance(record["host"], str) or not re.fullmatch("[a-f0-9]{64}", record["host"]):
        raise ValueError()
    if record["birth"] is not None and (not isinstance(record["birth"], str) or len(record["birth"]) > 256):
        raise ValueError()
    if instant(record["started_at"]) > instant(record["updated_at"]):
        raise ValueError()
    configuration(record["configuration"])
    return record


def status(root, component):
    root = root.resolve()
    folder = directory(root, component)
    base = {"component": component, "workspace": str(root), "ownership": "unknown"}
    locked = lock_state(root, str(folder.relative_to(root) / "pipeline.lock"))
    try:
        record = _valid_record(_read(folder / "state.json"), root, component)
    except FileNotFoundError:
        return dict(base, state="starting" if locked == "busy" else "not_registered", lock=locked)
    except (OSError, ValueError, TypeError, KeyError, ServiceError, RecursionError):
        return dict(base, state="invalid_record", lock=locked)
    result = dict(base, **{k: record[k] for k in ("instance", "pid", "phase", "started_at", "updated_at", "configuration")}, lock=locked)
    if record["host"] != host_id():
        return dict(result, state="different_host")
    if locked in ("absent", "available") and record["phase"] in ("stopped", "failed"):
        return dict(result, state=record["phase"], ownership="not_active")
    alive, current = birth(record["pid"])
    if alive == "dead":
        return dict(result, state="dead", ownership="not_active")
    if alive == "alive" and record["birth"] is not None and current != record["birth"]:
        return dict(result, state="pid_reused")
    age = (utcnow() - instant(record["updated_at"])).total_seconds()
    if age < -5:
        return dict(result, state="clock_skew")
    if alive != "alive" or current is None or record["birth"] is None or locked != "busy":
        return dict(result, state="unknown")
    if record["phase"] in ("stopped", "failed"):
        return dict(result, state="transition")
    return dict(result, state="verified" if age <= HEARTBEAT_TTL else "stale", ownership="verified", heartbeat_age_seconds=max(0, round(age, 3)))


def request_stop(root, component, instance):
    view = status(root, component)
    if view.get("instance") != instance:
        raise ServiceError("RUNTIME_INSTANCE_CHANGED", "组件实例已变化，请重新查询状态")
    if view["ownership"] != "verified":
        raise ServiceError("RUNTIME_UNVERIFIED", "无法确认运行实例归属，不写入停止请求")
    folder = directory(root, component)
    atomic_write(folder / "stop.json", json.dumps({"schema_version": "1", "instance": instance, "action": "stop"}).encode())
    return {"component": component, "instance": instance, "state": "stop_requested", "forced": False}


def logs(root, component, limit=50):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ServiceError("INVALID_INPUT", "日志 limit 须为 1 至 200")
    folder = directory(root, component)
    result = []
    for suffix in (".3", ".2", ".1", ""):
        path = folder / ("events.jsonl" + suffix)
        try:
            if path.stat().st_size > LOG_BYTES + MAX_RECORD:
                raise ServiceError("RUNTIME_LOG_INVALID", "生命周期日志超过预期上限")
            with path.open("rb") as stream:
                for raw in stream:
                    item = decode(raw, max_bytes=MAX_RECORD)
                    if (not isinstance(item, dict) or set(item) != {"at", "component", "instance", "event"}
                            or item["component"] != component or item["event"] not in EVENTS
                            or not isinstance(item["instance"], str) or not re.fullmatch("[a-f0-9]{32}", item["instance"])):
                        raise ValueError()
                    instant(item["at"])
                    result.append(item)
                    result = result[-limit:]
        except FileNotFoundError:
            continue
        except (OSError, ValueError, TypeError, ServiceError, RecursionError):
            raise ServiceError("RUNTIME_LOG_INVALID", "无法读取经过校验的生命周期日志") from None
    return result


class Component:
    def __init__(self, root, name, config=None, *, instance=None, interval=1):
        self.root, self.name = root.resolve(), name
        self.folder = directory(self.root, name)
        try:
            self.config = configuration({} if config is None else config)
        except (ValueError, TypeError):
            raise ServiceError("INVALID_INPUT", "组件公开运行参数无效") from None
        self.instance = instance or uuid.uuid4().hex
        if not isinstance(self.instance, str) or not re.fullmatch("[a-f0-9]{32}", self.instance):
            raise ServiceError("INVALID_INPUT", "运行实例 ID 无效")
        if type(interval) not in (int, float) or not math.isfinite(interval) or not .05 <= interval <= 10:
            raise ServiceError("INVALID_INPUT", "心跳间隔无效")
        self.interval = interval
        self.stopping, self.closed = threading.Event(), threading.Event()
        self.mutex = threading.RLock()
        self.handler, self.thread = None, None
        self.heartbeat_failed = False

    def __enter__(self):
        self.lock = process_lock(Config(self.folder))
        try:
            self.lock.__enter__()
        except RuntimeError:
            raise ServiceError("RUNTIME_BUSY", "该工作区的组件已有运行者，不接管或启动第二个实例") from None
        try:
            for suffix in ("", ".1", ".2", ".3"):
                path = self.folder / ("events.jsonl" + suffix)
                if path.exists() and path.stat().st_size > LOG_BYTES + MAX_RECORD:
                    raise ServiceError("RUNTIME_LOG_INVALID", "已有生命周期日志超过上限，不自动搬移或覆盖")
            self.handler = RotatingFileHandler(self.folder / "events.jsonl", maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
            self.handler.setFormatter(logging.Formatter("%(message)s"))
            stamp = utcnow().isoformat()
            self.record = {"schema_version": "1", "component": self.name, "workspace": _root(self.root), "instance": self.instance,
                "pid": os.getpid(), "birth": birth(os.getpid())[1], "host": host_id(), "started_at": stamp, "updated_at": stamp,
                "phase": "starting", "configuration": self.config}
            self._save()
            self._event("starting")
            self.thread = threading.Thread(target=self._heartbeat, daemon=True, name="runtime-heartbeat-" + self.name)
            self.thread.start()
            return self
        except BaseException:
            if self.handler:
                self.handler.close()
            self.lock.__exit__(None, None, None)
            raise

    def _event(self, event):
        body = json.dumps({"at": utcnow().isoformat(), "component": self.name, "instance": self.instance, "event": event})
        self.handler.handle(logging.LogRecord("runtime", logging.INFO, "", 0, body, (), None))

    def _save(self):
        self.record["updated_at"] = utcnow().isoformat()
        atomic_write(self.folder / "state.json", json.dumps(self.record, ensure_ascii=False).encode("utf-8"))

    def phase(self, value, **config):
        if value not in PHASES - {"stopped", "failed"}:
            raise ValueError("invalid component phase")
        with self.mutex:
            if self.stopping.is_set():
                value = "stopping"
            self.record["configuration"] = configuration({**self.record["configuration"], **config})
            changed = self.record["phase"] != value
            self.record["phase"] = value
            self._save()
            if changed:
                self._event(value)

    def _heartbeat(self):
        while not self.closed.wait(self.interval):
            try:
                with self.mutex:
                    self._accept_stop()
                    self._save()
            except Exception:
                # Do not keep processing queues when runtime ownership cannot be refreshed.
                self.heartbeat_failed = True
                self.stopping.set()
                try:
                    self._event("heartbeat_failed")
                except Exception:
                    pass
                return

    def _accept_stop(self):
        try:
            request = _read(self.folder / "stop.json")
            stop = (isinstance(request, dict) and request == {"schema_version": "1", "instance": self.instance, "action": "stop"})
        except (OSError, ServiceError, ValueError):
            stop = False
        if stop and not self.stopping.is_set():
            self.stopping.set()
            self.record["phase"] = "stopping"
            self._event("stopping")

    def should_stop(self):
        # Check at each work boundary too; do not consume another fast job while
        # waiting for the independent heartbeat thread's next polling interval.
        if not self.stopping.is_set():
            with self.mutex:
                self._accept_stop()
                if self.stopping.is_set():
                    self._save()
        return self.stopping.is_set()

    def wait(self, seconds):
        return self.stopping.wait(seconds)

    def __exit__(self, exc_type, exc, tb):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=2)
        try:
            with self.mutex:
                phase = "failed" if self.heartbeat_failed or (exc_type and not issubclass(exc_type, KeyboardInterrupt)) else "stopped"
                self.record["phase"] = phase
                self._save()
                self._event(phase)
        finally:
            if self.handler:
                self.handler.close()
            self.lock.__exit__(exc_type, exc, tb)
