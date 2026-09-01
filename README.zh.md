# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **实验版本 (v0.0.4b1)**

这是一个面向 PySide6 / QtWebEngine 应用程序的 WebUSB 兼容实现。

通过 JavaScript Polyfill、QWebChannel Bridge 以及基于 pyusb/libusb 的实际 USB 通信提供 `navigator.usb`。

## 主要功能

- 兼容 WebUSB 的 `navigator.usb`
- 实际 USB 设备通信
- 原生设备选择对话框
- 按 Origin 管理权限
- WebUSB 安全保护
- WebUSB API 兼容性

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
```

## 当前状态

目前为早期 Beta 版本。

Isochronous transfer 尚未通过实体 USB 硬件完成验证。

## License

MIT License.