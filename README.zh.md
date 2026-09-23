# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Beta — v0.0.5b1**

面向 **PySide6 / QtWebEngine** 应用程序的 WebUSB API 实现。

它结合 JavaScript WebUSB Polyfill、QWebChannel Bridge 以及 **pyusb / libusb** 实际 USB 通信，为 QtWebEngine 提供通常无法直接使用的 `navigator.usb`。

> GitHub 上的开发标识为 `v0.0.5b1`。按照 PyPI / PEP 440，实际打包版本字符串为 `0.0.5.post5`。

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
- WebUSB 兼容的 DOMException 和 Transfer 模型
- Virtual USB backend / Virtual USB device 测试支持

## 为什么需要它

PySide6 的 QtWebEngine 基于 Chromium，但嵌入式 QtWebEngine 并不会像完整 Chrome / Chromium 浏览器 shell 那样直接提供 WebUSB。

如果 PySide6 应用加载了需要 `navigator.usb` 的设备配置工具、固件工具或硬件控制面板，页面通常无法使用该 API。

`pyside6-webusb` 用于填补这一空缺。

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://your-site.example")
```

普通应用只需要在创建页面后调用一次 `install()`，即可连接 WebUSB Polyfill 和 Bridge。

## 安装

```bash
pip install pyside6-webusb
```

从源码树进行开发安装：

```bash
pip install -e .
```

主要依赖：

- Python >= 3.9
- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- 操作系统级 libusb

Linux 上可能还需要额外安装 `libusb-1.0`。

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
    ├── Origin / Frame 安全
    ├── 权限管理
    ├── 原生设备选择
    ├── Filter / exclusionFilter 匹配
    ├── Transfer 验证
    ├── Protected class / 黑名单检查
    └── Device / handle 管理
    │
    ▼
pyusb / libusb
    │
    ▼
USB 设备
```

这不是 Chromium 内部 WebUSB 实现的直接移植。

页面获得 WebUSB 兼容的 JavaScript API，而 Python 负责权限、安全、设备选择等策略，并通过 pyusb/libusb 访问 USB 设备。

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

选择设备：

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

`pyside6-webusb` 不会向任意网页公开系统中的全部 USB 设备。

主要保护措施：

- 基于 Origin 的设备权限
- 原生设备选择器
- Frame-aware Origin 归属
- 拒绝受保护 USB Interface Class
- Chromium 已知安全密钥黑名单
- Transfer 大小验证
- Host 侧安全上限
- Endpoint / Interface 验证
- Native 侧验证
- `getDevices()` 只返回已授权设备
- `requestDevice()` 的 user gesture 验证
- 防止 chooser 重入
- 防止网页通过直接 QWebChannel 调用访问 Host-only 管理 API
- 清理设备提供的字符串
- Hotplug 事件按 Origin 检查可见性
- 每个 Origin 的同时打开 handle 数量限制

以下 8 种受保护 Interface Class 会被拒绝：Audio、HID、Mass Storage、Hub、Smart Card、Video、Audio/Video、Wireless Controller。

保护不仅存在于 `claimInterface()`，Transfer、`clearHalt()` 和 `selectAlternateInterface()` 等路径也会进行相应检查。

## WebUSB Filter

`requestDevice()` 支持 `filters` 和 `exclusionFilters`，可以根据 Vendor ID、Product ID、Serial Number、Interface Class / Subclass / Protocol 等字段匹配设备。

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

Filter 结构也会在 Python 侧进行类型和数值范围验证。

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

`stall`、`babble` 等 Transfer 状态在适用情况下会转换为 WebUSB 结果模型。

Isochronous Transfer 已经实现，但由于 pyusb 公共 API 的限制，per-packet fidelity 目前仍属于 best-effort。

## 大容量 Transfer

32 MiB 是 Chrome / Chromium 中的重要 Transfer 大小参考值。

`pyside6-webusb` 不会像 Chrome 一样直接拒绝超过 32 MiB 的 Transfer，而是明确记录这一兼容性差异：

- 超过 32 MiB 时生成 `console.warn()`
- 可在 DevTools / F12 中看到
- Host 侧另设 512 MiB 安全上限

因此：

> **WebUSB-compatible ≠ Chrome clone**

与 Chrome 的有意差异会记录在 README 和 CHANGELOG 中，而不会被静默隐藏。

## DevTools / F12

页面中会注入：

```javascript
window.__pysideWebUSB
```

主要工具：

```javascript
window.__pysideWebUSB.listGrantedDevices()
window.__pysideWebUSB.bridgeInfo()
window.__pysideWebUSB.explainTransferLimits()
```

`bridgeInfo()` 可以显示 Bridge 版本、Rust acceleration 状态以及 Transfer 限制等信息。

## 主机应用程序预授权

可信任的主机应用程序可以提前为指定 Origin 授权指定 USB 设备：

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

适用于 kiosk、嵌入式应用等由主机配置决定允许哪些 Origin 和设备的场景。

该管理方法不会作为可由网页内容直接调用的 Qt Slot 暴露。

## 环境诊断

Python：

```python
from pyside6_webusb import (
    environment_report,
    format_environment_report,
)

print(format_environment_report())
```

命令行：

```bash
pyside6-webusb-doctor
```

或者：

```bash
python -m pyside6_webusb
```

JSON：

```bash
pyside6-webusb-doctor --json
```

```bash
python -m pyside6_webusb --json
```

诊断可以报告：

- Python version / implementation
- PySide6 version
- shiboken6 version
- Qt runtime version
- pyusb version
- 已解析的 libusb backend
- `pyusb_backend_note`
- `qtwebengine_importable`
- Frame-origin isolation 可用性
- Rust acceleration 状态
- 检测到的问题

`qtwebengine_importable` 会实际检查 `QtWebEngineCore` / `QtWebEngineWidgets` 是否可以导入。

Frame-origin isolation 会根据当前 PySide6 API 选择可用模式，并在诊断结果中显示实际状态。

## Native Acceleration

可以使用可选的 Rust 加速层。

主要处理：

- Base64 encode / decode
- 二进制处理
- ADB wire-protocol message framing helper
- Transfer response JSON construction

Rust acceleration 不是必需的。不可用时会fallback到Python实现。

Rust crate 使用 PyO3 `abi3-py39` 构建方式，便于为更新版本的 Python 构建 ABI-compatible wheel。

## TypeScript

`types/webusb-polyfill.d.ts` 包含WebUSB API的TypeScript定义。

例如：

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

`types/sample-usage.ts` 和 `types/negative-check.ts` 同时覆盖正常使用和预期的类型错误。

## 测试

本版本包含 Python tests、security audit、Node polyfill tests、TypeScript checks 以及 Rust tests。

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
    ├── Alternate-setting / protected-class bypass
    ├── Cross-origin hotplug leak
    ├── Direct channel bypass
    └── Malicious device / descriptor handling

JavaScript
    └── WebUSB API behavior

TypeScript
    └── API type checks

Rust
    └── Native acceleration tests
```

自动化测试不能完全替代真实 USB 设备测试。特别是 Isochronous Transfer 的真实硬件验证仍不完整。

## Isochronous Transfer

Isochronous Transfer 已实现，但目前属于 best-effort。

pyusb 公共 API 没有提供足够的 per-packet 信息，因此无法完全提供 WebUSB 所需的 per-packet fidelity。

在 pyusb 1.3.1 中，底层 libusb 结构包含每个 packet 的 `actual_length`，但公开的 `iso_read()` API 只能提供合计长度。

因此当前实现不会在没有真实硬件验证的情况下强行依赖 pyusb private internals，而是把该问题作为已知限制记录。

真实设备上的 per-packet 验证以及非均一 packet length 的扩展支持属于后续工作。

## 当前状态

**v0.0.5b1 — Experimental Beta**

### 已实现

- [x] `navigator.usb`
- [x] JavaScript WebUSB Polyfill
- [x] QWebChannel bridge
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
- [x] Automated tests
- [x] Direct QWebChannel bypass hardening
- [x] Canonical Base64 validation
- [x] Malformed Base64 → `DataError`
- [x] PySide6 / QtWebEngine import diagnostics
- [x] Serial-number device disambiguation
- [x] Protected alternate-setting checks
- [x] `window.USB` / `window.USBDevice` / `window.USBConnectionEvent` exposure

### 仍处于实验阶段

- [ ] 广泛的真实 USB 设备测试
- [ ] Isochronous Transfer 真实硬件验证
- [ ] 非均一 Isochronous packet length 的扩展支持
- [ ] 更广泛的 OS / USB driver 兼容性
- [ ] 长期 API 稳定化
- [ ] 与现有 WebUSB 网站的兼容性验证

## 与 Mock-webusb 的关系

`pyside6-webusb` 是 **Mock-webusb** 的 PySide6 / QtWebEngine 实现。

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

目标并不是完全复制 Chrome 内部的 WebUSB 实现，而是在不同 Host 环境中提供 WebUSB-compatible API。

与 Chrome 的有意差异会被记录，而不会静默隐藏。

## 注意事项

> ⚠️ `pyside6-webusb` 是实验性软件。

这是一个 1.0 之前的项目。API、兼容性以及真实设备支持都可能继续变化。

项目可能包含 AI 生成的代码或由 AI 协助产生的代码。

因此可能存在 bug、未完成行为、环境相关问题、兼容性差异以及尚未发现的安全问题。

如果用于生产环境，请完整验证目标 OS、USB 设备、驱动、libusb 以及 WebUSB 应用程序。

## Related projects

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

[MIT License](https://github.com/steck0714/Mock-webusb/blob/main/LICENSE)
