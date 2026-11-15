"""Explicit fixed-component launches and instance-fenced cooperative stopping."""
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from ..agent_service.contracts import ServiceError
from ..core import Config
from ..delivery import process_lock
from ..naming import env
from .components import configuration, directory, request_stop, status
from .probes import ProbeError, contained, port_state


def selected_root(cfg, component, crawler_workspace=None):
    if component == "crawler_worker":
        if crawler_workspace is None:
            from mcp_server.paths import workspace
            crawler_workspace = workspace()
        return Path(crawler_workspace).expanduser().resolve()
    return Path(cfg["workspace"]).resolve()


def start(cfg, config_path, component, *, crawler_workspace=None, port=8767, poll=2, timeout=15):
    root = selected_root(cfg, component, crawler_workspace)
    folder = directory(root, component)
    mode = "production" if env("MASTER_KEY") else "development"
    desired = ({"port": port, "vault_mode": mode} if component == "console" else
               {"poll_seconds": poll, "once": False, **({"vault_mode": mode} if component == "knowledge_worker" else {})})
    try:
        desired = configuration(desired)
        if component == "console" and port == 0:
            raise ValueError()
        if component == "crawler_worker" and poll > 30:
            raise ValueError()
        if type(timeout) not in (int, float) or not 1 <= timeout <= 30:
            raise ValueError()
    except (TypeError, ValueError):
        raise ServiceError("INVALID_INPUT", "运行端口/轮询或启动等待时间无效") from None
    try:
        contained(root, folder / "launch")
    except ProbeError:
        raise ServiceError("RUNTIME_PATH", "启动锁目录不可访问或越界") from None
    try:
        with process_lock(Config(folder / "launch")):
            view = status(root, component)
            if view["state"] == "verified":
                if view["configuration"] != desired or view["phase"] not in ("running", "idle", "busy"):
                    raise ServiceError("RUNTIME_CONFIG_CONFLICT", "现有实例参数不同或尚在切换阶段，请先核对状态")
                return dict(view, already_running=True)
            if view["lock"] == "busy" or view["state"] not in ("not_registered", "stopped", "failed", "dead"):
                raise ServiceError("RUNTIME_UNVERIFIED", "已有实例归属或运行状态不能确认，拒绝重复启动")
            if component == "console" and port_state(port) != "available":
                raise ServiceError("RUNTIME_PORT_UNAVAILABLE", "新控制台端口不可用；不接管原进程或自动换端口")
            instance = uuid.uuid4().hex
            command = [sys.executable, "-m", "stock_predict_mailer.operations.launcher", "--config", str(Path(config_path).resolve()),
                       "--workspace", str(Path(cfg["workspace"]).resolve()), "--root", str(root), "--component", component,
                       "--instance", instance, "--port", str(port), "--poll", str(poll)]
            with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as output:
                proc = subprocess.Popen(command, stdin=stdin, stdout=output, stderr=output, close_fds=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, start_new_session=os.name != "nt")
            threading.Thread(target=proc.wait, daemon=True, name="runtime-child-reaper").start()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                view = status(root, component)
                if view.get("instance") == instance:
                    if view["state"] == "verified" and view["phase"] in ("running", "idle", "busy"):
                        return dict(view, already_running=False)
                    if view["state"] in ("failed", "stopped", "dead"):
                        raise ServiceError("RUNTIME_START_FAILED", "组件启动失败或提前退出，请查看生命周期日志或前台结构化错误")
                if proc.poll() is not None:
                    raise ServiceError("RUNTIME_START_FAILED", "组件未完成启动登记，请检查配置并查询日志")
                time.sleep(.05)
            if view.get("instance") == instance and view["ownership"] == "verified":
                request_stop(root, component, instance)
            raise ServiceError("RUNTIME_START_TIMEOUT", "启动未能确认；已登记实例会收到协作停止请求，请查询状态，不自动杀进程")
    except RuntimeError:
        raise ServiceError("RUNTIME_BUSY", "另一个启动操作正在执行") from None


def stop(root, component, instance, wait=10):
    if type(wait) not in (int, float) or not 0 <= wait <= 30:
        raise ServiceError("INVALID_INPUT", "停止等待时间须为 0 至 30 秒")
    result = request_stop(root, component, instance)
    if wait == 0:
        return result
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        view = status(root, component)
        if view.get("instance") != instance:
            return dict(result, state="instance_changed")
        if view["state"] in ("stopped", "failed", "dead"):
            return view
        time.sleep(.1)
    return dict(result, state="stopping", timed_out=True)
