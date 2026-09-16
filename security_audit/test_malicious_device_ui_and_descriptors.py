# -*- coding: utf-8 -*-
"""脅威モデル: 「悪意ある/侵害されたUSBデバイス自体」が返す文字列記述子
(製品名・製造者名・シリアル番号)や、壊れた/異常な設定記述子を通じた攻撃。

1) UIスプーフィング(CVE-2020-16033『WebUSBにおけるセキュリティUIのスプーフィング
   を許す不適切な実装』と同種のリスク): chooser_dialog.py はデバイス側の文字列
   記述子をそのまま QLabel(textFormat=AutoText がデフォルト)へ渡している。
   hardening.py の safe_error_str() が例外メッセージに対して行っている
   制御文字除去・長さ制限と同等のサニタイズが、デバイス記述子文字列には
   一切適用されていない。

2) CVE-2026-5276 型(『WebUSBにおけるポリシー適用不備によりプロセスメモリの
   一部情報が漏洩』, 2026年4月公表, Chrome 146.0.7680.178で修正)の
   Pythonでの類推確認: 転送が要求より少ないバイト数しか実際に得られなかった
   場合に、レスポンスへ要求サイズ分の(使い回しバッファ由来の余剰/未初期化)
   データが混入しないか。

3) 「悪意あるペリフェラル」によるクラッシュ系CVE(例: Chrome 150.x, macOS,
   悪意あるUSB周辺機器によるuse-after-freeでの任意コード実行)のPythonでの
   類推確認: 壊れた/異常な設定記述子(列挙途中で例外を送出する等)が
   デバイス列挙全体をクラッシュさせないか。
"""
import json

from PySide6.QtGui import Qt as GuiQt

from pyside6_webusb.hardening import build_device_descriptor, safe_error_str
from _fixtures import FakeConfiguration, FakeDevice, FakeEndpoint, FakeInterface, FakeUsbUtil, make_bridge

_CHOOSER_DIALOG_SRC_PATH = __file__.rsplit("/", 2)[0] + "/src/pyside6_webusb/chooser_dialog.py"
with open(_CHOOSER_DIALOG_SRC_PATH, "r", encoding="utf-8") as _f:
    _CHOOSER_DIALOG_SOURCE = _f.read()


# --- 1) UIスプーフィング ---

def test_malicious_product_name_would_be_rendered_as_richtext_by_qt():
    """百聞は一見に如かず: 実際にQtの本物のヒューリスティック
    (Qt::mightBeRichText、QLabelのAutoTextモードが内部で使うのと同じもの)に、
    悪意あるデバイスが製品名として送りうる文字列を通し、リッチテキストと
    誤認識される(=chooser_dialog.pyのQLabelに渡ればHTML風の書式として
    描画されてしまう)ことを実環境で確認する。"""
    malicious_names = [
        "<b>Verified by OS</b>",
        "<span style='color:green'>Trusted Security Key</span>",
        "<img src=x>Not a real device name",
    ]
    for name in malicious_names:
        assert GuiQt.mightBeRichText(name) is True, (
            f"{name!r} が Qt::mightBeRichText() でリッチテキストと判定されなかった"
            "(想定外。テスト対象の見直しが必要)"
        )
    benign_names = ["Acme Widget", "SN-0001-ABCD", "USB 2.0 Hub"]
    for name in benign_names:
        assert GuiQt.mightBeRichText(name) is False, f"{name!r} が誤ってリッチテキスト扱いされている"


def test_chooser_dialog_forces_plain_text_for_device_supplied_strings():
    """chooser_dialog.py のソースが、デバイス提供文字列(製品名・製造者名等)を
    表示するQLabelに対して明示的に setTextFormat(Qt.TextFormat.PlainText) 相当を
    呼んでいる(=AutoTextの誤検出からUIを守っている)ことを確認する。
    現状は一度も呼ばれていないため、このテストはFAILする。"""
    assert "PlainText" in _CHOOSER_DIALOG_SOURCE, (
        "chooser_dialog.py はデバイス提供の文字列(productName/manufacturerName等)を "
        "QLabel のデフォルト textFormat(Qt::AutoText)のまま表示している。"
        "前のテストで確認した通り、'<b>...</b>' のようなHTML風の製品名を持つ"
        "(=安価なプログラマブルUSBデバイスなら誰でも作れる)悪意あるデバイスは、"
        "チューザーダイアログの表示そのものを書式操作で偽装できる"
        "(CVE-2020-16033『WebUSBにおけるセキュリティUIのスプーフィングを許す"
        "不適切な実装』と同種のリスク)。setTextFormat(Qt.TextFormat.PlainText) を"
        "明示するか、表示前に文字列をエスケープ/サニタイズする必要がある。"
    )


def test_device_string_descriptors_are_not_sanitized_unlike_error_messages():
    """hardening.py には例外メッセージ向けの safe_error_str()(制御文字除去・
    長さ上限)が既に存在するが、デバイス記述子文字列(製造者名・製品名・
    シリアル番号)には同等のサニタイズが適用されていないことを確認する。
    デバイス側の文字列はエラーメッセージ以上に完全に攻撃者(デバイス)
    制御下にあるため、本来はより厳格な扱いが必要である。"""
    control_char_payload = "Trusted\r\nDevice\x00Name"
    long_payload = "A" * 200_000

    sanitized_error = safe_error_str(Exception(control_char_payload))
    assert "\r" not in sanitized_error and "\n" not in sanitized_error, (
        "参考として: safe_error_str()自体は制御文字を正しく除去する"
        "(この結果が崩れているならテスト前提が誤り)"
    )

    util = FakeUsbUtil(strings={1: control_char_payload, 2: control_char_payload, 3: "SN"})
    cfg = FakeConfiguration(1, [])
    dev = FakeDevice(0x2341, 0x8036, [cfg], iManufacturer=1, iProduct=2, iSerialNumber=3)
    info = build_device_descriptor(dev, util, include_configurations=False)

    assert "\r" not in (info.get("manufacturerName") or "") and "\n" not in (info.get("manufacturerName") or ""), (
        f"build_device_descriptor() が返した manufacturerName に制御文字が"
        f"そのまま残っている: {info.get('manufacturerName')!r}。"
        "safe_error_str()と同水準の制御文字除去がデバイス記述子文字列には"
        "適用されていない。"
    )

    util_long = FakeUsbUtil(strings={1: long_payload, 2: "Acme Widget", 3: "SN"})
    dev_long = FakeDevice(0x2341, 0x8037, [cfg], iManufacturer=1, iProduct=2, iSerialNumber=3)
    info_long = build_device_descriptor(dev_long, util_long, include_configurations=False)
    assert len(info_long.get("manufacturerName") or "") <= 1000, (
        f"manufacturerName の長さが {len(info_long.get('manufacturerName') or '')} 文字と"
        "無制限に近い。safe_error_str()にはmax_lenによる長さ上限があるが、"
        "デバイス記述子文字列には長さ上限が適用されておらず、極端に長い文字列を"
        "報告するデバイスがチューザーダイアログのレイアウトを乱す/固まらせる"
        "余地がある。"
    )


# --- 2) CVE-2026-5276型: 短い応答時のバッファ汚染確認 ---

def test_short_device_read_does_not_leak_stale_buffer_bytes():
    """デバイスが要求より少ないバイト数しか返さなかった場合(=USBの
    'short packet'。故障気味の実機や、意図的に短く応答する悪意あるデバイスの
    双方で起こりうる)、bulkTransferIn()のレスポンスに実際に受け取った
    バイト数を超えるデータ(=使い回しバッファ由来の余剰/未初期化領域)が
    混入しないことを確認する。CVE-2026-5276『WebUSBにおけるポリシー適用不備に
    よりプロセスメモリの一部情報が漏洩』のPython版アナロジー確認。"""
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [FakeEndpoint(0x81, 0x02)])
    dev = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    dev.short_read_bytes = b"\x01\x02"  # 64バイト要求しても2バイトしか返さない
    bridge = make_bridge([dev])
    bridge._is_granted = lambda origin, vid, pid: True

    open_result = json.loads(bridge.openDevice(0x2341, 0x8036, ""))
    handle = open_result["handle"]
    claim_result = json.loads(bridge.claimInterface(handle, 0, ""))
    assert claim_result["success"] is True, claim_result

    result = json.loads(bridge.bulkTransferIn(handle, 1, 64, ""))
    assert result["success"] is True, result
    import base64
    returned_bytes = base64.b64decode(result["data"])
    assert returned_bytes == b"\x01\x02", (
        f"デバイスは2バイトしか返していないにもかかわらず、応答には "
        f"{len(returned_bytes)} バイトが含まれていた: {returned_bytes!r}。"
        "要求サイズ分のバッファを使い回し、実際に読み取れた分だけを"
        "切り詰めずに返している(=CVE-2026-5276と同種のバッファ/長さ"
        "取り扱い不備)可能性がある。"
    )


# --- 3) 悪意あるペリフェラルによるクラッシュ耐性 ---

def test_enumeration_survives_configuration_iterator_raising_midway():
    """設定記述子の列挙中に例外を送出する(=壊れた/異常なディスクリプタを返す
    悪意あるデバイスを想定した)デバイスが混ざっていても、他の正常なデバイスの
    列挙まで巻き込んでクラッシュしないことを確認する
    (悪意あるペリフェラルによるクラッシュ系CVEのPython版類推確認)。"""

    class ExplodingConfigIterator:
        def __iter__(self):
            raise RuntimeError("simulated malformed/hostile device descriptor")

    def configurations_that_explode_on_iteration():
        return [ExplodingConfigIterator()]

    good_dev = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    evil_dev = FakeDevice(0x9999, 0x0001, configurations_that_explode_on_iteration)
    bridge = make_bridge([good_dev, evil_dev])
    bridge._is_granted = lambda origin, vid, pid: True

    result = json.loads(bridge.listDevices(""))
    assert isinstance(result, dict)
    names = {d.get("vendorId") for d in result.get("devices", [])}
    assert 0x2341 in names, (
        "壊れたデバイス(evil_dev)の列挙中の例外が、正常なデバイス(good_dev)の"
        f"列挙まで巻き込んで失われてしまった: {result!r}"
    )
