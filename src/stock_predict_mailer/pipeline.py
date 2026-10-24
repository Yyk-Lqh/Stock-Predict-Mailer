from __future__ import annotations

from .core import Config, connect, now, tracked_run
from .data import demo_csv, import_csv
from .delivery import enqueue, process_lock
from .report import build_report
from .research import experiment


def demo_run(cfg: Config, cutoff: str, recipient: str = "preview@example.invalid", trees: bool = False) -> dict:
    with process_lock(cfg):
        with connect(cfg) as con:
            # The OS lock proves no other managed pipeline is running.
            con.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE status='running' AND task='demo-run'", (now(),))
        with tracked_run(cfg, "demo-run"):
            manifest = import_csv(cfg, demo_csv(cfg.workspace / "demo.csv"), synthetic=True)
            result = experiment(cfg, manifest["snapshot_id"], cutoff, trees=trees)
            report = build_report(cfg, result["experiment_id"])
            message = enqueue(cfg, report["report_id"], recipient)
            return {"synthetic": True, "snapshot_id": manifest["snapshot_id"],
                    "experiment_id": result["experiment_id"], "report_id": report["report_id"],
                    "html": str(cfg.workspace / "reports" / report["report_id"] / "report.html"),
                    "outbox_id": message["id"], "email_status": message["status"],
                    "sent": False}
