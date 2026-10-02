# -*- coding: utf-8 -*-
"""
ws_transport.py  (🆕 v0.0.6a)
=============================
QWebChannelを使えない埋め込みウェブビュー(QtWebView: Android WebView / WKWebView /
WebView2 等)向けの転送層。ループバック(127.0.0.1)のQWebSocketServerが、WebUSBBridge の
公開スロットをそのままJSON-RPCで公開する。QtWebEngine用のQWebChannel転送と**同じ
スロット・同じ引数**を使うので、bridge.py側のUSB処理・許可管理は共通。

プロトコル(JSONテキストフレーム):
    server -> page   {"hello": 1}                          接続の受理(=検証済み)
    page   -> server {"i": 7, "m": "listDevices", "a": [...]}   呼び出し(応答あり)
    page   -> server {"m": "closeDevice", "a": [...]}           呼び出し(応答なし)
    server -> page   {"i": 7, "r": <スロットの戻り値>} / {"i": 7, "e": "<短いエラー>"}
    server -> page   {"ev": "connect"|"disconnect", "d": "{\\"vendorId\\":..,\\"productId\\":..}"}

セキュリティ設計(どれも実際にテストで確認している):
  1. 127.0.0.1のみにbind。パスは `/pyusb/<秘密>`(起動ごとのランダム値、定数時間比較)。
     別ブラウザの任意サイトやDNSリバインディングは秘密を知り得ないので接続できない。
  2. `Origin` ヘッダはブラウザが付けるもので、ページのJSは偽造できない。これを
     「呼び出し元フレームのオリジン」として使う(QWebChannelでのフレームトークン相当)。
     `null`(サンドボックスiframe/file:)や非http(s)は拒否。allowed_origins で更に絞れる。
  3. スロットの引数の「フレームトークン」は**常にこのサーバーが接続ごとに発行した
     値で上書き**する(JSが何を送っても無視)。他の接続のトークンは使えない。
  4. 呼び出せるのは、WebUSBBridgeが持つ「公開スロット」だけ(QWebChannelでJSから見える
     ものと同じ集合。メタオブジェクトから起動時に導出)。引数の個数と型(int/str/bool)を
     宣言どおりに検証する。
  5. 接続数・メッセージサイズに上限。接続が閉じたら、その接続が開いたデバイスを閉じる。
  6. ホットプラグ通知は「その接続のオリジンに許可済みのデバイス」だけに、VID/PIDのみで送る。
"""
import inspect
import json
import re
import secrets

from PySide6.QtCore import QMetaMethod, QObject
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocketProtocol, QWebSocketServer

from .frame_origin import url_to_origin

_MAX_MESSAGE_BYTES = 96 * 1024 * 1024      # 64MiB転送(base64で約85MiB)まで余裕を持たせた上限
_MAX_CONNECTIONS = 64
_MAX_ARGS = 10
_INT32_MIN, _INT32_MAX = -(2 ** 31), 2 ** 31 - 1
_ORIGIN_RE = re.compile(r"^(https?)://([A-Za-z0-9._\-\[\]:]+)$")
_SIG_RE = re.compile(r"^(\w+)\((.*)\)$")


class WebSocketFrameRegistry:
    """WebUSBBridge._frame_tracker 互換(origin_for_token だけを持つ)。
    トークン=WebSocket接続。接続が閉じたらトークンも失効する。"""

    def __init__(self):
        self._token_to_origin = {}

    def add(self, token, origin):
        self._token_to_origin[token] = origin

    def remove(self, token):
        self._token_to_origin.pop(token, None)

    def origin_for_token(self, token):
        if not token or not isinstance(token, str):
            return None
        return self._token_to_origin.get(token)

    @property
    def is_functional(self):
        return True


class _Connection:
    __slots__ = ("socket", "origin", "token", "handles", "verified")

    def __init__(self, socket, origin, token):
        self.socket = socket
        self.origin = origin
        self.token = token
        self.handles = set()
        self.verified = False


class _Method:
    __slots__ = ("fn", "param_names", "token_param", "arities")

    def __init__(self, fn, param_names, token_param, arities):
        self.fn = fn
        self.param_names = param_names
        self.token_param = token_param
        self.arities = arities   # {個数: [型名,...]}


def _coerce(value, type_name):
    """JSONで届いた値を、スロットの宣言型へ厳密に変換する。不正なら ValueError。"""
    if type_name in ("int", "qint32", "qint64", "uint", "short", "ushort"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("integer expected")
        return max(_INT32_MIN, min(_INT32_MAX, value))   # 範囲外はクランプ(上限はbridge側が拒否)
    if type_name in ("QString", "QByteArray"):
        if not isinstance(value, str):
            raise ValueError("string expected")
        return value
    if type_name == "bool":
        if not isinstance(value, bool):
            raise ValueError("boolean expected")
        return value
    raise ValueError("unsupported parameter type")


class WebSocketBridgeServer(QObject):
    """WebUSBBridgeをループバックWebSocketで公開するサーバー。"""

    def __init__(self, bridge, allowed_origins=None, host="127.0.0.1", port=0,
                 max_connections=_MAX_CONNECTIONS, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._allowed_origins = allowed_origins
        self._host = host
        self._requested_port = port
        self._max_connections = max_connections
        self._secret = secrets.token_urlsafe(32)
        self._registry = WebSocketFrameRegistry()
        self._server = None
        self._conns = {}          # id(socket) -> _Connection
        self._methods = {}
        self._listening = False

    # ---------------------------------------------------------------- lifecycle
    @property
    def registry(self):
        return self._registry

    @property
    def port(self):
        return self._server.serverPort() if self._server is not None else 0

    @property
    def secret(self):
        return self._secret

    def client_config(self):
        """ポリフィルへ埋め込む接続情報 {"host","port","secret"}。"""
        return {"host": self._host, "port": self.port, "secret": self._secret}

    def start(self):
        """待受を開始し、実際のポート番号を返す。失敗時は RuntimeError。"""
        if self._listening:
            return self.port
        self._methods = self._build_dispatch_table()
        server = QWebSocketServer("pyside6-webusb", QWebSocketServer.SslMode.NonSecureMode, self)
        server.setMaxPendingConnections(8)
        try:
            server.setHandshakeTimeout(5000)
        except Exception:
            pass
        server.originAuthenticationRequired.connect(self._on_origin_auth)
        server.newConnection.connect(self._on_new_connection)
        if not server.listen(QHostAddress(self._host), self._requested_port):
            raise RuntimeError("WebSocket bridge could not listen on %s: %s" % (self._host, server.errorString()))
        self._server = server
        self._listening = True
        self._bridge.add_hotplug_listener(self._on_hotplug)
        return server.serverPort()

    def stop(self):
        if not self._listening:
            return
        self._listening = False
        try:
            self._bridge.remove_hotplug_listener(self._on_hotplug)
        except Exception:
            pass
        for conn in list(self._conns.values()):
            self._drop(conn, close=True)
        try:
            self._server.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- policy
    def _origin_allowed(self, origin_header):
        """Originヘッダを検証し、正規化したオリジン(またはNone)を返す。"""
        if not isinstance(origin_header, str) or not _ORIGIN_RE.match(origin_header):
            return None
        from PySide6.QtCore import QUrl
        origin = url_to_origin(QUrl(origin_header))
        if not origin:
            return None
        policy = self._allowed_origins
        if policy is None:
            return origin
        try:
            if callable(policy):
                return origin if policy(origin) else None
            return origin if origin in {p.lower() for p in policy} else None
        except Exception:
            return None

    def _on_origin_auth(self, authenticator):
        try:
            authenticator.setAllowed(self._origin_allowed(authenticator.origin()) is not None)
        except Exception:
            try:
                authenticator.setAllowed(False)
            except Exception:
                pass

    # ---------------------------------------------------------------- dispatch table
    def _build_dispatch_table(self):
        """bridgeの公開スロット(=QWebChannelでJSから呼べる集合)を、型付きで表にする。"""
        # 注意: インスタンスの metaObject() ではなく、型の staticMetaObject を使う。
        #  (1) 型レベルには@Slotで宣言したスロットだけが載る。動的スロット(ホストがSignalを
        #      バウンドメソッドへ接続した結果)はインスタンス側にしか載らないので、
        #      「宣言した公開スロットだけをディスパッチする」という性質が成り立つ。
        #  (2) PySide6では、親付きのQObjectに対して inst.metaObject() を呼ぶと、返るQMetaObjectの
        #      Pythonラッパが(型と共有されたまま)そのインスタンスの子として登録され、親が
        #      C++側で破棄された瞬間に、同じラッパを返す Cls.staticMetaObject まで
        #      "already deleted" になる(実測。tests/・security_audit/のコメント参照)。
        mo = type(self._bridge).staticMetaObject
        arities = {}
        for i in range(mo.methodOffset(), mo.methodCount()):
            m = mo.method(i)
            if m.methodType() != QMetaMethod.MethodType.Slot or m.access() != QMetaMethod.Access.Public:
                continue
            match = _SIG_RE.match(bytes(m.methodSignature()).decode("ascii", "replace"))
            if not match:
                continue
            name, params = match.group(1), match.group(2)
            types = [t.strip() for t in params.split(",")] if params.strip() else []
            arities.setdefault(name, {})[len(types)] = types
        table = {}
        for name, per_arity in arities.items():
            fn = getattr(self._bridge, name, None)
            if not callable(fn):
                continue
            try:
                sig = inspect.signature(fn)
                names = [p.name for p in sig.parameters.values()]
            except (TypeError, ValueError):
                continue
            table[name] = _Method(fn, names, "frame_token" if "frame_token" in names else None, per_arity)
        return table

    def dispatchable_methods(self):
        """テスト/診断用: JSから呼べるメソッド名の集合。"""
        return set(self._methods)

    # ---------------------------------------------------------------- connections
    def _on_new_connection(self):
        while self._server is not None and self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            if sock is None:
                return
            self._accept(sock)

    def _accept(self, sock):
        origin = None
        try:
            origin = self._origin_allowed(sock.origin())
            # 注意: サーバー側のQWebSocket.resourceName()は(パスではなく)完全なURLを返すので、
            #      requestUrl().path() を使う(実機のQML WebViewからの接続で判明)。
            path_ok = secrets.compare_digest(sock.requestUrl().path(), "/pyusb/" + self._secret)
        except Exception:
            path_ok = False
        if origin is None or not path_ok or len(self._conns) >= self._max_connections:
            try:
                sock.close(QWebSocketProtocol.CloseCode.CloseCodePolicyViolated, "rejected")
            except Exception:
                pass
            sock.deleteLater()
            return
        try:
            sock.setMaxAllowedIncomingMessageSize(_MAX_MESSAGE_BYTES)
            sock.setMaxAllowedIncomingFrameSize(_MAX_MESSAGE_BYTES)
        except Exception:
            pass
        conn = _Connection(sock, origin, secrets.token_urlsafe(24))
        conn.verified = True
        self._conns[id(sock)] = conn
        self._registry.add(conn.token, origin)
        sock.textMessageReceived.connect(lambda text, c=conn: self._on_message(c, text))
        sock.disconnected.connect(lambda c=conn: self._drop(c, close=False))
        sock.sendTextMessage('{"hello":1}')

    def _drop(self, conn, close):
        if self._conns.pop(id(conn.socket), None) is None:
            return
        # この接続が開いたデバイスを閉じる(フレームが消えたのにハンドルが残らないように)
        for handle in list(conn.handles):
            try:
                self._bridge.closeDevice(handle, conn.token)
            except Exception:
                pass
        conn.handles.clear()
        self._registry.remove(conn.token)
        if close:
            try:
                conn.socket.close()
            except Exception:
                pass
        try:
            conn.socket.deleteLater()
        except Exception:
            pass

    # ---------------------------------------------------------------- RPC
    def _on_message(self, conn, text):
        try:
            msg = json.loads(text)
        except Exception:
            return
        if not isinstance(msg, dict):
            return
        call_id = msg.get("i")
        if call_id is not None and (isinstance(call_id, bool) or not isinstance(call_id, int)):
            return
        try:
            result = self._invoke(conn, msg.get("m"), msg.get("a"))
            reply = {"i": call_id, "r": result}
        except _RpcError as e:
            reply = {"i": call_id, "e": str(e)}
        except Exception as e:   # noqa: BLE001 - 詳細はページへ返さない
            try:
                self._bridge._log("ws_transport._invoke", e)
            except Exception:
                pass
            reply = {"i": call_id, "e": "internal error"}
        if call_id is not None:
            try:
                conn.socket.sendTextMessage(json.dumps(reply, ensure_ascii=False))
            except Exception:
                pass

    def _invoke(self, conn, name, args):
        if not isinstance(name, str):
            raise _RpcError("invalid method")
        method = self._methods.get(name)
        if method is None:
            raise _RpcError("unknown method")
        if not isinstance(args, list) or len(args) > _MAX_ARGS:
            raise _RpcError("invalid arguments")
        types = method.arities.get(len(args))
        if types is None:
            raise _RpcError("invalid arguments")
        kwargs = {}
        try:
            for pname, ptype, value in zip(method.param_names, types, args):
                kwargs[pname] = _coerce(value, ptype)
        except ValueError:
            raise _RpcError("invalid arguments")
        if method.token_param is not None:
            kwargs[method.token_param] = conn.token      # JSが送った値は無視して上書き
        result = method.fn(**kwargs)
        self._track_handles(conn, name, kwargs, result)
        return result

    def _track_handles(self, conn, name, kwargs, result):
        try:
            if name == "openDevice" and isinstance(result, str):
                data = json.loads(result)
                if data.get("success") is True and isinstance(data.get("handle"), int):
                    conn.handles.add(data["handle"])
            elif name == "closeDevice":
                conn.handles.discard(kwargs.get("handle_id"))
        except Exception:
            pass

    # ---------------------------------------------------------------- hotplug
    def _on_hotplug(self, kind, vendor_id, product_id):
        payload = json.dumps({"ev": kind, "d": json.dumps({"vendorId": vendor_id, "productId": product_id})})
        for conn in list(self._conns.values()):
            try:
                if self._bridge._is_granted(conn.origin, vendor_id, product_id):
                    conn.socket.sendTextMessage(payload)
            except Exception:
                pass


class _RpcError(Exception):
    pass
