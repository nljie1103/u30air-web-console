# Windows 客户端第三方软件声明

## Qt for Python / PySide6 6.11.3

Copyright © The Qt Company Ltd. and contributors.

本项目 Windows 版本使用 Qt 6 的 QtCore、QtGui、QtWidgets、QtWebChannel 和 **QtWebEngineWidgets / QtWebEngineCore** 等模块及 PySide6 Python 绑定。QtWebEngine 内含基于 Chromium 的渲染组件，用于加载本地 Vue 3 界面，不依赖单独安装 Microsoft Edge。Qt for Python 社区版按 LGPLv3/GPLv3 或商业许可提供；请按照具体依赖组件对应的许可证履行义务。

- 官方项目：https://doc.qt.io/qtforpython-6/
- LGPLv3 正文：https://www.gnu.org/licenses/lgpl-3.0.html
- Qt 组件源码及许可证：https://code.qt.io/cgit/qt/

Windows 便携版提供可替换的动态 Qt 运行库，独立 EXE 使用 PyInstaller 的运行时解包方式。对 QtWebEngine/Chromium 第三方组件请同时参考 Qt 官方源代码、许可证及随包提供的 QtWebEngine 资源声明。Windows 页面源码位于 installer/frontend/，Python Qt 桥接位于 installer/qt_window.py。

- Qt WebEngine 模块许可：https://doc.qt.io/qt-6/qtwebengine-licensing.html
- QtWebEngine 源码：https://code.qt.io/cgit/qt/qtwebengine.git/
- Chromium 第三方许可证：https://chromium.googlesource.com/chromium/src/+/main/LICENSE

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
