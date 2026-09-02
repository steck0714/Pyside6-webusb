# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental (v0.0.4b2)**

A WebUSB-compatible implementation for **PySide6 / QtWebEngine** applications.

It provides `navigator.usb` through a JavaScript polyfill, a QWebChannel bridge, and real USB communication via **pyusb/libusb**.

## Features

- WebUSB-compatible `navigator.usb`
- Real USB device communication
- Native device chooser
- Per-origin permissions
- Frame-aware origin handling
- WebUSB security protections
- Chromium security-key blocklist
- Transfer validation and safety limits
- DevTools / F12 debugging support
- Optional native acceleration
- WebUSB API compatibility

## Quick Start

~~~python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://example.com")
~~~

## Architecture

~~~text
Web page
    │
    │ navigator.usb
    ▼
JavaScript WebUSB polyfill
    │
    │ QWebChannel
    ▼
WebUSBBridge
    │
    ├── Origin / security checks
    ├── Permission management
    ├── Native device chooser
    └── Transfer validation
    │
    ▼
pyusb / libusb
    │
    ▼
USB device
~~~

## Security

- Origin-based device permissions
- Native device chooser
- Frame-aware origin attribution
- Protected USB interface checks
- Chromium security-key blocklist
- Transfer-size validation
- Host-side safety limits

`getDevices()` only exposes devices that have already been granted to the requesting origin.

## Chrome Compatibility

Chrome / Chromium behavior is used as a compatibility reference, but this project is **not a byte-for-byte Chrome clone**.

> **WebUSB-compatible ≠ Chrome clone**

The Chrome 32 MiB transfer limit is treated as a warning in this implementation rather than an unconditional rejection. A separate host-side safety limit is also applied.

## Debugging

The following debug namespace is available:

~~~javascript
window.__pysideWebUSB
~~~

It provides information such as:

- Granted devices for the current origin
- Bridge version
- Native acceleration status
- Transfer limits
- Transfer-limit explanations

DevTools / F12 can therefore be used to inspect the WebUSB implementation from the page side.

## Installation

~~~bash
pip install pyside6-webusb
~~~

Or install directly from the source tree:

~~~bash
pip install -e .
~~~

## Status

**Early beta — v0.0.4b2**

The implementation is functional and tested, but some areas are still experimental.

In particular:

- Isochronous transfers have not yet been fully verified with physical hardware.
- Non-uniform isochronous packet lengths remain limited.
- Native acceleration is optional.

See [`CHANGELOG.md`](CHANGELOG.md) for details.

## Related Projects

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

MIT License.