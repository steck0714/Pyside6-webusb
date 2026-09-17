# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Alpha — v0.0.5a0**

**PySide6 / QtWebEngine** アプリケーション向けの WebUSB API 実装です。

JavaScript ポリフィル、QWebChannel ブリッジ、**pyusb / libusb** による実USB通信を組み合わせ、QtWebEngine では標準提供されていない `navigator.usb` を提供します。

## 特徴

- WebUSB互換 `navigator.usb`
- 実USBデバイスとの通信
- ネイティブデバイス選択ダイアログ
- Originごとのデバイス権限
- Frame-awareなOrigin処理
- WebUSBセキュリティ保護
- Chromiumのセキュリティキー・ブロックリスト
- Transferの検証と安全制限
- WebUSBフィルタの仕様準拠照合
- Hotplugの監視と `connect` / `disconnect` イベント
- DevTools / F12向けデバッグ情報
- オプションのRustネイティブアクセラレーション
- ホスト環境診断ユーティリティ
- ホストアプリからのデバイス事前認可
- WebUSB API互換性

## なぜ必要なのか

PySide6が提供するQtWebEngineはChromiumをベースにしていますが、埋め込み用のQtWebEngine環境では通常のChromeブラウザと同じWebUSB機能がそのまま利用できません。

WebUSBを必要とするデバイス設定ツール、ファームウェアツール、ハードウェアダッシュボードなどをPySide6アプリ内で動かす場合、ページ側から `navigator.usb` が利用できない問題があります。

`pyside6-webusb` はこの部分を補います。

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()

install(view.page())

view.load("https://example.com")
```

通常のアプリケーションでは、ページ作成後に `install()` を一度呼ぶだけでWebUSBポリフィルとブリッジが接続されます。

## インストール

```bash
pip install pyside6-webusb
```

ソースツリーから開発用インストールを行う場合:

```bash
pip install -e .
```

主な依存関係:

- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- OS側のlibusb

Linuxでは、別途 `libusb-1.0` のインストールが必要になる場合があります。

## アーキテクチャ

```text
Webページ
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
USBデバイス
```

Chromium内部のWebUSB実装をそのまま移植したものではありません。

Webページ側にはWebUSB互換のJavaScript APIを提供し、Python側で権限・セキュリティ・デバイス選択などを処理したうえで、pyusb/libusbを通してUSBデバイスへアクセスします。

## API

中心となるAPIは次のとおりです。

```javascript
navigator.usb
```

WebUSBの主要なオブジェクトモデルを扱います。

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

例:

```javascript
const devices = await navigator.usb.getDevices();

console.log(devices);
```

デバイス選択:

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

await device.open();
```

利用可能なデバイスや転送方式は、OS、USBドライバ、libusb、デバイス固有の実装などに依存します。

## セキュリティモデル

`pyside6-webusb` は、Webページへシステム上のUSBデバイスを無制限に公開する設計ではありません。

主な保護機構:

- Originベースのデバイス権限
- ネイティブデバイス選択
- Frame-awareなOrigin帰属
- 保護対象USB Interface Classの拒否
- Chromium由来の既知セキュリティキー・ブロックリスト
- Transferサイズ検証
- Host側の安全上限
- Endpoint / Interface検証
- Native側処理の検証
- 権限済みデバイスのみを対象とする `getDevices()`

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

`getDevices()` は、要求元Originにすでに許可されたデバイスのみを返すことを想定しています。

## WebUSBフィルタ

`requestDevice()` の `filters` / `exclusionFilters` に対応し、Vendor ID、Product ID、Serial Number、Interface Class / Subclass / Protocolなどを利用して候補デバイスを照合します。

フィルタ構造についてもWebUSB仕様に沿った検証を行います。

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

## Transfer

主に次のUSB操作を扱います。

- Control Transfer
- Bulk Transfer
- Interrupt Transfer
- Isochronous Transfer
- Interface Claim / Release
- Alternate Interface
- Endpoint Halt / Clear Halt
- Device Reset
- Open / Close

WebUSBの `stall` や `babble` などのTransfer状態も、可能な範囲でWebUSBの結果モデルへ変換します。

Isochronous Transferにはバックエンドや実機依存の制限が残っています。

## 大容量Transfer

Chrome / Chromiumの実装では32 MiBがTransferサイズの重要な基準値として扱われます。

`pyside6-webusb` はこれを**互換性の参考値**として扱いますが、32 MiBを超えたTransferをChromeと同様に即座に拒否するわけではありません。

代わりに:

- 32 MiB超過時は警告を生成
- DevToolsの `console.warn()` へ通知
- Host側には別の安全上限を適用

という設計です。

したがって:

> **WebUSB-compatible ≠ Chrome clone**

です。

これは仕様との差異を隠さず、互換性とこのプロジェクト独自の実装上の安全性を両立するための意図的な設計です。

## DevTools / F12

ページ側にはデバッグ用の名前空間があります。

```javascript
window.__pysideWebUSB
```

実装状態や環境情報の確認に利用できます。

例:

- Bridge version
- Rust acceleration status
- Transfer limits
- 現在のOriginに許可されたデバイス
- Transfer制限の説明

DevTools / F12のConsoleからWebUSB実装を確認できます。

## ホストアプリからの事前認可

v0.0.5a0では、ホストアプリから特定Originへ特定USBデバイスを事前認可できます。

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

これはキオスク、組み込みアプリなど、許可するOriginとデバイスをホストアプリ側の設定で固定したい場合を想定しています。

この管理用APIはWebページから直接呼び出せるQt Slotとして公開されていません。

## 環境診断

v0.0.5a0では環境診断機能を追加しています。

```python
from pyside6_webusb import (
    environment_report,
    format_environment_report,
)

print(format_environment_report())
```

またはコマンドラインから:

```bash
pyside6-webusb-doctor
```

あるいは:

```bash
python -m pyside6_webusb
```

診断では、例えば次の情報を確認できます。

- Python version
- Python implementation
- PySide6 version
- shiboken6 version
- Qt runtime version
- pyusb version
- 解決されたlibusb backend
- Rust acceleration status
- 検出された問題

Rustアクセラレーションが無効でも、それ自体はエラーではありません。標準Python実装へフォールバックできます。

## Native Acceleration

オプションのRustアクセラレーション層を利用できます。

対象となる処理には:

- Base64 encode / decode
- バイナリ処理
- Pack / Unpack
- Validation helper
- Checksum関連処理

などがあります。

アクセラレーションは必須ではありません。

## TypeScript

WebUSBスタイルAPI向けのTypeScript定義も含まれています。

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

これにより、WebUSB互換APIを型情報付きで利用できます。

## テスト

複数のレイヤーを対象としたテストがあります。

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

自動テストは実機USBデバイスでの検証を完全に置き換えるものではありません。

OS、USBドライバ、libusb、デバイス固有の挙動、Isochronous Transfer、権限処理などは実環境での確認が必要です。

## 現在の状態

**v0.0.5a0 — Early Alpha / Beta-quality experimental release**

v0.0.5a0では、v0.0.4b3までのWebUSB互換実装を基盤として、ホストアプリ向け機能と診断機能を追加しています。

### 実装済み

- [x] `navigator.usb`
- [x] JavaScript WebUSB Polyfill
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
- [x] Host application pre-authorization
- [x] Environment diagnostics
- [x] `pyside6-webusb-doctor`
- [x] TypeScript definitions
- [x] Automated tests

### まだ実験段階

- [ ] 幅広い実機USBデバイスでの検証
- [ ] Isochronous Transferの実機検証
- [ ] 非均一なIsochronous packet lengthへの対応拡張
- [ ] より広いOS / USB driver互換性
- [ ] 長期的なAPI安定化
- [ ] 既存WebUSBアプリケーションとの互換性検証

## Mock-webusbとの関係

`pyside6-webusb` は **Mock-webusb** のPySide6 / QtWebEngine向け実装です。

関連するFirefox向け実装として `fox-webusb` があります。

```text
Mock-webusb
   │
   ├── pyside6-webusb
   │      └── PySide6 / QtWebEngine
   │
   └── fox-webusb
          └── Firefox / Native Messaging
```

これらはChromeの内部WebUSB実装を完全に複製することを目的とするのではなく、WebUSB互換APIを異なるホスト環境へ提供することを目的としています。

## 注意事項

> ⚠️ `pyside6-webusb` は実験的なソフトウェアです。

v0.x系であり、API、互換性、実機サポートは今後変更される可能性があります。

本プロジェクトにはAIによって生成されたコード、またはAIの支援を受けたコードが含まれる場合があります。

そのため、バグ、未完成の挙動、環境依存の問題、互換性の違い、未発見のセキュリティ問題などが存在する可能性があります。

本番環境で使用する場合は、対象OS・USBデバイス・ドライバ・WebUSBアプリケーションを含めて十分に検証してください。

## Related Projects

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

MIT License.
