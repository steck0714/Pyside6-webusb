# -*- coding: utf-8 -*-
"""
pyside6-webusb
==============
A WebUSB API (https://wicg.github.io/webusb/) implementation for PySide6 / QtWebEngine
apps. QtWebEngine (the Chromium build PySide6 ships) does not implement WebUSB, so this
package reproduces it: a QWebChannel bridge backed by pyusb/libusb on the Python side, and
a JavaScript polyfill that makes `navigator.usb` behave like the real thing on the page
side.

Quick start
-----------
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from pyside6_webusb import install

    view = QWebEngineView()
    install(view.page())          # that's it -- navigator.usb now works on this page
    view.load("https://your-site.example")

See README.md for the security model, spec-compliance notes, and a full example app
(examples/minimal_browser.py).

Multi-language chooser dialog (🆕 v0.0.5b3)
--------------------------------------------
    install(view.page(), locale="en")   # or "ja" / "zh" / "auto" (follow the OS locale)

See pyside6_webusb.i18n for the full list of built-in locales and environment_report()/
format_environment_report()'s own `locale=` parameter for localizing the CLI/diagnostic
report the same way.

Troubleshooting your environment
---------------------------------
    python -m pyside6_webusb          # prints a PySide6/pyusb/libusb diagnostic report

or, from Python: `from pyside6_webusb import environment_report`. Unlike `install`/
`WebUSBBridge`/`WebUsbDeviceChooserDialog`, this always works even if `PySide6-Essentials`/
`PySide6-Addons` themselves aren't importable in this environment (see `0.0.5a0` CHANGELOG
entry) -- the diagnostic has to survive the exact condition it's meant to diagnose.
"""

from .diagnostics import environment_report, format_environment_report
from ._version import __version__
from .i18n import SUPPORTED_LOCALES, detect_locale
from .virtual import (
    VirtualUsbConfiguration,
    VirtualUsbDevice,
    VirtualUsbEndpoint,
    VirtualUsbInterface,
    make_virtual_usb_backend,
)

try:
    from .bridge import WebUSBBridge
    from .chooser_dialog import WebUsbDeviceChooserDialog
    from .polyfill import WEBUSB_POLYFILL_JS, install
except ImportError as _e:
    # 🆕 v0.0.5a0: 修正前はこのtry/exceptが無く、PySide6-Essentials/PySide6-Addonsの
    # どちらかでも欠けている環境では `import pyside6_webusb` 自体がここで生の
    # ModuleNotFoundErrorを投げて終わっていた——つまり、まさに`python -m
    # pyside6_webusb`/`pyside6-webusb-doctor`が助けになるべき「PySide6周りの環境が
    # 壊れている」状況で、その診断ツール自身が(diagnostics.pyへ到達する前に)
    # 起動不能になるという本末転倒が実際に発生していた(壊れたインストールで
    # 実際に再現して発見)。diagnostics.pyが意図的にPySide6非依存で書かれている
    # 設計方針と同じ理由で、ここも同様に持ち堪える必要がある。
    #
    # ただし本パッケージ自身のバグ(例: 内部importの取り違え)まで「PySide6が
    # 無いだけ」と誤魔化して握り潰してはならないため、実際にPySide6/shiboken6
    # 自体の欠如に起因するImportErrorかどうかを`.name`で見て絞り込み、それ以外は
    # そのまま再送出する。
    _missing = getattr(_e, "name", None) or ""
    if not (
        _missing == "shiboken6" or _missing.startswith("shiboken6.")
        or _missing == "PySide6" or _missing.startswith("PySide6.")
    ):
        raise

    # Python 3の `except ... as 名前` は、exceptブロックを抜けると同時にその名前を
    # 自動的にdelする(トレースバックが例外オブジェクトを介して延々と参照グラフに
    # 残り続けるのを防ぐための言語仕様)。_pyside6_unavailable()はこのexceptブロックの
    # 外——importが全部終わった後、実際にinstall()等が呼ばれた時点で初めて実行される
    # クロージャなので、_eをそのまま閉じ込めて参照すると、呼ばれた瞬間に
    # NameErrorになる(自動delされた後だから)。exceptブロックのスコープに縛られない
    # 普通の変数に詰め替えてから使う。
    _import_error = _e

    def _pyside6_unavailable(*_args, **_kwargs):
        raise ImportError(
            "pyside6_webusb.install() / WebUSBBridge / WebUsbDeviceChooserDialog require "
            "PySide6-Essentials and PySide6-Addons, which could not be imported in this "
            f"environment ({_import_error}). Run `python -m pyside6_webusb` (or, once "
            "installed, `pyside6-webusb-doctor`) for a full diagnostic report of what's "
            "missing."
        ) from _import_error

    WebUSBBridge = _pyside6_unavailable
    WebUsbDeviceChooserDialog = _pyside6_unavailable
    install = _pyside6_unavailable
    WEBUSB_POLYFILL_JS = None

__all__ = [
    "install",
    "WebUSBBridge",
    "WebUsbDeviceChooserDialog",
    "WEBUSB_POLYFILL_JS",
    "environment_report",
    "format_environment_report",
    "VirtualUsbDevice",
    "VirtualUsbConfiguration",
    "VirtualUsbInterface",
    "VirtualUsbEndpoint",
    "make_virtual_usb_backend",
    "SUPPORTED_LOCALES",
    "detect_locale",
]
