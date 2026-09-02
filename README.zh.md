# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **实验版本 (v0.0.4b2)**

这是一个面向 **PySide6 / QtWebEngine** 应用程序的 WebUSB 兼容实现。

通过 JavaScript Polyfill、QWebChannel Bridge 以及基于 **pyusb/libusb** 的实际 USB 通信提供 `navigator.usb`。

## 主要功能

- 兼容 WebUSB 的 `navigator.usb`
- 实际 USB 设备通信
- 原生设备选择对话框
- 按 Origin 管理权限
- 支持 Frame-aware Origin 处理
- WebUSB 安全保护
- Chromium 安全密钥黑名单
- 传输大小验证与安全限制
- DevTools / F12 调试支持
- 可选的原生加速
- WebUSB API 兼容性

## Quick Start

~~~python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://example.com")
~~~

## 架构

~~~text
Web 页面
    │
    │ navigator.usb
    ▼
JavaScript WebUSB Polyfill
    │
    │ QWebChannel
    ▼
WebUSBBridge
    │
    ├── Origin / 安全检查
    ├── 权限管理
    ├── 原生设备选择
    └── 传输验证
    │
    ▼
pyusb / libusb
    │
    ▼
USB 设备
~~~

## 安全性

- 基于 Origin 的设备权限管理
- 原生设备选择
- Frame-aware Origin 识别
- 受保护 USB 接口检查
- Chromium 安全密钥黑名单
- 传输大小验证
- 主机侧安全限制

`getDevices()` 只会返回已经明确授权给当前请求 Origin 的设备。

## Chrome 兼容性

Chrome / Chromium 的行为被用作兼容性参考，但本项目**并不是 Chrome 的逐字节克隆**。

> **WebUSB 兼容 ≠ Chrome 克隆**

Chrome 的 32 MiB 传输限制在本实现中作为警告处理，而不是无条件拒绝。此外还会应用独立的主机侧安全限制。

## 调试

可以使用以下调试命名空间：

~~~javascript
window.__pysideWebUSB
~~~

可以查看以下信息：

- 当前 Origin 已授权的设备
- Bridge 版本
- 原生加速状态
- 传输大小限制
- 传输限制说明

因此可以通过 DevTools / F12 从页面侧检查 WebUSB 实现。

## 安装

~~~bash
pip install pyside6-webusb
~~~

也可以从源代码目录直接安装：

~~~bash
pip install -e .
~~~

## 当前状态

**早期 Beta 版本 — v0.0.4b2**

当前实现已经可以运行并完成测试，但部分功能仍处于实验阶段。

特别需要注意：

- Isochronous transfer 尚未通过实体 USB 硬件完成完整验证。
- 非均匀 Isochronous packet length 目前仍存在限制。
- 原生加速功能为可选项。

详细信息请参阅 [`CHANGELOG.md`](CHANGELOG.md)。

## 相关项目

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

MIT License.