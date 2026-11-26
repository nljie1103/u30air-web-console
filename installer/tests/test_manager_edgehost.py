"""Loopback HTTP bridge tests: security, compatibility and concurrency."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edge_host import start_edge_server


class StubBridge:
    def environment(self):
        return {"version": "2.4.0", "adb_found": True, "adb_path": "C:\\adb.exe"}

    def list_devices(self):
        time.sleep(0.15)
        return [{"serial": "USB-MOCK", "state": "device", "detail": "test device"}]

    def get_logs(self):
        return []

    def reboot(self, serial):
        return "reboot " + serial


class TestEdgeHost(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        p = Path(self.folder.name)
        (p / "assets").mkdir()
        (p / "index.html").write_text(
            '<html><head></head><body><div id="app"></div></body></html>',
            encoding="utf-8",
        )
        (p / "assets" / "index-test.js").write_text("console.log('ok')", encoding="utf-8")
        (p / "secret.txt").write_text("do-not-read", encoding="utf-8")
        self.server, self.url = start_edge_server(p, StubBridge())
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, method, path, body=b"", **extra_headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {
            "Host": f"127.0.0.1:{self.server.server_port}",
            "Origin": self.origin,
            "Content-Type": "application/json",
            "X-AWD-Session": self.server.session_key,
        }
        headers.update(extra_headers)
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return result

    def invoke(self, name, *args, **extra):
        return self.request(
            "POST", "/_awd/api", json.dumps({"method": name, "args": args}).encode(),
            **extra,
        )

    def test_bootstrap_and_assets(self):
        status, body, headers = self.request("GET", "/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"window.pywebview = {api}", body)
        self.assertIn(self.server.session_key.encode(), body)
        self.assertIn(b"Content-Security-Policy".lower(), str(headers).lower().encode())
        self.assertEqual(self.request("GET", "/assets/index-test.js")[0], 200)
        for path in ("/secret.txt", "/assets/%2e%2e%2fsecret.txt", "/_awd/api"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_method_dispatch(self):
        code, data, _ = self.invoke("environment")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)["result"]["version"], "2.4.0")
        code, data, _ = self.invoke("reboot", "USB-MOCK")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)["result"], "reboot USB-MOCK")
        self.assertEqual(self.invoke("this_method_does_not_exist")[0], 404)
        self.assertEqual(self.invoke("__class__")[0], 404)

    def test_cross_origin_and_session_protection(self):
        self.assertEqual(
            self.invoke("reboot", "USB", Origin="https://untrusted.example")[0], 403
        )
        self.assertEqual(self.invoke("reboot", "USB", **{"X-AWD-Session": ""})[0], 403)
        self.assertEqual(self.invoke("reboot", "USB", Host="untrusted.example")[0], 403)
        self.assertEqual(self.request("OPTIONS", "/_awd/api")[0], 405)
        self.assertEqual(
            self.request("POST", "/_awd/api", body=b"x" * 40000)[0], 413
        )

    def test_slow_adb_call_does_not_block_other_methods(self):
        import threading
        result = []
        worker = threading.Thread(
            target=lambda: result.append(self.invoke("list_devices")[0])
        )
        worker.start()
        time.sleep(0.025)
        started = time.monotonic()
        self.assertEqual(self.invoke("environment")[0], 200)
        self.assertLess(time.monotonic() - started, 0.13)
        worker.join(timeout=3)
        self.assertEqual(result, [200])


if __name__ == "__main__":
    unittest.main()
