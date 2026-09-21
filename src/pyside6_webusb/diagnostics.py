# -*- coding: utf-8 -*-
"""
diagnostics.py
==============
🆕 v0.0.5a0: ホストアプリ/開発者向けの環境診断ユーティリティ。

「navigator.usbが動かない」「デバイスが一覧に出てこない」系の問い合わせの多くは、
実際にはこのパッケージ自体のロジックのバグではなく、周辺環境
(インストールされているPySide6/pyusbのバージョン、OS側のlibusb共有ライブラリの
有無、Rustアクセラレーションのビルド有無)に起因する。これまではその確認方法が
README中に散らばった説明とisAvailable()(JS/DevTools向け)しかなく、Pythonの
ホストアプリ側から一箇所で確認する手段が無かった。このモジュールはそのギャップを
埋める。

- `environment_report()`: 診断結果をJSON化可能なプリミティブ型のみの辞書として
  返す。ホストアプリが独自の「バージョン情報」画面やサポート用ログにそのまま
  埋め込める。
- `format_environment_report()`: 上記を人間が読むためのテキストに整形する。
- `python -m pyside6_webusb` (__main__.py) からコマンドラインでも直接実行できる。

⚠️ 意図的にPySide6/QtCoreに一切依存しない(importでもQApplicationの生成でも)。
「PySide6が正しくインストールされているか」自体を診断する道具が、その診断対象
であるPySide6が無いと動かないのでは本末転倒であるため——importの成否そのものが
診断結果の一部になる設計にしている。
"""
import platform

from ._version import __version__


def _pyside6_versions():
    """(pyside6_version, shiboken6_version, qt_runtime_version) のタプルを返す。
    いずれも取得できない場合はNoneになる(PySide6が全く入っていない場合や、
    バージョン属性を持たない極端に古い/壊れたインストールでも例外を投げない
    ——診断ツール自身が原因不明のクラッシュをしては本末転倒なため)。"""
    pyside6_version = None
    shiboken6_version = None
    qt_runtime_version = None
    try:
        import PySide6
        pyside6_version = getattr(PySide6, "__version__", None)
    except Exception:
        pass
    try:
        import shiboken6
        shiboken6_version = getattr(shiboken6, "__version__", None)
    except Exception:
        pass
    try:
        from PySide6.QtCore import qVersion
        qt_runtime_version = qVersion()
    except Exception:
        pass
    return pyside6_version, shiboken6_version, qt_runtime_version


def _pyusb_backend_info():
    """(pyusb_version, backend_name_or_None, problem_or_None) を返す。

    pyusbが「importできる」ことと「実際にUSBデバイスへアクセスできる」ことは
    別問題: pyusb自体は純Pythonパッケージなのでpipで必ず入るが、実際の通信は
    OS側のlibusb共有ライブラリ(.so/.dylib/.dll)にFFI越しで委譲しており、
    そちらが無いと`usb.core.find()`などが常に失敗する。この2段階を切り分けて
    報告することで、「pipでは入っているのになぜか動かない」という、この種の
    問い合わせで最も多いパターンを診断できるようにする。backend_nameは
    実際に解決できたバックエンド名('libusb1'/'libusb0')。"""
    pyusb_version = None
    try:
        import usb
        pyusb_version = getattr(usb, "__version__", None)
    except Exception as e:
        return None, None, f"pyusb自体がimportできません('pip install pyusb'を確認してください): {e}"

    backend_name = None
    try:
        import usb.backend.libusb1 as _libusb1
        if _libusb1.get_backend() is not None:
            backend_name = "libusb1"
    except Exception:
        pass
    if backend_name is None:
        try:
            import usb.backend.libusb0 as _libusb0
            if _libusb0.get_backend() is not None:
                backend_name = "libusb0"
        except Exception:
            pass

    problem = None
    if backend_name is None:
        problem = (
            "OS側のlibusb共有ライブラリが見つかりません(pyusb自体は正しくimportできています)。"
            "Linux: 'libusb-1.0-0' パッケージ / macOS: 'brew install libusb' / "
            "Windows: libusbのDLLを配置、のいずれかが必要です。"
        )
    return pyusb_version, backend_name, problem


def _rust_accel_status():
    """(rust_accelerated: bool, rust_accel_version_or_None) を返す。
    未ビルドでも本パッケージは完全に動作する(README「Rust acceleration
    (optional)」参照)ため、これは"problem"としては報告しない——単なる性能上の
    最適化がオプトインで効いているかどうかの情報。"""
    try:
        import pyside6_webusb_accel
        return True, getattr(pyside6_webusb_accel, "__version__", None)
    except ImportError:
        return False, None


def _qtwebengine_status():
    """(importable: bool | None, note_or_None) を返す。Noneは
    「PySide6自体が無いので判定不能(=既にpyside6_versionのNoneで報告済み)」。

    🔍 実機検証(v0.0.5a1、2026-09時点のPySide6 6.12.0a1開発版wheelを実際に
    展開して確認): QtWebEngineCore/QtWebEngineWidgetsの実体(.abi3.so/.pyi)
    が、もはやPySide6-Addonsのwheelには含まれておらず、新設の
    PySide6-WebEngineという別wheelへ分離されていた
    (`unzip -l pyside6_addons-*.whl`にQtWebEngineCore.abi3.soが無いことを
    確認/`unzip -l pyside6_webengine-*.whl`にはあることを確認)。
    この分離はまだ正式リリースには来ていない(PyPI上のpyside6-webengineは
    2026-09時点で存在しない=pip install pyside6-webengineは失敗する)ため、
    本パッケージのpyproject.tomlをこの時点でPySide6-WebEngine依存に
    変更することはできない(存在しないパッケージへの依存は
    `pip install pyside6-webusb`自体を壊す)。そのため今はここでの実行時
    診断としてのみ備え、正式リリースの動向を見て追従する
    (CHANGELOG参照)。"""
    try:
        import PySide6  # noqa: F401
    except Exception:
        return None, None
    missing = []
    try:
        from PySide6.QtWebEngineCore import QWebEngineScript  # noqa: F401
    except Exception:
        missing.append("QtWebEngineCore")
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except Exception:
        missing.append("QtWebEngineWidgets")
    if not missing:
        return True, None
    return False, (
        f"PySide6は見つかりましたが、{'/'.join(missing)} をimportできません。"
        "PySide6のバージョンによっては、QtWebEngineがPySide6-Addonsとは別の"
        "PySide6-WebEngineパッケージに分離されている場合があります"
        "('pip install PySide6-WebEngine' を追加で試してください)。"
        "あるいはPySide6-Addonsのインストール自体が不完全な可能性があります。"
    )


def _frame_origin_isolation_status():
    """(available: bool | None, note: str) を返す。

    availableは「QWebEngineFrameクラスがこの環境のPySide6に存在するか」の
    静的な可否のみを見る。実際にnavigationRequestedへ接続できるか
    (frame_origin.FrameOriginTracker.is_functional)は生きたQWebEnginePageが
    要るため、ここ(意図的にQApplicationを一切作らない診断ツール)では
    判定できない。Noneは判定不能(PySide6/QtWebEngineCore自体が無い)。

    🔍 実機検証(v0.0.5a1): PySide6 6.6.0/6.7.0にはQWebEngineFrameクラス
    自体が存在せず、6.8.0で初めて追加されたことを、3バージョンを実際に
    別々の venv へインストールしバイナリサーチして確認した。つまり
    PySide6-Addons>=6.5と宣言している現在のサポート範囲のうち6.5〜6.7では、
    frame_origin.pyによるcross-origin iframeのなりすまし対策は構造的に
    有効化できず、WebUSBBridge._current_origin()はpage.url()を見る
    後方互換パス(0.0.2b0より前の、より弱いオリジン判定)へ常に
    フォールバックする。これは既知の制約であってバグではないが、
    ホストアプリ開発者が気づけるよう明示的に報告する。"""
    try:
        import PySide6.QtWebEngineCore as _qtwec
    except Exception:
        return None, "PySide6/QtWebEngineCoreが利用できないため判定できません。"
    if hasattr(_qtwec, "QWebEngineFrame"):
        return True, (
            "フレーム単位のオリジン分離(cross-origin iframeのなりすまし対策)を"
            "有効化できます(実際に有効になるかはpolyfill.install()側の配線にも依存します)。"
        )
    return False, (
        "この環境のPySide6にはQWebEngineFrameがありません(実機確認: 6.7.0以前には無く、"
        "6.8.0で追加されました)。frame_origin.pyによるフレーム単位のオリジン分離は"
        "有効化できず、page.url()を見る後方互換パスにフォールバックします——"
        "cross-origin iframeによるなりすまし対策としては6.8以降より弱くなります。"
        "この保護が必要な場合はPySide6>=6.8への更新を検討してください。"
    )


def environment_report() -> dict:
    """現在の実行環境の診断結果を辞書として返す。JSON化可能なプリミティブ型
    (str/bool/None/list)のみで構成する。

    "problems" は今すぐ対処が要る項目のみ(PySide6が無い/libusbバックエンドが
    無い、等)。Rustアクセラレーション未ビルドはproblemsに含めない
    ——それ自体は正常な状態(フォールバックが正しく機能している)であるため。"""
    pyside6_version, shiboken6_version, qt_runtime_version = _pyside6_versions()
    pyusb_version, pyusb_backend, pyusb_problem = _pyusb_backend_info()
    rust_accelerated, rust_accel_version = _rust_accel_status()
    qtwebengine_importable, qtwebengine_note = _qtwebengine_status()
    frame_isolation_available, frame_isolation_note = _frame_origin_isolation_status()

    problems = []
    if pyside6_version is None:
        problems.append(
            "PySide6がインストールされていません。"
            "'pip install pyside6-webusb' の依存関係(PySide6-Essentials/PySide6-Addons)"
            "が正しく解決されているか確認してください。"
        )
    if qtwebengine_importable is False:
        problems.append(qtwebengine_note)
    if pyusb_problem is not None:
        problems.append(pyusb_problem)

    return {
        "pyside6_webusb_version": __version__,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "pyside6_version": pyside6_version,
        "shiboken6_version": shiboken6_version,
        "qt_runtime_version": qt_runtime_version,
        "qtwebengine_importable": qtwebengine_importable,
        "pyusb_version": pyusb_version,
        "pyusb_backend": pyusb_backend,
        "rust_accelerated": rust_accelerated,
        "rust_accel_version": rust_accel_version,
        # 🆕 v0.0.5a1: PySide6 6.8.0で追加されたQWebEngineFrameの静的な有無
        # (frame_origin.pyのフレーム単位オリジン分離が構造的に使えるか)。
        "frame_origin_isolation_available": frame_isolation_available,
        "frame_origin_isolation_note": frame_isolation_note,
        "problems": problems,
    }


def format_environment_report(report: dict = None) -> str:
    """environment_report()の結果を、人間が読むためのテキストレポートに整形する。
    reportを省略した場合はその場でenvironment_report()を呼ぶ。"""
    if report is None:
        report = environment_report()

    pyside6_line = f"PySide6: {report['pyside6_version'] or '見つかりません'}"
    if report["shiboken6_version"]:
        pyside6_line += f" (shiboken6 {report['shiboken6_version']})"

    pyusb_line = f"pyusb: {report['pyusb_version'] or '見つかりません'}"
    pyusb_line += f" (backend: {report['pyusb_backend'] or '見つかりません'})"

    if report["rust_accelerated"]:
        rust_line = "Rust acceleration: 有効"
        if report["rust_accel_version"]:
            rust_line += f" ({report['rust_accel_version']})"
    else:
        rust_line = "Rust acceleration: 無効(標準のPython実装にフォールバック中。動作には支障ありません)"

    # 🆕 v0.0.5a1
    if report.get("frame_origin_isolation_available") is True:
        frame_line = "Frame-level origin isolation: 利用可能(PySide6にQWebEngineFrameあり)"
    elif report.get("frame_origin_isolation_available") is False:
        frame_line = "Frame-level origin isolation: 利用不可(PySide6<6.8。ページURLベースの後方互換パスにフォールバック中)"
    else:
        frame_line = "Frame-level origin isolation: 不明(PySide6/QtWebEngineCoreが利用できません)"

    lines = [
        f"pyside6-webusb {report['pyside6_webusb_version']}",
        f"Python: {report['python_version']} ({report['python_implementation']}) on {report['platform']}",
        pyside6_line,
        f"Qt runtime: {report['qt_runtime_version'] or '不明'}",
        pyusb_line,
        rust_line,
        frame_line,
        "",
    ]
    if report["problems"]:
        lines.append("検出された問題:")
        for p in report["problems"]:
            lines.append(f"  - {p}")
    else:
        lines.append("問題は検出されませんでした。")
    if report.get("frame_origin_isolation_available") is False and report.get("frame_origin_isolation_note"):
        lines.append("")
        lines.append(f"参考: {report['frame_origin_isolation_note']}")
    return "\n".join(lines)
