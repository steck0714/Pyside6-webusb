# -*- coding: utf-8 -*-
"""platform_support.py: OS判定(特にAndroid)・機能表・ヒント・転送層の推奨。

PySide6/pyusbに依存しない葉モジュールなので、sys.platform/os.environ/platform.system を
差し替えて全OSの分岐をこの1台で検証できる。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import pytest

from pyside6_webusb import platform_support as ps


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("ANDROID_ARGUMENT", "ANDROID_PRIVATE", "ANDROID_ROOT", "ANDROID_DATA"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ps._platform, "system", lambda: "Linux")
    if hasattr(sys, "getandroidapilevel"):
        monkeypatch.delattr(sys, "getandroidapilevel", raising=False)
    return monkeypatch


@pytest.mark.parametrize("plat,expected", [
    ("win32", "windows"), ("cygwin", "windows"), ("msys", "windows"),
    ("darwin", "macos"), ("linux", "linux"), ("linux2", "linux"),
    ("freebsd13", "freebsd"), ("ios", "ios"), ("android", "android"), ("sunos5", "other"), ("", "other"),
])
def test_detect_platform_from_sys_platform(clean_env, plat, expected):
    clean_env.setattr(sys, "platform", plat)
    assert ps.detect_platform() == expected


def test_android_is_detected_even_when_sys_platform_says_linux(clean_env):
    """python-for-android / Qt for Python(Android) / Python<3.13 では sys.platform が 'linux' のまま。"""
    clean_env.setattr(sys, "platform", "linux")
    clean_env.setenv("ANDROID_ARGUMENT", "/data/app/x")
    assert ps.detect_platform() == "android"
    clean_env.delenv("ANDROID_ARGUMENT")
    clean_env.setenv("ANDROID_ROOT", "/system")
    assert ps.detect_platform() == "linux", "ANDROID_ROOT単独では判定しない(ANDROID_DATAとの組)"
    clean_env.setenv("ANDROID_DATA", "/data")
    assert ps.detect_platform() == "android"
    clean_env.delenv("ANDROID_ROOT")
    clean_env.delenv("ANDROID_DATA")
    clean_env.setattr(ps._platform, "system", lambda: "Android")
    assert ps.detect_platform() == "android"
    clean_env.setattr(ps._platform, "system", lambda: "Linux")
    clean_env.setattr(sys, "getandroidapilevel", lambda: 34, raising=False)
    assert ps.detect_platform() == "android"


def test_detect_platform_never_raises(clean_env):
    def boom():
        raise RuntimeError("boom")
    clean_env.setattr(ps._platform, "system", boom)
    clean_env.setattr(sys, "platform", "linux")
    assert ps.detect_platform() == "linux"
    clean_env.setattr(sys, "platform", None)
    assert ps.detect_platform() == "other"


def test_platform_summary_has_no_paths_or_user_names():
    info = ps.platform_summary()
    assert set(info) == {"os", "machine", "python"}
    assert info["os"] in ps.PLATFORMS
    blob = repr(info)
    assert os.path.expanduser("~") not in blob and "/" not in blob.replace("x86_64", "")


@pytest.mark.parametrize("osname", ["windows", "macos", "linux", "android", "ios", "other"])
def test_capability_summary_shape(osname):
    caps = ps.capability_summary(osname)
    assert set(caps) == {"controlTransfer", "bulkTransfer", "isochronousTransfer", "kernelDriverDetach",
                         "hotplugPolling", "nativeChooserDialog"}
    assert set(caps.values()) <= {"supported", "limited", "unsupported"}
    caps["bulkTransfer"] = "x"
    assert ps.capability_summary(osname)["bulkTransfer"] != "x", "呼び出しごとに独立したコピー"


def test_kernel_driver_detach_only_on_linux():
    assert ps.capability_summary("linux")["kernelDriverDetach"] == "supported"
    for osname in ("windows", "macos", "android"):
        assert ps.capability_summary(osname)["kernelDriverDetach"] == "unsupported"


@pytest.mark.parametrize("osname", ["windows", "macos", "linux", "android", "ios"])
def test_setup_hints_exist_for_every_supported_os(osname):
    hints = ps.setup_hints(osname)
    assert hints and all(isinstance(h, str) and h for h in hints)
    assert ps.setup_hints("nonexistent") == []


def test_android_hints_explain_usbmanager_and_webview():
    text = " ".join(ps.setup_hints("android")).lower()
    assert "usbmanager" in text and "install_webview" in text and "libusb" in text


@pytest.mark.parametrize("osname,we,wv,ws,expected", [
    ("linux", True, True, True, "webchannel"),
    ("windows", None, None, None, "webchannel"),
    ("macos", False, True, True, "websocket"),
    ("linux", False, True, False, None),
    ("linux", False, False, True, None),
    ("android", True, True, True, "websocket"),     # AndroidにQtWebEngineは無い: 有っても使わない
    ("android", None, None, None, "websocket"),
    ("android", None, False, True, None),
    ("ios", None, True, True, "websocket"),
    ("other", None, None, None, "webchannel"),
])
def test_recommended_transport(osname, we, wv, ws, expected):
    assert ps.recommended_transport(osname, have_webengine=we, have_webview=wv, have_websockets=ws) == expected


if __name__ == "__main__":
    # 直接実行でも本当にテストが走るように(import して終わり、にならないように)する。
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
