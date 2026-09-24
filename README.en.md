# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Beta — v0.0.5b2**

A WebUSB API implementation for **PySide6 / QtWebEngine** applications.

It combines a JavaScript WebUSB Polyfill, QWebChannel Bridge, and real USB communication through **pyusb / libusb** to provide `navigator.usb`.

> The GitHub development/release label is `v0.0.5b2`. The actual PyPI / PEP 440 package version is `0.0.5.post6`.

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
- `window.__pysideWebUSB` DevTools / F12 helpers
- Optional Rust native acceleration
- Host environment diagnostics
- `pyside6-webusb-doctor`
- JSON environment diagnostics
- Host-application device pre-authorization
- TypeScript definitions
- WebUSB-compatible DOMException / Transfer model
- Virtual USB backend / virtual USB device testing support

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://example.com")
```

## Installation

```bash
pip install pyside6-webusb
```

For development:

```bash
pip install -e .
```

Main dependencies:

- Python >= 3.9
- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- OS-level libusb

## Architecture

```text
Web page
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
USB device
```

This is not a direct transplant of Chromium's internal WebUSB implementation.

## API

Main API:

```javascript
navigator.usb
```

Main objects:

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

```javascript
const device = await navigator.usb.requestDevice({
    filters: [{ vendorId: 0x1234 }]
});
await device.open();
```

## Security Model

Main protections include:

- Origin-based device permissions
- Native device selection
- Frame-aware origin attribution
- Protected USB Interface Class rejection
- Chromium-derived known-security-key blocklist
- Transfer-size validation
- Host-side safety limits
- Endpoint / Interface validation
- Native-side validation
- `getDevices()` restricted to authorized devices
- User-activation checks for `requestDevice()`
- Chooser re-entry protection
- Protection against direct-channel bypass of host-only management APIs
- Sanitization of device-originated strings
- Origin-scoped hotplug visibility checks
- Per-origin concurrent-open-handle limits

## WebUSB Filters

`requestDevice()` supports `filters` / `exclusionFilters`.

```javascript
const device = await navigator.usb.requestDevice({
    filters: [{ vendorId: 0x1234, productId: 0x5678 }]
});
```

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

## Large Transfers

32 MiB is an important transfer-size reference in Chrome / Chromium.

`pyside6-webusb` intentionally does not immediately reject transfers above 32 MiB:

- `console.warn()` is emitted above 32 MiB
- The condition can be inspected through DevTools / F12
- A separate 512 MiB host-side safety ceiling is applied

> **WebUSB-compatible ≠ Chrome clone**

## DevTools / F12

```javascript
window.__pysideWebUSB
```

This exposes bridge information, granted-device state, and transfer-limit diagnostics.

## Host Application Pre-Authorization

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

## Environment Diagnostics

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

An optional Rust acceleration layer is available for:

- Base64 encoding / decoding
- Binary processing
- ADB wire-protocol message framing helper
- Transfer response JSON construction

If unavailable, the implementation falls back to Python. The Rust crate uses PyO3 `abi3-py39`.

## TypeScript

WebUSB TypeScript definitions are included in:

```text
types/webusb-polyfill.d.ts
```

## Virtual USB

Virtual USB backend / virtual USB device support is included for testing.

```python
from pyside6_webusb.virtual import VirtualUsbDevice
```

It allows USB descriptors and transfer behavior to be tested without physical USB hardware.

## Testing

The project includes Python tests, security audit, Node/polyfill tests, TypeScript checks, and Rust tests.

```text
184 passed, 2 skipped
```

Automated tests do not replace real-hardware validation.

## Isochronous Transfers

Isochronous Transfer is implemented on a best-effort basis.

The public pyusb API does not expose enough per-packet length / result information for complete fidelity, especially for IN transfers.

## Current Status

**v0.0.5b2 — Experimental Beta**

### Implemented

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

### Still Experimental

- [ ] Broad real-hardware USB validation
- [ ] Real-hardware Isochronous Transfer verification
- [ ] Expanded support for non-uniform Isochronous packet lengths
- [ ] Wider OS / USB-driver compatibility
- [ ] Long-term API stabilization
- [ ] Compatibility testing with existing WebUSB websites

## Relationship to Mock-webusb

`pyside6-webusb` is the PySide6 / QtWebEngine implementation under **Mock-webusb**.

```text
Mock-webusb
   │
   ├── pyside6-webusb
   │      └── PySide6 / QtWebEngine
   │
   └── fox-webusb
          └── Firefox / Native Messaging
```

The goal is not to reproduce Chrome's internal WebUSB implementation exactly, but to provide a WebUSB-compatible API in different host environments.

## Important Notes

> ⚠️ `pyside6-webusb` is experimental software.

This is a v0.x project. APIs, compatibility, and real-hardware support may change.

The project may contain AI-generated code or code developed with AI assistance.

Bugs, incomplete behavior, environment-specific problems, compatibility differences, and undiscovered security issues may exist.

For production use, thoroughly validate the target OS, USB devices, drivers, libusb backend, and WebUSB application together.

## License

MIT License
