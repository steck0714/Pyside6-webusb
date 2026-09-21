# pyside6-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental Alpha — v0.0.5a2**

**PySide6 / QtWebEngine** アプリケーション向けの WebUSB API 実装です。

JavaScript ポリフィル、QWebChannel ブリッジ、**pyusb / libusb** による実USB通信を組み合わせ、QtWebEngine では標準提供されていない `navigator.usb` を提供します。

> GitHub上の開発・リリース表記は `v0.0.5a2` です。PyPI/PEP 440上で実際にパッケージへ入るバージョン文字列は `0.0.5.post3` です。

## 特徴

- WebUSB互換 `navigator.usb`
- 実USBデバイスとの通信
- ネイティブデバイス選択ダイアログ
- Originごとのデバイス権限
- Frame-awareなOrigin処理
- WebUSBセキュリティ保護
- Chromiumの既知セキュリティキー・ブロックリスト
- Transferの検証と安全制限
- WebUSBフィルタ / `exclusionFilters` の照合
- Hotplugの監視と `connect` / `disconnect` イベント
- DevTools / F12向け `window.__pysideWebUSB`
- オプションのRustネイティブアクセラレーション
- ホスト環境診断ユーティリティ
- `pyside6-webusb-doctor`
- JSON形式の環境診断
- ホストアプリからのデバイス事前認可
- TypeScript定義
- WebUSB API互換性を意識したDOMException / Transferモデル

## なぜ必要なのか

PySide6が提供するQtWebEngineはChromiumをベースにしていますが、埋め込み用のQtWebEngineでは通常のChromeブラウザと同じWebUSB機能をそのまま利用できません。

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
    ├── Filter / exclusion filter matching
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
- `requestDevice()` のuser gesture検証
- chooserの再入防止
- 直接QWebChannel呼び出しを考慮したホスト管理APIの保護
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

フィルタ構造についてもPython側で検証します。

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

Isochronous Transferにはバックエンドや実機依存の制限が残っています。

## 大容量Transfer

Chrome / Chromiumの実装では32 MiBがTransferサイズの重要な基準値として扱われます。

`pyside6-webusb` では32 MiB超過をChromeと同様に即座に拒否するのではなく、互換性の差異を明示したうえで警告を出します。

- 32 MiB超過時に `console.warn()` を生成
- DevTools / F12から確認可能
- Host側には512 MiBの安全上限を適用

したがって、

> **WebUSB-compatible ≠ Chrome clone**

です。

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

環境診断:

```python
from pyside6_webusb import (
    environment_report,
    format_environment_report,
)

print(format_environment_report())
```

または:

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

`--json` は `environment_report()` の結果をJSONとして標準出力へ出します。終了コードは通常の診断と同じで、実際の問題がある場合はnon-zeroになります。

診断では、例えば次の情報を確認できます。

- Python version
- Python implementation
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

`pyusb_backend_note` は、pyusbが古い `libusb0` backendへfallbackした場合などに参考情報を示します。

`qtwebengine_importable` は `QtWebEngineCore` / `QtWebEngineWidgets` が実際にimport可能かを個別に確認します。将来のPySide6 6.12系でQtWebEngineが別wheelへ分離された場合にも、原因を診断しやすくするための情報です。

Frame-origin isolationについては、`QWebEngineFrame` が利用できない古いPySide6環境では、より限定的なmain-frame-only動作へfallbackします。診断結果から実際にどのモードが利用されているか確認できます。

## Native Acceleration

オプションのRustアクセラレーション層を利用できます。

主な処理:

- Base64 encode / decode
- バイナリ処理
- ADB wire-protocol message framing helper
- Transfer response JSON construction

Rustアクセラレーションは必須ではありません。利用できない場合はPython実装へfallbackします。

Rust crateはPyO3の `abi3-py39` を使用しており、Python 3.15のような新しいPythonでもABI互換wheelを構築できる構成になっています。

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

このリリースでは、Python tests / security audit / Node polyfill tests / TypeScript checksを含む検証を行っています。

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

このリリースの実行環境では:

**184 passed, 2 skipped**

でした。

また、NodeのpolyfillテストとTypeScript定義のチェックも再実行されています。

ただし、自動テストは実機USBデバイスでの検証を完全に置き換えるものではありません。

## Isochronous Transferについて

Isochronous Transferは実装されていますが、現時点ではbest-effortです。

pyusbの公開APIではIsochronous Transferのper-packet length / result情報を十分に扱えないため、現在の実装には制約があります。

特に `isochronousTransferIn()` のper-packet fidelityについては、pyusb 1.3.1内部のlibusb構造体には各packetの `actual_length` が存在する一方、pyusbの公開 `iso_read()` APIでは合計値としてしか取得できないことを確認しています。

そのため、現時点ではpyusbのprivate internalsへ無理に踏み込んで修正するのではなく、実機検証を伴う将来の改善事項として残しています。

## 現在の状態

**v0.0.5a2 — Experimental Alpha**

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

Chromeの内部WebUSB実装を完全に複製することを目的とするのではなく、WebUSB互換APIを異なるホスト環境へ提供することを目的としています。

Chromeとの意図的な差異は隠さずREADMEやCHANGELOGに記録する方針です。

## 注意事項

> ⚠️ `pyside6-webusb` は実験的なソフトウェアです。

v0.x系であり、API、互換性、実機サポートは今後変更される可能性があります。

本プロジェクトにはAIによって生成されたコード、またはAIの支援を受けたコードが含まれる場合があります。

そのため、バグ、未完成の挙動、環境依存の問題、互換性の違い、未発見のセキュリティ問題などが存在する可能性があります。

本番環境で使用する場合は、対象OS・USBデバイス・ドライバ・WebUSBアプリケーションを含めて十分に検証してください。

## Related Projects

- Mock-webusb
- fox-webusb

## License

MIT License.
