"""Offline scoring of the retrieval path against a reviewed case set.

M9 exists because "the corpus is imported" and "questions get answered" are
different claims. This module turns annotated queries into one repeatable number,
with three properties that matter more than the number itself:

* **No model judges relevance.** A case names the version slots, domains and terms
  it expects; scoring is string matching over what ``search()`` actually returned.
  A second model would add variance exactly where the measurement is needed least.
* **A missing document is not a missed document.** When the expected slot is absent
  from the corpus the case is reported as ``blocked`` and excluded from the rate,
  because an empty shelf and a bad index need opposite fixes.
* **Point-in-time filtering is asserted, not sampled.** Every returned chunk must be
  available at the case's ``as_of``. A leak fails the run (``unsafe``) instead of
  quietly lowering the pass rate, since a leak means the conclusion of a backtest
  cannot be reproduced at all.

Thresholds are the operator's, not this module's: a case set is a contract about
what the corpus must answer, so the default 0.7 mirrors the seed-corpus acceptance
line rather than anything measured here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..agent_service.contracts import ServiceError, utcnow
from ..knowledge_api import open_store
from .service import day, domain, stock_codes

CASE_KEYS = {"id", "query", "as_of", "start_date", "stock_code", "entity", "expect", "note", "critical"}
EXPECT_KEYS = {"logical", "domains", "keywords", "min_results", "min_recall", "relation", "inference", "conflict"}
FILTERS = ("as_of", "start_date", "stock_code", "entity")
MAX_CASES = 500
TOP_SHOWN = 3


def squash(value):
    # Chinese retrieval text may carry the spaces a PDF extractor inserted, so a
    # keyword check that respects whitespace would fail on a correct hit.
    return re.sub(r"\s+", "", str(value)).casefold()


def _strings(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ServiceError("INVALID_INPUT", f"{label} 须为非空字符串列表")
    return [item.strip() for item in value]


def _load(path):
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        raise ServiceError("INVALID_INPUT", f"用例文件不可读：{path}") from None
    except ValueError as exc:
        raise ServiceError("INVALID_INPUT", f"用例文件不是合法 JSON：{exc}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ServiceError("INVALID_INPUT", '用例文件顶层须为 {"cases": [...]}')
    unknown = set(raw) - {"version", "cases", "note"}
    if unknown:
        raise ServiceError("INVALID_INPUT", f"用例文件含未知字段：{'、'.join(sorted(unknown))}")
    if not raw["cases"]:
        raise ServiceError("INVALID_INPUT", "用例文件没有任何用例")
    if len(raw["cases"]) > MAX_CASES:
        raise ServiceError("INVALID_INPUT", f"用例超过 {MAX_CASES} 条")
    return raw["cases"]


def _case(number, raw, default_as_of):
    """Validate one case strictly; a typo in a key would otherwise score as a miss."""
    if not isinstance(raw, dict):
        raise ServiceError("INVALID_INPUT", f"第 {number} 条用例须为对象")
    unknown = set(raw) - CASE_KEYS
    if unknown:
        raise ServiceError("INVALID_INPUT", f"第 {number} 条用例含未知字段：{'、'.join(sorted(unknown))}；允许 {', '.join(sorted(CASE_KEYS))}")
    ident, query = raw.get("id"), raw.get("query")
    if not isinstance(ident, str) or not ident.strip():
        raise ServiceError("INVALID_INPUT", f"第 {number} 条用例缺少 id")
    if not isinstance(query, str) or not query.strip():
        raise ServiceError("INVALID_INPUT", f"用例 {ident} 缺少 query")
    expect = raw.get("expect") or {}
    if not isinstance(expect, dict):
        raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 expect 须为对象")
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 expect 含未知字段：{'、'.join(sorted(unknown))}")
    logical, domains = _strings(expect.get("logical"), f"用例 {ident} 的 logical"), _strings(expect.get("domains"), f"用例 {ident} 的 domains")
    if not logical and not domains:
        raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 expect 至少要有 logical 或 domains，否则任何结果都算命中")
    minimum = expect.get("min_results", 1)
    if type(minimum) is not int or minimum < 0:
        raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 min_results 须为非负整数")
    recall = expect.get("min_recall", 1.0 if logical else 0.0)
    if type(recall) not in (int, float) or not 0 <= recall <= 1:
        raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 min_recall 须在 0 到 1 之间")
    for key in ("relation", "inference", "conflict"):
        if expect.get(key) is not None and not isinstance(expect[key], bool):
            raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 {key} 须为布尔值")
    case = {"id": ident.strip(), "query": query.strip(), "note": (raw.get("note") or "").strip(),
            "critical": bool(raw.get("critical")),
            "expect": {"logical": logical, "domains": domains, "keywords": _strings(expect.get("keywords"), f"用例 {ident} 的 keywords"),
                       "min_results": minimum, "min_recall": float(recall), "relation": bool(expect.get("relation")),
                       "inference": bool(expect.get("inference")), "conflict": bool(expect.get("conflict"))}}
    for key in FILTERS:
        if raw.get(key) is not None:
            if not isinstance(raw[key], str) or not raw[key].strip():
                raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 {key} 须为非空字符串")
            value = raw[key].strip()
            # Validated here rather than inside search(): one malformed case should not
            # abort a run that is otherwise fine, and the message should name the case.
            if key == "stock_code" and not stock_codes(value, explicit=True):
                raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 stock_code 无效：{value}")
            if key == "entity" and len(value) > 200:
                raise ServiceError("INVALID_INPUT", f"用例 {ident} 的 entity 超过 200 字符")
            case[key] = day(value) if key in ("as_of", "start_date") else value
    case.setdefault("as_of", default_as_of)
    return case


def _match(logical, expected):
    # A slot is written as a full name in the case, but a prefix is enough: one corpus
    # holds quarterly reports, and listing all five in every case is busywork.
    stem = expected.rstrip("/")
    return squash(logical) == squash(stem) or squash(logical).startswith(squash(stem) + "/")


def _corpus(kb, owner):
    """Slot -> the version that decides whether the corpus can answer at all."""
    with kb.db() as con:
        rows = con.execute("SELECT logical,status,active FROM documents WHERE owner=? ORDER BY uploaded,id", (owner,)).fetchall()
    found = {}
    for row in rows:
        current = found.get(row["logical"])
        # The active version is what search() can actually reach. A newer upload that
        # is still pending must not make the slot look unavailable, and a slot with no
        # active version at all keeps its status so the report can say why.
        if current is None or not current["active"]:
            found[row["logical"]] = {"status": row["status"], "active": bool(row["active"])}
    return found


def _resolution(case, corpus):
    """Why the expected slot cannot be retrieved, or None when the corpus has it."""
    expect = case["expect"]
    if not expect["logical"]:
        # A domain-only case still has a factual precondition: that domain must hold
        # something searchable. Without this check an empty workspace would score as
        # a retrieval miss, which points the operator at the index instead of the shelf.
        inside = {slot: state for slot, state in corpus.items() if domain(slot) in expect["domains"]}
        usable = [state for state in inside.values() if state["active"] and state["status"] == "ready"]
        if not usable:
            return [{"logical": "/".join(expect["domains"]),
                     "status": next(iter(inside.values()))["status"] if inside else "absent",
                     "detail": "期望域内没有可检索的资料"}]
        return None
    missing = []
    for expected in expect["logical"]:
        hits = {slot: state for slot, state in corpus.items() if _match(slot, expected)}
        live = [state for state in hits.values() if state["active"]]
        if not hits:
            missing.append({"logical": expected, "status": "absent", "detail": "语料里没有该槽位"})
        elif not live:
            missing.append({"logical": expected, "status": next(iter(hits.values()))["status"], "detail": "该槽位没有活动版本"})
        elif live[0]["status"] != "ready":
            missing.append({"logical": expected, "status": live[0]["status"], "detail": "活动版本尚未清洗完成"})
    return missing or None


def _leaks(items, as_of):
    """Chunks that should have been excluded by the point-in-time filter."""
    found = []
    for item in items:
        meta = item["metadata"]
        if meta["available_date"] > as_of or (meta["document_date"] and meta["document_date"] > as_of):
            found.append({"citation_id": item["citation_id"], "available_date": meta["available_date"],
                          "document_date": meta["document_date"], "as_of": as_of})
    return found


def _acceptable(item, expect):
    if any(_match(item["logical"], slot) for slot in expect["logical"]):
        return True
    if expect["domains"] and domain(item["logical"]) in expect["domains"]:
        return True
    return any(squash(word) in squash(item["text"]) for word in expect["keywords"])


def _score(kb, owner, case, *, limit, answer):
    filters = {key: case[key] for key in FILTERS if case.get(key)}
    found = kb.answer(owner, case["query"], limit=limit, **filters) if answer else kb.search(owner, case["query"], limit=limit, **filters)
    items, expect = found["results"], case["expect"]
    text = " ".join(squash(item["text"]) for item in items)
    hit_slots = [slot for slot in expect["logical"] if any(_match(item["logical"], slot) for item in items)]
    recall = len(hit_slots) / len(expect["logical"]) if expect["logical"] else None
    rank = next((index for index, item in enumerate(items) if _acceptable(item, expect)), None)
    # Only the expectations the case actually declares are reported: a "mode: true"
    # row in a search-mode run would read as a check that passed rather than one that
    # never applied.
    checks = {"results": len(items) >= expect["min_results"]}
    if expect["logical"]:
        checks["recall"] = recall >= expect["min_recall"]
    if expect["domains"]:
        checks["domain"] = any(domain(item["logical"]) in expect["domains"] for item in items)
    if expect["keywords"]:
        checks["keywords"] = all(squash(word) in text for word in expect["keywords"])
    if expect["relation"]:
        checks["relation"] = bool(found.get("relations"))
    if answer:
        checks["mode"] = found.get("mode") == "evidence_extract"
    if expect["inference"]:
        checks["inference"] = bool(found.get("inferences"))
    if expect["conflict"]:
        checks["conflict"] = bool(found.get("conflicts"))
    return {"id": case["id"], "query": case["query"], "as_of": found["as_of"], "critical": case["critical"],
            "status": "pass" if all(checks.values()) else "fail", "checks": checks,
            "mrr": 1 / (rank + 1) if rank is not None else 0.0, "recall": recall,
            "hit_slots": hit_slots, "missing_keywords": [word for word in expect["keywords"] if squash(word) not in text],
            "leaks": _leaks(items, found["as_of"]),
            "top": [{"logical": item["logical"], "citation_id": item["citation_id"], "score": round(item["score"], 6)} for item in items[:TOP_SHOWN]]}


def _rate(results):
    return round(sum(1 for item in results if item["status"] == "pass") / len(results), 3) if results else 0.0


def run(workspace, cases, *, principal="owner", limit=8, answer=False, threshold=0.7, as_of=None, progress=True):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ServiceError("INVALID_INPUT", "limit 须为 1–20")
    if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
        raise ServiceError("INVALID_INPUT", "threshold 须在 0 到 1 之间")
    default_as_of = day(as_of) if as_of else utcnow().date().isoformat()
    raw = _load(cases)
    seen, prepared = set(), []
    for number, item in enumerate(raw, start=1):
        case = _case(number, item, default_as_of)
        if case["id"] in seen:
            raise ServiceError("INVALID_INPUT", f"用例 id 重复：{case['id']}")
        seen.add(case["id"])
        prepared.append(case)

    kb, owner = open_store(workspace, principal)
    corpus = _corpus(kb, owner)
    tell = (lambda text: print(text, file=sys.stderr)) if progress else (lambda text: None)
    results, blocked = [], []
    for case in prepared:
        missing = _resolution(case, corpus)
        if missing:
            blocked.append({"id": case["id"], "query": case["query"], "critical": case["critical"],
                            "status": "blocked", "gold_missing": missing})
            tell(f"[blocked] {case['id']} {case['query']}：{missing[0]['detail']}（{missing[0]['status']}）")
            continue
        scored = _score(kb, owner, case, limit=limit, answer=answer)
        results.append(scored)
        failed = [name for name, ok in scored["checks"].items() if not ok]
        tell(f"[{scored['status']}] {case['id']} {case['query']}" + (f"：未通过 {', '.join(failed)}" if failed else ""))

    leaks = [{"id": item["id"], "leak": leak} for item in results for leak in item["leaks"]]
    critical_failed = [item["id"] for item in results if item["critical"] and item["status"] != "pass"]
    rate = _rate(results)
    summary = {"cases_file": str(cases), "principal": principal, "owner": owner, "as_of_default": default_as_of,
               "limit": limit, "answer": bool(answer), "threshold": threshold,
               "corpus": {"slots": len(corpus), "ready": sum(1 for state in corpus.values() if state["active"] and state["status"] == "ready"),
                          "domains": sorted({domain(slot) for slot in corpus})},
               "totals": {"cases": len(prepared), "evaluated": len(results), "passed": sum(1 for item in results if item["status"] == "pass"),
                          "failed": sum(1 for item in results if item["status"] == "fail"), "blocked": len(blocked),
                          "pass_rate": rate},
               "metrics": {"mrr": round(sum(item["mrr"] for item in results) / len(results), 3) if results else 0.0,
                           "mean_recall": round(sum(item["recall"] for item in results if item["recall"] is not None) /
                                                max(1, len([item for item in results if item["recall"] is not None])), 3)},
               "by_domain": {}, "gates": {"leaks": leaks, "safe": not leaks},
               "critical_failed": critical_failed, "results": results, "blocked": blocked}
    scored_by_id = {item["id"]: item for item in results}
    for case in prepared:
        item = scored_by_id.get(case["id"])
        if item is None:
            continue
        # One case can be filed under several expected domains; counting it in each
        # keeps the per-domain rate readable, and the total is not used as a sum.
        # A slot-only case still names a domain through its first segment.
        names = case["expect"]["domains"] or sorted({domain(slot.rstrip("/")) for slot in case["expect"]["logical"]})
        for name in names:
            bucket = summary["by_domain"].setdefault(name, {"evaluated": 0, "passed": 0})
            bucket["evaluated"] += 1
            bucket["passed"] += int(item["status"] == "pass")
    for bucket in summary["by_domain"].values():
        bucket["pass_rate"] = round(bucket["passed"] / bucket["evaluated"], 3) if bucket["evaluated"] else 0.0
    if leaks:
        summary["verdict"] = "unsafe"
    elif not results:
        summary["verdict"] = "empty"
    elif critical_failed or rate < threshold:
        summary["verdict"] = "fail"
    else:
        summary["verdict"] = "pass"
    if not corpus:
        summary["note"] = "该 owner 下没有任何资料；先用 STOCK_PREDICT_MAILER_KB_KEY 对齐控制台密钥再导入"
    elif blocked:
        summary["note"] = "blocked 表示语料里缺该槽位或尚未清洗完成，不计入通过率；先补语料再看分数"
    return summary
