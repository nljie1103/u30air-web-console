"""Microsoft Edge app-mode host for the Windows manager.

The original WinForms/pythonnet/WebView2 host could lock up on interactive
window dragging. Edge app mode delegates OS chrome/move/resize handling to a
real browser process, while exposing only a narrow loopback HTTP bridge.
"""
from __future__ import annotations

from functools import partial
import hmac
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from threading import Thread
from urllib.parse import urlsplit

from local_server import FrontendHandler

_ALLOWED_METHODS = frozenset({
    "environment", "list_devices", "device_info", "list_apps", "connect",
    "set_adb_path", "choose_adb", "choose_local_zip", "install_official_adb",
    "check_release", "install_latest", "install_local", "uninstall",
    "uninstall_app", "set_system_app", "reboot", "poweroff", "open_web",
    "get_logs", "clear_logs",
})
_MAX_BODY = 32 * 1024

_BRIDGE_JS = r"""
(() => {
  const key = __TOKEN__;
  const methods = __METHODS__;
  const api = Object.create(null);
  for (const method of methods) {
    api[method] = async (...args) => {
      const response = await fetch('/_awd/api', {
        method: 'POST',
        mode: 'same-origin',
        credentials: 'omit',
        cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-AWD-Session': key},
        body: JSON.stringify({method, args})
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || '本机管理操作失败');
      return data.result;
    };
  }
  window.pywebview = {api};
  document.dispatchEvent(new Event('awdbridgeready'));
  window.dispatchEvent(new Event('pywebviewready'));
})();
"""


class EdgeHandler(FrontendHandler):
    def _json_response(self, status: int, value: dict) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if not self._allowed():
            return
        path = urlsplit(self.path).path
        if path not in {"/", "/index.html"}:
            return super().do_GET()
        # No cache: the bridge session and bound port change every launch.
        html = (Path(self.directory) / "index.html").read_text(encoding="utf-8")
        token = json.dumps(self.server.session_key)
        methods = json.dumps(sorted(_ALLOWED_METHODS))
        script = _BRIDGE_JS.replace("__TOKEN__", token).replace("__METHODS__", methods)
        if "</head>" not in html:
            self.send_error(500, "Invalid Vue frontend")
            return
        html = html.replace("</head>", "<script>" + script + "</script></head>", 1)
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; font-src 'self' data:; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if not self._allowed_host():
            return
        if urlsplit(self.path).path != "/_awd/api":
            self.send_error(404)
            return
        expected_origin = "http://127.0.0.1:" + str(self.server.server_port)
        # Strict origin / custom header checks prevent a malicious website
        # from issuing privileged ADB requests through the loopback service.
        if self.headers.get("Origin") != expected_origin:
            self.send_error(403, "Invalid origin")
            return
        if not hmac.compare_digest(
            self.headers.get("X-AWD-Session", ""), self.server.session_key
        ):
            self.send_error(403, "Invalid session")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self.send_error(415, "JSON requests only")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= _MAX_BODY:
            self.send_error(413, "Request is too large")
            return
        try:
            req = json.loads(self.rfile.read(length))
            if not isinstance(req, dict):
                raise ValueError("请求格式错误")
            name = req.get("method")
            args = req.get("args")
            if not isinstance(name, str) or name not in _ALLOWED_METHODS:
                self._json_response(404, {"ok": False, "error": "未知管理接口"})
                return
            if not isinstance(args, list) or len(args) > 8:
                raise ValueError("调用参数错误")
            func = getattr(self.server.bridge, name)
            result = func(*args)
            self._json_response(200, {"ok": True, "result": result})
        except (ValueError, TypeError, OSError, RuntimeError) as exc:
            self._json_response(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json_response(500, {"ok": False, "error": "操作执行失败：" + str(exc)})

    def _allowed_host(self) -> bool:
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403, "Invalid host")
            return False
        return True

    def do_HEAD(self) -> None:
        if self._allowed_host():
            super().do_HEAD()

    def do_OPTIONS(self) -> None:
        self.send_error(405, "CORS requests are not permitted")


def start_edge_server(dist_dir: Path, bridge) -> tuple[ThreadingHTTPServer, str]:
    root = dist_dir.resolve()
    if not (root / "index.html").is_file() or not (root / "assets").is_dir():
        raise FileNotFoundError(f"Vue frontend build is missing: {root}")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(EdgeHandler, directory=str(root))
    )
    server.daemon_threads = True
    server.bridge = bridge
    server.session_key = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{server.server_port}/index.html"
    Thread(target=server.serve_forever, name="EdgeAppBridge", daemon=True).start()
    return server, url
