# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental (v0.0.4b1)**

A WebUSB-compatible implementation for PySide6 / QtWebEngine applications.

It provides `navigator.usb` through a JavaScript polyfill, a QWebChannel bridge, and real USB communication via pyusb/libusb.

## Features

- WebUSB-compatible `navigator.usb`
- Real USB device communication
- Native device chooser
- Per-origin permissions
- WebUSB security protections
- WebUSB API compatibility

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
```

## Status

Early beta. Isochronous transfers have not yet been verified with physical hardware.

## License

MIT License.