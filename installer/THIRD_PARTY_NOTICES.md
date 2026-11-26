# Windows 客户端第三方软件声明

## Qt for Python / PySide6 6.11.3

Copyright © The Qt Company Ltd. and contributors.

本项目使用 Qt 6 的 QtCore、QtGui、QtWidgets 等原生 UI 组件与 PySide6 Python 绑定。Qt for Python 社区版按 LGPLv3/GPLv3 或商业许可提供；请按照具体依赖组件对应的许可证履行义务。

- 官方项目：https://doc.qt.io/qtforpython-6/
- LGPLv3 正文：https://www.gnu.org/licenses/lgpl-3.0.html
- Qt 组件源码及许可证：https://code.qt.io/cgit/qt/

Windows 便携版提供可替换的动态 Qt 运行库，独立 EXE 使用 PyInstaller 的运行时解包方式。Windows 客户端源码位于本仓库 installer/。

## Google Android SDK Platform-Tools

ADB 不直接包含于 Windows EXE 中。用户选择安装时，程序从 Google 官方 HTTPS 地址独立下载最新 Windows Platform-Tools 到当前用户目录，并保留官方工具的原始文件。使用该工具需遵守 Google Android SDK 条款。

- 官方说明：https://developer.android.com/tools/releases/platform-tools
- 官方下载：https://dl.google.com/android/repository/platform-tools-latest-windows.zip

## Python、PyInstaller、Pillow

Python、PyInstaller 与用于生成 ICO 图标的 Pillow 依其各自开源许可证提供。
