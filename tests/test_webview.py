# -*- coding: utf-8 -*-
"""webview.py: install_webview()/WebViewHandle/_run_js/QmlDeviceChooser の単体テスト。

実物のQML WebViewを使った動作確認は e2e_qtwebview_runner.py(別プロセス)側。ここでは、
runJavaScript()しか持たない最小のビューで、配線(注入タイミング・冪等性・後始末・
トップレベルURLの供給)をQtWebView無しで確認する。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import pytest

pytest.importorskip("PySide6.QtWebSockets")

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QSettings, QTimer, QUrl, Signal

from pyside6_webusb import QmlDeviceChooser, install_webview
from pyside6_webusb import webview as wv
from pyside6_webusb.virtual import VirtualUsbDevice, make_virtual_usb_backend

_app = QCoreApplication.instance() or QCoreApplication([])


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeView(QObject):
    """QtWebEngine風(Python側に runJavaScript(str) と loadStarted/loadFinished)の最小ビュー。"""
    loadStarted = Signal()
    loadFinished = Signal(bool)

    def __init__(self):
        super().__init__()
        self.scripts = []
        self._url = QUrl("https://app.example/")

    def runJavaScript(self, script):
        self.scripts.append(script)

    def url(self):
        return self._url


def _win():
    tmp = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
    tmp.close()

    class W:
        pass
    w = W()
    w.settings = QSettings(tmp.name, QSettings.Format.IniFormat)
    return w


def _install(view, **kw):
    backend = make_virtual_usb_backend([VirtualUsbDevice(vendor_id=1, product_id=2)])
    handle = install_webview(view, browser_window=_win(), usb_backend=backend, locale="en",
                             chooser=lambda d, o, s: None, **kw)
    handle.bridge._hotplug_timer.stop()
    return handle


def test_install_injects_immediately_and_on_every_load_event():
    view = FakeView()
    handle = _install(view, inject_delays_ms=(0,))
    assert len(view.scripts) == 1 and view.scripts[0] is handle.script
    view.loadStarted.emit()
    assert len(view.scripts) == 2
    view.loadFinished.emit(True)
    assert len(view.scripts) == 3
    handle.dispose()
    view.loadFinished.emit(True)
    assert len(view.scripts) == 3, "dispose()後は注入しない"


def test_delayed_reinjection_schedule_after_load_start():
    view = FakeView()
    handle = _install(view, inject_delays_ms=(0, 30, 90))
    base = len(view.scripts)
    view.loadStarted.emit()
    assert len(view.scripts) == base + 1
    spin(250)
    assert len(view.scripts) == base + 3
    handle.dispose()


def test_injected_script_is_the_websocket_flavour_with_this_servers_secret_and_no_qwebchannel():
    view = FakeView()
    handle = _install(view, inject_delays_ms=(0,))
    js = handle.script
    assert '"transport": "websocket"' in js
    assert handle.server.secret in js and str(handle.port) in js
    assert handle.server.client_config()["host"] == "127.0.0.1"
    assert "webChannelTransport" in js        # 使わないコードパスとして存在するだけ(transport=websocketなら選ばれない)
    handle.dispose()


def test_extra_guard_js_runs_before_the_polyfill_in_the_same_injection():
    view = FakeView()
    handle = _install(view, inject_delays_ms=(0,), extra_guard_js="window.__pysideWebUSBExtraGuard = function () { return true; };")
    assert handle.script.startswith("window.__pysideWebUSBExtraGuard") and "(function () {\n'use strict';" in handle.script
    handle.dispose()


def test_top_level_url_provider_drives_the_bridge_origin():
    view = FakeView()
    handle = _install(view, inject_delays_ms=(0,))
    assert handle.bridge._top_level_origin() == "https://app.example"
    view._url = QUrl("http://127.0.0.1:8080/x")
    assert handle.bridge._top_level_origin() == "http://127.0.0.1:8080"
    view._url = QUrl("about:blank")
    assert handle.bridge._top_level_origin() is None
    handle.dispose()


def test_origin_change_on_load_start_drops_handles_opened_by_the_previous_origin():
    view = FakeView()
    handle = _install(view, inject_delays_ms=(0,))
    handle.bridge._open_devices[11] = {"device": None, "origin": "https://old.example", "claimed_interfaces": set()}
    handle.bridge._open_devices[12] = {"device": None, "origin": "https://app.example", "claimed_interfaces": set()}
    view.loadStarted.emit()
    assert 11 not in handle.bridge._open_devices and 12 in handle.bridge._open_devices
    handle.dispose()


def test_dispose_stops_the_server_and_is_idempotent():
    view = FakeView()
    handle = _install(view, inject_delays_ms=(0,))
    port = handle.port
    assert port > 0
    handle.dispose()
    handle.dispose()
    assert handle.server._listening is False


def test_view_without_load_signals_is_rejected_clearly():
    class Bare(QObject):
        def runJavaScript(self, s):
            pass
    with pytest.raises(TypeError):
        _install(Bare())


def test_run_js_prefers_the_invokable_meta_method_and_falls_back_to_the_python_method():
    calls = []

    class Py(QObject):
        def runJavaScript(self, s):
            calls.append(("py", s))
    wv._run_js(Py(), "1+1")
    assert calls == [("py", "1+1")]
    with pytest.raises(TypeError):
        wv._run_js(object(), "1+1")


# ---------------------------------------------------------------- QmlDeviceChooser
DEVICES = [{"vendorId": 1, "productId": 2, "productName": "A", "manufacturerName": "M", "serialNumber": "S1", "configurations": [{"x": 1}]},
           {"vendorId": 3, "productId": 4, "productName": "B", "manufacturerName": None, "serialNumber": None}]


def test_qml_chooser_selects_by_index_and_only_sends_display_fields():
    import json
    chooser = QmlDeviceChooser()
    seen = {}

    def on_requested(text):
        seen["req"] = json.loads(text)
        QTimer.singleShot(10, lambda: chooser.select(1))
    chooser.requested.connect(on_requested)
    picked = chooser(DEVICES, "https://app.example", {"title": "Pick"})
    assert picked is DEVICES[1]
    assert seen["req"]["origin"] == "https://app.example"
    assert [set(d) for d in seen["req"]["devices"]] == [{"vendorId", "productId", "productName", "manufacturerName", "serialNumber"}] * 2
    assert seen["req"]["strings"] == {"title": "Pick"}


@pytest.mark.parametrize("choice", [-1, 2, 99, -5])
def test_qml_chooser_cancel_and_out_of_range_are_cancellations(choice):
    chooser = QmlDeviceChooser()
    chooser.requested.connect(lambda _t: QTimer.singleShot(5, lambda: chooser.select(choice)))
    assert chooser(DEVICES, "o", {}) is None


def test_qml_chooser_cancel_slot_and_timeout_and_reentrancy():
    chooser = QmlDeviceChooser()
    chooser.requested.connect(lambda _t: QTimer.singleShot(5, chooser.cancel))
    assert chooser(DEVICES, "o", {}) is None
    slow = QmlDeviceChooser(timeout_ms=40)
    assert slow(DEVICES, "o", {}) is None           # 誰も選ばない → タイムアウトでキャンセル

    outer = QmlDeviceChooser()
    inner_results = []

    def reenter(_t):
        inner_results.append(outer(DEVICES, "o", {}))   # 選択待ちの最中に再入 → 即None(ネストしない)
        QTimer.singleShot(5, lambda: outer.select(0))
    outer.requested.connect(reenter)
    assert outer(DEVICES, "o", {}) is DEVICES[0]
    assert inner_results == [None]


if __name__ == "__main__":
    # 直接実行でも本当にテストが走るように(import して終わり、にならないように)する。
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
