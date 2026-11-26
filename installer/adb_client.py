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
from concurrent.futures import ThreadPoolExecutor


DATA_DIR = "/data/local/tmp/android-web-desktop"
PKG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
VERSION_RE = re.compile(r"^releases/(\d+\.\d+\.\d+)/desktopd$")
# Conservative denylist for packages that may remove boot, network, UI or ADB access.
# Not exhaustive: platform-specific safety is enforced by explicit UI confirmation too.
CRITICAL_EXACT = frozenset({
    "android",
    "com.android.systemui",
    "com.android.settings",
    "com.android.shell",
    "com.android.phone",
    "com.android.bluetooth",
    "com.android.keychain",
    "com.android.externalstorage",
    "com.android.nfc",
    "com.android.carrierconfig",
    "com.android.tethering",
    "com.android.adbd",
    "com.android.launcher",
    "com.android.launcher3",
    "com.android.webview",
    "com.android.networkstack",
    "com.android.permissioncontroller",
    "com.android.packageinstaller",
    "com.android.captiveportallogin",
    "com.android.inputdevices",
    "com.android.documentsui",
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.google.android.webview",
    "com.google.android.networkstack",
    "com.google.android.tethering",
    "com.google.android.permissioncontroller",
    "com.google.android.packageinstaller",
    "com.google.android.apps.nexuslauncher",
    "com.google.android.setupwizard",
    "com.google.android.inputmethod.latin",
})
CRITICAL_PREFIXES = (
    "android.",
    "com.android.providers.",
    "com.google.android.providers.",
    "com.android.server.",
    "com.android.networkstack.",
    "com.google.android.networkstack.",
    "com.android.telephony.",
    "com.android.wifi.",
    "com.android.inputmethod.",
    "com.android.permissioncontroller.",
    "com.google.android.permissioncontroller.",
    "com.google.android.gms.",
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
    if getattr(sys, "frozen", False) and os.environ.get("AWD_MANAGER_DIR"):
        directory = Path(os.environ["AWD_MANAGER_DIR"])
        if directory.is_absolute():
            exe_dir = directory
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
    if not isinstance(ip, ipaddress.IPv4Address) or not is_rfc1918(str(ip)):
        raise ValueError("仅允许私有局域网 IPv4 地址")
    port = int(match.group(2) or 5555)
    if not 1 <= port <= 65535:
        raise ValueError("无效端口")
    return f"{ip}:{port}"


# Android devices expose several networks, including cellular interfaces with
# RFC1918 addresses. Those are NOT LAN management addresses.
CELLULAR_IFACE_PREFIXES = (
    "rmnet", "ccmni", "pdp", "wwan", "cell", "radio", "clat", "v4-rmnet",
    "tun", "tap", "wg", "ipsec", "vti", "ppp", "veth", "dummy",
)
HOTSPOT_IFACE_PREFIXES = ("ap", "softap", "swlan", "wlan", "br", "bridge", "eth")
USB_IFACE_PREFIXES = ("rndis", "usb", "ncm")

def is_rfc1918(address: str) -> bool:
    try:
        value = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        return False
    return any(value in ipaddress.ip_network(net) for net in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
    ))

def parse_network_addresses(output: str) -> list[dict[str, str]]:
    """Return assigned IPv4 addresses ranked by management suitability.

    Carrier PDP interfaces commonly have changing 10.x IPs and must not be
    suggested as hotspot gateway addresses.
    """
    addresses: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in output.splitlines():
        match = re.search(
            r"^\s*\d+:\s+([^\s:]+)\s+inet\s+(\d{1,3}(?:\.\d{1,3}){3})/\d+",
            line,
        )
        if not match:
            continue
        iface, value = match.group(1).split("@", 1)[0].lower(), match.group(2)
        if not is_rfc1918(value) or value in seen:
            continue
        seen.add(value)
        if iface.startswith(CELLULAR_IFACE_PREFIXES):
            role = "蜂窝/隧道"
        elif iface.startswith(USB_IFACE_PREFIXES):
            role = "USB 网络"
        elif iface.startswith(HOTSPOT_IFACE_PREFIXES):
            role = "热点/局域网"
        else:
            role = "其他网络"
        addresses.append({"ip": value, "interface": iface, "role": role})

    def ranking(entry: dict[str, str]) -> tuple[int, str]:
        ip, role = entry["ip"], entry["role"]
        if role == "蜂窝/隧道":
            return (-1, ip)
        last_octet = int(ip.split(".")[-1])
        score = (400 if ip == "192.168.0.1" else
                 220 if last_octet == 1 else 0)
        if role == "热点/局域网":
            score += 100
        elif role == "USB 网络":
            score += 40
        if ip.startswith("192.168."):
            score += 70
        return (score, ip)

    return sorted(addresses, key=ranking, reverse=True)

def parse_lan_ips(output: str) -> list[str]:
    """Only LAN-side interfaces are suitable for user HTTP endpoints."""
    return [
        entry["ip"] for entry in parse_network_addresses(output)
        if entry["role"] != "蜂窝/隧道"
    ]


def read_running_listener(adb, serial: str, pid: str | None = None) -> str:
    if pid is None:
        pid = adb.shell(serial, "cat", DATA_DIR + "/server.pid", timeout=5).strip()
    if not pid.isascii() or not pid.isdecimal() or not 1 < int(pid) < 2**31:
        raise ADBError("服务 PID 无效")
    command = adb.shell(serial, "cat", f"/proc/{pid}/cmdline", timeout=5)
    args = command.split("\x00")
    executable = args[0]
    if executable != DATA_DIR + "/current" and not (
        executable.startswith(DATA_DIR + "/") and
        VERSION_RE.fullmatch(executable[len(DATA_DIR)+1:])
    ):
        raise ADBError("服务进程身份不匹配")
    try:
        index = args.index("-listen")
        endpoint = args[index+1]
    except (ValueError, IndexError):
        endpoint = next((arg[8:] for arg in args if arg.startswith("-listen=")), "")
    host, sep, port = endpoint.partition(":")
    if not sep or not is_rfc1918(host) or not port.isascii() or not port.isdecimal() or not 1024 <= int(port) <= 65535:
        raise ADBError("服务监听地址无效")
    return f"{host}:{int(port)}"


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
        """Read properties in one ADB call and fetch network/version concurrently.

        Previously this made eight sequential getprop subprocess calls, followed
        by two further calls. Wireless ADB could make each one take seconds.
        """
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
        def props_request() -> dict[str, str]:
            output = self.shell(serial, "getprop", timeout=12)
            lines = re.findall(r"^\[([^\]]+)\]: \[(.*)\]\s*$", output, re.MULTILINE)
            mapping = dict(lines)
            return {name: mapping.get(key, "未知") for name, key in props.items()}

        def network_request() -> list[dict[str, str]]:
            return parse_network_addresses(
                self.shell(serial, "ip", "-o", "-4", "addr", "show", timeout=9)
            )

        def version_request() -> str:
            return self.shell(serial, "readlink", DATA_DIR + "/current", timeout=8).strip()

        def listener_request() -> str:
            return read_running_listener(self, serial)

        # Connections may be slower than the desktop UI, but Python bridge
        # invocation happens off the UI thread and these calls can overlap.
        values = {"adb_serial": serial}
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="ADBInfo") as pool:
            futures = {
                "props": pool.submit(props_request),
                "network": pool.submit(network_request),
                "version": pool.submit(version_request),
                "listener": pool.submit(listener_request),
            }
            for key, future in futures.items():
                try:
                    value = future.result()
                except (ADBError, OSError, ValueError):
                    value = {"props": {k: "未知" for k in props}, "network": [], "version": "", "listener": ""}[key]
                if key == "props":
                    values.update(value)
                elif key == "network":
                    values["network_addresses"] = value
                    values["ips"] = [
                        entry["ip"] for entry in value if entry["role"] != "蜂窝/隧道"
                    ]
                    values["suggested_ip"] = values["ips"][0] if values["ips"] else ""
                elif key == "version":
                    match = VERSION_RE.fullmatch(value)
                    values["installed_version"] = match.group(1) if match else None
                elif key == "listener":
                    values["listening_address"] = value
        values["install_status"] = "已安装" if values["installed_version"] else "未安装"
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
        if package in CRITICAL_EXACT or package.startswith(CRITICAL_PREFIXES):
            raise ValueError("已阻止对系统关键组件的操作")
        if package not in self.packages(serial, system=True):
            raise ValueError("不是当前系统组件")
        args = ("enable", "--user", "0", package) if enabled else ("disable-user", "--user", "0", package)
        return self.shell(serial, "pm", *args, timeout=35)

    def restart(self, serial: str) -> None:
        self.selected(serial, "reboot", timeout=12)

    def poweroff(self, serial: str) -> None:
        self.shell(serial, "reboot", "-p", timeout=12)
