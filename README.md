<div align="center">

# 🖥️ Android Web Desktop

**让 Android 设备管理和远程桌面操作更简单。**

提供 Windows 图形化设备管理器与设备本机网页桌面服务。通过 USB 或无线 ADB 部署一次，之后可在同一局域网的浏览器中查看和操作 Android。

[![Latest Release](https://img.shields.io/github/v/release/nljie1103/u30air-web-console?style=for-the-badge)](https://github.com/nljie1103/u30air-web-console/releases/latest)
[![Build](https://img.shields.io/github/actions/workflow/status/nljie1103/u30air-web-console/release.yml?branch=main&style=for-the-badge)](https://github.com/nljie1103/u30air-web-console/actions)
[![Platform](https://img.shields.io/badge/Android-ARM64-63768b?style=for-the-badge)](#system-requirements)

[**下载 Windows 管理器**](https://github.com/nljie1103/u30air-web-console/releases/latest/download/AndroidWebDesktopManager.exe) · [**下载 Android 安装包**](https://github.com/nljie1103/u30air-web-console/releases/latest/download/android-web-desktop-arm64.zip) · [**问题反馈**](https://github.com/nljie1103/u30air-web-console/issues)

</div>

---

## ✨ 功能

| 组件 | 能力 |
|:---|:---|
| **Windows 图形化管理器** | Vue 3 可收缩侧边栏、设备总览、ADB 状态、型号、系统信息与快捷操作 |
| **安装与卸载** | 从 GitHub 下载并校验最新版，通过 ADB 健康检查确认服务已启动；支持本地离线 ZIP、一键卸载与失败回滚 |
| **设备控制** | 局域网 ADB 连接、重启、关机、应用查询与普通应用卸载 |
| **高级应用管理** | 可查询系统应用、停用和恢复非关键系统组件，操作前需要二次确认 |
| **设备本机网页桌面** | 定时屏幕预览、点击与滑动、系统按键、用户应用启动 |
| **网页内在线更新** | 手动检查 Release、验证 SHA256、切换版本，健康检查失败时尝试恢复旧版 |

网页端目前采用 Android 系统截图方式定时更新画面，**不是高帧率视频流**。系统组件停用不等于永久删除系统分区文件。

---

<a id="system-requirements"></a>

## 💻 运行环境与安全

| 组件 | 运行要求 |
|:---|:---|
| Windows 管理器 | Windows 10/11 x64、Microsoft WebView2 Runtime；EXE 不需额外安装 Python |
| Android 设备 | ARM64（`arm64-v8a`）、可用的 ADB Shell |
| ADB | 已连接并授权的 USB 调试设备，或已启用无线调试的 Android 设备 |
| 网页控制 | 支持 JavaScript 的现代浏览器，能够连接设备局域网 IPv4 地址 |
| 在线安装/更新 | Windows 管理器或设备可访问对应 GitHub Release |

> **操作须知：** 首次安装需要设备已开启并授权 ADB；管理器无法绕过调试授权。网页控制台默认使用 HTTP，仅可用于可信局域网，禁止直接将网页端口、ADB 或 VNC 端口映射到公网。关机可能需要现场操作才能重新开机，停用系统组件可能造成设备功能异常；请先备份重要数据。

---

## 📥 下载与安装

### Windows · 推荐

1. 从 [最新 Release](https://github.com/nljie1103/u30air-web-console/releases/latest) 下载 **`AndroidWebDesktopManager.exe`** 并运行。
2. 通过 USB 连接已授权的 Android 设备，或者点击 **连接局域网设备** 输入已开启无线 ADB 的地址。
3. 如果系统尚未安装 ADB，可在管理器中选择现有 `adb.exe`，或手动确认下载 Google 官方 Platform Tools。
4. 选择设备后，查看其型号、系统版本和网页桌面安装状态，点击 **一键安装 / 升级**。
5. 安装成功后，管理器显示访问网址及首次登录口令，随后用浏览器打开设备网页桌面。

管理器也支持从 [Release](https://github.com/nljie1103/u30air-web-console/releases/latest) 下载完整 ARM64 ZIP 后点击 **选择本地安装包**，在没有互联网连接时部署。安装过程中不会刷写系统固件。

### Linux / macOS · ADB 脚本

下载 `android-web-desktop-arm64.zip` 并解压，在安装包目录运行：

```bash
bash installer/install_linux_mac.sh
```

若连接多台设备或需要明确指定访问地址：

```bash
bash installer/install_linux_mac.sh <ADB序列号> <设备局域网IPv4> 8765
```

---

## 🌐 网页桌面

Windows 管理器采用 Vue 3 与 WebView2，提供可折叠导航栏、设备工作台、应用管理、部署与更新、日志和设置页面。前端资源通过仅监听 `127.0.0.1` 随机端口的本机静态服务加载，不向局域网开放 Windows 管理桥接接口。安装后可从管理器打开设备端网页控制台，在浏览器中查看 Android 画面、点击滑动和使用系统按键。

支持的操作受到 Android 系统权限限制。没有可截图的显示画面，或系统禁止通过 ADB 模拟触控时，相应功能可能不可用。需要实时帧率时，可以额外使用支持网页访问的 VNC 方案。

---

## 🔧 设备管理

Windows 管理器可以同时识别多台设备，并区分 `device`、`unauthorized`、`offline` 等 ADB 状态。选择一台可用设备后，可查看其型号、品牌、系统构建号、ABI、局域网 IP，以及网页桌面是否已安装及其版本。

**卸载网页桌面**会删除程序目录中的密码、日志和历史版本，需要确认；不删除其他 Android 应用。**卸载普通应用**针对当前主用户（user 0）操作，可能丢失应用数据；系统组件默认不会被直接卸载，只有经过明确包名确认的停用与恢复操作，并阻止一组已知关键系统包。

---

## 🛠️ 技术与项目结构

| 层级 | 技术 | 用途 |
|:---|:---|:---|
| Windows 桌面 | Vue 3、WebView2、Python、PyInstaller | 可折叠侧边栏、Windows 图形界面、ADB 操作与 EXE 构建 |
| Android 服务 | Go | 局域网 HTTP 服务、鉴权、版本更新 |
| 屏幕与输入 | Android `screencap`、`input`、`pm` | 获取画面、执行触控、列出应用 |
| Web 前端 | 原生 HTML、CSS、JavaScript | 响应式控制页面 |
| 发布 | GitHub Actions / Releases | Windows EXE 与 Android ARM64 ZIP |

```text
android-web-desktop/
├── manager/                  # Windows 管理器 Python 后端、Vue 3 前端
├── web/                      # Android 本机网页控制台
├── installer/                # Android 首次部署脚本
├── tests/                    # Windows 管理器与接口测试
├── main.go                   # Android 后端入口
├── update.go                 # Android 在线更新与回滚
└── .github/workflows/        # 自动化测试、构建和发布
```

### 源码构建

Android 服务需要 Go 1.23 或更新版本：

```bash
go test ./...
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -o desktopd .
```

Windows 管理器需 Node.js 22、Python 3.12、WebView2 Runtime。先在仓库目录构建 Vue 3 前端，再打包 Windows EXE：

```powershell
npm ci --prefix manager/frontend
npm run build --prefix manager/frontend
python -m unittest discover -s tests -p "test_manager_*.py"
python -m pip install pywebview==6.2.1 pyinstaller==6.22.3
python -m PyInstaller --onefile --windowed --name AndroidWebDesktopManager --collect-all webview --add-data "manager/frontend/dist;manager/frontend/dist" manager/app.py
```

---

## 🔒 数据与更新

设备上的默认目录是 `/data/local/tmp/android-web-desktop`，包含管理口令、运行日志、程序版本和当前版本符号链接。网页内安装更新时保留这些配置；通过管理器彻底卸载时删除该目录。Windows 管理器从 GitHub 发布页下载软件并校验 Release 提供的 SHA256 摘要；部署完成后通过 ADB 临时端口转发访问仅绑定设备回环地址的健康接口，确认正确版本已启动且局域网服务已监听；本地离线 ZIP 需要用户自己确认可信来源。

Windows 管理器依赖的 ADB 工具可从 Google 官方 Platform Tools 下载，首次下载时需要用户确认；本项目不把第三方工具重新打包为自己的程序。当前尚未添加独立的数字签名，下载后的 EXE 可能触发 Windows SmartScreen 提示。

---

## 🤝 反馈与维护

欢迎在 [Issues](https://github.com/nljie1103/u30air-web-console/issues) 反馈设备兼容问题及功能建议。

项目功能设计参考 [Universal Android Debloater NG](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation)、[Aya](https://github.com/liriliri/aya) 和 [scrcpy](https://github.com/Genymobile/scrcpy) 的使用体验；本项目的设备管理和网页控制代码独立实现，未直接复制这些项目的代码。

---

<div align="center">

**Made with ❤️ by [nljie1103](https://github.com/nljie1103)**

</div>
