# -*- coding: utf-8 -*-
"""
i18n.py
=======
🆕 v0.0.5b3: この配布物が今まで唯一の言語として持っていた文言(デバイスチューザー
ダイアログ、diagnostics.pyのレポート文言)に、English / 中文(简体) を追加した
組み込みロケールテーブル。

なぜ今まで存在しなかったか: chooser_dialog.py は元々 `strings=` 引数で任意の
辞書を差し込める設計だったが、それを実際に呼び出す唯一の経路
(bridge.py の `_request_device_chooser_impl` → `WebUsbDeviceChooserDialog(...)`)
は `strings=` を一切渡しておらず、常に英語の `DEFAULT_STRINGS` になっていた
(=ホストアプリ側の差し込み口はあっても、実際に差し込む配線が無かった)。
同様に diagnostics.py の文言は日本語決め打ちだった。本モジュールは翻訳文字列の
置き場所を1箇所にまとめ、install()/WebUSBBridge の新しい `locale=`/
`chooser_strings=` 引数(polyfill.py/bridge.py参照)がその配線を実際に完成させる。

⚠️ 後方互換性: 引数を何も指定しない(locale省略)場合のデフォルトは
`DEFAULT_LOCALE = "ja"` に固定してある。これは「気を利かせてOSのロケールに
自動追従する」のではなく、0.0.5.post6までこのパッケージが実際に出力していた
日本語文言と一言一句同じ出力を、引数無しの呼び出しに対して保ち続けるための
意図的な選択(diagnostics.pyの既存テストは検出された問題の見出し文言
"検出された問題:" や "見つかりません" 等を日本語の生文字列で直接assertして
おり、ここでデフォルトを変えるとテストだけでなく、この文言をそのままパース/
表示している既存のホストアプリ・CIログも静かに壊れる)。OSロケールへの
自動追従が欲しい場合は明示的に `locale="auto"`(resolve_locale/detect_locale
参照)を渡す——オプトインであり、デフォルトを変えない。

⚠️ diagnostics.py と同じ理由で、本モジュールはPySide6/QtCoreに一切依存しない
(トップレベルimportはosとlocale標準ライブラリのみ)。「PySide6が壊れている
環境を診断する」道具が言語選択のためだけにPySide6を要求しては本末転倒なため。
"""
import os

#: このパッケージが組み込みで持つロケール。増やす場合はCHOOSER_STRINGS/
#: DIAGNOSTICS_STRINGSの両方に同じキーを追加すること(test_i18n.pyが
#: 全ロケールで全キーが揃っていることを検証する)。
SUPPORTED_LOCALES = ("en", "ja", "zh")

#: 明示的な locale= を何も渡さなかった場合に使われるロケール。
#: 上のモジュールdocstring参照——0.0.5.post6までの既存の挙動(日本語決め打ち)を
#: そのまま保つための固定値であり、自動検出ではない。
DEFAULT_LOCALE = "ja"


def normalize_locale(locale):
    """任意のロケール文字列("ja_JP.UTF-8", "zh-Hans-CN", "EN" 等)を
    SUPPORTED_LOCALESのいずれかへ正規化する。None/空文字/認識できない値は
    すべて DEFAULT_LOCALE にフォールバックする——呼び出し元
    (チューザーダイアログ・診断レポート)がロケール文字列の妥当性で
    例外を出してはならないため、ここでは一切raiseしない。"""
    if not locale:
        return DEFAULT_LOCALE
    try:
        loc = str(locale).strip().lower().replace("_", "-")
    except Exception:
        return DEFAULT_LOCALE
    lang = loc.split("-", 1)[0]
    if lang in SUPPORTED_LOCALES:
        return lang
    return DEFAULT_LOCALE


def detect_locale():
    """OS/プロセスのロケールからの自動検出(ベストエフォート)。
    1. 環境変数 PYSIDE6_WEBUSB_LOCALE が優先(CI等での明示的な上書き用)。
    2. Python標準の locale モジュール(getlocale/getdefaultlocale)。
    3. どちらも得られなければ DEFAULT_LOCALE。
    resolve_locale(locale="auto") から使われる、明示的なオプトイン専用の
    関数——normalize_locale()と同様、一切raiseしない。"""
    env = os.environ.get("PYSIDE6_WEBUSB_LOCALE")
    if env:
        return normalize_locale(env)
    try:
        import locale as _locale
        loc = None
        try:
            loc = _locale.getlocale()[0]
        except Exception:
            pass
        if not loc:
            try:
                loc = _locale.getdefaultlocale()[0]  # noqa: F821 (Python<3.11のみ; 3.13+で削除予定だがtry/exceptで保護済み)
            except Exception:
                pass
        if loc:
            return normalize_locale(loc)
    except Exception:
        pass
    return DEFAULT_LOCALE


def resolve_locale(locale):
    """このパッケージの公開API全体(install()/WebUSBBridge/environment_report()/
    format_environment_report())が受け付ける locale= 引数の共通解決ルール。
        None    -> DEFAULT_LOCALE (0.0.5.post6までの既存の挙動をそのまま維持)
        "auto"  -> detect_locale() (明示的なオプトインでのみOSロケールへ追従)
        それ以外 -> normalize_locale(locale)
    """
    if locale is None:
        return DEFAULT_LOCALE
    if locale == "auto":
        return detect_locale()
    return normalize_locale(locale)


# ---------------------------------------------------------------------------
# デバイスチューザーダイアログ(chooser_dialog.py)の文言。
# "heading" は {origin} を埋め込む str.format() テンプレート。
# "serial_label" は本来どの言語でも共通の技術略号("SN")なのであえて
# 翻訳していない(逆に "不明なデバイス" 等はプレーンな文章なので翻訳する)。
# ---------------------------------------------------------------------------
CHOOSER_STRINGS = {
    "en": {
        "title": "Select a USB Device",
        "heading": "{origin} wants to connect to a USB device",
        "heading_no_origin": "This page wants to connect to a USB device",
        "trust_reminder": "Only connect devices from sites you trust.",
        "empty": "No compatible devices found.",
        "cancel": "Cancel",
        "connect": "Connect",
        "unknown_device": "Unknown device",
        "serial_label": "SN",
    },
    "ja": {
        "title": "USBデバイスを選択",
        "heading": "{origin} がUSBデバイスへの接続を求めています",
        "heading_no_origin": "このページがUSBデバイスへの接続を求めています",
        "trust_reminder": "信頼できるサイトからのデバイスのみ接続してください。",
        "empty": "対応するデバイスが見つかりません。",
        "cancel": "キャンセル",
        "connect": "接続",
        "unknown_device": "不明なデバイス",
        "serial_label": "SN",
    },
    "zh": {
        "title": "选择 USB 设备",
        "heading": "{origin} 请求连接一个 USB 设备",
        "heading_no_origin": "此页面请求连接一个 USB 设备",
        "trust_reminder": "请仅连接您信任的网站请求的设备。",
        "empty": "未找到兼容的设备。",
        "cancel": "取消",
        "connect": "连接",
        "unknown_device": "未知设备",
        "serial_label": "SN",
    },
}


def chooser_strings_for(locale):
    """指定ロケール(normalize_locale/resolve_locale適用後の"en"/"ja"/"zh")の
    チューザーダイアログ文言の辞書コピーを返す。未知の値は
    normalize_locale()経由でDEFAULT_LOCALEへフォールバックする。"""
    return dict(CHOOSER_STRINGS[normalize_locale(locale)])


# ---------------------------------------------------------------------------
# diagnostics.py (environment_report() / format_environment_report()) の文言。
# "ja" は0.0.5.post6までdiagnostics.py内に直接ハードコードされていた文言と
# 一言一句同じ(既存テストのassertする生文字列との互換性を保つため)。
# ---------------------------------------------------------------------------
DIAGNOSTICS_STRINGS = {
    "en": {
        "pyusb_import_error": "pyusb itself could not be imported (check 'pip install pyusb'): {error}",
        "pyusb_backend_missing": (
            "The OS-level libusb shared library could not be found (pyusb itself imported "
            "successfully). You need one of: Linux: the 'libusb-1.0-0' package / "
            "macOS: 'brew install libusb' / Windows: place libusb's DLL."
        ),
        "pyusb_backend_note_libusb0": (
            "The currently resolved backend is libusb0 (pyusb's fallback for when libusb1 "
            "cannot be found). This works, but on Python 3.14+, pyusb 1.3.1's libusb0 backend "
            "is confirmed to emit a DeprecationWarning about its ctypes.Structure "
            "_pack_/_fields_ combination (an upstream pyusb issue -- see the 'Environment "
            "note' in security_report/VULNERABILITY_REPORT.md). Installing an OS-level "
            "libusb1 shared library is recommended where possible."
        ),
        "pyside6_missing": (
            "PySide6 is not installed. Check that 'pip install pyside6-webusb''s dependencies "
            "(PySide6-Essentials/PySide6-Addons) resolved correctly."
        ),
        "qtwebengine_missing": (
            "PySide6 was found, but {missing} could not be imported. Depending on your "
            "PySide6 version, QtWebEngine may have been split out of PySide6-Addons into a "
            "separate PySide6-WebEngine package (try additionally running "
            "'pip install PySide6-WebEngine'). The PySide6-Addons installation itself may "
            "also be incomplete."
        ),
        "frame_isolation_unknown_note": "Cannot be determined because PySide6/QtWebEngineCore is unavailable.",
        "frame_isolation_available_note": (
            "Frame-level origin isolation (protection against cross-origin iframe "
            "impersonation) can be enabled (whether it actually is also depends on how "
            "polyfill.install() wires it up)."
        ),
        "frame_isolation_unavailable_note": (
            "This environment's PySide6 has no QWebEngineFrame (confirmed on real hardware: "
            "absent through 6.7.0, added in 6.8.0). Frame-level origin isolation from "
            "frame_origin.py cannot be enabled and falls back to the page.url()-based path "
            "-- weaker protection against cross-origin iframe impersonation than 6.8+. "
            "Consider upgrading to PySide6>=6.8 if you need this protection."
        ),
        "report_not_found": "not found",
        "report_qt_runtime_unknown": "unknown",
        "report_rust_enabled": "enabled",
        "report_rust_disabled": "disabled (falling back to the standard Python implementation; this does not affect functionality)",
        "report_frame_available": "available (this PySide6 has QWebEngineFrame)",
        "report_frame_unavailable": "unavailable (PySide6<6.8; falling back to the page-URL-based compatibility path)",
        "report_frame_unknown": "unknown (PySide6/QtWebEngineCore is unavailable)",
        "report_problems_header": "Problems detected:",
        "report_no_problems": "No problems detected.",
        "report_reference_prefix": "Note: {note}",
    },
    "ja": {
        "pyusb_import_error": "pyusb自体がimportできません('pip install pyusb'を確認してください): {error}",
        "pyusb_backend_missing": (
            "OS側のlibusb共有ライブラリが見つかりません(pyusb自体は正しくimportできています)。"
            "Linux: 'libusb-1.0-0' パッケージ / macOS: 'brew install libusb' / "
            "Windows: libusbのDLLを配置、のいずれかが必要です。"
        ),
        "pyusb_backend_note_libusb0": (
            "現在のバックエンドはlibusb0です(pyusbがlibusb1を見つけられなかった場合の"
            "フォールバック)。動作はしますが、Python 3.14以降でpyusb 1.3.1のlibusb0.py"
            "バックエンドがctypes.Structureの_pack_/_fields_の組み合わせについて"
            "DeprecationWarningを出すことを確認済みです(upstream pyusb側の課題。"
            "security_report/VULNERABILITY_REPORT.mdの「Environment note」参照)。"
            "可能であればOS側にlibusb1の共有ライブラリを導入してください。"
        ),
        "pyside6_missing": (
            "PySide6がインストールされていません。"
            "'pip install pyside6-webusb' の依存関係(PySide6-Essentials/PySide6-Addons)"
            "が正しく解決されているか確認してください。"
        ),
        "qtwebengine_missing": (
            "PySide6は見つかりましたが、{missing} をimportできません。"
            "PySide6のバージョンによっては、QtWebEngineがPySide6-Addonsとは別の"
            "PySide6-WebEngineパッケージに分離されている場合があります"
            "('pip install PySide6-WebEngine' を追加で試してください)。"
            "あるいはPySide6-Addonsのインストール自体が不完全な可能性があります。"
        ),
        "frame_isolation_unknown_note": "PySide6/QtWebEngineCoreが利用できないため判定できません。",
        "frame_isolation_available_note": (
            "フレーム単位のオリジン分離(cross-origin iframeのなりすまし対策)を"
            "有効化できます(実際に有効になるかはpolyfill.install()側の配線にも依存します)。"
        ),
        "frame_isolation_unavailable_note": (
            "この環境のPySide6にはQWebEngineFrameがありません(実機確認: 6.7.0以前には無く、"
            "6.8.0で追加されました)。frame_origin.pyによるフレーム単位のオリジン分離は"
            "有効化できず、page.url()を見る後方互換パスにフォールバックします——"
            "cross-origin iframeによるなりすまし対策としては6.8以降より弱くなります。"
            "この保護が必要な場合はPySide6>=6.8への更新を検討してください。"
        ),
        "report_not_found": "見つかりません",
        "report_qt_runtime_unknown": "不明",
        "report_rust_enabled": "有効",
        "report_rust_disabled": "無効(標準のPython実装にフォールバック中。動作には支障ありません)",
        "report_frame_available": "利用可能(PySide6にQWebEngineFrameあり)",
        "report_frame_unavailable": "利用不可(PySide6<6.8。ページURLベースの後方互換パスにフォールバック中)",
        "report_frame_unknown": "不明(PySide6/QtWebEngineCoreが利用できません)",
        "report_problems_header": "検出された問題:",
        "report_no_problems": "問題は検出されませんでした。",
        "report_reference_prefix": "参考: {note}",
    },
    "zh": {
        "pyusb_import_error": "无法导入 pyusb 本身(请确认已执行 'pip install pyusb'): {error}",
        "pyusb_backend_missing": (
            "未找到操作系统层面的 libusb 共享库(pyusb 本身已正确导入)。需要以下其中之一: "
            "Linux: 安装 'libusb-1.0-0' 软件包 / macOS: 执行 'brew install libusb' / "
            "Windows: 放置 libusb 的 DLL 文件。"
        ),
        "pyusb_backend_note_libusb0": (
            "当前解析到的后端是 libusb0(pyusb 在找不到 libusb1 时的回退方案)。这可以正常"
            "工作,但已确认: 在 Python 3.14 及以上版本中,pyusb 1.3.1 的 libusb0 后端会针对其 "
            "ctypes.Structure 的 _pack_/_fields_ 组合发出 DeprecationWarning(这是上游 "
            "pyusb 的问题,详见 security_report/VULNERABILITY_REPORT.md 中的 "
            "'Environment note')。如果可能,建议安装操作系统层面的 libusb1 共享库。"
        ),
        "pyside6_missing": (
            "未安装 PySide6。请确认 'pip install pyside6-webusb' 的依赖项"
            "(PySide6-Essentials/PySide6-Addons)已正确解析安装。"
        ),
        "qtwebengine_missing": (
            "已找到 PySide6,但无法导入 {missing}。根据 PySide6 版本不同,QtWebEngine 有可能"
            "已从 PySide6-Addons 中拆分为独立的 PySide6-WebEngine 软件包(请尝试额外执行 "
            "'pip install PySide6-WebEngine')。也可能是 PySide6-Addons 本身安装不完整。"
        ),
        "frame_isolation_unknown_note": "由于无法使用 PySide6/QtWebEngineCore,无法判定。",
        "frame_isolation_available_note": (
            "可以启用基于帧(frame)级别的来源隔离(用于防范跨源 iframe 仿冒)。实际是否"
            "启用还取决于 polyfill.install() 的具体接线方式。"
        ),
        "frame_isolation_unavailable_note": (
            "当前环境的 PySide6 中没有 QWebEngineFrame(经实机确认: 6.7.0 及以前版本没有,"
            "6.8.0 起才加入)。frame_origin.py 提供的帧级别来源隔离无法启用,将回退到基于 "
            "page.url() 的兼容路径——作为跨源 iframe 仿冒防护手段,其强度弱于 6.8 以上版本。"
            "如需此项防护,请考虑升级到 PySide6>=6.8。"
        ),
        "report_not_found": "未找到",
        "report_qt_runtime_unknown": "未知",
        "report_rust_enabled": "已启用",
        "report_rust_disabled": "未启用(已回退到标准 Python 实现,不影响功能)",
        "report_frame_available": "可用(此 PySide6 含有 QWebEngineFrame)",
        "report_frame_unavailable": "不可用(PySide6<6.8,已回退到基于页面 URL 的兼容路径)",
        "report_frame_unknown": "未知(无法使用 PySide6/QtWebEngineCore)",
        "report_problems_header": "检测到的问题:",
        "report_no_problems": "未检测到问题。",
        "report_reference_prefix": "参考: {note}",
    },
}


def diagnostics_text(locale, key, **kwargs):
    """DIAGNOSTICS_STRINGS[normalize_locale(locale)][key] を取り出し、kwargsが
    あれば str.format() で埋め込む。存在しないキーはKeyErrorを送出する
    (diagnostics.py側の呼び出しミス・キー名のtypoを早期に気付けるようにする
    ため、握りつぶさない——ここは"開発時に見つけたい"種類のバグなので、
    通常運用でこのパッケージ自身のロケール文字列がKeyErrorになることは無い)。"""
    text = DIAGNOSTICS_STRINGS[normalize_locale(locale)][key]
    return text.format(**kwargs) if kwargs else text
