"""Trusted schema catalogue and structural models; never import service constructors."""
import json
import re
import sqlite3
from functools import lru_cache
from importlib.resources import files

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError
from ..naming import version

INTERNAL = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat3", "sqlite_stat4"}
MAX_OBJECTS = 256
MAX_COLUMNS = 128
MAX_SQL_BYTES = 512 * 1024
TOKEN = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|--[^\n]*|/\*.*?\*/|[\w]+|[^\s]", re.S)


def sql_id(sql):
    if sql is None:
        return None
    tokens = [t if t.startswith(("'", '"', "`", "[")) else t.casefold()
              for t in TOKEN.findall(sql) if not t.startswith(("--", "/*"))]
    while tokens and tokens[-1] == ";":
        tokens.pop()
    return identity(tokens)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


@lru_cache(maxsize=1)
def catalogue():
    try:
        value = json.loads(files(__package__).joinpath("schema_catalog.json").read_text(encoding="utf-8"))
        if value["schema_version"] != "1" or value["app_version"] != version():
            raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise ServiceError("SCHEMA_CATALOGUE", "结构目录缺失、损坏或未匹配当前软件版本") from None


def shape(con):
    rows = con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    if len(rows) > MAX_OBJECTS or sum(len((r[3] or "").encode("utf-8")) for r in rows) > MAX_SQL_BYTES:
        raise ServiceError("SCHEMA_LIMIT", "数据库结构对象或定义大小超过上限")
    result = {}
    for kind, name, table, sql in rows:
        if name in INTERNAL:
            continue
        item = {"type": kind, "name": name, "table": table, "definition_id": sql_id(sql)}
        if kind == "table":
            columns = con.execute("PRAGMA table_xinfo(" + quote(name) + ")").fetchall()
            if len(columns) > MAX_COLUMNS:
                raise ServiceError("SCHEMA_LIMIT", "表结构字段数量超过上限")
            item["columns"] = [{"name": r[1], "type": r[2].strip().upper(), "not_null": r[3], "default_id": sql_id(r[4]), "pk": r[5], "hidden": r[6]} for r in columns]
            item["foreign_keys"] = [list(r) for r in con.execute("PRAGMA foreign_key_list(" + quote(name) + ")")]
        elif kind == "index":
            item["columns"] = [list(r)[1:] for r in con.execute("PRAGMA index_xinfo(" + quote(name) + ")")]
            item["flags"] = next((list(r)[2:] for r in con.execute("PRAGMA index_list(" + quote(table) + ")") if r[1] == name), None)
        result[kind + ":" + name] = item
    return result


def execute_group(con, group, additions=None):
    for statement in group["ddl"]:
        con.execute(statement)
    if additions is None:
        additions = [a["id"] for a in group["additions"]]
    by_id = {a["id"]: a for a in group["additions"]}
    for identifier in additions:
        con.execute(by_id[identifier]["sql"])


@lru_cache(maxsize=128)
def model(group_name, additions=None):
    group = catalogue()["groups"][group_name]
    con = sqlite3.connect(":memory:")
    try:
        con.execute("PRAGMA trusted_schema=OFF")
        execute_group(con, group, additions)
        return shape(con)
    except sqlite3.Error:
        raise ServiceError("SCHEMA_ENGINE", "当前 SQLite 不能构建所需结构模型") from None
    finally:
        con.close()


def classify(con, family):
    source = shape(con)
    schema_id = identity(source)
    record = {"schema_id": schema_id, "user_version": con.execute("PRAGMA user_version").fetchone()[0],
              "application_id": con.execute("PRAGMA application_id").fetchone()[0],
              "schema_cookie": con.execute("PRAGMA schema_version").fetchone()[0], "version_source": "structural_inference",
              "features": [], "operations": [], "issues": [], "objects": len(source)}
    if record["user_version"] != 0:
        record["issues"].append({"code": "UNREGISTERED_USER_VERSION"})
    if record["application_id"] != 0:
        record["issues"].append({"code": "FOREIGN_APPLICATION_ID"})
    definition = catalogue()["stores"][family]
    known_keys = set()
    for name in definition["groups"]:
        known_keys.update(model(name))
    unknown = set(source) - known_keys
    if unknown:
        record["issues"].append({"code": "UNKNOWN_SCHEMA_OBJECTS", "count": len(unknown), "objects_id": identity(sorted(unknown))})
    for name in definition["groups"]:
        group = catalogue()["groups"][name]
        target = model(name)
        present = {k: v for k, v in source.items() if k in target}
        feature = {"name": name, "target_revision": group["target_revision"], "inferred_revision": None, "state": "not_initialized"}
        record["features"].append(feature)
        if not present:
            if name in definition["required"]:
                feature["state"] = "unknown"
                record["issues"].append({"code": "REQUIRED_GROUP_MISSING", "feature": name})
            elif group["initialize_when_absent"]:
                feature["state"] = "upgrade_available"
                record["operations"].append({"id": name + ".initialize", "feature": name, "statements": list(group["ddl"]),
                    "data_effect": "creates_empty_binding_tables_without_deriving_history" if name == "mail.bindings" else "creates_empty_worker_status_table",
                    "requires_permission_review": False})
            continue
        present_adds, missing_adds = [], []
        for addition in group["additions"]:
            table = source.get("table:" + addition["table"])
            names = {c["name"] for c in table["columns"]} if table else set()
            (present_adds if addition["column"] in names else missing_adds).append(addition["id"])
        expected_old = model(name, tuple(present_adds))
        if present != expected_old:
            feature["state"] = "unknown"
            missing = len(set(expected_old) - set(present))
            record["issues"].append({"code": "INCOMPLETE_FEATURE_GROUP" if missing else "STRUCTURAL_DRIFT", "feature": name,
                                     "missing_objects": missing, "actual_id": identity(present), "expected_id": identity(expected_old)})
            continue
        if model(name, tuple(present_adds + missing_adds)) != target:
            feature["state"] = "unknown"
            record["issues"].append({"code": "UNSUPPORTED_ADDITION_ORDER", "feature": name})
            continue
        feature["inferred_revision"] = group["target_revision"] if not missing_adds else "1" if not present_adds else "1+known_additions"
        feature["state"] = "current" if not missing_adds else "upgrade_available"
        for addition in group["additions"]:
            if addition["id"] in missing_adds:
                record["operations"].append({"id": addition["id"], "feature": name, "statements": [addition["sql"], *addition["data_sql"]],
                    "data_effect": addition["data_effect"], "requires_permission_review": bool(addition["data_sql"])})
    if record["issues"]:
        record["state"], record["operations"] = "blocked", []
    else:
        record["state"] = "upgrade_available" if record["operations"] else "current"
    return record
