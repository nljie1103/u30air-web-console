<div align="center">

# 🖥️ Android Web Desktop

**使用 Windows 图形管理器部署 Android 网页桌面，在可信局域网通过浏览器操作 Android 设备。**

[![Release](https://img.shields.io/github/v/release/nljie1103/u30air-web-console?style=for-the-badge)](https://github.com/nljie1103/u30air-web-console/releases/latest)
[![CI](https://img.shields.io/github/actions/workflow/status/nljie1103/u30air-web-console/release.yml?branch=main&style=for-the-badge)](https://github.com/nljie1103/u30air-web-console/actions)
[![Platform](https://img.shields.io/badge/Android-ARM64-687787?style=for-the-badge)](#环境要求)

[**下载 Windows 便携版（推荐）**](https://github.com/nljie1103/u30air-web-console/releases/latest/download/AndroidWebDesktopManager-Portable.zip) · [**下载独立 EXE**](https://github.com/nljie1103/u30air-web-console/releases/latest/download/AndroidWebDesktopManager.exe) · [**Android 安装包**](https://github.com/nljie1103/u30air-web-console/releases/latest/download/android-web-desktop-arm64.zip)

</div>

---

## ✨ 功能

| 功能 | 内容 |
|:---|:---|
| Windows 图形管理 | Vue 3 + Microsoft Edge 应用窗口、可折叠侧边栏、设备选择器、设备信息、日志和设置 |
| ADB 连接 | 自动发现 USB / 无线 ADB，识别热点网关并排除蜂窝/隧道动态 IP；区分未授权、离线与在线状态 |
| 部署维护 | 从 GitHub 校验下载或选择本地安装包；安装、更新、卸载、异常回滚 |
| 应用管理 | 按需查询应用、搜索、卸载普通应用，停用与恢复非关键系统组件 |
| 设备控制 | 重启、关机、打开设备端网页控制台 |
| 网页桌面 | 截图预览、点击和滑动、系统按键、用户应用名称和图标、直接启动应用、手动在线更新 |

网页桌面目前使用定时截图，不是高帧率视频流。用户应用名称和图标从设备本地 APK 资源读取，无法解析时会回退为包名及首字母图标。可以直接启动具有公开桌面入口的应用；没有启动入口的后台组件不会强行运行。

---

## 📥 下载和安装

### Windows · 推荐便携版

1. 在 [Releases](https://github.com/nljie1103/u30air-web-console/releases/latest) 下载 `AndroidWebDesktopManager-Portable.zip`。
2. **完整解压**后双击其中的 `AndroidWebDesktopManager.exe`。不要仅从压缩包预览中直接运行 EXE。
3. 使用已授权 USB ADB 连接设备；也可从程序中输入已开启无线 ADB 的设备 IP 和端口。
4. 在可搜索的设备下拉菜单中选择在线设备，确认型号、系统版本和已安装的网页桌面版本。
5. 点击 **一键安装 / 升级**，成功后可打开网页控制台。

便携版采用已解包的程序目录，避免单文件 EXE 在**每次冷启动**时重新释放依赖文件。新版已移除原先的 pythonnet/WinForms 依赖，不再需要 .NET 程序配置文件。需要把全部程序放在一个文件中时，也可下载独立 EXE；独立 EXE 首次启动速度可能因电脑性能和安全软件检查而有所不同。

**网关地址说明：** Windows 管理器会区分热点/局域网地址与蜂窝数据 10.x 私网地址。对于使用 192.168.0.1 作为管理网关的 U30 Air，可在“部署与更新”页面选择或手动填入 192.168.0.1，部署后的网页访问地址为 http://192.168.0.1:8765/ 。这个地址与官方后台（通常为 80 端口）、UFI 插件（例如 2333 端口）通常可共存，前提是设备实际拥有该网卡地址且端口没有冲突。已经绑定在旧 10.x 地址的服务，必须重新部署才能切换监听地址；单纯刷新浏览器不会迁移服务。对于其他 Android 设备，不强行使用 192.168.0.1。

管理器可以使用已有的 `adb.exe`，也提供从 Google 官方下载 Platform Tools 的入口。若设备显示 `unauthorized` 或 `offline`，需在 Android 侧完成调试授权或恢复连接，不能靠程序绕过。

### Linux / macOS · ADB 脚本

从 Release 下载 `android-web-desktop-arm64.zip`，解压并在安装包目录执行：

```bash
bash installer/install_linux_mac.sh
```

多台设备连接时可以传入 ADB 序列号及设备私有 IPv4：

```bash
bash installer/install_linux_mac.sh <ADB序列号> <设备局域网IPv4> 8765
```

命令行脚本会阻止同版本直接覆盖，**同版本安全重装请使用 Windows 图形管理器**。

---

<a id="环境要求"></a>

## 💻 环境要求

| 组件 | 要求 |
|:---|:---|
| Windows 管理器 | Windows 10 / 11 x64、完整 Microsoft Edge 浏览器 |
| 目标设备 | Android ARM64（`arm64-v8a`）、可用的 ADB Shell |
| 设备连接 | USB 调试已授权，或已正确配置的局域网无线 ADB |
| 网页访问 | 浏览器能连接设备私有 IPv4 地址与管理端口（默认 8765） |
| 在线更新 | 管理电脑或设备可以访问 GitHub Release |

**安全提醒：** 网页控制台默认使用 HTTP，仅供可信局域网使用。不要把网页管理端口、ADB 端口或 VNC 端口直接映射到公网。系统应用的停用与卸载可能影响设备功能，应谨慎操作。

---

## 🏗️ 仓库结构

仓库根目录只保留 GitHub 工作流、Windows 管理器源码、Android 网页端源码及必要的项目文件。每部分的测试、依赖和构建配置放在所属组件内部。

```text
android-web-desktop/
├── .github/
│   └── workflows/                # 自动化构建、Windows/Android 测试及 Release
├── installer/                    # Windows EXE 管理器源码
│   ├── app.py                    # Microsoft Edge 原生应用窗口启动器
│   ├── bridge.py                 # ADB 业务接口与独立文件选择器
│   ├── adb_client.py             # 设备识别及 Android 操作
│   ├── deployment.py             # 下载、部署、卸载与回滚
│   ├── local_server.py           # 静态前端资源服务器
│   ├── edge_host.py               # 127.0.0.1 管理 API 白名单与会话保护
│   ├── frontend/                 # Vue 3、CSS、TypeScript、界面测试
│   └── tests/                    # 管理器、部署和脚本回归测试
├── web-console/                  # Android 设备端源码
│   ├── main.go                   # 网页控制台服务
│   ├── update.go                 # Android 在线更新与回滚
│   ├── launch.go                 # Activity Manager 应用启动
│   ├── app_metadata.go           # 已安装 APK 名称和图标解析
│   ├── launch.go                 # Activity Manager 应用启动
│   ├── app_metadata.go           # 已安装 APK 名称和图标解析
│   ├── web/                      # Android 页面资源
│   ├── deploy/                   # 跨平台首次安装脚本
│   ├── version.json              # 唯一的正式版本及更新说明
│   ├── THIRD_PARTY_NOTICES.md    # 第三方依赖许可声明
│   ├── THIRD_PARTY_NOTICES.md    # 第三方依赖许可声明
│   └── go.mod
├── .gitignore
└── README.md
```

两个组件共用一个 Release 版本号。发布的 Android ZIP 内仍使用 `installer/` 作为**安装包内部的脚本目录名**，这是为了兼容已经发布的安装流程；它与仓库根目录的 Windows 管理器 `installer/` 不同。

### 源码构建

Windows 管理器：Node.js 22、Python 3.12、PyInstaller、Microsoft Edge。先构建 Vue 再打包：

```powershell
npm ci --prefix installer/frontend
npm run build --prefix installer/frontend
python -m pip install pyinstaller==6.22.3
python -m unittest discover -s installer/tests -p "test_manager_*.py"
python -m PyInstaller --onedir --windowed --name AndroidWebDesktopManager --add-data "installer/frontend/dist;installer/frontend/dist" installer/app.py
```

Android 网页端：Go 1.23 或更新版本：

```bash
cd web-console
go test ./...
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -o desktopd .
```

---

## 🔧 故障排查与反馈

Windows 界面设备下拉菜单会列出检测到的在线、未授权和离线设备；首次连接检查 `adb devices -l` 的结果。应用列表只在进入“应用管理”时加载，以减少启动时的额外 ADB 调用。 Windows 管理器使用 Edge 原生应用窗口和本机受限 Python 接口；窗口移动不再进入 Python WinForms 消息循环。操作详情可以在运行日志中查看。

应用为设备端部署提供健康检查：安装后通过临时 ADB 转发确认正确版本确实启动并监听；异常时尝试恢复此前版本。设备上的服务默认保存到 `/data/local/tmp/android-web-desktop`，图形管理器的一键卸载会清理该项目目录。

使用反馈、兼容性问题与改进建议可通过 [GitHub Issues](https://github.com/nljie1103/u30air-web-console/issues) 提交。

---

<div align="center">

**Made with ❤️ by [nljie1103](https://github.com/nljie1103)**

</div>
