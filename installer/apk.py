"""Download and install ordinary APKs using the selected authorized ADB device."""
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile, BadZipFile
import time

MAX_APK = 128 * 1024 * 1024


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("请输入有效的 HTTPS APK 下载链接（仅 443 端口）")
    return url


class HTTPSRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_apk(path):
    if not path.is_file() or path.suffix.lower() != ".apk" or not 0 < path.stat().st_size <= MAX_APK:
        raise ValueError("请选择不超过 128 MiB 的单文件 APK")
    try:
        with ZipFile(path) as archive:
            if archive.getinfo("AndroidManifest.xml").file_size <= 0:
                raise ValueError("APK 清单为空")
    except (BadZipFile, KeyError) as exc:
        raise ValueError("不是有效的单文件 APK") from exc


def install_apk(adb, serial, source, remote, progress):
    def install(path):
        validate_apk(path)
        progress("正在通过 ADB 安装 APK")
        result = adb.selected(serial, "install", "-r", str(path), timeout=180)
        if not any(line.strip() == "Success" for line in result.splitlines()):
            raise ValueError("Android 安装失败：" + result)
        return result

    if not remote:
        return install(Path(source))
    validate_url(source)
    with TemporaryDirectory(prefix="awd-apk-") as tmp:
        path = Path(tmp) / "download.apk"
        opener = build_opener(HTTPSRedirect())
        deadline = time.monotonic() + 240
        received = last = 0
        progress("正在使用电脑网络下载 APK")
        with opener.open(Request(source, headers={"User-Agent": "AndroidWebDesktop"}), timeout=20) as response, path.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            if total > MAX_APK:
                raise ValueError("APK 超过 128 MiB")
            while block := response.read(128 * 1024):
                received += len(block)
                if received > MAX_APK or time.monotonic() > deadline:
                    raise ValueError("APK 下载超时或超过 128 MiB")
                out.write(block)
                if received - last >= 1024 * 1024:
                    last = received
                    progress(f"下载 APK：{received // 1048576} MiB" + (f" / {total // 1048576} MiB" if total else ""))
        return install(path)
