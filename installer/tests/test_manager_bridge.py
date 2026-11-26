"""Focused safety and integration tests for the Vue/WebView2 bridge."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIR))
from bridge import DesktopBridge


class TestDesktopBridge(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bridge = DesktopBridge()

    def test_version_and_config(self):
        env = self.bridge.environment()
        self.assertEqual(env["version"], "2.3.2")
        self.assertIn("adb_found", env)
        self.assertTrue(Path(self.bridge.settings_file).parent.is_dir())

    def test_private_ip_validation(self):
        for valid in ("192.168.1.1", "10.20.0.3", "172.20.1.1"):
            self.assertEqual(DesktopBridge._validate_ip(valid), valid)
        for invalid in ("8.8.8.8", "127.0.0.1", "169.254.2.3", "0.0.0.0",
                        "192.168.1.1;shutdown", "example.com"):
            with self.subTest(invalid=invalid):
                with self.assertRaises((ValueError, TypeError)):
                    DesktopBridge._validate_ip(invalid)

    def test_missing_adb_fails_safely(self):
        self.bridge.adb_path = None
        with self.assertRaisesRegex(ValueError, "ADB"):
            self.bridge.list_devices()

    def test_operation_failure_recorded_and_lock_released(self):
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            self.bridge._execute("模拟操作", lambda: (_ for _ in ()).throw(RuntimeError("simulated")))
        entries = self.bridge.get_logs()
        self.assertEqual(entries[-1]["level"], "error")
        self.assertIn("模拟操作", entries[-1]["message"])
        self.assertEqual(self.bridge._execute("第二次", lambda: 42), 42)

    def test_log_clear_does_not_reappear_on_poll(self):
        self.bridge.log("hello")
        self.assertEqual(len(self.bridge.get_logs()), 1)
        self.assertTrue(self.bridge.clear_logs())
        self.assertEqual(self.bridge.get_logs(), [])

    def test_user_approval_required_by_frontend_not_backend(self):
        # Bridge does not offer arbitrary command execution or generic shell APIs.
        for name in ("run_shell", "exec_command", "root", "adb_shell"):
            self.assertFalse(hasattr(self.bridge, name))


if __name__ == "__main__":
    unittest.main()
