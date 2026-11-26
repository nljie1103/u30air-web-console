"""Loopback-only server for packaged Vite ES modules.

Only the index document and directly stored, non-symlinked Vite asset files
are served; no data or system-management APIs are exposed.
"""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from threading import Thread
from urllib.parse import urlsplit

_ASSET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:js|css|png|svg|ico|woff2?)\Z")


class FrontendHandler(SimpleHTTPRequestHandler):
    def _allowed(self) -> bool:
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403, "Invalid host")
            return False
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            return True

        # SimpleHTTPRequestHandler URL-decodes paths internally: validating
        # only the raw slash count permits /assets/%2e%2e%2fsecret.txt.
        # Require an exact, already-normalized direct child of assets.
        if not path.startswith("/assets/"):
            self.send_error(404, "Not found")
            return False
        name = path[len("/assets/"):]
        if not _ASSET_NAME.fullmatch(name) or ".." in name:
            self.send_error(404, "Not found")
            return False
        base = Path(self.directory).resolve() / "assets"
        candidate = base / name
        if not candidate.is_file() or candidate.is_symlink() or candidate.resolve().parent != base:
            self.send_error(404, "Not found")
            return False
        return True

    def do_GET(self) -> None:
        if self._allowed():
            return super().do_GET()

    def do_HEAD(self) -> None:
        if self._allowed():
            return super().do_HEAD()

    def do_POST(self) -> None:
        self.send_error(405, "Method not allowed")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def log_message(self, *_args) -> None:
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
