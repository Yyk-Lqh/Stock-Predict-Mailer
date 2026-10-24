"""Local text retrieval; document content is data, never executable instructions."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from .core import Config, connect, digest, timestamp


def schema(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, title TEXT NOT NULL,
            published_at TEXT NOT NULL, available_at TEXT NOT NULL, active INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS document_acl (
            document_id TEXT NOT NULL, principal TEXT NOT NULL,
            PRIMARY KEY (document_id, principal));
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY, document_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            content TEXT NOT NULL, sha256 TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(terms);
    """)


def terms(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    return words + [part[i:i + 2] for part in chinese for i in range(len(part) - 1)]


def ingest_document(cfg: Config, path: Path, published_at: str, available_at: str, allow: list[str]) -> dict:
    if path.suffix.lower() not in (".md", ".txt"):
        raise ValueError("only local UTF-8 .md and .txt documents supported")
    if timestamp(available_at) < timestamp(published_at):
        raise ValueError("available_at cannot precede publication")
    if not allow or any(not p.strip() for p in allow):
        raise ValueError("explicit nonempty ACL required")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("empty document")
    logical = digest(str(path.resolve()).encode("utf-8"))
    identity = {"logical": logical, "raw": digest(raw), "published": published_at,
                "available": available_at, "allow": sorted(set(allow))}
    doc_id = digest(json.dumps(identity, sort_keys=True).encode())
    with connect(cfg) as con:
        schema(con)
        existing = con.execute("SELECT id,active FROM documents WHERE id=?", (doc_id,)).fetchone()
        if existing:
            if not existing["active"]:
                raise ValueError("revoked version cannot be silently reactivated; change source or metadata")
            return {"document_id": doc_id, "status": "unchanged"}
        con.execute("UPDATE documents SET active=0 WHERE logical_key=?", (logical,))
        con.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, 1)", (doc_id, logical, path.name, published_at, available_at))
        con.executemany("INSERT INTO document_acl VALUES (?, ?)", [(doc_id, p) for p in set(allow)])
        # Character windows retain exact offsets, and overlap is explicit.
        for ordinal, offset in enumerate(range(0, len(text), 700)):
            content = text[offset:offset + 800]
            cur = con.execute("INSERT INTO chunks(document_id,ordinal,content,sha256) VALUES (?, ?, ?, ?)", (doc_id, ordinal, content, digest(content.encode())))
            con.execute("INSERT INTO chunk_fts(rowid,terms) VALUES (?, ?)", (cur.lastrowid, " ".join(terms(content))))
    return {"document_id": doc_id, "status": "created"}


def revoke(cfg: Config, document_id: str) -> None:
    with connect(cfg) as con:
        schema(con)
        if con.execute("UPDATE documents SET active=0 WHERE id=?", (document_id,)).rowcount != 1:
            raise ValueError("unknown document")


def retrieve(cfg: Config, query: str, cutoff: str, limit: int = 5) -> list[dict]:
    instant = timestamp(cutoff)
    if not query.strip() or not 1 <= limit <= 20:
        raise ValueError("nonempty query and limit 1..20 required")
    with connect(cfg) as con:
        schema(con)
        candidates = [dict(row) for row in con.execute("""SELECT c.id AS chunk_id,c.document_id,c.ordinal,
            c.content,c.sha256,d.title,d.published_at,d.available_at
            FROM chunks c JOIN documents d ON d.id=c.document_id
            JOIN document_acl a ON a.document_id=d.id
            WHERE d.active=1 AND a.principal=?""", (cfg.principal,))
            if timestamp(row["available_at"]) <= instant and timestamp(row["published_at"]) <= instant]
        if not candidates:
            return []
        query_terms = sorted(set(terms(query)))[:64]
        if not query_terms:
            return []
        # Apply authorization and as-of filtering inside FTS query too.
        placeholders = ",".join("?" for _ in candidates)
        expression = " OR ".join('"' + word.replace('"', '""') + '"' for word in query_terms)
        keyword = {r[0]: float(r[1]) for r in con.execute(
            f"SELECT rowid,bm25(chunk_fts) FROM chunk_fts WHERE chunk_fts MATCH ? AND rowid IN ({placeholders}) ORDER BY bm25(chunk_fts)",
            [expression] + [r["chunk_id"] for r in candidates])}
    # Local character hashing is a lexical vector baseline, not semantic embeddings.
    vectorizer = HashingVectorizer(analyzer="char", ngram_range=(2, 4), n_features=16384, alternate_sign=False, norm="l2")
    vectors = vectorizer.transform([r["content"] for r in candidates])
    similarities = (vectors @ vectorizer.transform([query]).T).toarray().ravel()
    lexical_order = {key: i + 1 for i, key in enumerate(sorted(keyword, key=keyword.get))}
    semantic_order = np.argsort(-similarities, kind="stable")
    vector_rank = {int(index): rank + 1 for rank, index in enumerate(semantic_order) if similarities[index] > 0}
    scored = []
    for i, row in enumerate(candidates):
        k_rank = lexical_order.get(row["chunk_id"])
        v_rank = vector_rank.get(i)
        if k_rank is None and v_rank is None:
            continue
        score = (1 / (60 + k_rank) if k_rank else 0) + (1 / (60 + v_rank) if v_rank else 0)
        scored.append({**row, "score": score, "citation_id": f"{row['document_id']}:{row['ordinal']}"})
    return sorted(scored, key=lambda r: (-r["score"], r["citation_id"]))[:limit]


def validate_citations(cfg: Config, evidence: list[dict], cutoff: str) -> None:
    instant = timestamp(cutoff)
    with connect(cfg) as con:
        schema(con)
        for item in evidence:
            row = con.execute("""SELECT c.content,c.sha256,d.available_at,d.published_at,d.active
                FROM chunks c JOIN documents d ON d.id=c.document_id
                JOIN document_acl a ON a.document_id=d.id
                WHERE c.id=? AND c.document_id=? AND a.principal=?""",
                (item["chunk_id"], item["document_id"], cfg.principal)).fetchone()
            if row is None or not row["active"] or timestamp(row["available_at"]) > instant or timestamp(row["published_at"]) > instant:
                raise ValueError("citation revoked, unauthorized or not yet available")
            if item["sha256"] != row["sha256"] or digest(item["content"].encode()) != row["sha256"] or row["content"] != item["content"]:
                raise ValueError("citation content mismatch")
