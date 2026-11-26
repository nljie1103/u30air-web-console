"""Windows launcher for the Vue 3 desktop interface.

The browser chrome is owned by Microsoft Edge (native app window), not the
pywebview/pythonnet WinForms host. Interactive dragging therefore does not
enter a Python/.NET managed window message loop.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from bridge import DesktopBridge
from browser_lifecycle import (
    visible_edge_windows, wait_for_app_window, keep_server_until_window_closed
)
from edge_host import start_edge_server
from local_server import start_frontend_server

APP_VERSION = "2.4.3"


def frontend_file() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "installer" / "frontend" / "dist" / "index.html"


def edge_executable() -> Path:
    """Locate real Microsoft Edge rather than a general file-association URI."""
    candidates: list[Path] = []
    if os.environ.get("AWD_EDGE_EXE"):
        candidates.append(Path(os.environ["AWD_EDGE_EXE"]))
    for env in ("ProgramFiles(x86)", "PROGRAMFILES", "ProgramFiles", "LOCALAPPDATA"):
        home = os.environ.get(env)
        if home:
            candidates.append(Path(home) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    if os.name == "nt":
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as key:
                        value = winreg.QueryValueEx(key, "")[0]
                    candidates.append(Path(value))
                except OSError:
                    pass
        except ImportError:
            pass
    found = shutil.which("msedge")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file() and candidate.name.lower() == "msedge.exe":
            return candidate.resolve()
    raise FileNotFoundError(
        "没有检测到 Microsoft Edge 浏览器。请安装或修复 Edge 后重试。"
        "Windows WebView2 Runtime 并不等于完整的 Edge 浏览器。"
    )


def self_test(frontend_dir: Path) -> None:
    bridge = DesktopBridge()
    if bridge.environment()["version"] != APP_VERSION:
        raise RuntimeError("Python bridge version mismatch")
    server, url = start_frontend_server(frontend_dir)
    try:
        with urlopen(url, timeout=3) as response:
            html = response.read(100_000).decode("utf-8")
            if response.status != 200 or 'id="app"' not in html or "/src/main.ts" in html:
                raise RuntimeError("Production Vue index.html was not served")
        from html.parser import HTMLParser

        class ScriptFinder(HTMLParser):
            def __init__(self):
                super().__init__()
                self.assets: list[str] = []
            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if value and key in ("src", "href") and "assets/" in value:
                        self.assets.append(value.lstrip("./"))

        finder = ScriptFinder()
        finder.feed(html)
        if not finder.assets:
            raise RuntimeError("Vite production assets are missing")
        base = url.rsplit("/", 1)[0] + "/"
        for asset in finder.assets:
            with urlopen(base + asset, timeout=3) as response:
                if response.status != 200 or len(response.read(2_000_000)) < 8:
                    raise RuntimeError("Failed to serve Vue asset: " + asset)
        print(f"Android Web Desktop Manager v{APP_VERSION}: Vue assets and Python bridge OK")
    finally:
        server.shutdown()
        server.server_close()


def _move_browser_window(edge_pid: int) -> None:
    """Windows smoke: reposition a real Edge app window and verify it survived."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = (
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    )
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.IsWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = (
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.c_void_p,
    )
    user32.mouse_event.restype = None
    hwnds: list[int] = []

    def inspect(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        if "Android Web Desktop" in buff.value:
            hwnds.append(hwnd)
        return True

    deadline = time.monotonic() + 16
    while time.monotonic() < deadline:
        hwnds.clear()
        user32.EnumWindows(callback(inspect), 0)
        if hwnds:
            break
        time.sleep(0.35)
    if not hwnds:
        raise RuntimeError("Edge 应用窗口未能在 16 秒内显示")
    hwnd = hwnds[0]
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("无法读取 Edge 窗口位置")
    left, top = rect.left, rect.top
    width, height = rect.right - rect.left, rect.bottom - rect.top

    # First move through normal top-level Windows APIs.
    flags = 0x0004 | 0x0010  # SWP_NOZORDER | SWP_NOACTIVATE
    for dx, dy in ((32, 24), (74, 50), (0, 0)):
        if not user32.SetWindowPos(hwnd, None, left + dx, top + dy, width, height, flags):
            raise RuntimeError("Edge 窗口移动失败")
        time.sleep(0.20)
    if not user32.IsWindow(hwnd):
        raise RuntimeError("移动后 Edge 窗口消失")

    # Also exercise actual title-bar mouse drag. During an interactive drag
    # Windows enters its native moving message loop, the user-reported hang.
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    user32.SetCursorPos(left + 280, top + 17)
    time.sleep(0.10)
    user32.mouse_event(0x0002, 0, 0, 0, None)  # LEFTDOWN
    try:
        for step in range(1, 7):
            user32.SetCursorPos(left + 280 + 12 * step, top + 17 + 5 * step)
            time.sleep(0.08)
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP
    time.sleep(0.30)
    if not user32.IsWindow(hwnd):
        raise RuntimeError("拖动标题栏后 Edge 窗口消失")


def _startup_event(home: Path, message: str) -> None:
    """Best-effort diagnostic log; never records ADB credentials or tokens."""
    try:
        from datetime import datetime
        home.mkdir(parents=True, exist_ok=True)
        logfile = home / "manager-startup.log"
        if logfile.exists() and logfile.stat().st_size > 180_000:
            logfile.replace(home / "manager-startup.previous.log")
        with logfile.open("a", encoding="utf-8") as stream:
            stream.write(datetime.now().isoformat(timespec="seconds") +
                         " " + message + "\n")
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Android Web Desktop Manager")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-smoke-test", action="store_true")
    parser.add_argument("--lifecycle-smoke-test", action="store_true")
    args = parser.parse_args()

    index = frontend_file()
    if not index.is_file():
        raise SystemExit("Vue frontend build missing. Run npm run build in installer/frontend.")

    if args.self_test:
        self_test(index.parent)
        return

    browser = edge_executable()
    bridge = DesktopBridge()
    app_data = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "AndroidWebDesktop"
    _startup_event(app_data, "Starting Windows manager " + APP_VERSION)
    server, url = start_edge_server(index.parent, bridge)
    temp_root = app_data / "edge-sessions"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        # The HTTP server must be serving the Vue page before Edge is
        # launched. On failure, do not leave Edge on its built-in error page.
        with urlopen(url, timeout=4) as response:
            if response.status != 200 or b'id="app"' not in response.read(100_000):
                raise RuntimeError("Windows 管理界面本机服务启动未就绪")
        _startup_event(app_data, "Loopback server ready on localhost")
        old_edge_windows = visible_edge_windows()
        with tempfile.TemporaryDirectory(prefix="edge-", dir=str(temp_root), ignore_cleanup_errors=True) as profile:
            command = [
                str(browser), f"--app={url}", f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check",
                "--disable-background-mode", "--disable-extensions",
                "--window-size=1360,860",
            ]
            if args.gui_smoke_test or args.lifecycle_smoke_test:
                command.extend(("--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"))
            process = subprocess.Popen(command)
            _startup_event(app_data, f"Edge app bootstrap spawned (PID {process.pid})")
            if args.lifecycle_smoke_test and os.environ.get("AWD_SMOKE_INFO"):
                Path(os.environ["AWD_SMOKE_INFO"]).write_text(
                    json.dumps({"url": url, "profile": profile, "pid": process.pid}),
                    encoding="utf-8",
                )
            try:
                if args.gui_smoke_test:
                    # Expose the ephemeral debugging port to the CI script only.
                    if os.environ.get("AWD_SMOKE_INFO"):
                        Path(os.environ["AWD_SMOKE_INFO"]).write_text(
                            json.dumps({"url": url, "profile": profile, "pid": process.pid}),
                            encoding="utf-8",
                        )
                    _move_browser_window(process.pid)
                    if process.poll() is not None:
                        raise RuntimeError("移动窗口时浏览器意外退出")
                    if os.environ.get("AWD_SMOKE_INFO"):
                        metadata = Path(os.environ["AWD_SMOKE_INFO"])
                        temporary = metadata.with_suffix(".tmp")
                        temporary.write_text(
                            json.dumps({"url": url, "profile": profile, "pid": process.pid,
                                        "drag_complete": True}),
                            encoding="utf-8",
                        )
                        temporary.replace(metadata)
                    hold = min(max(float(os.environ.get("AWD_SMOKE_HOLD", "1")), 0), 40)
                    done_file = os.environ.get("AWD_SMOKE_DONE")
                    until = time.monotonic() + hold
                    while time.monotonic() < until:
                        if done_file and Path(done_file).is_file():
                            break
                        time.sleep(0.15)
                else:
                    # Edge can hand off the app window to a new process and
                    # exit its initial launcher. process.wait() is NOT a
                    # reliable indicator that the browser window has closed.
                    hwnd = wait_for_app_window(process, old_edge_windows)
                    _startup_event(app_data, f"Edge app window opened (HWND {hwnd})")
                    if args.lifecycle_smoke_test and os.environ.get("AWD_SMOKE_INFO"):
                        metadata = Path(os.environ["AWD_SMOKE_INFO"])
                        staging = metadata.with_suffix(".tmp")
                        staging.write_text(
                            json.dumps({"url": url, "profile": profile, "pid": process.pid,
                                        "window_ready": True}), encoding="utf-8",
                        )
                        staging.replace(metadata)
                    if process.poll() is not None:
                        _startup_event(app_data,
                                       "Edge launcher exited but window remains; server retained")
                    keep_server_until_window_closed(hwnd)
                    _startup_event(app_data, "Edge app window closed")
            finally:
                if args.gui_smoke_test and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, str(exc), "Android Web Desktop 启动失败", 0x10
            )
        raise
