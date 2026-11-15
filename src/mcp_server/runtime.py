"""Cross-process writer exclusion and cooperative collection controls."""
import hashlib
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from .quality import DataQualityError

_control = ContextVar("crawler_job_control", default=None)
_paths = ContextVar("crawler_job_paths", default=None)
_held = {}


class JobStopped(KeyboardInterrupt):
    """Bypass broad provider error handlers while preserving cleanup."""


def _key(directory):
    return os.getpid(), threading.get_ident(), os.path.normcase(str(Path(directory).resolve()))


def lock_held(directory):
    return _key(directory) in _held


@contextmanager
def workspace_lock(directory):
    key = _key(directory)
    if key in _held:
        yield
        return
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / ".crawler.lock").open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise DataQualityError("WORKSPACE_BUSY", "该工作区已有采集写入者") from None
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise DataQualityError("WORKSPACE_BUSY", "该工作区已有采集写入者") from None
        acquired = True
        _held[key] = stream
        yield
    finally:
        if acquired:
            _held.pop(key, None)
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def serialize(output_path):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with workspace_lock(Path(output_path()).parent):
                return function(*args, **kwargs)
        return wrapped
    return decorate


@contextmanager
def using_control(control):
    token = _control.set(control)
    try:
        yield
    finally:
        _control.reset(token)


def current_control():
    return _control.get()


@contextmanager
def using_paths(values):
    token = _paths.set({name: str(value) for name, value in values.items()})
    try:
        yield
    finally:
        _paths.reset(token)


def path_for(name, default):
    return (_paths.get() or {}).get(name, default)


def file_digest(path):
    if not Path(path).exists():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_cancelled():
    control = current_control()
    if control is not None:
        control.check()


def progress(**values):
    control = current_control()
    if control is not None:
        control.progress(values)


def pause(seconds):
    if current_control() is None:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        check_cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.5))
