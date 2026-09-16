# security_audit/

`tests/` とは独立した、セキュリティ監査専用のテストスイート。`tests/` が
「現在正しく動いている機能・既知の脆弱性への回帰保護」を検証するのに対し、
このディレクトリは実行環境(Python 3.14.4 / PySide6 6.11.2 / Rust拡張
pyo3 0.27.2)上で実際に動かして初めて確認できる、新規の攻撃面の検証を目的とする。

## 実行方法

```bash
pip install -e ".[dev]"
export QT_QPA_PLATFORM=offscreen   # ヘッドレス環境の場合
pytest security_audit/ -v
```

`tests/` と同様、`conftest.py` がsrc/レイアウトのimportパスとオフスクリーン
フォールバックを自動設定するため、上記だけで動く。

## このスイート特有の設計方針: 「あるべき安全な振る舞い」をassertする

`tests/` 内の既存テストは、正しく直った後のコードに対して書かれており、
現状すべてPASSする。対してこのディレクトリの一部のテストは、**現状のコードに
対して意図的にFAILするように書いてある。** 各テストは「修正後にはこうあって
ほしい」という安全な振る舞いをassertしており、対応する脆弱性がまだ存在する間は
FAILし、bridge.py/hardening.py/chooser_dialog.py側に対応する修正を入れれば、
テストコード自体は一切変更しなくてもPASSに変わるように設計してある
(このプロジェクト自身がCHANGELOGで採用している「直す前は落ちる、直したら
通ることを確認した」という検証スタイルを踏襲した)。

そのため、**このスイートの現在のFAILは「テストが壊れている」のではなく、
「対応する脆弱性がまだ修正されていない」ことを意味する。** 個々のFAILの
詳細な説明・重大度・推奨対応は `../security_report/VULNERABILITY_REPORT.md`
を参照。

一方で、`test_hotplug_gate_checks_top_level_origin_not_receiving_frame` の
ように、単一箇所の修正では閉じられない設計上のトレードオフ(Qt Signalの
配信範囲はフレーム単位に絞れない、等)を対象にしたテストは、現状の挙動を
そのまま裏付ける**証拠(evidence)テストとしてPASSする**形にしてある。
この種のテストはコメントで「証拠テストである」旨を明記している。

## ファイル構成

| ファイル | 対象 |
|---|---|
| `_fixtures.py` | `tests/test_bridge.py` と同形のフェイクpyusbオブジェクト群(共有) |
| `test_altsetting_class_confusion.py` | 【最重要】alternate setting間でのbInterfaceClass混同による保護対象インターフェースクラスの回避 |
| `test_direct_channel_bypass.py` | polyfill.pyを経由しない素のQWebChannel直叩き(ユーザー操作要求・filter構造検証の不在、全Slotへの敵対的引数フラッディング) |
| `test_malicious_device_ui_and_descriptors.py` | 悪意あるUSBデバイスが返す文字列記述子によるUIスプーフィング、短い応答時のバッファ汚染、壊れた記述子への耐性 |
| `test_cross_origin_hotplug_leak.py` | ホットプラグイベントのクロスオリジンブロードキャスト、フレームトークンキャッシュの溢れ耐性 |

## 現在の結果の要約

実環境(Python 3.14.4 / PySide6 6.11.2)での最終実行結果: **80件中14件FAIL、
66件PASS**。FAILの内訳と対応する脆弱性番号は `../security_report/` を参照。
