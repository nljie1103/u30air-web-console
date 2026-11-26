"""Android Web Desktop native Qt 6 Windows launcher."""
from __future__ import annotations

import argparse
import os
import sys

from version import APP_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="Android Web Desktop Qt6 Manager")
    parser.add_argument("--self-test", action="store_true",
                        help="Build-time Qt UI smoke test without connecting to ADB")
    parser.add_argument("--gui-smoke-test", action="store_true",
                        help="Show, move and interact with a real Qt top-level window")
    args = parser.parse_args()

    # QApplication is constructed on the main thread, never on an ADB worker.
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from qt_window import ManagerWindow, register_web_scheme, frontend_root
    from pathlib import Path

    if args.self_test and sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    register_web_scheme()
    application = QApplication(sys.argv)
    application.setApplicationName("Android Web Desktop Manager")
    application.setApplicationVersion(APP_VERSION)
    application.setOrganizationName("AndroidWebDesktop")
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "app.ico"
    if icon.exists():
        application.setWindowIcon(QIcon(str(icon)))
    assert frontend_root().joinpath("index.html").is_file(), "Vue 3 资源尚未构建，请运行 npm run build"
    window = ManagerWindow(auto_start=not (args.self_test or args.gui_smoke_test))
    if args.self_test:
        assert window.view is not None
        assert window.channel is not None
        assert "nativeBridge" in window.channel.registeredObjects()
        assert APP_VERSION == application.applicationVersion()
        print("Qt6 WebEngine shell and original Vue3 assets available")
        window.close()
        window.deleteLater()
        application.processEvents()
        return 0
    window.show()
    if args.gui_smoke_test:
        tries = [0]
        def smoke():
            tries[0] += 1
            if tries[0] > 40:
                print("Qt6 Vue UI did not load in time", file=sys.stderr)
                application.exit(2)
                return
            def checked(result):
                if os.environ.get("AWD_DEBUG_UI"):
                    print("UI PROBE", result, flush=True)
                if not result or result.get("nav") != 6 or not result.get("loaded"):
                    QTimer.singleShot(400, smoke)
                    return
                original = window.pos()
                for n in range(1, 5):
                    window.move(original.x()+n*16, original.y()+n*7)
                    application.processEvents()
                window.js("document.querySelector('.sidebar-toggle').click()")
                window.js("document.querySelector('button.nav-item[title=\\'部署与更新\\']').click()")
                window.js("document.querySelector('button.nav-item[title=\\'工作台\\']').click()")
                print("Qt6 embedded Vue3 first-load, sidebar, navigation and native window motion OK")
                window.close()
                application.quit()
            if os.environ.get("AWD_DEBUG_UI"):
                window.js("1+1", lambda value: print("JS MATH:",repr(value),flush=True))
                window.js("document.title",lambda value: print("JS TITLE:",repr(value),flush=True))
                window.js("document.documentElement.outerHTML.slice(0,600)",lambda value: print("JS HTML:",repr(value),flush=True))
                window.js("typeof window.QWebChannel",lambda value: print("JS CHANNEL:",repr(value),flush=True))
            import json
            window.js("JSON.stringify({nav: document.querySelectorAll('button.nav-item').length, loaded: !!document.querySelector('.app-root'), bridge: typeof window.pywebview?.api?.environment === 'function'})",
                      lambda value: checked(json.loads(value) if isinstance(value, str) and value else None))
        QTimer.singleShot(750, smoke)
    exit_code = application.exec()
    window.deleteLater()
    application.processEvents()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
