# Windows 客户端第三方软件声明

## Wails v2.17.1 与 Microsoft WebView2

Windows 宿主使用 Wails（MIT）和系统 Microsoft WebView2 Runtime；不分发 Qt、Chromium 或 WebView2 固定运行库。Wails 运行依赖与对应许可证见 installer/host/go.mod、go.sum 与各上游项目。

- Wails：https://github.com/wailsapp/wails
- Wails 许可：https://github.com/wailsapp/wails/blob/master/LICENSE
- Microsoft WebView2：https://developer.microsoft.com/microsoft-edge/webview2/

Vue 3、Lucide 图标及 TypeScript 等组件见 installer/frontend/package.json 与对应许可证。

## Google Android SDK Platform-Tools

ADB 不直接包含于 Windows EXE 中。用户选择安装时，程序从 Google 官方 HTTPS 地址独立下载最新 Windows Platform-Tools 到当前用户目录，并保留官方工具的原始文件。使用该工具需遵守 Google Android SDK 条款。

- 官方说明：https://developer.android.com/tools/releases/platform-tools
- 官方下载：https://dl.google.com/android/repository/platform-tools-latest-windows.zip

## Python、PyInstaller、Pillow

Python、PyInstaller 与用于生成 ICO 图标的 Pillow 依其各自开源许可证提供。

## Vue 3 与 Lucide 图标

Windows 视觉界面采用 Vue 3 和 lucide-vue-next；依各自许可证提供。生产构建输出为本地静态资源，不通过 CDN 运行。

- Vue 3：https://github.com/vuejs/core （MIT）
- Lucide：https://lucide.dev/license （ISC）
