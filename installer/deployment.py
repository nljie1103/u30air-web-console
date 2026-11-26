"""Release download, integrity validation and on-device installation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler
from urllib.request import Request, urlopen
from zipfile import ZipFile
import io
import uuid

from adb_client import ADB, ADBError, DATA_DIR, VERSION_RE, is_rfc1918, read_running_listener


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



def verify_remote_service(adb: ADB, serial: str, version: str, progress=lambda _: None) -> None:
    """Verify the Android service through a local ADB-forwarded health endpoint.

    Unlike reading a password or symlink, this proves the expected version has
    actually started and has bound its LAN HTTP listener.
    """
    last_error: Exception | None = None
    opener = build_opener(ProxyHandler({}))
    for attempt in range(14):
        forward_port: str | None = None
        try:
            health_port = adb.shell(serial, "cat", DATA_DIR + "/health.port", timeout=6).strip()
            if not re.fullmatch(r"[0-9]{1,5}", health_port) or not (1 <= int(health_port) <= 65535):
                raise ADBError("设备健康检查端口无效")
            forward_port = adb.selected(
                serial, "forward", "tcp:0", "tcp:" + health_port, timeout=6
            ).strip()
            if not re.fullmatch(r"[0-9]{1,5}", forward_port) or not (1 <= int(forward_port) <= 65535):
                raise ADBError("ADB forward 没有返回有效的本地端口")
            with opener.open("http://127.0.0.1:" + forward_port + "/healthz", timeout=1.5) as response:
                if response.status != 200:
                    raise ADBError("健康检查 HTTP 状态码异常")
                data = json.loads(response.read(2048))
            if data.get("status") == "ok" and data.get("version") == version and data.get("ready") is True:
                progress("服务健康检查通过，网页端口已监听")
                return
            if data.get("version") != version:
                raise ADBError("启动的服务版本与安装包不一致")
            raise ADBError("Android 网页服务尚未监听局域网端口")
        except (ADBError, OSError, ValueError, URLError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt in (0, 4, 9):
                progress("等待 Android 网页服务就绪…")
            if attempt != 13:
                time.sleep(0.5)
        finally:
            if forward_port:
                try:
                    adb.selected(serial, "forward", "--remove", "tcp:" + forward_port, timeout=6)
                except ADBError:
                    pass
    raise ADBError("部署后健康检查未通过：" + str(last_error or "无响应"))

def remote_entries(adb: ADB, serial: str) -> set[str]:
    # Listing failure is not evidence of absence; never treat transport or
    # permission errors as a missing file.
    return set(adb.shell(serial, "ls", "-a", DATA_DIR, timeout=8).splitlines())


def require_no_recovery(entries: set[str]) -> None:
    if any(name.endswith((".rollback", ".before-edit")) for name in entries) or "deployment-recovery" in entries:
        raise ADBError("检测到尚未验收的恢复备份，请先检查设备端备份与日志，不会覆盖原件")


def write_recovery_marker(adb, serial, old_link, old_listen, had_auth):
    # No plaintext password in recovery metadata.
    with tempfile.TemporaryDirectory(prefix="awd-recovery-") as temp:
        marker = Path(temp) / "deployment-recovery"
        marker.write_text(json.dumps({"previous": old_link, "listen": old_listen,
                                      "auth_existed": had_auth}), encoding="utf-8")
        adb.selected(serial, "push", str(marker), DATA_DIR + "/deployment-recovery", timeout=15)
        adb.shell(serial, "chmod", "600", DATA_DIR + "/deployment-recovery")


def preserve_copy(adb, serial, backup, live, timeout=12):
    adb.shell(serial, "cp", backup, live + ".restore", timeout=timeout)
    adb.shell(serial, "mv", "-f", live + ".restore", live, timeout=timeout)


def install_on_device(
    adb: ADB, serial: str, package: Package, ip: str, port: int = 8765,
    progress=lambda _: None,
    auth_enabled: bool | None = None, auth_password: str = "",
) -> tuple[str, str]:
    if auth_enabled is not None:
        if not isinstance(auth_enabled, bool):
            raise ValueError("登录开关必须为布尔值")
        if auth_enabled and not auth_password:
            raise ValueError("开启网页密码时需要设置密码（不要求复杂度或最短长度）")
        if not isinstance(auth_password, str):
            raise ValueError("密码格式错误")
    parsed = ipaddress.ip_address(ip)
    if (parsed.version != 4 or not is_rfc1918(str(parsed))):
        raise ValueError("访问 IP 必须是设备的私有局域网地址")
    if not 1024 <= port <= 65535:
        raise ValueError("不支持该网页端口")
    if adb.getprop(serial, "ro.product.cpu.abi") != "arm64-v8a":
        raise ADBError("设备不是 arm64-v8a，无法安装此程序")
    # Do not replace an already-running instance with a listener bound to
    # a stale carrier/USB IP. Check before stopping the previous version.
    try:
        from adb_client import parse_network_addresses
        interfaces = parse_network_addresses(
            adb.shell(serial, "ip", "-o", "-4", "addr", "show", timeout=9)
        )
    except ADBError:
        interfaces = []
    if interfaces and ip not in {entry["ip"] for entry in interfaces}:
        raise ADBError(
            f"设备当前没有配置 {ip}。请确认网关地址属于该设备的网络接口后再部署。"
        )
    if any(entry["ip"] == ip and entry["role"] == "蜂窝/隧道" for entry in interfaces):
        raise ADBError(
            f"{ip} 属于蜂窝数据或隧道接口，不适合当作固定网页管理地址；"
            "请改用设备的 Wi-Fi 热点网关地址。"
        )

    remote = DATA_DIR
    target = f"releases/{package.version}/desktopd"
    base = f"{remote}/releases/{package.version}"
    adb.shell(serial, "mkdir", "-p", remote, timeout=15)
    entries = remote_entries(adb, serial)
    require_no_recovery(entries)
    old_link = adb.shell(serial, "readlink", remote + "/current").strip() if "current" in entries else ""
    old_exists = VERSION_RE.fullmatch(old_link) is not None
    if "current" in entries and not old_exists:
        raise ADBError("原版本指针无效，已停止部署")
    replacing_current = old_link == target
    old_pid = ""
    old_listen = ""
    if "server.pid" in entries:
        if not old_exists:
            raise ADBError("发现未识别的旧服务进程，已停止部署")
        old_pid = adb.shell(serial, "cat", remote + "/server.pid", timeout=6).strip()
        if not old_pid.isascii() or not old_pid.isdecimal() or not 1 < int(old_pid) < 2**31:
            raise ADBError("原服务 PID 无效")
        proc_entries = set(adb.shell(serial, "ls", "-a", "/proc", timeout=8).splitlines())
        if old_pid in proc_entries:
            old_listen = read_running_listener(adb, serial, old_pid)
        else:
            # A confirmed absent process is a stopped service, not an ADB error.
            old_pid = ""
    if "auth.json" in entries:
        read_device_auth(adb, serial, entries)

    # Stage every file before stopping the old service. Never push directly
    # into an executable that might currently be running.
    stage_binary = base + "/desktopd.next"
    stage_start = remote + "/start.sh.next"
    stage_stop = remote + "/stop.sh.next"
    stage_auth = remote + "/auth.json.next"
    live_auth = remote + "/auth.json"
    backup_auth = remote + "/auth.json.rollback"
    configured_auth = auth_enabled is not None
    old_auth_exists = "auth.json" in entries
    recovery_marker = remote + "/deployment-recovery"
    old_binary_backup = base + "/desktopd.rollback"
    script_backups = (remote + "/start.sh.rollback", remote + "/stop.sh.rollback")
    script_files = (remote + "/start.sh", remote + "/stop.sh")
    stopped = False
    stop_confirmed = False
    switched = False
    install_healthy = False
    rollback_healthy = False

    try:
        progress("准备临时版本目录")
        adb.shell(serial, "mkdir", "-p", base, timeout=15)
        with tempfile.TemporaryDirectory(prefix="awd-manager-") as temp:
            for name, content in package.files.items():
                local = Path(temp) / name
                local.write_bytes(content)
                dest = stage_binary if name == "desktopd" else (
                    stage_start if name == "start.sh" else stage_stop
                )
                progress(f"暂存 {name}")
                adb.selected(serial, "push", str(local), dest, timeout=75)
        adb.shell(serial, "chmod", "700", stage_binary, stage_start, stage_stop)
        if configured_auth:
            # Only a temporary local file is used, not an ADB shell argument,
            # so a custom password can contain spaces and symbols.
            with tempfile.TemporaryDirectory(prefix="awd-auth-") as temp:
                local = Path(temp) / "auth.json"
                local.write_text(json.dumps({
                    "enabled": auth_enabled,
                    "password": auth_password if auth_enabled else "",
                }, ensure_ascii=False), encoding="utf-8")
                adb.selected(serial, "push", str(local), stage_auth, timeout=30)
            adb.shell(serial, "chmod", "600", stage_auth)
            if old_auth_exists:
                adb.shell(serial, "cp", live_auth, backup_auth, timeout=10)
                adb.shell(serial, "chmod", "600", backup_auth)

        # Save the old startup scripts even if the app version is changing.
        # Their behavior might change between releases, so rollback needs them.
        if old_exists:
            for live, backup in zip(script_files, script_backups):
                adb.shell(serial, "cp", live, backup, timeout=10)
                adb.shell(serial, "chmod", "700", backup)
            if replacing_current:
                adb.shell(serial, "cp", base + "/desktopd", old_binary_backup, timeout=15)
                adb.shell(serial, "chmod", "700", old_binary_backup)

        write_recovery_marker(adb, serial, old_link, old_listen, old_auth_exists)
        progress("停止现有服务")
        stopped = True
        if old_exists:
            adb.shell(serial, "sh", remote + "/stop.sh", timeout=15)
        stop_confirmed = True

        # Rename files atomically on the device filesystem.
        adb.shell(serial, "mv", "-f", stage_binary, base + "/desktopd")
        adb.shell(serial, "mv", "-f", stage_start, script_files[0])
        adb.shell(serial, "mv", "-f", stage_stop, script_files[1])
        adb.shell(serial, "rm", "-f", remote + "/current.new")
        adb.shell(serial, "ln", "-s", target, remote + "/current.new")
        adb.shell(serial, "mv", "-f", remote + "/current.new", remote + "/current")
        switched = True
        if configured_auth:
            adb.shell(serial, "mv", "-f", stage_auth, live_auth)
            adb.shell(serial, "chmod", "600", live_auth)

        progress("启动并验收新服务")
        adb.shell(serial, "sh", remote + "/start.sh", f"{ip}:{port}", timeout=15)
        verify_remote_service(adb, serial, package.version, progress)
        if old_pid:
            new_pid = adb.shell(serial, "cat", remote + "/server.pid", timeout=6).strip()
            if new_pid == old_pid:
                raise ADBError("新服务没有重新启动，检测到仍在使用旧进程")
        if read_running_listener(adb, serial) != f"{ip}:{port}":
            raise ADBError("新服务未绑定指定的监听地址")
        if auth_enabled is False:
            password = ""
        elif auth_enabled is True:
            password = auth_password
        elif old_auth_exists:
            password = ""
        else:
            password = adb.shell(serial, "cat", remote + "/password.txt", timeout=10).strip()
            if not password:
                raise ADBError("旧版管理口令读取失败，请检查 server.log")
        install_healthy = True
        progress("部署健康检查通过")
        return f"http://{ip}:{port}", password

    except Exception:
        if stopped:
            progress("部署失败，尝试恢复原有服务")
            try:
                if not stop_confirmed:
                    raise ADBError("原服务停止状态未确认")
                # If the new version was started, stop it before restoring.
                if switched:
                    adb.shell(serial, "sh", remote + "/stop.sh", timeout=12)
                if configured_auth:
                    if old_auth_exists:
                        preserve_copy(adb, serial, backup_auth, live_auth)
                    else:
                        adb.shell(serial, "rm", "-f", live_auth, timeout=10)
                if old_exists:
                    for live, backup in zip(script_files, script_backups):
                        preserve_copy(adb, serial, backup, live)
                    if replacing_current:
                        preserve_copy(adb, serial, old_binary_backup, base + "/desktopd", timeout=15)
                    adb.shell(serial, "rm", "-f", remote + "/current.new")
                    adb.shell(serial, "ln", "-s", old_link, remote + "/current.new")
                    adb.shell(serial, "mv", "-f", remote + "/current.new", remote + "/current")
                    if old_listen:
                        adb.shell(serial, "sh", remote + "/start.sh", old_listen, timeout=15)
                        verify_remote_service(adb, serial, VERSION_RE.fullmatch(old_link).group(1), progress)
                        if read_running_listener(adb, serial) != old_listen:
                            raise ADBError("旧监听地址未恢复")
                    progress("已恢复上一版本及原监听设置")
                    rollback_healthy = True
                elif switched:
                    adb.shell(serial, "rm", "-f", remote + "/current", timeout=10)
                    progress("首次安装失败，已撤销无效版本指针")
                    rollback_healthy = True
                else:
                    rollback_healthy = True
            except Exception as recovery_error:
                progress("恢复过程失败，保留原件与恢复标记：" + str(recovery_error))
                raise ADBError("部署失败且恢复未通过，已保留备份，请检查设备端日志") from recovery_error
        raise
    finally:
        # Removing stage and optional rollback files never touches a running
        # executable. Do not let cleanup failures mask the original result.
        for path in (stage_binary, stage_start, stage_stop, stage_auth, remote + "/current.new"):
            try:
                adb.shell(serial, "rm", "-f", path, timeout=6)
            except ADBError:
                pass
        # Keep rollback material when an attempted recovery has failed.
        if install_healthy or rollback_healthy or not stopped:
            for path in (old_binary_backup, backup_auth, *script_backups, recovery_marker):
                try:
                    adb.shell(serial, "rm", "-f", path, timeout=6)
                except ADBError:
                    pass


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
    """One-click download from Google's HTTPS source; no PATH/admin changes.

    Extract into a temporary directory and replace the working ADB files
    only after validating that all required Windows PE files are present.
    """
    import os
    url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    target = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AndroidWebDesktop" / "platform-tools"
    target.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "Android-Web-Desktop-Manager"})
    chunks = []
    total = 0
    progress("连接 Google 官方 Platform Tools 下载地址…")
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
    try:
        archive = ZipFile(io.BytesIO(b"".join(chunks)))
    except Exception as exc:
        raise ValueError("下载到的 Google ADB ZIP 格式错误") from exc
    required = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")
    with tempfile.TemporaryDirectory(prefix="awd-adb-", dir=target.parent) as temporary:
        stage = Path(temporary)
        for name in required:
            info = archive.getinfo("platform-tools/" + name)
            if info.file_size < 400 or info.file_size > 40 * 1024 * 1024:
                raise ValueError(f"Google Platform Tools 文件大小异常：{name}")
            data = archive.read("platform-tools/" + name)
            if data[:2] != b"MZ":
                raise ValueError(f"Platform Tools Windows 文件签名异常：{name}")
            (stage / name).write_bytes(data)
        # Never replace an individual member of the live three-file set.
        # The previous directory remains usable even when ADB has DLLs open.
        if target.exists():
            if all((target / name).is_file() and (target / name).read_bytes() == (stage / name).read_bytes()
                   for name in required):
                return target / "adb.exe"
            target = target.parent / ("platform-tools-" + uuid.uuid4().hex)
        os.replace(stage, target)
    progress("Google 官方 ADB 已安装，无需配置环境变量")
    return target / "adb.exe"


def read_device_auth(adb: ADB, serial: str, entries=None) -> dict:
    """Return the login toggle only; only a confirmed absent file is legacy."""
    if entries is None:
        entries = remote_entries(adb, serial)
    if "auth.json" not in entries:
        return {"enabled": True, "configured": False}
    raw = adb.shell(serial, "cat", DATA_DIR + "/auth.json", timeout=7)
    try:
        value = json.loads(raw)
        if not isinstance(value["enabled"], bool) or not isinstance(value.get("password", ""), str):
            raise ValueError("invalid config")
        if value["enabled"] and not value.get("password"):
            raise ValueError("empty password")
    except (ValueError, TypeError, KeyError) as exc:
        raise ADBError("设备认证配置无法读取，已停止操作") from exc
    return {"enabled": value["enabled"], "configured": True}


def configure_device_auth(adb: ADB, serial: str, enabled: bool, password: str = "",
                          progress=lambda _: None) -> dict:
    """Set auth via authorized ADB, restart current service and verify its health.

    Back up the previous configuration and restore on a failed restart.
    """
    if not isinstance(enabled, bool):
        raise ValueError("登录开关不合法")
    entries = remote_entries(adb, serial)
    require_no_recovery(entries)
    current = read_device_auth(adb, serial, entries)
    if enabled and not password and not current["enabled"]:
        raise ValueError("重新开启密码验证时，需要填写一个密码")
    if enabled and not password and not current["configured"]:
        # Preserve the legacy generated password without asking for new one.
        password = adb.shell(serial, "cat", DATA_DIR + "/password.txt").strip()
    elif enabled and not password and current["configured"]:
        raw = adb.shell(serial, "cat", DATA_DIR + "/auth.json")
        password = json.loads(raw).get("password", "")
    if enabled and not password:
        raise ValueError("开启登录需要输入密码")
    old_link = adb.shell(serial, "readlink", DATA_DIR + "/current").strip()
    match = VERSION_RE.fullmatch(old_link)
    if not match:
        raise ADBError("网页控制台尚未部署")
    listen = read_running_listener(adb, serial)

    live = DATA_DIR + "/auth.json"
    backup = DATA_DIR + "/auth.json.before-edit"
    stage = DATA_DIR + "/auth.json.edit"
    marker = DATA_DIR + "/deployment-recovery"
    had_existing = current["configured"]
    if had_existing:
        adb.shell(serial, "cp", live, backup)
        adb.shell(serial, "chmod", "600", backup)
    changed = False
    healthy = False
    try:
        with tempfile.TemporaryDirectory(prefix="awd-auth-") as temp:
            local = Path(temp) / "auth.json"
            local.write_text(json.dumps({"enabled": enabled,
                                         "password": password if enabled else ""},
                                        ensure_ascii=False), encoding="utf-8")
            adb.selected(serial, "push", str(local), stage)
        adb.shell(serial, "chmod", "600", stage)
        write_recovery_marker(adb, serial, old_link, listen, had_existing)
        changed = True
        adb.shell(serial, "sh", DATA_DIR + "/stop.sh")
        adb.shell(serial, "mv", "-f", stage, live)
        adb.shell(serial, "chmod", "600", live)
        progress("应用新的网页密码设置并重新启动服务")
        adb.shell(serial, "sh", DATA_DIR + "/start.sh", listen)
        verify_remote_service(adb, serial, match.group(1), progress)
        if read_running_listener(adb, serial) != listen:
            raise ADBError("认证重启后的监听地址不一致")
        healthy = True
    except Exception:
        if not changed:
            raise
        progress("认证配置未通过健康检查，正在恢复旧设置")
        try:
            adb.shell(serial, "sh", DATA_DIR + "/stop.sh")
            if had_existing:
                preserve_copy(adb, serial, backup, live)
            else:
                adb.shell(serial, "rm", "-f", live)
            adb.shell(serial, "sh", DATA_DIR + "/start.sh", listen)
            verify_remote_service(adb, serial, match.group(1), progress)
            if read_running_listener(adb, serial) != listen:
                raise ADBError("旧监听地址未恢复")
            healthy = True
        except Exception as recovery_error:
            progress("认证恢复未验收，已保留原始备份")
            raise ADBError("认证恢复失败，已保留备份，请检查设备端日志") from recovery_error
        raise
    finally:
        for item in ((stage, backup, marker) if healthy or not changed else (stage,)):
            try:
                adb.shell(serial, "rm", "-f", item)
            except ADBError:
                pass
    return {"enabled": enabled, "message": "网页登录设置已应用"}
