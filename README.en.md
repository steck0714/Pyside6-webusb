# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Alpha — v0.0.5a0**

A WebUSB API implementation for **PySide6 / QtWebEngine** applications.

It provides `navigator.usb` through a JavaScript polyfill, a QWebChannel bridge, and real USB communication through **pyusb / libusb**.

## Features

- WebUSB-compatible `navigator.usb`
- Real USB device communication
- Native device chooser
- Per-origin device permissions
- Frame-aware origin handling
- WebUSB security protections
- Chromium security-key blocklist
- Transfer validation and safety limits
- WebUSB filter matching
- USB hotplug monitoring and connection events
- DevTools / F12 debugging support
- Optional Rust native acceleration
- Host environment diagnostics
- Host-side device pre-authorization
- WebUSB API compatibility

## Why does this exist?

QtWebEngine uses Chromium technology, but an embedded QtWebEngine application does not expose the same WebUSB environment as the full Chrome / Chromium browser.

Applications such as device configuration tools, firmware utilities, and hardware dashboards may expect `navigator.usb` to exist.

`pyside6-webusb` fills that gap for PySide6 applications.

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()

install(view.page())

view.load("https://example.com")
```

For most applications, calling `install()` once for the page is enough to connect the WebUSB polyfill and Python bridge.

## Installation

```bash
pip install pyside6-webusb
```

Or install directly from the source tree:

```bash
pip install -e .
```

Main dependencies:

- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- An OS-level libusb implementation

On Linux, an OS-level `libusb-1.0` package may need to be installed separately.

## Architecture

```text
Web page
    │
    │ navigator.usb
    ▼
JavaScript WebUSB Polyfill
    │
    │ QWebChannel
    ▼
WebUSBBridge
    │
    ├── Origin / Frame security
    ├── Permission management
    ├── Native device chooser
    ├── Filter matching
    ├── Transfer validation
    └── Device / handle management
    │
    ▼
pyusb / libusb
    │
    ▼
USB device
```

This is not a direct copy of Chromium's internal WebUSB implementation.

The page receives a WebUSB-compatible JavaScript API, while Python handles permissions, security checks, device selection, and USB operations through pyusb/libusb.

## API

The primary API is:

```javascript
navigator.usb
```

The implementation provides a WebUSB-style object model including:

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

Example:

```javascript
const devices = await navigator.usb.getDevices();

console.log(devices);
```

Device selection:

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

await device.open();
```

Actual device and transfer compatibility depends on the OS, USB drivers, libusb, and device-specific behavior.

## Security Model

`pyside6-webusb` is not designed to expose every USB device on the host system to arbitrary web pages.

Major protections include:

- Origin-based device permissions
- Native device chooser
- Frame-aware origin attribution
- Protected USB interface class checks
- Chromium-derived known security-key blocklist
- Transfer-size validation
- Host-side safety limits
- Endpoint / interface validation
- Native-side validation
- `getDevices()` limited to already-authorized devices

```text
requestDevice()
      │
      ▼
Device chooser
      │
      ▼
User / host authorization
      │
      ▼
Granted device
      │
      ▼
getDevices()
```

`getDevices()` is intended to expose only devices already granted to the requesting origin.

## WebUSB Filters

`requestDevice()` supports `filters` and `exclusionFilters`, including matching by Vendor ID, Product ID, Serial Number, Interface Class / Subclass / Protocol, and related WebUSB filter fields.

Filter structure is also validated according to the WebUSB model.

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

## USB Transfers

The implementation covers operations such as:

- Control Transfer
- Bulk Transfer
- Interrupt Transfer
- Isochronous Transfer
- Interface Claim / Release
- Alternate Interface selection
- Endpoint Halt / Clear Halt
- Device Reset
- Open / Close

WebUSB transfer states such as `stall` and `babble` are mapped to the WebUSB result model where possible.

Isochronous transfers still have backend- and hardware-dependent limitations.

## Large Transfers

Chrome / Chromium uses 32 MiB as an important transfer-size reference value.

`pyside6-webusb` treats that value as a **compatibility reference**, but does not reject transfers above 32 MiB merely because Chrome does.

Instead:

- transfers above 32 MiB generate a warning
- the warning is forwarded to `console.warn()`
- an independent host-side safety ceiling is applied

Therefore:

> **WebUSB-compatible ≠ Chrome clone**

This is an intentional design choice. Compatibility differences are documented instead of being hidden, while a separate host-side limit prevents unbounded resource usage.

## DevTools / F12

A debug namespace is available on the page:

```javascript
window.__pysideWebUSB
```

It can expose implementation information such as:

- Bridge version
- Rust acceleration status
- Transfer limits
- Devices already visible to the current origin
- Transfer-limit explanations

DevTools / F12 can therefore be used to inspect the WebUSB implementation from the page side.

## Host-side Pre-Authorization

v0.0.5a0 adds a host-application API for pre-authorizing a specific device for a specific origin.

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

This is intended for kiosk and embedded deployments where the allowed origins and devices are determined by host application configuration.

The management API is deliberately not exposed as a Qt Slot callable directly by web content.

## Environment Diagnostics

v0.0.5a0 adds environment diagnostics:

```python
from pyside6_webusb import (
    environment_report,
    format_environment_report,
)

print(format_environment_report())
```

Or from the command line:

```bash
pyside6-webusb-doctor
```

Or:

```bash
python -m pyside6_webusb
```

The report can include:

- Python version
- Python implementation
- PySide6 version
- shiboken6 version
- Qt runtime version
- pyusb version
- resolved libusb backend
- Rust acceleration status
- detected problems

Missing Rust acceleration is not treated as a failure because the normal Python implementation remains fully supported.

## Native Acceleration

An optional Rust acceleration layer is included.

It can provide optimized handling for areas such as:

- Base64 encoding / decoding
- Binary processing
- Pack / Unpack
- Validation helpers
- Checksum-related processing

The acceleration layer is optional.

## TypeScript

TypeScript definitions for the WebUSB-style API are included.

For example:

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

This allows applications to work with the compatibility API using type information rather than an untyped injected script alone.

## Testing

The project contains tests for multiple implementation layers:

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

Automated tests do not replace testing with physical USB hardware.

OS behavior, USB drivers, libusb compatibility, device-specific behavior, isochronous transfers, and permission boundaries should be verified in the target environment.

## Current Status

**v0.0.5a0 — Early Alpha / Beta-quality experimental release**

v0.0.5a0 builds on the WebUSB-compatible implementation from v0.0.4b3 and adds host-application capabilities and diagnostics.

### Implemented

- [x] `navigator.usb`
- [x] JavaScript WebUSB polyfill
- [x] QWebChannel bridge
- [x] pyusb / libusb backend
- [x] Native device chooser
- [x] Origin permissions
- [x] Frame-aware origin handling
- [x] WebUSB filter matching
- [x] USB transfers
- [x] Hotplug monitoring
- [x] Security hardening
- [x] Chromium security-key blocklist
- [x] DevTools debug namespace
- [x] Optional Rust acceleration
- [x] Host-side device pre-authorization
- [x] Environment diagnostics
- [x] `pyside6-webusb-doctor`
- [x] TypeScript definitions
- [x] Automated tests

### Still Experimental

- [ ] Validation with a wider range of physical USB devices
- [ ] Physical-hardware verification of isochronous transfers
- [ ] Expanded support for non-uniform isochronous packet lengths
- [ ] Broader OS / USB-driver compatibility
- [ ] Long-term API stabilization
- [ ] Compatibility testing with existing WebUSB applications

## Relationship to Mock-webusb

`pyside6-webusb` is the PySide6 / QtWebEngine implementation under **Mock-webusb**.

The related Firefox implementation is `fox-webusb`.

```text
Mock-webusb
   │
   ├── pyside6-webusb
   │      └── PySide6 / QtWebEngine
   │
   └── fox-webusb
          └── Firefox / Native Messaging
```

These projects are intended to provide WebUSB-compatible APIs across different host environments rather than reproduce Chromium's internal implementation byte-for-byte.

## ⚠️ Disclaimer

> ⚠️ `pyside6-webusb` is experimental software.

This project is in the v0.x series, and APIs, compatibility, and hardware support may change.

The project may contain AI-generated code or code developed with AI assistance.

Bugs, incomplete behavior, environment-specific issues, compatibility differences, and undiscovered security problems may exist.

Before using it in production, test the complete target environment, including the OS, USB drivers, USB devices, and the WebUSB application itself.

## Related Projects

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

MIT License.
