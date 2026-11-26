"""Safety checks for the universal Linux/macOS fallback installer."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(os.name == "nt", "Linux installer checks run on Linux CI")
class TestLinuxInstaller(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.install_dir = root / "installer"
        self.install_dir.mkdir()
        shutil.copy2(ROOT / "web-console" / "deploy" / "install_linux_mac.sh", self.install_dir / "install_linux_mac.sh")
        shutil.copy2(ROOT / "web-console" / "deploy" / "start.sh", self.install_dir / "start.sh")
        shutil.copy2(ROOT / "web-console" / "deploy" / "stop.sh", self.install_dir / "stop.sh")
        (root / "VERSION").write_text("2.2.2\n")
        (root / "desktopd").write_bytes(b"ELF test only")
        self.bin_dir = root / "bin"
        self.bin_dir.mkdir()
        self.fake_adb = self.bin_dir / "adb"
        self.fake_adb.write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$AWD_FAKE_ADB_LOG"
case "$*" in
  "devices -l") printf 'List of devices attached\\nusb-test    device\\n' ;;
  "-s usb-test get-state") printf 'device\\n' ;;
  "-s usb-test shell getprop ro.product.cpu.abi") printf 'arm64-v8a\\n' ;;
  "-s usb-test shell readlink /data/local/tmp/android-web-desktop/current")
      printf '%s\\n' "$AWD_FAKE_CURRENT" ;;
  "-s usb-test shell cat /data/local/tmp/android-web-desktop/password.txt")
      printf '0123456789abcdef0123456789abcdef\\n' ;;
  *) : ;;
esac
""")
        self.fake_adb.chmod(0o700)
        self.log = root / "commands.log"

    def run_installer(self, previous: str):
        env = os.environ.copy()
        env.update(
            PATH=str(self.bin_dir) + os.pathsep + env["PATH"],
            AWD_FAKE_CURRENT=previous,
            AWD_FAKE_ADB_LOG=str(self.log),
        )
        return subprocess.run(
            ["bash", str(self.install_dir / "install_linux_mac.sh"), "usb-test", "192.168.1.20"],
            capture_output=True, text=True, timeout=20, env=env,
        )

    def test_same_version_aborts_before_upload(self):
        result = self.run_installer("releases/2.2.2/desktopd")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Same version", result.stdout)
        self.assertNotIn("push ", self.log.read_text())

    def test_different_version_stages_binary(self):
        result = self.run_installer("releases/2.2.1/desktopd")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.log.read_text()
        self.assertIn("desktopd.next", commands)
        self.assertIn("start.sh.next", commands)
        self.assertIn("stop.sh.next", commands)
        self.assertNotIn("push desktopd /data/local/tmp/android-web-desktop/releases/2.2.2/desktopd\n", commands)


if __name__ == "__main__":
    unittest.main()
