# -*- coding: utf-8 -*-
"""pyside6_webusb_accel (native/pyside6_webusb_accel/, PyO3拡張) のクロス検証テスト。

このRust拡張はオプショナルなアクセラレーション層であり、ビルドされていなくても
pyside6-webusb本体は完全に動作する(bridge.py側の _b64encode/_b64decode を参照)。
そのため、この拡張がインストールされていない環境でもテストスイート全体は
壊れないよう、モジュール全体を pytest.importorskip でスキップ可能にしてある。

検証内容:
1. Rust実装のbase64エンコード/デコードが、Pythonの標準base64モジュールと
   あらゆるサイズ(0バイト〜WebADB規模の大容量)で完全に一致すること。
2. ADBメッセージヘッダのpack/unpack/verifyが正しく機能し、改ざんを検出できること。
3. 不正な入力(壊れたbase64、長さの違うヘッダ)がクラッシュではなく、
   Python側で捕捉可能な例外として報告されること。
4. (v0.0.4b1) format_transfer_in_success_json()が、bridge.py側のPure Python
   フォールバック経路(_format_transfer_success_json、HAVE_RUST_ACCEL=False時)
   と完全にバイト一致する出力を生成すること — Rustが使えるかどうかで
   ワイヤ上のバイト列が変わってしまわないことの確認。
"""
import base64
import json
import os
import random
import sys

import pytest

accel = pytest.importorskip(
    "pyside6_webusb_accel",
    reason="Rust拡張(pyside6_webusb_accel)は未ビルド。"
           "native/pyside6_webusb_accel/ で `maturin develop` すればこのテストが有効になる。"
           "pyside6-webusb本体はこの拡張なしでも完全に動作する(README参照)。",
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ============================================================
# base64: Rust実装とPython標準ライブラリのクロス検証
# ============================================================

def test_base64_matches_python_stdlib_across_sizes():
    random.seed(20260829)
    sizes = [0, 1, 2, 3, 4, 5, 15, 16, 17, 1000, 65536, 300_000, 600_000]
    for size in sizes:
        data = bytes(random.randrange(256) for _ in range(size))
        rust_encoded = accel.encode_base64(data)
        py_encoded = base64.b64encode(data).decode("ascii")
        assert rust_encoded == py_encoded, f"size={size}: encode不一致"

        rust_decoded = bytes(accel.decode_base64(rust_encoded))
        assert rust_decoded == data, f"size={size}: decode往復で不一致"
    print("test_base64_matches_python_stdlib_across_sizes: OK")


def test_base64_rfc4648_test_vectors():
    """RFC 4648 Section 10 の標準テストベクタ。"""
    cases = [
        (b"", ""),
        (b"f", "Zg=="),
        (b"fo", "Zm8="),
        (b"foo", "Zm9v"),
        (b"foob", "Zm9vYg=="),
        (b"fooba", "Zm9vYmE="),
        (b"foobar", "Zm9vYmFy"),
    ]
    for raw, want in cases:
        assert accel.encode_base64(raw) == want
        assert bytes(accel.decode_base64(want)) == raw
    print("test_base64_rfc4648_test_vectors: OK")


def test_base64_decode_rejects_invalid_input_with_catchable_error():
    with pytest.raises(ValueError):
        accel.decode_base64("this is not valid base64 !!!")
    print("test_base64_decode_rejects_invalid_input_with_catchable_error: OK")


# ============================================================
# ADBメッセージフレーミング
# ============================================================

CNXN = 0x4E584E43
OKAY = 0x5941_4B4F
WRTE = 0x4554_5257


def test_adb_command_name_matches_reference_values():
    # tth0714/adb_client (adb_client/src/device/models/message_commands.rs) を
    # 実際に読んで確認した値(bridge.pyのadb_command_nameコメント/CHANGELOG参照)。
    assert accel.adb_command_name(CNXN) == "CNXN"
    assert accel.adb_command_name(OKAY) == "OKAY"
    assert accel.adb_command_name(WRTE) == "WRTE"
    assert accel.adb_command_name(0xDEADBEEF) is None
    print("test_adb_command_name_matches_reference_values: OK")


def test_adb_header_pack_unpack_round_trip():
    data = b"pyside6-webusb ADB framing test payload"
    header = accel.adb_pack_header(CNXN, 0x01000000, 256 * 1024, data)
    assert len(header) == 24

    command, arg0, arg1, data_length, data_crc32, magic = accel.adb_unpack_header(header)
    assert command == CNXN
    assert arg0 == 0x01000000
    assert arg1 == 256 * 1024
    assert data_length == len(data)
    assert data_crc32 == accel.adb_checksum(data)
    assert magic == (command ^ 0xFFFFFFFF)
    assert accel.adb_verify_header(command, magic, data, data_crc32) is True
    print("test_adb_header_pack_unpack_round_trip: OK")


def test_adb_header_verify_detects_tampering():
    data = b"original payload"
    header = accel.adb_pack_header(WRTE, 1, 2, data)
    command, _arg0, _arg1, _len, data_crc32, magic = accel.adb_unpack_header(header)
    assert accel.adb_verify_header(command, magic, data, data_crc32) is True
    # データを1バイトでも変えれば検出できるはず
    assert accel.adb_verify_header(command, magic, b"tampered payload", data_crc32) is False
    print("test_adb_header_verify_detects_tampering: OK")


def test_adb_unpack_header_rejects_wrong_length():
    with pytest.raises(ValueError):
        accel.adb_unpack_header(b"\x00" * 23)
    with pytest.raises(ValueError):
        accel.adb_unpack_header(b"\x00" * 25)
    print("test_adb_unpack_header_rejects_wrong_length: OK")


def test_adb_checksum_is_sum_not_real_crc32():
    """ADBの「data_crc32」フィールドは、名前に反して本物のCRC32ではなく単純な
    バイト総和(mod 2^32)である。実際に動作する参照実装から確認した事実
    (bridge.pyのCHANGELOG/コメント参照)なので、それがそのまま再現されている
    ことを明示的に確認しておく(勘違いして本物のCRC32に"修正"してしまう将来の
    回帰を防ぐため)。"""
    data = bytes([1, 2, 3, 4, 5])
    assert accel.adb_checksum(data) == 15  # 1+2+3+4+5

    import zlib
    real_crc32 = zlib.crc32(data)
    assert accel.adb_checksum(data) != real_crc32, (
        "ADBのdata_crc32は単純総和のはずで、本物のCRC32とは一致しないはず"
    )
    print("test_adb_checksum_is_sum_not_real_crc32: OK")


# ============================================================
# 🚚 v0.0.4b1: 転送成功レスポンスJSON組み立ての高速化
# ============================================================

def test_format_transfer_in_success_json_matches_python_json_dumps():
    """format_transfer_in_success_json()の出力が、
    json.dumps({"success": True, "status": ..., "data": base64(...)},
    separators=(",", ":")) と完全にバイト一致することを、複数サイズで確認する。
    一致していれば、JSON.parse()する側(polyfill.py)からは常に同じ内容が
    見えることになる。"""
    random.seed(20260830)
    for size in [0, 1, 16, 1000, 300_000]:
        data = bytes(random.randrange(256) for _ in range(size))
        for status in ["ok", "stall", "babble"]:
            rust_json = accel.format_transfer_in_success_json(status, data)
            python_json = json.dumps(
                {"success": True, "status": status, "data": base64.b64encode(data).decode("ascii")},
                separators=(",", ":"),
            )
            assert rust_json == python_json, f"size={size} status={status}: 不一致"
            # 構文的に妥当なJSONであり、パース結果も期待どおりであること
            parsed = json.loads(rust_json)
            assert parsed == {"success": True, "status": status, "data": base64.b64encode(data).decode("ascii")}
    print("test_format_transfer_in_success_json_matches_python_json_dumps: OK")


def test_bridge_format_transfer_success_json_wrapper_matches_rust_and_python_paths():
    """bridge.py側のラッパー(_format_transfer_success_json)が、
    HAVE_RUST_ACCELの真偽どちらでも同一のバイト列を返すことを確認する
    (=Rust拡張の有無でワイヤフォーマットが変わらないことの、実際に配線
    されているbridge.py経由での確認。test_format_transfer_in_success_json_
    matches_python_json_dumps はRust関数を直接叩く下位レベルの確認)。"""
    from pyside6_webusb import bridge as bridge_module
    data = bytes(range(200)) * 500  # 100KB程度、Rustパスもチャンク相当を通る

    original = bridge_module.HAVE_RUST_ACCEL
    try:
        bridge_module.HAVE_RUST_ACCEL = True
        with_rust = bridge_module._format_transfer_success_json("ok", data)
        bridge_module.HAVE_RUST_ACCEL = False
        without_rust = bridge_module._format_transfer_success_json("ok", data)
    finally:
        bridge_module.HAVE_RUST_ACCEL = original

    assert with_rust == without_rust
    assert json.loads(with_rust)["data"] == base64.b64encode(data).decode("ascii")
    print("test_bridge_format_transfer_success_json_wrapper_matches_rust_and_python_paths: OK")
