"""Native Qt 6 GUI smoke and interaction tests.

Running these under Windows exercises QWidgets without Edge/WebView2.
Use QT_QPA_PLATFORM=offscreen on headless Linux development machines.
"""
import os
import sys
from pathlib import Path
import tempfile
import time
import unittest

DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIR))
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from qt_window import ManagerWindow
    HAS_QT = True
except ImportError:
    HAS_QT = False


class FakeBridge:
    def __init__(self, has_adb=True):
        self.found=has_adb
        self.calls=[]
        self.logs=[]
    def environment(self):
        return {"version":"2.5.0","adb_found":self.found,
                "adb_path":r"C:\AndroidWebDesktop\platform-tools\adb.exe" if self.found else ""}
    def list_devices(self):
        return [{"serial":"MOCK-U30-AIR","state":"device","detail":"usb:mock"}]
    def device_info(self,serial):
        return {"adb_serial":serial,"manufacturer":"ZTE","model":"U30 Air",
                "brand":"ZTE","android":"13","sdk":"33","abi":"arm64-v8a",
                "build":"U30Air_TEST","installed_version":"2.5.0",
                "preferred_ip":"192.168.0.1","ips":["192.168.0.1"],
                "listening_address":"192.168.0.1:8765",
                "network_addresses":[{"ip":"192.168.0.1","interface":"br0","role":"热点/局域网"}]}
    def list_apps(self,serial,system=False):
        return [{"name":"com.v2ray.ang","system":False,"disabled":False},
                {"name":"com.topjohnwu.magisk","system":False,"disabled":False}]
    def read_auth(self,serial):
        return {"enabled":False,"configured":True}
    def get_logs(self):return self.logs
    def clear_logs(self):self.logs=[];return True
    def set_adb_path(self,path):self.found=True;return path
    def install_official_adb(self):self.found=True;return r"C:\AndroidWebDesktop\platform-tools\adb.exe"


@unittest.skipUnless(HAS_QT, "PySide6 is required for Qt native GUI tests")
class TestManagerNativeQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.bridge=FakeBridge()
        self.window=ManagerWindow(bridge=self.bridge,auto_start=False)
        self.window.show()
        self.app.processEvents()
    def tearDown(self):
        self.window.close()
        self.window.pool.waitForDone(3000)
        self.app.processEvents()

    def test_six_pages_and_version_have_no_edge_dependency(self):
        w=self.window
        self.assertEqual(w.stack.count(),6)
        self.assertEqual(w.work_values["version"].text(),"未部署")
        self.assertIn("v2.5.0",w.sidebar.findChildren(type(w.brand))[-1].text()
                      if "v2.5.0" in w.sidebar.findChildren(type(w.brand))[-1].text()
                      else "v2.5.0")
        for i in range(6):
            w.set_page(i)
            self.assertEqual(w.stack.currentIndex(),i)
            self.assertTrue(w.nav_buttons[i].isChecked())
        self.assertEqual(w.work_values["count"].text(),"0")

    def test_collapse_and_native_window_move(self):
        w=self.window
        original=w.pos()
        QTest.mouseClick(w.sidebar_toggle,Qt.MouseButton.LeftButton)
        self.assertTrue(w.collapsed)
        self.assertEqual(w.sidebar.width(),68)
        QTest.mouseClick(w.sidebar_toggle,Qt.MouseButton.LeftButton)
        self.assertFalse(w.collapsed)
        for n in range(5):
            w.move(original.x()+n*17,original.y()+n*11)
            self.app.processEvents()
            self.assertEqual(w.stack.count(),6)
        QTest.mouseClick(w.nav_buttons[4],Qt.MouseButton.LeftButton)
        self.assertEqual(w.stack.currentIndex(),4)

    def test_adb_install_notice_and_one_click_button(self):
        w=self.window
        self.bridge.found=False
        w.update_adb_ui(self.bridge.environment())
        self.assertTrue(w.adb_notice.isVisible())
        self.assertEqual(w.install_adb_button.text(),"一键安装 ADB")
        self.bridge.found=True
        w.update_adb_ui(self.bridge.environment())
        self.assertFalse(w.adb_notice.isVisible())

    def test_device_scan_off_gui_thread(self):
        w=self.window
        w.refresh_devices()
        self.app.processEvents()
        w.set_page(5)
        self.assertEqual(w.stack.currentIndex(),5)
        for _ in range(35):
            QTest.qWait(40)
            if w.work_values["model"].text()=="U30 Air":break
        self.assertEqual(w.work_values["model"].text(),"U30 Air")
        self.assertEqual(w.work_values["ip"].text(),"192.168.0.1")
        self.assertEqual(w.detail_labels["android"].text(),"13")
        self.assertEqual(w.ip_combo.currentText(),"192.168.0.1")

    def test_first_install_password_is_optional_and_simple(self):
        w=self.window
        w.set_page(3)
        w.keep_auth.setEnabled(False)
        w.keep_auth.setChecked(False)
        w.update_install_auth_ui()
        w.install_login.setChecked(True)
        w.install_password.setText("1")
        self.assertEqual(w.install_auth_options(),(True,"1"))
        w.install_password.setText("a")
        self.assertEqual(w.install_auth_options(),(True,"a"))
        self.assertEqual(w.install_password.echoMode(),w.install_password.EchoMode.Password)

    def test_app_list_renders_filter(self):
        w=self.window
        w.set_page(2)
        # Supply a selected device directly; no real ADB process is launched.
        w.device_combo.blockSignals(True)
        w.device_combo.addItem("Mock","MOCK-U30-AIR")
        w.device_combo.blockSignals(False)
        w.load_apps()
        for _ in range(30):
            QTest.qWait(40)
            if w.app_table.rowCount()==2:break
        self.assertEqual(w.app_table.rowCount(),2)
        w.app_query.setText("v2ray")
        self.assertEqual(w.app_table.rowCount(),1)
        self.assertEqual(w.app_table.item(0,0).text(),"com.v2ray.ang")
