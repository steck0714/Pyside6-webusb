# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Beta — v0.0.5b1**

A WebUSB API implementation for **PySide6 / QtWebEngine** applications.

It combines a JavaScript WebUSB polyfill, a QWebChannel bridge, and real USB access through **pyusb / libusb** to provide `navigator.usb`, which is normally unavailable in embedded QtWebEngine.

> The GitHub development label is `v0.0.5b1`. The actual package version shipped under PyPI / PEP 440 is `0.0.5.post5`.

## Features

- WebUSB-compatible `navigator.usb`
- Communication with real USB devices
- Native device chooser dialog
- Per-origin device permissions
- Frame-aware origin handling
- WebUSB security protections
- Chromium known-security-key blocklist
- Transfer validation and safety limits
- WebUSB `filters` / `exclusionFilters` matching
- Hotplug monitoring with `connect` / `disconnect` events
- `window.__pysideWebUSB` for DevTools / F12 debugging
- Optional Rust native acceleration
- Host-environment diagnostics
- `pyside6-webusb-doctor`
- JSON diagnostics
- Host-application device pre-authorization
- TypeScript definitions
- WebUSB-compatible DOMException / transfer models
- Virtual USB backend / virtual USB device test support

## Why this exists

PySide6's QtWebEngine is based on Chromium, but the embeddable QtWebEngine component does not expose WebUSB in the same way as the full Chrome/Chromium browser shell.

If a PySide6 application loads a device configuration tool, firmware flasher, or hardware dashboard that expects `navigator.usb`, the API is normally unavailable inside the embedded page.

`pyside6-webusb` fills that gap.

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://your-site.example")
```

For a normal application, calling `install()` once after creating the page connects the WebUSB polyfill and bridge.

## Installation

```bash
pip install pyside6-webusb
```

For a development install from the source tree:

```bash
pip install -e .
```

Main dependencies:

- Python >= 3.9
- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- system-level libusb

On Linux, `libusb-1.0` may need to be installed separately.

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
    ├── Filter / exclusionFilter matching
    ├── Transfer validation
    ├── Protected-class / blocklist checks
    └── Device / handle management
    │
    ▼
pyusb / libusb
    │
    ▼
USB device
```

This is not a direct port of Chromium's internal WebUSB implementation.

The page receives a WebUSB-compatible JavaScript API. Python handles permissions, security, device selection, and related policy before accessing the USB device through pyusb/libusb.

## API

The central API is:

```javascript
navigator.usb
```

Main objects include:

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

Request a device:

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

await device.open();
```

Actual device and transfer capabilities depend on the operating system, USB driver, libusb, and the device itself.

## Security model

`pyside6-webusb` is not designed to expose every USB device on the system to arbitrary web pages.

Main protections include:

- Origin-based device permissions
- Native device chooser
- Frame-aware origin attribution
- Rejection of protected USB interface classes
- Chromium-derived known-security-key blocklist
- Transfer-size validation
- Host-side safety limits
- Endpoint / interface validation
- Native-side validation
- `getDevices()` limited to authorized devices
- User-gesture validation for `requestDevice()`
- Chooser re-entry protection
- Protection against bypassing host-only management APIs through direct QWebChannel calls
- Sanitization of device-provided strings
- Origin-scoped visibility checks for hotplug events
- Per-origin simultaneous-open-handle limits

Eight protected interface classes are rejected: Audio, HID, Mass Storage, Hub, Smart Card, Video, Audio/Video, and Wireless Controller.

The protection is also enforced across paths such as `claimInterface()`, transfers, `clearHalt()`, and `selectAlternateInterface()` so that protected interfaces cannot simply be reached through another operation.

## WebUSB filters

`requestDevice()` supports `filters` and `exclusionFilters`, matching fields such as Vendor ID, Product ID, Serial Number, Interface Class / Subclass / Protocol, and related values.

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

Filter structures are independently validated on the Python side, including type and numeric-range checks.

## Transfers

The implementation handles:

- Control Transfer
- Bulk Transfer
- Interrupt Transfer
- Isochronous Transfer
- Interface Claim / Release
- Alternate Interface
- Endpoint Halt / Clear Halt
- Device Reset
- Open / Close

Transfer states such as `stall` and `babble` are mapped to the WebUSB result model where applicable.

Isochronous transfers are implemented, but per-packet fidelity remains best-effort because of limitations in pyusb's public API.

## Large transfers

32 MiB is an important transfer-size reference point in Chrome / Chromium.

`pyside6-webusb` does not simply reject transfers above 32 MiB like Chrome. Instead, the compatibility difference is made explicit:

- A `console.warn()` is generated above 32 MiB
- The warning can be inspected in DevTools / F12
- A separate 512 MiB safety limit is enforced on the host side

Therefore:

> **WebUSB-compatible ≠ Chrome clone**

Intentional differences from Chrome are documented in the README and CHANGELOG.

## DevTools / F12

The page exposes:

```javascript
window.__pysideWebUSB
```

Useful helpers include:

```javascript
window.__pysideWebUSB.listGrantedDevices()
window.__pysideWebUSB.bridgeInfo()
window.__pysideWebUSB.explainTransferLimits()
```

`bridgeInfo()` can report the bridge version, Rust acceleration status, transfer limits, and related information.

## Host-application pre-authorization

A trusted host application can pre-authorize a specific USB device for a specific Origin:

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

This is intended for kiosks, embedded applications, and other environments where the host application wants to fix the set of permitted Origins and devices.

The management method is not exposed as a Qt Slot callable directly by web content.

## Environment diagnostics

From Python:

```python
from pyside6_webusb import (
    environment_report,
    format_environment_report,
)

print(format_environment_report())
```

Command line:

```bash
pyside6-webusb-doctor
```

or:

```bash
python -m pyside6_webusb
```

JSON output:

```bash
pyside6-webusb-doctor --json
```

```bash
python -m pyside6_webusb --json
```

Diagnostics can report, among other things:

- Python version / implementation
- PySide6 version
- shiboken6 version
- Qt runtime version
- pyusb version
- Resolved libusb backend
- `pyusb_backend_note`
- `qtwebengine_importable`
- Frame-origin isolation availability
- Rust acceleration status
- Detected problems

`qtwebengine_importable` checks whether `QtWebEngineCore` / `QtWebEngineWidgets` can actually be imported.

Frame-origin isolation selects the strongest mode supported by the available PySide6 APIs, and the diagnostic report shows the mode actually in use.

## Native acceleration

An optional Rust acceleration layer is available.

It is used for tasks such as:

- Base64 encode / decode
- Binary processing
- ADB wire-protocol message framing helpers
- Transfer response JSON construction

Rust acceleration is optional. If it is unavailable, the implementation falls back to Python.

The Rust crate is structured around PyO3 `abi3-py39`, making it practical to build ABI-compatible wheels for newer Python versions as well.

## TypeScript

`types/webusb-polyfill.d.ts` provides TypeScript definitions for the WebUSB API.

Examples include:

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

`types/sample-usage.ts` and `types/negative-check.ts` cover both valid usage and intentional type errors.

## Testing

The release includes validation across Python tests, security audits, Node polyfill tests, TypeScript checks, and Rust tests.

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

Automated tests do not replace testing against real USB devices. In particular, real-hardware validation of isochronous transfers remains incomplete.

## Isochronous transfers

Isochronous transfers are implemented on a best-effort basis.

The public pyusb API does not expose enough per-packet information to provide complete per-packet fidelity.

In pyusb 1.3.1, the underlying libusb structure contains per-packet `actual_length`, while the public `iso_read()` API exposes only the combined length.

The current implementation therefore treats this as a known limitation rather than depending on pyusb private internals without real hardware verification.

Real-device per-packet validation and expanded support for non-uniform packet lengths remain future work.

## Current status

**v0.0.5b1 — Experimental Beta**

### Implemented

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

### Still experimental

- [ ] Broad real-device testing
- [ ] Real-hardware isochronous-transfer verification
- [ ] Expanded support for non-uniform isochronous packet lengths
- [ ] Wider OS / USB-driver compatibility
- [ ] Long-term API stabilization
- [ ] Compatibility verification with existing WebUSB sites

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

The goal is not to reproduce Chrome's internal WebUSB implementation perfectly, but to provide a WebUSB-compatible API across different host environments.

Intentional differences from Chrome are documented rather than silently hidden.

## Important notes

> ⚠️ `pyside6-webusb` is experimental software.

This is a pre-1.0 project. APIs, compatibility, and real-device support may change.

The project may contain AI-generated code or code produced with AI assistance.

Bugs, incomplete behavior, environment-specific problems, compatibility differences, and undiscovered security issues may exist.

For production use, validate the complete target environment, including the OS, USB device, driver, libusb, and the WebUSB application.

## Related projects

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

[MIT License](https://github.com/steck0714/Mock-webusb/blob/main/LICENSE)
