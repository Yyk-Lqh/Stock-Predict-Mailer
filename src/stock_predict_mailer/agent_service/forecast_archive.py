"""Immutable local forecast records and evidence-based maturity evaluations."""
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ..core import Config
from ..delivery import process_lock
from .contracts import ServiceError, decode, instant, keys, prediction, utcnow
from .forecast_contracts import definition, forecast_id, observation, registration, score
from .input_evidence import canonical, fingerprint

KEY = re.compile("[a-f0-9]{64}")
MAX_FILE = 1024 * 1024
MAX_RECORDS = 1000
MAX_EVALUATIONS = 32
MAX_READ = 16 * 1024 * 1024


def fail(code, message):
    raise ServiceError(code, message)


def seal(value):
    return {**value, "integrity_id": fingerprint(value)}


class ForecastArchive:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.read_bytes = 0

    def _directory(self, *parts, create=False):
        path = self.root
        if path.exists() and not path.is_dir():
            fail("FORECAST_PATH", "工作区不是目录")
        for part in ("forecasts", *parts):
            path /= part
            if create:
                path.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(path):
                info = path.lstat()
                if path.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400) or not path.is_dir():
                    fail("FORECAST_PATH", "不跟随归档目录链接或重解析点")
        return path

    def _path(self, key, evaluation=None, create=False):
        if not isinstance(key, str) or not KEY.fullmatch(key) or (evaluation is not None and (not isinstance(evaluation, str) or not KEY.fullmatch(evaluation))):
            fail("INVALID_INPUT", "预测/评估标识必须为 64 位摘要")
        return (self._directory("records", create=create) / (key + ".json") if evaluation is None else
                self._directory("evaluations", key, create=create) / (evaluation + ".json"))

    def _read(self, path):
        if not os.path.lexists(path):
            fail("FORECAST_NOT_FOUND", "预测或评估记录不存在")
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400) or not stat.S_ISREG(info.st_mode):
            fail("FORECAST_PATH", "不读取链接、重解析点或特殊文件")
        if info.st_size > MAX_FILE:
            fail("FORECAST_LIMIT", "归档文件超过 1 MiB")
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE + 1)
        self.read_bytes += len(raw)
        if len(raw) > MAX_FILE or self.read_bytes > MAX_READ:
            fail("FORECAST_LIMIT", "归档读取超过大小预算")
        try:
            value = decode(raw)
            if not isinstance(value, dict) or value.get("integrity_id") != fingerprint({k: v for k, v in value.items() if k != "integrity_id"}):
                raise ValueError()
            return value
        except (ServiceError, ValueError, TypeError, KeyError):
            fail("FORECAST_CORRUPT", "归档记录损坏或摘要不符")

    def _record(self, key):
        value = self._read(self._path(key))
        try:
            value = registration(value)
            if key != value["forecast_id"]:
                raise ValueError()
            return value
        except (ServiceError, ValueError, TypeError, KeyError):
            fail("FORECAST_CORRUPT", "归档预测或事前定义不符合契约")

    def _entries(self, folder, limit):
        if not folder.exists():
            return []
        result = []
        for path in folder.glob("*.json"):
            if not KEY.fullmatch(path.stem):
                fail("FORECAST_PATH", "归档中存在未知 JSON 文件名")
            result.append(path)
            if len(result) > limit:
                fail("FORECAST_LIMIT", "归档条数超过读取上限")
        return sorted(result)

    @contextmanager
    def _writer(self):
        lock = self.root / "pipeline.lock"
        if os.path.lexists(lock):
            info = lock.lstat()
            if lock.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400) or not stat.S_ISREG(info.st_mode):
                fail("FORECAST_PATH", "工作区写锁不是安全的普通文件")
        try:
            with process_lock(Config(self.root)):
                yield
        except RuntimeError:
            fail("FORECAST_BUSY", "工作区存在另一个写入操作")

    def _publish(self, path, value):
        payload = canonical(value)
        if len(payload) > MAX_FILE:
            fail("FORECAST_LIMIT", "待保存记录超过 1 MiB")
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(name, path)
            except OSError:
                fail("FORECAST_PUBLISH", "无法安全发布不可覆盖的归档")
        finally:
            Path(name).unlink(missing_ok=True)

    def register(self, raw_prediction, raw_definition, *, now=None):
        self.read_bytes = 0
        now = instant((now or utcnow()).isoformat())
        # Clone and bound input before retaining nested dictionaries.
        p = prediction(decode(canonical(raw_prediction)), now=now)
        d = definition(decode(canonical(raw_definition)), p, now)
        key = forecast_id(p)
        content_id = fingerprint({"prediction": p, "definition": d})
        with self._writer():
            path = self._path(key)
            if os.path.lexists(path):
                existing = self._record(key)
                if existing["content_id"] != content_id:
                    fail("FORECAST_CONFLICT", "同一预测身份已有不同预测或评价定义，请使用新的预测 ID")
                return {"created": False, "record": existing}
            if len(self._entries(self._directory("records"), MAX_RECORDS)) >= MAX_RECORDS:
                fail("FORECAST_LIMIT", "预测归档已满")
            record = seal({"schema_version": "1", "forecast_id": key, "registered_at": now.isoformat(),
                           "prediction": p, "definition": d, "content_id": content_id})
            self._publish(self._path(key, create=True), record)
            return {"created": True, "record": record}

    def _as_of(self, as_of, now):
        now = instant((now or utcnow()).isoformat())
        at = instant(as_of) if as_of is not None else now
        if at > now:
            fail("INVALID_INPUT", "评估/查询截止时间不能晚于现在")
        return at, now

    def _evaluations(self, record, at):
        folder = self._directory("evaluations", record["forecast_id"])
        result = []
        for path in self._entries(folder, MAX_EVALUATIONS):
            value = self._evaluation(path, record)
            if instant(value["evaluated_at"]) <= at:
                result.append(value)
        return sorted(result, key=lambda r: (r["evaluated_at"], r["evaluation_id"]))

    def _evaluation(self, path, record):
        value = self._read(path)
        try:
            keys(value, ("schema_version", "evaluation_id", "forecast_id", "forecast_content_id", "observation", "metrics", "as_of", "evaluated_at", "integrity_id"))
            actual = observation(value["observation"], record)
            key = fingerprint({"forecast_content_id": record["content_id"], "observation": actual})
            if (value["schema_version"] != "1" or value["forecast_id"] != record["forecast_id"] or value["forecast_content_id"] != record["content_id"]
                    or value["evaluation_id"] != key or path.stem != key or value["metrics"] != score(record, actual)
                    or not instant(record["registered_at"]) <= instant(value["as_of"]) <= instant(value["evaluated_at"])
                    or instant(actual["available_at"]) > instant(value["as_of"])):
                raise ValueError()
            return value
        except (ServiceError, ValueError, KeyError, TypeError):
            fail("FORECAST_CORRUPT", "评估记录与事前预测或观测不匹配")

    def _view(self, record, at):
        evaluations = self._evaluations(record, at)
        return {"record": record, "as_of": at.isoformat(), "evaluations": evaluations,
                "state": "evaluated" if evaluations else "due" if at >= instant(record["definition"]["target_at"]) else "pending"}

    def show(self, key, *, as_of=None, now=None):
        self.read_bytes = 0
        at, _ = self._as_of(as_of, now)
        record = self._record(key)
        if instant(record["registered_at"]) > at:
            fail("FORECAST_NOT_YET_REGISTERED", "截止时点该预测尚未注册")
        return self._view(record, at)

    def listing(self, *, as_of=None, now=None, limit=50, offset=0):
        self.read_bytes = 0
        if type(limit) is not int or not 1 <= limit <= 100:
            fail("INVALID_INPUT", "列表数量必须为 1 至 100")
        if type(offset) is not int or not 0 <= offset <= MAX_RECORDS:
            fail("INVALID_INPUT", "列表偏移无效")
        at, _ = self._as_of(as_of, now)
        records = [self._record(path.stem) for path in self._entries(self._directory("records"), MAX_RECORDS)]
        records = sorted((r for r in records if instant(r["registered_at"]) <= at), key=lambda r: (r["registered_at"], r["forecast_id"]), reverse=True)
        values = [self._view(record, at) for record in records[offset:offset + limit]]
        return {"as_of": at.isoformat(), "total": len(records), "returned": len(values), "records": values, "offset": offset,
                "next_offset": offset + len(values) if offset + len(values) < len(records) else None}

    def evaluate(self, key, raw_observation=None, *, as_of=None, now=None, dry_run=False):
        self.read_bytes = 0
        if type(dry_run) is not bool:
            fail("INVALID_INPUT", "dry_run 必须为布尔值")
        at, now = self._as_of(as_of, now)
        record = self._record(key)
        if instant(record["registered_at"]) > at:
            fail("FORECAST_NOT_YET_REGISTERED", "截止时点该预测尚未注册")
        result = {"forecast_id": key, "as_of": at.isoformat(), "persisted": False, "synthetic": record["prediction"]["synthetic"],
                  "limitations": ["来源及其时间为提供方声明，未独立认证；这些指标不代表交易收益或置信度校准。"]}
        if at < instant(record["definition"]["target_at"]):
            return {**result, "state": "not_due"}
        if raw_observation is None:
            return {**result, "state": "awaiting_observation"}
        actual = observation(decode(canonical(raw_observation)), record)
        if instant(actual["available_at"]) > at:
            return {**result, "state": "awaiting_observation"}
        evaluation_id = fingerprint({"forecast_content_id": record["content_id"], "observation": actual})
        value = seal({"schema_version": "1", "evaluation_id": evaluation_id, "forecast_id": key,
                      "forecast_content_id": record["content_id"], "as_of": at.isoformat(), "evaluated_at": now.isoformat(),
                      "observation": actual, "metrics": score(record, actual)})
        if dry_run:
            return {**result, "state": "evaluated", "evaluation": value}
        with self._writer():
            if self._record(key)["integrity_id"] != record["integrity_id"]:
                fail("FORECAST_CONFLICT", "计算期间事前记录发生变化")
            path = self._path(key, evaluation_id)
            if os.path.lexists(path):
                value = self._evaluation(path, record)
            else:
                if len(self._entries(self._directory("evaluations", key), MAX_EVALUATIONS)) >= MAX_EVALUATIONS:
                    fail("FORECAST_LIMIT", "此预测的评估修订数量已满")
                self._publish(self._path(key, evaluation_id, create=True), value)
        return {**result, "state": "evaluated", "persisted": True, "evaluation": value}
