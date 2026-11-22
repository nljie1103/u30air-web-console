<div align="center">

# 🖥️ Android Web Desktop

**用浏览器查看和操作 Android 桌面。**

面向支持 ADB 的 Android 设备，提供一个可部署在设备本机的轻量网页控制台，适用于局域网设备维护与远程操作。

[![Latest Release](https://img.shields.io/github/v/release/nljie1103/u30air-web-console?style=for-the-badge)](https://github.com/nljie1103/u30air-web-console/releases/latest)
[![Build](https://img.shields.io/github/actions/workflow/status/nljie1103/u30air-web-console/release.yml?branch=main&style=for-the-badge)](https://github.com/nljie1103/u30air-web-console/actions)
[![Platform](https://img.shields.io/badge/Android-ARM64-68768a?style=for-the-badge)](#system-requirements)

</div>

---

## ✨ 功能

| 功能 | 说明 |
|:---|:---|
| **网页屏幕预览** | 设备本地截图，通过浏览器定时刷新画面 |
| **触控与系统按键** | 点击、滑动、主页、返回、最近任务、唤醒 |
| **应用启动** | 搜索设备安装的第三方应用，并尝试打开其启动界面 |
| **设备信息** | 显示设备型号、Android 版本和处理器架构 |
| **手动在线更新** | 在网页内查看新版本与更新说明，确认后安装，支持失败回滚 |

桌面画面来自 Android 系统自带的 `screencap`；当前是定时截图模式，**不是实时视频流**。如设备另行启用了带网页客户端的 VNC 服务，可通过控制台的快捷入口访问。

---

<a id="system-requirements"></a>

## 💻 系统要求与安全

| 项目 | 要求 |
|:---|:---|
| 目标设备 | 支持执行 ADB Shell 的 Android ARM64 设备（`arm64-v8a`） |
| 首次安装 | 已安装 Android Platform Tools 的 Windows、macOS 或 Linux 电脑 |
| 浏览器 | 支持 JavaScript 的现代桌面或移动浏览器 |
| 网络 | 浏览器与设备可通过可信局域网访问；网页更新需设备能连接 GitHub |

> **安全提示：** 控制台使用 HTTP，虽有登录口令，但通信内容未加密。请仅在可信局域网使用，不要将服务端口、ADB 或 VNC 端口直接映射到公网。屏幕捕获与输入权限受到 Android 版本和设备固件限制；部分设备可能无法显示屏幕或模拟触控。

---

## 📥 下载与安装

从 **[最新 Release](https://github.com/nljie1103/u30air-web-console/releases/latest)** 下载 `android-web-desktop-arm64.zip` 并解压。

### Windows

1. 安装 [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools)。
2. 在 Android 设备上开启调试权限并完成授权，使设备可通过 USB 或已开启的无线 ADB 与电脑连接。
3. 双击解压目录中的 **`installer/install_windows.bat`**。
4. 安装器检测设备；如果有多台设备，会要求选择。如果没有发现设备，会显示连接状态并提示下一步操作。
5. 安装完成后，终端显示局域网访问网址和首次登录口令；使用浏览器访问即可。

无线 ADB 已启用的设备，也可给安装脚本传入 IP：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\installer\install_windows.ps1 -ConnectAddress 192.168.1.20:5555
```

安装器**不会替设备开启 ADB 调试**；设备的 USB 或无线调试必须事先可用并完成授权。

### Linux / macOS

前置条件同上。解压后进入安装包目录，运行：

```bash
bash installer/install_linux_mac.sh
```

如有多台设备，或需要直接指定访问 IP：

```bash
bash installer/install_linux_mac.sh <ADB序列号> <设备局域网IPv4地址> 8765
```

---

## 🚀 使用说明

网页采用自适应布局，主区域展示 Android 画面；在画面上点击、拖动，或使用下方系统按钮执行操作。右侧可搜索已安装应用、查看设备信息和进行更新。

应用列表来自系统返回的用户安装包名；它不等于每个软件都提供可直接启动的 Activity。设备若限制了截图或触控注入，控制台会显示相应错误。

默认端口是 **8765**，实际访问 IP 由安装器识别或用户指定。后续使用网页中的 **检查更新** 与 **安装更新** 即可升级，无需重新安装整个程序。更新会保留本机管理密码，新版本健康检查失败时会尝试回滚。

---

## 🏗️ 技术与数据

| 层级 | 实现 | 用途 |
|:---|:---|:---|
| 后端 | Go（单文件 ARM64 程序） | 局域网 HTTP 服务、口令验证、更新与回滚 |
| 桌面控制 | Android `screencap`、`input`、`pm` | 屏幕获取、触控与应用列表 |
| 前端 | 原生 HTML / CSS / JavaScript | 响应式界面、图片显示、鼠标与触控 |
| 发布 | GitHub Actions / Releases | 测试、构建与安装包分发 |

程序默认存储在 `/data/local/tmp/android-web-desktop`。其中 `password.txt` 保存管理口令，`current` 指向当前程序版本，`releases/` 保存已安装的程序文件，`server.log` 和 `update.log` 用于诊断。

**升级不删除上述配置。** 设备重启后是否自动启动取决于另外的服务启动配置；本安装器不擅自修改系统开机脚本。

### 源码构建

需要 Go 1.23 或更高版本：

```bash
go test ./...
go vet ./...
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -o desktopd .
```

---

## 🔧 故障排查

| 现象 | 排查方式 |
|:---|:---|
| 安装器未发现设备 | 执行 `adb devices -l` 查看 USB/无线 ADB 状态及授权 |
| 出现 `unauthorized` | 在目标设备上确认 USB 调试授权，之后重新检查 |
| 出现 `offline` | 检查连接并重新建立 ADB 会话 |
| 网页无法打开 | 核实设备局域网地址、安装器输出的 URL 与设备服务日志 |
| 屏幕无法显示 | 检查系统是否允许 `screencap -p` 输出有效画面 |
| 无法点击 | 检查 Android 系统对 `input` 命令及当前显示的限制 |

反馈和改进建议可通过 [GitHub Issues](https://github.com/nljie1103/u30air-web-console/issues) 提交。

---

<div align="center">

**Made with ❤️ by [nljie1103](https://github.com/nljie1103)**

</div>
