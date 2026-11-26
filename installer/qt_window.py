"""Qt 6 native Windows desktop manager.

All controls are QWidgets. Unlike the former Edge application shell, this
program doesn't open a browser for its own management UI. Android's 8765
web dashboard remains a separate service opened only on user request.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QHeaderView,
)

from bridge import DesktopBridge
from version import APP_VERSION

PAGES = [
    ("工作台", "⌗"),
    ("设备管理", "▯"),
    ("应用管理", "▤"),
    ("部署与更新", "◇"),
    ("运行日志", "≡"),
    ("设置", "⚙"),
]

STYLE = """
QWidget { font-family:"Microsoft YaHei UI","Segoe UI"; font-size:13px; color:#25344b; }
QMainWindow, QWidget#Root, QScrollArea, QWidget#Page { background:#f6f8fb; }
QWidget#SideBar { background:#ffffff; border-right:1px solid #e6ebf1; }
QFrame#Card, QFrame#Notice {
  background:#fff; border:1px solid #e6ebf2; border-radius:13px;
}
QFrame#Notice { background:#fff8e9; border-color:#f3d4a2; }
QLabel#Title { font-size:26px; font-weight:700; color:#192941; }
QLabel#SectionTitle { font-size:15px; font-weight:700; color:#25344b; }
QLabel#Muted { color:#8090a7; font-size:12px; }
QLabel#Metric { font-size:23px; font-weight:750; color:#1a324d; }
QLabel#LogoText { font-size:15px; font-weight:750; color:#263952; }
QLabel#StatusChip { background:#eaf7ef; border-radius:8px; color:#22845e; padding:6px 10px; }
QPushButton { background:#fff; color:#354860; border:1px solid #dce4ee;
  border-radius:9px; padding:10px 14px; font-weight:600; min-height:20px; }
QPushButton:hover { background:#f0f5fb; border-color:#bbcce0; }
QPushButton:pressed { background:#e4edf8; }
QPushButton:disabled { background:#f4f5f7; color:#a8b1bf; }
QPushButton#Primary { background:#253249; border-color:#253249; color:#fff; }
QPushButton#Primary:hover { background:#384c67; }
QPushButton#Danger { color:#b9424b; border-color:#f0cbce; background:#fff8f8; }
QPushButton#Danger:hover { background:#ffebeb; }
QPushButton#Nav { border:0; text-align:left; padding:13px 14px; background:#fff;
  color:#5c718e; font-size:13px; border-radius:9px; }
QPushButton#Nav:checked { background:#eaf1f8; color:#192b43; font-weight:700; }
QPushButton#Nav:hover { background:#f0f4f9; }
QLineEdit, QComboBox { border:1px solid #dfe6ee; border-radius:8px;
  padding:9px 10px; background:#fff; min-height:21px; }
QLineEdit:focus, QComboBox:focus { border:1px solid #6a9ec5; }
QComboBox QAbstractItemView { background:white; color:#22344c; selection-background-color:#e9f2fb; }
QCheckBox { spacing:9px; color:#485a72; }
QCheckBox::indicator { width:17px; height:17px; }
QTableWidget { background:white; border:1px solid #e9edf3; border-radius:9px;
  gridline-color:#eff2f6; alternate-background-color:#f8fafc; selection-background-color:#e7f3f7; }
QTableWidget::item { padding:8px; }
QHeaderView::section { background:#f3f6fa; color:#63758b; padding:10px;
  border:0; border-bottom:1px solid #e7ecf2; font-size:12px; }
QPlainTextEdit { background:#101c2c; color:#d6e4ee; border-radius:10px;
  border:0; padding:12px; font-family:Consolas; font-size:12px; }
QScrollBar:vertical { background:#f5f7fa; width:10px; }
QScrollBar::handle:vertical { background:#cdd6e1; border-radius:5px; min-height:32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""

class TaskSignals(QObject):
    ok = Signal(object)
    failed = Signal(str)
    finished = Signal()

class Task(QRunnable):
    def __init__(self, job: Callable):
        super().__init__()
        self.job = job
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.ok.emit(self.job())
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()

def line(text="", muted=False):
    label = QLabel(str(text))
    label.setWordWrap(True)
    if muted:
        label.setObjectName("Muted")
    return label

def button(label, click=None, primary=False, danger=False):
    b = QPushButton(label)
    if primary: b.setObjectName("Primary")
    if danger: b.setObjectName("Danger")
    if click: b.clicked.connect(click)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b

def card(title: str, *, content=None):
    f = QFrame()
    f.setObjectName("Card")
    box = QVBoxLayout(f)
    box.setContentsMargins(20, 18, 20, 18)
    box.setSpacing(13)
    heading = QLabel(title)
    heading.setObjectName("SectionTitle")
    box.addWidget(heading)
    if content: content(box)
    return f, box

def row_of(*widgets):
    row = QHBoxLayout()
    row.setSpacing(9)
    for widget in widgets:
        row.addWidget(widget)
    return row

def page_root(title, caption):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    shell = QWidget()
    shell.setObjectName("Page")
    layout = QVBoxLayout(shell)
    layout.setContentsMargins(33, 28, 33, 30)
    layout.setSpacing(18)
    heading = QLabel(title)
    heading.setObjectName("Title")
    layout.addWidget(heading)
    layout.addWidget(line(caption, muted=True))
    scroll.setWidget(shell)
    return scroll, layout

class ManagerWindow(QMainWindow):
    def __init__(self, bridge: DesktopBridge | None = None, *, auto_start=True):
        super().__init__()
        self.bridge = bridge or DesktopBridge()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.running = set()
        self.tasks = {}
        self.info = {}
        self.devices = []
        self.apps = []
        self.apps_system = False
        self.collapsed = False
        self._initial_prompt_shown = False
        self._page_index = 0

        self.setObjectName("ManagerWindow")
        self.setWindowTitle("Android Web Desktop · 设备管理器")
        self.resize(1240, 815)
        self.setMinimumSize(880, 580)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "app.ico"
        if not icon.is_file():
            icon = Path(__file__).parent / "assets" / "app-icon.svg"
        self.setWindowIcon(QIcon(str(icon)))
        self.setStyleSheet(STYLE)
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("SideBar")
        self.sidebar.setFixedWidth(243)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 16, 12, 15)
        side.setSpacing(6)
        branding = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setPixmap(QIcon(str(icon)).pixmap(38, 38))
        branding.addWidget(self.logo)
        self.brand = QLabel("Android Desktop\nDevice Manager")
        self.brand.setObjectName("LogoText")
        branding.addWidget(self.brand, 1)
        self.sidebar_toggle = button("☷", self.toggle_sidebar)
        self.sidebar_toggle.setToolTip("收起或展开侧边栏")
        self.sidebar_toggle.setFixedWidth(36)
        branding.addWidget(self.sidebar_toggle)
        side.addLayout(branding)
        side.addSpacing(26)
        side.addWidget(line("工作空间", muted=True))
        self.nav_buttons = []
        for n,(name,symbol) in enumerate(PAGES):
            b = button(f"{symbol}    {name}", lambda _checked=False, i=n: self.set_page(i))
            b.setCheckable(True)
            b.setObjectName("Nav")
            b.setToolTip(name)
            b.setMinimumHeight(43)
            self.nav_buttons.append(b)
            side.addWidget(b)
        side.addStretch(1)
        security,_ = card("本地安全管理")
        security.layout().addWidget(line("ADB 与设备操作在本机执行，不经过远程云端。", True))
        self.security_card = security
        side.addWidget(security)
        side.addWidget(line(f"Desktop Manager  ·  v{APP_VERSION}", True))
        outer.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(0)
        right_layout.setContentsMargins(0,0,0,0)
        header = QWidget()
        header.setStyleSheet("background:#fff; border-bottom:1px solid #e7edf4")
        top = QHBoxLayout(header)
        top.setContentsMargins(25, 12, 25, 12)
        top.setSpacing(10)
        self.crumb = QLabel("管理平台   ›   工作台")
        top.addWidget(self.crumb)
        top.addStretch(1)
        self.connection_status = QLabel("● 未连接设备")
        self.connection_status.setObjectName("Muted")
        top.addWidget(self.connection_status)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(245)
        self.device_combo.setToolTip("选择已连接的 Android 设备")
        self.device_combo.currentIndexChanged.connect(self.selection_changed)
        top.addWidget(self.device_combo)
        top.addWidget(button("⟳ 刷新", self.refresh_devices))
        right_layout.addWidget(header)

        self.adb_notice = QFrame()
        self.adb_notice.setObjectName("Notice")
        notice_layout = QHBoxLayout(self.adb_notice)
        notice_layout.setContentsMargins(18,10,18,10)
        notice_layout.addWidget(line("未找到 ADB。点击右侧按钮自动获取 Google 官方 Platform Tools，无需配置 PATH。"),1)
        self.install_adb_button = button("一键安装 ADB", self.install_adb, primary=True)
        notice_layout.addWidget(self.install_adb_button)
        right_layout.addWidget(self.adb_notice)
        self.adb_notice.hide()

        self.stack = QStackedWidget()
        self._build_workbench()
        self._build_devices()
        self._build_apps()
        self._build_deploy()
        self._build_logs()
        self._build_settings()
        right_layout.addWidget(self.stack,1)
        self.foot_status = QLabel("就绪 · 所有设备操作均在本机执行")
        self.foot_status.setStyleSheet("color:#8694a7;background:#fff;border-top:1px solid #e7edf4;padding:9px 25px;font-size:11px")
        right_layout.addWidget(self.foot_status)
        outer.addWidget(right,1)
        self.set_page(0)

        self.scan_timer = QTimer(self)
        self.scan_timer.setInterval(11000)
        self.scan_timer.timeout.connect(self.refresh_devices)
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(1800)
        self.log_timer.timeout.connect(self.refresh_logs)
        self.log_timer.start()
        if auto_start:
            QTimer.singleShot(250, self.initial_scan)

    def _build_workbench(self):
        scroll, layout = page_root("工作台","统一查看设备连接、网页桌面状态与快捷操作。")
        stats = QGridLayout()
        stats.setSpacing(14)
        self.work_values = {}
        for i,(key,title,default) in enumerate([
            ("count","已发现设备","0"), ("model","当前设备","未选择"),
            ("version","网页桌面","未部署"), ("ip","推荐管理地址","—"),
        ]):
            f,box = card(title)
            lab = QLabel(default)
            lab.setObjectName("Metric")
            box.addWidget(lab)
            self.work_values[key] = lab
            stats.addWidget(f,0,i)
        layout.addLayout(stats)
        pane = QGridLayout(); pane.setSpacing(14)
        device, a = card("设备概况")
        self.work_device_label=line("连接 Android 设备后会自动加载系统信息。",True)
        a.addWidget(self.work_device_label)
        a.addStretch()
        quick,b = card("快捷操作")
        b.addWidget(line("连接设备、安装、打开网页桌面和电源管理。",True))
        for title, callback in [
            ("一键部署网页桌面", lambda:self.set_page(3)),
            ("打开网页桌面",self.open_web),
            ("连接无线设备",self.connect_wireless),
            ("重启设备",self.reboot_confirm),
        ]: b.addWidget(button(title,callback))
        pane.addWidget(device,0,0);pane.addWidget(quick,0,1)
        layout.addLayout(pane)
        layout.addStretch()
        self.stack.addWidget(scroll)

    def _build_devices(self):
        scroll,layout=page_root("设备管理","通过 ADB 获取设备品牌、系统信息和局域网接口。")
        f,box=card("设备详细信息")
        self.device_details = QFormLayout()
        self.detail_labels={}
        for key,title in [
            ("manufacturer","制造商"),("model","品牌 / 型号"),("android","Android 系统"),
            ("sdk","系统 SDK"),("abi","CPU 架构"),("build","系统构建"),
            ("installed_version","网页控制台版本"),("listening_address","当前监听地址"),
        ]:
            label=line("—")
            self.detail_labels[key]=label
            self.device_details.addRow(line(title,True),label)
        box.addLayout(self.device_details)
        layout.addWidget(f)
        power,inner=card("设备操作")
        inner.addLayout(row_of(
            button("连接无线 ADB",self.connect_wireless),
            button("打开控制台",self.open_web),
            button("重启设备",self.reboot_confirm),
            button("关机",self.poweroff_confirm,danger=True),
        ))
        layout.addWidget(power);layout.addStretch()
        self.stack.addWidget(scroll)

    def _build_apps(self):
        scroll,layout=page_root("应用管理","搜索应用包名并管理用户应用与非关键系统组件。")
        f,box=card("已安装的应用")
        filter_row=QHBoxLayout()
        self.app_query=QLineEdit()
        self.app_query.setPlaceholderText("搜索包名…")
        self.app_query.textChanged.connect(self.filter_apps)
        filter_row.addWidget(self.app_query,1)
        self.app_mode=QComboBox()
        self.app_mode.addItems(["用户应用","系统应用"])
        self.app_mode.currentIndexChanged.connect(self.load_apps)
        filter_row.addWidget(self.app_mode)
        filter_row.addWidget(button("刷新列表",self.load_apps))
        box.addLayout(filter_row)
        self.app_table=QTableWidget(0,2)
        self.app_table.setHorizontalHeaderLabels(["应用包名","状态"])
        self.app_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.app_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        self.app_table.setAlternatingRowColors(True)
        self.app_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.app_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        box.addWidget(self.app_table)
        actions=QHBoxLayout()
        actions.addWidget(button("卸载用户应用",self.uninstall_app,danger=True))
        actions.addWidget(button("停用系统组件",lambda:self.toggle_system_app(False)))
        actions.addWidget(button("恢复系统组件",lambda:self.toggle_system_app(True)))
        actions.addStretch()
        box.addLayout(actions)
        box.addWidget(line("停用系统组件前需输入完整包名，关键系统包始终禁止操作。",True))
        layout.addWidget(f);layout.addStretch()
        self.stack.addWidget(scroll)

    def _build_deploy(self):
        scroll,layout=page_root("部署与更新","安装 Android ARM64 网页控制台并管理首次访问密码。")
        f,box=card("安装或更新网页桌面")
        box.addWidget(line("设备管理地址：优先选择真正配置在设备上的热点网关（例如 192.168.0.1），网页端口固定 8765。",True))
        self.ip_combo=QComboBox()
        self.ip_combo.setEditable(True)
        self.ip_combo.addItem("192.168.0.1")
        box.addWidget(self.ip_combo)
        self.ip_note=line("等待设备网卡信息…",True)
        box.addWidget(self.ip_note)
        self.keep_auth=QCheckBox("更新时保持设备现有的密码设置")
        self.keep_auth.setChecked(True)
        self.keep_auth.toggled.connect(self.update_install_auth_ui)
        box.addWidget(self.keep_auth)
        self.install_login=QCheckBox("开启网页控制台登录密码")
        self.install_login.setChecked(False)
        self.install_login.toggled.connect(self.update_install_auth_ui)
        box.addWidget(self.install_login)
        self.install_password=QLineEdit()
        self.install_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.install_password.setPlaceholderText("任意长度、无需数字/大小写/特殊符号")
        box.addWidget(self.install_password)
        box.addWidget(line("关闭密码后，同一 Wi-Fi 局域网内能访问管理地址的用户都可控制设备。",True))
        box.addLayout(row_of(
            button("从 GitHub 安装最新版",self.install_latest,primary=True),
            button("安装本地 ZIP",self.install_local),
            button("卸载设备端服务",self.uninstall_service,danger=True),
        ))
        self.last_install = line("尚未执行安装操作",True)
        box.addWidget(self.last_install)
        layout.addWidget(f)

        security,inner=card("修改现有网页访问密码")
        inner.addWidget(line("无需重新下载程序。更改后服务会重启，并保留原有网关地址。",True))
        self.change_login=QCheckBox("开启密码验证")
        self.change_login.toggled.connect(self.update_change_auth_ui)
        inner.addWidget(self.change_login)
        self.change_password=QLineEdit()
        self.change_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.change_password.setPlaceholderText("新密码（已有密码时留空可保留）")
        inner.addWidget(self.change_password)
        self.current_auth=line("连接设备后读取当前状态",True)
        inner.addWidget(self.current_auth)
        inner.addWidget(button("保存并应用登录设置",self.save_auth,primary=True))
        layout.addWidget(security);layout.addStretch()
        self.stack.addWidget(scroll)
        self.update_install_auth_ui()
        self.update_change_auth_ui()

    def _build_logs(self):
        scroll,layout=page_root("运行日志","查看 ADB 操作结果与部署诊断。")
        f,box=card("客户端活动日志")
        self.log_view=QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(350)
        box.addWidget(self.log_view)
        box.addLayout(row_of(
            button("刷新",self.refresh_logs),
            button("清空日志",self.clear_logs),
        ))
        layout.addWidget(f);layout.addStretch()
        self.stack.addWidget(scroll)

    def _build_settings(self):
        scroll,layout=page_root("设置","本机 ADB 安装与 Windows 客户端信息。")
        f,box=card("Android Debug Bridge")
        self.adb_status=line("正在检测本机 ADB…",True)
        box.addWidget(self.adb_status)
        box.addLayout(row_of(
            button("一键安装 Google 官方 ADB",self.install_adb,primary=True),
            button("选择现有 adb.exe",self.choose_adb),
        ))
        box.addWidget(line("下载至当前 Windows 用户的 AppData 目录，不需要管理员权限或修改系统环境变量。首次下载需要联网并同意官方工具许可。",True))
        layout.addWidget(f)
        about,inner=card("客户端信息")
        inner.addWidget(line(f"Android Web Desktop Manager  ·  v{APP_VERSION}"))
        inner.addWidget(line("界面：Qt 6 / PySide6 原生 Widgets · Windows x64",True))
        inner.addWidget(line("设备控制：Python + 官方 Google ADB · Android Go ARM64 服务",True))
        inner.addWidget(line("不依赖 Edge、Chrome 或额外 Python/Qt 运行环境（发布版自包含）。",True))
        layout.addWidget(about);layout.addStretch()
        self.stack.addWidget(scroll)

    def toggle_sidebar(self):
        self.collapsed=not self.collapsed
        self.sidebar.setFixedWidth(68 if self.collapsed else 243)
        self.brand.setVisible(not self.collapsed)
        self.security_card.setVisible(not self.collapsed)
        self.logo.setVisible(not self.collapsed)
        for b,(title,icon) in zip(self.nav_buttons,PAGES):
            b.setText(icon if self.collapsed else f"{icon}    {title}")
        self.sidebar_toggle.setText("›" if self.collapsed else "☷")

    def set_page(self,index):
        self._page_index=index
        self.stack.setCurrentIndex(index)
        self.crumb.setText("管理平台   ›   "+PAGES[index][0])
        for n,b in enumerate(self.nav_buttons):
            b.setChecked(n==index)
        if index==2: self.load_apps()
        if index==4: self.refresh_logs()
        if index==3 and self.serial(): self.load_auth()

    def run_task(self,key,job,on_success=None,*,silent=False):
        if key in self.running:
            return
        self.running.add(key)
        self.foot_status.setText("正在执行："+key)
        task=Task(job)
        self.tasks[key] = task  # Keep signal sender alive until queued slots finish.
        def finished():
            self.running.discard(key)
            self.tasks.pop(key, None)
            self.foot_status.setText("就绪 · 所有设备操作均在本机执行")
        def success(value):
            if on_success:
                try: on_success(value)
                except Exception as exc: self.show_error(str(exc))
        def failure(message):
            if not silent:
                self.show_error(message)
            else:
                self.foot_status.setText("检查失败："+message)
        task.signals.ok.connect(success)
        task.signals.failed.connect(failure)
        task.signals.finished.connect(finished)
        self.pool.start(task)

    def show_error(self,text):
        QMessageBox.warning(self,"Android Desktop",text)

    def initial_scan(self):
        env=self.bridge.environment()
        self.update_adb_ui(env)
        if not env.get("adb_found"):
            self._initial_prompt_shown=True
            ans=QMessageBox.question(
                self,"首次使用：安装 ADB",
                "本机尚未检测到 Android ADB 工具。\n"
                "是否一键下载并安装 Google 官方 Platform Tools？\n"
                "不需要管理员权限，也不需要配置环境变量。",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans==QMessageBox.StandardButton.Yes:
                self.install_adb()
            return
        self.scan_timer.start()
        self.refresh_devices()

    def update_adb_ui(self,env):
        found=bool(env.get("adb_found"))
        self.adb_notice.setVisible(not found)
        self.adb_status.setText("已找到 ADB： "+(env.get("adb_path") or "未安装"))
        self.connection_status.setText("● 等待设备连接" if found else "● 未配置 ADB")

    def install_adb(self):
        if "安装 ADB" in self.running: return
        def done(path):
            self.update_adb_ui(self.bridge.environment())
            self.foot_status.setText("Google 官方 ADB 已安装："+str(path))
            self.scan_timer.start()
            self.refresh_devices()
            QMessageBox.information(self,"ADB 已就绪","ADB 已自动安装到当前用户目录。\n现在连接 USB 并授权调试即可使用。")
        self.run_task("安装 ADB",self.bridge.install_official_adb,done)

    def choose_adb(self):
        p,_=QFileDialog.getOpenFileName(self,"选择 adb.exe","","ADB (adb.exe);;所有文件 (*)")
        if not p:return
        self.run_task("选择 ADB",lambda:self.bridge.set_adb_path(p),
            lambda value:(self.update_adb_ui(self.bridge.environment()),self.refresh_devices()))

    def serial(self):
        return self.device_combo.currentData() or ""

    def require_serial(self):
        serial=self.serial()
        if not serial:
            self.show_error("请先连接并选择一台已授权的 Android 设备。")
        return serial

    def refresh_devices(self):
        if "设备扫描" in self.running or any(x.startswith("部署") or x in {"安装 ADB","连接无线 ADB"} for x in self.running):
            return
        if not self.bridge.environment().get("adb_found"):
            self.update_adb_ui(self.bridge.environment())
            return
        self.run_task("设备扫描",self.bridge.list_devices,self.display_devices,silent=True)

    def display_devices(self,result):
        before=self.serial()
        self.devices=result
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for d in result:
            label=d.get("serial","未知设备")
            if d.get("state")!="device":
                label+="  ·  "+d.get("state","未知")
            self.device_combo.addItem(label,d.get("serial",""))
        old_index=self.device_combo.findData(before)
        if old_index>=0:self.device_combo.setCurrentIndex(old_index)
        self.device_combo.blockSignals(False)
        online=sum(x.get("state")=="device" for x in result)
        self.work_values["count"].setText(str(len(result)))
        self.connection_status.setText("● "+str(online)+" 台设备在线")
        if not result:
            self.info={}
            for key in self.work_values:
                if key!="count":self.work_values[key].setText("—")
            return
        self.selection_changed()

    def selection_changed(self,*_):
        serial=self.serial()
        if not serial:return
        selected=next((x for x in self.devices if x.get("serial")==serial),{})
        if selected.get("state")!="device":
            self.foot_status.setText("设备尚未授权："+serial)
            return
        self.run_task("设备详情",lambda:self.bridge.device_info(serial),self.display_info,silent=True)

    def display_info(self,info):
        self.info=info
        self.work_values["model"].setText(str(info.get("model") or "未知"))
        self.work_values["version"].setText("v"+str(info.get("installed_version")) if info.get("installed_version") else "未部署")
        self.work_values["ip"].setText(str(info.get("preferred_ip") or "未检测到"))
        self.work_device_label.setText(
            f"型号：{info.get('manufacturer','—')} {info.get('model','—')}\n"
            f"系统：Android {info.get('android','—')} · {info.get('abi','—')}\n"
            f"构建：{info.get('build','—')}\n"
            f"ADB：{info.get('adb_serial','—')}"
        )
        for key,label in self.detail_labels.items():
            val=info.get(key)
            label.setText(str(val) if val else "—")
        ips=[str(ip) for ip in info.get("ips",[]) if ip]
        pref=str(info.get("preferred_ip") or "")
        self.ip_combo.blockSignals(True)
        self.ip_combo.clear()
        for ip in ips:
            self.ip_combo.addItem(ip)
        if pref:
            if pref not in ips:self.ip_combo.addItem(pref)
            self.ip_combo.setCurrentText(pref)
        self.ip_combo.blockSignals(False)
        iface=", ".join(
            str(a.get("ip"))+"（"+str(a.get("interface"))+"）"
            for a in info.get("network_addresses",[])
            if a.get("role")!="蜂窝/隧道"
        )
        self.ip_note.setText("设备局域网地址："+(iface or "未检测到，请核实网关"))
        installed=bool(info.get("installed_version"))
        self.keep_auth.setEnabled(installed)
        self.keep_auth.setChecked(installed)
        self.update_install_auth_ui()
        if installed and self._page_index==3:
            self.load_auth()

    def connect_wireless(self):
        endpoint,ok=QInputDialog.getText(self,"连接无线 ADB","输入设备 IP:端口：",text="192.168.0.1:5555")
        if not ok or not endpoint.strip():return
        self.run_task("连接无线 ADB",lambda:self.bridge.connect(endpoint.strip()),
            lambda _:self.refresh_devices())

    def open_web(self):
        if not self.require_serial():return
        ip=self.info.get("preferred_ip")
        if not ip:
            self.show_error("设备尚未识别到可访问的局域网管理地址。")
            return
        self.run_task("打开网页控制台",lambda:self.bridge.open_web(ip))

    def reboot_confirm(self):
        self.power_confirm("重启","reboot")

    def poweroff_confirm(self):
        self.power_confirm("关机","poweroff")

    def power_confirm(self,label,method):
        serial=self.require_serial()
        if not serial:return
        answer,ok=QInputDialog.getText(self,"危险操作确认",f"设备可能立即断开连接。\n请输入“{label}”确认：")
        if not ok or answer!=label:return
        self.run_task(label+"设备",lambda:getattr(self.bridge,method)(serial),lambda _:self.refresh_devices())

    def load_apps(self,*_):
        serial=self.serial()
        if not serial or self._page_index!=2:return
        system=self.app_mode.currentIndex()==1
        self.apps_system=system
        self.run_task("读取应用列表",lambda:self.bridge.list_apps(serial,system),self.display_apps,silent=True)

    def display_apps(self,apps):
        self.apps=apps
        self.filter_apps()

    def filter_apps(self,*_):
        query=self.app_query.text().strip().lower()
        visible=[app for app in self.apps if query in app.get("name","").lower()]
        self.app_table.setRowCount(len(visible))
        for n,app in enumerate(visible):
            self.app_table.setItem(n,0,QTableWidgetItem(app.get("name","")))
            self.app_table.setItem(n,1,QTableWidgetItem(
                "已停用" if app.get("disabled") else ("系统" if app.get("system") else "普通应用")))
        self.app_table.resizeRowsToContents()

    def selected_package(self):
        selections=self.app_table.selectionModel().selectedRows()
        if not selections:
            self.show_error("请在应用列表中选择一个包。")
            return ""
        item=self.app_table.item(selections[0].row(),0)
        return item.text() if item else ""

    def uninstall_app(self):
        serial=self.require_serial()
        if not serial:return
        if self.apps_system:
            self.show_error("不能卸载系统应用；需要停用时请使用停用功能。")
            return
        pkg=self.selected_package()
        if not pkg:return
        typed,ok=QInputDialog.getText(self,"卸载确认","请完整输入以下包名以确认卸载：\n"+pkg)
        if not ok or typed!=pkg:return
        self.run_task("卸载应用",lambda:self.bridge.uninstall_app(serial,pkg),
            lambda _:self.load_apps())

    def toggle_system_app(self,enabled):
        serial=self.require_serial()
        if not serial:return
        if not self.apps_system:
            self.show_error("请先将右上角列表切换为「系统应用」。")
            return
        pkg=self.selected_package()
        if not pkg:return
        verb="恢复" if enabled else "停用"
        typed,ok=QInputDialog.getText(self,verb+"系统组件",f"请完整输入包名以确认{verb}：\n"+pkg)
        if not ok or typed!=pkg:return
        self.run_task(verb+"系统组件",
            lambda:self.bridge.set_system_app(serial,pkg,enabled),
            lambda _:self.load_apps())

    def update_install_auth_ui(self,*_):
        needs_choice=not self.keep_auth.isEnabled() or not self.keep_auth.isChecked()
        self.install_login.setEnabled(needs_choice)
        self.install_password.setEnabled(needs_choice and self.install_login.isChecked())
        self.keep_auth.setVisible(self.keep_auth.isEnabled())

    def update_change_auth_ui(self,*_):
        self.change_password.setEnabled(self.change_login.isChecked())

    def install_auth_options(self):
        keep=self.keep_auth.isEnabled() and self.keep_auth.isChecked()
        if keep:return (None,"")
        enabled=self.install_login.isChecked()
        password=self.install_password.text()
        if enabled and not password:
            self.show_error("开启密码登录时请输入密码。没有复杂度要求，一个字符也可以。")
            return None
        if not enabled:
            confirm=QMessageBox.question(self,"关闭网页密码",
                "关闭登录后，连接同一 Wi-Fi 的其他设备也可以直接控制 Android。\n确认不启用密码吗？",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if confirm!=QMessageBox.StandardButton.Yes:
                return None
        return enabled,password

    def install_latest(self):
        serial=self.require_serial()
        if not serial:return
        options=self.install_auth_options()
        if options is None:return
        ip=self.ip_combo.currentText().strip()
        enabled,password=options
        self.run_task("部署 GitHub 最新版",
            lambda:self.bridge.install_latest(serial,ip,enabled,password),
            self.installed_success)

    def install_local(self):
        serial=self.require_serial()
        if not serial:return
        options=self.install_auth_options()
        if options is None:return
        path,_=QFileDialog.getOpenFileName(self,"选择 ARM64 ZIP 安装包","","ZIP 文件 (*.zip)")
        if not path:return
        ip=self.ip_combo.currentText().strip()
        enabled,password=options
        self.run_task("部署本地 ZIP",
            lambda:self.bridge.install_local(serial,ip,path,enabled,password),
            self.installed_success)

    def installed_success(self,result):
        if result.get("auth_kept"):
            auth_status = "登录设置：保留了原有设置（不显示已保存的密码）"
        elif result.get("password"):
            auth_status = "本次自定义登录密码："+str(result["password"])
        else:
            auth_status = "网页登录：无需密码"
        self.last_install.setText("✓ 安装成功：v"+str(result.get("version"))+
            "\n访问地址："+str(result.get("url"))+"\n"+auth_status)
        self.install_password.clear()
        self.refresh_devices()
        self.load_auth()

    def uninstall_service(self):
        serial=self.require_serial()
        if not serial:return
        reply=QMessageBox.warning(self,"卸载设备端",
            "将删除本项目已安装的服务及其配置（包括访问密码）。\n确认卸载吗？",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if reply!=QMessageBox.StandardButton.Yes:return
        self.run_task("卸载网页服务",lambda:self.bridge.uninstall(serial),
            lambda r:(self.last_install.setText(str(r)),self.refresh_devices()))

    def load_auth(self):
        serial=self.serial()
        if not serial or not self.info.get("installed_version"):return
        self.run_task("读取网页认证配置",lambda:self.bridge.read_auth(serial),self.display_auth,silent=True)

    def display_auth(self,config):
        enabled=bool(config.get("enabled"))
        self.change_login.blockSignals(True)
        self.change_login.setChecked(enabled)
        self.change_login.blockSignals(False)
        self.current_auth.setText("当前状态："+("已开启密码登录" if enabled else "无需登录"))
        self.update_change_auth_ui()

    def save_auth(self):
        serial=self.require_serial()
        if not serial:return
        enabled=self.change_login.isChecked()
        password=self.change_password.text()
        if enabled and not password and "无需登录" in self.current_auth.text():
            self.show_error("启用密码验证时需要设置一个密码。")
            return
        if not enabled:
            reply=QMessageBox.question(self,"关闭密码确认",
                "关闭后，同一局域网内能访问 8765 的设备都可以远程控制。\n确认保存吗？",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if reply!=QMessageBox.StandardButton.Yes:return
        self.run_task("更新网页登录配置",
            lambda:self.bridge.configure_auth(serial,enabled,password),
            lambda _:(self.change_password.clear(),self.load_auth(),
                      QMessageBox.information(self,"已完成","网页登录设置已保存并重新启动服务。")))

    def refresh_logs(self):
        lines=[]
        for event in self.bridge.get_logs():
            lines.append(f"[{event.get('time','')}] {event.get('level','info').upper():<7} {event.get('message','')}")
        text="\n".join(lines[-160:])
        if text!=self.log_view.toPlainText():
            self.log_view.setPlainText(text)
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def clear_logs(self):
        self.bridge.clear_logs()
        self.refresh_logs()
