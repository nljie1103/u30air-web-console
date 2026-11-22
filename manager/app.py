"""Windows desktop entry: Vue 3 + WebView2, with a narrow Python ADB bridge."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from bridge import DesktopBridge

APP_VERSION = "2.2.1"


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

    smoke = {"ok": False, "reason": "Vue 页面未就绪"}
    completed = threading.Event()
    diagnostic = Path(tempfile.gettempdir()) / "awd-webview2-smoke.log"

    def trace(message: str) -> None:
        if not args.gui_smoke_test:
            return
        with diagnostic.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {message}\n")

    if args.gui_smoke_test:
        diagnostic.write_text("WebView2 smoke start\n", encoding="utf-8")

        def watchdog() -> None:
            if not completed.wait(38):
                trace("TIMEOUT: GUI event loop did not exit")
                os._exit(7)

        threading.Thread(target=watchdog, daemon=True).start()

    def on_ready() -> None:
        if not args.gui_smoke_test:
            return
        try:
            trace("callback started")
            if not window.events.loaded.wait(14):
                raise RuntimeError("WebView2 页面 loaded 事件超时")
            trace("window loaded")
            if not window.events._pywebviewready.wait(14):
                raise RuntimeError("WebView2 Python 桥接 ready 事件超时")
            trace("bridge ready")
            for attempt in range(18):
                result = window.evaluate_js("""(() => ({
                    vue: !!document.querySelector('#app .app-root'),
                    nav: document.querySelectorAll('.nav-item').length,
                    bridge: typeof window.pywebview?.api?.environment === 'function'
                }))()""")
                if attempt in (0, 4, 9):
                    trace("Vue DOM: " + repr(result))
                if isinstance(result, dict) and result.get("vue") and result.get("nav") == 6 and result.get("bridge"):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Vue 页面未渲染六个导航项或环境 API 未注入")
            trace("Vue DOM and bridge ready")

            window.evaluate_js("""(() => {
                window.__awdSmoke = {done:false};
                window.pywebview.api.environment()
                  .then(r => { window.__awdSmoke = {done:true,version:r.version}; })
                  .catch(e => { window.__awdSmoke = {done:true,error:String(e)}; });
            })()""")
            for attempt in range(16):
                result = window.evaluate_js("window.__awdSmoke")
                if isinstance(result, dict) and result.get("done"):
                    trace("Python bridge response: " + repr(result))
                    if result.get("version") != APP_VERSION:
                        raise RuntimeError("Python 桥接返回版本不匹配：" + repr(result))
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Vue 无法调用 Python environment 接口")
            before = window.evaluate_js("document.querySelector('.app-root').classList.contains('sidebar-closed')")
            window.evaluate_js("document.querySelector('.sidebar-toggle').click()")
            time.sleep(0.25)
            after = window.evaluate_js("document.querySelector('.app-root').classList.contains('sidebar-closed')")
            trace(f"sidebar toggle: {before!r} -> {after!r}")
            if before == after:
                raise RuntimeError("侧边栏收缩交互未生效")
            smoke["ok"] = True
            trace("smoke passed")
        except Exception as exc:
            smoke["reason"] = str(exc)
            trace("ERROR: " + str(exc))
        finally:
            # Keep window destruction separate from pywebview's startup callback.
            def close_window() -> None:
                try:
                    trace("closing GUI window")
                    window.destroy()
                except Exception as exc:
                    trace("window close error: " + str(exc))
            threading.Thread(target=close_window, daemon=True).start()

    # WebView2 is the native Windows rendering engine used by pywebview.
    webview.start(on_ready, gui="edgechromium", debug=False)
    completed.set()
    if args.gui_smoke_test and not smoke["ok"]:
        raise SystemExit("WebView2 GUI integration smoke test failed: " + smoke["reason"])


if __name__ == "__main__":
    main()
