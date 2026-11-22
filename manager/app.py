"""Windows desktop entry: Vue 3 + WebView2, with a narrow Python ADB bridge."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
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

    def on_ready():
        if not args.gui_smoke_test:
            return
        try:
            for attempt in range(42):
                try:
                    result = window.evaluate_js("""(() => ({
                        vue: !!document.querySelector('#app .app-root'),
                        nav: document.querySelectorAll('.nav-item').length,
                        bridge: typeof window.pywebview?.api?.environment === 'function'
                    }))()""")
                    if isinstance(result, dict) and result.get("vue") and result.get("nav") == 6 and result.get("bridge"):
                        break
                except Exception as exc:
                    smoke["reason"] = str(exc)
                time.sleep(0.35)
            else:
                raise RuntimeError("Vue 未渲染六个导航项或 Python API 未注入")

            # A ready JS function is not enough: invoke the Python bridge and await its result.
            window.evaluate_js("""(() => {
                window.__awdSmoke = {done:false};
                window.pywebview.api.environment()
                  .then(r => { window.__awdSmoke = {done:true,version:r.version}; })
                  .catch(e => { window.__awdSmoke = {done:true,error:String(e)}; });
            })()""")
            for attempt in range(24):
                result = window.evaluate_js("window.__awdSmoke")
                if isinstance(result, dict) and result.get("done"):
                    if result.get("version") != APP_VERSION:
                        raise RuntimeError("Python 桥接返回异常：" + repr(result))
                    break
                time.sleep(0.3)
            else:
                raise RuntimeError("Vue 无法调用 Python environment 接口")

            before = window.evaluate_js("document.querySelector('.app-root').classList.contains('sidebar-closed')")
            window.evaluate_js("document.querySelector('.sidebar-toggle').click()")
            time.sleep(0.2)
            after = window.evaluate_js("document.querySelector('.app-root').classList.contains('sidebar-closed')")
            if before == after:
                raise RuntimeError("侧边栏收缩交互未生效")
            smoke["ok"] = True
        except Exception as exc:
            smoke["reason"] = str(exc)
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    webview.start(on_ready, gui="edgechromium", debug=False)
    if args.gui_smoke_test and not smoke["ok"]:
        raise SystemExit("WebView2 GUI integration smoke test failed: " + smoke["reason"])


if __name__ == "__main__":
    main()
