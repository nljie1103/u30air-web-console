"""Qt 6 Windows shell for the original Vue 3 / shadcn-inspired UI.

Uses an embedded QtWebEngine view and a local, read-only Qt URL scheme:
- no Microsoft Edge dependency
- no 127.0.0.1 HTTP server or first-launch connection race
- native ADB work runs in a Qt thread pool, never in the UI thread
- only a fixed allowlist of Python bridge methods is exposed to the UI

This is intentionally a web-rendered interface inside Qt, not Qt Widgets.
The visual design matches v2.4.x while retaining the v2.5.x Python backend.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, QRunnable, QThreadPool, QByteArray, QBuffer, QIODevice, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
    QWebEngineUrlScheme, QWebEngineUrlSchemeHandler,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from bridge import DesktopBridge

SCHEME_NAME = b"awdapp"
SCHEME_HOST = "desktop"
SCHEME_URL = "awdapp://desktop/index.html"

# Must be called before QApplication is constructed.
_registered = False
def register_web_scheme():
    global _registered
    if _registered:
        return
    scheme = QWebEngineUrlScheme(SCHEME_NAME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.HostAndPort)
    scheme.setDefaultPort(443)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme |
        QWebEngineUrlScheme.Flag.LocalScheme |
        QWebEngineUrlScheme.Flag.CorsEnabled
    )
    QWebEngineUrlScheme.registerScheme(scheme)
    _registered = True


def frontend_root() -> Path:
    folder = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return folder / "frontend" / "dist"


# QtWebEngine profiles MUST outlive all pages which use them. Keeping a
# single profile owned by QApplication avoids profile/page use-after-free
# when windows are reopened, closed, or exercised repeatedly in unit tests.
_shared_profile = None
_shared_asset_handler = None


def shared_web_profile():
    global _shared_profile, _shared_asset_handler
    if _shared_profile is None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication must exist before constructing QtWebEngine")
        profile = QWebEngineProfile("AndroidWebDesktop", app)
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AndroidWebDesktop" / "qt-web-profile"
        local.mkdir(parents=True, exist_ok=True)
        profile.setPersistentStoragePath(str(local / "storage"))
        profile.setCachePath(str(local / "cache"))
        handler = StaticAssets(frontend_root(), profile)
        profile.installUrlSchemeHandler(SCHEME_NAME, handler)
        _shared_profile = profile
        _shared_asset_handler = handler
    return _shared_profile


class StaticAssets(QWebEngineUrlSchemeHandler):
    """Never expose files outside the bundled Vite dist directory."""
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root.resolve()

    def requestStarted(self, job):
        url = job.requestUrl()
        if os.environ.get("AWD_DEBUG_UI"):
            print("ASSET REQUEST", url.toString(), flush=True)
        if url.host().lower() != SCHEME_HOST:
            job.fail(job.Error.UrlInvalid)
            return
        relative = url.path().lstrip("/") or "index.html"
        target = (self.root / relative).resolve()
        if target != self.root and self.root not in target.parents:
            job.fail(job.Error.UrlInvalid)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file() or target.suffix.lower() not in {".html",".js",".css",".svg",".png",".webp",".ico",".woff",".woff2",".json"}:
            job.fail(job.Error.UrlNotFound)
            return
        try:
            raw = target.read_bytes()
        except OSError:
            job.fail(job.Error.RequestFailed)
            return
        data = QBuffer(job)
        data.setData(QByteArray(raw))
        data.open(QIODevice.OpenModeFlag.ReadOnly)
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix.lower() == ".js":
            mime = "text/javascript"
        job.reply(mime.encode("ascii"), data)


class BrowserPage(QWebEnginePage):
    """Never navigate the application surface to arbitrary remote origins."""
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        if os.environ.get("AWD_DEBUG_UI"):
            print(f"WEB CONSOLE [{level}] {source_id}:{line_number}: {message}", flush=True)
        return super().javaScriptConsoleMessage(level, message, line_number, source_id)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if is_main_frame and url.scheme() != SCHEME_NAME.decode():
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def createWindow(self, window_type):
        return None


ALLOWED_METHODS = frozenset({
    "environment", "list_devices", "device_info", "list_apps",
    "get_logs", "clear_logs", "connect", "set_adb_path",
    "install_official_adb", "check_release", "install_latest",
    "install_local", "read_auth", "configure_auth",
    "uninstall", "uninstall_app", "set_system_app",
    "reboot", "poweroff", "open_web",
})
UI_METHODS = frozenset({"choose_adb", "choose_local_zip"})


class JobSignals(QObject):
    success = Signal(str, object)
    failure = Signal(str, str)
    done = Signal(str)


class Job(QRunnable):
    def __init__(self, task_id: str, fn, args: list):
        super().__init__()
        self.task_id, self.fn, self.args = task_id, fn, args
        self.signals = JobSignals()

    def run(self):
        try:
            self.signals.success.emit(self.task_id, self.fn(*self.args))
        except Exception as exc:
            self.signals.failure.emit(self.task_id, str(exc))
        finally:
            self.signals.done.emit(self.task_id)


class QtBridge(QObject):
    completed = Signal(str, str)

    def __init__(self, bridge: DesktopBridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(5)
        self.jobs = {}

    @Slot(str, str, str)
    def request(self, task_id: str, method: str, args_json: str):
        """Strict RPC boundary: disallow arbitrary local Python execution."""
        if method in UI_METHODS:
            self._dialog_method(task_id, method)
            return
        if method not in ALLOWED_METHODS:
            self._reply(task_id, False, error="不允许访问的设备管理接口")
            return
        try:
            args = json.loads(args_json)
            if not isinstance(args, list) or len(args) > 6 or len(args_json) > 15000:
                raise ValueError("操作参数格式错误或过长")
            fn = getattr(self.bridge, method)
        except Exception as exc:
            self._reply(task_id, False, error=str(exc))
            return
        job = Job(task_id, fn, args)
        self.jobs[task_id] = job
        job.signals.success.connect(lambda identifier, val: self._reply(identifier, True, val))
        job.signals.failure.connect(lambda identifier, err: self._reply(identifier, False, error=err))
        job.signals.done.connect(lambda identifier: self.jobs.pop(identifier, None))
        self.pool.start(job)

    def _dialog_method(self, task_id, method):
        if method == "choose_adb":
            path, _ = QFileDialog.getOpenFileName(
                None, "选择 ADB 工具", "", "ADB 可执行文件 (adb.exe);;所有文件 (*)"
            )
            if not path:
                self._reply(task_id, True, "")
                return
            # Let normal path validation run in the worker.
            job = Job(task_id, self.bridge.set_adb_path, [path])
            self.jobs[task_id] = job
            job.signals.success.connect(lambda i, val: self._reply(i, True, val))
            job.signals.failure.connect(lambda i, err: self._reply(i, False, error=err))
            job.signals.done.connect(lambda i: self.jobs.pop(i, None))
            self.pool.start(job)
            return
        file, _ = QFileDialog.getOpenFileName(
            None, "选择 Android ARM64 ZIP", "", "ZIP 安装包 (*.zip)"
        )
        self._reply(task_id, True, file)

    def _reply(self, task_id: str, success: bool, result=None, error=""):
        try:
            body = json.dumps(
                {"ok": success, "result": result if success else None, "error": error if not success else ""},
                ensure_ascii=False, default=str,
            )
        except Exception as exc:
            body = json.dumps({"ok":False, "error":str(exc)}, ensure_ascii=False)
        self.completed.emit(task_id, body)


class ManagerWindow(QMainWindow):
    def __init__(self, bridge: DesktopBridge | None = None, *, auto_start=True):
        super().__init__()
        self.bridge = bridge or DesktopBridge()
        self.setWindowTitle("Android Web Desktop · 设备管理器")
        self.resize(1550, 980)
        self.setMinimumSize(960, 600)
        icon_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        icon = icon_root / "assets" / "app.ico"
        if not icon.is_file():
            icon = Path(__file__).resolve().parent / "assets" / "app.ico"
        self.setWindowIcon(QIcon(str(icon)))

        self.profile = shared_web_profile()
        self.assets = _shared_asset_handler

        self.view = QWebEngineView(self)
        page = BrowserPage(self.profile, self.view)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.view.setPage(page)
        if os.environ.get("AWD_DEBUG_UI"):
            self.view.loadFinished.connect(lambda ok: print("WEB LOAD FINISHED",ok,self.view.url().toString(),flush=True))
            self.view.loadStarted.connect(lambda: print("WEB LOAD STARTED",flush=True))

        self.channel = QWebChannel(self.view)
        self.backend = QtBridge(self.bridge, self)
        self.channel.registerObject("nativeBridge", self.backend)
        page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)
        self.view.load(QUrl(SCHEME_URL))

    def js(self, script, callback=None):
        self.view.page().runJavaScript(script, callback or (lambda _: None))

    def closeEvent(self, event):
        self.backend.pool.waitForDone(1200)
        # Destroy QWebEnginePage synchronously, while its QApplication-owned
        # profile still exists. deleteLater alone can be too late when the
        # Python executable immediately exits after the final window closes.
        if self.centralWidget() is not None:
            import shiboken6
            widget = self.takeCentralWidget()
            if widget is not None:
                shiboken6.delete(widget)
        return super().closeEvent(event)
