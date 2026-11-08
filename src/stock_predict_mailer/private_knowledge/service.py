"""Private immutable files, resumable import jobs and atomic index generations."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..agent_service.contracts import ServiceError, utcnow
from ..core import atomic_write
from .cleaner import CleanerAdapter, cleaner_config, extract, fingerprint
from .embedding import EmbeddingAdapter, configuration
from .parsing import FORMATS, clean, parse


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def terms(text):
    text = text.casefold()
    result = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", text)
    for word in re.findall(r"[\u3400-\u9fff]+", text):
        result += [word[i:i + 2] for i in range(len(word) - 1)]
    return sorted(set(result))


def day(value):
    if not isinstance(value, str):
        raise ServiceError("INVALID_INPUT", "日期须为 YYYY-MM-DD")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ServiceError("INVALID_INPUT", "日期须为 YYYY-MM-DD") from None


def stock_codes(text, *, explicit=False):
    codes = set()
    pattern = r"(?<![A-Z0-9])(\d{6})(?:[. ]?(SH|SZ|BJ))?(?![A-Z0-9])" if explicit else r"(?<![A-Z0-9])(\d{6})[. ]?(SH|SZ|BJ)(?![A-Z0-9])"
    for code, exchange in re.findall(pattern, text.upper()):
        exchange = exchange or ("SH" if code.startswith("6") else "BJ" if code.startswith(("4", "8", "9")) else "SZ")
        codes.add(f"{code}.{exchange}")
    return sorted(codes)


class Knowledge:
    def __init__(self, store, adapter=None, cleaner_adapter=None):
        self.store, self.root = store, store.root / "private-knowledge"
        self.root.mkdir(parents=True, exist_ok=True)
        self.adapter = adapter or EmbeddingAdapter()
        self.cleaner = cleaner_adapter or CleanerAdapter()
        with self.db() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS owners (owner TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0, config BLOB);
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, logical TEXT NOT NULL, filename TEXT NOT NULL,
                    hash TEXT NOT NULL, metadata TEXT NOT NULL, uploaded TEXT NOT NULL,
                    status TEXT NOT NULL, step TEXT NOT NULL, error TEXT, parsed TEXT, draft TEXT,
                    active INTEGER NOT NULL DEFAULT 0, UNIQUE(owner,logical,hash,metadata));
                CREATE INDEX IF NOT EXISTS doc_owner ON documents(owner,logical,active);
                CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, doc TEXT NOT NULL, owner TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, body TEXT NOT NULL, UNIQUE(doc,ordinal));
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(terms);
                CREATE TABLE IF NOT EXISTS relations (id TEXT PRIMARY KEY, owner TEXT NOT NULL, doc TEXT NOT NULL,
                    chunk INTEGER NOT NULL, subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL,
                    valid_from TEXT, valid_to TEXT, evidence TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS generations (id TEXT PRIMARY KEY, owner TEXT NOT NULL, config BLOB NOT NULL,
                    dimension INTEGER, status TEXT NOT NULL, error TEXT);
                CREATE TABLE IF NOT EXISTS vectors (generation TEXT NOT NULL, chunk INTEGER NOT NULL, vector TEXT NOT NULL,
                    PRIMARY KEY(generation,chunk));
                CREATE TABLE IF NOT EXISTS review_audit (id TEXT PRIMARY KEY, owner TEXT NOT NULL, doc TEXT NOT NULL,
                    at TEXT NOT NULL, decision TEXT NOT NULL, body TEXT NOT NULL);
            """)
            con.execute("BEGIN IMMEDIATE")
            for table, additions in {"owners": {"cleaner_config": "BLOB"},
                                     "documents": {"extraction": "TEXT", "review": "TEXT"},
                                     "relations": {"origin": "TEXT NOT NULL DEFAULT 'structured'", "claim_id": "TEXT"}}.items():
                columns = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                for column, sql_type in additions.items():
                    if column not in columns:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.root / "knowledge.sqlite3", timeout=20)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def ensure(self, owner):
        with self.store.db() as con:
            if con.execute("SELECT 1 FROM memory_owners WHERE id=?", (owner,)).fetchone() is None:
                raise ServiceError("FORBIDDEN", "私有用户不存在")
        with self.db() as con:
            con.execute("INSERT OR IGNORE INTO owners(owner) VALUES (?)", (owner,))

    def seal(self, value):
        return self.store.cipher.encrypt(packed(value).encode())

    def opened(self, blob):
        return json.loads(self.store.cipher.decrypt(blob))

    def config(self, owner, raw=None):
        self.ensure(owner)
        with self.db() as con:
            row = con.execute("SELECT config FROM owners WHERE owner=?", (owner,)).fetchone()
            cfg = self.opened(row[0]) if row[0] else configuration({})
            if raw is not None:
                if not isinstance(raw, dict):
                    raise ServiceError("INVALID_CONFIG", "配置须为对象")
                same_destination = raw.get("provider") == cfg["provider"] and raw.get("base_url") == cfg["base_url"]
                cfg = configuration({**raw, "api_key": raw.get("api_key") or (cfg.get("api_key", "") if same_destination else "")}, require_consent=False)
                con.execute("UPDATE owners SET config=?,revision=revision+1 WHERE owner=?", (self.seal(cfg), owner))
            active = con.execute("SELECT id,dimension,config FROM generations WHERE owner=? AND status='active'", (owner,)).fetchone()
        public = {k: v for k, v in cfg.items() if k != "api_key"}
        return {**public, "has_secret": bool(cfg.get("api_key")), "active_index": active["id"] if active else None,
                "dimension": active["dimension"] if active else None,
                "active_model": self.opened(active["config"])["model"] if active else None}

    def private_config(self, owner):
        self.ensure(owner)
        with self.db() as con:
            raw = con.execute("SELECT config FROM owners WHERE owner=?", (owner,)).fetchone()[0]
        return self.opened(raw) if raw else configuration({})

    def test(self, owner):
        cfg = self.private_config(owner)
        if cfg["provider"] == "none":
            return {"status": "lexical_only", "dimension": None}
        vectors = self.adapter.embed(cfg, ["股票风险与营业收入", "供应链事件"])
        return {"status": "ok", "dimension": len(vectors[0]), "model": cfg["model"], "version": cfg["version"]}

    def cleaning_config(self, owner, raw=None, *, private=False):
        self.ensure(owner)
        with self.db() as con:
            row = con.execute("SELECT cleaner_config FROM owners WHERE owner=?", (owner,)).fetchone()
            cfg = self.opened(row[0]) if row[0] else cleaner_config({})
            if raw is not None:
                if not isinstance(raw, dict):
                    raise ServiceError("INVALID_CONFIG", "清洗配置须为对象")
                clear = raw.get("clear_secret", False)
                if type(clear) is not bool:
                    raise ServiceError("INVALID_CONFIG", "clear_secret 须为布尔值")
                body = {k: v for k, v in raw.items() if k != "clear_secret"}
                same = body.get("provider") == cfg["provider"] and body.get("base_url") == cfg["base_url"]
                body["api_key"] = "" if clear else body.get("api_key") or (cfg["api_key"] if same else "")
                cfg = cleaner_config(body)
                con.execute("UPDATE owners SET cleaner_config=? WHERE owner=?", (self.seal(cfg), owner))
        if private:
            return cfg
        return {**{k: v for k, v in cfg.items() if k != "api_key"}, "has_secret": bool(cfg["api_key"]),
                "fingerprint": fingerprint(cfg), "review_policy": "all_model_candidates"}

    def authorize_cleaner(self, owner, cfg):
        current = self.cleaning_config(owner, private=True)
        if fingerprint(current) != fingerprint(cfg):
            raise ServiceError("CLEANER_CONFIG_CHANGED", "清洗配置或外发授权已改变，请重置提取步骤")
        configuration({k: cfg[k] for k in ("provider", "base_url", "model", "version", "api_key", "allow_external", "timeout_seconds")})

    def test_cleaner(self, owner):
        cfg = self.cleaning_config(owner, private=True)
        if cfg["provider"] == "none":
            return {"status": "disabled"}
        draft = {"chunks": [{"text": "测试公司没有可核实资料。", "fields": {}, "location": {"line": 1}}]}
        state = extract(self.cleaner, cfg, draft, {}, lambda _: None, lambda: self.authorize_cleaner(owner, cfg))
        return {"status": "ok", "model": cfg["model"], "version": cfg["version"],
                "candidates": len(state["candidates"]), "message": "连接与结构化输出通过，不代表提取准确率"}

    def review_digest(self, row):
        return hashlib.sha256(packed([row["hash"], row["metadata"], row["draft"], row["extraction"]]).encode()).hexdigest()

    def review(self, owner, did, decision=None, digest=None, approved_ids=None):
        self.ensure(owner)
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._row(con, owner, did)
            state = json.loads(row["extraction"]) if row["extraction"] else None
            current_digest = self.review_digest(row)
            if decision is not None:
                if row["status"] != "review" or not state or not state.get("complete"):
                    raise ServiceError("INVALID_STATE", "仅完整提取且待复核的资料可审阅")
                if digest != current_digest:
                    raise ServiceError("REVIEW_CHANGED", "复核批次已改变，请重新读取候选")
                if decision not in ("approve", "reject") or not isinstance(approved_ids, list) or any(not isinstance(v, str) for v in approved_ids):
                    raise ServiceError("INVALID_INPUT", "需要 approve/reject 与 approved_ids 列表")
                valid = {c["id"] for c in state["candidates"] if c["validated"]}
                if len(set(approved_ids)) != len(approved_ids) or not set(approved_ids) <= valid or (decision == "reject" and approved_ids):
                    raise ServiceError("INVALID_INPUT", "无依据或重复候选不可批准，reject 不接受候选")
                audit = {"digest": digest, "approved_ids": approved_ids, "at": utcnow().isoformat(), "decision": decision}
                con.execute("INSERT INTO review_audit VALUES (?,?,?,?,?,?)", (uuid.uuid4().hex, owner, did, audit["at"], decision, packed(audit)))
                con.execute("UPDATE documents SET review=?,status=?,step='reviewed' WHERE id=? AND owner=?",
                            (packed(audit), "pending" if decision == "approve" else "rejected", did, owner))
            return {"id": did, "digest": current_digest, "extraction": state, "review": audit if decision is not None else json.loads(row["review"]) if row["review"] else None,
                    "status": row["status"] if decision is None else "pending" if decision == "approve" else "rejected"}

    def reextract(self, owner, did):
        self.ensure(owner)
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._row(con, owner, did)
            if row["active"] or row["status"] not in ("failed", "review", "rejected"):
                raise ServiceError("INVALID_STATE", "仅未发布的失败或复核版本可重置提取")
            con.execute("UPDATE documents SET status='pending',step='chunked',extraction=NULL,review=NULL,error=NULL WHERE id=? AND owner=?", (did, owner))
        return self.document(owner, did)

    def metadata(self, value):
        allowed = {"source", "document_date", "available_date", "valid_to", "companies", "industries", "topics", "stock_codes"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise ServiceError("INVALID_INPUT", "资料元数据无效")
        value = {"source": "用户上传", "document_date": None, "available_date": utcnow().date().isoformat(),
                 "valid_to": None, "companies": [], "industries": [], "topics": [], "stock_codes": [], **value}
        for key in ("document_date", "available_date", "valid_to"):
            if value[key] is not None:
                value[key] = day(value[key])
        if value["available_date"] is None:
            raise ServiceError("INVALID_INPUT", "可用日期不可为空")
        if value["valid_to"] and value["document_date"] and value["valid_to"] < value["document_date"]:
            raise ServiceError("INVALID_INPUT", "有效期结束早于文档日期")
        if not isinstance(value["source"], str) or not 1 <= len(value["source"]) <= 1000:
            raise ServiceError("INVALID_INPUT", "来源须非空")
        for key in ("companies", "industries", "topics", "stock_codes"):
            if not isinstance(value[key], list) or len(value[key]) > 40 or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in value[key]):
                raise ServiceError("INVALID_INPUT", "元数据标签无效")
        if any(not stock_codes(code, explicit=True) for code in value["stock_codes"]):
            raise ServiceError("INVALID_INPUT", "股票代码标签无法规范")
        value["stock_codes"] = stock_codes(" ".join(value["stock_codes"]), explicit=True)
        return value

    def upload(self, owner, filename, raw, metadata=None, logical=None):
        self.ensure(owner)
        if (not isinstance(filename, str) or Path(filename).name != filename or "/" in filename or "\\" in filename
                or len(filename) > 200 or Path(filename).suffix.lower() not in FORMATS):
            raise ServiceError("FORMAT_UNSUPPORTED", "支持 PDF/DOCX/TXT/MD/CSV/XLSX/JSON，不接受路径")
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= 10 * 1024 * 1024:
            raise ServiceError("FILE_LIMIT", "原文件须为 1 字节至 10 MiB")
        meta = self.metadata(metadata or {})
        logical = logical or filename
        if not isinstance(logical, str) or not 1 <= len(logical) <= 200:
            raise ServiceError("INVALID_INPUT", "逻辑资料名称无效")
        fingerprint = hashlib.sha256(raw).hexdigest()
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT id FROM documents WHERE owner=? AND logical=? AND hash=? AND metadata=?",
                              (owner, logical, fingerprint, packed(meta))).fetchone()
            if row:
                did = row[0]
            else:
                did = uuid.uuid4().hex
                folder = self.root / owner
                atomic_write(folder / (did + ".bin"), self.store.cipher.encrypt(raw))
                con.execute("INSERT INTO documents(id,owner,logical,filename,hash,metadata,uploaded,status,step) VALUES (?,?,?,?,?,?,?,'pending','received')",
                            (did, owner, logical, filename, fingerprint, packed(meta), utcnow().isoformat()))
                con.execute("UPDATE owners SET revision=revision+1 WHERE owner=?", (owner,))
        return self.document(owner, did)

    def _row(self, con, owner, did):
        row = con.execute("SELECT * FROM documents WHERE id=? AND owner=?", (did, owner)).fetchone()
        if row is None:
            raise ServiceError("NOT_FOUND", "资料不存在或无权访问")
        return row

    def document(self, owner, did, detail=False):
        self.ensure(owner)
        with self.db() as con:
            row = dict(self._row(con, owner, did))
            result = {k: row[k] for k in ("id", "logical", "filename", "hash", "uploaded", "status", "step", "error", "active")}
            result["metadata"] = json.loads(row["metadata"])
            draft = json.loads(row["draft"]) if row["draft"] else {}
            result["warnings"] = draft.get("warnings", [])
            result["needs_review"] = bool(result["warnings"]) or row["status"] == "review"
            result["extraction"] = json.loads(row["extraction"]) if detail and row["extraction"] else None
            result["review"] = json.loads(row["review"]) if row["review"] else None
            reasons = {"PARSE_OR_IMPORT_FAILED": "文件解析或导入失败，请检查格式和当前步骤",
                       "REVIEW_REQUIRED": "扫描件、缺失字段或复杂结构需要人工复核",
                       "PARSER_MISSING": "缺少解析依赖，请安装 knowledge extra",
                       "UNSUPPORTED_ENCODING": "文本不是 UTF-8，请转换编码后更新资料",
                       "INTERRUPTED": "工作进程中断，可重试已完成步骤之后的处理"}
            result["error_message"] = reasons.get(row["error"], row["error"])
            if detail:
                result["chunks"] = [json.loads(r[0]) for r in con.execute("SELECT body FROM chunks WHERE doc=? AND owner=? ORDER BY ordinal", (did, owner))]
                if not result["chunks"]:
                    result["chunks"] = draft.get("chunks", [])
                result["relations"] = [dict(r) for r in con.execute("SELECT * FROM relations WHERE doc=? AND owner=?", (did, owner))]
        return result

    def listing(self, owner):
        self.ensure(owner)
        with self.db() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM documents WHERE owner=? ORDER BY uploaded DESC,id", (owner,))]
        return [self.document(owner, did) for did in ids]

    def citation(self, owner, citation_id):
        if not isinstance(citation_id, str) or not re.fullmatch(r"[a-f0-9]{32}:[0-9]{1,8}", citation_id):
            raise ServiceError("INVALID_INPUT", "引用 ID 无效")
        did, ordinal = citation_id.split(":")
        item = self.document(owner, did)
        with self.db() as con:
            row = con.execute("SELECT body FROM chunks WHERE doc=? AND owner=? AND ordinal=?", (did, owner, int(ordinal))).fetchone()
        if row is None:
            raise ServiceError("NOT_FOUND", "引用不存在或已删除")
        return {"citation_id": citation_id, "document": item, "chunk": json.loads(row[0])}

    def original(self, owner, did):
        item = self.document(owner, did)
        return item["filename"], self.store.cipher.decrypt((self.root / owner / (did + ".bin")).read_bytes())

    def retry(self, owner, did):
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._row(con, owner, did)
            if row["status"] != "failed":
                raise ServiceError("INVALID_STATE", "只能重试失败任务")
            con.execute("UPDATE documents SET status='pending',error=NULL WHERE id=? AND owner=?", (did, owner))
        return self.document(owner, did)

    def recover(self):
        # Explicit worker startup recovery; web requests never reset a running worker.
        with self.db() as con:
            con.execute("UPDATE documents SET status='failed',error='INTERRUPTED' WHERE status='processing'")

    def process_one(self):
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM documents WHERE status='pending' ORDER BY uploaded,id LIMIT 1").fetchone()
            if row is None:
                return None
            item = dict(row)
            con.execute("UPDATE documents SET status='processing',error=NULL WHERE id=?", (item["id"],))
        owner, did = item["owner"], item["id"]
        try:
            if item["parsed"]:
                parsed = json.loads(item["parsed"])
            else:
                raw = self.store.cipher.decrypt((self.root / owner / (did + ".bin")).read_bytes())
                parsed = parse(item["filename"], raw)
                self._checkpoint(owner, did, "parsed", "parsed", parsed)
            draft = json.loads(item["draft"]) if item["draft"] else clean(parsed)
            if not draft["chunks"]:
                raise ServiceError("REVIEW_REQUIRED", "清洗后没有有效内容")
            self._checkpoint(owner, did, "chunked", "draft", draft)
            cfg = self.cleaning_config(owner, private=True)
            state = json.loads(item["extraction"]) if item["extraction"] else None
            reviewed = json.loads(item["review"]) if item["review"] else None
            if not reviewed and (cfg["provider"] != "none" or state):
                state = extract(self.cleaner, cfg, draft, json.loads(item["metadata"]),
                                lambda value: self._checkpoint(owner, did, "extracting", "extraction", value),
                                lambda: self.authorize_cleaner(owner, cfg), state)
                self.authorize_cleaner(owner, cfg)
                with self.db() as con:
                    self._row(con, owner, did)
                    con.execute("UPDATE documents SET status='review',step='extracted' WHERE id=? AND owner=?", (did, owner))
                return self.document(owner, did)
            if reviewed:
                with self.db() as con:
                    row = self._row(con, owner, did)
                    if reviewed["decision"] != "approve" or self.review_digest(row) != reviewed["digest"]:
                        raise ServiceError("REVIEW_CHANGED", "审批证据不一致，不能发布")
                approved = {c["id"] for c in state["candidates"] if c["validated"]} & set(reviewed["approved_ids"])
                for ordinal, chunk in enumerate(draft["chunks"]):
                    chunk["semantic_reviewed"] = True
                    chunk["extractions"] = [c for c in state["candidates"] if c["id"] in approved and c["chunk"] == ordinal]
            with self.db() as con:
                active = con.execute("SELECT * FROM generations WHERE owner=? AND status='active'", (owner,)).fetchone()
            def authorize_import():
                with self.db() as con:
                    self._row(con, owner, did)
                self.authorized_config(owner, active["config"])
            vectors = self._embed(self.authorized_config(owner, active["config"]), draft["chunks"], authorize=authorize_import) if active else []
            if vectors and len(vectors[0]) != active["dimension"]:
                raise ServiceError("EMBEDDING_DIMENSION", "模型维度已改变，请重建索引")
            with self.db() as con:
                con.execute("BEGIN IMMEDIATE")
                row = self._row(con, owner, did)
                current = con.execute("SELECT id FROM generations WHERE owner=? AND status='active'", (owner,)).fetchone()
                if (current[0] if current else None) != (active["id"] if active else None):
                    raise ServiceError("INDEX_CHANGED", "索引已切换，请重试当前步骤", True)
                con.execute("UPDATE documents SET active=0 WHERE owner=? AND logical=?", (owner, row["logical"]))
                for ordinal, chunk in enumerate(draft["chunks"]):
                    chunk["stock_codes"] = sorted(set(stock_codes(chunk["text"]) + [
                        code for key, value in chunk["fields"].items()
                        if key.strip().casefold() in ("股票代码", "证券代码", "stock_code", "ticker")
                        for code in stock_codes(str(value), explicit=True)]))
                    chunk["entities"] = {k: chunk["fields"][k] for k in ("company", "industry", "subject", "object", "event", "person") if k in chunk["fields"]}
                    cid = con.execute("INSERT INTO chunks(doc,owner,ordinal,body) VALUES (?,?,?,?)",
                                      (did, owner, ordinal, packed(chunk))).lastrowid
                    con.execute("INSERT INTO chunk_fts(rowid,terms) VALUES (?,?)", (cid, " ".join(terms(chunk["text"] + " " + row["metadata"]))))
                    if vectors:
                        con.execute("INSERT INTO vectors VALUES (?,?,?)", (active["id"], cid, packed(vectors[ordinal])))
                    self._relations(con, owner, did, cid, chunk, json.loads(row["metadata"]))
                    for candidate in chunk.get("extractions", []):
                        if candidate["kind"] == "relation" and candidate["assertion"] == "asserted":
                            con.execute("INSERT INTO relations(id,owner,doc,chunk,subject,predicate,object,valid_from,valid_to,evidence,origin,claim_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                        (uuid.uuid4().hex, owner, did, cid, candidate["subject"], candidate["predicate"], candidate["object"],
                                         candidate["valid_from"], candidate["valid_to"], candidate["quote"], "model_reviewed", candidate["id"]))
                con.execute("UPDATE documents SET active=1,status='ready',step='indexed',error=NULL WHERE id=? AND owner=?", (did, owner))
                con.execute("UPDATE owners SET revision=revision+1 WHERE owner=?", (owner,))
        except BaseException as exc:
            code = (exc.code if isinstance(exc, ServiceError) else "INTERRUPTED" if not isinstance(exc, Exception)
                    else "UNSUPPORTED_ENCODING" if isinstance(exc, UnicodeDecodeError) else "PARSE_OR_IMPORT_FAILED")
            with self.db() as con:
                con.execute("UPDATE documents SET status='failed',error=? WHERE id=? AND owner=?", (code, did, owner))
            if not isinstance(exc, Exception):
                raise
        try:
            return self.document(owner, did)
        except ServiceError:
            return {"id": did, "status": "deleted"}

    def _checkpoint(self, owner, did, step, column, value):
        with self.db() as con:
            self._row(con, owner, did)
            con.execute(f"UPDATE documents SET {column}=?,step=? WHERE id=? AND owner=?", (packed(value), step, did, owner))

    def authorized_config(self, owner, blob):
        cfg = self.opened(blob)
        current = self.private_config(owner)
        from urllib.parse import urlsplit
        if (cfg["provider"] != "none" and urlsplit(cfg["base_url"]).hostname not in ("localhost", "127.0.0.1", "::1")
                and (not current["allow_external"] or current["base_url"] != cfg["base_url"])):
            raise ServiceError("EXTERNAL_CONSENT", "旧索引的外发授权已撤销，需重建本地索引")
        return cfg

    def _embed(self, cfg, chunks, *, authorize=None):
        vectors = []
        for start in range(0, len(chunks), 16):
            if authorize:
                authorize()
            vectors.extend(self.adapter.embed(cfg, [packed(c["fields"]) + "\n" + c["text"] for c in chunks[start:start + 16]]))
        if vectors and len({len(v) for v in vectors}) != 1:
            raise ServiceError("EMBEDDING_DIMENSION", "批次间向量维度不一致")
        return vectors

    def _relations(self, con, owner, did, cid, chunk, meta):
        fields = chunk.get("normalized_fields", chunk["fields"])
        if chunk["location"].get("extracted_text_offset", 0) != 0:
            return
        if not all(isinstance(fields.get(k), str) and fields[k].strip() for k in ("subject", "predicate", "object")):
            return
        if fields.get("assertion", "asserted") != "asserted":
            return
        if any(len(fields[key]) > maximum for key, maximum in (("subject", 200), ("predicate", 100), ("object", 200))):
            raise ServiceError("REVIEW_REQUIRED", "关系实体或谓词过长，不能截断原始含义")
        start = fields.get("valid_from")
        end = fields.get("valid_to")
        if start:
            start = day(start)
        if end:
            end = day(end)
        if start and end and start > end:
            raise ServiceError("REVIEW_REQUIRED", "关系有效期无效")
        con.execute("INSERT INTO relations(id,owner,doc,chunk,subject,predicate,object,valid_from,valid_to,evidence) VALUES (?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, owner, did, cid,
                    fields["subject"], fields["predicate"], fields["object"], start, end, packed(chunk["fields"])))

    def rebuild(self, owner):
        cfg = self.private_config(owner)
        gid = uuid.uuid4().hex
        with self.db() as con:
            revision = con.execute("SELECT revision FROM owners WHERE owner=?", (owner,)).fetchone()[0]
            rows = con.execute("SELECT c.id,c.body FROM chunks c JOIN documents d ON c.doc=d.id WHERE c.owner=? AND d.active=1", (owner,)).fetchall()
            con.execute("INSERT INTO generations VALUES (?,?,?,NULL,'building',NULL)", (gid, owner, self.seal(cfg)))
        try:
            def authorize_build():
                with self.db() as con:
                    current = con.execute("SELECT revision FROM owners WHERE owner=?", (owner,)).fetchone()[0]
                if current != revision:
                    raise ServiceError("INDEX_CHANGED", "资料或外发授权在重建期间改变，停止后续批次", True)
                configuration(cfg)
            vectors = self._embed(cfg, [json.loads(r["body"]) for r in rows], authorize=authorize_build)
            authorize_build()
            # Probe an empty index so dimension metadata is still known.
            dimension = len(vectors[0]) if vectors else len(self.adapter.embed(cfg, ["维度测试"])[0]) if cfg["provider"] != "none" else None
            with self.db() as con:
                con.execute("BEGIN IMMEDIATE")
                current = con.execute("SELECT revision FROM owners WHERE owner=?", (owner,)).fetchone()[0]
                if current != revision:
                    raise ServiceError("INDEX_CHANGED", "资料在重建期间改变，原索引保留，请重试", True)
                con.executemany("INSERT INTO vectors VALUES (?,?,?)", [(gid, r["id"], packed(v)) for r, v in zip(rows, vectors, strict=False)])
                con.execute("UPDATE generations SET status='retired' WHERE owner=? AND status='active'", (owner,))
                con.execute("UPDATE generations SET status='active',dimension=? WHERE id=?", (dimension, gid))
        except BaseException as exc:
            with self.db() as con:
                con.execute("UPDATE generations SET status='failed',error=? WHERE id=?", (exc.code if isinstance(exc, ServiceError) else 'EMBEDDING_FAILED', gid))
            raise
        return {"id": gid, "status": "active", "dimension": dimension, "chunks": len(rows), "model": cfg["model"], "version": cfg["version"]}

    def indexes(self, owner):
        self.ensure(owner)
        with self.db() as con:
            rows = con.execute("SELECT id,status,dimension,error,config FROM generations WHERE owner=? ORDER BY rowid DESC", (owner,)).fetchall()
        return [{**{k: row[k] for k in ("id", "status", "dimension", "error")},
                 "model": self.opened(row["config"])["model"], "version": self.opened(row["config"])["version"],
                 "fingerprint": hashlib.sha256(packed({k: v for k, v in self.opened(row["config"]).items() if k != "api_key"}).encode()).hexdigest()} for row in rows]

    def delete(self, owner, did):
        self.ensure(owner)
        with self.db() as con:
            self._row(con, owner, did)
            con.execute("UPDATE documents SET active=0,status='deleting' WHERE owner=? AND id=?", (owner, did))
            con.execute("UPDATE owners SET revision=revision+1 WHERE owner=?", (owner,))
        try:
            (self.root / owner / (did + ".bin")).unlink(missing_ok=True)
        except OSError:
            raise ServiceError("DELETE_PENDING", "原件暂时无法删除，请重试删除", True) from None
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            self._row(con, owner, did)
            ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE owner=? AND doc=?", (owner, did))]
            for cid in ids:
                con.execute("DELETE FROM chunk_fts WHERE rowid=?", (cid,))
                con.execute("DELETE FROM vectors WHERE chunk=?", (cid,))
            con.execute("DELETE FROM review_audit WHERE owner=? AND doc=?", (owner, did))
            con.execute("DELETE FROM relations WHERE owner=? AND doc=?", (owner, did))
            con.execute("DELETE FROM chunks WHERE owner=? AND doc=?", (owner, did))
            con.execute("DELETE FROM documents WHERE owner=? AND id=?", (owner, did))
            con.execute("UPDATE owners SET revision=revision+1 WHERE owner=?", (owner,))
        # Deletion does not reactivate older versions.
        return {"status": "deleted", "id": did}

    def search(self, owner, query, *, as_of=None, start_date=None, stock_code=None, entity=None, limit=8):
        self.ensure(owner)
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 4000 or type(limit) is not int or not 1 <= limit <= 20:
            raise ServiceError("INVALID_INPUT", "查询须非空且 limit 为 1–20")
        as_of = day(as_of or utcnow().date().isoformat())
        start_date = day(start_date) if start_date else None
        if stock_code is not None and (not isinstance(stock_code, str) or not stock_codes(stock_code, explicit=True)):
            raise ServiceError("INVALID_INPUT", "股票代码无效")
        if entity is not None and (not isinstance(entity, str) or len(entity) > 200):
            raise ServiceError("INVALID_INPUT", "实体参数无效")
        with self.db() as con:
            con.execute("BEGIN")
            versions = con.execute("SELECT id,logical,metadata,uploaded FROM documents WHERE owner=? AND status='ready' AND logical IN (SELECT logical FROM documents WHERE owner=? AND active=1)", (owner, owner)).fetchall()
            selected = {}
            for version in versions:
                meta = json.loads(version["metadata"])
                if meta["available_date"] > as_of or (meta["document_date"] and meta["document_date"] > as_of):
                    continue
                key = (meta["available_date"], version["uploaded"], version["id"])
                if version["logical"] not in selected or key > selected[version["logical"]][0]:
                    selected[version["logical"]] = (key, version["id"])
            selected_ids = {v[1] for v in selected.values()}
            rows = con.execute("SELECT c.id,c.doc,c.ordinal,c.body,d.filename,d.metadata,d.hash FROM chunks c JOIN documents d ON d.id=c.doc WHERE c.owner=? AND d.owner=?", (owner, owner)).fetchall()
            rows = [r for r in rows if r["doc"] in selected_ids]
            relations = [dict(r) for r in con.execute("SELECT r.* FROM relations r JOIN documents d ON r.doc=d.id WHERE r.owner=? AND d.owner=?", (owner, owner)) if r["doc"] in selected_ids]
            active = con.execute("SELECT * FROM generations WHERE owner=? AND status='active'", (owner,)).fetchone()
            vecs = {r[0]: json.loads(r[1]) for r in con.execute("SELECT chunk,vector FROM vectors WHERE generation=?", (active["id"],))} if active else {}
            eligible = []
            for row in rows:
                meta = json.loads(row["metadata"])
                if meta["available_date"] > as_of or (meta["document_date"] and meta["document_date"] > as_of):
                    continue
                if start_date and (not meta["document_date"] or meta["document_date"] < start_date):
                    continue
                chunk = json.loads(row["body"])
                if chunk.get("data_date") and (chunk["data_date"] > as_of or (start_date and chunk["data_date"] < start_date)):
                    continue
                if stock_code and not set(stock_codes(stock_code, explicit=True)) & set(meta["stock_codes"] + chunk.get("stock_codes", [])):
                    continue
                eligible.append({**dict(row), **chunk, "metadata": meta})
            query_terms = terms(query)[:80]
            ranks = {}
            if query_terms:
                expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in query_terms)
                # FTS finds matches; owner-local token coverage ranks them without global IDF leakage.
                matches = {r[0] for r in con.execute("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?", (expression,))}
                local = [(r["id"], len(set(query_terms).intersection(terms(r["text"] + " " + packed(r["metadata"])))))
                         for r in eligible if r["id"] in matches]
                ranks = {cid: i + 1 for i, (cid, _) in enumerate(sorted(local, key=lambda p: (-p[1], p[0])))}
        ids = {r["id"] for r in eligible}
        relations = [r for r in relations if r["chunk"] in ids and (not r["valid_from"] or r["valid_from"] <= as_of)
                     and (not r["valid_to"] or r["valid_to"] >= as_of)]
        seeds = {entity} if entity else {v for r in relations for v in (r["subject"], r["object"]) if v in query}
        linked, edges = set(seeds), []
        for _ in range(2):
            frontier = set(linked)
            for relation in relations:
                if relation["subject"] in frontier or relation["object"] in frontier:
                    if relation not in edges:
                        edges.append(relation)
                    linked.update((relation["subject"], relation["object"]))
        vector_ranks, warnings = {}, []
        if active and active["dimension"]:
            try:
                vector = self.adapter.embed(self.authorized_config(owner, active["config"]), [query])[0]
                if len(vector) != active["dimension"]:
                    raise ServiceError("EMBEDDING_DIMENSION", "查询向量与索引维度不匹配")
                similarities = [(r["id"], sum(a * b for a, b in zip(vector, vecs[r["id"]], strict=True)))
                                for r in eligible if r["id"] in vecs]
                vector_ranks = {cid: i + 1 for i, (cid, score) in enumerate(sorted(similarities, key=lambda p: (-p[1], p[0]))) if score > 0}
            except ServiceError as exc:
                warnings.append(exc.code + "：已降级为关键词与关系检索")
        else:
            warnings.append("未启用语义向量索引，当前为关键词与关系检索")
        results = []
        edge_ids = {e["chunk"] for e in edges}
        for row in eligible:
            cid = row["id"]
            graph = cid in edge_ids or any(v in row["text"] or v in row["metadata"]["companies"] or v in row["metadata"]["industries"] for v in linked)
            if entity and not graph:
                continue
            score = (1 / (60 + ranks[cid]) if cid in ranks else 0) + (1 / (60 + vector_ranks[cid]) if cid in vector_ranks else 0) + (1 / 61 if graph else 0)
            if score:
                meta = row["metadata"]
                item_warnings = []
                for claim in row.get("extractions", []):
                    if claim["kind"] == "event" and (not claim["event_date"] or claim["event_date"] > as_of):
                        item_warnings.append("事件发生时间未知或晚于截止日期，不得用作当时已发生的事件")
                    if claim["assertion"] != "asserted":
                        item_warnings.append("来源含否定或不确定声明，不能当作肯定事实")
                if all(k in row["fields"] for k in ("subject", "predicate", "object")) and not row["fields"].get("valid_from"):
                    item_warnings.append("关系起始日期未知，不推断生效时间")
                if not meta["document_date"]:
                    item_warnings.append("文档日期未知")
                if meta["valid_to"] and meta["valid_to"] < as_of:
                    item_warnings.append("资料已过有效期，仅作历史参考")
                for key, label in (("valid_from", "关系尚未生效"), ("valid_to", "关系已过期")):
                    value = row.get("normalized_fields", row["fields"]).get(key)
                    if value and ((key == "valid_from" and value > as_of) or (key == "valid_to" and value < as_of)):
                        item_warnings.append(label + "，不得用作当前有效关系")
                results.append({"citation_id": f"{row['doc']}:{row['ordinal']}", "document_id": row["doc"], "chunk_id": cid,
                                "filename": row["filename"], "text": row["text"], "location": row["location"],
                                "fields": row["fields"], "extractions": row.get("extractions", []),
                                "semantic_reviewed": row.get("semantic_reviewed", False), "metadata": {**meta, "data_date": row.get("data_date"),
                                    "entities": row.get("entities", {}), "stock_codes": sorted(set(meta["stock_codes"] + row.get("stock_codes", [])))}, "score": score, "warnings": item_warnings,
                                "citation_path": f"/api/knowledge/citations/{row['doc']}:{row['ordinal']}",
                                "source_hash": row["hash"], "trust": "untrusted_source_material"})
        results.sort(key=lambda r: (-r["score"], r["citation_id"]))
        chosen = results[:limit]
        chosen_ids = {r["chunk_id"] for r in chosen}
        return {"query": query, "as_of": as_of, "results": chosen,
                "relations": [r for r in edges if r["chunk"] in chosen_ids], "warnings": warnings}

    def answer(self, owner, query, **filters):
        found = self.search(owner, query, **filters)
        citations = found["results"]
        lines = [f"资料截止日期：{found['as_of']}。以下是来源摘录与关系证据，不将原文声明当作已独立验证事实。"]
        if not citations:
            lines.append("证据不足：未找到当前权限与时间范围内的资料。")
        for item in citations:
            lines.append(f"[{item['citation_id']}] {item['metadata']['document_date'] or '日期未知'} {item['filename']}：{item['text']}")
        for edge in found["relations"]:
            cite = next((c["citation_id"] for c in citations if c["chunk_id"] == edge["chunk"]), None)
            if cite:
                lines.append(f"关系证据：{edge['subject']} —{edge['predicate']}→ {edge['object']}；有效期 {edge['valid_from'] or '未知'} 至 {edge['valid_to'] or '未声明'} [{cite}]")
        inferences = []
        for edge in found["relations"]:
            if edge["predicate"] not in ("供应商", "supplier", "采购自"):
                continue
            relation_source = next((c for c in citations if c["chunk_id"] == edge["chunk"]), None)
            for event in citations:
                risk = next((word for word in ("停产", "延期", "短缺", "制裁", "火灾") if word in event["text"]), None)
                supported_event = True
                if event.get("semantic_reviewed"):
                    typed_events = [c for c in event.get("extractions", []) if c["kind"] == "event" and c["assertion"] == "asserted"
                                    and c["subject"] == edge["object"] and c["event_date"] and c["event_date"] <= found["as_of"]
                                    and risk and risk in c["quote"]]
                    supported_event = bool(typed_events)
                elif risk:
                    clauses = [part for part in re.split(r"[，,。；;\n]", event["text"]) if risk in part]
                    supported_event = bool(clauses) and not any(re.search(r"否认|并非|不是|不再|尚未|未确认|未发生|未停产|不停产|没有|传闻|可能|拟|计划", part) for part in clauses)
                if edge.get("origin") == "model_reviewed" and not edge["valid_from"]:
                    supported_event = False
                if (supported_event and risk and edge["object"] in event["text"] and event["chunk_id"] != edge["chunk"]
                        and not event["warnings"] and relation_source and not relation_source["warnings"]):
                    refs = [relation_source["citation_id"], event["citation_id"]]
                    text = (f"条件性推断：资料将{edge['object']}列为{edge['subject']}的供应商，且有涉及该供应商的{risk}信息；"
                            f"{edge['subject']}可能存在交付连续性风险。采购占比、事件影响范围与替代能力尚无证据，不能量化损失。")
                    inferences.append({"text": text, "evidence_ids": refs, "kind": "bounded_rule_inference"})
                    lines.append(text + " " + " ".join(f"[{ref}]" for ref in refs))
        warnings = found["warnings"] + [w for c in citations for w in c["warnings"]]
        # Preserve potentially conflicting numeric evidence rather than deciding which source is true.
        values, field_sources = {}, {}
        for item in citations:
            for key, value in item["fields"].items():
                if key not in ("subject", "predicate", "object", "valid_from", "valid_to"):
                    values.setdefault(key, set()).add(packed(value))
                    field_sources.setdefault(key, []).append({"value": value, "citation_id": item["citation_id"],
                                                               "document_date": item["metadata"]["document_date"]})
        conflicting = [key for key, variants in values.items() if len(variants) > 1]
        if conflicting:
            warnings.append("来源字段取值不同，可能统计周期或口径不同，请核对：" + "、".join(conflicting))
        metric_groups = {}
        for item in citations:
            for claim in item.get("extractions", []):
                if claim["kind"] == "metric" and claim["assertion"] == "asserted":
                    key = (claim["subject"], claim["predicate"], claim["period"], claim["unit"])
                    metric_groups.setdefault(key, []).append({"value": claim["value"], "citation_id": item["citation_id"],
                                                              "document_date": item["metadata"]["document_date"]})
        typed_conflicts = [{"subject": key[0], "field": key[1], "period": key[2], "unit": key[3], "sources": items,
                            "status": "same_period_unit_different_source_values"} for key, items in metric_groups.items()
                           if len({Decimal(i["value"].replace(",", "")) for i in items}) > 1]
        if typed_conflicts:
            warnings.append("相同主体、指标、周期和单位存在不同来源数值，请核对原文，不自动择一")
        warnings.append("不能仅凭供应商或事件关联推断影响规模、确定因果关系或收益；需进一步核实。")
        return {**found, "answer": "\n\n".join(lines), "warnings": sorted(set(warnings)),
                "inferences": inferences, "conflicts": [{"field": key, "sources": field_sources[key],
                    "status": "different_values_need_period_and_unit_review"} for key in conflicting] + typed_conflicts, "mode": "evidence_extract"}
