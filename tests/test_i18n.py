# -*- coding: utf-8 -*-
"""🆕 v0.0.5b3で追加した pyside6_webusb.i18n の単体テスト。PySide6に一切依存しない
モジュールなので(diagnostics.pyと同じ設計方針)、QApplication等は不要。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pyside6_webusb.i18n import (
    CHOOSER_STRINGS,
    DEFAULT_LOCALE,
    DIAGNOSTICS_STRINGS,
    SUPPORTED_LOCALES,
    chooser_strings_for,
    detect_locale,
    diagnostics_text,
    normalize_locale,
    resolve_locale,
)


def test_default_locale_is_japanese_for_backward_compatibility():
    """0.0.5.post6までこのパッケージが実際に出力していた文言は全て日本語だった。
    locale=を何も指定しない既存の呼び出しの出力を変えないため、DEFAULT_LOCALEは
    "ja"に固定されている(自動検出ではない)ことを確認する。"""
    assert DEFAULT_LOCALE == "ja"
    assert resolve_locale(None) == "ja"
    print("test_default_locale_is_japanese_for_backward_compatibility: OK")


def test_normalize_locale_handles_arbitrary_and_unknown_input():
    assert normalize_locale("ja") == "ja"
    assert normalize_locale("EN") == "en"
    assert normalize_locale("zh-CN") == "zh"
    assert normalize_locale("zh_Hans_CN") == "zh"
    assert normalize_locale("ja_JP.UTF-8") == "ja"
    assert normalize_locale(None) == DEFAULT_LOCALE
    assert normalize_locale("") == DEFAULT_LOCALE
    assert normalize_locale("fr") == DEFAULT_LOCALE  # 未対応言語は既定値へフォールバック
    assert normalize_locale(12345) == DEFAULT_LOCALE  # 文字列以外でも例外を出さない
    print("test_normalize_locale_handles_arbitrary_and_unknown_input: OK")


def test_resolve_locale_auto_uses_detect_locale():
    assert resolve_locale("auto") == detect_locale()
    assert resolve_locale("ja") == "ja"
    assert resolve_locale("zh") == "zh"
    assert resolve_locale("not-a-real-locale") == DEFAULT_LOCALE
    print("test_resolve_locale_auto_uses_detect_locale: OK")


def test_detect_locale_respects_env_override(monkeypatch):
    monkeypatch.setenv("PYSIDE6_WEBUSB_LOCALE", "en")
    assert detect_locale() == "en"
    monkeypatch.setenv("PYSIDE6_WEBUSB_LOCALE", "zh-CN")
    assert detect_locale() == "zh"
    monkeypatch.delenv("PYSIDE6_WEBUSB_LOCALE", raising=False)
    # 環境変数が無くても例外を出さないことだけ確認する(実際のOSロケールは
    # 実行環境依存なので、戻り値そのものはSUPPORTED_LOCALESに含まれることだけ検証)。
    assert detect_locale() in SUPPORTED_LOCALES
    print("test_detect_locale_respects_env_override: OK")


def test_every_supported_locale_has_the_same_chooser_keys():
    """ロケールを追加/編集する際に一部のキーだけ訳し忘れる、を防ぐための
    構造チェック。"""
    key_sets = {locale: set(strings.keys()) for locale, strings in CHOOSER_STRINGS.items()}
    assert set(CHOOSER_STRINGS.keys()) == set(SUPPORTED_LOCALES)
    reference = key_sets["en"]
    for locale, keys in key_sets.items():
        assert keys == reference, f"locale {locale!r} has mismatched chooser string keys: {keys ^ reference}"
    print("test_every_supported_locale_has_the_same_chooser_keys: OK")


def test_every_supported_locale_has_the_same_diagnostics_keys():
    key_sets = {locale: set(strings.keys()) for locale, strings in DIAGNOSTICS_STRINGS.items()}
    assert set(DIAGNOSTICS_STRINGS.keys()) == set(SUPPORTED_LOCALES)
    reference = key_sets["en"]
    for locale, keys in key_sets.items():
        assert keys == reference, f"locale {locale!r} has mismatched diagnostics string keys: {keys ^ reference}"
    print("test_every_supported_locale_has_the_same_diagnostics_keys: OK")


def test_chooser_strings_for_returns_an_independent_copy():
    """呼び出し元がdictを書き換えても、i18n内部のマスターテーブルに影響しない
    ことを確認する(chooser_strings_forはdict(...)で毎回コピーを返す設計)。"""
    s = chooser_strings_for("en")
    s["title"] = "MUTATED"
    assert CHOOSER_STRINGS["en"]["title"] != "MUTATED"
    print("test_chooser_strings_for_returns_an_independent_copy: OK")


def test_chooser_strings_heading_template_has_origin_placeholder():
    for locale in SUPPORTED_LOCALES:
        s = chooser_strings_for(locale)
        assert "{origin}" in s["heading"]
        assert s["heading"].format(origin="https://example.com")
    print("test_chooser_strings_heading_template_has_origin_placeholder: OK")


def test_diagnostics_text_formats_and_defaults_to_japanese():
    assert diagnostics_text(None, "report_problems_header") == "検出された問題:"
    assert diagnostics_text("en", "report_problems_header") == "Problems detected:"
    assert diagnostics_text("zh", "report_problems_header") == "检测到的问题:"
    formatted = diagnostics_text("en", "qtwebengine_missing", missing="QtWebEngineCore")
    assert "QtWebEngineCore" in formatted
    print("test_diagnostics_text_formats_and_defaults_to_japanese: OK")


if __name__ == "__main__":
    class _FakeMonkeypatch:
        """pytestなしでも走らせられるよう、monkeypatch.setenv/delenv相当を素朴に
        実装したもの(他のテストファイルの_FakeMonkeypatchと同じ役割)。"""
        def __init__(self):
            self._restore = []

        def setenv(self, key, value):
            self._restore.append((key, key in os.environ, os.environ.get(key)))
            os.environ[key] = value

        def delenv(self, key, raising=True):
            self._restore.append((key, key in os.environ, os.environ.get(key)))
            os.environ.pop(key, None)

        def undo(self):
            for key, had_key, old_value in reversed(self._restore):
                if had_key:
                    os.environ[key] = old_value
                else:
                    os.environ.pop(key, None)
            self._restore.clear()

    mp = _FakeMonkeypatch()
    test_default_locale_is_japanese_for_backward_compatibility()
    test_normalize_locale_handles_arbitrary_and_unknown_input()
    test_resolve_locale_auto_uses_detect_locale()
    test_detect_locale_respects_env_override(mp)
    mp.undo()
    test_every_supported_locale_has_the_same_chooser_keys()
    test_every_supported_locale_has_the_same_diagnostics_keys()
    test_chooser_strings_for_returns_an_independent_copy()
    test_chooser_strings_heading_template_has_origin_placeholder()
    test_diagnostics_text_formats_and_defaults_to_japanese()
    print("ALL I18N TESTS PASSED")
