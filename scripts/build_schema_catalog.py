"""Build/check the packaged DDL catalogue without importing application services."""
import argparse
import ast
import hashlib
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/stock_predict_mailer/operations/schema_catalog.json"

# Historical state.sqlite3 layout, retained after upstream removed knowledge.py.
# This is recognition only: the facade does not auto-migrate old evidence or ACLs.
LEGACY_KNOWLEDGE = [
    "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, title TEXT NOT NULL, published_at TEXT NOT NULL, available_at TEXT NOT NULL, active INTEGER NOT NULL);",
    "CREATE TABLE IF NOT EXISTS document_acl (document_id TEXT NOT NULL, principal TEXT NOT NULL, PRIMARY KEY (document_id, principal));",
    "CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, document_id TEXT NOT NULL, ordinal INTEGER NOT NULL, content TEXT NOT NULL, sha256 TEXT NOT NULL);",
    "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(terms);",
]


def ddl(relative):
    tree = ast.parse((ROOT / "src" / relative).read_text(encoding="utf-8"))
    constants = {target.id: node.value for node in tree.body if isinstance(node, ast.Assign)
                 for target in node.targets if isinstance(target, ast.Name)}
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr not in ("execute", "executescript") or not node.args:
            continue
        value = node.args[0]
        if isinstance(value, ast.Name):
            value = constants.get(value.id)
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not value.value.lstrip().upper().startswith("CREATE "):
            continue
        pending = ""
        for character in value.value:
            pending += character
            if character == ";" and sqlite3.complete_statement(pending):
                result.append(pending.strip())
                pending = ""
        if pending.strip():
            result.append(pending.strip().rstrip(";") + ";")
    return result


def object_name(sql):
    match = re.match(r"CREATE\s+(?:VIRTUAL\s+|UNIQUE\s+)?(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][a-zA-Z_0-9]*)", sql, re.I)
    if not match:
        raise ValueError("unsupported catalogue DDL")
    return match[1]


def addition(identifier, table, column, declaration, *, data_sql=None, effect="adds_defaulted_or_nullable_column"):
    return {"id": identifier, "table": table, "column": column, "sql": f"ALTER TABLE {table} ADD COLUMN {column} {declaration}",
            "data_sql": data_sql or [], "data_effect": effect}


def build():
    groups = {}
    def group(name, module, *, objects=None, additions=None, initialize=False):
        statements = ddl(module)
        if objects is not None:
            statements = [sql for sql in statements if object_name(sql) in objects]
        if not statements:
            raise ValueError("empty catalogue group: " + name)
        source_id = hashlib.sha256((ROOT / "src" / module).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        groups[name] = {"source": module, "source_id": source_id, "ddl": statements, "additions": additions or [], "initialize_when_absent": initialize,
                        "target_revision": "2" if additions else "1"}
    group("mail.core", "stock_predict_mailer/mail_core/service.py", objects={"mail", "mail_audit"})
    group("mail.bindings", "stock_predict_mailer/mail_core/service.py", objects={"mail_binding", "mail_alias", "mail_control"}, initialize=True)
    group("mail.archive", "stock_predict_mailer/mail_core/migration.py")
    group("control.base", "stock_predict_mailer/control/store.py")
    group("control.memory", "stock_predict_mailer/control/memory.py")
    groups["control.receipts"] = {"source": "historical control/orchestrator", "ddl": ["CREATE TABLE IF NOT EXISTS mcp_mail (id TEXT PRIMARY KEY,status TEXT);"],
                                  "additions": [], "initialize_when_absent": False, "target_revision": "1"}
    group("control.knowledge_owners", "stock_predict_mailer/knowledge_api.py")
    group("knowledge.core", "stock_predict_mailer/private_knowledge/service.py",
          objects={"owners", "documents", "doc_owner", "chunks", "chunk_fts", "relations", "generations", "vectors", "review_audit"}, additions=[
        addition("knowledge.cleaner_config", "owners", "cleaner_config", "BLOB"),
        addition("knowledge.extraction", "documents", "extraction", "TEXT"),
        addition("knowledge.review", "documents", "review", "TEXT"),
        addition("knowledge.origin", "relations", "origin", "TEXT NOT NULL DEFAULT 'structured'"),
        addition("knowledge.claim_id", "relations", "claim_id", "TEXT"),
    ])
    group("knowledge.workers", "stock_predict_mailer/private_knowledge/service.py", objects={"workers"}, initialize=True)
    group("crawler.jobs", "mcp_server/jobs.py")
    group("legacy.runs", "stock_predict_mailer/core.py")
    group("legacy.outbox", "stock_predict_mailer/delivery.py")
    group("legacy.authorizations", "stock_predict_mailer/dataset_auth.py", additions=[
        addition("legacy.replay", "dataset_authorizations", "replay_enabled", "INTEGER NOT NULL DEFAULT 0",
                 data_sql=["UPDATE dataset_authorizations SET replay_enabled=1 WHERE platform_training=1"],
                 effect="enables_replay_for_existing_platform_training_grants")])
    group("legacy.training", "stock_predict_mailer/model_training.py", additions=[
        addition("legacy.additional_rounds", "training_specs", "additional_rounds", "INTEGER NOT NULL DEFAULT 0"),
        addition("legacy.priority", "training_jobs", "priority", "INTEGER NOT NULL DEFAULT 0")])
    groups["legacy.knowledge"] = {"source": "historical knowledge.py before bb8c104", "ddl": LEGACY_KNOWLEDGE,
                                  "additions": [], "initialize_when_absent": False, "target_revision": "1"}
    for label, module in (("calendar", "calendar"), ("updates", "marketdata"), ("registry", "model_registry"),
                          ("drift", "drift"), ("keys", "keys"), ("retention", "retention"), ("shadow", "shadow")):
        group("legacy." + label, "stock_predict_mailer/" + module + ".py")
    version_tree = ast.parse((ROOT / "src/stock_predict_mailer/__init__.py").read_text(encoding="utf-8"))
    version = next(node.value.value for node in version_tree.body if isinstance(node, ast.Assign) and
                   any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets))
    return {"schema_version": "1", "catalogue_revision": "2", "app_version": version, "groups": groups,
            "stores": {
                "mail": {"required": ["mail.core"], "groups": ["mail.core", "mail.bindings", "mail.archive"]},
                "control": {"required": ["control.base"], "groups": ["control.base", "control.memory", "control.receipts", "control.knowledge_owners"]},
                "knowledge": {"required": ["knowledge.core"], "groups": ["knowledge.core", "knowledge.workers"]},
                "crawler": {"required": ["crawler.jobs"], "groups": ["crawler.jobs"]},
                "legacy": {"required": ["legacy.runs"], "groups": [name for name in groups if name.startswith("legacy.")]}}}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    result = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != result:
            print("schema-catalogue: stale; rebuild and review the catalogue")
            return 1
        print("schema-catalogue: current")
        return 0
    OUTPUT.write_text(result, encoding="utf-8")
    print("schema-catalogue: generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
