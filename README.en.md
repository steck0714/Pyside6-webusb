# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Beta — v0.0.5b3**

A WebUSB API implementation for **PySide6 / QtWebEngine** applications.

It combines a JavaScript polyfill, a QWebChannel bridge, and real USB access through **pyusb / libusb** to provide `navigator.usb`, which is not normally available in embedded QtWebEngine.

> The GitHub development/release label is `v0.0.5b3`. The actual package version shipped under PyPI/PEP 440 is `0.0.5.post7`.

## Features

- WebUSB-compatible `navigator.usb`
- Communication with real USB devices
- Native device chooser dialog, with built-in English / Japanese / Chinese translations
- Per-origin device permissions
- Frame-aware origin handling
- WebUSB security protections
- Chromium known-security-key blocklist
- Transfer validation and safety limits
- WebUSB `filters` / `exclusionFilters` matching
- Hotplug monitoring with `connect` / `disconnect` events
- `window.__pysideWebUSB` DevTools / F12 helpers
- Optional Rust native acceleration
- Host environment diagnostics
- `pyside6-webusb-doctor`
- JSON environment diagnostics
- Host-application device pre-authorization
- TypeScript definitions
- WebUSB-compatible DOMException and transfer behavior

## Why this exists

PySide6's QtWebEngine is based on Chromium, but embedded QtWebEngine does not expose WebUSB in the same way as the full Chrome browser.

If a PySide6 application loads a device configuration tool, firmware tool, or hardware dashboard that expects `navigator.usb`, the API may simply be unavailable.

`pyside6-webusb` fills that gap.

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://example.com")
```

For normal applications, calling `install()` once after creating the page connects the WebUSB polyfill and bridge.

## Installation

```bash
pip install pyside6-webusb
```

For a development checkout:

```bash
pip install -e .
```

Main dependencies:

- Python >= 3.9
- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- OS-level libusb

On Linux, an OS-level `libusb-1.0` package may also be required.

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
    ├── Filter / exclusion filter matching
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

The page receives a WebUSB-compatible JavaScript API, while Python handles permissions, security, device selection, and native USB access through pyusb/libusb.

## API

The main API is:

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

Device selection:

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

await device.open();
```

Actual device and transfer support depends on the OS, USB driver, libusb, and the device itself.

## Security model

`pyside6-webusb` does not expose the system's USB device list to arbitrary web pages.

Main protections include:

- Origin-based device permissions
- Native device chooser
- Frame-aware origin attribution
- Protected USB interface-class rejection
- Chromium known-security-key blocklist
- Transfer-size validation
- Host-side safety limit
- Endpoint / interface validation
- Native-side validation
- `getDevices()` restricted to granted devices
- `requestDevice()` user-gesture validation
- Chooser reentrancy protection
- Protection of host-only management APIs against direct QWebChannel access
- Sanitization of device-supplied strings
- Origin-aware hotplug event visibility
- Per-origin simultaneous-open-handle limits

Eight protected interface classes are rejected: Audio, HID, Mass Storage, Hub, Smart Card, Video, Audio/Video, and Wireless Controller.

The protection is also enforced for transfers, `clearHalt()`, and `selectAlternateInterface()` so that `claimInterface()` cannot simply be bypassed.

## WebUSB filters

`requestDevice()` supports `filters` and `exclusionFilters`, matching Vendor ID, Product ID, Serial Number, Interface Class / Subclass / Protocol, and related fields.

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

Filter structure is independently validated on the Python side.

## Transfers

The implementation covers:

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

Isochronous transfers still have backend and real-hardware limitations.

## Large transfers

32 MiB is an important transfer-size reference point in Chrome / Chromium.

`pyside6-webusb` intentionally does not reject transfers above 32 MiB in the same way. Instead, the difference is made explicit:

- A `console.warn()` is emitted above 32 MiB
- The warning is visible in DevTools / F12
- A separate 512 MiB host-side safety ceiling is applied

Therefore:

> **WebUSB-compatible ≠ Chrome clone**

Intentional compatibility differences are documented instead of being hidden.

## DevTools / F12

The page receives:

```javascript
window.__pysideWebUSB
```

Main helpers:

```javascript
window.__pysideWebUSB.listGrantedDevices()
window.__pysideWebUSB.bridgeInfo()
window.__pysideWebUSB.explainTransferLimits()
```

`bridgeInfo()` reports the bridge version, Rust acceleration status, and transfer limits.

## Host-application pre-authorization

A trusted host application can pre-authorize a specific USB device for a specific origin:

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

This is intended for kiosk and embedded applications where allowed origins and devices are determined by host configuration.

This management method is deliberately not exposed as a Qt Slot callable from web content.

## Environment diagnostics

Python:

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

JSON:

```bash
pyside6-webusb-doctor --json
```

```bash
python -m pyside6_webusb --json
```

`--json` prints the `environment_report()` result as JSON. Exit-code behavior remains the same: real problems produce a non-zero exit code.

The report can include:

- Python version
- Python implementation
- PySide6 version
- shiboken6 version
- Qt runtime version
- pyusb version
- resolved libusb backend
- `pyusb_backend_note`
- `qtwebengine_importable`
- frame-origin isolation availability
- Rust acceleration status
- detected problems

`pyusb_backend_note` provides additional information when pyusb falls back to the older `libusb0` backend.

`qtwebengine_importable` separately checks whether `QtWebEngineCore` / `QtWebEngineWidgets` can actually be imported. This is useful for the PySide6 6.12 development-series packaging change where QtWebEngine was moved into a separate wheel.

Frame-origin isolation reports whether the stronger `QWebEngineFrame`-based model is available. Older PySide6 environments fall back to the more limited main-frame-only behavior.

## Native acceleration

An optional Rust acceleration layer is available.

It covers:

- Base64 encoding / decoding
- Binary processing
- ADB wire-protocol message framing helpers
- Transfer-response JSON construction

Rust acceleration is optional. If it is unavailable, the Python implementation is used instead.

The Rust crate uses PyO3's `abi3-py39` configuration, allowing a single ABI-compatible wheel to cover the package's Python >= 3.9 range, including very new Python versions when the forward-compatibility build mode is required.

## TypeScript

`types/webusb-polyfill.d.ts` contains TypeScript definitions for the WebUSB surface installed by the polyfill.

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

`types/sample-usage.ts` and `types/negative-check.ts` exercise both valid and invalid API usage.

## Testing

The release includes Python tests, security-audit tests, Node polyfill tests, TypeScript checks, and Rust tests.

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

This release ran with:

**184 passed, 2 skipped**

The Node polyfill and TypeScript checks were also re-run.

Automated tests do not replace testing against real USB devices.

## Isochronous transfers

Isochronous transfers are implemented on a best-effort basis.

The public pyusb API does not expose enough per-packet information to provide complete per-packet fidelity. In particular, pyusb 1.3.1's underlying libusb structure contains per-packet `actual_length`, while the public `iso_read()` API exposes only the combined length.

The current implementation therefore leaves this as a known limitation rather than reaching into pyusb's private internals without real hardware verification.

## Current status

**v0.0.5b3 — Experimental Beta**

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

### Still experimental

- [ ] Broad real-device testing
- [ ] Real-hardware Isochronous Transfer verification
- [ ] Expanded support for non-uniform Isochronous packet lengths
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

It is a pre-1.0 project. APIs, compatibility, and real-device support may change.

This project may contain AI-generated code or code produced with AI assistance.

Bugs, incomplete behavior, environment-specific problems, compatibility differences, and undiscovered security issues may exist.

For production use, validate the complete target environment, including the OS, USB device, driver, libusb, and the WebUSB application.

## Related projects

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

[MIT License](https://github.com/steck0714/Mock-webusb/blob/main/LICENSE)
