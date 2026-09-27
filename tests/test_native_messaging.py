# -*- coding: utf-8 -*-
"""native_messaging.py (🆕 v0.0.6) のテスト。

fox-webusb(Firefox WebExtension + 独立したnative messagingホストプロセスで
navigator.usbのポリフィルを実現する姉妹プロジェクト)を調査した上で、その
「native codeでnavigator.usbが機能しているように見せる」方式のうち、
(1) Chrome/Firefox共通のワイヤフォーマット(read_message/write_message)、
(2) manifest.json単体の静的チェッカー、の2つをpyside6-webusb側にも
取り入れたもの。詳細はnative_messaging.pyのモジュールdocstring参照。

PySide6を一切importしないモジュールなので、このテストファイル自体も
PySide6無しで完結する(QApplication等のセットアップが不要)。
"""
import io
import json
import os
import stat
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pyside6_webusb.i18n import NATIVE_MESSAGING_STRINGS, SUPPORTED_LOCALES  # noqa: E402
from pyside6_webusb.native_messaging import (  # noqa: E402
    NativeMessagingError,
    format_manifest_check,
    read_message,
    validate_native_messaging_manifest,
    write_message,
)


def test_every_supported_locale_has_the_same_native_messaging_keys():
    """i18n.pyのLOG_STRINGS/DIAGNOSTICS_STRINGSと同じ構造チェック
    (test_i18n.pyのtest_every_supported_locale_has_the_same_log_keys等参照)。"""
    key_sets = {locale: set(strings.keys()) for locale, strings in NATIVE_MESSAGING_STRINGS.items()}
    assert set(NATIVE_MESSAGING_STRINGS.keys()) == set(SUPPORTED_LOCALES)
    reference = key_sets["en"]
    for locale, keys in key_sets.items():
        assert keys == reference, f"locale {locale!r} mismatched keys: {keys ^ reference}"
    print("test_every_supported_locale_has_the_same_native_messaging_keys: OK")


def test_write_then_read_message_round_trips():
    """write_message()が書いたものをread_message()がそのまま読み戻せること
    (4byte長プレフィックス+UTF-8 JSONというワイヤフォーマットの基本)。
    非ASCII(日本語)を含むペイロードも正しく往復することを確認する。"""
    buf = io.BytesIO()
    payload = {"hello": "world", "日本語": True, "n": 12345, "nested": {"a": [1, 2, 3]}}
    write_message(buf, payload)
    buf.seek(0)
    assert read_message(buf) == payload
    print("test_write_then_read_message_round_trips: OK")


def test_read_message_returns_none_on_clean_stream_end():
    """ストリームが最初の4byteすら返さず終端した場合(=ブラウザ側がパイプを
    閉じた、拡張機能のアンインストール等による正常な切断)はNoneを返す。
    例外にはしない——ホスト側の通常の終了ループの条件に使える設計。"""
    assert read_message(io.BytesIO(b"")) is None
    print("test_read_message_returns_none_on_clean_stream_end: OK")


def test_read_message_handles_multiple_sequential_messages():
    """1本のストリームに複数メッセージを続けて書いても、それぞれ独立して
    正しく読み出せる(native messagingホストの実際の使い方: ループでread_message
    を呼び続ける)。"""
    buf = io.BytesIO()
    write_message(buf, {"seq": 1})
    write_message(buf, {"seq": 2})
    buf.seek(0)
    assert read_message(buf) == {"seq": 1}
    assert read_message(buf) == {"seq": 2}
    assert read_message(buf) is None
    print("test_read_message_handles_multiple_sequential_messages: OK")


def test_write_message_rejects_oversized_payload():
    try:
        write_message(io.BytesIO(), {"x": "a" * 100}, max_bytes=10)
        raise AssertionError("サイズ超過なのに例外が飛ばなかった")
    except NativeMessagingError:
        pass
    print("test_write_message_rejects_oversized_payload: OK")


def test_read_message_rejects_oversized_length_prefix():
    """相手が(悪意・バグにより)実際には送らない巨大な長さを名乗った場合、
    その分のペイロードを律儀に読もうとして無限にブロックする前に
    早期にエラーにする。"""
    buf = io.BytesIO(struct.pack("=I", 999_999_999))
    try:
        read_message(buf, max_bytes=1024 * 1024)
        raise AssertionError("巨大な長さプレフィックスなのに例外が飛ばなかった")
    except NativeMessagingError:
        pass
    print("test_read_message_rejects_oversized_length_prefix: OK")


def test_read_message_rejects_mid_message_truncation():
    """長さプレフィックスが約束した分より少ないバイト数でストリームが
    途切れた場合(=通信が壊れた)、不完全なメッセージを黙って握りつぶさず
    エラーにする(read_message()がNoneを返す「クリーンな終端」との違いは
    「1byteも読めていないか」どうかで区別する設計)。"""
    buf = io.BytesIO(struct.pack("=I", 100) + b"short")
    try:
        read_message(buf)
        raise AssertionError("途中切断なのに例外が飛ばなかった")
    except NativeMessagingError:
        pass
    print("test_read_message_rejects_mid_message_truncation: OK")


def _write_manifest(directory, **overrides):
    data = {
        "name": "com.example.fox_webusb_host",
        "description": "test host",
        "path": "host.py",
        "type": "stdio",
        "allowed_extensions": ["fox-webusb@example.com"],
    }
    data.update(overrides)
    manifest_path = os.path.join(directory, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return manifest_path


def test_validate_manifest_accepts_a_well_formed_manifest():
    with tempfile.TemporaryDirectory() as d:
        host_path = os.path.join(d, "host.py")
        with open(host_path, "w") as f:
            f.write("# host\n")
        os.chmod(host_path, 0o755)
        manifest_path = _write_manifest(d)
        problems, warnings = validate_native_messaging_manifest(manifest_path)
        assert problems == [], problems
        assert warnings == [], warnings
    print("test_validate_manifest_accepts_a_well_formed_manifest: OK")


def test_validate_manifest_accepts_an_already_loaded_dict():
    """ファイルパスだけでなく、既に読み込み済みのdictも直接渡せる
    (呼び出し元が既にJSONを読んでいる場合に二重に読み直させない)。
    ただしdict渡しの場合はpathの相対解決の基準ディレクトリが無いため、
    相対pathは(base_dir=Noneのまま)カレントディレクトリ基準になる——
    このテストでは絶対パスを使ってその違いを避ける。"""
    with tempfile.TemporaryDirectory() as d:
        host_path = os.path.join(d, "host.py")
        with open(host_path, "w") as f:
            f.write("# host\n")
        os.chmod(host_path, 0o755)
        problems, warnings = validate_native_messaging_manifest({
            "name": "com.example.host", "description": "d", "path": host_path,
            "type": "stdio", "allowed_origins": ["chrome-extension://abc/"],
        })
        assert problems == [], problems
    print("test_validate_manifest_accepts_an_already_loaded_dict: OK")


def test_validate_manifest_reports_missing_required_keys():
    problems, _ = validate_native_messaging_manifest({"name": "x"})
    joined = " ".join(problems)
    for key in ("description", "path", "type"):
        assert key in joined, f"'{key}'の欠落が報告に含まれるはず: {problems}"
    print("test_validate_manifest_reports_missing_required_keys: OK")


def test_validate_manifest_rejects_unsupported_type():
    with tempfile.TemporaryDirectory() as d:
        manifest_path = _write_manifest(d, type="websocket")
        problems, _ = validate_native_messaging_manifest(manifest_path)
        assert any("websocket" in p or "stdio" in p for p in problems), problems
    print("test_validate_manifest_rejects_unsupported_type: OK")


def test_validate_manifest_flags_missing_path_and_resolves_relative_paths():
    """pathが存在しない場合は問題として報告し、相対pathはmanifest自身の
    ディレクトリを基準に解決する(実際のブラウザの解決規則と同じ——
    validate_native_messaging_manifest()のdocstring参照)。"""
    with tempfile.TemporaryDirectory() as d:
        manifest_path = _write_manifest(d, path="no_such_host.py")
        problems, _ = validate_native_messaging_manifest(manifest_path)
        assert len(problems) == 1
        assert "no_such_host.py" in problems[0]
    print("test_validate_manifest_flags_missing_path_and_resolves_relative_paths: OK")


def test_validate_manifest_warns_on_non_executable_path():
    if os.name == "nt":
        print("test_validate_manifest_warns_on_non_executable_path: SKIP (Windowsではos.access(X_OK)が実行可否を正しく反映しない)")
        return
    with tempfile.TemporaryDirectory() as d:
        host_path = os.path.join(d, "host.py")
        with open(host_path, "w") as f:
            f.write("# host\n")
        os.chmod(host_path, stat.S_IRUSR | stat.S_IWUSR)  # 実行ビット無し
        manifest_path = _write_manifest(d)
        problems, warnings = validate_native_messaging_manifest(manifest_path)
        assert problems == [], problems
        assert len(warnings) == 1
    print("test_validate_manifest_warns_on_non_executable_path: OK")


def test_validate_manifest_requires_allowed_origins_or_extensions():
    with tempfile.TemporaryDirectory() as d:
        host_path = os.path.join(d, "host.py")
        open(host_path, "w").close()
        os.chmod(host_path, 0o755)
        manifest_path = _write_manifest(d, allowed_extensions=[])
        problems, _ = validate_native_messaging_manifest(manifest_path)
        assert len(problems) == 1, problems

        # allowed_originsだけでも(Chrome形式)十分。
        manifest_path2 = os.path.join(d, "manifest2.json")
        with open(manifest_path2, "w", encoding="utf-8") as f:
            json.dump({
                "name": "com.example.host", "description": "d", "path": "host.py",
                "type": "stdio", "allowed_origins": ["chrome-extension://abc/"],
            }, f)
        problems2, _ = validate_native_messaging_manifest(manifest_path2)
        assert problems2 == [], problems2
    print("test_validate_manifest_requires_allowed_origins_or_extensions: OK")


def test_validate_manifest_reports_invalid_json_and_non_object():
    with tempfile.TemporaryDirectory() as d:
        bad_path = os.path.join(d, "bad.json")
        with open(bad_path, "w") as f:
            f.write("{not valid json")
        problems, _ = validate_native_messaging_manifest(bad_path)
        assert len(problems) == 1

    problems2, _ = validate_native_messaging_manifest([1, 2, 3])
    assert len(problems2) == 1

    problems3, _ = validate_native_messaging_manifest("/no/such/path/manifest.json")
    assert len(problems3) == 1
    print("test_validate_manifest_reports_invalid_json_and_non_object: OK")


def test_manifest_not_an_object_message_shows_literal_braces_not_escaped_ones():
    """🐛 バグ修正の回帰テスト(v0.0.6)。

    NATIVE_MESSAGING_STRINGS["manifest_not_an_object"]はkwargsを一切
    受け取らないメッセージだが、説明文中でリテラルの中括弧 '{...}' を
    示すために str.format() のエスケープ記法 '{{...}}' を使っている。
    以前のi18n.diagnostics_text/log_text/native_messaging_textは
    `text.format(**kwargs) if kwargs else text` としてkwargsが空の場合に
    format()自体を呼ばずtextをそのまま返していたため、このエスケープが
    一切解決されず、出力に'{{...}}'という2重の中括弧がそのまま出てしまって
    いた(実際に発生を確認した上で、kwargsの有無に関わらず常にformat()を
    呼ぶよう修正した)。"""
    problems, _ = validate_native_messaging_manifest([1, 2, 3])
    assert len(problems) == 1
    assert "{{" not in problems[0] and "}}" not in problems[0], problems[0]
    assert "{...}" in problems[0], problems[0]
    print("test_manifest_not_an_object_message_shows_literal_braces_not_escaped_ones: OK")


def test_format_manifest_check_reuses_diagnostics_headers_across_locales():
    """format_manifest_check()の見出し("問題を検出しました"/"問題なし")は
    diagnostics.pyの既存文言をそのまま再利用している(別の言い回しを
    3言語ぶん新たに用意する意味が無いため)ことを、3ロケールすべてで
    確認する。"""
    ok_problems, ok_warnings = [], []
    for locale, expect_no_problems_substr in [("en", "No problems detected."),
                                               ("ja", "問題は検出されませんでした。"),
                                               ("zh", "未检测到问题。")]:
        text = format_manifest_check("manifest.json", ok_problems, ok_warnings, locale=locale)
        assert expect_no_problems_substr in text, (locale, text)

    bad_problems = ["something is wrong"]
    for locale, expect_header_substr in [("en", "Problems detected:"),
                                          ("ja", "検出された問題:"),
                                          ("zh", "检测到的问题:")]:
        text = format_manifest_check("manifest.json", bad_problems, [], locale=locale)
        assert expect_header_substr in text, (locale, text)
        assert "something is wrong" in text
    print("test_format_manifest_check_reuses_diagnostics_headers_across_locales: OK")


def test_cli_check_native_messaging_flag_end_to_end(capsys):
    """python -m pyside6_webusb --check-native-messaging <path> の統合確認
    (__main__.main()を直接呼ぶ)。--jsonと--langの組み合わせ、および
    問題の有無に応じた終了コード(1/0)も合わせて確認する。"""
    from pyside6_webusb.__main__ import main

    with tempfile.TemporaryDirectory() as d:
        host_path = os.path.join(d, "host.py")
        with open(host_path, "w") as f:
            f.write("# host\n")
        os.chmod(host_path, 0o755)
        good_manifest = _write_manifest(d)

        rc = main(["--check-native-messaging", good_manifest, "--lang", "en"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "No problems detected." in out

        bad_manifest = _write_manifest(d, type="websocket")
        # 🔍 _write_manifest()は同じディレクトリの"manifest.json"を毎回
        # 上書きするため、good_manifestとbad_manifestは実際には同じパス。
        rc2 = main(["--check-native-messaging", bad_manifest, "--lang", "ja", "--json"])
        parsed = json.loads(capsys.readouterr().out)
        assert rc2 == 1
        assert parsed["path"] == bad_manifest
        assert len(parsed["problems"]) >= 1
    print("test_cli_check_native_messaging_flag_end_to_end: OK")


if __name__ == "__main__":
    test_every_supported_locale_has_the_same_native_messaging_keys()
    test_write_then_read_message_round_trips()
    test_read_message_returns_none_on_clean_stream_end()
    test_read_message_handles_multiple_sequential_messages()
    test_write_message_rejects_oversized_payload()
    test_read_message_rejects_oversized_length_prefix()
    test_read_message_rejects_mid_message_truncation()
    test_validate_manifest_accepts_a_well_formed_manifest()
    test_validate_manifest_accepts_an_already_loaded_dict()
    test_validate_manifest_reports_missing_required_keys()
    test_validate_manifest_rejects_unsupported_type()
    test_validate_manifest_flags_missing_path_and_resolves_relative_paths()
    test_validate_manifest_warns_on_non_executable_path()
    test_validate_manifest_requires_allowed_origins_or_extensions()
    test_validate_manifest_reports_invalid_json_and_non_object()
    test_manifest_not_an_object_message_shows_literal_braces_not_escaped_ones()
    test_format_manifest_check_reuses_diagnostics_headers_across_locales()

    class _FakeCapsys:
        """pytestなしで走らせる場合のcapsysの簡易代役。標準出力をStringIOへ
        差し替えて溜め、readouterr().outで取り出せるようにするだけの
        最小限の実装。"""
        def __init__(self):
            import io as _io
            self._buf = _io.StringIO()
            self._real_stdout = sys.stdout
            sys.stdout = self._buf

        def readouterr(self):
            import io as _io
            captured = self._buf.getvalue()
            self._buf = _io.StringIO()
            sys.stdout = self._buf

            class _R:
                out = captured
            return _R()

        def restore(self):
            sys.stdout = self._real_stdout

    fake_capsys = _FakeCapsys()
    try:
        test_cli_check_native_messaging_flag_end_to_end(fake_capsys)
    finally:
        fake_capsys.restore()
    print("ALL NATIVE MESSAGING TESTS PASSED")
