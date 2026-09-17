# -*- coding: utf-8 -*-
"""🆕 v0.0.5a0: diagnostics.py(environment_report/format_environment_report)と
__main__.py(`python -m pyside6_webusb`)の新規テスト。

このファイルは意図的にQApplicationを生成しない(test_bridge.py等のconftest.py
経由のオフスクリーン設定に依存しない) -- diagnostics.py自身がQtCoreに一切
依存しない設計であることを、テスト自身の作りでも裏付けるため。"""
import os
import platform
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pyside6_webusb
from pyside6_webusb import diagnostics
from pyside6_webusb.diagnostics import environment_report, format_environment_report


def test_environment_report_reflects_the_running_interpreter_and_is_clean():
    """このテストを実際に動かしている環境(PySide6-Essentials/Addons 6.11.2、
    pyusb、libusb-1.0が全てインストール済み)では、diagnosticsは実際の
    バージョン文字列をそのまま反映し、problemsは空であるはず。"""
    report = environment_report()
    assert report["pyside6_webusb_version"] == pyside6_webusb.__version__
    assert report["python_version"] == platform.python_version()
    assert report["python_implementation"] == platform.python_implementation()

    import PySide6
    import shiboken6
    assert report["pyside6_version"] == PySide6.__version__
    assert report["shiboken6_version"] == shiboken6.__version__
    assert report["qt_runtime_version"], "Qt runtimeバージョンが取得できているはず"

    import usb
    assert report["pyusb_version"] == usb.__version__
    assert report["pyusb_backend"] in ("libusb1", "libusb0"), (
        "このテスト実行環境にはlibusb-1.0が入っているはずなのでbackendが解決されるはず"
    )
    assert report["problems"] == [], report["problems"]
    print("test_environment_report_reflects_the_running_interpreter_and_is_clean: OK")


def test_environment_report_detects_missing_pyside6(monkeypatch):
    """sys.modulesへNoneを仕込む(pytest公式に文書化された「モジュール未インストールを
    模す」定石)ことで、'import PySide6'自体をImportErrorにする。PySide6.QtCoreは
    このテストプロセス内で既に他モジュール経由でimport済み(=sys.modulesに
    キャッシュ済み)なので、'PySide6'だけをNoneにしても`from PySide6.QtCore import
    qVersion`はキャッシュされた実物をそのまま返してしまう(親パッケージの再チェックは
    そのサブモジュールが未キャッシュの場合にしか発生しないというCPythonのimport実装の
    詳細)。実際に「PySide6が全く入っていない」状況を再現するには、QtCore側の
    キャッシュエントリも合わせて塞ぐ必要がある。
    shiboken6はPySide6のサブモジュールではなく独立したパッケージなので、この操作でも
    影響を受けない(それぞれ独立にimportを試みる実装が正しくその独立性を反映して
    いることも合わせて確認する)。"""
    monkeypatch.setitem(sys.modules, "PySide6", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", None)
    report = environment_report()
    assert report["pyside6_version"] is None
    assert report["qt_runtime_version"] is None
    assert any("PySide6" in p for p in report["problems"]), report["problems"]
    print("test_environment_report_detects_missing_pyside6: OK")


def test_environment_report_detects_missing_pyusb(monkeypatch):
    monkeypatch.setitem(sys.modules, "usb", None)
    report = environment_report()
    assert report["pyusb_version"] is None
    assert report["pyusb_backend"] is None
    assert any("pyusb" in p for p in report["problems"]), report["problems"]
    print("test_environment_report_detects_missing_pyusb: OK")


def test_environment_report_detects_pyusb_installed_without_libusb_backend(monkeypatch):
    """pyusb自体はimportできるがOS側にlibusb共有ライブラリが無い、という
    (この種の問い合わせで最も多い)パターンを切り分けて検出できることを確認する。"""
    import usb.backend.libusb1 as libusb1_mod
    import usb.backend.libusb0 as libusb0_mod
    monkeypatch.setattr(libusb1_mod, "get_backend", lambda *a, **kw: None)
    monkeypatch.setattr(libusb0_mod, "get_backend", lambda *a, **kw: None)

    report = environment_report()
    assert report["pyusb_version"] is not None, "pyusb自体は正しくimportできているはず"
    assert report["pyusb_backend"] is None
    assert any("libusb" in p for p in report["problems"]), report["problems"]
    print("test_environment_report_detects_pyusb_installed_without_libusb_backend: OK")


def test_rust_accel_status_reflects_import_success_without_being_a_problem(monkeypatch):
    """Rust拡張は完全にオプション(README「Rust acceleration (optional)」参照)であり、
    未ビルドの状態は正常。problemsには含めないことを確認する。"""
    monkeypatch.setitem(sys.modules, "pyside6_webusb_accel", None)
    report = environment_report()
    assert report["rust_accelerated"] is False
    assert report["rust_accel_version"] is None
    assert not any("Rust" in p or "rust" in p for p in report["problems"]), report["problems"]

    fake_accel = type(sys)("pyside6_webusb_accel")
    fake_accel.__version__ = "0.1.0-test"
    monkeypatch.setitem(sys.modules, "pyside6_webusb_accel", fake_accel)
    report2 = environment_report()
    assert report2["rust_accelerated"] is True
    assert report2["rust_accel_version"] == "0.1.0-test"
    print("test_rust_accel_status_reflects_import_success_without_being_a_problem: OK")


def test_format_environment_report_lists_detected_problems():
    dirty_report = {
        "pyside6_webusb_version": "0.0.5a0", "python_version": "3.14.7",
        "python_implementation": "CPython", "platform": "Linux-test",
        "pyside6_version": None, "shiboken6_version": None, "qt_runtime_version": None,
        "pyusb_version": "1.3.1", "pyusb_backend": None,
        "rust_accelerated": False, "rust_accel_version": None,
        "problems": ["PySide6がインストールされていません。何かのメッセージ"],
    }
    text = format_environment_report(dirty_report)
    assert "検出された問題:" in text
    assert "PySide6がインストールされていません" in text
    assert "見つかりません" in text  # PySide6/backend欄がその旨を示しているはず

    clean_report = dict(dirty_report, problems=[], pyside6_version="6.11.2")
    clean_text = format_environment_report(clean_report)
    assert "問題は検出されませんでした。" in clean_text
    assert "検出された問題:" not in clean_text
    print("test_format_environment_report_lists_detected_problems: OK")


def test_format_environment_report_defaults_to_calling_environment_report():
    """report引数を省略した場合は、その場でenvironment_report()を呼ぶこと。"""
    text = format_environment_report()
    assert "pyside6-webusb" in text
    assert pyside6_webusb.__version__ in text
    print("test_format_environment_report_defaults_to_calling_environment_report: OK")


def test_main_returns_zero_when_clean_and_nonzero_when_problems(monkeypatch, capsys):
    import pyside6_webusb.__main__ as main_mod

    monkeypatch.setattr(main_mod, "environment_report", lambda: {
        "pyside6_webusb_version": "0.0.5a0", "python_version": "3.14.7",
        "python_implementation": "CPython", "platform": "Linux-test",
        "pyside6_version": "6.11.2", "shiboken6_version": "6.11.2", "qt_runtime_version": "6.11.2",
        "pyusb_version": "1.3.1", "pyusb_backend": "libusb1",
        "rust_accelerated": False, "rust_accel_version": None,
        "problems": [],
    })
    assert main_mod.main() == 0
    assert "問題は検出されませんでした" in capsys.readouterr().out

    monkeypatch.setattr(main_mod, "environment_report", lambda: {
        "pyside6_webusb_version": "0.0.5a0", "python_version": "3.14.7",
        "python_implementation": "CPython", "platform": "Linux-test",
        "pyside6_version": None, "shiboken6_version": None, "qt_runtime_version": None,
        "pyusb_version": None, "pyusb_backend": None,
        "rust_accelerated": False, "rust_accel_version": None,
        "problems": ["PySide6がインストールされていません"],
    })
    assert main_mod.main() == 1
    assert "検出された問題" in capsys.readouterr().out
    print("test_main_returns_zero_when_clean_and_nonzero_when_problems: OK")


def test_package_import_and_install_survive_pyside6_being_unavailable():
    """🆕 v0.0.5a0: 実際にこの不具合が発生し、修正した際の回帰テスト。

    修正前は、PySide6-Essentials/PySide6-Addonsのどちらかでも欠けている環境では
    `import pyside6_webusb`自体が__init__.py経由でbridge.pyの
    `from PySide6.QtCore import ...`に到達し、生のModuleNotFoundErrorで落ちていた——
    つまり、まさに`python -m pyside6_webusb`/`pyside6-webusb-doctor`が助けになるべき
    「PySide6周りの環境が壊れている」状況で、その診断ツール自身が起動不能になるという
    本末転倒が実際に起きていた(`--no-deps`でwheelだけをインストールした、まっさらな
    仮想環境への実インストールで発見)。

    「PySide6が無い」を再現するのに`sys.modules[...] = None`は使わない: 一度試した
    ところ、PySide6が実際にインストールされたこのテスト環境では、shiboken6が
    site初期化時に仕込むシグネチャ内省用の`.pth`フック(shibokensupport)が
    「後からNoneで塞がれたPySide6」という想定外の状態に反応してこのテスト自身とは
    無関係な例外を出して落ちることが分かった(このバグ自体の実在を疑わせるものでは
    なく、あくまでこのテストの模し方の問題)。代わりに`python -S`
    (siteモジュール自体の初期化=`.pth`処理を丸ごと止める)と、`pyside6_webusb`
    自身の`src/`だけを指す`PYTHONPATH`を組み合わせ、site-packages(PySide6/pyusb
    含む)がそもそもパス上に存在しない、正真正銘「PySide6が入っていない」
    プロセスを作る——最初にこの不具合を発見した`--no-deps`実インストールに近い、
    より現実的な再現方法でもある。"""
    import subprocess

    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    script = """
import pyside6_webusb
print("import_ok=" + pyside6_webusb.__version__)

from pyside6_webusb import environment_report
report = environment_report()
print("pyside6_version=" + str(report["pyside6_version"]))
assert report["pyside6_version"] is None

for name in ("install", "WebUSBBridge", "WebUsbDeviceChooserDialog"):
    obj = getattr(pyside6_webusb, name)
    try:
        obj()
        print(name + "=NO_ERROR_RAISED")
    except ImportError as e:
        assert "PySide6" in str(e)
        print(name + "=CLEAN_IMPORTERROR")

assert pyside6_webusb.WEBUSB_POLYFILL_JS is None
print("ALL_OK")
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", script],
        env={"PYTHONPATH": src_dir, "PATH": os.environ.get("PATH", "")},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "import_ok=0.0.5.post1" in result.stdout, result.stdout
    assert "pyside6_version=None" in result.stdout, result.stdout
    assert "install=CLEAN_IMPORTERROR" in result.stdout, result.stdout
    assert "WebUSBBridge=CLEAN_IMPORTERROR" in result.stdout, result.stdout
    assert "WebUsbDeviceChooserDialog=CLEAN_IMPORTERROR" in result.stdout, result.stdout
    assert "ALL_OK" in result.stdout, result.stdout
    print("test_package_import_and_install_survive_pyside6_being_unavailable: OK")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
