# -*- coding: utf-8 -*-
"""
native_messaging.py
====================
🆕 v0.0.6: Chrome/Firefoxの「Native Messaging」プロトコル
(https://developer.chrome.com/docs/apps/nativeMessaging ,
https://developer.mozilla.org/docs/Mozilla/Add-ons/WebExtensions/Native_messaging
の両公式ドキュメントで、ホスト側実装者向けに公開されている安定したワイヤ
フォーマット)向けの、最小限のメッセージ入出力ユーティリティと、ホスト登録用
manifest.jsonの静的チェッカーを提供する。

なぜこのモジュールがpyside6-webusbにあるか
-------------------------------------------
姉妹プロジェクトのfox-webusb(Firefox WebExtension + 独立したnative
messagingホストプロセスによってnavigator.usbのポリフィルを実現する
プロジェクト)は、pyside6-webusbのようにQtWebEngineへ直接埋め込むのでは
なく、ブラウザ標準のnative messaging機構「だけ」を使って、ページ側のJSから
navigator.usb相当のAPIがまるで動いているかのように見せる——つまり
"native codeでnavigator.usbが機能しているように見える"別の実現方式を
取っている。この方式の要点は、ブラウザの拡張機能(content script)が
browser.runtime.connectNative()でOS上のネイティブ実行ファイルへ接続し、
以降は標準入出力(stdin/stdout)を介してこの4byte長プレフィックス付き
JSONメッセージをやり取りするだけ、という点にある——QWebChannelもQt自体も
一切不要であり、実際にどんなプログラミング言語で書かれたホストプロセスでも
拡張機能側からは区別が付かない。

この方式の実運用上の弱点は、pyside6-webusbのdiagnostics.pyがPySide6/libusb
側で解決してきた「動かない理由の切り分け」を、native messaging側でも
必要とすることだ: manifest.jsonの配置場所の誤り・必須キーの欠落・pathが
指す実行可能ファイルの不在などは、ブラウザ側は正常に動いているのにホスト
プロセスだけが起動しない、という原因の分かりにくい失敗を起こしやすい
(diagnostics.pyのモジュールdocstringが述べる問題意識と同じもの)。

本モジュールはfox-webusb全体(実際のpyusb/libusb直結のUSBバックエンド、
Ed25519によるローカル認証、Tkinter製チューザーダイアログ等)を複製する
ものではない——それらは既にfox-webusb自身が独立したプロジェクトとして
持っている。ここに置くのは意図的に次の2つだけに絞っている:

    1. ワイヤフォーマット部分(read_message()/write_message())。
       Chrome/Firefox双方のドキュメントに明記された安定したプロトコルの
       実装であり、fox-webusbのホストプロセス実装からもこのまま
       import して使い回せる(=同じプロトコルを2つのプロジェクトで
       別々に、独立に実装してバグを2箇所に作り込む必要が無くなる)。

    2. manifest.json単体の静的検査(validate_native_messaging_manifest()/
       format_manifest_check())。pyside6-webusb-doctorコマンドの哲学
       ("動かない理由をこのパッケージ自身のツールで切り分けられるように
       する")を、native messaging方式のデプロイにも広げたもの。

使用例::

    # ホストプロセス本体(標準入出力を使う典型的な形)
    import sys
    from pyside6_webusb.native_messaging import read_message, write_message

    while True:
        msg = read_message(sys.stdin.buffer)
        if msg is None:
            break  # ブラウザ側がパイプを閉じた(正常な終了)
        write_message(sys.stdout.buffer, {"ok": True, "echo": msg})

    # manifest.jsonのチェック(pyside6-webusb-doctor --check-native-messaging
    # からもこの関数を使う。詳細は__main__.py参照)
    from pyside6_webusb.native_messaging import validate_native_messaging_manifest
    problems, warnings = validate_native_messaging_manifest("/path/to/manifest.json")
"""
import json
import os
import struct


class NativeMessagingError(Exception):
    """メッセージの読み書き中に発生したプロトコルエラー(不正な長さ・
    JSON解析失敗・サイズ超過・ストリームの予期しない途切れ等)をまとめて
    表す例外。"""
    pass


# 🔍 出典についての注記: 4byte長プレフィックス(ネイティブバイト順)+
# UTF-8 JSON、というワイヤフォーマットそのものは、Chrome/Firefox双方が
# 長年公開しているnative messagingホスト実装者向けドキュメントに明記
# された、安定した仕様である。一方でDEFAULT_MAX_MESSAGE_BYTES(メッセージ
# 1件あたりの上限)の具体的な数値はブラウザ側の実装依存で将来変更され
# 得るため、ここでは意図的に安全側の保守的な値を既定にしている——本
# パッケージの他の箇所にあるような「実ソースで確認済み」の数値とは性質が
# 異なる。正確な最新の上限は各ブラウザの公式ドキュメントを確認すること
# を推奨する。呼び出し側はmax_bytes=で必要に応じて調整できる。
DEFAULT_MAX_MESSAGE_BYTES = 1024 * 1024  # 1 MiB


def write_message(stream, obj, max_bytes=DEFAULT_MAX_MESSAGE_BYTES):
    """objをUTF-8 JSONへシリアライズし、4byte長プレフィックス(ネイティブ
    バイト順、符号なし32bit、struct.pack("=I", ...))を先頭に付けてstreamへ
    書き込む。

    streamはバイナリモードで開かれたファイル/パイプ/BytesIO等、
    .write(bytes)を持つものを想定する(例: sys.stdout.buffer)。
    テキストモードのsys.stdoutをそのまま渡すと、プラットフォームに
    よっては改行コード変換(\\n → \\r\\n)でJSONペイロード中の値やフレーミング
    そのものが壊れるため不可。"""
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if len(payload) > max_bytes:
        raise NativeMessagingError(
            f"message too large: {len(payload)} bytes (max {max_bytes}); "
            "native messaging hosts should keep individual messages small"
        )
    stream.write(struct.pack("=I", len(payload)))
    stream.write(payload)
    if hasattr(stream, "flush"):
        # 🛡️ パイプはバッファリングされ得るため、明示的にflushしないと
        # ブラウザ側がメッセージの到着にすぐ気付けない場合がある。
        stream.flush()


def _read_exact(stream, n):
    """ちょうどn byte読めるまでstream.read()を繰り返す(パイプ越しのI/Oは
    1回のread(n)呼び出しが必ずしもn byteぴったり返すとは限らないため——
    これを1回のread(n)で済ませてしまうのは、ネイティブメッセージング
    ホストの実装でありがちな見落としの一つ)。

    最初の1byte目すら読めなかった場合(=ブラウザ側がパイプを閉じた。
    拡張機能のアンインストール・ブラウザの終了等で起きる、ホスト側の
    正常な終了経路)はNoneを返す——例外にはしない。それ以外の「一部だけ
    読めた後で途切れた」場合は、不完全なメッセージを黙って握りつぶさない
    よう、NativeMessagingErrorを送出する。"""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if not chunks:
                return None
            raise NativeMessagingError(
                f"stream ended mid-message: got {n - remaining} of {n} expected bytes"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(stream, max_bytes=DEFAULT_MAX_MESSAGE_BYTES):
    """4byte長プレフィックスを読み、その長さぶんのUTF-8 JSONを読んで
    デコードして返す(通常はdict、送信側の実装次第でlist等の他のJSON型も
    あり得る)。

    ストリームが最初の4byteすら返さず終端した場合(=ブラウザ側がパイプを
    閉じた、正常な終了経路)はNoneを返す。長さプレフィックスがmax_bytesを
    超えている、途中でストリームが途切れた、JSONとして解析できない、
    のいずれの場合もNativeMessagingErrorを送出する。"""
    header = _read_exact(stream, 4)
    if header is None:
        return None
    (length,) = struct.unpack("=I", header)
    if length > max_bytes:
        raise NativeMessagingError(f"message too large: {length} bytes (max {max_bytes})")
    payload = _read_exact(stream, length)
    if payload is None:
        raise NativeMessagingError(f"stream ended before the {length}-byte message body")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise NativeMessagingError(f"message body is not valid UTF-8 JSON: {e}") from e


# ---------------------------------------------------------------------------
# manifest.json の静的検査
# ---------------------------------------------------------------------------
_REQUIRED_MANIFEST_KEYS = ("name", "description", "path", "type")


def validate_native_messaging_manifest(manifest, locale=None):
    """native messagingホスト登録用のmanifest.jsonを検査する。

    manifest引数は次のいずれか:
      - ファイルパス(str): 開いてJSONとして読み込む。
      - 既に読み込み済みのdict。

    戻り値は (problems, warnings) のタプル(どちらも文字列のリスト。
    localeで指定した言語——省略時はi18n.DEFAULT_LOCALE)。problemsは
    ブラウザがこのホストを起動できない可能性が高い重大な欠陥、warningsは
    致命的ではないが確認を推奨する点を指す。

    🛡️ 意図的なスコープ外(ここで**確認しないこと**): 実際にOS側の
    しかるべき場所(Windowsならレジストリ、macOS/Linuxなら所定の
    ディレクトリ)へこのmanifest.json自体が登録されているかどうか——これは
    実行中のブラウザ・OSの状態に依存し、Pythonから一般的に確認する手段が
    無い。本関数が見るのはmanifest.json**単体の中身**が要件を満たしているか
    だけである(diagnostics.environment_report()がPySide6/libusb側の状態を
    見るのと同じ立ち位置で、native messaging側の状態を見るものではない)。"""
    from .i18n import native_messaging_text, resolve_locale
    loc = resolve_locale(locale)
    problems = []
    warnings = []
    base_dir = None

    if isinstance(manifest, str):
        base_dir = os.path.dirname(os.path.abspath(manifest))
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError as e:
            problems.append(native_messaging_text(loc, "manifest_unreadable", path=manifest, error=str(e)))
            return problems, warnings
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as e:
            problems.append(native_messaging_text(loc, "manifest_invalid_json", error=str(e)))
            return problems, warnings

    if not isinstance(manifest, dict):
        problems.append(native_messaging_text(loc, "manifest_not_an_object"))
        return problems, warnings

    for key in _REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            problems.append(native_messaging_text(loc, "manifest_missing_key", missing_key=key))

    manifest_type = manifest.get("type")
    if manifest_type is not None and manifest_type != "stdio":
        problems.append(native_messaging_text(loc, "manifest_unsupported_type", type=manifest_type))

    path = manifest.get("path")
    if isinstance(path, str) and path:
        resolved = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir or ".", path))
        if not os.path.exists(resolved):
            problems.append(native_messaging_text(loc, "manifest_path_missing", path=path, resolved=resolved))
        elif os.name != "nt" and not os.access(resolved, os.X_OK):
            # 🔍 Windowsではos.access(X_OK)が拡張子ベースの判定になり実行
            # 可否を正しく反映しないため、Windows以外でのみ確認する。
            warnings.append(native_messaging_text(loc, "manifest_path_not_executable", path=resolved))

    allowed_origins = manifest.get("allowed_origins")
    allowed_extensions = manifest.get("allowed_extensions")
    has_chrome_origins = isinstance(allowed_origins, list) and len(allowed_origins) > 0
    has_firefox_extensions = isinstance(allowed_extensions, list) and len(allowed_extensions) > 0
    if not has_chrome_origins and not has_firefox_extensions:
        problems.append(native_messaging_text(loc, "manifest_missing_allowed_list"))

    return problems, warnings


def format_manifest_check(path, problems, warnings, locale=None):
    """validate_native_messaging_manifest()の結果を、
    diagnostics.format_environment_report()と同じ構成(見出し→問題点の
    箇条書き→(問題が無ければ)"問題なし"の一文→注記)で読みやすいテキストに
    整形する。problems/warningsの見出し自体はdiagnostics.pyの既存文言
    (i18n.diagnostics_text)を再利用する——「問題を列挙する」という構造は
    diagnostics.pyの環境レポートと全く同じであり、別の言い回しを新たに
    3言語ぶん用意する意味が無いため。"""
    from .i18n import diagnostics_text, native_messaging_text, resolve_locale
    loc = resolve_locale(locale)
    lines = [native_messaging_text(loc, "check_header", path=path), ""]
    if problems:
        lines.append(diagnostics_text(loc, "report_problems_header"))
        for p in problems:
            lines.append(f"  - {p}")
    else:
        lines.append(diagnostics_text(loc, "report_no_problems"))
    for w in warnings:
        lines.append(diagnostics_text(loc, "report_reference_prefix", note=w))
    return "\n".join(lines)
