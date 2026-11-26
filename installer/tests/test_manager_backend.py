import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

MANAGER_DIR = Path(__file__).resolve().parents[1]
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
        for value in ["8.8.8.8", "127.0.0.1", "169.254.8.8", "999.0.0.1", "198.18.0.1", "192.168.1.3:70000", "192.168.1.3;reboot"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    adb_client.validate_lan_endpoint(value)

    def test_parse_ip(self):
        ips = adb_client.parse_lan_ips("""2: wlan0 inet 192.168.0.1/24
3: eth0 inet 10.20.1.33/16
4: lo inet 127.0.0.1/8
5: random inet 169.254.1.1/32""")
        self.assertEqual(ips, ["192.168.0.1", "10.20.1.33"])

    def test_hotspot_gateway_is_prioritized_over_cellular_and_usb(self):
        raw = """8: rmnet_data0    inet 10.129.230.33/30 scope global rmnet_data0
9: rndis0    inet 10.10.14.1/24 scope global rndis0
10: br0    inet 192.168.0.1/24 scope global br0
1: lo    inet 127.0.0.1/8 scope host lo"""
        info = adb_client.parse_network_addresses(raw)
        self.assertEqual([v["ip"] for v in info],
                         ["192.168.0.1", "10.10.14.1", "10.129.230.33"])
        self.assertEqual(info[-1]["role"], "蜂窝/隧道")
        self.assertEqual(adb_client.parse_lan_ips(raw),
                         ["192.168.0.1", "10.10.14.1"])

    def test_mobile_private_ip_must_not_be_treated_as_hotspot(self):
        raw = """3: rmnet_data2 inet 10.129.230.33/30 scope global
4: ccmni0 inet 10.25.44.17/29 scope global
5: tun0 inet 10.0.5.2/24 scope global"""
        self.assertEqual(adb_client.parse_lan_ips(raw), [])
        self.assertEqual(len(adb_client.parse_network_addresses(raw)), 3)

    def test_private_ip_not_automatically_public_lan(self):
        raw = "2: wlan0 inet 198.18.0.1/16 scope global"
        self.assertEqual(adb_client.parse_lan_ips(raw), [])

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
    def test_deployment_rejects_unassigned_and_cellular_addresses_before_install(self):
        class NetworkADB(FakeADB):
            def shell(self, serial, *args, timeout=20):
                if args[:4] == ("ip", "-o", "-4", "addr"):
                    return """9: rmnet_data0 inet 10.129.230.33/30
10: br0 inet 192.168.0.1/24"""
                return super().shell(serial, *args, timeout=timeout)
        fake = NetworkADB()
        pack = deployment.parse_package(package_zip())
        for ip, message in (
            ("10.129.230.33", "蜂窝"),
            ("192.168.0.99", "没有配置"),
        ):
            with self.subTest(ip=ip):
                with self.assertRaisesRegex(adb_client.ADBError, message):
                    deployment.install_on_device(fake, "usb-1", pack, ip)
        self.assertFalse(any("push" in c for c in fake.commands),
                         "An invalid address must not interrupt or stage deployment")

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
        with patch.object(deployment, "verify_remote_service") as health:
            url, password = deployment.install_on_device(fake, "usb-1", package, "192.168.0.1")
        health.assert_called_once()
        self.assertEqual(url, "http://192.168.0.1:8765")
        self.assertEqual(len(password), 32)
        self.assertTrue(any("push" in c for c in fake.commands))
        self.assertTrue(any("mv" in c for c in fake.commands))
        fake.version = "releases/2.1.0/desktopd"
        response = deployment.uninstall_from_device(fake, "usb-1")
        self.assertIn("卸载", response)
        self.assertEqual(fake.commands[-1][-2:], ("-rf", adb_client.DATA_DIR))

    def test_same_version_reinstall_uses_staging_and_backup(self):
        fake = FakeADB()
        fake.version = "releases/2.1.0/desktopd"
        with patch.object(deployment, "verify_remote_service") as health:
            url, password = deployment.install_on_device(
                fake, "usb-1", deployment.parse_package(package_zip()), "192.168.0.1"
            )
        health.assert_called_once()
        self.assertEqual(url, "http://192.168.0.1:8765")
        uploads = [c for c in fake.commands if c[0] == "selected" and "push" in c]
        self.assertTrue(any(c[-1].endswith("desktopd.next") for c in uploads))
        self.assertFalse(any(c[-1].endswith("/desktopd") for c in uploads))
        backups = [i for i, c in enumerate(fake.commands) if c[0] == "shell" and c[2] == "cp"]
        stops = [i for i, c in enumerate(fake.commands) if c[0] == "shell" and c[2:4] == ("sh", adb_client.DATA_DIR + "/stop.sh")]
        self.assertGreaterEqual(len(backups), 3)
        self.assertTrue(stops)
        self.assertLess(max(backups), min(stops))
        self.assertTrue(any(c[-2:] == ("-f", adb_client.DATA_DIR + "/releases/2.1.0/desktopd.rollback") for c in fake.commands))

    def test_same_version_failure_restores_executable(self):
        fake = FakeADB()
        fake.version = "releases/2.1.0/desktopd"
        with patch.object(deployment, "verify_remote_service", side_effect=adb_client.ADBError("new server crashed")):
            with self.assertRaisesRegex(adb_client.ADBError, "new server crashed"):
                deployment.install_on_device(fake, "usb-1", deployment.parse_package(package_zip()), "192.168.0.1")
        commands = fake.commands
        self.assertTrue(any(c[2:5] == ("mv", "-f", adb_client.DATA_DIR + "/releases/2.1.0/desktopd.rollback") for c in commands))
        self.assertFalse(any(c[2:5] == ("rm", "-f", adb_client.DATA_DIR + "/releases/2.1.0/desktopd.rollback") for c in commands))

    def test_refuses_old_pid_without_new_process(self):
        fake = FakeADB()
        fake.version = "releases/2.1.0/desktopd"
        old_shell = fake.shell
        def with_pid(serial, *args, timeout=20):
            if args == ("cat", adb_client.DATA_DIR + "/server.pid"):
                fake.commands.append(("shell", serial, *args))
                return "1234"
            return old_shell(serial, *args, timeout=timeout)
        fake.shell = with_pid
        with patch.object(deployment, "verify_remote_service") as health:
            with self.assertRaisesRegex(adb_client.ADBError, "旧进程"):
                deployment.install_on_device(fake, "usb-1", deployment.parse_package(package_zip()), "192.168.0.1")
        health.assert_not_called()

    def test_install_restore_old_version_when_start_fails(self):
        fake = FakeADB()
        fake.fail_start = True
        with self.assertRaises(adb_client.ADBError):
            deployment.install_on_device(fake, "usb-1", deployment.parse_package(package_zip()), "192.168.0.1")
        restores = [c for c in fake.commands if "releases/2.0.0/desktopd" in c]
        self.assertTrue(restores)

    def test_install_rolls_back_when_health_fails(self):
        fake = FakeADB()
        with patch.object(deployment, "verify_remote_service", side_effect=adb_client.ADBError("service not ready")):
            with self.assertRaisesRegex(adb_client.ADBError, "service not ready"):
                deployment.install_on_device(fake, "usb-1", deployment.parse_package(package_zip()), "192.168.0.1")
        self.assertTrue(any("releases/2.0.0/desktopd" in command for command in fake.commands))

    def test_first_install_failure_clears_version_pointer(self):
        fake = FakeADB()
        fake.version = ""
        with patch.object(deployment, "verify_remote_service", side_effect=adb_client.ADBError("health unavailable")):
            with self.assertRaises(adb_client.ADBError):
                deployment.install_on_device(fake, "usb-1", deployment.parse_package(package_zip()), "192.168.0.1")
        self.assertTrue(any(c[-3:] == ("rm", "-f", adb_client.DATA_DIR+"/current") for c in fake.commands))

    def test_adb_forwarded_health_verification(self):
        import io
        class Response:
            status = 200
            def __init__(self, data):
                self.data = data
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, *_): return self.data
        class Opener:
            def __init__(self, payload): self.payload = payload
            def open(self, url, timeout):
                if url != "http://127.0.0.1:33861/healthz":
                    raise AssertionError("Health target must remain loopback only")
                return Response(self.payload)
        fake = FakeADB()
        original_shell = fake.shell
        def read_health_port(serial, *args, timeout=20):
            if args == ("cat", adb_client.DATA_DIR+"/health.port"):
                return "37123"
            return original_shell(serial, *args, timeout=timeout)
        fake.shell = read_health_port
        original_selected = fake.selected
        def forward(serial, *args, timeout=20):
            if args == ("forward", "tcp:0", "tcp:37123"):
                fake.commands.append(("forward", serial, *args))
                return "33861"
            return original_selected(serial, *args, timeout=timeout)
        fake.selected = forward
        data = b'{"status":"ok","version":"2.2.1","ready":true}'
        with patch.object(deployment, "build_opener", return_value=Opener(data)):
            deployment.verify_remote_service(fake, "usb-1", "2.2.1")
        self.assertTrue(any("forward" in c and "--remove" in c for c in fake.commands))
        bad = b'{"status":"ok","version":"2.2.0","ready":true}'
        with patch.object(deployment, "build_opener", return_value=Opener(bad)):
            with patch.object(deployment.time, "sleep"):
                with self.assertRaisesRegex(adb_client.ADBError, "版本"):
                    deployment.verify_remote_service(fake, "usb-1", "2.2.1")

    def test_invalid_install_ip(self):
        for ip in ("0.0.0.0", "127.0.0.1", "8.8.8.8", "169.254.0.5"):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                deployment.install_on_device(FakeADB(), "usb-1", deployment.parse_package(package_zip()), ip)

    def test_remove_core_apps_blocked(self):
        fake = FakeADB()
        with patch.object(fake, "packages", return_value=[
            "com.android.systemui", "com.google.android.gms", "com.google.android.webview",
            "com.android.tethering", "com.vendor.feature"
        ]):
            for package in ("com.android.systemui", "com.google.android.gms",
                            "com.google.android.webview", "com.android.tethering"):
                with self.subTest(package=package):
                    with self.assertRaisesRegex(ValueError, "关键"):
                        adb_client.ADB.toggle_system_app(fake, "usb-1", package, False)
            with self.assertRaisesRegex(ValueError, "不合法"):
                adb_client.ADB.toggle_system_app(fake, "usb-1", "com.vendor.feature;rm", False)


if __name__ == "__main__":
    unittest.main()
