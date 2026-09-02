# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **実験版 (v0.0.4b2)**

PySide6 / QtWebEngine向けのWebUSB互換実装です。

JavaScriptポリフィル、QWebChannelブリッジ、pyusb/libusbを使用した実際のUSB通信によって `navigator.usb` を提供します。

## 主な機能

- WebUSB互換 `navigator.usb`
- 実際のUSBデバイス通信
- ネイティブデバイス選択ダイアログ
- Originごとの権限管理
- フレーム対応のOrigin処理
- WebUSBのセキュリティ保護
- Chromiumのセキュリティキー・ブロックリスト
- 転送サイズの検証と安全制限
- DevTools / F12デバッグ対応
- オプションのネイティブアクセラレーション
- WebUSB API互換

## Quick Start

~~~python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://example.com")
~~~

## アーキテクチャ

~~~text
Webページ
    │
    │ navigator.usb
    ▼
JavaScript WebUSBポリフィル
    │
    │ QWebChannel
    ▼
WebUSBBridge
    │
    ├── Origin / セキュリティチェック
    ├── 権限管理
    ├── ネイティブデバイス選択
    └── 転送検証
    │
    ▼
pyusb / libusb
    │
    ▼
USBデバイス
~~~

## セキュリティ

- Originベースのデバイス権限
- ネイティブデバイス選択
- フレーム対応のOrigin識別
- 保護対象USBインターフェースのチェック
- Chromiumのセキュリティキー・ブロックリスト
- 転送サイズの検証
- ホスト側の安全制限

`getDevices()` は、リクエスト元のOriginに対して明示的に許可されたデバイスのみを返します。

## Chromeとの互換性

Chrome / Chromiumの挙動を互換性の基準として使用していますが、このプロジェクトは**Chromeの完全なクローンではありません**。

> **WebUSB互換 ≠ Chromeクローン**

Chromeの32 MiB転送制限は、この実装では無条件の拒否ではなく警告として扱われます。また、別途ホスト側の安全制限が適用されます。

## デバッグ

以下のデバッグ用名前空間を利用できます。

~~~javascript
window.__pysideWebUSB
~~~

以下のような情報を確認できます。

- 現在のOriginに許可されたデバイス
- ブリッジのバージョン
- ネイティブアクセラレーションの状態
- 転送サイズ制限
- 転送制限の説明

DevTools / F12から、ページ側のWebUSB実装を確認できます。

## インストール

~~~bash
pip install pyside6-webusb
~~~

ソースツリーから直接インストールする場合：

~~~bash
pip install -e .
~~~

## 現在の状態

**初期ベータ版 — v0.0.4b2**

実装は動作しておりテスト済みですが、一部の機能はまだ実験的です。

特に以下の点には注意してください。

- Isochronous transferは、まだ実機ハードウェアでの完全な検証が完了していません。
- 不均一なIsochronous packet lengthには現在も制限があります。
- ネイティブアクセラレーションはオプションです。

詳細については [`CHANGELOG.md`](CHANGELOG.md) を参照してください。

## 関連プロジェクト

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

MIT License.