# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Beta — v0.0.5b2**

**PySide6 / QtWebEngine** アプリケーション向けの WebUSB API 実装です。

JavaScript WebUSB Polyfill、QWebChannel Bridge、**pyusb / libusb** による実USB通信を組み合わせ、QtWebEngine では通常利用できない `navigator.usb` を提供します。

> GitHub上の開発・リリース表記は `v0.0.5b2` です。PyPI / PEP 440で実際にパッケージへ入るバージョン文字列は `0.0.5.post6` です。

## 特徴

- WebUSB互換 `navigator.usb`
- 実USBデバイスとの通信
- ネイティブデバイス選択ダイアログ
- Originごとのデバイス権限
- Frame-awareなOrigin処理
- WebUSBセキュリティ保護
- Chromiumの既知セキュリティキー・ブロックリスト
- Transferの検証と安全制限
- WebUSB `filters` / `exclusionFilters` の照合
- Hotplug監視と `connect` / `disconnect` イベント
- DevTools / F12向け `window.__pysideWebUSB`
- オプションのRustネイティブアクセラレーション
- ホスト環境診断ユーティリティ
- `pyside6-webusb-doctor`
- JSON形式の環境診断
- ホストアプリからのデバイス事前認可
- TypeScript定義
- WebUSB互換のDOMException / Transferモデル
- Virtual USB backend / Virtual USB deviceによるテスト支援

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://example.com")
```

## インストール

```bash
pip install pyside6-webusb
```

開発用:

```bash
pip install -e .
```

主な依存関係:

- Python >= 3.9
- PySide6-Essentials >= 6.5
- PySide6-Addons >= 6.5
- pyusb >= 1.2.1
- OS側のlibusb

## アーキテクチャ

```text
Webページ
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
USBデバイス
```

Chromium内部のWebUSB実装をそのまま移植したものではありません。Webページ側にはWebUSB互換APIを提供し、Python側で権限・セキュリティ・デバイス選択などを処理します。

## API

中心となるAPI:

```javascript
navigator.usb
```

主なオブジェクト:

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

```javascript
const device = await navigator.usb.requestDevice({
    filters: [{ vendorId: 0x1234 }]
});
await device.open();
```

## セキュリティモデル

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
- `requestDevice()` のユーザー操作検証
- chooserの再入防止
- Host-only管理APIへの直接通信経路の迂回対策
- デバイス由来文字列のサニタイズ
- HotplugイベントのOrigin単位での可視性確認
- Originごとの同時open handle数制限

## WebUSBフィルタ

`requestDevice()` の `filters` / `exclusionFilters` に対応します。

```javascript
const device = await navigator.usb.requestDevice({
    filters: [{ vendorId: 0x1234, productId: 0x5678 }]
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

Isochronous Transferは実装されていますが、バックエンドや実機に依存する制約があります。

## 大容量Transfer

Chrome / Chromiumでは32 MiBが重要なTransferサイズ基準です。

`pyside6-webusb` では32 MiB超過を即座に拒否せず、互換性差異を明示します。

- 32 MiB超過時に `console.warn()` を生成
- DevTools / F12から確認可能
- Host側には512 MiBの安全上限

> **WebUSB-compatible ≠ Chrome clone**

## DevTools / F12

```javascript
window.__pysideWebUSB
```

Bridge情報、権限済みデバイス状態、Transfer制限などを確認できます。

## ホストアプリからの事前認可

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

## 環境診断

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

オプションのRustアクセラレーション層を利用できます。

- Base64 encode / decode
- バイナリ処理
- ADB wire-protocol message framing helper
- Transfer response JSON construction

利用できない場合はPythonへfallbackします。Rust crateはPyO3 `abi3-py39` を使用します。

## TypeScript

`types/webusb-polyfill.d.ts` にWebUSB API向けのTypeScript定義を含みます。

## Virtual USB

テスト支援用としてVirtual USB backend / Virtual USB deviceを提供します。

```python
from pyside6_webusb.virtual import VirtualUsbDevice
```

## テスト

Python tests、security audit、Node/polyfill tests、TypeScript checks、Rust testsなどを含みます。

```text
184 passed, 2 skipped
```

自動テストは実機USBデバイスでの検証を完全には置き換えません。

## Isochronous Transfer

Isochronous Transferはbest-effortです。

pyusbの公開APIではper-packet length / result情報を十分に扱えないため、特にIN Transferのper-packet fidelityに既知の制約があります。

## 現在の状態

**v0.0.5b2 — Experimental Beta**

### 実装済み

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

### まだ実験段階

- [ ] 幅広い実機USBデバイスでの検証
- [ ] Isochronous Transferの実機検証
- [ ] 非均一Isochronous packet lengthへの対応拡張
- [ ] より広いOS / USB driver互換性
- [ ] 長期的なAPI安定化
- [ ] 既存WebUSBサイトとの互換性検証

## Mock-webusbとの関係

`pyside6-webusb` は **Mock-webusb** のPySide6 / QtWebEngine向け実装です。

```text
Mock-webusb
   │
   ├── pyside6-webusb
   │      └── PySide6 / QtWebEngine
   │
   └── fox-webusb
          └── Firefox / Native Messaging
```

Chromeの内部WebUSB実装を完全に複製することではなく、異なるHost環境へWebUSB互換APIを提供することを目的としています。

## 注意事項

> ⚠️ `pyside6-webusb` は実験的なソフトウェアです。

v0.x系であり、API、互換性、実機サポートは今後変更される可能性があります。

本プロジェクトにはAIによって生成されたコード、またはAIの支援を受けたコードが含まれる場合があります。

バグ、未完成の挙動、環境依存の問題、互換性の違い、未発見のセキュリティ問題などが存在する可能性があります。

本番環境で使用する場合は、対象OS・USBデバイス・ドライバ・libusb・WebUSBアプリケーションを含めて十分に検証してください。

## License

MIT License
