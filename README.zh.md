# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Beta — v0.0.5b2**

面向 **PySide6 / QtWebEngine** 应用程序的 WebUSB API 实现。

它结合 JavaScript WebUSB Polyfill、QWebChannel Bridge 以及通过 **pyusb / libusb** 进行的真实 USB 通信，为 QtWebEngine 提供通常无法直接使用的 `navigator.usb`。

> GitHub 上的开发/发布标识为 `v0.0.5b2`。按照 PyPI / PEP 440，实际打包版本字符串为 `0.0.5.post6`。

## 特性

- WebUSB 兼容的 `navigator.usb`
- 与真实 USB 设备通信
- 原生设备选择对话框
- 按 Origin 管理设备权限
- Frame-aware Origin 处理
- WebUSB 安全保护
- Chromium 已知安全密钥黑名单
- Transfer 验证与安全限制
- WebUSB `filters` / `exclusionFilters` 匹配
- Hotplug 监控以及 `connect` / `disconnect` 事件
- `window.__pysideWebUSB` DevTools / F12 调试工具
- 可选 Rust 原生加速
- 主机环境诊断工具
- `pyside6-webusb-doctor`
- JSON 格式环境诊断
- 主机应用程序预授权设备
- TypeScript 类型定义
- WebUSB 兼容的 DOMException / Transfer 模型
- Virtual USB backend / Virtual USB device 测试支持

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://example.com")
```

## 安装

```bash
pip install pyside6-webusb
```

开发安装：

```bash
pip install -e .
```

主要依赖：

- Python >= 3.9
- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- 操作系统级 libusb

## 架构

```text
Web 页面
    │ navigator.usb
    ▼
JavaScript WebUSB Polyfill
    │ QWebChannel
    ▼
WebUSBBridge
    │
    ├── Origin / Frame security
    ├── Permission management
    ├── Native device chooser
    ├── Filter / exclusionFilter matching
    ├── Transfer validation
    ├── Protected-class / blocklist checks
    └── Device / handle management
    │
    ▼
pyusb / libusb
    │
    ▼
USB 设备
```

这不是 Chromium 内部 WebUSB 实现的直接移植。页面获得 WebUSB 兼容 JavaScript API，而 Python 侧负责权限、安全检查、设备选择和原生 USB 访问。

## API

主要 API：

```javascript
navigator.usb
```

主要对象：

```text
USB
USBDevice
USBConfiguration
USBInterface
USBAlternateInterface
USBEndpoint
USBConnectionEvent
USBInTransferResult
USBOutTransferResult
USBIsochronousInTransferResult
USBIsochronousOutTransferResult
USBIsochronousInTransferPacket
```

示例：

```javascript
const devices = await navigator.usb.getDevices();
console.log(devices);
```

```javascript
const device = await navigator.usb.requestDevice({
    filters: [{ vendorId: 0x1234 }]
});
await device.open();
```

## 安全模型

主要保护机制包括：

- 基于 Origin 的设备权限
- 原生设备选择
- Frame-aware Origin 归属
- 受保护 USB Interface Class 拒绝
- Chromium 派生的已知安全密钥黑名单
- Transfer 大小验证
- Host 侧安全限制
- Endpoint / Interface 验证
- Native 侧验证
- `getDevices()` 仅返回已授权设备
- `requestDevice()` 用户操作检查
- chooser 重入保护
- 防止绕过 Host-only 管理 API
- 设备来源字符串清理
- 按 Origin 检查 Hotplug 可见性
- 每个 Origin 的并发 open handle 限制

## WebUSB Filter

支持 `requestDevice()` 的 `filters` / `exclusionFilters`。

```javascript
const device = await navigator.usb.requestDevice({
    filters: [{ vendorId: 0x1234, productId: 0x5678 }]
});
```

## Transfer

主要支持：

- Control Transfer
- Bulk Transfer
- Interrupt Transfer
- Isochronous Transfer
- Interface Claim / Release
- Alternate Interface
- Endpoint Halt / Clear Halt
- Device Reset
- Open / Close

Isochronous Transfer 已实现，但仍存在 backend 和真实硬件相关限制。

## 大容量 Transfer

32 MiB 是 Chrome / Chromium 中的重要 Transfer 大小参考。

`pyside6-webusb` 不会立即拒绝超过 32 MiB 的 Transfer：

- 超过 32 MiB 时生成 `console.warn()`
- 可通过 DevTools / F12 检查
- Host 侧设置 512 MiB 安全上限

> **WebUSB-compatible ≠ Chrome clone**

## DevTools / F12

```javascript
window.__pysideWebUSB
```

可用于检查 Bridge 信息、已授权设备状态以及 Transfer 限制诊断。

## 主机应用程序预授权

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

## 环境诊断

```python
from pyside6_webusb import environment_report, format_environment_report
print(format_environment_report())
```

```bash
pyside6-webusb-doctor
python -m pyside6_webusb
pyside6-webusb-doctor --json
python -m pyside6_webusb --json
```

## Native Acceleration

提供可选的 Rust 加速层：

- Base64 编码 / 解码
- 二进制处理
- ADB wire-protocol message framing helper
- Transfer response JSON 构建

不可用时回退到 Python。Rust crate 使用 PyO3 `abi3-py39`。

## TypeScript

WebUSB API 的 TypeScript 类型定义位于：

```text
types/webusb-polyfill.d.ts
```

## Virtual USB

提供用于测试的 Virtual USB backend / Virtual USB device。

```python
from pyside6_webusb.virtual import VirtualUsbDevice
```

无需物理 USB 硬件即可测试 USB descriptor 和 Transfer 行为。

## 测试

项目包含 Python tests、security audit、Node/polyfill tests、TypeScript checks 和 Rust tests。

```text
184 passed, 2 skipped
```

自动化测试不能完全替代真实 USB 硬件测试，尤其是 Isochronous Transfer。

## Isochronous Transfer

Isochronous Transfer 目前以 best-effort 方式实现。

pyusb 公开 API 无法提供完整的 per-packet length / result 信息，尤其是 IN Transfer 的 per-packet fidelity 存在已知限制。

## 当前状态

**v0.0.5b2 — Experimental Beta**

### 已实现

- [x] `navigator.usb`
- [x] JavaScript WebUSB Polyfill
- [x] QWebChannel Bridge
- [x] pyusb / libusb backend
- [x] Native device chooser
- [x] Origin permissions
- [x] Frame-aware origin handling
- [x] WebUSB filter matching
- [x] `exclusionFilters`
- [x] USB transfers
- [x] Hotplug monitoring
- [x] Security hardening
- [x] Chromium security-key blocklist
- [x] DevTools debug namespace
- [x] Optional Rust acceleration
- [x] Host application pre-authorization
- [x] Environment diagnostics
- [x] JSON diagnostics
- [x] `pyside6-webusb-doctor`
- [x] TypeScript definitions
- [x] Virtual USB testing support
- [x] Direct QWebChannel bypass hardening
- [x] Canonical Base64 validation
- [x] Malformed Base64 → `DataError`
- [x] PySide6 / QtWebEngine import diagnostics
- [x] Serial-number device disambiguation
- [x] Protected alternate-setting checks
- [x] `window.USB` / `window.USBDevice` / `window.USBConnectionEvent` exposure

### 仍处于实验阶段

- [ ] 大范围真实 USB 硬件验证
- [ ] 真实硬件上的 Isochronous Transfer 验证
- [ ] 非均一 Isochronous packet length 的扩展支持
- [ ] 更广泛的 OS / USB-driver 兼容性
- [ ] 长期 API 稳定化
- [ ] 与现有 WebUSB 网站的兼容性测试

## 与 Mock-webusb 的关系

`pyside6-webusb` 是 **Mock-webusb** 下的 PySide6 / QtWebEngine 实现。

```text
Mock-webusb
   │
   ├── pyside6-webusb
   │      └── PySide6 / QtWebEngine
   │
   └── fox-webusb
          └── Firefox / Native Messaging
```

目标不是完全复制 Chrome 内部 WebUSB 实现，而是在不同 Host 环境中提供 WebUSB-compatible API。

## 注意事项

> ⚠️ `pyside6-webusb` 是实验性软件。

这是一个 v0.x 项目，API、兼容性和真实硬件支持可能发生变化。

本项目可能包含 AI 生成的代码或在 AI 协助下开发的代码。

因此可能存在 bug、不完整行为、环境相关问题、兼容性差异以及尚未发现的安全问题。

如果用于生产环境，请针对目标操作系统、USB 设备、驱动、libusb backend 以及 WebUSB 应用进行完整验证。

## License

MIT License
