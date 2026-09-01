# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **実験版 (v0.0.4b1)**

PySide6 / QtWebEngine向けのWebUSB互換実装です。

JavaScriptポリフィル、QWebChannelブリッジ、pyusb/libusbを使用した実際のUSB通信によって `navigator.usb` を提供します。

## 主な機能

- WebUSB互換 `navigator.usb`
- 実際のUSBデバイス通信
- ネイティブデバイス選択ダイアログ
- Originごとの権限管理
- WebUSBのセキュリティ保護
- WebUSB API互換

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
```

## 現在の状態

初期ベータ版です。

Isochronous transferは、まだ実機ハードウェアでの検証が完了していません。

## License

MIT License.