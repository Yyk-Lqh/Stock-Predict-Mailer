"""数据面 MCP：一个服务，dataset 参数切换 small（单池）/ big（大股池）。"""
import argparse
import csv
import json

from mcp.server.fastmcp import FastMCP

from mcp_server import datamart_core as core
from mcp_server import relative_core as relative

AUTO_ORDER = ("big", "small")


def _targets(dataset: str):
    if dataset in core.DATASETS:
        return [core.DATASETS[dataset]]
    if dataset == "auto":
        return [core.DATASETS[key] for key in AUTO_ORDER]
    return None


def _invalid(dataset: str) -> str:
    return json.dumps({"ok": False, "error": {"code": "INVALID_ARGUMENT",
                       "message": f"dataset 仅支持 auto、{'、'.join(sorted(core.DATASETS))}"}},
                      ensure_ascii=False)


def _first_ok(dataset: str, call) -> str:
    targets = _targets(dataset)
    if targets is None:
        return _invalid(dataset)
    attempts = []
    for target in targets:
        raw = call(target)
        try:
            payload = json.loads(raw)
        except ValueError:
            return raw
        if payload.get("ok"):
            return raw
        attempts.append({"dataset": target.key, "error": payload.get("error"),
                         "details": payload.get("details")})
    return json.dumps({"ok": False, "error": {"code": "ARTIFACT_MISSING",
                       "message": "两套数据面都没有可用产物"}, "attempts": attempts},
                      ensure_ascii=False)


def build(port: int = 8765) -> FastMCP:
    server = FastMCP("stock-datamart", host="127.0.0.1", port=port, log_level="ERROR")

    @server.tool(description="列出数据面产物：存在性、大小、列名。dataset=auto 时 small/big 都报。")
    def datamart_status(dataset: str = "auto", count_rows: bool = False) -> str:
        targets = _targets(dataset)
        if targets is None:
            return _invalid(dataset)
        return json.dumps({"ok": True,
                           "datasets": [json.loads(core.status(t, count_rows)) for t in targets]},
                          ensure_ascii=False)

    @server.tool(description="查股票池：关键词或代码前缀。dataset=auto 时先大池再小池。")
    def datamart_universe(keyword: str = "", prefix: str = "", limit: int = 50,
                          dataset: str = "auto") -> str:
        return _first_ok(dataset, lambda d: core.list_universe(d, keyword, prefix, limit))

    @server.tool(description="读单只证券的日线或特征序列。dataset=auto 时先大池再小池。")
    def datamart_bars(code: str, artifact: str = "features", start: str | None = None,
                      end: str | None = None, limit: int = 120, dataset: str = "auto") -> str:
        return _first_ok(dataset, lambda d: core.read_bars(d, code, artifact, start, end, limit))

    @server.tool(description="最近交易日的截面（每只证券一行）。dataset=auto 时先大池再小池。")
    def datamart_cross_section(artifact: str = "features", top: int = 0, dataset: str = "auto") -> str:
        return _first_ok(dataset, lambda d: core.latest_cross_section(d, artifact, top))

    @server.tool(description="读模型包训练元数据（不含模型对象）。两边模型文件名不同也能自动找。")
    def datamart_model(dataset: str = "auto") -> str:
        return _first_ok(dataset, core.model_info)

    @server.tool(description="对比两套数据面的池子规模与重叠，只读股票池，不做全量扫描。")
    def datamart_compare() -> str:
        pools = {}
        for key in ("small", "big"):
            path = core.data_dir(core.DATASETS[key]) / core.ARTIFACTS["universe"][0]
            codes = set()
            if path.exists():
                with path.open("r", encoding="utf-8-sig", newline="") as stream:
                    codes = {(row.get("股票代码") or "").strip() for row in csv.DictReader(stream)
                             if (row.get("股票代码") or "").strip()}
            pools[key] = codes
        small, big = pools["small"], pools["big"]
        return json.dumps({"ok": True,
                           "small": {"stocks": len(small),
                                     "dir": str(core.data_dir(core.DATASETS["small"]))},
                           "big": {"stocks": len(big),
                                   "dir": str(core.data_dir(core.DATASETS["big"]))},
                           "shared": len(big & small),
                           "only_in_big": len(big - small),
                           "only_in_small": len(small - big),
                           "sample_only_in_big": sorted(big - small)[:20]},
                          ensure_ascii=False)

    @server.tool(description="按白名单执行脚本（会写盘、联网）。dataset 必须显式给 small 或 big；"
                             "history 阶段可用 bars_start/bars_end 指定日线区间，默认 2009-10-23 ~ 2026-10-23。")
    def datamart_run(dataset: str, stage: str, timeout_seconds: int = 900,
                     args: list[str] | None = None,
                     bars_start: str | None = None, bars_end: str | None = None) -> str:
        if dataset not in core.DATASETS:
            return json.dumps({"ok": False, "error": {"code": "INVALID_ARGUMENT",
                               "message": "run 必须显式指定 dataset：small 或 big"}}, ensure_ascii=False)
        return core.run_stage(core.DATASETS[dataset], stage, timeout_seconds, args, bars_start, bars_end)

    @server.tool(description="相对市场跌涨（周频相对强弱）：查看周度缓存、预测、名单与模型文件的状态，"
                             "并提示名单是否落后于预测。只读，不建目录不联网。")
    def datamart_relative_status() -> str:
        return relative.status()

    @server.tool(description="相对市场跌涨名单：buy=概率最高，avoid=概率最低，all=全量，both=涨/跌各 top 只（默认 35）。"
                             "as_of=YYYY-MM-DD 时从预测缓存回看该日或更早的最近一周，否则读最新 名单_*.csv。"
                             "with_names=True 时用股票池补股票名称。")
    def datamart_relative_list(side: str = "both", top: int = 35, as_of: str | None = None,
                               with_names: bool = True, limit: int = 0) -> str:
        return relative.listing(side, top, as_of, with_names, limit)

    @server.tool(description="相对市场跌涨：按白名单跑脚本（会写盘并训练，较慢）。"
                             "predict=周频跌涨模型.py 重建周度缓存与预测，list=出名单.py 训练最终模型并写名单。")
    def datamart_relative_run(stage: str, timeout_seconds: int = 1800,
                              args: list[str] | None = None) -> str:
        return relative.run_stage(stage, timeout_seconds, args)

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="数据面 MCP（一个服务，dataset 切换 small/big）")
    parser.add_argument("--http", action="store_true", help="使用 Streamable HTTP；默认 stdio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    build(args.port).run(transport="streamable-http" if args.http else "stdio")


if __name__ == "__main__":
    raise SystemExit(main())
