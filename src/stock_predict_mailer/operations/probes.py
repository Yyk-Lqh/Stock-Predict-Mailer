"""Bounded read-only storage and transient local availability probes."""
from __future__ import annotations

import errno
import os
import socket
import sqlite3
import time
from contextlib import contextmanager


class ProbeError(Exception):
    def __init__(self, code):
        self.code = code


def contained(root, path):
    try:
        safe = path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        raise ProbeError("PATH_UNREADABLE") from None
    if not safe:
        raise ProbeError("PATH_OUTSIDE_WORKSPACE")


@contextmanager
def database(root, relative, seconds=2):
    path = root / relative
    contained(root, path)
    con = None
    deadline = time.monotonic() + seconds
    try:
        # SQLite mode=ro can still create/update WAL coordination files. Do not use
        # immutable=1: it ignores live WAL commits and would give a false snapshot.
        with path.open("rb") as stream:
            header = stream.read(100)
        if header[:16] == b"SQLite format 3\x00" and len(header) < 100:
            raise ProbeError("DB_CORRUPT")
        if header[:16] == b"SQLite format 3\x00" and (header[18] == 2 or header[19] == 2):
            raise ProbeError("DB_WAL_CHECK_DEFERRED")
        if any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm")):
            raise ProbeError("DB_WAL_CHECK_DEFERRED")
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2)
        con.row_factory = sqlite3.Row
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA trusted_schema=OFF")
        con.execute("BEGIN")
        yield con
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", 0) or 0
        base = code & 255
        raise ProbeError("DB_BUSY" if base in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else
                         "DB_CHECK_LIMIT" if base == sqlite3.SQLITE_INTERRUPT else
                         "DB_CORRUPT" if base in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB) else "DB_UNREADABLE") from None
    except OSError:
        raise ProbeError("DB_UNREADABLE") from None
    finally:
        if con is not None:
            con.close()


def lock_state(root, relative):
    """A shared advisory probe conflicts with writers; it never creates a lock file."""
    path = root / relative
    try:
        contained(root, path)
        if not path.exists():
            return "absent"
        # POSIX flock locks the file description even when the file is empty.
        # Windows byte-range probing still needs an existing lock byte.
        if os.name == "nt" and path.stat().st_size == 0:
            return "unknown"
        with path.open("rb") as handle:
            acquired = False
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
                acquired = True
                return "available"
            except OSError as exc:
                return "busy" if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) else "unknown"
            finally:
                if acquired:
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)
    except (OSError, ProbeError):
        return "unknown"


def port_state(port):
    """Test a new loopback listener's bind only; do not connect, listen or issue HTTP."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))
        return "available"
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES) or getattr(exc, "winerror", None) in (10048, 10013):
            return "unavailable"
        return "unknown"
