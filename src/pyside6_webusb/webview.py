# -*- coding: utf-8 -*-
"""
webview.py  (🆕 v0.0.6a)
========================
QtWebView(Qt Quick の `WebView`。Android WebView / iOS・macOSのWKWebView / Windows /
Linuxデスクトップ)向けの `install_webview()` と、QMLのダイアログでデバイスを選ばせる
`QmlDeviceChooser`。

    from PySide6.QtWebView import QtWebView
    QtWebView.initialize()                       # QGuiApplication生成より前に!
    ...
    webview = engine.rootObjects()[0].findChild(QObject, "webView")   # QMLのWebView
    handle = install_webview(webview, chooser=my_qml_chooser,
                             settings_organization="MyCompany", settings_application="MyApp")

QtWebEngineとの違い(正直な制約):
  - QtWebViewには「ドキュメント開始時にスクリプトを差し込む」APIが無い。ロード開始/完了の
    シグナルで runJavaScript() するため、ページ自身のスクリプトが最初に走る瞬間には
    navigator.usb がまだ無いことがある(遅延して呼ぶ実装なら問題ない)。厳密に
    ドキュメント開始時の注入が要る場合は QtWebEngine + install() を使うこと。
  - サブフレーム(iframe)には注入されない(=iframe内ではWebUSBは使えない。安全側)。
  - ページのCSP(connect-src)が ws://127.0.0.1 を禁じていると、ポリフィルはブリッジへ
    接続できない。HTTPSページから ws://127.0.0.1 へ繋げるかは埋め込み先のエンジン次第
    (Chromium系は許可、WKWebViewは要確認)。
  - 転送層は WebSocket(ws_transport.py)。フレームごとのオリジンはハンドシェイクの
    Originヘッダから決まる(ページJSは偽造できない)。
"""
from PySide6.QtCore import QCoreApplication, QEventLoop, QMetaObject, QObject, Q_ARG, Qt, QTimer, Signal, Slot

from .polyfill import build_polyfill_js
from .ws_transport import WebSocketBridgeServer

_DEFAULT_INJECT_DELAYS_MS = (0, 40, 160, 500)


class WebViewHandle(QObject):
    """install_webview()の戻り値。bridge/serverへのアクセスと後始末を提供する。"""

    def __init__(self, view, bridge, server, script, delays):
        super().__init__(None)
        self.view = view
        self.bridge = bridge
        self.server = server
        self._script = script
        self._delays = tuple(delays)
        self._disposed = False
        self.inject_count = 0

    @property
    def port(self):
        return self.server.port

    @property
    def script(self):
        """注入するJavaScriptソース(デバッグ/テスト用)。"""
        return self._script

    def inject_now(self):
        """今すぐ(冪等に)ポリフィルを注入する。ホストが独自の遷移フックを持つ場合に使う。"""
        if self._disposed:
            return
        _run_js(self.view, self._script)
        self.inject_count += 1

    def schedule_injection(self):
        """ロード開始直後の取りこぼしを減らすため、短い遅延を挟んで複数回注入する(冪等)。"""
        for delay in self._delays:
            if delay <= 0:
                self.inject_now()
            else:
                QTimer.singleShot(delay, self.inject_now)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        try:
            self.server.stop()
        except Exception:
            pass
        try:
            self.bridge.dispose()
        except Exception:
            pass


def _run_js(view, script):
    """view上でJavaScriptを実行する。QMLのWebView(Q_INVOKABLE runJavaScript(QString,QJSValue))と、
    Python側に runJavaScript(str) を持つビュー(QWebEnginePage等)の両方に対応する。

    QMLのWebViewはPythonから `view.runJavaScript(script)` と書くと「引数が2つ必要」で失敗する
    (QJSValueのコールバック引数が省略できない)ので、メタオブジェクトにQ_INVOKABLEとして
    見えている場合は QMetaObject.invokeMethod() で1引数呼び出しにする。"""
    if isinstance(view, QObject):
        try:
            mo = view.metaObject()
            has_invokable = (mo.indexOfMethod("runJavaScript(QString,QJSValue)") >= 0
                             or mo.indexOfMethod("runJavaScript(QString)") >= 0)
        except Exception:
            has_invokable = False
        if has_invokable and QMetaObject.invokeMethod(view, "runJavaScript",
                                                      Qt.ConnectionType.DirectConnection, Q_ARG(str, script)):
            return
    runner = getattr(view, "runJavaScript", None)
    if callable(runner):
        runner(script)
        return
    raise TypeError("view must provide runJavaScript() (QtWebView WebView item or QWebEnginePage)")


def _connect_load_signals(view, on_started, on_finished):
    """ビューの種類ごとのロード通知へ接続する。QMLのloadingChanged(QQuickWebViewLoadRequest*)は
    引数がPythonへ変換できないので、引数なしのcallableで受けて`loading`プロパティを読む。"""
    connected = False
    sig = getattr(view, "loadingChanged", None)
    if sig is not None:
        def _on_loading():
            try:
                loading = view.property("loading")
            except Exception:
                loading = None
            if loading is True:
                on_started()
            elif loading is False:
                on_finished()
        sig.connect(_on_loading)
        connected = True
    if not connected:
        # QWebEnginePage風: loadStarted / loadFinished(bool)。片方だけでも接続できたら成功とする。
        for name, cb in (("loadStarted", on_started), ("loadFinished", on_finished)):
            s = getattr(view, name, None)
            if s is not None:
                s.connect(lambda *_a, _cb=cb: _cb())
                connected = True
    return connected


def install_webview(view, browser_window=None,
                    settings_organization="pyside6-webusb", settings_application="WebUSBBridge",
                    locale=None, chooser=None, usb_backend=None, chooser_strings=None,
                    extra_guard_js=None, allowed_origins=None,
                    lock_navigator_usb=True, native_lookalike=True, expose_commands=True, debug=False,
                    inject_delays_ms=_DEFAULT_INJECT_DELAYS_MS, port=0):
    """
    QtWebView(または runJavaScript() を持つ任意のビュー)へ navigator.usb を装着する。

    view: QMLの `WebView` アイテム(QObject)、または runJavaScript(str) を持つオブジェクト
        (QWebEnginePageでも動く。QtWebEngineなら install() の方が厳密で推奨)。
    chooser: デバイス選択UI callable(devices, origin, strings) -> dict|None。QML/QGuiApplication
        のアプリでは必須(QtWidgetsのダイアログはQApplicationが無いと作れない)。
        `QmlDeviceChooser` が使える。
    allowed_origins: 接続を許すオリジンのiterable、または callable(origin)->bool。省略時は
        http(s)の任意オリジン(許可の付与自体はオリジンごとにユーザーが決める)。
    extra_guard_js: install() と同じ意味(ポリフィルより前に実行される)。
    inject_delays_ms: ロード開始後に注入を繰り返す遅延(ミリ秒)。
    戻り値: WebViewHandle(.bridge/.server/.port/.dispose())。失敗時は例外を送出する
        (QtWebEngineのinstall()と違い、ここでは黙って無効化しない: QtWebViewでは
        設定ミスが原因のことが多く、静かに動かないより早く気づける方が良い)。
    """
    from ._version import __version__
    from .bridge import WebUSBBridge
    from .i18n import resolve_locale

    parent = view if isinstance(view, QObject) else None
    bridge = WebUSBBridge(browser_window=browser_window, parent=parent,
                          settings_organization=settings_organization,
                          settings_application=settings_application,
                          usb_backend=usb_backend, locale=locale, chooser_strings=chooser_strings,
                          chooser=chooser, transport_kind="websocket")
    try:
        url_method = getattr(view, "url", None)
        if callable(url_method):                       # QWebEnginePage風(Python側に url())
            bridge.set_top_level_url_provider(url_method)
        elif isinstance(view, QObject):                # QMLのWebView(Qtプロパティ "url")
            bridge.set_top_level_url_provider(lambda: view.property("url"))
        server = WebSocketBridgeServer(bridge, allowed_origins=allowed_origins, port=port, parent=bridge)
        server.start()
        bridge._frame_tracker = server.registry
        script = build_polyfill_js(
            locale=resolve_locale(locale), lock_navigator_usb=lock_navigator_usb,
            native_lookalike=native_lookalike, expose_commands=expose_commands,
            transport="websocket", ws=server.client_config(), version=__version__, debug=debug)
        if extra_guard_js:
            script = extra_guard_js + "\n;\n" + script
        handle = WebViewHandle(view, bridge, server, script, inject_delays_ms)
    except Exception:
        try:
            bridge.dispose()
        except Exception:
            pass
        raise

    def _started():
        bridge.notify_navigated()
        handle.schedule_injection()

    def _finished():
        handle.inject_now()

    if not _connect_load_signals(view, _started, _finished):
        raise TypeError("view exposes neither loadingChanged nor loadStarted/loadFinished")
    handle.inject_now()      # 既に読み込み済みのページにも効かせる
    return handle


class QmlDeviceChooser(QObject):
    """QMLのダイアログでデバイスを選ばせるためのブリッジ(QtWidgets不要)。

    Python側:
        chooser = QmlDeviceChooser()
        engine.rootContext().setContextProperty("usbChooser", chooser)
        install_webview(webview, chooser=chooser)

    QML側:
        Connections {
            target: usbChooser
            function onRequested(requestJson) { chooserDialog.show(JSON.parse(requestJson)) }
        }
        // ユーザーが選んだら usbChooser.select(index)、キャンセルなら usbChooser.select(-1)

    requestJson = {"origin": "...", "devices": [{vendorId, productId, productName,
                   manufacturerName, serialNumber}, ...], "strings": {...}}
    (シリアル番号などは表示用に整形済みで、ページが自由に操作できる値ではない)
    """

    requested = Signal(str)

    def __init__(self, parent=None, timeout_ms=0):
        super().__init__(parent)
        self._loop = None
        self._choice = -1
        self._timeout_ms = timeout_ms

    def __call__(self, devices, origin, strings):
        import json
        if self._loop is not None:
            return None      # 既に選択待ち(再入)
        listing = [{k: d.get(k) for k in ("vendorId", "productId", "productName", "manufacturerName", "serialNumber")}
                   for d in devices]
        self._choice = -1
        self._loop = QEventLoop()
        if self._timeout_ms:
            QTimer.singleShot(self._timeout_ms, self._loop.quit)
        try:
            self.requested.emit(json.dumps({"origin": origin, "devices": listing, "strings": dict(strings or {})},
                                           ensure_ascii=False))
            self._loop.exec()
        finally:
            self._loop = None
        choice, self._choice = self._choice, -1
        if 0 <= choice < len(devices):
            return devices[choice]
        return None

    @Slot(int)
    def select(self, index):
        """QMLから呼ぶ。-1(または範囲外)はキャンセル。"""
        self._choice = index
        if self._loop is not None:
            self._loop.quit()

    @Slot()
    def cancel(self):
        self.select(-1)
