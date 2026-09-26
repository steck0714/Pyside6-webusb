# -*- coding: utf-8 -*-
"""🆕 v0.0.5b3で追加。chooser_dialog.py (WebUsbDeviceChooserDialog) には
これまで専用のテストファイルが一つも無かった(bridge.py/hardening.py等
だいたいのモジュールにあるような直接テストが欠けていた)。実際のQDialog/
QListWidgetを使い(GUIは出さずQT_QPA_PLATFORM=offscreenで)、
- デフォルト文言(DEFAULT_STRINGS)/ロケール別文言(i18n.chooser_strings_for)の
  どちらでもダイアログが正しく組み立てられること
- strings=の部分上書きが機能すること
- 「不明なデバイス」/"SN"のロケール別文言が実際にデバイス行へ反映されること
- Connectボタンがデバイス未選択では無効、選択で有効になること(既存の
  Chrome踏襲の安全側動作 — 誤って自動選択されないこと)
を確認する。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication  # noqa: E402

from pyside6_webusb.chooser_dialog import (  # noqa: E402
    DEFAULT_STRINGS,
    WebUsbDeviceChooserDialog,
    _device_name_and_detail,
)
from pyside6_webusb.i18n import chooser_strings_for  # noqa: E402

_app = QApplication.instance() or QApplication([])

_WIDGET_DEVICE = {
    "vendorId": 0x2341, "productId": 0x8036,
    "productName": "Virtual Widget", "manufacturerName": "Acme",
    "serialNumber": "SN-0001",
}
_NAMELESS_DEVICE = {"vendorId": 0x1234, "productId": 0x5678}
# name も vid/pid も無い、"unknown_device"フォールバックそのものを踏ませるための
# 完全に空のデバイス(_NAMELESS_DEVICEはvid/pidがあるのでVID:xxxx PID:yyyy側の
# 表示になり、unknown_deviceフォールバックには到達しない——これは意図した挙動)。
_BLANK_DEVICE = {}


def test_default_strings_is_english_and_matches_i18n_table():
    assert DEFAULT_STRINGS == chooser_strings_for("en")
    assert DEFAULT_STRINGS["cancel"] == "Cancel"
    print("test_default_strings_is_english_and_matches_i18n_table: OK")


def test_device_name_and_detail_uses_locale_strings():
    name, detail = _device_name_and_detail(_WIDGET_DEVICE, chooser_strings_for("ja"))
    assert name == "Virtual Widget"
    assert "SN:SN-0001" in detail

    # nameもvid/pidも無い(=表示できる情報が本当に何も無い)デバイスだけが
    # 「不明なデバイス」(ja)/"Unknown device"(en)/"未知设备"(zh)のいずれかになる
    # ——vid/pidさえあれば、その方が"Unknown device"よりも有用な情報として優先される
    # (この関数自身の既存の設計。detail_str or unknown_deviceの順序を参照)。
    name_ja, _ = _device_name_and_detail(_BLANK_DEVICE, chooser_strings_for("ja"))
    name_en, _ = _device_name_and_detail(_BLANK_DEVICE, chooser_strings_for("en"))
    name_zh, _ = _device_name_and_detail(_BLANK_DEVICE, chooser_strings_for("zh"))
    assert name_ja == "不明なデバイス"
    assert name_en == "Unknown device"
    assert name_zh == "未知设备"

    # vid/pidだけあるデバイスは、名前が無くてもVID/PID表示が優先され
    # unknown_deviceフォールバックには到達しない。
    name_with_vidpid, _ = _device_name_and_detail(_NAMELESS_DEVICE, chooser_strings_for("ja"))
    assert name_with_vidpid == "VID:1234 PID:5678"
    print("test_device_name_and_detail_uses_locale_strings: OK")


def test_device_name_and_detail_defaults_to_english_when_strings_omitted():
    """既存コード(strings=を渡さずこの関数を直接呼んでいた場合)が無変更で
    動き続けることを確認する回帰テスト。"""
    name, _ = _device_name_and_detail(_BLANK_DEVICE)
    assert name == "Unknown device"
    print("test_device_name_and_detail_defaults_to_english_when_strings_omitted: OK")


def test_dialog_renders_with_each_built_in_locale():
    for locale in ("en", "ja", "zh"):
        dlg = WebUsbDeviceChooserDialog(
            [_WIDGET_DEVICE], strings=chooser_strings_for(locale), origin="https://example.com",
        )
        expected = chooser_strings_for(locale)
        assert expected["title"] in dlg.windowTitle()
        assert dlg.device_list.count() == 1
        dlg.deleteLater()
    print("test_dialog_renders_with_each_built_in_locale: OK")


def test_dialog_strings_partial_override_falls_back_to_english_defaults():
    dlg = WebUsbDeviceChooserDialog(
        [_WIDGET_DEVICE], strings={"trust_reminder": "CUSTOM WARNING"}, origin="https://example.com",
    )
    assert dlg._strings["trust_reminder"] == "CUSTOM WARNING"
    assert dlg._strings["cancel"] == DEFAULT_STRINGS["cancel"]  # 上書きしていないキーは英語既定値のまま
    dlg.deleteLater()
    print("test_dialog_strings_partial_override_falls_back_to_english_defaults: OK")


def test_connect_button_disabled_until_a_device_is_selected():
    """Chromeのチューザーを踏襲した安全側動作: 複数デバイスがあっても先頭行を
    自動選択せず、ユーザーが明示的に選ぶまでConnectを無効にする。"""
    dlg = WebUsbDeviceChooserDialog(
        [_WIDGET_DEVICE, _NAMELESS_DEVICE], strings=chooser_strings_for("en"), origin="https://example.com",
    )
    assert dlg.device_list.currentRow() == -1
    assert dlg.btn_connect.isEnabled() is False
    dlg.device_list.setCurrentRow(0)
    assert dlg.btn_connect.isEnabled() is True
    dlg.deleteLater()
    print("test_connect_button_disabled_until_a_device_is_selected: OK")


def test_empty_device_list_shows_localized_empty_message():
    for locale in ("en", "ja", "zh"):
        dlg = WebUsbDeviceChooserDialog([], strings=chooser_strings_for(locale), origin="https://example.com")
        assert dlg.device_list.count() == 1
        assert dlg.device_list.item(0).text() == chooser_strings_for(locale)["empty"]
        dlg.deleteLater()
    print("test_empty_device_list_shows_localized_empty_message: OK")


if __name__ == "__main__":
    test_default_strings_is_english_and_matches_i18n_table()
    test_device_name_and_detail_uses_locale_strings()
    test_device_name_and_detail_defaults_to_english_when_strings_omitted()
    test_dialog_renders_with_each_built_in_locale()
    test_dialog_strings_partial_override_falls_back_to_english_defaults()
    test_connect_button_disabled_until_a_device_is_selected()
    test_empty_device_list_shows_localized_empty_message()
    print("ALL CHOOSER DIALOG TESTS PASSED")
