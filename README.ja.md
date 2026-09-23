# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Beta — v0.0.5b1**

**PySide6 / QtWebEngine** アプリケーション向けの WebUSB API 実装です。

JavaScript WebUSB Polyfill、QWebChannel Bridge、**pyusb / libusb** による実USB通信を組み合わせ、QtWebEngine では通常利用できない `navigator.usb` を提供します。

> GitHub上の開発表記は `v0.0.5b1` です。PyPI / PEP 440で実際にパッケージへ入るバージョン文字列は `0.0.5.post5` です。

## 特徴

- WebUSB互換 `navigator.usb`
- 実USBデバイスとの通信
- ネイティブデバイス選択ダイアログ
- Originごとのデバイス権限
- Frame-awareなOrigin処理
- WebUSBセキュリティ保護
- Chromium由来の既知セキュリティキー・ブロックリスト
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

## なぜ必要なのか

PySide6のQtWebEngineはChromiumをベースにしていますが、埋め込み用のQtWebEngineでは通常のChrome/Chromiumブラウザシェルと同じWebUSB機能をそのまま利用できません。

WebUSBを必要とするデバイス設定ツール、ファームウェアツール、ハードウェアダッシュボードなどをPySide6アプリ内で動かす場合、ページ側から `navigator.usb` が利用できない問題があります。

`pyside6-webusb` はこの部分を補います。

## Quick Start

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())
view.load("https://your-site.example")
```

通常のアプリケーションでは、ページ作成後に `install()` を一度呼ぶだけでWebUSB PolyfillとBridgeが接続されます。

## インストール

```bash
pip install pyside6-webusb
```

ソースツリーから開発用インストールを行う場合:

```bash
pip install -e .
```

主な依存関係:

- Python >= 3.9
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

Chromium内部のWebUSB実装をそのまま移植したものではありません。

Webページ側にはWebUSB互換のJavaScript APIを提供し、Python側で権限・セキュリティ・デバイス選択などを処理したうえで、pyusb/libusbを通してUSBデバイスへアクセスします。

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

デバイス選択:

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

await device.open();
```

実際に利用できるデバイスや転送方式は、OS、USBドライバ、libusb、デバイス固有の実装などに依存します。

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
- `requestDevice()` のuser gesture検証
- chooserの再入防止
- Webページから直接QWebChannelを利用したHost-only管理APIの迂回防止
- デバイス由来文字列のサニタイズ
- HotplugイベントのOrigin単位での可視性確認
- Originごとの同時open handle数制限

8種類の保護対象Interface Class（Audio、HID、Mass Storage、Hub、Smart Card、Video、Audio/Video、Wireless Controller）を拒否します。

また、`claimInterface()` だけでなく、Transfer、`clearHalt()`、`selectAlternateInterface()` などから保護対象Interfaceを迂回できないよう検証します。

## WebUSBフィルタ

`requestDevice()` の `filters` / `exclusionFilters` に対応し、Vendor ID、Product ID、Serial Number、Interface Class / Subclass / Protocolなどを利用して候補デバイスを照合します。

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

フィルタ構造についてもPython側で型・値域を検証します。

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

`stall` や `babble` などのTransfer状態も、可能な範囲でWebUSBの結果モデルへ変換します。

Isochronous Transferは実装されていますが、per-packet情報についてはpyusb公開APIの制約があり、現時点ではbest-effortです。

## 大容量Transfer

Chrome / Chromiumでは32 MiBがTransferサイズの重要な基準値として扱われます。

`pyside6-webusb` では32 MiB超過をChromeと同様に即座に拒否するのではなく、この互換性差異を明示します。

- 32 MiB超過時に `console.warn()` を生成
- DevTools / F12から確認可能
- Host側には512 MiBの安全上限を適用

したがって、

> **WebUSB-compatible ≠ Chrome clone**

です。

Chromeとの意図的な差異はREADMEやCHANGELOGに記録する方針です。

## DevTools / F12

ページ側には次のデバッグ用名前空間があります。

```javascript
window.__pysideWebUSB
```

主な機能:

```javascript
window.__pysideWebUSB.listGrantedDevices()
window.__pysideWebUSB.bridgeInfo()
window.__pysideWebUSB.explainTransferLimits()
```

`bridgeInfo()` では、Bridge version、Rust accelerationの状態、Transfer制限などを確認できます。

## ホストアプリからの事前認可

ホストアプリから特定Originへ特定USBデバイスを事前認可できます。

```python
bridge = install(view.page())

bridge.grant_device_for_origin(
    "https://kiosk.example",
    vendor_id=0x2341,
    product_id=0x8036,
)
```

キオスク、組み込みアプリなど、許可するOriginとデバイスをホスト側の設定で固定したい場合を想定しています。

この管理用メソッドはWebページから直接呼び出せるQt Slotとして公開されていません。

## 環境診断

Pythonから:

```python
from pyside6_webusb import (
    environment_report,
    format_environment_report,
)

print(format_environment_report())
```

コマンドラインから:

```bash
pyside6-webusb-doctor
```

または:

```bash
python -m pyside6_webusb
```

JSON形式:

```bash
pyside6-webusb-doctor --json
```

```bash
python -m pyside6_webusb --json
```

診断では、例えば次の情報を確認できます。

- Python version / implementation
- PySide6 version
- shiboken6 version
- Qt runtime version
- pyusb version
- 解決されたlibusb backend
- `pyusb_backend_note`
- `qtwebengine_importable`
- Frame-origin isolationの利用可能性
- Rust acceleration status
- 検出された問題

`qtwebengine_importable` は `QtWebEngineCore` / `QtWebEngineWidgets` が実際にimport可能かを確認します。

Frame-origin isolationについては、利用可能なPySide6 APIに応じて適切なモードを選択し、診断結果から実際の状態を確認できます。

## Native Acceleration

オプションのRustアクセラレーション層を利用できます。

主な処理:

- Base64 encode / decode
- バイナリ処理
- ADB wire-protocol message framing helper
- Transfer response JSON construction

Rustアクセラレーションは必須ではありません。利用できない場合はPython実装へfallbackします。

Rust crateはPyO3の `abi3-py39` を使用する構成になっており、新しいPython向けにもABI互換wheelを構築しやすい設計です。

## TypeScript

`types/webusb-polyfill.d.ts` にWebUSB API向けのTypeScript定義を含みます。

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

`types/sample-usage.ts` と `types/negative-check.ts` も含まれ、正常な利用と型エラーの両方を確認できます。

## テスト

このリリースでは、Python tests / security audit / Node polyfill tests / TypeScript checks / Rust testsを含む検証を行っています。

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

自動テストは実機USBデバイスでの検証を完全に置き換えるものではありません。特にIsochronous Transferについては実機検証が残っています。

## Isochronous Transferについて

Isochronous Transferは実装されていますが、現時点ではbest-effortです。

pyusbの公開APIではIsochronous Transferのper-packet length / result情報を十分に扱えません。

pyusb 1.3.1の内部libusb構造には各packetの `actual_length` が存在する一方、公開 `iso_read()` APIでは合計値としてしか取得できないため、現在の実装ではprivate internalsへ無理に依存せず、この制約を既知の制限として扱っています。

実機でのper-packet fidelity検証と、非均一packet lengthへの対応拡張は今後の課題です。

## 現在の状態

**v0.0.5b1 — Experimental Beta**

### 実装済み

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

### まだ実験段階

- [ ] 幅広い実機USBデバイスでの検証
- [ ] Isochronous Transferの実機検証
- [ ] 非均一Isochronous packet lengthへの対応拡張
- [ ] より広いOS / USB driver互換性
- [ ] 長期的なAPI安定化
- [ ] 既存WebUSBサイトとの互換性検証

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

Chromeの内部WebUSB実装を完全に複製することを目的とするのではなく、異なるホスト環境へWebUSB互換APIを提供することを目的としています。

Chromeとの意図的な差異は隠さずREADMEやCHANGELOGに記録します。

## 注意事項

> ⚠️ `pyside6-webusb` は実験的なソフトウェアです。

v0.x系であり、API、互換性、実機サポートは今後変更される可能性があります。

本プロジェクトにはAIによって生成されたコード、またはAIの支援を受けたコードが含まれる場合があります。

そのため、バグ、未完成の挙動、環境依存の問題、互換性の違い、未発見のセキュリティ問題などが存在する可能性があります。

本番環境で使用する場合は、対象OS・USBデバイス・ドライバ・libusb・WebUSBアプリケーションを含めて十分に検証してください。

## Related Projects

- [Mock-webusb](https://github.com/steck0714/Mock-webusb)
- [fox-webusb](https://github.com/steck0714/fox-webusb)

## License

[MIT License](https://github.com/steck0714/Mock-webusb/blob/main/LICENSE)
