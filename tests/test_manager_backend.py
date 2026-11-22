import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

MANAGER_DIR = Path(__file__).resolve().parents[1] / "manager"
sys.path.insert(0, str(MANAGER_DIR))
import adb_client
import deployment


class TestADB(unittest.TestCase):
    def test_devices(self):
        text = """List of devices attached
* daemon not running; starting now
emulator-5554  device product:sdk model:Pixel
192.168.0.25:5555 offline
USB09 unauthorized usb:1-3
"""
        items = adb_client.parse_devices(text)
        self.assertEqual(len(items), 3)
        self.assertEqual([d.state for d in items], ["device", "offline", "unauthorized"])

    def test_private_endpoint(self):
        self.assertEqual(adb_client.validate_lan_endpoint("192.168.0.4"), "192.168.0.4:5555")
        self.assertEqual(adb_client.validate_lan_endpoint("10.1.2.3:37099"), "10.1.2.3:37099")
        for value in ["8.8.8.8", "127.0.0.1", "169.254.8.8", "999.0.0.1", "192.168.1.3:70000", "192.168.1.3;reboot"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    adb_client.validate_lan_endpoint(value)

    def test_parse_ip(self):
        ips = adb_client.parse_lan_ips("""2: wlan0 inet 192.168.0.1/24
3: eth0 inet 10.20.1.33/16
4: lo inet 127.0.0.1/8
5: random inet 169.254.1.1/32""")
        self.assertEqual(ips, ["192.168.0.1", "10.20.1.33"])

    def test_package_guard(self):
        self.assertTrue(adb_client.PKG_RE.fullmatch("com.example.app"))
        self.assertFalse(adb_client.PKG_RE.fullmatch("com.example;reboot"))
        self.assertFalse(adb_client.PKG_RE.fullmatch("com.example.app -x"))


class FakeADB:
    def __init__(self):
        self.commands = []
        self.version = "releases/2.0.0/desktopd"
        self.fail_start = False

    def shell(self, serial, *args, timeout=20):
        self.commands.append(("shell", serial, *args))
        if args[0] == "readlink":
            return self.version
        if args[0] == "getprop":
            return "arm64-v8a"
        if args[0] == "cat":
            return "0123456789abcdef0123456789abcdef"
        if args[:2] == ("sh", "/data/local/tmp/android-web-desktop/start.sh") and self.fail_start:
            raise adb_client.ADBError("start denied")
        return ""

    def getprop(self, serial, key):
        return "arm64-v8a"

    def packages(self, serial, system=False):
        return ["com.android.systemui", "com.vendor.feature"]

    def selected(self, serial, *args, timeout=20):
        self.commands.append(("selected", serial, *args))
        return "uploaded"


def arm64_elf():
    b = bytearray(200)
    b[:4] = b"\x7fELF"
    b[4] = 2
    b[5] = 1
    b[18:20] = (183).to_bytes(2, "little")
    return bytes(b)


def package_zip(version="2.1.0", binary=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("VERSION", version + "\n")
        z.writestr("desktopd", binary if binary is not None else arm64_elf())
        z.writestr("installer/start.sh", "#!/system/bin/sh\necho start\n")
        z.writestr("installer/stop.sh", "#!/system/bin/sh\necho stop\n")
    return buf.getvalue()


class TestDeployment(unittest.TestCase):
    def test_parse_package(self):
        package = deployment.parse_package(package_zip())
        self.assertEqual(package.version, "2.1.0")
        self.assertEqual(package.files["desktopd"][:4], b"\x7fELF")
        with self.assertRaisesRegex(ValueError, "不是 Android ARM64"):
            deployment.parse_package(package_zip(binary=b"\x7fELF" + bytes(196)))
        with self.assertRaisesRegex(ValueError, "版本号"):
            deployment.parse_package(package_zip(version="../2.1.0"))
        with self.assertRaises(Exception):
            deployment.parse_package(b"not a zip")

    def test_release_must_be_pinned(self):
        base = {"tag_name": "v2.1.0", "body": "中文更新说明"}
        good = {
            **base,
            "assets": [{
                "name": deployment.PACKAGE_NAME,
                "browser_download_url": "https://github.com/nljie1103/u30air-web-console/releases/download/v2.1.0/android-web-desktop-arm64.zip",
                "digest": "sha256:" + ("a" * 64),
            }],
        }
        self.assertEqual(deployment.parse_release(good)["version"], "2.1.0")
        bad = json.loads(json.dumps(good))
        bad["assets"][0]["browser_download_url"] = "https://evil.example/exe"
        with self.assertRaisesRegex(ValueError, "不可信"):
            deployment.parse_release(bad)
        bad = json.loads(json.dumps(good))
        bad["assets"][0]["digest"] = ""
        with self.assertRaisesRegex(ValueError, "SHA256"):
            deployment.parse_release(bad)

    def test_install_and_uninstall(self):
        fake = FakeADB()
        package = deployment.parse_package(package_zip())
        url, password = deployment.install_on_device(fake, "usb-1", package, "192.168.0.1")
        self.assertEqual(url, "http://192.168.0.1:8765")
        self.assertEqual(len(password), 32)
        self.assertTrue(any("push" in c for c in fake.commands))
        self.assertTrue(any("mv" in c for c in fake.commands))
        fake.version = "releases/2.1.0/desktopd"
        response = deployment.uninstall_from_device(fake, "usb-1")
        self.assertIn("卸载", response)
        self.assertEqual(fake.commands[-1][-2:], ("-rf", adb_client.DATA_DIR))

    def test_install_restore_old_version_when_start_fails(self):
        fake = FakeADB()
        fake.fail_start = True
        with self.assertRaises(adb_client.ADBError):
            deployment.install_on_device(fake, "usb-1", deployment.parse_package(package_zip()), "192.168.0.1")
        restores = [c for c in fake.commands if "releases/2.0.0/desktopd" in c]
        self.assertTrue(restores)

    def test_remove_core_apps_blocked(self):
        fake = FakeADB()
        with patch.object(fake, "packages", return_value=["com.android.systemui", "com.vendor.feature"]):
            with self.assertRaisesRegex(ValueError, "关键"):
                adb_client.ADB.toggle_system_app(fake, "usb-1", "com.android.systemui", False)
            with self.assertRaisesRegex(ValueError, "不合法"):
                adb_client.ADB.toggle_system_app(fake, "usb-1", "com.vendor.feature;rm", False)


if __name__ == "__main__":
    unittest.main()
