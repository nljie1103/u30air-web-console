"""QtWebEngine regression tests for the restored original Vue 3 interface."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest import TestCase, skipUnless

DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY))

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage")

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from qt_window import ManagerWindow, register_web_scheme
    HAVE_QT = True
except (ImportError, OSError):
    HAVE_QT = False


class FakeBridge:
    def __init__(self, adb=True):
        self.version = "2.5.1"
        self.adb = adb
        self.calls = []
    def environment(self):
        self.calls.append(("environment",))
        return {"version":self.version,"adb_found":self.adb,
                "adb_path":r"C:\AndroidWebDesktop\platform-tools\adb.exe" if self.adb else ""}
    def list_devices(self):
        self.calls.append(("list_devices",))
        return [{"serial":"MOCK-U30-AIR","state":"device"}]
    def device_info(self, serial):
        self.calls.append(("device_info",serial))
        return {"brand":"ZTE", "manufacturer":"ZTE","model":"U30 Air",
                "android":"13", "sdk":"33", "abi":"arm64-v8a", "build":"U30Air_TEST",
                "ips":["192.168.0.1"],"preferred_ip":"192.168.0.1",
                "network_addresses":[{"ip":"192.168.0.1","interface":"br0","role":"热点/局域网"}],
                "installed_version":"2.5.0","listening_address":"192.168.0.1:8765"}
    def read_auth(self,serial):
        self.calls.append(("read_auth",serial))
        return {"enabled":False,"configured":True}
    def get_logs(self):return []
    def clear_logs(self):self.calls.append(("clear_logs",));return True
    def install_official_adb(self):
        self.calls.append(("install_official_adb",))
        self.adb=True
        return r"C:\AndroidWebDesktop\platform-tools\adb.exe"
    def list_apps(self,serial,system=False):
        return [{"name":"com.v2ray.ang","system":False,"disabled":False}]


@skipUnless(HAVE_QT,"Qt6 WebEngine is required")
class TestManagerQtClassic(TestCase):
    @classmethod
    def setUpClass(cls):
        register_web_scheme()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.bridge = FakeBridge()
        self.window = ManagerWindow(self.bridge,auto_start=False)
        self.window.show()
        self._wait(lambda: self._js("document.querySelectorAll('.nav-item').length")==6)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _wait(self, condition, seconds=8):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if condition():return
            QTest.qWait(75)
        self.fail("Embedded Vue3 view did not reach expected state")

    def _js(self,script):
        result=[]
        self.window.js(script, lambda value: result.append(value))
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not result:
            QTest.qWait(25)
        return result[0] if result else None

    def test_original_sidebar_and_cards_restored(self):
        self.assertEqual(self._js("document.querySelectorAll('.stat-card').length"),4)
        self.assertEqual(self._js("document.querySelectorAll('.nav-item').length"),6)
        self.assertEqual(self._js("getComputedStyle(document.querySelector('.sidebar')).backgroundColor"),"rgb(255, 255, 255)")
        self.assertEqual(self._js("document.querySelector('.sidebar-profile span').textContent"),"v2.5.1")
        self.assertTrue(self.window.view.url().toString().startswith("awdapp://"))
        self.assertFalse("127.0.0.1" in self.window.view.url().toString())

    def test_window_move_and_sidebar_navigation(self):
        origin=self.window.pos()
        for offset in range(5):
            self.window.move(origin.x()+offset*14,origin.y()+offset*8)
            self.app.processEvents()
        was_collapsed = self._js("document.querySelector('.app-root').classList.contains('sidebar-closed')")
        self._js("document.querySelector('.sidebar-toggle').click();true")
        self._wait(lambda:self._js("document.querySelector('.app-root').classList.contains('sidebar-closed')") != was_collapsed)
        self._js("document.querySelector('.sidebar-toggle').click();true")
        self._wait(lambda:self._js("document.querySelector('.app-root').classList.contains('sidebar-closed')") == was_collapsed)
        self._js("document.querySelector('button.nav-item[title=\"部署与更新\"]').click();true")
        self._wait(lambda:self._js("document.querySelector('.page-content h1').textContent")=="部署与更新")
        self.assertEqual(self._js("document.querySelectorAll('.auth-setup').length"),1)
        self._js("document.querySelector('button.nav-item[title=\"工作台\"]').click();true")
        self._wait(lambda:self._js("document.querySelector('.page-content h1').textContent")=="工作台")

    def test_qt_bridge_async_roundtrip_and_denies_arbitrary_call(self):
        self._wait(lambda:self._js("typeof window.pywebview?.api?.environment")=="function")
        self._js("window.pywebview.api.environment().then(v=>window.__envReply=JSON.stringify(v))")
        self._wait(lambda:bool(self._js("window.__envReply")))
        obj=json.loads(self._js("window.__envReply"))
        self.assertEqual(obj["version"],"2.5.1")
        self.assertTrue(obj["adb_found"])
        self.assertIn(("environment",),self.bridge.calls)
        self._js("window.pywebview.api.list_devices().then(v=>window.__deviceReply=JSON.stringify(v))")
        self._wait(lambda:bool(self._js("window.__deviceReply")))
        self.assertEqual(json.loads(self._js("window.__deviceReply"))[0]["serial"],"MOCK-U30-AIR")
        results=[]
        self.window.backend.completed.connect(lambda _task,data:results.append(json.loads(data)))
        self.window.backend.request("fake-id","exec_command",'["rm","-rf","/"]')
        self.assertFalse(results[-1]["ok"])

    def test_no_adb_shows_one_click_banner(self):
        self.bridge.adb=False
        self._js("window.pywebview.api.environment().then(v=>window.__noAdb=JSON.stringify(v))")
        self._wait(lambda:bool(self._js("window.__noAdb")))
        # Toggle the Vue banner by reloading with a no-ADB mock.
        self.window.view.reload()
        self._wait(lambda:self._js("document.querySelectorAll('.nav-item').length")==6)
        # Reload is asynchronous; a QWebEngine JS evaluation performed during
        # navigation can return an empty QVariant even if Vue is healthy.
        self._wait(lambda:self._js(
            "Boolean(document.querySelector('.adb-setup-banner')?.textContent?.includes('一键安装 ADB'))"
        ) is True)
