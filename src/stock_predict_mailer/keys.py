"""Publisher key revocation list.

A signature proves *which* key signed a package; revocation answers whether that
key is still trusted. Installations consult this list, so a compromised or
retired publisher key cannot keep installing new packages even though its old
signatures still verify.
"""
from __future__ import annotations

from .core import Config, connect, now


def schema(con) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS key_revocations (
        fingerprint TEXT PRIMARY KEY, owner TEXT NOT NULL, reason TEXT NOT NULL, revoked_at TEXT NOT NULL);
    """)


def _fingerprint(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("key fingerprint must be a sha256 hex digest")
    return value


def revoke_key(cfg: Config, fingerprint: str, reason: str = "") -> dict:
    fingerprint = _fingerprint(fingerprint)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
        raise ValueError("key revocation requires a recorded reason")
    stamp = now()
    with connect(cfg) as con:
        schema(con)
        con.execute("INSERT OR REPLACE INTO key_revocations VALUES (?, ?, ?, ?)",
                    (fingerprint, cfg.principal, reason, stamp))
    return {"fingerprint": fingerprint, "revoked": True, "reason": reason, "revoked_at": stamp}


def is_revoked(cfg: Config, fingerprint: str) -> bool:
    with connect(cfg) as con:
        schema(con)
        row = con.execute("SELECT 1 FROM key_revocations WHERE fingerprint=?", (fingerprint,)).fetchone()
    return row is not None


def require_active(cfg: Config, fingerprint: str) -> None:
    if is_revoked(cfg, fingerprint):
        raise ValueError("publisher key has been revoked; install a package signed by a trusted active key")


def revoked_keys(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        schema(con)
        return [dict(row) for row in con.execute(
            "SELECT fingerprint, reason, revoked_at FROM key_revocations ORDER BY revoked_at DESC")]
