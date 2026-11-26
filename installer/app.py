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
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from qt_window import ManagerWindow
    from pathlib import Path

    if args.self_test and sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication(sys.argv)
    application.setApplicationName("Android Web Desktop Manager")
    application.setApplicationVersion(APP_VERSION)
    application.setOrganizationName("AndroidWebDesktop")
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "app.ico"
    if icon.exists():
        application.setWindowIcon(QIcon(str(icon)))
    window = ManagerWindow(auto_start=not (args.self_test or args.gui_smoke_test))
    if args.self_test:
        assert window.stack.count() == 6, "Qt UI missing expected navigation pages"
        assert window.device_combo.isEditable() is False
        window.toggle_sidebar()
        assert window.collapsed and window.sidebar.width() == 68
        window.toggle_sidebar()
        assert not window.collapsed
        assert window.install_adb_button.text() == "一键安装 ADB"
        assert APP_VERSION == application.applicationVersion()
        print("Qt6 native self-test passed, 6 pages, ADB one-click and collapsible sidebar")
        window.close()
        return 0
    window.show()
    if args.gui_smoke_test:
        def smoke():
            original = window.pos()
            for n in range(1, 7):
                window.move(original.x()+n*16, original.y()+n*8)
                application.processEvents()
                if not window.isVisible():
                    raise RuntimeError("Qt window became invisible during move")
            window.toggle_sidebar()
            assert window.collapsed
            window.set_page(3)
            assert window.stack.currentIndex() == 3
            window.toggle_sidebar()
            window.set_page(0)
            assert window.sidebar.width() == 243
            print("Qt6 native window shown, moved and navigation exercised")
            window.close()
            application.quit()
        QTimer.singleShot(400, smoke)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
