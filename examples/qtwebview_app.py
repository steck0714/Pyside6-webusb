# -*- coding: utf-8 -*-
"""QtWebView(Qt Quick の WebView)で navigator.usb を使う最小サンプル (0.0.6.post1+)。

    python examples/qtwebview_app.py https://your-site.example/
    python examples/qtwebview_app.py --smoke        # 画面なしで起動確認(CI/動作確認用)

QtWidgetsを使わない(QGuiApplication + QML)ので、デバイス選択は QmlDeviceChooser 経由で
QMLのダイアログに任せる。Android(PySide6 for Android)でも、このQML側の作りは同じ。
ただしAndroidでは USB 自体のバックエンド(UsbManager)をホストが用意する必要がある
(README「QtWebView」「Platforms」参照)。`--virtual` を付けると仮想USBデバイス(1台)を
ブリッジに差し込むので、ハードウェア無しでも一通りの動作を確認できる。
"""
import json
import os
import sys

from PySide6.QtWebView import QtWebView

QtWebView.initialize()        # QGuiApplication を作るより前に呼ぶこと(QtWebViewの決まり)

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from pyside6_webusb import QmlDeviceChooser, install_webview

QML = r"""
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtWebView

ApplicationWindow {
    id: win
    visible: true
    width: 960; height: 640
    title: "pyside6-webusb QtWebView example"

    property var request: null

    WebView {
        id: web
        objectName: "webView"
        anchors.fill: parent
        url: startUrl
    }

    // usbChooser は Python から setContextProperty された QmlDeviceChooser
    Connections {
        target: usbChooser
        function onRequested(requestJson) {
            win.request = JSON.parse(requestJson)
            list.model = win.request.devices
            dialog.open()
        }
    }

    Dialog {
        id: dialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(parent.width - 40, 520)
        title: win.request ? (win.request.strings.title || "Select a USB device") : ""
        standardButtons: Dialog.Cancel | Dialog.Ok
        onAccepted: usbChooser.select(list.currentIndex)
        onRejected: usbChooser.cancel()
        contentItem: ColumnLayout {
            Label {
                text: win.request ? win.request.origin : ""
                font.bold: true
                elide: Text.ElideMiddle
                Layout.fillWidth: true
            }
            ListView {
                id: list
                Layout.fillWidth: true
                Layout.preferredHeight: 180
                clip: true
                currentIndex: 0
                delegate: ItemDelegate {
                    width: ListView.view.width
                    highlighted: ListView.isCurrentItem
                    onClicked: list.currentIndex = index
                    // 表示用の値(記述子由来の文字列)はQMLの Text に素のテキストとして渡す
                    text: (modelData.productName || "(unnamed)") + "  [" + modelData.vendorId.toString(16) + ":" + modelData.productId.toString(16) + "]"
                          + (modelData.serialNumber ? "  #" + modelData.serialNumber : "")
                }
            }
        }
    }
}
"""


def main(argv):
    smoke = "--smoke" in argv
    use_virtual = "--virtual" in argv or smoke
    args = [a for a in argv[1:] if not a.startswith("--")]
    start_url = args[0] if args else "https://example.com/"
    if smoke:
        # ネットワークに依存しないよう、ローカルのHTTPサーバーのページを読み込む。
        import http.server
        import threading

        class _Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):   # noqa: N802
                body = b"<!doctype html><html><head><meta charset=utf-8><title>smoke</title></head><body>smoke</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        _srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Page)
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
        start_url = "http://127.0.0.1:%d/" % _srv.server_address[1]

    app = QGuiApplication(argv[:1])
    engine = QQmlApplicationEngine()

    chooser = QmlDeviceChooser()
    engine.rootContext().setContextProperty("usbChooser", chooser)
    engine.rootContext().setContextProperty("startUrl", QUrl(start_url))
    engine.loadData(QML.encode("utf-8"))
    if not engine.rootObjects():
        print("QML failed to load", file=sys.stderr)
        return 1
    # ⚠ rootObjects()[0] のラッパを変数に保持すること。一時オブジェクトのままだと、PySide6が
    #   そのラッパのGC時にQMLツリーごと破棄してしまい、後で "already deleted" になる(実測)。
    root = engine.rootObjects()[0]
    webview = root.findChild(QObject, "webView")

    usb_backend = None
    if use_virtual:
        from pyside6_webusb.virtual import VirtualUsbDevice, make_virtual_usb_backend
        usb_backend = make_virtual_usb_backend([
            VirtualUsbDevice(vendor_id=0x2341, product_id=0x8036, manufacturer="Example Inc.",
                             product="Virtual Widget", serial_number="DEMO-0001")])

    handle = install_webview(
        webview, chooser=chooser, usb_backend=usb_backend,
        settings_organization="pyside6-webusb-example", settings_application="qtwebview_app",
        locale="en")
    print("WebSocket bridge listening on 127.0.0.1:%d" % handle.port)

    if smoke:
        # 実際にページを読み込み、ポリフィルが入って WebSocket が確立したことを確認して終了する。
        result = {}

        def poll():
            from PySide6.QtCore import QMetaObject, Q_ARG, Qt
            QMetaObject.invokeMethod(webview, "runJavaScript", Qt.ConnectionType.DirectConnection, Q_ARG(
                str, "(async function(){ try { var t = await __pysideWebUSB.transport(); "
                     "document.title = 'SMOKE:' + JSON.stringify({usb: typeof navigator.usb, kind: t.kind, ready: t.ready}); } catch (e) { document.title = 'SMOKE:' + e; } })()"))
            QTimer.singleShot(400, check)

        def check():
            title = webview.property("title") or ""
            if title.startswith("SMOKE:"):
                result["v"] = title
                print(title)
                ok = '"usb":"object"' in title and '"ready":true' in title
                app.exit(0 if ok else 1)
            else:
                QTimer.singleShot(300, poll)
        QTimer.singleShot(2500, poll)
        QTimer.singleShot(25000, lambda: (print("smoke test timed out"), app.exit(2)))

    code = app.exec()
    handle.dispose()
    return code


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage")
    sys.exit(main(sys.argv))
