"""Loopback-only static server for the bundled Vite ES-module assets.

Using file:// breaks ES module loading in Chromium/WebView2. The loopback
server is bound to a random port and does not provide any ADB API endpoints.
"""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit


class FrontendHandler(SimpleHTTPRequestHandler):
    def _allowed(self) -> bool:
        # Reject DNS rebinding and non-static paths before filesystem translation.
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403, "Invalid host")
            return False
        path = urlsplit(self.path).path
        if not (path in {"/", "/index.html"} or (path.startswith("/assets/") and path.count("/") == 2)):
            self.send_error(404, "Not found")
            return False
        return True

    def do_GET(self):
        if self._allowed():
            return super().do_GET()

    def do_HEAD(self):
        if self._allowed():
            return super().do_HEAD()

    def do_POST(self):
        self.send_error(405, "Method not allowed")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def log_message(self, *_args):
        # Avoid exposing local filesystem and session details to stdout.
        return None


def start_frontend_server(dist_dir: Path) -> tuple[ThreadingHTTPServer, str]:
    root = dist_dir.resolve()
    if not (root / "index.html").is_file() or not (root / "assets").is_dir():
        raise FileNotFoundError(f"Vue frontend build is missing: {root}")
    handler = partial(FrontendHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}/index.html"
    Thread(target=server.serve_forever, name="VueFrontendHTTP", daemon=True).start()
    return server, url
