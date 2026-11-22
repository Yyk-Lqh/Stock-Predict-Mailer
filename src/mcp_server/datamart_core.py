"""数据面两套产物的共享读取层：small=单池，big=沪深300∪中证A500。

只读工具不建目录、不联网；run_stage 才会写盘并启动子进程。
"""
import csv
import json
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def _src_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    env: str
    default_dir: Path
    models: tuple[str, ...]
    stages: dict[str, str]


ARTIFACTS = {
    "universe": ("stock_data117.csv", "股票池：代码、名称、现价、成交量"),
    "history_raw": ("all_stock_history119.csv", "原始日线（带 sh./sz. 前缀）"),
    "history_cleaned": ("all_stock_history120_cleaned.csv", "清洗后日线"),
    "features": ("all_stock_history120_deep_cleaned.csv", "量价特征"),
    "fundamental_raw": ("fundamental_quarterly_new.csv", "原始季度基本面"),
    "fundamental_cleaned": ("fundamental_quarterly_cleaned.csv", "清洗后季度基本面"),
}

DATASETS = {
    "small": Dataset(
        key="small",
        label="数据面（单池，东方财富 bk0500 约 117 只）",
        env="STOCK_PREDICT_MAILER_DATAMART_SMALL_DIR",
        default_dir=_src_root() / "数据面",
        models=("random_forest_monthly_candidate.pkl", "random_forest_monthly.pkl"),
        stages={
            "universe": "fetch_stock_universe.py",
            "history": "fetch_stock_history.py",
            "clean_history": "clean_stock_history.py",
            "features": "build_price_volume_features.py",
            "clean_fundamental": "clean_quarterly_fundamentals.py",
            "validate_fundamental": "validate_quarterly_fundamentals.py",
            "rank_ic": "evaluate_factor_rank_ic.py",
            "train": "train_random_forest.py",
        },
    ),
    "big": Dataset(
        key="big",
        label="数据面（大股池，沪深300 ∪ 中证A500）",
        env="STOCK_PREDICT_MAILER_DATAMART_BIG_DIR",
        default_dir=_src_root() / "数据面（大股池）",
        models=("random_forest_modle.pkl",),
        stages={
            "universe": "拉取指数成分.py",
            "history": "历史股票数据爬虫_步骤(2).py",
            "clean_history": "处理_步骤(3).py",
            "features": "特征工程2_步骤(4).py",
            "fundamental": "我已无力2，要更新数据面就用这个_步骤(5).py",
            "clean_fundamental": "数据面清洗版_步骤(6).py",
            "validate_fundamental": "校验_步骤(7).py",
            "factor_test": "因子试探_步骤(8).py",
            "rank_ic": "IC.py",
            "train": "模型落盘.py",
        },
    ),
}

SERIES_ARTIFACTS = ("history_cleaned", "features")
MAX_LIMIT = 2000
DEFAULT_BARS_START = "2009-10-23"
DEFAULT_BARS_END = "2026-10-23"


def data_dir(dataset: Dataset) -> Path:
    configured = os.environ.get(dataset.env)
    return Path(configured).expanduser().resolve() if configured else dataset.default_dir


def _fail(code, message, **details):
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


def _num(text):
    if text is None:
        return None
    text = text.strip()
    if text in ("", "-", "--"):
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return round(float(text), 6)
        except ValueError:
            return text


def _bare(code):
    return code.strip().removeprefix("sh.").removeprefix("sz.").removeprefix("SH.").removeprefix("SZ.")


def _rows(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def status(dataset: Dataset, count_rows: bool = False) -> str:
    """列出产物路径、大小、修改时间与列名；count_rows=True 时逐个数行（大文件偏慢）。"""
    root = data_dir(dataset)
    items = []
    for name, (filename, description) in ARTIFACTS.items():
        path = root / filename
        entry = {"name": name, "file": str(path), "exists": path.exists(), "description": description}
        if path.exists():
            stat = path.stat()
            entry["size_bytes"] = stat.st_size
            entry["modified"] = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                entry["columns"] = next(reader, [])
                if count_rows:
                    entry["rows"] = sum(1 for _ in reader)
        items.append(entry)
    models = [{"file": str(root / name), "exists": (root / name).exists()} for name in dataset.models]
    return json.dumps({"ok": True, "dataset": dataset.key, "label": dataset.label,
                       "dir": str(root), "artifacts": items, "models": models}, ensure_ascii=False)


def list_universe(dataset: Dataset, keyword: str = "", prefix: str = "", limit: int = 50) -> str:
    """按名称关键词或代码前缀查询股票池。"""
    try:
        limit = _int(limit, "limit", 1, MAX_LIMIT)
    except ValueError as exc:
        return _fail("INVALID_ARGUMENT", str(exc))
    path = data_dir(dataset) / ARTIFACTS["universe"][0]
    if not path.exists():
        return _fail("ARTIFACT_MISSING", "股票池文件不存在", dataset=dataset.key, file=str(path))
    items, total = [], 0
    for row in _rows(path):
        code, name = (row.get("股票代码") or "").strip(), (row.get("股票名称") or "").strip()
        if prefix and not code.startswith(prefix):
            continue
        if keyword and keyword not in name and keyword not in code:
            continue
        total += 1
        if len(items) < limit:
            items.append({"code": code, "name": name,
                          **{k: _num(v) for k, v in row.items() if k not in ("股票代码", "股票名称")}})
    return json.dumps({"ok": True, "dataset": dataset.key, "total": total,
                       "returned": len(items), "items": items}, ensure_ascii=False)


def read_bars(dataset: Dataset, code: str, artifact: str = "features",
              start: str | None = None, end: str | None = None, limit: int = 120) -> str:
    """读取单只证券的日线或特征序列；不给区间时返回最近 limit 条。"""
    try:
        limit, start, end = _int(limit, "limit", 1, MAX_LIMIT), _date(start, "start"), _date(end, "end")
    except ValueError as exc:
        return _fail("INVALID_ARGUMENT", str(exc))
    if artifact not in SERIES_ARTIFACTS:
        return _fail("INVALID_ARGUMENT", f"artifact 仅支持 {'、'.join(SERIES_ARTIFACTS)}")
    if not isinstance(code, str) or not code.strip():
        return _fail("INVALID_ARGUMENT", "code 必填")
    path = data_dir(dataset) / ARTIFACTS[artifact][0]
    if not path.exists():
        return _fail("ARTIFACT_MISSING", "数据文件不存在", dataset=dataset.key, file=str(path))
    wanted, rows, matched, latest = _bare(code), deque(maxlen=limit), 0, None
    for row in _rows(path):
        if _bare(row.get("股票代码") or "") != wanted:
            continue
        day = (row.get("日期") or "").strip()
        if (start and day < start) or (end and day > end):
            continue
        matched += 1
        latest = day
        rows.append({k: (v if k in ("日期", "股票代码") else _num(v)) for k, v in row.items()})
    return json.dumps({"ok": True, "dataset": dataset.key, "code": wanted, "artifact": artifact,
                       "matched": matched, "latest": latest, "rows": list(rows)}, ensure_ascii=False)


def latest_cross_section(dataset: Dataset, artifact: str = "features", top: int = 0) -> str:
    """取最近交易日的横截面（每只证券一行）；top>0 时只返回按代码排序的前 top 只。"""
    try:
        top = _int(top, "top", 0, MAX_LIMIT)
    except ValueError as exc:
        return _fail("INVALID_ARGUMENT", str(exc))
    if artifact not in SERIES_ARTIFACTS:
        return _fail("INVALID_ARGUMENT", f"artifact 仅支持 {'、'.join(SERIES_ARTIFACTS)}")
    path = data_dir(dataset) / ARTIFACTS[artifact][0]
    if not path.exists():
        return _fail("ARTIFACT_MISSING", "数据文件不存在", dataset=dataset.key, file=str(path))
    latest, as_of = {}, ""
    for row in _rows(path):
        code, day = _bare(row.get("股票代码") or ""), (row.get("日期") or "").strip()
        if not code or not day:
            continue
        as_of = max(as_of, day)
        if code not in latest or day > latest[code][0]:
            latest[code] = (day, row)
    ordered = [row for _, row in sorted(latest.items())]
    items = [{k: (v if k in ("日期", "股票代码") else _num(v)) for k, v in row.items()} for row in ordered]
    if top:
        items = items[:top]
    return json.dumps({"ok": True, "dataset": dataset.key, "as_of": as_of, "artifact": artifact,
                       "total": len(ordered), "returned": len(items), "items": items}, ensure_ascii=False)


def model_info(dataset: Dataset) -> str:
    """读取模型包里的训练元数据（不含模型对象）。pickle 会执行反序列化，只读可信来源。"""
    root = data_dir(dataset)
    path = next((root / name for name in dataset.models if (root / name).exists()), None)
    if path is None:
        return _fail("ARTIFACT_MISSING", "模型文件不存在，先跑 train 阶段", dataset=dataset.key,
                     expected=[str(root / name) for name in dataset.models])
    try:
        import pickle
        with path.open("rb") as stream:
            bundle = pickle.load(stream)
    except ModuleNotFoundError as exc:
        return _fail("DEPENDENCY_MISSING", str(exc), hint="uv sync --extra datamart")
    except Exception as exc:
        return _fail("MODEL_UNREADABLE", str(exc))
    if not isinstance(bundle, dict):
        return _fail("MODEL_UNREADABLE", "模型包不是字典结构")
    meta = {k: v for k, v in bundle.items() if k != "model"}
    return json.dumps({"ok": True, "dataset": dataset.key, "file": str(path), "meta": meta},
                      ensure_ascii=False, default=str)


def run_stage(dataset: Dataset, stage: str, timeout_seconds: int = 900,
              args: list[str] | None = None,
              bars_start: str | None = None, bars_end: str | None = None) -> str:
    """按白名单执行脚本；bars_start/bars_end 仅对 history 阶段有意义，通过环境变量注入。"""
    if stage not in dataset.stages:
        return _fail("INVALID_ARGUMENT", f"stage 仅支持 {sorted(dataset.stages)}", dataset=dataset.key)
    try:
        timeout_seconds = _int(timeout_seconds, "timeout_seconds", 1, 3600)
        start_value = _date(bars_start, "bars_start") or os.environ.get(
            "STOCK_PREDICT_MAILER_BARS_START", DEFAULT_BARS_START)
        end_value = _date(bars_end, "bars_end") or os.environ.get(
            "STOCK_PREDICT_MAILER_BARS_END", DEFAULT_BARS_END)
    except ValueError as exc:
        return _fail("INVALID_ARGUMENT", str(exc))
    if start_value > end_value:
        return _fail("INVALID_ARGUMENT", "bars_start 不能晚于 bars_end",
                     bars_start=start_value, bars_end=end_value)
    extra = []
    for token in args or []:
        if not isinstance(token, str) or len(token) > 200 or "\n" in token:
            return _fail("INVALID_ARGUMENT", "args 只接受不超过 200 字符的单行字符串")
        extra.append(token)
    root = data_dir(dataset)
    script = root / dataset.stages[stage]
    if not script.exists():
        return _fail("SCRIPT_MISSING", "脚本不存在", dataset=dataset.key, script=str(script))
    root.mkdir(parents=True, exist_ok=True)
    (_src_root() / "sessions").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["STOCK_PREDICT_MAILER_BARS_START"] = start_value
    env["STOCK_PREDICT_MAILER_BARS_END"] = end_value
    started = time.monotonic()
    try:
        done = subprocess.run([sys.executable, str(script)] + extra, cwd=str(root), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds,
                              env=env)
    except subprocess.TimeoutExpired:
        return _fail("STAGE_TIMEOUT", f"{stage} 超过 {timeout_seconds} 秒未结束", dataset=dataset.key)
    return json.dumps({"ok": done.returncode == 0, "dataset": dataset.key, "stage": stage,
                       "exit_code": done.returncode, "seconds": round(time.monotonic() - started, 1),
                       "bars_start": start_value, "bars_end": end_value,
                       "output_tail": (done.stdout or "").strip().splitlines()[-30:],
                       "stderr_tail": (done.stderr or "").strip().splitlines()[-20:]},
                      ensure_ascii=False)
