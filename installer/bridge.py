"""Desktop bridge between the Vue frontend and Android ADB operations.

The WebView exposes only these explicit methods, not a general shell.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
import webbrowser

from adb_client import ADB, ADBError, locate_adb, validate_lan_endpoint, PKG_RE
from deployment import (
    download_release,
    fetch_release,
    install_on_device,
    parse_package,
    uninstall_from_device,
    official_adb_download,
)


class DesktopBridge:
    def __init__(self):
        self.window = None
        self._lock = threading.RLock()
        self._busy = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=300)
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AndroidWebDesktop"
        base.mkdir(parents=True, exist_ok=True)
        self.settings_file = base / "manager-settings.json"
        self.settings = self._load_settings()
        saved = self.settings.get("adb_path", "")
        self.adb_path = Path(saved) if saved and Path(saved).is_file() else locate_adb()
        self.version = "2.3.1"

    def _load_settings(self) -> dict:
        try:
            return json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        self.settings_file.write_text(
            json.dumps(self.settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def log(self, message: str, level: str = "info") -> None:
        now = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._events.append({"time": now, "level": level, "message": message})

    def get_logs(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def clear_logs(self) -> bool:
        with self._lock:
            self._events.clear()
        return True

    def _adb(self) -> ADB:
        if not self.adb_path:
            raise ValueError("未检测到 ADB，请在设置页面选择或下载官方工具")
        return ADB(self.adb_path)

    def _ready(self, serial: str) -> ADB:
        adb = self._adb()
        if not any(d.serial == serial and d.state == "device" for d in adb.devices()):
            raise ValueError("目标设备未授权或已断开，请刷新设备列表")
        return adb

    def _execute(self, label: str, operation):
        if not self._busy.acquire(blocking=False):
            raise ValueError("已有设备操作在执行，请稍后再试")
        try:
            self.log(label)
            result = operation()
            self.log(label + " · 完成", "success")
            return result
        except Exception as exc:
            self.log(label + " · 失败：" + str(exc), "error")
            raise
        finally:
            self._busy.release()

    def environment(self) -> dict:
        return {
            "version": self.version,
            "adb_path": str(self.adb_path) if self.adb_path else "",
            "adb_found": bool(self.adb_path and self.adb_path.is_file()),
        }

    def list_devices(self) -> list[dict]:
        adb = self._adb()
        return [dict(serial=d.serial, state=d.state, detail=d.detail)
                for d in adb.devices()]

    def device_info(self, serial: str) -> dict:
        return self._ready(serial).device_info(serial)

    def list_apps(self, serial: str, system: bool = False) -> list[dict]:
        adb = self._ready(serial)
        packages = adb.packages(serial, system=system)
        disabled = adb.disabled_packages(serial) if system else set()
        return [{"name": name, "system": bool(system), "disabled": name in disabled}
                for name in packages]

    def connect(self, endpoint: str) -> str:
        valid = validate_lan_endpoint(endpoint)
        return self._execute("无线 ADB 连接 " + valid, lambda: self._adb().connect(valid))

    def set_adb_path(self, path: str) -> str:
        p = Path(path)
        if not p.is_file() or p.name.lower() != ("adb.exe" if os.name == "nt" else "adb"):
            raise ValueError("请选择有效的 adb 可执行文件")
        self.adb_path = p
        self.settings["adb_path"] = str(p)
        self._save_settings()
        self.log("已设置 ADB 路径：" + str(p))
        return str(p)

    def choose_adb(self) -> str:
        path = self._choose_file("adb.exe" if os.name == "nt" else "adb")
        return self.set_adb_path(path) if path else ""

    def choose_local_zip(self) -> str:
        return self._choose_file("*.zip") or ""

    def _choose_file(self, pattern: str) -> str | None:
        if self.window is None:
            raise ValueError("窗口尚未准备完成")
        import webview
        option = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
        if option is None:
            option = getattr(webview, "OPEN_DIALOG", 10)
        paths = self.window.create_file_dialog(
            option,
            allow_multiple=False,
            file_types=(f"文件 ({pattern})",),
        )
        return str(paths[0]) if paths else None

    def install_official_adb(self) -> str:
        def operation():
            path = official_adb_download(lambda msg: self.log(msg))
            self.adb_path = path
            self.settings["adb_path"] = str(path)
            self._save_settings()
            return str(path)
        return self._execute("下载 Google 官方 Platform Tools", operation)

    def check_release(self) -> dict:
        return self._execute("检查最新版", fetch_release)

    @staticmethod
    def _validate_ip(ip: str) -> str:
        # App URLs must refer to a local device address, not an arbitrary URL.
        return validate_lan_endpoint(ip + ":5555").split(":")[0]

    def install_latest(self, serial: str, ip: str) -> dict:
        def operation():
            adb = self._ready(serial)
            release = fetch_release()
            self.log(f"发现版本 v{release['version']}，下载并校验 SHA256")
            package = parse_package(download_release(release, lambda msg: self.log(msg)))
            if package.version != release["version"]:
                raise ValueError("安装包版本和 Release 不一致")
            url, password = install_on_device(
                adb, serial, package, self._validate_ip(ip),
                progress=lambda msg: self.log(msg),
            )
            return {"url": url, "password": password, "version": package.version}
        return self._execute("安装最新版 · " + serial, operation)

    def install_local(self, serial: str, ip: str, file_path: str) -> dict:
        def operation():
            adb = self._ready(serial)
            p = Path(file_path)
            if p.suffix.lower() != ".zip" or not p.is_file() or p.stat().st_size > 35 * 1024 * 1024:
                raise ValueError("本地安装包不存在或格式错误")
            package = parse_package(p.read_bytes())
            url, password = install_on_device(
                adb, serial, package, self._validate_ip(ip),
                progress=lambda msg: self.log(msg),
            )
            return {"url": url, "password": password, "version": package.version}
        return self._execute("安装本地版本 · " + serial, operation)

    def uninstall(self, serial: str) -> str:
        return self._execute("卸载网页桌面 · " + serial,
                             lambda: uninstall_from_device(self._ready(serial), serial))

    def uninstall_app(self, serial: str, package: str) -> str:
        return self._execute("卸载普通应用 · " + package,
                             lambda: self._ready(serial).remove_user_app(serial, package))

    def set_system_app(self, serial: str, package: str, enabled: bool) -> str:
        verb = "恢复" if enabled else "停用"
        return self._execute(verb + "系统组件 · " + package,
                             lambda: self._ready(serial).toggle_system_app(serial, package, enabled))

    def reboot(self, serial: str) -> str:
        def operation():
            self._ready(serial).restart(serial)
            return "已发送重启命令"
        return self._execute("重启设备 · " + serial, operation)

    def poweroff(self, serial: str) -> str:
        def operation():
            self._ready(serial).poweroff(serial)
            return "已发送关机命令"
        return self._execute("关闭设备 · " + serial, operation)

    def open_web(self, ip: str, port: int = 8765) -> str:
        valid = self._validate_ip(ip)
        if not 1024 <= int(port) <= 65535:
            raise ValueError("端口超出允许范围")
        url = f"http://{valid}:{int(port)}"
        webbrowser.open(url)
        return url
