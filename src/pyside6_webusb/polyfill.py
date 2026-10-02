# -*- coding: utf-8 -*-
"""
polyfill.py
===========
navigator.usb のJSポリフィルと、QWebEnginePageへの装着を1回の呼び出しで済ませる
install() を提供する。

    from pyside6_webusb import install
    install(my_web_engine_page)

だけで、そのページ上のJavaScriptから navigator.usb.getDevices() /
navigator.usb.requestDevice() などが動くようになる(実機の選択はネイティブの
Qtダイアログ、実際のUSB通信はpyusb/libusb経由)。

🆕 v0.0.6a(配布版 0.0.6.post1)での作り直し:
  - JSは jssrc/*.js に平文で書かれ、scripts/build_polyfill.py が _polyfill_bundle.py
    (Pythonモジュール)へ束ねる。Android等「.py以外を同梱しない」配布形態でも動く。
  - navigator.usb は Navigator.prototype 上のgetter(=ネイティブのWebIDL属性と同じ形)。
    インスタンスの自前プロパティではないので `delete navigator.usb` では消えず、
    既定では Navigator.prototype.usb 自体も non-configurable(lock_navigator_usb)。
  - USB / USBDevice / USBConfiguration / USBInterface / USBAlternateInterface /
    USBEndpoint / USBConnectionEvent / 各転送結果クラスを、Chromium(Blink)のIDLと
    エラーメッセージに合わせて実装(Symbol.toStringTag、illegal constructor、
    ブランドチェック、[native code]のtoString等)。
  - qwebchannel.js は別スクリプトではなくポリフィルのクロージャ内へ取り込み、
    QWebChannel/QObject等のグローバルがページへ漏れない。
  - 転送層を差し替え可能に: QWebChannel(QtWebEngine) と WebSocket(QtWebView等)。
"""
import json

from ._polyfill_bundle import POLYFILL_JS_TEMPLATE

_CONFIG_RE_BEGIN = "/*CONFIG_BEGIN*/"
_CONFIG_RE_END = "/*CONFIG_END*/"
_QWC_BEGIN = "/*QWC_LIB_BEGIN*/"
_QWC_END = "/*QWC_LIB_END*/"

_QWEBCHANNEL_JS_CACHE = None


def _load_qwebchannel_js():
    """Qt自身が(QtWebChannelモジュールの一部として)同梱しているqwebchannel.jsを
    実行時に読み込む。Qt公式のQWebChannel standaloneサンプルが示す標準的な取得方法
    (QFile(":/qtwebchannel/qwebchannel.js"))を使うことで、本パッケージがQt本体の
    JSファイルを別途同梱・バージョン追従する必要をなくしている
    (qwebchannel.js自体はQt側で通常BSD-3-Clauseライセンスとして配布されているが、
    正確なライセンスは実行時にリンクされる具体的なQt/PySide6ディストリビューション
    次第であり、本パッケージはこのQt提供リソースについて断定的なライセンス表明を
    行わない — 詳細はLICENSE §2.1参照)。

    PySide6.QtWebChannel を一度でもimportしていないと、このQtリソースパスは
    まだ登録されていないことがある。install()はQWebChannelを内部でimportするため、
    通常このモジュールを直接使わずinstall()経由で呼べば問題にならない。
    """
    global _QWEBCHANNEL_JS_CACHE
    if _QWEBCHANNEL_JS_CACHE is not None:
        return _QWEBCHANNEL_JS_CACHE
    from PySide6.QtCore import QFile, QIODevice
    f = QFile(":/qtwebchannel/qwebchannel.js")
    opened = f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text)
    if not opened:
        raise RuntimeError(
            "Could not load qwebchannel.js from Qt's built-in resources "
            "(:/qtwebchannel/qwebchannel.js). This usually means PySide6.QtWebChannel "
            "has not been imported yet. install() imports it automatically, so if you "
            "see this error you are likely calling _load_qwebchannel_js() directly, or "
            "your Qt installation does not ship the qtwebchannel resource. As a "
            "workaround, pass qwebchannel_js=<the file's contents> to install() "
            "explicitly (you can find qwebchannel.js inside your Qt/PySide6 installation)."
        )
    data = bytes(f.readAll().data()).decode("utf-8", errors="replace")
    f.close()
    _QWEBCHANNEL_JS_CACHE = data
    return data


def _replace_between(text, begin, end, replacement):
    """begin/endのマーカーコメントは残したまま、その間だけを置き換える
    (注入後のソースからも設定を機械的に取り出せるように)。"""
    i = text.index(begin) + len(begin)
    j = text.index(end, i)
    return text[:i] + replacement + text[j:]


def build_polyfill_js(*, locale="en", lock_navigator_usb=True, native_lookalike=True,
                      expose_commands=True, transport="webchannel", ws=None, version="",
                      debug=False, qwebchannel_js=None):
    """設定を埋め込んだ、注入用のポリフィルJSソースを返す。

    locale:              F12コマンド出力の言語('en'/'ja'/'zh')。
    lock_navigator_usb:  Navigator.prototype.usb を non-configurable にする(既定True)。
                         Falseにするとネイティブと同じ configurable:true になる。
    native_lookalike:    ポリフィルの関数を Function.prototype.toString で
                         `function x() { [native code] }` と見せる(既定True)。
    expose_commands:     window.__pysideWebUSB(非列挙)の独自コマンドを公開する。
    transport:           'webchannel'(QtWebEngine) か 'websocket'(QtWebView等)。
    ws:                  transport='websocket' のとき {"host","port","secret"}。
    qwebchannel_js:      qwebchannel.js の中身。指定するとクロージャ内へ取り込む。
                         省略時はページに既にある QWebChannel グローバルを使う
                         (テストや、ホストが自前で注入する構成向け)。
    debug:               Trueなら //# sourceURL を付け、DevToolsのSourcesで見つけやすくする。
    """
    config = {
        "locale": locale,
        "lockNavigatorUsb": bool(lock_navigator_usb),
        "nativeLookalike": bool(native_lookalike),
        "exposeCommands": bool(expose_commands),
        "transport": transport,
        "ws": ws,
        "version": version,
        "debug": bool(debug),
    }
    js = _replace_between(POLYFILL_JS_TEMPLATE, _CONFIG_RE_BEGIN, _CONFIG_RE_END,
                          json.dumps(config, ensure_ascii=True))
    if qwebchannel_js is not None:
        js = _replace_between(js, _QWC_BEGIN, _QWC_END,
                              "(function () {\n" + qwebchannel_js + "\nreturn QWebChannel;\n})()")
    if debug:
        js += "//# sourceURL=pyside6-webusb/polyfill.js\n"
    return js


# 既定設定のポリフィル(後方互換の公開定数。Nodeテストもこれを直接実行する)。
WEBUSB_POLYFILL_JS = build_polyfill_js()


def install(page, browser_window=None,
            settings_organization="pyside6-webusb", settings_application="WebUSBBridge",
            qwebchannel_js=None, locale=None, chooser_strings=None, extra_guard_js=None,
            *, lock_navigator_usb=True, native_lookalike=True, expose_commands=True,
            chooser=None, usb_backend=None, debug=False):
    """
    QWebEnginePage に navigator.usb ポリフィルを装着する(QtWebEngine向けの公開エントリポイント)。
    QtWebView(Android/iOS/macOS/Windowsのネイティブ・ウェブビュー)向けは
    pyside6_webusb.install_webview() を使う。

    page: QWebEnginePage。このページ(と、そのページで開かれる以降のドキュメント)上で
        navigator.usb が有効になる。
    browser_window: 任意。`.settings` (QSettingsインスタンス)属性を持つホストアプリの
        ウィンドウを渡すと、デバイス許可の永続化にそれを使う。省略時は
        settings_organization/settings_applicationでQSettingsへフォールバックする。
    settings_organization / settings_application: browser_window省略時に使う
        QSettingsの組織名・アプリ名(省略時は"pyside6-webusb"/"WebUSBBridge")。
        ⚠ 既定値のままだと、同じ既定値を使う別アプリと許可リストを共有する。
        製品では必ず自分の値を渡すこと。
    qwebchannel_js: 通常は不要(Qtの内蔵リソースから自動取得する)。取得に失敗する
        環境向けに、qwebchannel.jsの中身を直接渡すための上書き用パラメータ。
    locale / chooser_strings: デバイスチューザーダイアログの表示言語
        (WebUSBBridge(locale=, chooser_strings=)へ転送)。
    extra_guard_js: 任意のJavaScriptソース文字列。ポリフィルより前に別スクリプトとして
        注入され、`window.__pysideWebUSBExtraGuard = function({origin, filters,
        exclusionFilters}) { return true/false; }` を定義しておくと、requestDevice() は
        チューザーを開く前に必ずそれを呼び、厳密にfalseならSecurityErrorで拒否する。
        🆕 v0.0.6a: 関数はポリフィル起動時に1度だけ捕捉されるため、後からページが
        window.__pysideWebUSBExtraGuard を書き換え/削除してもガードは外せない。
    lock_navigator_usb: 🆕 v0.0.6a。Trueなら Navigator.prototype.usb を non-configurable にし、
        `delete Navigator.prototype.usb` や Object.defineProperty での差し替えを防ぐ。
        Falseにするとネイティブと完全に同じ記述子(configurable:true)になる。
    native_lookalike: 🆕 v0.0.6a。ポリフィルの関数を [native code] 表示にする。
    expose_commands: 🆕 v0.0.6a。window.__pysideWebUSB(非列挙)の独自コマンドを公開する。
    chooser: 🆕 v0.0.6a。デバイス選択UIの差し替え。callable(devices, origin, strings) ->
        選んだデバイス情報dict または None。省略時はQtWidgetsのダイアログ。
    usb_backend: (usb.core, usb.util)相当のペア。テストや独自バックエンド(Android等)向け。
    debug: 🆕 v0.0.6a。Trueなら注入JSへ //# sourceURL を付ける。

    戻り値: 生成した WebUSBBridge インスタンス(追加の配線やデバッグに使える)。
        QWebChannel自体が使えない環境では例外を送出せず None を返す
        (WebUSB機能だけが無効になり、アプリ全体は落とさない設計)。
    """
    from ._version import __version__
    from .bridge import WebUSBBridge
    from .frame_origin import FrameOriginTracker
    from .i18n import log_text, resolve_locale

    try:
        # PySide6.QtWebChannel/QtWebEngineCoreのimportもこのtry節の中に置く:
        # 環境によっては(QtWebEngineが別パッケージ化された開発版など)importに失敗し、
        # 「例外を送出せずNoneを返す」という約束をここで守るため。
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEngineScript

        bridge = WebUSBBridge(browser_window=browser_window, parent=page,
                              settings_organization=settings_organization,
                              settings_application=settings_application,
                              usb_backend=usb_backend, locale=locale,
                              chooser_strings=chooser_strings, chooser=chooser,
                              transport_kind="webchannel")
        channel = QWebChannel(page)
        channel.registerObject("pyUsbBridge", bridge)
        page.setWebChannel(channel)
    except Exception:
        return None

    try:
        tracker = FrameOriginTracker(page, locale=locale)
        tracker.wire()
        if tracker.is_functional:
            bridge._frame_tracker = tracker
        else:
            print(log_text(locale, "subframes_restricted"))
            bridge._frame_tracker = None
    except Exception as e:
        print(log_text(locale, "exception_ignored",
                       context="install(FrameOriginTracker)", error=e))
        bridge._frame_tracker = None

    try:
        qwc_js = qwebchannel_js if qwebchannel_js is not None else _load_qwebchannel_js()
    except Exception as e:
        print(log_text(locale, "exception_ignored", context="install(qwebchannel.js)", error=e))
        return bridge  # ブリッジ自体は生成済みだが、スクリプト注入はできていない

    loc = resolve_locale(locale)
    polyfill_js = build_polyfill_js(
        locale=loc, lock_navigator_usb=lock_navigator_usb, native_lookalike=native_lookalike,
        expose_commands=expose_commands, transport="webchannel", version=__version__,
        debug=debug, qwebchannel_js=qwc_js)

    # extra_guard_js は必ずポリフィルより前に注入する(ポリフィルが起動時に捕捉するため)。
    script_specs = []
    if extra_guard_js:
        script_specs.append(("PySide6WebUSBExtraGuard", extra_guard_js))
    script_specs.append(("PySide6WebUSBPolyfill", polyfill_js))

    for name, code in script_specs:
        try:
            script = QWebEngineScript()
            script.setName(name)
            script.setSourceCode(code)
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            # FrameOriginTrackerが正常に配線できた場合のみサブフレームでも実行する。
            # 配線に失敗した場合はFalse(安全側。WebUSBBridge._current_origin()参照)。
            script.setRunsOnSubFrames(bridge._frame_tracker is not None)
            page.scripts().insert(script)
        except Exception as e:
            print(log_text(locale, "exception_ignored", context="install(script)", error=e))

    return bridge
