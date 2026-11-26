"""Regression tests for the private, allowlisted subprocess protocol."""
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker import serve


class Stub:
    def environment(self):
        return {"version": "3.0.0", "adb_found": False, "adb_path": ""}

    def install_application(self, serial, source, remote):
        return [serial, source, remote]

    def list_devices(self):
        raise ValueError("未找到设备")


class TestWorker(unittest.TestCase):
    def test_rpc_results_errors_and_rejected_arbitrary_calls(self):
        items = [
            {"id": 1, "method": "environment", "args": []},
            {"id": 2, "method": "install_application", "args": ["serial", "https://example.com/a.apk", True]},
            {"id": 3, "method": "exec_command", "args": ["danger"]},
            {"id": 4, "method": "list_devices", "args": []},
            {"id": 5, "method": "environment", "args": "invalid"},
        ]
        source = io.StringIO("\n".join(map(json.dumps, items)) + "\ninvalid\n")
        target = io.StringIO()
        serve(source, target, Stub())
        replies = {r["id"]: r for r in map(json.loads, target.getvalue().splitlines())}
        self.assertEqual(replies[1]["result"]["version"], "3.0.0")
        self.assertEqual(replies[2]["result"], ["serial", "https://example.com/a.apk", True])
        self.assertFalse(replies[3]["ok"])
        self.assertEqual(replies[4]["error"], "未找到设备")
        self.assertFalse(replies[5]["ok"])
