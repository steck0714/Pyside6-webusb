# -*- coding: utf-8 -*-
"""
platform_support.py  (🆕 v0.0.6a)
=================================
OS判定・機能マトリクス・セットアップのヒントをまとめた、PySide6にもpyusbにも
依存しない葉モジュール(標準ライブラリのみ)。

用途:
  - WebUSBBridge.isAvailable() / getDiagnostics() が返す platform / capabilities
    (=ページ側の window.__pysideWebUSB.platform() / diagnose() の中身)
  - `pyside6-webusb-doctor`(diagnostics.py)の「この環境で何をすべきか」の案内
  - QtWebEngine(デスクトップ) と QtWebView(Android/iOS/ネイティブWebView) のどちらの
    転送層を使うべきかの推奨(recommended_transport)

どのOSでも例外を出さず、判定不能なら "other" を返す(診断コマンドが診断対象の環境で
落ちては意味がないため)。
"""
import os
import platform as _platform
import sys

PLATFORMS = ("windows", "macos", "linux", "android", "ios", "freebsd", "other")


def detect_platform():
    """'windows' | 'macos' | 'linux' | 'android' | 'ios' | 'freebsd' | 'other'。

    Android判定が先: 古いPython(<3.13)/python-for-android/Qt for Python(Android)では
    sys.platform が 'linux' のままなので、Android固有の手掛かり(環境変数・sys属性・
    platform.system())を先に見る。
    """
    try:
        plat = sys.platform or ""
        if plat == "android" or hasattr(sys, "getandroidapilevel"):
            return "android"
        env = os.environ
        if env.get("ANDROID_ARGUMENT") or env.get("ANDROID_PRIVATE") or (
                env.get("ANDROID_ROOT") and env.get("ANDROID_DATA")):
            return "android"
        try:
            if _platform.system() == "Android":
                return "android"
        except Exception:
            pass
        if plat == "ios":
            return "ios"
        if plat.startswith("win") or plat in ("cygwin", "msys"):
            return "windows"
        if plat == "darwin":
            return "macos"
        if plat.startswith("linux"):
            return "linux"
        if plat.startswith("freebsd"):
            return "freebsd"
    except Exception:
        pass
    return "other"


def platform_summary():
    """ページへ渡しても安全な最小限のホスト情報(パス・ユーザー名などは含めない)。"""
    name = detect_platform()
    try:
        machine = _platform.machine() or ""
    except Exception:
        machine = ""
    try:
        py = _platform.python_version()
    except Exception:
        py = ""
    return {"os": name, "machine": machine, "python": py}


# ---- 機能マトリクス -------------------------------------------------------------
#   値: "supported" | "limited" | "unsupported"
_CAPABILITIES = {
    "windows": {
        "controlTransfer": "supported", "bulkTransfer": "supported",
        "isochronousTransfer": "limited", "kernelDriverDetach": "unsupported",
        "hotplugPolling": "supported", "nativeChooserDialog": "supported",
    },
    "macos": {
        "controlTransfer": "supported", "bulkTransfer": "supported",
        "isochronousTransfer": "supported", "kernelDriverDetach": "unsupported",
        "hotplugPolling": "supported", "nativeChooserDialog": "supported",
    },
    "linux": {
        "controlTransfer": "supported", "bulkTransfer": "supported",
        "isochronousTransfer": "supported", "kernelDriverDetach": "supported",
        "hotplugPolling": "supported", "nativeChooserDialog": "supported",
    },
    "android": {
        "controlTransfer": "supported", "bulkTransfer": "supported",
        "isochronousTransfer": "limited", "kernelDriverDetach": "unsupported",
        "hotplugPolling": "supported", "nativeChooserDialog": "limited",
    },
}
_DEFAULT_CAPABILITIES = {
    "controlTransfer": "limited", "bulkTransfer": "limited", "isochronousTransfer": "limited",
    "kernelDriverDetach": "unsupported", "hotplugPolling": "supported", "nativeChooserDialog": "limited",
}


def capability_summary(os_name=None):
    """OSごとの機能の対応状況(libusbバックエンド前提の目安)。実際のデバイス依存の挙動は保証しない。"""
    os_name = os_name or detect_platform()
    return dict(_CAPABILITIES.get(os_name, _DEFAULT_CAPABILITIES))


# ---- セットアップのヒント(短い英語の定型句。診断UIが言語別に整形する) -------------
_SETUP_HINTS = {
    "windows": [
        "libusb-1.0.dll must be findable (next to python.exe, in PATH, or shipped via the 'libusb-package' wheel).",
        "Devices need a WinUSB/libusbK driver (for example installed with Zadig) to be opened with libusb.",
    ],
    "macos": [
        "Install libusb (for example 'brew install libusb'); Apple Silicon Homebrew lives under /opt/homebrew/lib.",
        "Sandboxed/notarised apps need the com.apple.security.device.usb entitlement.",
    ],
    "linux": [
        "Install libusb-1.0 (for example 'apt install libusb-1.0-0').",
        "Unprivileged access needs a udev rule (SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"xxxx\", MODE=\"0666\" or TAG+=\"uaccess\").",
    ],
    "android": [
        "Android grants USB access per device through UsbManager (permission dialog); libusb only sees a device through a file descriptor from UsbDeviceConnection.",
        "Bundle libusb-1.0 (libusb1.0.so) in the APK and inject an Android-aware usb_backend into install_webview(); plain pyusb enumeration does not work without root.",
        "Use install_webview() (QtWebView + loopback WebSocket): QtWebEngine is not available on Android.",
    ],
    "ios": [
        "iOS does not expose raw USB access to third-party apps; only the virtual test backend works here.",
    ],
}


def setup_hints(os_name=None):
    return list(_SETUP_HINTS.get(os_name or detect_platform(), []))


def recommended_transport(os_name=None, have_webengine=None, have_webview=None, have_websockets=None):
    """使うべき転送層の推奨: 'webchannel'(QtWebEngine) | 'websocket'(QtWebView等) | None。

    Android/iOSではQtWebEngineが存在しないので常にwebsocket(QtWebView)。
    デスクトップではQtWebEngineがあればwebchannel、無くてQtWebView+QtWebSocketsがあればwebsocket。
    have_* は診断側が実際のimport可否を渡す(Noneは未判定=楽観的に扱う)。
    """
    os_name = os_name or detect_platform()
    if os_name in ("android", "ios"):
        return "websocket" if have_webview is not False and have_websockets is not False else None
    if have_webengine is not False:
        return "webchannel"
    if have_webview is not False and have_websockets is not False:
        return "websocket"
    return None
