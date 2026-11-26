"""Device-information performance regression tests (no actual ADB device required)."""
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adb_client import ADB, ADBError


class SimulatedWirelessADB(ADB):
    def __init__(self, delay=0.10):
        self.delay = delay
        self.commands = []
        self.guard = threading.Lock()

    def shell(self, serial: str, *args: str, timeout: int = 20) -> str:
        with self.guard:
            self.commands.append((serial, args))
        time.sleep(self.delay)
        if args[0] == "getprop":
            return """[ro.product.manufacturer]: [Google]
[ro.product.brand]: [Google]
[ro.product.model]: [Pixel Mock]
[ro.build.version.release]: [16]
[ro.build.version.sdk]: [36]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.build.display.id]: [MOCK-123]
[ro.serialno]: [ABC123]
"""
        if args[0] == "ip":
            return "2: wlan0 inet 192.168.0.1/24"
        if args[0] == "readlink":
            return "releases/2.2.2/desktopd"
        if args[0] == "cat" and args[1].endswith("/server.pid"):
            return "1234"
        if args[0] == "cat" and args[1] == "/proc/1234/cmdline":
            return "/data/local/tmp/android-web-desktop/current\x00-listen\x00192.168.0.1:8765\x00"
        raise AssertionError(args)


class TestDeviceInfoPerformance(unittest.TestCase):
    def test_bulk_properties_and_parallel_requests(self):
        device = SimulatedWirelessADB()
        started = time.monotonic()
        result = device.device_info("USB-TEST")
        elapsed = time.monotonic() - started
        self.assertEqual(result["model"], "Pixel Mock")
        self.assertEqual(result["android"], "16")
        self.assertEqual(result["ips"], ["192.168.0.1"])
        self.assertEqual(result["installed_version"], "2.2.2")
        self.assertEqual(result["listening_address"], "192.168.0.1:8765")
        self.assertEqual(len(device.commands), 5, "device_info must not spawn per-property adb processes")
        # Listener detail adds two dependent calls in one parallel task.
        self.assertLess(elapsed, 0.5)

    def test_failure_of_one_component_preserves_other_details(self):
        device = SimulatedWirelessADB(delay=0)
        original_shell = device.shell

        def partial_failure(serial, *args, timeout=20):
            if args[0] == "ip":
                raise ADBError("network interface unavailable")
            return original_shell(serial, *args, timeout=timeout)

        device.shell = partial_failure
        data = device.device_info("USB-TEST")
        self.assertEqual(data["model"], "Pixel Mock")
        self.assertEqual(data["ips"], [])
        self.assertEqual(data["installed_version"], "2.2.2")


if __name__ == "__main__":
    unittest.main()
