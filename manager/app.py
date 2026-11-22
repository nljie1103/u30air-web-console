"""Windows desktop entry: Vue 3 + WebView2, with a narrow Python ADB bridge."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
import time

from bridge import DesktopBridge

APP_VERSION = "2.2.0"


def frontend_file() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "manager" / "frontend" / "dist" / "index.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="Android Web Desktop Manager")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-smoke-test", action="store_true")
    args = parser.parse_args()

    index = frontend_file()
    if args.self_test:
        if not index.is_file():
            raise SystemExit(f"Frontend build is missing: {index}")
        bridge = DesktopBridge()
        assert bridge.environment()["version"] == APP_VERSION
        print(f"Android Web Desktop Manager v{APP_VERSION}: frontend and bridge OK")
        return

    if not index.is_file():
        raise SystemExit("Vue frontend build missing. Run npm run build in manager/frontend.")

    try:
        import webview
    except ImportError as exc:
        raise SystemExit("pywebview is not installed") from exc

    bridge = DesktopBridge()
    window = webview.create_window(
        title=f"Android Web Desktop  ·  v{APP_VERSION}",
        url=index.as_uri(),
        js_api=bridge,
        width=1360,
        height=860,
        min_size=(1000, 650),
        background_color="#f8fafc",
    )
    bridge.window = window

    def on_ready():
        if args.gui_smoke_test:
            # A real smoke test must create a WebView2 window and load the Vue UI.
            def close_later():
                time.sleep(4)
                try:
                    window.destroy()
                except Exception:
                    pass
            threading.Thread(target=close_later, daemon=True).start()

    # WebView2 is the native Windows rendering engine used by pywebview.
    webview.start(on_ready, gui="edgechromium", debug=False)


if __name__ == "__main__":
    main()
