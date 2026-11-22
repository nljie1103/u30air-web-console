"""Loopback-only frontend server regression tests."""
from pathlib import Path
import http.client
import sys
import tempfile
import unittest

MANAGER_DIR = Path(__file__).resolve().parents[1] / "manager"
sys.path.insert(0, str(MANAGER_DIR))
from local_server import start_frontend_server


class TestLocalFrontend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "assets").mkdir()
        (root / "index.html").write_text('<div id="app"></div>', encoding="utf-8")
        (root / "assets" / "index-test.js").write_text('console.log("ok");', encoding="utf-8")
        (root / "secret.txt").write_text("never serve", encoding="utf-8")
        self.server, _ = start_frontend_server(root)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path: str, method="GET", host: str | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request(method, path, headers={"Host": host or f"127.0.0.1:{self.server.server_port}"})
        response = conn.getresponse()
        result = (response.status, response.read(), response.getheaders())
        conn.close()
        return result

    def test_serves_only_html_and_assets(self):
        status, body, _ = self.get("/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b'id="app"', body)
        status, body, _ = self.get("/assets/index-test.js")
        self.assertEqual(status, 200)
        self.assertIn(b'console.log', body)
        for path in (
            "/secret.txt", "/../secret.txt", "/settings", "/api/devices",
            "/assets/%2e%2e%2fsecret.txt", "/assets/%252e%252e%252fsecret.txt",
            "/assets/%2e%2e%5csecret.txt", "/assets/test%2ejs",
            "/assets/../secret.txt", "/assets/./index-test.js",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)

    def test_rejects_asset_symlinks(self):
        root = Path(self.tmp.name)
        (root / "assets" / "linked.js").symlink_to(root / "secret.txt")
        self.assertEqual(self.get("/assets/linked.js")[0], 404)

    def test_rejects_dns_rebinding_and_post(self):
        self.assertEqual(self.get("/index.html", host="untrusted.example")[0], 403)
        self.assertEqual(self.get("/index.html", method="POST")[0], 405)

    def test_headers(self):
        status, _, headers = self.get("/index.html")
        self.assertEqual(status, 200)
        values = dict(headers)
        self.assertEqual(values.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(values.get("Cache-Control"), "no-store")


if __name__ == "__main__":
    unittest.main()
