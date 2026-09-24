# -*- coding: utf-8 -*-
"""フレーム単位でのオリジン特定(per-frame origin attribution)。

背景(詳しくは CHANGELOG.md の 0.0.2b0 / 0.0.3 / 0.0.3a0 のエントリを参照):
WebUSBBridge._current_origin() は元々 QWebEnginePage.url() だけを見ていた。これは
常に「トップレベルフレームのURL」であり、ページ内のどのフレーム(iframe)から
QWebChannel経由の呼び出しが来たかを区別する手段が無かった。そのため
setRunsOnSubFrames(True) にすると、クロスオリジンiframeがトップレベルページに
成りすまして、そのページが許可済みのUSBデバイスへ完全にアクセスできてしまう
(0.0.2b0で修正: 一旦 setRunsOnSubFrames(False) にして安全側に倒した)。

このモジュールは、その後 0.0.3/0.0.3a0 で確認した以下の事実を使って、
実際にフレーム単位の判定を行う:
  - QWebEnginePage.mainFrame() / QWebEngineFrame.children() で、Qt/Chromium自身が
    把握しているフレーム木と各フレームの本当のURLを(JSを介さず)取得できる。
  - QWebEnginePage.navigationRequested(QWebEngineNavigationRequest&) が
    メインフレーム・サブフレームの区別なく、ナビゲーションのたびに発火する
    (実験で確認済み: 2つのiframeを含むページで3回発火し、それぞれ
    isMainFrame()とurl()が正しく取れた)。
  - QWebEngineFrame.runJavaScript(code) で、特定のフレームだけへコードを
    注入できる。

設計方針:
  Python側(=攻撃者が介入できない側)が、各フレームへ推測不可能なトークンを
  個別に配布し(そのフレームの実際のrunJavaScript()経由なので、他のフレームは
  同一オリジンポリシーにより読み取れない)、WEBUSB_POLYFILL_JS はブリッジ呼び出し
  のたびに「自分がPythonから受け取ったトークン」を引数として渡す。
  Pythonはそのトークンをトークン->オリジンの対応表で引き、呼び出し元の本当の
  オリジンを特定する。JSが「自分はこのオリジンです」と自己申告する値は一切
  信用しない(信用してしまうと、素のQWebChannelオブジェクトを直接叩く敵対的な
  フレームが、そのままトップレベルページに成りすませてしまうため)。

既知の制約(意図的な簡略化・現状の限界):
  - QWebEnginePageにはフレーム単位の「読み込み完了」シグナルが無いため、
    navigationRequested発火をきっかけに、少し遅延を置いてから
    mainFrame()/children()を再走査する方式を取っている。加えて保険として
    タイマーでの定期再走査も行う。フレームがナビゲーション後、実際にトークンが
    そのフレームへ届くまでの短い時間差は避けられない(その間はトークン未着で
    呼び出しが失敗する=安全側)。
  - QWebEngineFrameオブジェクトはmainFrame()/children()を呼ぶたびに新しい
    ラッパーが返ってくるようで(実機検証で確認: 同じiframeでもid()が呼び出しごとに
    変わることがある)、Python側のオブジェクトIDをフレームの安定した識別子として
    使うのは信頼できない。そのため「このフレームには既に有効なトークンを配って
    あるか」の判定はせず、再走査のたびに毎回新しいトークンを発行する単純な方式に
    している(無害だが再走査のたびにrunJavaScript呼び出しが増える点はやや非効率。
    トークン総数には上限を設けて際限ない増加だけは防いでいる)。
  - about:blankやfile://等、scheme+hostの組で意味のある「オリジン」を構成できない
    フレームにはトークンを配らない(=そのフレームからの呼び出しは常に拒否される。
    ブラウザの「不透明オリジン」の扱いに近い、安全側の判断)。
  - ネストしたiframe(iframe内のiframe)も再帰的に辿るが、非常に深いネストや、
    高頻度で動的に追加/削除されるフレームに対する動作は限定的にしか検証できて
    いない。
"""
import secrets

try:
    from PySide6.QtCore import QTimer
except Exception:  # pragma: no cover - PySide6が無い環境からのimport時に備える
    QTimer = None


def url_to_origin(qurl):
    """QUrlから 'scheme://host[:port]' 形式の正規化オリジン文字列を作る。
    判定不能な場合はNone(=どのオリジンにも許可を出さない、安全側に倒す)。
    WebUSBBridge._origin_from_url() と全く同じロジック(元々そちらにあったものを
    ここへ集約し、bridge.py側は薄いラッパーとしてこれを呼ぶ形にした)。"""
    try:
        if qurl is None or not qurl.isValid():
            return None
        scheme = (qurl.scheme() or "").lower()
        host = (qurl.host() or "").lower()
        if not scheme or not host:
            return None
        default_ports = {"http": 80, "https": 443}
        port = qurl.port(-1)
        if port == -1 or port == default_ports.get(scheme):
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"
    except Exception:
        return None


class FrameOriginTracker:
    """ページ内の各フレーム(メイン+サブフレーム)へトークンを配布し、
    トークンから本当のオリジンを引けるようにするクラス。

    install()から1ページにつき1個作られ、WebUSBBridge._frame_tracker として
    保持される。install()を使わない(=従来通りmake_bridge()等でbridgeだけを
    直接構築する)場合はこのクラス自体が使われず、WebUSBBridge._current_origin()
    は既存どおりpage.url()を直接見る後方互換パスへ自動的にフォールバックする。"""

    # 1プロセスで保持するトークンの総数の上限(際限ない増加を防ぐ安全弁)。
    # 挿入順を保つdictの先頭(=最も古い)から追い出す。
    _MAX_TOTAL_TOKENS = 256
    _RESCAN_DELAYS_MS = (0, 200, 1000)  # navigationRequested後、この間隔で再走査
    _PERIODIC_RESCAN_MS = 2000  # 保険としての定期再走査間隔

    def __init__(self, page):
        self._page = page
        self._token_to_origin = {}       # token(str) -> origin(str) (挿入順保持)
        self._periodic_timer = None
        self._wired = False
        self._navigation_signal_connected = False
        self._destroyed = False  # 🆕 v0.0.5b2: __init__.wire()/_on_page_destroyed()参照

    @property
    def is_functional(self):
        """navigationRequestedへ実際に接続できた場合のみTrue。
        古いPySide6/Qt(このシグナルやQWebEngineFrameが無いバージョン)や、
        pageがQWebEnginePageと十分互換のオブジェクトでない場合はFalseになる。
        install()はこれを見てsetRunsOnSubFrames()を決めるべき
        (Falseなら安全側に倒し、サブフレームへは注入しない)。

        🔍 実機検証(v0.0.5a1): QWebEngineFrameクラス自体は、PySide6 6.6.0/
        6.7.0には存在せず、6.8.0で初めて追加されたことを、3バージョンを
        実際に別々の環境へインストールしバイナリサーチして確認した
        (diagnostics.environment_report()の"frame_origin_isolation_available"
        で同じ判定を報告している)。つまりPySide6-Addons>=6.5という現在の
        サポート下限では、6.5〜6.7で本クラスが常にFalseとなり、
        WebUSBBridge._current_origin()はpage.url()を見る後方互換パス
        (0.0.2b0より前の、cross-origin iframeのなりすましに弱い判定)へ
        フォールバックする。バグではなく設計上のフォールバックだが、
        ホストアプリ開発者が気づけるようdiagnostics側で明示している。"""
        return self._navigation_signal_connected

    # ---- 配線 ----

    def wire(self):
        """navigationRequestedへ接続し、最初の走査を行う。install()から呼ばれる。
        例外が起きても(古いPySide6でnavigationRequested自体が無い場合等)
        呼び出し元を巻き込んで落ちないようにする。"""
        if self._wired:
            return
        self._wired = True
        try:
            self._page.navigationRequested.connect(self._on_navigation_requested)
            self._navigation_signal_connected = True
        except Exception as e:
            print(f"[pyside6-webusb] FrameOriginTracker.wire: navigationRequested接続に失敗(無視): {e}")
        if QTimer is not None:
            try:
                self._periodic_timer = QTimer(self._page)
                self._periodic_timer.setInterval(self._PERIODIC_RESCAN_MS)
                self._periodic_timer.timeout.connect(self.rescan)
                self._periodic_timer.start()
            except Exception as e:
                print(f"[pyside6-webusb] FrameOriginTracker.wire: 定期再走査タイマーの起動に失敗(無視): {e}")
        # 🐛 バグ修正(v0.0.5b2、実機のDevTools+ログ確認で発見。checklog2.md
        #    「45. QWebEnginePage Lifetime Observation」参照): 定期タイマーは
        #    QTimer(self._page) と親を指定しているため、page破棄時にQt自身が
        #    連鎖的に破棄してくれるはずだが、実機では「page破棄後に
        #    libshiboken: Internal C++ object (...QWebEnginePage) already
        #    deleted」というログが実際に観測された——特にnavigationRequested
        #    直後の遅延再走査(_on_navigation_requestedが使うQTimer.singleShot)
        #    はどのオブジェクトにも親子付けされていないstaticコールのため、
        #    親子関係による連鎖破棄の保護を一切受けない。rescan()自体は例外を
        #    捕まえて無視するだけなので落ちはしないが、pageが死んでいることを
        #    知る手立てがなく、以後も定期タイマーが2秒おきに同じ失敗を繰り返し、
        #    ログを埋め続けていた。QObjectが実際に破棄される直前に必ず発火する
        #    destroyedシグナルへ接続し、そこで即座にタイマーを止め以降の
        #    走査を全て短絡させる。
        try:
            self._page.destroyed.connect(self._on_page_destroyed)
        except Exception as e:
            print(f"[pyside6-webusb] FrameOriginTracker.wire: destroyed接続に失敗(無視): {e}")
        self.rescan()

    def _on_page_destroyed(self, _obj=None):
        """🆕 v0.0.5b2: pageのC++オブジェクトが破棄される直前に呼ばれる。
        この時点でpageへは(mainFrame()はおろか、いかなるメソッドも)もう
        触れてはならないので、ここでは自分自身の後始末だけを行う。"""
        self._destroyed = True
        if self._periodic_timer is not None:
            try:
                self._periodic_timer.stop()
            except Exception:
                pass

    def disconnect(self):
        """🆕 v0.0.5b2: 明示的な後始末用の公開メソッド。pageがまだ生きている
        うちにホストアプリ側からトラッカーを早期に止めたい場合(例:
        install()を同じpageへ対して呼び直す前や、bridgeを明示的に
        破棄する前)に使う。定期タイマーを止め、navigationRequested/
        destroyedへの接続をいずれも解除する——以後rescan()を呼んでも
        何もしない。pageが既に破棄済みでも安全に呼べる(各解除は
        例外を無視する)。"""
        self._destroyed = True
        if self._periodic_timer is not None:
            try:
                self._periodic_timer.stop()
            except Exception:
                pass
        if self._navigation_signal_connected:
            try:
                self._page.navigationRequested.disconnect(self._on_navigation_requested)
            except Exception:
                pass
            self._navigation_signal_connected = False
        try:
            self._page.destroyed.disconnect(self._on_page_destroyed)
        except Exception:
            pass

    def _on_navigation_requested(self, _request):
        if self._destroyed:
            return
        # request自体からはisMainFrame()/url()が取れるが、実際にQWebEngineFrame
        # オブジェクトとして木に現れるまで(特に新規iframeの場合)わずかに遅延が
        # あるため、複数回タイミングをずらして再走査する。
        if QTimer is None:
            self.rescan()
            return
        for delay in self._RESCAN_DELAYS_MS:
            try:
                QTimer.singleShot(delay, self.rescan)
            except Exception:
                pass

    # ---- 走査・トークン配布 ----

    def rescan(self):
        """現在のフレーム木を走査し、各フレームへトークンを(再)配布する。"""
        if self._destroyed:
            # 🆕 v0.0.5b2: destroyedシグナルで既に検知済みなら、
            # page.mainFrame()を試みることすらしない(上のwire()コメント参照)。
            return
        try:
            main = self._page.mainFrame()
        except Exception as e:
            print(f"[pyside6-webusb] FrameOriginTracker.rescan: mainFrame()取得失敗(無視): {e}")
            return
        if main is None:
            return
        try:
            self._walk(main)
        except Exception as e:
            print(f"[pyside6-webusb] FrameOriginTracker.rescan: フレーム走査中の例外(無視): {e}")

    def _walk(self, frame):
        self._assign_token(frame)
        try:
            children = frame.children() or []
        except Exception:
            children = []
        for child in children:
            self._walk(child)

    def _assign_token(self, frame):
        try:
            origin = url_to_origin(frame.url())
        except Exception:
            origin = None
        if not origin:
            return  # オリジンを特定できないフレーム(about:blank、file://等)には配らない

        token = secrets.token_urlsafe(24)
        self._token_to_origin[token] = origin
        while len(self._token_to_origin) > self._MAX_TOTAL_TOKENS:
            # dictは挿入順を保持するので、最初のキー(最も古く発行したトークン)から追い出す。
            oldest = next(iter(self._token_to_origin))
            del self._token_to_origin[oldest]

        try:
            # 🛡️ 実機検証の結果、QWebEngineFrame.runJavaScript()はコード文字列のみの
            #    1引数では "not enough arguments" になり、コールバック(無視してよい)を
            #    含めて最低2引数が必要と判明した。
            import json as _json
            frame.runJavaScript(f"window.__pyUsbFrameToken = {_json.dumps(token)};", lambda _result=None: None)
        except Exception as e:
            print(f"[pyside6-webusb] FrameOriginTracker._assign_token: runJavaScript失敗(無視): {e}")

    # ---- 解決 ----

    def origin_for_token(self, token):
        """トークンからオリジンを引く。不明なトークン(未発行・失効済み・偽造)
        の場合はNoneを返す(=呼び出し元は安全側に倒して拒否すること)。"""
        if not token:
            return None
        return self._token_to_origin.get(token)
