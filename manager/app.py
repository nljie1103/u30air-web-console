"""Native Windows GUI for Android Web Desktop Manager."""
from __future__ import annotations

import argparse
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import webbrowser

from adb_client import ADB, ADBError, Device, locate_adb
from deployment import (
    parse_package, fetch_release, download_release,
    install_on_device, uninstall_from_device, official_adb_download,
)


APP_VERSION = "2.1.0"
BG = "#F4F6F9"
WHITE = "#FFFFFF"
INK = "#1D2635"
MUTED = "#68768A"
LINE = "#E1E6ED"
ACCENT = "#2C425C"
GREEN = "#15835D"
RED = "#B73434"
FONT = "Microsoft YaHei UI"


class Manager:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"Android Web Desktop Manager  ·  v{APP_VERSION}")
        root.geometry("1160x760")
        root.minsize(950, 630)
        root.configure(bg=BG)
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.adb_path = locate_adb()
        self.devices: list[Device] = []
        self.serial: str | None = None
        self.info: dict = {}
        self.apps: list[tuple[str, str, bool]] = []
        self.web_address: str | None = None
        self.password: str | None = None
        self.filter_text = tk.StringVar()
        self.system_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="准备就绪")
        self.version_var = tk.StringVar(value="未检测")
        self.model_var = tk.StringVar(value="—")
        self.android_var = tk.StringVar(value="—")
        self.build_var = tk.StringVar(value="—")
        self.abi_var = tk.StringVar(value="—")
        self.ip_var = tk.StringVar(value="—")
        self.serial_var = tk.StringVar(value="尚未连接设备")
        self.adb_var = tk.StringVar(value=str(self.adb_path) if self.adb_path else "未找到 ADB，请选择路径或下载官方工具")
        self._style()
        self._build()
        self.root.after(70, self._pump)
        self.root.after(200, self.refresh_devices)
        self.root.after(7000, self._auto_refresh)

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK,
                        rowheight=30, borderwidth=0, font=(FONT, 10))
        style.configure("Treeview.Heading", background="#F0F2F5", foreground=INK,
                        font=(FONT, 10, "bold"), relief="flat", padding=(6, 8))
        style.map("Treeview", background=[("selected", "#DDE7F2")], foreground=[("selected", INK)])
        style.configure("App.TNotebook", background=BG, borderwidth=0)
        style.configure("App.TNotebook.Tab", font=(FONT, 10), padding=(16, 10), foreground=INK)

    def _label(self, parent, text, size=10, color=INK, bold=False, **kw):
        return tk.Label(parent, text=text, font=(FONT, size, "bold" if bold else "normal"),
                        fg=color, bg=parent.cget("bg"), **kw)

    def _button(self, parent, text, command, primary=False, danger=False, width=None):
        bg = RED if danger else ACCENT if primary else "#E9EDF2"
        fg = WHITE if primary or danger else INK
        btn = tk.Button(parent, text=text, command=command, font=(FONT, 10),
                        bg=bg, fg=fg, activebackground="#405A76" if primary else "#D8E0EA",
                        activeforeground=WHITE if primary else INK, relief="flat",
                        padx=13, pady=8, cursor="hand2", bd=0, width=width)
        return btn

    def _card(self, parent, **kw):
        card = tk.Frame(parent, bg=WHITE, highlightbackground=LINE, highlightthickness=1, **kw)
        return card

    def _build(self):
        header = tk.Frame(self.root, bg=WHITE, height=76)
        header.pack(fill="x")
        header.pack_propagate(False)
        self._label(header, "Android Web Desktop", 17, INK, True).pack(side="left", padx=(25, 8), pady=22)
        self._label(header, "设备管理器", 10, MUTED).pack(side="left", pady=25)
        self._label(header, f"v{APP_VERSION}", 10, MUTED).pack(side="right", padx=27)
        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x")

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=19)
        main.columnconfigure(0, minsize=280, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = self._card(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
        left.columnconfigure(0, weight=1)
        title = tk.Frame(left, bg=WHITE)
        title.pack(fill="x", padx=16, pady=(17, 6))
        self._label(title, "已连接设备", 12, INK, True).pack(side="left")
        self._button(title, "刷新", self.refresh_devices).pack(side="right")

        self.tree = ttk.Treeview(left, columns=("state",), show="tree headings", height=10)
        self.tree.heading("#0", text="设备")
        self.tree.heading("state", text="状态")
        self.tree.column("#0", width=155, minwidth=100)
        self.tree.column("state", width=93, anchor="center", minwidth=70)
        self.tree.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection)
        self._label(left, "ADB 连接", 11, INK, True).pack(anchor="w", padx=16, pady=(10, 2))
        self._label(left, "支持 USB 调试与已开启的无线 ADB。", 9, MUTED, wraplength=245, justify="left").pack(anchor="w", padx=16, pady=(0, 10))
        self._button(left, "连接局域网设备", self._connect).pack(fill="x", padx=16, pady=(0, 10))
        self._label(left, "ADB 可执行文件", 9, MUTED).pack(anchor="w", padx=16)
        tk.Label(left, textvariable=self.adb_var, bg=WHITE, fg=MUTED, wraplength=238, justify="left",
                 font=(FONT, 8)).pack(anchor="w", padx=16, pady=(4, 8))
        adb_row = tk.Frame(left, bg=WHITE)
        adb_row.pack(fill="x", padx=16, pady=(0, 16))
        self._button(adb_row, "选择 ADB", self._choose_adb).pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(adb_row, "获取官方 ADB", self._get_adb).pack(side="left", fill="x", expand=True)

        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        overview = self._card(right)
        overview.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        headerrow = tk.Frame(overview, bg=WHITE)
        headerrow.pack(fill="x", padx=20, pady=(16, 8))
        self._label(headerrow, "设备概况", 12, INK, True).pack(side="left")
        self._label(headerrow, "", 9).pack(side="left")
        tk.Label(headerrow, textvariable=self.serial_var, font=(FONT, 9), bg=WHITE, fg=MUTED).pack(side="right")
        stats = tk.Frame(overview, bg=WHITE)
        stats.pack(fill="x", padx=20, pady=(0, 14))
        fields = [
            ("设备型号", self.model_var), ("Android 版本", self.android_var),
            ("系统构建号", self.build_var), ("处理器架构", self.abi_var),
            ("设备局域网 IP", self.ip_var), ("网页桌面版本", self.version_var),
        ]
        for i, (name, variable) in enumerate(fields):
            item = tk.Frame(stats, bg="#F7F9FB", highlightbackground=LINE, highlightthickness=1)
            item.grid(row=i//3, column=i%3, sticky="ew", padx=4, pady=4, ipadx=9, ipady=8)
            stats.columnconfigure(i%3, weight=1)
            tk.Label(item, text=name, fg=MUTED, bg="#F7F9FB", font=(FONT, 9)).pack(anchor="w", padx=7)
            tk.Label(item, textvariable=variable, fg=INK, bg="#F7F9FB", font=(FONT, 10, "bold"),
                     anchor="w", wraplength=205, justify="left").pack(anchor="w", padx=7, pady=(5, 0))
        actions = tk.Frame(overview, bg=WHITE)
        actions.pack(fill="x", padx=20, pady=(0, 17))
        self._button(actions, "一键安装 / 升级", self._install_latest, primary=True).pack(side="left", padx=(0, 7))
        self._button(actions, "选择本地安装包", self._install_local).pack(side="left", padx=(0, 7))
        self._button(actions, "打开网页桌面", self._open_web).pack(side="left", padx=(0, 7))
        self._button(actions, "卸载本项目", self._uninstall, danger=True).pack(side="right")

        book = ttk.Notebook(right, style="App.TNotebook")
        book.grid(row=1, column=0, sticky="nsew")
        apps_page = tk.Frame(book, bg=WHITE)
        tools_page = tk.Frame(book, bg=WHITE)
        logs_page = tk.Frame(book, bg=WHITE)
        book.add(apps_page, text="应用管理")
        book.add(tools_page, text="设备控制")
        book.add(logs_page, text="运行日志")

        apphead = tk.Frame(apps_page, bg=WHITE)
        apphead.pack(fill="x", padx=16, pady=(14, 10))
        self._label(apphead, "已安装应用", 11, INK, True).pack(side="left")
        self._button(apphead, "刷新应用", self._load_apps).pack(side="right")
        controls = tk.Frame(apps_page, bg=WHITE)
        controls.pack(fill="x", padx=16, pady=(0, 11))
        self.search_entry = tk.Entry(controls, textvariable=self.filter_text, relief="solid", bd=1,
                                     font=(FONT, 10), fg=INK)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 14))
        self.filter_text.trace_add("write", lambda *_: self._filter_apps())
        tk.Checkbutton(controls, text="显示系统组件", variable=self.system_var, bg=WHITE,
                       font=(FONT, 9), command=self._load_apps).pack(side="left")
        columns = ("kind", "state")
        self.apps_tree = ttk.Treeview(apps_page, columns=columns, show="tree headings", height=10)
        self.apps_tree.heading("#0", text="包名")
        self.apps_tree.heading("kind", text="类型")
        self.apps_tree.heading("state", text="状态")
        self.apps_tree.column("#0", width=440)
        self.apps_tree.column("kind", width=105, anchor="center")
        self.apps_tree.column("state", width=90, anchor="center")
        self.apps_tree.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        appactions = tk.Frame(apps_page, bg=WHITE)
        appactions.pack(fill="x", padx=16, pady=(0, 13))
        self._button(appactions, "卸载普通应用", self._uninstall_app).pack(side="left", padx=(0, 9))
        self._button(appactions, "停用系统组件（高级）", self._disable_app).pack(side="left", padx=(0, 9))
        self._button(appactions, "恢复系统组件", self._enable_app).pack(side="left")

        self._label(tools_page, "电源与设备维护", 12, INK, True).pack(anchor="w", padx=22, pady=(23, 14))
        self._label(tools_page, "对选中设备执行操作。所有重启、关机指令都需要明确确认。", 10, MUTED).pack(anchor="w", padx=22)
        row = tk.Frame(tools_page, bg=WHITE)
        row.pack(anchor="w", padx=22, pady=22)
        self._button(row, "重新启动", self._restart, primary=True).pack(side="left", padx=(0, 12))
        self._button(row, "关闭设备电源", self._poweroff, danger=True).pack(side="left")
        self._label(tools_page, "部分设备不允许 ADB 直接关机，或者关机后需要物理按键才能重新启动。", 9, MUTED,
                    wraplength=520).pack(anchor="w", padx=22)

        self.logs = tk.Text(logs_page, bg="#FAFBFC", fg=INK, font=("Consolas", 10),
                            relief="flat", borderwidth=0, wrap="word", state="disabled")
        self.logs.pack(fill="both", expand=True, padx=14, pady=14)

        footer = tk.Frame(self.root, bg=WHITE, height=34)
        footer.pack(fill="x", side="bottom")
        tk.Label(footer, textvariable=self.status_var, bg=WHITE, fg=MUTED, font=(FONT, 9),
                 anchor="w").pack(fill="x", padx=23, pady=7)

    def _pump(self):
        for _ in range(30):
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._log(payload)
            elif kind == "status":
                self.status_var.set(payload)
            elif kind == "ok":
                cb, result = payload
                self.busy = False
                self.status_var.set("操作完成")
                cb(result)
            elif kind == "error":
                self.busy = False
                self.status_var.set("操作失败")
                self._log("错误：" + str(payload))
                messagebox.showerror("操作失败", str(payload), parent=self.root)
        self.root.after(110, self._pump)

    def _log(self, message):
        self.logs.configure(state="normal")
        self.logs.insert("end", str(message) + "\n")
        self.logs.see("end")
        self.logs.configure(state="disabled")

    def _work(self, description, task, completed=lambda _: None):
        if self.busy:
            self.status_var.set("有一项操作正在执行，请稍后再试")
            return
        self.busy = True
        self.status_var.set(description)
        self._log("▶ " + description)

        def run():
            try:
                result = task()
                self.events.put(("ok", (completed, result)))
            except Exception as exc:
                self.events.put(("error", exc))

        threading.Thread(target=run, daemon=True).start()

    def _progress(self, message):
        self.events.put(("status", str(message)))
        self.events.put(("log", str(message)))

    def _adb(self):
        if not self.adb_path:
            raise ADBError("没有检测到 ADB，请先选择 adb.exe 或下载官方工具")
        return ADB(self.adb_path)

    def _selected(self):
        if not self.serial:
            raise ValueError("请先选择一台已授权且在线的 Android 设备")
        return self.serial

    def refresh_devices(self):
        if not self.adb_path:
            self.status_var.set("未找到 ADB，可点击左侧获取官方 ADB")
            return

        def done(devices):
            previous = self.serial
            self.devices = devices
            self.tree.delete(*self.tree.get_children())
            for d in devices:
                self.tree.insert("", "end", iid=d.serial, text=d.serial, values=(d.state,))
            if previous and previous in {d.serial for d in devices if d.state == "device"}:
                self.tree.selection_set(previous)
            elif len([d for d in devices if d.state == "device"]) == 1:
                target = next(d.serial for d in devices if d.state == "device")
                self.tree.selection_set(target)
            elif not devices:
                self.serial = None
                self._reset()
            self.status_var.set(f"发现 {len(devices)} 台设备；'device' 表示已授权且在线")
        self._work("正在扫描 ADB 设备…", lambda: self._adb().devices(), done)

    def _on_selection(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        serial = selection[0]
        self.serial = serial
        d = next((d for d in self.devices if d.serial == serial), None)
        if not d or d.state != "device":
            self._reset()
            self.serial_var.set(serial + "  ·  " + (d.state if d else "不可用"))
            return
        self.serial_var.set(serial)
        self._work("正在读取设备信息…", lambda: self._adb().device_info(serial), self._show_info)

    def _reset(self):
        for v in (self.model_var, self.android_var, self.build_var, self.abi_var, self.ip_var):
            v.set("—")
        self.version_var.set("未检测")
        self.info = {}
        self.web_address = None
        self.apps = []
        self._filter_apps()

    def _show_info(self, data):
        self.info = data
        self.model_var.set(" ".join(filter(None, [data.get("brand"), data.get("model")])) or "未知")
        self.android_var.set(data.get("android") or "未知")
        self.build_var.set(data.get("build") or "未知")
        self.abi_var.set(data.get("abi") or "未知")
        self.ip_var.set(", ".join(data.get("ips") or []) or "未知")
        ver = data.get("installed_version")
        self.version_var.set("v" + ver if ver else "未安装")
        if ver:
            ips = data.get("ips") or []
            self.web_address = f"http://{ips[0]}:8765" if ips else None
        else:
            self.web_address = None
        self._load_apps()

    def _load_apps(self):
        if not self.serial or not self.info:
            return
        serial = self.serial
        system = self.system_var.get()

        def task():
            adb = self._adb()
            names = adb.packages(serial, system=system)
            disabled = adb.disabled_packages(serial) if system else set()
            return [(name, "系统" if system else "用户", name in disabled) for name in names]

        def done(apps):
            if self.serial != serial or self.system_var.get() != system:
                return
            self.apps = apps
            self._filter_apps()
            self._log(f"已读取 {len(apps)} 个{'系统' if system else '用户'}应用")
        self._work("正在获取应用列表…", task, done)

    def _filter_apps(self):
        if not hasattr(self, "apps_tree"):
            return
        phrase = self.filter_text.get().lower().strip()
        self.apps_tree.delete(*self.apps_tree.get_children())
        for pkg, kind, disabled in self.apps:
            if phrase and phrase not in pkg.lower():
                continue
            self.apps_tree.insert("", "end", iid=pkg, text=pkg, values=(kind, "已停用" if disabled else "已启用"))

    def _app_selected(self):
        ids = self.apps_tree.selection()
        if not ids:
            raise ValueError("请先在应用列表选择一个包名")
        return ids[0]

    def _choose_adb(self):
        value = filedialog.askopenfilename(parent=self.root, title="选择 adb.exe", filetypes=[("ADB executable", "adb.exe"), ("所有文件", "*.*")])
        if value:
            self.adb_path = Path(value)
            self.adb_var.set(value)
            self.refresh_devices()

    def _get_adb(self):
        if not messagebox.askyesno("下载官方 ADB", "将从 Google 官方地址下载 Android Platform Tools 中的 ADB。\n需要联网，文件将保存在当前用户的本地目录。是否继续？", parent=self.root):
            return
        def done(path):
            self.adb_path = Path(path)
            self.adb_var.set(str(path))
            messagebox.showinfo("已就绪", "官方 ADB 已安装，正在扫描设备。", parent=self.root)
            self.refresh_devices()
        self._work("下载官方 Android Platform Tools…", lambda: official_adb_download(self._progress), done)

    def _connect(self):
        address = simpledialog.askstring("无线 ADB 连接", "输入已开启无线 ADB 的设备 IP:端口\n例如 192.168.1.20:5555", parent=self.root)
        if not address:
            return
        self._work("正在连接无线 ADB…", lambda: self._adb().connect(address),
                   lambda s: (self._log(s), self.refresh_devices()))

    def _target_ip(self):
        ips = self.info.get("ips") or []
        if len(ips) == 1:
            return ips[0]
        answer = simpledialog.askstring("网页监听地址", "请输入设备用于浏览器访问的局域网 IPv4：\n" + (", ".join(ips) if ips else "未自动检测到 IP"), initialvalue=ips[0] if ips else "", parent=self.root)
        if not answer:
            return None
        return answer.strip()

    def _install_latest(self):
        try:
            serial = self._selected()
        except ValueError as exc:
            messagebox.showwarning("请选择设备", str(exc), parent=self.root)
            return
        ip = self._target_ip()
        if not ip:
            return
        if not messagebox.askyesno("安装最新版", f"即将向设备 {serial} 安装最新稳定版本。\n\n会短暂重启设备上的网页桌面服务，不会刷写固件。\n是否继续？", parent=self.root):
            return

        def task():
            release = fetch_release()
            self._progress(f"找到 v{release['version']}，验证安装包…")
            package = parse_package(download_release(release, self._progress))
            if release["version"] != package.version:
                raise ValueError("Release 版本与安装包内版本不一致")
            url, password = install_on_device(self._adb(), serial, package, ip, progress=self._progress)
            return url, password, package.version

        self._work("下载并安装最新版…", task, lambda x: self._installed(serial, x))

    def _install_local(self):
        try:
            serial = self._selected()
        except ValueError as exc:
            messagebox.showwarning("请选择设备", str(exc), parent=self.root)
            return
        source = filedialog.askopenfilename(parent=self.root, title="选择 Android ARM64 安装 ZIP",
                                            filetypes=[("安装包 ZIP", "*.zip")])
        if not source:
            return
        ip = self._target_ip()
        if not ip or not messagebox.askyesno("确认离线安装", "本地 ZIP 不能通过 GitHub 发布摘要验证，请确保它来自可信来源。\n确认安装吗？", parent=self.root):
            return

        def task():
            data = Path(source).read_bytes()
            package = parse_package(data)
            url, password = install_on_device(self._adb(), serial, package, ip, progress=self._progress)
            return url, password, package.version

        self._work("安装本地 ZIP…", task, lambda x: self._installed(serial, x))

    def _installed(self, serial, result):
        url, password, version = result
        self.web_address, self.password = url, password
        self.version_var.set("v" + version)
        self._log(f"成功安装 v{version}：{url}")
        if messagebox.askyesno("安装成功", f"版本：v{version}\n地址：{url}\n\n管理口令：{password}\n\n是否将口令复制到剪贴板？", parent=self.root):
            self.root.clipboard_clear()
            self.root.clipboard_append(password)
        if messagebox.askyesno("打开网页桌面", "是否在浏览器中打开网页控制台？", parent=self.root):
            webbrowser.open(url)

    def _uninstall(self):
        try:
            serial = self._selected()
        except ValueError as exc:
            messagebox.showwarning("请选择设备", str(exc), parent=self.root)
            return
        version = self.info.get("installed_version") or self.version_var.get()
        if version in ("未检测", "未安装"):
            messagebox.showinfo("未安装", "当前设备没有检测到网页桌面服务。", parent=self.root)
            return
        if not messagebox.askyesno("卸载网页桌面", f"将从 {serial} 删除本项目的程序、登录密码、日志及历史版本。\n\n这是不可恢复的配置清理操作，确认卸载吗？", parent=self.root):
            return
        confirm = simpledialog.askstring("再次确认", "请输入 卸载 以继续：", parent=self.root)
        if confirm != "卸载":
            return

        def done(result):
            self._log(result)
            self.version_var.set("未安装")
            self.info["installed_version"] = None
            self.web_address = None
            messagebox.showinfo("卸载完成", result, parent=self.root)
        self._work("正在卸载网页桌面…", lambda: uninstall_from_device(self._adb(), serial), done)

    def _open_web(self):
        if self.web_address:
            webbrowser.open(self.web_address)
        else:
            messagebox.showinfo("没有可用地址", "请先安装网页桌面，并确认设备具有可访问的局域网 IP。", parent=self.root)

    def _uninstall_app(self):
        try:
            serial, package = self._selected(), self._app_selected()
        except ValueError as exc:
            messagebox.showwarning("请选择应用", str(exc), parent=self.root)
            return
        selected = next((a for a in self.apps if a[0] == package), None)
        if not selected or selected[1] == "系统":
            messagebox.showwarning("不支持", "普通应用卸载只支持用户安装的应用。系统组件请使用高级管理功能。", parent=self.root)
            return
        if not messagebox.askyesno("卸载普通应用", f"从用户 0 卸载以下应用：\n\n{package}\n\n其应用数据可能丢失。确认继续？", parent=self.root):
            return
        self._work("正在卸载应用…", lambda: self._adb().remove_user_app(serial, package),
                   lambda result: (self._log(result), self._load_apps()))

    def _toggle_app(self, enable):
        try:
            serial, package = self._selected(), self._app_selected()
        except ValueError as exc:
            messagebox.showwarning("请选择应用", str(exc), parent=self.root)
            return
        selected = next((a for a in self.apps if a[0] == package), None)
        if not selected or selected[1] != "系统":
            messagebox.showwarning("仅系统组件", "该功能只针对系统组件。", parent=self.root)
            return
        action = "恢复" if enable else "停用"
        if not messagebox.askyesno("系统组件风险确认",
                                   f"即将在用户 0 上{action}系统包：\n{package}\n\n错误操作可能导致设备失去网络、桌面或启动能力。\n不建议操作不了解的包。确认继续？",
                                   parent=self.root):
            return
        typed = simpledialog.askstring("确认系统包名", "请输入完整包名确认操作：", parent=self.root)
        if typed != package:
            messagebox.showinfo("已取消", "包名不匹配，未执行任何操作。", parent=self.root)
            return
        self._work(f"正在{action}系统组件…", lambda: self._adb().toggle_system_app(serial, package, enable),
                   lambda result: (self._log(result), self._load_apps()))

    def _disable_app(self):
        self._toggle_app(False)

    def _enable_app(self):
        self._toggle_app(True)

    def _restart(self):
        if not self.serial:
            messagebox.showwarning("未选择设备", "请先选择设备", parent=self.root)
            return
        if not messagebox.askyesno("重启设备", f"确定重启 {self.serial} 吗？连接会暂时中断。", parent=self.root):
            return
        serial = self.serial
        self._work("正在请求重启…", lambda: self._adb().restart(serial),
                   lambda _: (self._log("已发送重启命令"), self.root.after(4000, self.refresh_devices)))

    def _poweroff(self):
        if not self.serial:
            messagebox.showwarning("未选择设备", "请先选择设备", parent=self.root)
            return
        if not messagebox.askyesno("关闭设备电源", f"确定关闭 {self.serial} 的电源吗？\n\n部分设备关机后无法远程重新开机，需要现场按键。", icon="warning", parent=self.root):
            return
        serial = self.serial
        self._work("正在请求关机…", lambda: self._adb().poweroff(serial),
                   lambda _: self._log("已发送关机指令"))

    def _auto_refresh(self):
        if not self.busy and self.adb_path:
            self.refresh_devices()
        self.root.after(9000, self._auto_refresh)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="run a packaged executable smoke test")
    parser.add_argument("--gui-smoke-test", action="store_true", help="launch the GUI and exit after 2s")
    options = parser.parse_args()
    if options.self_test:
        print(f"Android Web Desktop Manager v{APP_VERSION} self-test OK")
        return
    window = tk.Tk()
    Manager(window)
    if options.gui_smoke_test:
        window.after(2200, window.destroy)
    window.mainloop()


if __name__ == "__main__":
    main()
