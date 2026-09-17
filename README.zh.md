# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Alpha — v0.0.5a0**

一个面向 **PySide6 / QtWebEngine** 应用程序的 WebUSB API 实现。

通过 JavaScript Polyfill、QWebChannel Bridge，以及基于 **pyusb / libusb** 的真实 USB 通信，为 QtWebEngine 提供 `navigator.usb`。

## 特性

- 兼容 WebUSB 的 `navigator.usb`
- 真实 USB 设备通信
- 原生设备选择对话框
- 按 Origin 管理设备权限
- 支持 Frame-aware Origin 处理
- WebUSB 安全保护
- Chromium 安全密钥黑名单
- Transfer 验证与安全限制
- WebUSB Filter 匹配
- USB Hotplug 监视以及连接事件
- DevTools / F12 调试支持
- 可选 Rust 原生加速
- 主机环境诊断工具
- 主机应用预授权 USB 设备
- WebUSB API 兼容性

## 为什么需要它？

QtWebEngine 使用 Chromium 技术，但嵌入式 QtWebEngine 应用并不会自动拥有完整 Chrome / Chromium 浏览器环境中的 WebUSB 能力。

设备配置工具、固件工具、硬件仪表盘等 Web 应用可能依赖 `navigator.usb`。

`pyside6-webusb` 用于为 PySide6 应用补充这一能力。

## 快速开始

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()

install(view.page())

view.load("https://example.com")
```

对于大多数应用，只需要在页面上调用一次 `install()`，即可连接 WebUSB Polyfill 与 Python Bridge。

## 安装

```bash
pip install pyside6-webusb
```

也可以直接从源代码目录安装：

```bash
pip install -e .
```

主要依赖：

- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- 操作系统层面的 libusb

在 Linux 上，可能还需要单独安装系统级 `libusb-1.0`。

## 架构

```text
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
    ├── Origin / Frame 安全检查
    ├── 权限管理
    ├── 原生设备选择
    ├── Filter 匹配
    ├── Transfer 验证
    └── Device / Handle 管理
    │
    ▼
pyusb / libusb
    │
    ▼
USB 设备
```

本项目并不是 Chromium 内部 WebUSB 实现的直接复制。

网页获得 WebUSB 兼容的 JavaScript API，而 Python 负责权限、安全检查、设备选择以及通过 pyusb/libusb 进行 USB 操作。

## API

核心 API：

```javascript
navigator.usb
```

提供 WebUSB 风格的对象模型，包括：

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

设备选择：

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

await device.open();
```

实际可用的设备和 Transfer 能力取决于操作系统、USB 驱动、libusb 以及具体设备。

## 安全模型

`pyside6-webusb` 并不是为了向任意网页公开主机上的所有 USB 设备。

主要保护机制包括：

- 基于 Origin 的设备权限
- 原生设备选择器
- Frame-aware Origin 归属
- 受保护 USB Interface Class 检查
- Chromium 来源的已知安全密钥黑名单
- Transfer 大小验证
- Host 侧安全限制
- Endpoint / Interface 验证
- Native 侧验证
- `getDevices()` 仅提供已经授权的设备

```text
requestDevice()
      │
      ▼
设备选择器
      │
      ▼
用户 / 主机授权
      │
      ▼
已授权设备
      │
      ▼
getDevices()
```

`getDevices()` 的设计目标是只向请求 Origin 提供已经获得授权的设备。

## WebUSB Filters

`requestDevice()` 支持 `filters` 和 `exclusionFilters`，可以根据 Vendor ID、Product ID、Serial Number、Interface Class / Subclass / Protocol 等字段匹配设备。

Filter 的结构也会按照 WebUSB 模型进行验证。

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        {
            vendorId: 0x1234,
            productId: 0x5678
        }
    ]
});
```

## USB Transfer

实现覆盖以下操作：

- Control Transfer
- Bulk Transfer
- Interrupt Transfer
- Isochronous Transfer
- Interface Claim / Release
- Alternate Interface
- Endpoint Halt / Clear Halt
- Device Reset
- Open / Close

WebUSB 的 `stall`、`babble` 等 Transfer 状态也会在可能的情况下转换为 WebUSB 结果模型。

Isochronous Transfer 仍然存在后端和实际硬件相关的限制。

## 大型 Transfer

Chrome / Chromium 使用 32 MiB 作为重要的 Transfer 大小参考值。

`pyside6-webusb` 将其作为**兼容性参考值**，但不会仅仅因为超过 32 MiB 就像 Chrome 一样直接拒绝 Transfer。

相反：

- 超过 32 MiB 时产生警告
- 警告会发送到 `console.warn()`
- 另外应用独立的 Host 侧安全上限

因此：

> **WebUSB-compatible ≠ Chrome clone**

这是一个有意的设计选择。实现与 Chrome 的差异会被明确记录，而不是隐藏起来；同时通过独立的 Host 安全上限避免无限制的资源消耗。

## DevTools / F12

网页中提供调试命名空间：

```javascript
window.__pysideWebUSB
```

可以用于查看：

- Bridge version
- Rust acceleration 状态
- Transfer 限制
- 当前 Origin 已可见的设备
- Transfer 限制说明

因此可以直接通过 DevTools / F12 检查 WebUSB 实现。

## 主机应用预授权

v0.0.5a0 新增了主机应用 API，可以预先允许指定 Origin 访问指定 USB 设备。

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

适用于 Kiosk、嵌入式应用等场景，其中允许的 Origin 和设备由主机应用配置决定。

该管理 API 不会作为 Qt Slot 直接暴露给网页内容。

## 环境诊断

v0.0.5a0 新增环境诊断功能：

```python
from pyside6_webusb import (
    environment_report,
    format_environment_report,
)

print(format_environment_report())
```

也可以通过命令行运行：

```bash
pyside6-webusb-doctor
```

或者：

```bash
python -m pyside6_webusb
```

诊断报告可以包含：

- Python 版本
- Python 实现
- PySide6 版本
- shiboken6 版本
- Qt Runtime 版本
- pyusb 版本
- 实际解析到的 libusb Backend
- Rust 加速状态
- 检测到的问题

Rust 加速没有安装并不意味着环境损坏，因为项目可以回退到标准 Python 实现。

## Native Acceleration

项目包含可选的 Rust 原生加速层。

可用于优化：

- Base64 编码 / 解码
- 二进制处理
- Pack / Unpack
- Validation Helper
- Checksum 相关处理

该加速层不是必需依赖。

## TypeScript

项目包含 WebUSB 风格 API 的 TypeScript 类型定义。

例如：

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

因此应用可以使用类型信息，而不是只能依赖无类型的注入脚本。

## 测试

项目包含多个实现层的测试：

```text
Python Tests
    ├── Bridge
    ├── Polyfill
    ├── Origin / Frame handling
    ├── Hardening
    ├── Diagnostics
    ├── Error handling
    └── Rust acceleration

Security Audit
    ├── Resource exhaustion
    ├── Altsetting class confusion
    ├── Cross-origin hotplug leakage
    ├── Direct channel bypass
    └── Malicious device / descriptor handling

JavaScript Tests
    └── WebUSB API behavior

TypeScript
    └── API type checks

Rust
    └── Native acceleration tests
```

自动化测试不能完全代替真实 USB 硬件测试。

目标环境中的操作系统行为、USB 驱动、libusb 兼容性、设备特有行为、Isochronous Transfer 以及权限边界都应进行实际验证。

## 当前状态

**v0.0.5a0 — Early Alpha / Beta-quality experimental release**

v0.0.5a0 在 v0.0.4b3 的 WebUSB 兼容实现基础上，增加了主机应用功能和环境诊断能力。

### 已实现

- [x] `navigator.usb`
- [x] JavaScript WebUSB Polyfill
- [x] QWebChannel Bridge
- [x] pyusb / libusb Backend
- [x] 原生设备选择器
- [x] Origin 权限
- [x] Frame-aware Origin 处理
- [x] WebUSB Filter 匹配
- [x] USB Transfer
- [x] Hotplug 监视
- [x] Security Hardening
- [x] Chromium Security-key Blocklist
- [x] DevTools 调试命名空间
- [x] 可选 Rust 加速
- [x] 主机应用设备预授权
- [x] 环境诊断
- [x] `pyside6-webusb-doctor`
- [x] TypeScript 定义
- [x] 自动化测试

### 仍处于实验阶段

- [ ] 更广泛的真实 USB 设备验证
- [ ] Isochronous Transfer 的真实硬件验证
- [ ] 扩展非均匀 Isochronous Packet Length 支持
- [ ] 更广泛的 OS / USB 驱动兼容性
- [ ] 长期 API 稳定化
- [ ] 与现有 WebUSB 应用的兼容性测试

## 与 Mock-webusb 的关系

`pyside6-webusb` 是 **Mock-webusb** 面向 PySide6 / QtWebEngine 的实现。

相关的 Firefox 实现为 `fox-webusb`。

```text
Mock-webusb
   │
   ├── pyside6-webusb
   │      └── PySide6 / QtWebEngine
   │
   └── fox-webusb
          └── Firefox / Native Messaging
```

这些项目的目标是在不同主机环境中提供 WebUSB 兼容 API，而不是逐字节复制 Chromium 的内部实现。

## ⚠️ 注意事项

> ⚠️ `pyside6-webusb` 是实验性软件。

本项目目前处于 v0.x 系列，API、兼容性和硬件支持可能继续变化。

项目中可能包含 AI 生成的代码，或在 AI 辅助下开发的代码。

因此可能存在 Bug、未完成行为、环境相关问题、兼容性差异以及尚未发现的安全问题。

如果用于生产环境，请对完整目标环境进行充分测试，包括操作系统、USB 驱动、USB 设备以及实际 WebUSB 应用。

## 相关项目

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

MIT License.
