"""Track the *window* rather than only the initial Edge launcher process.

Edge can delegate a --app launch to another browser process and let the
short-lived launcher exit. Waiting on that first PID then stops our Python
loopback server even though the app window is still open. Tracking the native
top-level window prevents a permanent ERR_CONNECTION_REFUSED page.
"""
from __future__ import annotations

import os
import time
from typing import Callable


def visible_edge_windows() -> set[int]:
    """Enumerate top-level visible Microsoft Edge windows on Windows only."""
    if os.name != "nt":
        return set()

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    result: set[int] = set()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def inspect(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return True
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                if os.path.basename(buf.value).lower() == "msedge.exe":
                    result.add(int(hwnd))
        finally:
            kernel32.CloseHandle(handle)
        return True

    callback = callback_type(inspect)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows(callback, 0)
    return result


def wait_for_app_window(
    process,
    old_windows: set[int],
    *,
    enumerate_windows: Callable[[], set[int]] = visible_edge_windows,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    startup_timeout: float = 23.0,
) -> int:
    """Find the newly opened Edge app HWND even if the launch PID already exited."""
    deadline = clock() + startup_timeout
    while clock() < deadline:
        found = enumerate_windows() - old_windows
        if found:
            # A fresh profile opens a single app window. In unusual cases,
            # pick the newest HWND, not an existing unrelated Edge window.
            return max(found)
        sleep(0.22)
    if process.poll() is not None:
        raise RuntimeError(
            "Edge 启动进程已经结束，但未发现应用窗口。请检查 Edge 是否被安全软件或策略拦截。"
        )
    raise RuntimeError("Edge 启动超时：没有检测到应用窗口")


def keep_server_until_window_closed(
    hwnd: int,
    *,
    enumerate_windows: Callable[[], set[int]] = visible_edge_windows,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Preserve the Python service while Edge's native app window exists.

    Deliberately do not call process.wait() to decide the lifetime: on some
    Windows installations the Edge bootstrap PID exits while its UI survives.
    """
    missed = 0
    while True:
        if hwnd in enumerate_windows():
            missed = 0
        else:
            missed += 1
            if missed >= 4:
                return
        sleep(0.35)
