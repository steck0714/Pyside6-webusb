# -*- coding: utf-8 -*-
"""QtWebView(Qt Quick の `WebView`)+ WebSocket転送の実動作テスト(スタンドアロン)。

デスクトップLinux/WindowsのQtWebViewはQtWebEngineをバックエンドに使うので、この環境でも
「QWebChannelもドキュメント開始時注入も無く、runJavaScript()しか使えない」という
QtWebView(Android/iOS/macOSと同じ)の条件でそのまま検証できる。

pytest(tests/test_e2e_qtwebview.py)から別プロセスで起動される。結果は
`E2E_JSON={"checks": [...]}` の1行で出力する。
"""
import http.server
import json
import os
import sys
import tempfile
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
for _f in ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--ignore-certificate-errors"]:
    if _f not in _flags:
        _flags.append(_f)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(_flags)   # 親プロセスが既に値を持っていても必要なフラグを足す(setdefaultだと取りこぼす)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtWebView import QtWebView

QtWebView.initialize()          # QGuiApplication生成より前

from PySide6.QtCore import QEventLoop, QObject, QSettings, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from pyside6_webusb import QmlDeviceChooser, install_webview
from pyside6_webusb.virtual import (
    VirtualUsbConfiguration, VirtualUsbDevice, VirtualUsbEndpoint, VirtualUsbInterface, make_virtual_usb_backend,
)

VID, PID = 0x2341, 0x8036
PAGE = (b"<!doctype html><html><head><meta charset=utf-8><title>qtwebview-e2e</title></head>"
        b"<body><h1 id=t>hello</h1></body></html>")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):   # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *a):
        pass


_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
ORIGIN = "http://127.0.0.1:%d" % _srv.server_address[1]


def _start_https_server():
    """自己署名証明書のHTTPSサーバー(opensslが無ければNone)。ページ側のmixed content検証用。"""
    import shutil
    import ssl
    import subprocess
    if shutil.which("openssl") is None:
        return None
    d = tempfile.mkdtemp()
    key, crt = os.path.join(d, "k.pem"), os.path.join(d, "c.pem")
    r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "2",
                        "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost"], capture_output=True)
    if r.returncode != 0:
        return None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "https://127.0.0.1:%d" % srv.server_address[1]

app = QGuiApplication(sys.argv)     # QApplication ではない: QtWidgetsのダイアログは使えない条件
engine = QQmlApplicationEngine()
engine.loadData(('''
import QtQuick
import QtQuick.Window
import QtWebView
Window { visible: true; width: 500; height: 400
  WebView { id: wv; objectName: "wv"; anchors.fill: parent; url: "%s/" }
}''' % ORIGIN).encode())
root = engine.rootObjects()[0]
webview = root.findChild(QObject, "wv")

CHECKS = []


def record(name, ok, detail=""):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": "" if ok else detail})


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


_n = [0]


def js(code, timeout_ms=15000):
    _n[0] += 1
    key = "__r%d" % _n[0]
    wrapped = ("(function(){ window['%s'] = null; Promise.resolve().then(function(){ return (async function(){ %s })(); })"
               ".then(function(v){ window['%s'] = JSON.stringify({ok: v}); },"
               " function(e){ window['%s'] = JSON.stringify({err: String(e && e.name) + ': ' + String(e && e.message)}); }); })();"
               % (key, code, key, key))
    from PySide6.QtCore import QMetaObject, Qt, Q_ARG
    QMetaObject.invokeMethod(webview, "runJavaScript", Qt.ConnectionType.DirectConnection, Q_ARG(str, wrapped))
    # 結果の取得: QML WebViewのrunJavaScriptはコールバックがQMLのJS関数なので、
    # 結果はdocument.titleへ書き戻して読む(Python側からはtitleプロパティを読める)。
    out = None
    elapsed = 0
    while elapsed < timeout_ms:
        spin(150)
        elapsed += 150
        QMetaObject.invokeMethod(webview, "runJavaScript", Qt.ConnectionType.DirectConnection,
                                 Q_ARG(str, "if (window['%s']) { document.title = 'R' + window['%s']; }" % (key, key)))
        spin(80)
        elapsed += 80
        title = webview.property("title") or ""
        if title.startswith("R{"):
            out = json.loads(title[1:])
            QMetaObject.invokeMethod(webview, "runJavaScript", Qt.ConnectionType.DirectConnection,
                                     Q_ARG(str, "document.title = 'qtwebview-e2e';"))
            spin(80)
            return out
    return {"err": "timeout"}


def expect(name, code, predicate=None, equals=None):
    r = js(code)
    if "err" in r:
        record(name, False, "JS error: %s" % r["err"])
        return
    v = r["ok"]
    if equals is not None:
        record(name, v == equals, "got %r expected %r" % (v, equals))
    elif predicate is not None:
        record(name, predicate(v), "got %r" % (v,))
    else:
        record(name, v is True, "got %r" % (v,))


def run():
    tmp = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
    tmp.close()

    class _Win:
        pass
    win = _Win()
    win.settings = QSettings(tmp.name, QSettings.Format.IniFormat)

    device = VirtualUsbDevice(
        vendor_id=VID, product_id=PID, manufacturer="Acme", product="Virtual Widget", serial_number="SN-0001",
        configurations=[VirtualUsbConfiguration(value=1, interfaces=[
            VirtualUsbInterface(number=0, alternate=0, interface_class=0xFF, endpoints=[
                VirtualUsbEndpoint(number=1, direction="in", transfer_type="bulk"),
                VirtualUsbEndpoint(number=1, direction="out", transfer_type="bulk"),
            ]),
        ])])
    backend = make_virtual_usb_backend([device])
    chooser = QmlDeviceChooser()
    chosen = {}

    def on_requested(request_json):
        req = json.loads(request_json)
        chosen["req"] = req
        QTimer.singleShot(30, lambda: chooser.select(0))    # QMLのダイアログでユーザーが1番目を選ぶ、の代役
    chooser.requested.connect(on_requested)

    handle = install_webview(webview, browser_window=win, usb_backend=backend, locale="en", chooser=chooser)
    handle.bridge._hotplug_timer.stop()
    handle.bridge._grant(ORIGIN, VID, PID)
    spin(1500)                      # ロード完了 + 注入 + WebSocket接続
    for _ in range(40):             # ページとポリフィルの準備完了を待つ(最初のチェックが空振りしないように)
        r0 = js("return document.readyState === 'complete' && typeof navigator.usb === 'object' && (await __pysideWebUSB.transport()).ready === true", timeout_ms=2500)
        if r0.get("ok") is True:
            break
        spin(250)

    record("install_webview started a loopback WebSocket server", handle.port > 0)
    dispatchable = handle.server.dispatchable_methods()
    record("dispatch table equals the bridge's public slots (no internals, no deleteLater)",
           {"listDevices", "openDevice", "requestDeviceChooser", "bulkTransferIn", "mintGestureToken", "getDiagnostics"} <= dispatchable
           and not (dispatchable & {"deleteLater", "_on_page_navigated", "_poll_hotplug", "event", "dispose"}),
           sorted(dispatchable))

    expect("navigator.usb was injected into the QtWebView page and is native-shaped",
           "return navigator.usb instanceof USB && Object.prototype.toString.call(navigator.usb) === '[object USB]' && "
           "!Object.prototype.hasOwnProperty.call(navigator, 'usb') && typeof QWebChannel === 'undefined'")
    expect("...transport is websocket and ready",
           "var t = await __pysideWebUSB.transport(); return t.kind === 'websocket' && t.ready === true")
    expect("delete navigator.usb / delete Navigator.prototype.usb cannot remove it",
           "var b = navigator.usb; var r = delete navigator.usb; var m = 'no throw'; try { 'use strict'; (function(){ 'use strict'; delete Navigator.prototype.usb; })(); } catch (e) { m = e.name; } return r === true && m === 'TypeError' && navigator.usb === b")
    expect("selfTest() passes on the WebSocket transport",
           "var r = __pysideWebUSB.selfTest(); return r.ok === true ? true : JSON.stringify(r.checks.filter(function (c) { return !c.ok; }))")
    expect("platform()/diagnose() custom commands work over WebSocket (no QWebChannel, QtWebView conditions)",
           "var p = await __pysideWebUSB.platform(); var d = await __pysideWebUSB.diagnose(); "
           "return p.host.os === 'linux' && d.transport === 'websocket' && d.chooser === 'custom' && d.backendUsable === true && Array.isArray(d.hints)")
    expect("getDevices() returns the granted device (origin came from the WebSocket handshake)",
           "var a = await navigator.usb.getDevices(); return a.length === 1 && a[0] instanceof USBDevice && a[0].productName === 'Virtual Widget'")
    expect("open/claim/transferOut/transferIn/close over WebSocket",
           "var d = (await navigator.usb.getDevices())[0]; await d.open(); if (d.configuration === null) await d.selectConfiguration(1);"
           "await d.claimInterface(0); var o = await d.transferOut(1, new Uint8Array([1,2,3])); var i = await d.transferIn(1, 8);"
           "await d.releaseInterface(0); await d.close();"
           "return o.bytesWritten === 3 && i.data.byteLength === 8 && !d.opened")
    expect("bridge errors keep the native DOMException names over WebSocket",
           "var d = (await navigator.usb.getDevices())[0]; try { await d.transferIn(1, 8); return 'resolved'; } catch (e) { return e.name + ': ' + e.message; }",
           equals="InvalidStateError: The device must be opened first.")

    # 秘密(パス)無しで別の接続を張れないこと
    expect("a WebSocket without the secret path is rejected",
           "var cfg = null; return await new Promise(function (resolve) { var s = new WebSocket('ws://127.0.0.1:%d/pyusb/wrong'); "
           "s.onopen = function () { s.onmessage = function (m) { resolve('opened:' + m.data); }; setTimeout(function () { resolve('open-no-hello'); }, 500); };"
           "s.onclose = function () { resolve('closed'); }; s.onerror = function () {}; setTimeout(function () { resolve('timeout'); }, 3000); })" % handle.port,
           predicate=lambda v: v in ("closed", "open-no-hello"))

    # hotplug
    js("window.__ev = []; navigator.usb.addEventListener('disconnect', function (e) { window.__ev.push('d:' + e.device.vendorId); });"
       "navigator.usb.addEventListener('connect', function (e) { window.__ev.push('c:' + e.device.vendorId + ':' + (e.device instanceof USBDevice)); });"
       "await navigator.usb.getDevices(); return true;")
    handle.bridge._poll_hotplug()
    spin(100)
    device.unplug()
    handle.bridge._poll_hotplug()
    spin(1200)
    device.plug()
    handle.bridge._poll_hotplug()
    spin(1500)
    expect("hotplug disconnect/connect events reach the page over WebSocket (VID/PID only on the wire)",
           "return JSON.stringify(window.__ev)", equals=json.dumps(["d:9025", "c:9025:true"], separators=(",", ":")))

    # requestDevice: runJavaScript has no user activation -> native SecurityError text
    expect("requestDevice without user activation rejects with the exact Chromium text",
           "try { await navigator.usb.requestDevice({filters: [{vendorId: 0x2341}]}); return 'resolved'; } catch (e) { return e.name + ': ' + e.message; }",
           equals="SecurityError: Failed to execute 'requestDevice' on 'USB': Must be handling a user gesture to show a permission request.")

    # (チューザー経路: QtWebView環境ではrunJavaScript由来のJSに実ユーザー操作が無いため、ここでは
    #  「未操作なら拒否」までを確認する。実クリックでの許可付与はQtWebEngineのe2eで確認済み)
    record("QmlDeviceChooser was not invoked by anything but the chooser flow", "req" not in chosen)

    # ---- HTTPSページ(WebUSBの実運用はほぼHTTPS)からループバックのws://へ接続できること
    https_origin = _start_https_server()
    if https_origin is None:
        record("https page -> ws://127.0.0.1 (skipped: openssl not available)", True)
    else:
        from PySide6.QtCore import QUrl as _QUrl
        handle.bridge._grant(https_origin, VID, PID)
        webview.setProperty("url", _QUrl(https_origin + "/"))
        for _ in range(60):
            spin(250)
            if (webview.property("title") or "") == "qtwebview-e2e" and not webview.property("loading"):
                break
        spin(1200)
        for _ in range(30):
            r1 = js("return location.protocol === 'https:' && typeof navigator.usb === 'object' && (await __pysideWebUSB.transport()).ready === true", timeout_ms=2500)
            if r1.get("ok") is True:
                break
            spin(300)
        expect("an https:// page reaches the loopback ws:// transport (mixed-content exemption for 127.0.0.1) and sees its grant",
               "var t = await __pysideWebUSB.transport(); var d = await navigator.usb.getDevices(); return location.protocol === 'https:' && isSecureContext && t.kind === 'websocket' && t.ready === true && d.length === 1")

    # ---- ページのJSが生のWebSocketでブリッジを直接叩く(悪意あるページ想定)
    raw_call = ("async function rawCall(method, args) { return await new Promise(function (resolve) {"
                " var s = new WebSocket('ws://127.0.0.1:%d/pyusb/%s');"
                " s.onmessage = function (m) { var d = JSON.parse(m.data); if (d.hello) { s.send(JSON.stringify({i: 1, m: method, a: args})); } else if (d.i === 1) { resolve(JSON.stringify(d)); s.close(); } };"
                " s.onclose = function () { resolve('closed'); }; setTimeout(function () { resolve('timeout'); }, 3000); }); }"
                % (handle.port, handle.server.secret))
    expect("raw WS: internal / QObject methods are not callable (deleteLater, _poll_hotplug, dispose)",
           raw_call + " var out = []; for (var m of ['deleteLater', '_poll_hotplug', '_on_page_navigated', 'dispose', 'event', 'notify_navigated']) out.push(JSON.parse(await rawCall(m, [])).e); return JSON.stringify(out);",
           equals=json.dumps(["unknown method"] * 6, separators=(",", ":")))
    expect("raw WS: argument count/type violations are refused, not coerced",
           raw_call + " var a = JSON.parse(await rawCall('openDevice', [1, 2])).e; var b = JSON.parse(await rawCall('openDevice', ['x', 2, '', ''])).e; "
           "var c = JSON.parse(await rawCall('closeDevice', [true, ''])).e; var d = JSON.parse(await rawCall('listDevices', [1])).e; return JSON.stringify([a, b, c, d]);",
           equals=json.dumps(["invalid arguments"] * 4, separators=(",", ":")))
    expect("raw WS: a forged frame token is ignored (the connection's own token always wins)",
           raw_call + " var r = JSON.parse(await rawCall('listDevices', ['forged-token-of-another-origin'])); return typeof r.r === 'string' && JSON.parse(r.r).devices.length === 1;")
    # (別オリジンからの接続・権限の無いオリジンの見え方は tests/test_ws_transport.py で検証)
    return handle


def main():
    try:
        handle = run()
        # 別オリジンからの接続を拒否できること(Pythonクライアントで検証)
        import socket
        import base64
        import os as _os

        def ws_status(origin, path):
            s = socket.create_connection(("127.0.0.1", handle.port), timeout=3)
            key = base64.b64encode(_os.urandom(16)).decode()
            req = ("GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n" % (path, handle.port, key))
            if origin is not None:
                req += "Origin: %s\r\n" % origin
            req += "\r\n"
            s.sendall(req.encode())
            s.settimeout(2)
            got = b""
            try:
                while b"\r\n\r\n" not in got:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    got += chunk
            except Exception:
                pass
            s.close()
            return got.split(b"\r\n", 1)[0].decode("latin1"), got

        import threading as _t
        results = {}

        def worker():
            results["null_origin"] = ws_status("null", "/pyusb/" + handle.server.secret)
            results["no_origin"] = ws_status(None, "/pyusb/" + handle.server.secret)
            results["file_origin"] = ws_status("file://", "/pyusb/" + handle.server.secret)
            results["good"] = ws_status(ORIGIN, "/pyusb/" + handle.server.secret)
        th = _t.Thread(target=worker, daemon=True)
        th.start()
        while th.is_alive():
            spin(50)
        for k in ("null_origin", "no_origin", "file_origin"):
            status = results[k][0]
            record("handshake with %s is refused at the HTTP level" % k, "101" not in status, status)
        record("handshake with the page's own origin is accepted", "101" in results["good"][0], results["good"][0])
    except Exception as e:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        CHECKS.append({"name": "runner crashed", "ok": False, "detail": repr(e)})
    print("E2E_JSON=" + json.dumps({"checks": CHECKS}))
    sys.stdout.flush()
    os._exit(0 if all(c["ok"] for c in CHECKS) else 1)


if __name__ == "__main__":
    main()
