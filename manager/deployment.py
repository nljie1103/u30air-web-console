"""Release download, integrity validation and on-device installation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZipFile
import io

from adb_client import ADB, ADBError, DATA_DIR, VERSION_RE


REPOSITORY = "nljie1103/u30air-web-console"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
PACKAGE_NAME = "android-web-desktop-arm64.zip"
ASSET_LIMIT = 35 * 1024 * 1024
BINARY_LIMIT = 24 * 1024 * 1024
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
INSTALL_FILES = {
    "desktopd": "desktopd",
    "installer/start.sh": "start.sh",
    "installer/stop.sh": "stop.sh",
}


@dataclass(frozen=True)
class Package:
    version: str
    files: dict[str, bytes]


def parse_release(data: dict) -> dict:
    version_tag = data.get("tag_name", "")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version_tag):
        raise ValueError("GitHub Release 版本号格式不正确")
    for a in data.get("assets", []):
        if a.get("name") != PACKAGE_NAME:
            continue
        url = a.get("browser_download_url", "")
        if not url.startswith(f"https://github.com/{REPOSITORY}/releases/download/"):
            raise ValueError("Release 下载地址不可信")
        digest = a.get("digest", "")
        if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
            raise ValueError("Release 没有提供可验证的 SHA256 摘要")
        return {
            "version": version_tag[1:],
            "notes": data.get("body") or "",
            "url": url,
            "sha256": digest[7:].lower(),
        }
    raise ValueError("Release 缺少 Android ARM64 安装 ZIP")


def fetch_release() -> dict:
    req = Request(RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "Android-Web-Desktop-Manager"})
    with urlopen(req, timeout=25) as r:
        body = r.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("Release 元数据过大")
    return parse_release(json.loads(body))


def download_release(release: dict, progress=lambda _: None) -> bytes:
    req = Request(release["url"], headers={"User-Agent": "Android-Web-Desktop-Manager"})
    parts: list[bytes] = []
    size = 0
    with urlopen(req, timeout=75) as r:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > ASSET_LIMIT:
                raise ValueError("安装包超过限制大小")
            parts.append(chunk)
            progress(f"下载中：{size // 1024} KB")
    content = b"".join(parts)
    actual = hashlib.sha256(content).hexdigest()
    if actual != release["sha256"]:
        raise ValueError("安装包 SHA256 校验失败，已停止安装")
    return content


def parse_package(content: bytes) -> Package:
    if len(content) > ASSET_LIMIT:
        raise ValueError("安装包过大")
    files = {}
    with ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
        required = {"VERSION", *INSTALL_FILES.keys()}
        if not required.issubset(names):
            raise ValueError("不是有效的 Android Web Desktop 安装包")
        if archive.getinfo("VERSION").file_size > 128:
            raise ValueError("版本信息过大")
        version = archive.read("VERSION").decode("ascii").strip()
        if not VERSION_PATTERN.fullmatch(version):
            raise ValueError("安装包版本号不合法")
        for path, name in INSTALL_FILES.items():
            info = archive.getinfo(path)
            limit = BINARY_LIMIT if name == "desktopd" else 50_000
            if info.file_size > limit:
                raise ValueError(f"安装文件超限：{name}")
            data = archive.read(path)
            if not data:
                raise ValueError(f"安装文件为空：{name}")
            files[name] = data
    binary = files["desktopd"]
    if len(binary) < 20 or binary[:4] != b"\x7fELF" or binary[4] != 2 or int.from_bytes(binary[18:20], "little") != 183:
        raise ValueError("安装包不是 Android ARM64 ELF 程序")
    return Package(version, files)


def install_on_device(adb: ADB, serial: str, package: Package, ip: str, port: int = 8765, progress=lambda _: None) -> tuple[str, str]:
    parsed = ipaddress.ip_address(ip)
    if parsed.version != 4 or not parsed.is_private or parsed.is_link_local or parsed.is_loopback:
        raise ValueError("访问 IP 必须是设备的私有局域网地址")
    if not (1024 <= port <= 65535):
        raise ValueError("不支持该网页端口")
    if adb.getprop(serial, "ro.product.cpu.abi") != "arm64-v8a":
        raise ADBError("设备不是 arm64-v8a，无法安装此程序")
    remote = DATA_DIR
    current = ""
    try:
        current = adb.shell(serial, "readlink", remote + "/current").strip()
    except ADBError:
        pass
    target = f"releases/{package.version}/desktopd"
    base = f"{remote}/releases/{package.version}"
    progress("准备目标目录")
    adb.shell(serial, "mkdir", "-p", base, timeout=15)
    with tempfile.TemporaryDirectory(prefix="awd-manager-") as temp:
        for name, content in package.files.items():
            local = Path(temp) / name
            local.write_bytes(content)
            dest = base + "/desktopd" if name == "desktopd" else remote + "/" + name
            progress(f"传输 {name}")
            adb.selected(serial, "push", str(local), dest, timeout=75)
    adb.shell(serial, "chmod", "700", base + "/desktopd", remote + "/start.sh", remote + "/stop.sh")
    progress("停止旧服务并切换程序")
    adb.shell(serial, "sh", remote + "/stop.sh", timeout=12)
    try:
        adb.shell(serial, "rm", "-f", remote + "/current.new")
        adb.shell(serial, "ln", "-s", target, remote + "/current.new")
        adb.shell(serial, "mv", "-f", remote + "/current.new", remote + "/current")
        progress("启动服务")
        adb.shell(serial, "sh", remote + "/start.sh", f"{ip}:{port}", timeout=15)
        password = adb.shell(serial, "cat", remote + "/password.txt", timeout=10).strip()
        if not re.fullmatch(r"[0-9a-f]{32}", password):
            raise ADBError("服务启动口令读取失败，请检查 server.log")
        return f"http://{ip}:{port}", password
    except Exception:
        # Preserve a working installation when a new version fails to launch.
        if VERSION_RE.fullmatch(current) and current != target:
            try:
                adb.shell(serial, "rm", "-f", remote + "/current.new")
                adb.shell(serial, "ln", "-s", current, remote + "/current.new")
                adb.shell(serial, "mv", "-f", remote + "/current.new", remote + "/current")
                adb.shell(serial, "sh", remote + "/start.sh", f"{ip}:{port}")
                progress("已尝试恢复旧版本")
            except Exception:
                progress("旧版本自动恢复失败，请检查设备日志")
        raise


def uninstall_from_device(adb: ADB, serial: str) -> str:
    # Only our fixed private application data directory is ever removed.
    current = ""
    try:
        current = adb.shell(serial, "readlink", DATA_DIR + "/current")
    except ADBError:
        pass
    if not VERSION_RE.fullmatch(current.strip()):
        raise ValueError("设备没有检测到可卸载的本项目版本")
    adb.shell(serial, "sh", DATA_DIR + "/stop.sh")
    adb.shell(serial, "rm", "-rf", DATA_DIR)
    return "本机网页桌面及其配置数据已卸载"


def official_adb_download(progress=lambda _: None) -> Path:
    """Download only Google's official Platform Tools after user consent."""
    import os
    url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    target = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AndroidWebDesktop" / "platform-tools"
    target.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "Android-Web-Desktop-Manager"})
    chunks = []
    total = 0
    with urlopen(req, timeout=70) as r:
        while True:
            block = r.read(512 * 1024)
            if not block:
                break
            total += len(block)
            if total > 100 * 1024 * 1024:
                raise ValueError("官方工具包超过下载大小限制")
            chunks.append(block)
            progress(f"正在下载官方 ADB：{total // 1024} KB")
    archive = ZipFile(io.BytesIO(b"".join(chunks)))
    for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"):
        path = "platform-tools/" + name
        info = archive.getinfo(path)
        if info.file_size > 40 * 1024 * 1024:
            raise ValueError(f"官方工具包文件过大：{name}")
        data = archive.read(path)
        (target / name).write_bytes(data)
    if not (target / "adb.exe").is_file():
        raise ValueError("ADB 文件未能安装")
    return target / "adb.exe"
