# -*- coding: utf-8 -*-
"""ws_transport.WebSocketBridgeServer の単体テスト(実際のQWebSocketクライアントで接続する)。

QtWebEngine/QtWebViewは不要。「別オリジン」「偽トークン」「内部メソッド」「接続上限」
「切断時のハンドル後始末」「ホットプラグ通知の絞り込み」といったセキュリティ上の性質を、
クライアント側でOriginヘッダを自由に指定して確認する。
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import pytest

PySide6 = pytest.importorskip("PySide6")
pytest.importorskip("PySide6.QtWebSockets")

from PySide6.QtCore import QCoreApplication, QEventLoop, QSettings, QTimer, QUrl
from PySide6.QtWebSockets import QWebSocket

from pyside6_webusb.bridge import WebUSBBridge
from pyside6_webusb.virtual import (
    VirtualUsbConfiguration, VirtualUsbDevice, VirtualUsbEndpoint, VirtualUsbInterface, make_virtual_usb_backend,
)
from pyside6_webusb.ws_transport import WebSocketBridgeServer

_app = QCoreApplication.instance() or QCoreApplication([])
VID, PID = 0x2341, 0x8036
GOOD = "https://app.example"


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def make_setup(allowed_origins=None, max_connections=64):
    tmp = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
    tmp.close()

    class _Win:
        pass
    win = _Win()
    win.settings = QSettings(tmp.name, QSettings.Format.IniFormat)
    dev = VirtualUsbDevice(
        vendor_id=VID, product_id=PID, product="Widget", serial_number="S1",
        configurations=[VirtualUsbConfiguration(value=1, interfaces=[
            VirtualUsbInterface(number=0, alternate=0, endpoints=[
                VirtualUsbEndpoint(number=1, direction="in", transfer_type="bulk"),
                VirtualUsbEndpoint(number=1, direction="out", transfer_type="bulk")])])])
    backend = make_virtual_usb_backend([dev])
    bridge = WebUSBBridge(browser_window=win, usb_backend=backend, locale="en", transport_kind="websocket")
    if bridge._hotplug_timer is not None:
        bridge._hotplug_timer.stop()
    server = WebSocketBridgeServer(bridge, allowed_origins=allowed_origins, max_connections=max_connections)
    server.start()
    bridge._frame_tracker = server.registry
    return bridge, server, dev


class Client:
    def __init__(self, server, origin=GOOD, path=None, secret=None):
        self.sock = QWebSocket(origin)
        self.msgs = []
        self.closed = False
        self.opened = False
        self.sock.textMessageReceived.connect(lambda t: self.msgs.append(json.loads(t)))
        self.sock.disconnected.connect(lambda: setattr(self, "closed", True))
        self.sock.connected.connect(lambda: setattr(self, "opened", True))
        url = "ws://127.0.0.1:%d%s" % (server.port, path if path is not None else "/pyusb/" + (secret or server.secret))
        self.sock.open(QUrl(url))
        spin(300)

    @property
    def hello(self):
        return any(m.get("hello") for m in self.msgs)

    def call(self, method, args, wait=250):
        n = len([m for m in self.msgs if "i" in m]) + 1
        self.sock.sendTextMessage(json.dumps({"i": 1000 + n, "m": method, "a": args}))
        spin(wait)
        for m in reversed(self.msgs):
            if m.get("i") == 1000 + n:
                return m
        return None

    def close(self):
        self.sock.close()
        spin(100)


def test_accepts_a_page_origin_with_the_secret_and_sends_hello():
    bridge, server, _ = make_setup()
    c = Client(server)
    assert c.opened and c.hello and not c.closed
    c.close()
    server.stop()


@pytest.mark.parametrize("origin", ["null", "file://", "about:blank", "chrome-extension://abc", "", "https://", "javascript:1", "https://a b.example"])
def test_rejects_null_and_non_http_origins(origin):
    bridge, server, _ = make_setup()
    c = Client(server, origin=origin)
    assert not c.hello, "origin %r must not get a verified session" % origin
    server.stop()


def test_rejects_wrong_secret_and_wrong_path():
    bridge, server, _ = make_setup()
    assert not Client(server, secret="wrong").hello
    assert not Client(server, path="/").hello
    assert not Client(server, path="/pyusb/").hello
    assert not Client(server, path="/pyusb/" + server.secret + "x").hello
    server.stop()


def test_allowed_origins_list_and_callable_policy():
    bridge, server, _ = make_setup(allowed_origins=[GOOD])
    assert Client(server, origin=GOOD).hello
    assert not Client(server, origin="https://evil.example").hello
    server.stop()
    bridge2, server2, _ = make_setup(allowed_origins=lambda o: o.endswith(".example"))
    assert Client(server2, origin="https://x.example").hello
    assert not Client(server2, origin="https://x.test").hello
    server2.stop()


def test_dispatch_table_contains_only_public_slots():
    bridge, server, _ = make_setup()
    names = server.dispatchable_methods()
    assert {"listDevices", "openDevice", "closeDevice", "claimInterface", "bulkTransferIn", "bulkTransferOut",
            "requestDeviceChooser", "mintGestureToken", "isAvailable", "getDiagnostics"} <= names
    assert not (names & {"deleteLater", "dispose", "event", "_on_page_navigated", "_poll_hotplug", "set_top_level_url_provider",
                         "add_hotplug_listener", "notify_navigated", "metaObject", "destroyed", "objectName"})
    assert all(not n.startswith("_") for n in names)
    server.stop()


def test_unknown_and_malformed_calls_are_refused_without_leaking_details():
    bridge, server, _ = make_setup()
    c = Client(server)
    assert c.call("deleteLater", [])["e"] == "unknown method"
    assert c.call("__class__", [])["e"] == "unknown method"
    assert c.call("listDevices", [1, 2, 3])["e"] == "invalid arguments"
    assert c.call("openDevice", ["x", 2, "", ""])["e"] == "invalid arguments"
    assert c.call("openDevice", [True, 2, "", ""])["e"] == "invalid arguments"
    assert c.call("closeDevice", [1.5, ""])["e"] == "invalid arguments"
    assert c.call("listDevices", "notalist")["e"] == "invalid arguments"
    c.sock.sendTextMessage("not json")
    c.sock.sendTextMessage(json.dumps([1, 2, 3]))
    c.sock.sendTextMessage(json.dumps({"i": "x", "m": "listDevices", "a": [""]}))
    spin(150)
    assert c.call("isAvailable", [])["r"], "the session must survive garbage input"
    server.stop()


def test_frame_token_argument_from_the_page_is_always_overridden():
    bridge, server, _ = make_setup()
    bridge._grant(GOOD, VID, PID)
    c = Client(server, origin=GOOD)
    forged = c.call("listDevices", ["a-token-someone-else-would-have"])
    assert len(json.loads(forged["r"])["devices"]) == 1
    other = Client(server, origin="https://other.example")
    seen = other.call("listDevices", [""])
    assert json.loads(seen["r"])["devices"] == [], "an origin without a grant must see no devices"
    for cl in (c, other):
        cl.close()
    server.stop()


def test_devices_opened_by_a_connection_are_closed_when_it_drops():
    bridge, server, dev = make_setup()
    bridge._grant(GOOD, VID, PID)
    c = Client(server, origin=GOOD)
    res = json.loads(c.call("openDevice", [VID, PID, "", "S1"])["r"])
    assert res["success"] is True
    assert len(bridge._open_devices) == 1
    c.close()
    spin(300)
    assert len(bridge._open_devices) == 0, "handles must not outlive their WebSocket"
    server.stop()


def test_a_connection_cannot_use_another_connections_handle():
    bridge, server, dev = make_setup()
    bridge._grant(GOOD, VID, PID)
    bridge._grant("https://other.example", VID, PID)
    a = Client(server, origin=GOOD)
    b = Client(server, origin="https://other.example")
    handle = json.loads(a.call("openDevice", [VID, PID, "", "S1"])["r"])["handle"]
    stolen = json.loads(b.call("claimInterface", [handle, 0, ""])["r"])
    assert stolen["success"] is False
    a.close()
    b.close()
    server.stop()


def test_connection_limit():
    bridge, server, _ = make_setup(max_connections=2)
    clients = [Client(server) for _ in range(3)]
    assert sum(1 for c in clients if c.hello) == 2
    for c in clients:
        c.close()
    server.stop()


def test_hotplug_events_go_only_to_granted_origins_and_carry_only_vid_pid():
    bridge, server, dev = make_setup()
    bridge._grant(GOOD, VID, PID)
    granted = Client(server, origin=GOOD)
    stranger = Client(server, origin="https://stranger.example")
    bridge._poll_hotplug()
    spin(100)
    dev.unplug()
    bridge._poll_hotplug()
    spin(400)
    ev = [m for m in granted.msgs if "ev" in m]
    assert len(ev) == 1 and ev[0]["ev"] == "disconnect"
    assert json.loads(ev[0]["d"]) == {"vendorId": VID, "productId": PID}
    assert not [m for m in stranger.msgs if "ev" in m]
    granted.close()
    stranger.close()
    server.stop()


def test_stop_closes_every_connection_and_stops_listening():
    bridge, server, _ = make_setup()
    c = Client(server)
    port = server.port
    server.stop()
    spin(300)
    assert c.closed
    late = QWebSocket(GOOD)
    opened = []
    late.connected.connect(lambda: opened.append(1))
    late.open(QUrl("ws://127.0.0.1:%d/pyusb/x" % port))
    spin(300)
    assert not opened


if __name__ == "__main__":
    # 直接実行でも本当にテストが走るように(import して終わり、にならないように)する。
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
