"""Windows desktop entry: Vue 3 over local HTTP + WebView2 + controlled ADB bridge."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
import time
from urllib.request import urlopen

from bridge import DesktopBridge
from local_server import start_frontend_server

APP_VERSION = "2.2.1"


def frontend_file() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "manager" / "frontend" / "dist" / "index.html"


def self_test(frontend_dir: Path) -> None:
    bridge = DesktopBridge()
    if bridge.environment()["version"] != APP_VERSION:
        raise RuntimeError("Python bridge version mismatch")
    server, url = start_frontend_server(frontend_dir)
    try:
        with urlopen(url, timeout=3) as response:
            html = response.read(100_000).decode("utf-8")
            if response.status != 200 or 'id="app"' not in html or "/src/main.ts" in html:
                raise RuntimeError("Production Vue index.html was not served")
        from html.parser import HTMLParser

        class ScriptFinder(HTMLParser):
            def __init__(self):
                super().__init__()
                self.assets: list[str] = []
            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if value and (key in ("src", "href")) and "assets/" in value:
                        self.assets.append(value.lstrip("./"))

        finder = ScriptFinder()
        finder.feed(html)
        if not finder.assets:
            raise RuntimeError("Vite production assets are missing")
        base = url.rsplit("/", 1)[0] + "/"
        for asset in finder.assets:
            with urlopen(base + asset, timeout=3) as response:
                if response.status != 200 or len(response.read(2_000_000)) < 8:
                    raise RuntimeError("Failed to serve Vue asset: " + asset)
        print(f"Android Web Desktop Manager v{APP_VERSION}: Vue local HTTP and Python bridge OK")
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Android Web Desktop Manager")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-smoke-test", action="store_true")
    args = parser.parse_args()

    index = frontend_file()
    if not index.is_file():
        raise SystemExit("Vue frontend build missing. Run npm run build in manager/frontend.")

    if args.self_test:
        self_test(index.parent)
        return

    try:
        import webview
    except ImportError as exc:
        raise SystemExit("pywebview is not installed") from exc

    server, url = start_frontend_server(index.parent)
    try:
        bridge = DesktopBridge()
        window = webview.create_window(
            title=f"Android Web Desktop  ·  v{APP_VERSION}",
            url=url,
            js_api=bridge,
            width=1360,
            height=860,
            min_size=(1000, 650),
            background_color="#f8fafc",
        )
        bridge.window = window

        def on_ready() -> None:
            if args.gui_smoke_test:
                # GitHub-hosted Windows runners have no interactive user desktop.
                # Check native window construction here; real Vue DOM tests run
                # separately with headless Edge in the CI workflow.
                def close_later() -> None:
                    time.sleep(4)
                    try:
                        window.destroy()
                    except Exception:
                        pass
                threading.Thread(target=close_later, daemon=True).start()

        webview.start(on_ready, gui="edgechromium", debug=False)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
