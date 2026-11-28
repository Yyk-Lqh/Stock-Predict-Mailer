"""相对市场跌涨（周频相对强弱）的只读读取层与白名单执行。

目录固定为 big 数据面下的 相对市场跌涨/，可用
STOCK_PREDICT_MAILER_DATAMART_RELATIVE_DIR 单独覆盖。只读工具不建目录、不联网。
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from mcp_server import datamart_core as core

CACHE_FILE = "周度特征缓存.csv"
MODEL_FILE = "周频模型_相对强弱.pkl"
LIST_PATTERN = "名单_*.csv"
PREDICTION_PATTERN = "预测_涨_相对_*.csv"
STAGES = {"predict": "周频跌涨模型.py", "list": "出名单.py"}
SIDE_ALIASES = {"top": "buy", "up": "buy", "bottom": "avoid", "down": "avoid"}
SIDES = ("both", "buy", "avoid", "all")
MAX_TOP = 500
MAX_LIMIT = 5000
KEEP_FILES = 5


def relative_dir() -> Path:
    configured = os.environ.get("STOCK_PREDICT_MAILER_DATAMART_RELATIVE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return core.data_dir(core.DATASETS["big"]) / "相对市场跌涨"


def _fail(code: str, message: str, **details) -> str:
    return json.dumps({"ok": False, "error": {"code": code, "message": message}, "details": details},
                      ensure_ascii=False)


def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} 须为 {low} 至 {high} 的整数")
    return value


def _date(value, name):
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"{name} 须为 YYYY-MM-DD") from None
    return value


def _number(text):
    if text is None:
        return None
    text = str(text).strip()
    if text in ("", "-", "--"):
        return None
    try:
        return round(float(text), 6)
    except ValueError:
        return None


def _files(pattern: str) -> list[Path]:
    root = relative_dir()
    if not root.exists():
        return []
    found = [path for path in root.glob(pattern) if path.is_file()]
    return sorted(found, key=lambda path: (path.stat().st_mtime, path.name))


def _entry(path: Path) -> dict:
    if not path.exists():
        return {"file": str(path), "exists": False}
    stat = path.stat()
    return {"file": str(path), "exists": True, "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")}


def status() -> str:
    """报告缓存、预测、名单与模型的状态；只按文件名和修改时间判断，不读大文件。"""
    root = relative_dir()
    if not root.exists():
        return _fail("ARTIFACT_MISSING", "相对市场跌涨目录不存在", dir=str(root))
    predictions, lists = _files(PREDICTION_PATTERN), _files(LIST_PATTERN)
    cache, model = root / CACHE_FILE, root / MODEL_FILE
    behind = bool(predictions and lists
                  and predictions[-1].stat().st_mtime > lists[-1].stat().st_mtime)
    response = {
        "ok": True, "dir": str(root),
        "cache": _entry(cache), "model": _entry(model),
        "predictions": [{"name": path.name, **_entry(path)} for path in predictions[-KEEP_FILES:]],
        "lists": [{"name": path.name, **_entry(path)} for path in lists[-KEEP_FILES:]],
        "latest_list_date": lists[-1].stem.removeprefix("名单_") if lists else None,
        "list_behind_predictions": behind,
        "model_behind_cache": bool(cache.exists() and model.exists()
                                   and cache.stat().st_mtime > model.stat().st_mtime),
    }
    hints = []
    if not cache.exists():
        hints.append("先跑 stage=predict 生成周度特征缓存与预测")
    if not lists:
        hints.append("还没有名单，跑 stage=list")
    elif behind:
        hints.append("预测缓存比名单新，名单可能已过期，重跑 stage=list")
    if response["model_behind_cache"]:
        hints.append("模型文件早于周度缓存，出名单时会自动重训")
    response["hints"] = hints
    return json.dumps(response, ensure_ascii=False)


def _list_rows(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            code = (row.get("股票代码") or "").strip()
            if not code:
                continue
            rows.append({"code": code.zfill(6), "date": (row.get("日期") or "").strip()[:10],
                         "probability": _number(row.get("概率")),
                         "weekly_return": _number(row.get("周收益"))})
    return rows


def _week_rows(path: Path, as_of: str | None) -> list[dict]:
    """从预测缓存里取 日期<=as_of 的最近一周；as_of 为空时取最后一整周。"""
    best, bucket = None, []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            day = (row.get("日期") or "").strip()[:10]
            if not day or (as_of and day > as_of):
                continue
            try:
                week = int(row.get("周序"))
            except (TypeError, ValueError):
                continue
            if best is None or week > best:
                best, bucket = week, []
            elif week < best:
                continue
            bucket.append({"code": (row.get("股票代码") or "").strip().zfill(6), "date": day,
                           "probability": _number(row.get("概率")),
                           "weekly_return": _number(row.get("下周收益"))})
    return [row for row in bucket if row["code"]]


def _names() -> dict[str, str]:
    path = core.data_dir(core.DATASETS["big"]) / core.ARTIFACTS["universe"][0]
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return {(row.get("股票代码") or "").strip().zfill(6): (row.get("股票名称") or "").strip()
                for row in csv.DictReader(stream) if (row.get("股票代码") or "").strip()}


def _ranked(rows, with_names: bool) -> list[dict]:
    ordered = sorted(rows, key=lambda row: (row["probability"] is None, -(row["probability"] or 0.0)))
    names = _names() if with_names else {}
    for position, row in enumerate(ordered, 1):
        row["rank"] = position
        if with_names:
            row["name"] = names.get(row["code"], "")
    return ordered


def _block(rows) -> dict:
    return {"returned": len(rows), "items": rows}


def listing(side: str = "both", top: int = 35, as_of: str | None = None,
            with_names: bool = True, limit: int = 0) -> str:
    """返回名单：buy=概率最高，avoid=概率最低，all=全量，both=涨/跌各 top 只。"""
    side = SIDE_ALIASES.get(side, side)
    if side not in SIDES:
        return _fail("INVALID_ARGUMENT", f"side 仅支持 {'、'.join(SIDES)}（另接受 top/bottom 别名）")
    try:
        top, limit, as_of = _int(top, "top", 1, MAX_TOP), _int(limit, "limit", 0, MAX_LIMIT), _date(as_of, "as_of")
    except ValueError as exc:
        return _fail("INVALID_ARGUMENT", str(exc))
    root = relative_dir()
    lists, predictions = _files(LIST_PATTERN), _files(PREDICTION_PATTERN)
    if as_of:
        if not predictions:
            return _fail("ARTIFACT_MISSING", "没有预测缓存，无法按 as_of 回看", dir=str(root))
        source, rows = predictions[-1], _week_rows(predictions[-1], as_of)
    elif lists:
        source, rows = lists[-1], _list_rows(lists[-1])
    elif predictions:
        source, rows = predictions[-1], _week_rows(predictions[-1], None)
    else:
        return _fail("ARTIFACT_MISSING", "没有名单也没有预测缓存，先跑 stage=list", dir=str(root))
    if not rows:
        return _fail("ARTIFACT_MISSING", "没有可用记录", file=str(source), as_of=as_of)
    ordered = _ranked(rows, with_names)
    response = {"ok": True, "dataset": "big", "source": source.name, "dir": str(root),
                "side": side, "as_of": as_of or max(row["date"] for row in ordered),
                "total": len(ordered), "top": top}
    if side == "both":
        response["buy"] = _block(ordered[:top])
        response["avoid"] = _block(list(reversed(ordered[-top:])))
    elif side == "buy":
        response.update(_block(ordered[:top]))
    elif side == "avoid":
        response.update(_block(list(reversed(ordered[-top:]))))
    else:
        response.update(_block(ordered[:limit or MAX_LIMIT]))
    return json.dumps(response, ensure_ascii=False)


def run_stage(stage: str, timeout_seconds: int = 1800, args: list[str] | None = None) -> str:
    """按白名单执行脚本；predict 重建缓存与预测，list 训练最终模型并写名单。会写盘。"""
    if stage not in STAGES:
        return _fail("INVALID_ARGUMENT", f"stage 仅支持 {sorted(STAGES)}")
    try:
        timeout_seconds = _int(timeout_seconds, "timeout_seconds", 1, 3600)
    except ValueError as exc:
        return _fail("INVALID_ARGUMENT", str(exc))
    extra = []
    for token in args or []:
        if not isinstance(token, str) or len(token) > 200 or "\n" in token:
            return _fail("INVALID_ARGUMENT", "args 只接受不超过 200 字符的单行字符串")
        extra.append(token)
    root = relative_dir()
    script = root / STAGES[stage]
    if not script.exists():
        return _fail("SCRIPT_MISSING", "脚本不存在", dir=str(root), script=str(script))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    started = time.monotonic()
    try:
        done = subprocess.run([sys.executable, str(script)] + extra, cwd=str(root), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds, env=env)
    except subprocess.TimeoutExpired:
        return _fail("STAGE_TIMEOUT", f"{stage} 超过 {timeout_seconds} 秒未结束", script=str(script))
    return json.dumps({"ok": done.returncode == 0, "stage": stage, "script": str(script),
                       "exit_code": done.returncode, "seconds": round(time.monotonic() - started, 1),
                       "output_tail": (done.stdout or "").strip().splitlines()[-30:],
                       "stderr_tail": (done.stderr or "").strip().splitlines()[-20:]},
                      ensure_ascii=False)
