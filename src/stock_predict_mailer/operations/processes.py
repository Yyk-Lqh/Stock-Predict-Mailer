"""Read-only process creation identity, never process enumeration or signalling."""
import hashlib
import os
import socket
import sys
from pathlib import Path


def host_id():
    return hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()


def birth(pid):
    if type(pid) is not int or not 0 < pid < 2**32:
        return "unknown", None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4)
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ("dead", None) if ctypes.get_last_error() == 87 else ("unknown", None)
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return "unknown", None
            if code.value != 259:
                return "dead", None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                return "unknown", None
            return "alive", "windows:" + str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        try:
            raw = (Path("/proc") / str(pid) / "stat").read_text()[:8192]
            fields = raw.rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                return "dead", None
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            return "alive", "linux:" + boot + ":" + fields[19]
        except FileNotFoundError:
            return "dead", None
        except (OSError, IndexError):
            return "unknown", None
    return "unknown", None
