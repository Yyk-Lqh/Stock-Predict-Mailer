"""Compatibility facade over the private knowledge store.

Report and CLI code keeps the four legacy function signatures, so moving to the
encrypted store needs no rewrite at the call sites. The facade translates only
three things: ``Config`` into a ``(Knowledge, owner)`` pair, the asynchronous
import queue into a synchronous call, and the store's evidence shape back into
the legacy dictionary.

Two limits are deliberate and documented rather than hidden: dates replace
timestamps (see ``_as_of``), and revocation now means ``retire`` - the encrypted
original survives, which deletion cannot offer.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .agent_service.contracts import ServiceError
from .core import Config, digest, timestamp
from .naming import env

OWNER_MAP = "CREATE TABLE IF NOT EXISTS kb_owner_map (principal TEXT PRIMARY KEY, owner TEXT NOT NULL)"


@contextmanager
def preview_workspace(workspace):
    """Clone metadata/vault key for dry-run constructors; never open source SQLite."""
    from .operations import backup_inventory as inv
    from .operations.schema_planning import snapshot

    root = Path(workspace).resolve()
    if not env("MASTER_KEY") and (root / "control.sqlite3").exists():
        raise ValueError("workspace was created with a master key; set STOCK_PREDICT_MAILER_MASTER_KEY to reach its knowledge base")
    control = "control.sqlite3" if env("MASTER_KEY") else "control-development.sqlite3"
    with tempfile.TemporaryDirectory(prefix="knowledge-preview-") as folder:
        target = Path(folder)
        for relative in (control, "private-knowledge/knowledge.sqlite3"):
            if not (root / relative).exists():
                continue
            with snapshot(root, relative) as (source, _):
                output = target / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                con = sqlite3.connect(output)
                try:
                    source.backup(con)
                finally:
                    con.close()
        key = root / "control-development.key"
        if control == "control-development.sqlite3" and key.exists():
            before = inv.fingerprint(key)
            shutil.copyfile(key, target / key.name)
            if inv.fingerprint(key) != before or inv.fingerprint(target / key.name) != before:
                raise ServiceError("SCHEMA_SOURCE_CHANGED", "预演期间开发密钥变化")
        yield target


def _knowledge(cfg: Config):
    # Imported lazily: the control layer belongs to the console, and importing it
    # at module level would make report generation depend on the web application.
    from .control.memory import Memory
    from .control.store import Store
    from .private_knowledge.service import Knowledge

    if not env("MASTER_KEY") and (cfg.workspace / "control.sqlite3").exists():
        # A fresh development vault would not fail: it would silently present an
        # empty knowledge base and a key that cannot decrypt the existing files.
        raise ValueError("workspace was created with a master key; set STOCK_PREDICT_MAILER_MASTER_KEY to reach its knowledge base")
    store = Store(cfg.workspace)  # Knowledge appends "private-knowledge" itself
    memory = Memory(store)
    with store.db() as con:
        con.executescript(OWNER_MAP)
    return store, memory, Knowledge(store)


def _owner(store, memory, principal, *, primary=False):
    key = env("KB_KEY")
    if primary and key:
        return memory.owner(key)  # Same view as the console, when its key is supplied
    with store.db() as con:
        row = con.execute("SELECT owner FROM kb_owner_map WHERE principal=?", (principal,)).fetchone()
    if row:
        return row[0]
    created = memory.create_owner()
    with store.db() as con:
        con.execute("INSERT OR IGNORE INTO kb_owner_map VALUES (?,?)", (principal, created["owner"]))
        return con.execute("SELECT owner FROM kb_owner_map WHERE principal=?", (principal,)).fetchone()[0]


def _context(cfg: Config):
    store, memory, kb = _knowledge(cfg)
    return kb, _owner(store, memory, cfg.principal, primary=True)


def open_store(workspace, principal="owner"):
    """Public ``(Knowledge, owner)`` pair for tools that write in bulk.

    The import tool is not a legacy caller, so it uses this instead of the four
    compatibility functions; it still resolves the owner the same way, which is
    what keeps a console session and a command line import in one space when
    ``STOCK_PREDICT_MAILER_KB_KEY`` is set.
    """
    return _context(Config(Path(workspace), principal=principal))


def _as_of(cutoff: str) -> str:
    return timestamp(cutoff).date().isoformat()


def _available(meta, as_of: str) -> bool:
    day = meta.get("available_date")
    if not day:
        return False  # Unknown availability is treated as unavailable, never as usable
    # Must match the engine, which skips only when available_date > as_of. Using a
    # strict comparison here would accept what search returned and then reject it.
    return day <= as_of


def _drain(kb, owner, did, *, cap=200):
    # upload() only queues the job, but every legacy caller reads immediately after
    # writing, so the facade has to finish the pipeline itself.
    for _ in range(cap):
        with kb.db() as con:
            row = con.execute("SELECT status,error FROM documents WHERE id=? AND owner=?", (did, owner)).fetchone()
        if row is None:
            raise ValueError("document disappeared during processing")
        if row["status"] != "pending" and row["status"] != "processing":
            if row["status"] != "ready":
                raise ValueError(f"knowledge processing {row['status']}: {row['error'] or ''}")
            return
        if kb.process_one() is None:
            raise ValueError("knowledge queue is empty but the document is still pending")
    raise ValueError("knowledge pipeline did not finish in time; run the knowledge worker first")


def ingest_document(cfg: Config, path: Path, published_at: str, available_at: str, allow: list[str]) -> dict:
    if timestamp(available_at) < timestamp(published_at):
        raise ValueError("available_at cannot precede publication")
    if not allow or any(not str(principal).strip() for principal in allow):
        raise ValueError("explicit nonempty ACL required")
    path = Path(path)
    raw = path.read_bytes()
    if not raw.strip():
        raise ValueError("empty document")
    store, memory, kb = _knowledge(cfg)
    # The slot identity must survive version changes, so it keeps the old
    # path-derived key instead of upload()'s filename default.
    logical = digest(str(path.resolve()).encode("utf-8"))
    meta = {"source": "legacy-cli",
            "document_date": timestamp(published_at).date().isoformat(),
            "available_date": timestamp(available_at).date().isoformat()}
    # The old store attached several principals to one document; the new one grants
    # one owner per copy, so a multi-principal ACL becomes several encrypted copies.
    ids = {}
    for principal in sorted(set(allow)):
        owner = _owner(store, memory, principal, primary=principal == cfg.principal)
        item = kb.upload(owner, path.name, raw, meta, logical)
        _drain(kb, owner, item["id"])
        ids[principal] = item["id"]
    # Return the caller's own copy, so a later revoke addresses the same owner.
    return {"document_id": ids.get(cfg.principal) or next(iter(ids.values())), "status": "created"}


def retrieve(cfg: Config, query: str, cutoff: str, limit: int = 5) -> list[dict]:
    if not query.strip() or not 1 <= limit <= 20:
        raise ValueError("nonempty query and limit 1..20 required")
    kb, owner = _context(cfg)
    found = kb.search(owner, query, as_of=_as_of(cutoff), limit=limit)
    return [{"chunk_id": item["chunk_id"], "document_id": item["document_id"],
             "ordinal": int(item["citation_id"].split(":")[1]), "content": item["text"],
             "sha256": digest(item["text"].encode("utf-8")), "title": item["filename"],
             "published_at": item["metadata"].get("document_date") or "",
             "available_at": item["metadata"].get("available_date") or "",
             "score": item["score"], "citation_id": item["citation_id"],
             "warnings": item.get("warnings", [])} for item in found["results"]]


def validate_citations(cfg: Config, evidence: list[dict], cutoff: str) -> None:
    as_of = _as_of(cutoff)
    kb, owner = _context(cfg)
    for item in evidence:
        if digest(item["content"].encode("utf-8")) != item["sha256"]:
            raise ValueError("citation content mismatch")
        if len(item["citation_id"].split(":")[0]) != 32:
            raise ValueError("legacy citation from the retired knowledge store; regenerate the report")
        try:
            found = kb.citation(owner, item["citation_id"])
        except ServiceError:
            raise ValueError("citation revoked, unauthorized or not yet available") from None
        if found["chunk"].get("text") != item["content"]:
            raise ValueError("citation content mismatch")
        if not found["document"]["active"] or not _available(found["document"]["metadata"], as_of):
            raise ValueError("citation revoked, unauthorized or not yet available")


def revoke(cfg: Config, document_id: str) -> None:
    store, memory, kb = _knowledge(cfg)
    owner = _owner(store, memory, cfg.principal, primary=True)
    with store.db() as con:
        mapped = [row[0] for row in con.execute("SELECT owner FROM kb_owner_map ORDER BY principal")]
    # One legacy document could carry several ACLs, so revoking it has to reach
    # every copy this facade created, not only the caller's own.
    candidates = [owner] + [item for item in dict.fromkeys(mapped) if item != owner]
    logical = None
    for candidate in candidates:
        try:
            logical = kb.document(candidate, document_id)["logical"]
            break
        except ServiceError:
            continue
    if logical is None:
        raise ValueError("unknown document")
    for candidate in candidates:
        for version in kb.versions(candidate, logical):
            if version["active"]:
                kb.retire(candidate, version["id"])
