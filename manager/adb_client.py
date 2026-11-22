"""Android ADB device discovery and device-management operations.

All Android commands use fixed argument arrays, never a user-supplied shell.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass


DATA_DIR = "/data/local/tmp/android-web-desktop"
PKG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
VERSION_RE = re.compile(r"^releases/(\d+\.\d+\.\d+)/desktopd$")
CRITICAL_PREFIXES = (
    "android", "com.android.systemui", "com.android.settings", "com.android.shell",
    "com.android.providers.", "com.google.android.packageinstaller",
    "com.android.packageinstaller", "com.android.permissioncontroller",
    "com.google.android.permissioncontroller", "com.android.server.",
    "com.android.phone", "com.android.bluetooth", "com.android.launcher",
    "com.google.android.apps.nexuslauncher", "com.android.inputmethod",
)


class ADBError(RuntimeError):
    pass


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    detail: str = ""


def locate_adb() -> Path | None:
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    candidates = [
        exe_dir / "adb.exe",
        exe_dir / "platform-tools" / "adb.exe",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AndroidWebDesktop" / "platform-tools" / "adb.exe",
        Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
    ]
    found = shutil.which("adb")
    if found:
        candidates.append(Path(found))
    return next((p for p in candidates if p.is_file()), None)


def run_command(args: list[str], timeout: int = 20) -> str:
    options = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": timeout}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        res = subprocess.run(args, **options)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ADBError(f"执行 ADB 失败：{exc}") from exc
    out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
    if res.returncode != 0:
        raise ADBError(out or f"ADB 返回错误码 {res.returncode}")
    return out


def parse_devices(output: str) -> list[Device]:
    found: list[Device] = []
    states = {"device", "unauthorized", "offline", "recovery", "bootloader", "sideload"}
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) >= 2 and parts[1] in states:
            found.append(Device(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return found


def validate_lan_endpoint(value: str) -> str:
    match = re.fullmatch(r"(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?", value.strip())
    if not match:
        raise ValueError("请输入局域网 IPv4 地址，例如 192.168.1.20:5555")
    ip = ipaddress.ip_address(match.group(1))
    if not isinstance(ip, ipaddress.IPv4Address) or not ip.is_private or ip.is_loopback or ip.is_link_local:
        raise ValueError("仅允许私有局域网 IPv4 地址")
    port = int(match.group(2) or 5555)
    if not 1 <= port <= 65535:
        raise ValueError("无效端口")
    return f"{ip}:{port}"


def parse_lan_ips(output: str) -> list[str]:
    ips = []
    for value in re.findall(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/\d+", output):
        try:
            ip = ipaddress.ip_address(value)
            if isinstance(ip, ipaddress.IPv4Address) and ip.is_private and not ip.is_link_local and not ip.is_loopback:
                if value not in ips:
                    ips.append(value)
        except ValueError:
            continue
    return ips


class ADB:
    def __init__(self, adb_path: str | Path):
        path = Path(adb_path)
        if not path.is_file():
            raise ADBError(f"找不到 adb.exe：{path}")
        self.executable = str(path)

    def call(self, *args: str, timeout: int = 20) -> str:
        return run_command([self.executable, *[str(a) for a in args]], timeout=timeout)

    def devices(self) -> list[Device]:
        return parse_devices(self.call("devices", "-l", timeout=12))

    def connect(self, endpoint: str) -> str:
        address = validate_lan_endpoint(endpoint)
        return self.call("connect", address, timeout=15)

    def selected(self, serial: str, *args: str, timeout: int = 20) -> str:
        return self.call("-s", serial, *args, timeout=timeout)

    def shell(self, serial: str, *args: str, timeout: int = 20) -> str:
        return self.selected(serial, "shell", *args, timeout=timeout)

    def getprop(self, serial: str, key: str) -> str:
        return self.shell(serial, "getprop", key).strip() if key else ""

    def device_info(self, serial: str) -> dict:
        props = {
            "manufacturer": "ro.product.manufacturer",
            "brand": "ro.product.brand",
            "model": "ro.product.model",
            "android": "ro.build.version.release",
            "sdk": "ro.build.version.sdk",
            "abi": "ro.product.cpu.abi",
            "build": "ro.build.display.id",
            "serial": "ro.serialno",
        }
        values = {"adb_serial": serial}
        for name, key in props.items():
            try:
                values[name] = self.getprop(serial, key)
            except ADBError:
                values[name] = "未知"
        try:
            values["ips"] = parse_lan_ips(self.shell(serial, "ip", "-o", "-4", "addr", "show", timeout=9))
        except ADBError:
            values["ips"] = []
        try:
            current = self.shell(serial, "readlink", DATA_DIR + "/current", timeout=8).strip()
        except ADBError:
            current = ""
        match = VERSION_RE.fullmatch(current)
        values["installed_version"] = match.group(1) if match else None
        values["install_status"] = "已安装" if match else "未安装"
        return values

    def packages(self, serial: str, system: bool = False) -> list[str]:
        mode = "-s" if system else "-3"
        output = self.shell(serial, "pm", "list", "packages", mode, timeout=25)
        return sorted({
            line.strip().removeprefix("package:")
            for line in output.splitlines()
            if line.strip().startswith("package:") and PKG_RE.fullmatch(line.strip().removeprefix("package:"))
        })

    def disabled_packages(self, serial: str) -> set[str]:
        output = self.shell(serial, "pm", "list", "packages", "-d", timeout=25)
        return {
            line.strip().removeprefix("package:")
            for line in output.splitlines()
            if line.strip().startswith("package:")
        }

    def remove_user_app(self, serial: str, package: str) -> str:
        if not PKG_RE.fullmatch(package):
            raise ValueError("应用包名不合法")
        if package not in self.packages(serial, system=False):
            raise ValueError("仅允许卸载用户安装的应用")
        result = self.shell(serial, "pm", "uninstall", "--user", "0", package, timeout=40)
        if "Success" not in result:
            raise ADBError(result)
        return result

    def toggle_system_app(self, serial: str, package: str, enabled: bool) -> str:
        if not PKG_RE.fullmatch(package):
            raise ValueError("应用包名不合法")
        if any(package == value or package.startswith(value) for value in CRITICAL_PREFIXES):
            raise ValueError("已阻止对系统关键组件的操作")
        if package not in self.packages(serial, system=True):
            raise ValueError("不是当前系统组件")
        args = ("enable", "--user", "0", package) if enabled else ("disable-user", "--user", "0", package)
        return self.shell(serial, "pm", *args, timeout=35)

    def restart(self, serial: str) -> None:
        self.selected(serial, "reboot", timeout=12)

    def poweroff(self, serial: str) -> None:
        self.shell(serial, "reboot", "-p", timeout=12)
