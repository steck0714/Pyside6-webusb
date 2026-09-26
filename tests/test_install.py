# -*- coding: utf-8 -*-
"""install()(WEBUSB_POLYFILL_JS/qwebchannel.jsの注入設定)のテスト。

🛡️ 重要: 以前はここのテストが1件も無かった。install()自体はGUIを持たない
QObjectサブクラスでも(page.url()/setWebChannel()/scripts()さえ提供すれば)
軽量に検証できるにもかかわらず、この抜けのせいで
`script.setRunsOnSubFrames(True)` という、クロスオリジンiframeへ
navigator.usbを漏らしてしまう重大な設定ミスが長らく発見されずに残っていた
(詳細は CHANGELOG.md / bridge.py の WebUSBBridge._current_origin() の
docstring、および polyfill.py の install() 内コメントを参照)。

実際のQWebEngineScript/QWebChannelオブジェクトを使い、QWebEnginePageそのものは
使わず(GUI/レンダラを起動せず軽量に済ませるため)、install()が要求する
最小限のインターフェース(url()/setWebChannel()/scripts())だけを持つ
フェイクページに対してinstall()を実行する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pyside6_webusb.polyfill import install  # noqa: E402


class FakeScripts:
    """QWebEngineScriptCollection の代わり。insert()された本物の
    QWebEngineScript を後から検査できるようにリストへ集める。"""

    def __init__(self):
        self.inserted = []

    def insert(self, script):
        self.inserted.append(script)


class FakePage(QObject):
    """install()が要求する最小限のインターフェース(url()/setWebChannel()/
    scripts())だけを持つ、QWebEnginePageの軽量な代役。QWebChannel(page)は
    pageが本物のQObjectであることを要求するため、QObjectを継承している。"""

    def __init__(self, url="https://example.test/"):
        super().__init__()
        self._url = QUrl(url)
        self._scripts = FakeScripts()
        self.web_channel = None

    def url(self):
        return self._url

    def setWebChannel(self, channel):
        self.web_channel = channel

    def scripts(self):
        return self._scripts


def _make_app():
    return QApplication.instance() or QApplication([])


def test_install_returns_a_bridge_and_registers_the_web_channel():
    _make_app()
    page = FakePage()
    bridge = install(page, settings_organization="pyside6-webusb-tests", settings_application="test_install")
    assert bridge is not None
    assert page.web_channel is not None
    assert page.web_channel.registeredObjects().get("pyUsbBridge") is bridge
    print("test_install_returns_a_bridge_and_registers_the_web_channel: OK")


def test_install_injects_exactly_two_scripts_with_correct_injection_point_and_world():
    _make_app()
    page = FakePage()
    install(page, settings_organization="pyside6-webusb-tests", settings_application="test_install")
    names = sorted(s.name() for s in page._scripts.inserted)
    assert names == ["PySide6WebUSBPolyfill", "PySide6WebUSBQWebChannelLib"]
    for s in page._scripts.inserted:
        from PySide6.QtWebEngineCore import QWebEngineScript
        assert s.injectionPoint() == QWebEngineScript.InjectionPoint.DocumentCreation
        assert s.worldId() == QWebEngineScript.ScriptWorldId.MainWorld
        assert s.sourceCode(), f"{s.name()} のソースコードが空になっている"
    print("test_install_injects_exactly_two_scripts_with_correct_injection_point_and_world: OK")


def test_install_does_not_run_scripts_on_subframes():
    """🚨 これが今回のセキュリティ修正そのものの回帰テスト。
    WebUSBBridge._current_origin() はQWebEnginePage.url()(常にトップレベル
    フレームのURL)しか見ておらず、QWebChannel越しの呼び出しがどのフレーム
    (iframe)から来たかを区別する手段が無い。scriptがiframe内でも実行される
    (runsOnSubFrames=True)と、クロスオリジンiframeがトップレベルページに
    成りすまして、そのページが許可済みのUSBデバイスへ完全にアクセスできて
    しまう。安全側に倒し、メインフレームでしか navigator.usb を定義しない
    (runsOnSubFrames=False)ことを確認する。"""
    _make_app()
    page = FakePage()
    install(page, settings_organization="pyside6-webusb-tests", settings_application="test_install")
    assert len(page._scripts.inserted) == 2
    for s in page._scripts.inserted:
        assert s.runsOnSubFrames() is False, (
            f"{s.name()} が runsOnSubFrames=True のままだと、クロスオリジンiframeへ"
            "navigator.usbが漏れ、トップレベルページの許可済みUSBデバイスへ"
            "iframeが成りすましてアクセスできてしまう"
        )
    print("test_install_does_not_run_scripts_on_subframes: OK")


def test_install_is_scoped_to_the_pages_own_origin_not_a_shared_default():
    """install()を異なるオリジンの2つのFakePageに対して呼び、生成される
    WebUSBBridgeがそれぞれ自分のページのURLをオリジン判定に使うこと
    (=別ページ間で許可状態が混ざらないこと)を確認する。"""
    _make_app()
    page_a = FakePage(url="https://a.example/")
    page_b = FakePage(url="https://b.example/")
    bridge_a = install(page_a, settings_organization="pyside6-webusb-tests", settings_application="test_install")
    bridge_b = install(page_b, settings_organization="pyside6-webusb-tests", settings_application="test_install")
    assert bridge_a._current_origin() == "https://a.example"
    assert bridge_b._current_origin() == "https://b.example"
    print("test_install_is_scoped_to_the_pages_own_origin_not_a_shared_default: OK")


def test_install_returns_none_instead_of_raising_when_qtwebenginecore_is_unimportable(monkeypatch):
    """🛡️ バグ修正の回帰テスト(v0.0.5a1)。

    install()のdocstringは「QWebChannel自体が使えない環境では例外を送出せず
    Noneを返す」と約束しているが、修正前は`from PySide6.QtWebChannel import
    QWebChannel`/`from PySide6.QtWebEngineCore import QWebEngineScript`が
    本体のtry節より外(関数の一番最初)に置かれていたため、これら自体の
    importが失敗する環境では生のImportError/ModuleNotFoundErrorがそのまま
    送出され、約束が守られていなかった。

    PySide6 6.12.0a1開発版のwheelを実機確認したところ、QtWebEngineCoreが
    PySide6-Addonsから新設のPySide6-WebEngineという別パッケージへ分離されて
    いた(まだ正式リリースはされていない)ため、「PySide6-Addonsは入って
    いるがQtWebEngineCoreだけがimportできない」環境は今後起こり得る、
    実際に発生し得る状況として見つかった。

    sys.modulesへNoneを仕込む(test_diagnostics.pyの
    test_environment_report_detects_missing_pyside6と同じ、pytest公式に
    文書化された定石)ことでPySide6.QtWebEngineCoreだけをimport不能にし
    (PySide6自体・QtWebChannel等は本物のまま)、install()がNoneを返す
    (raiseしない)ことを確認する。monkeypatchはテスト終了時に自動で
    元へ戻すため、他のテストへの副作用は残らない。"""
    monkeypatch.setitem(sys.modules, "PySide6.QtWebEngineCore", None)
    _make_app()
    page = FakePage()
    result = install(page, settings_organization="pyside6-webusb-tests", settings_application="test_install")
    assert result is None
    assert page.web_channel is None, "QtWebEngineCoreのimportに失敗した時点で、QWebChannelの配線自体に進んでいないはず"
    print("test_install_returns_none_instead_of_raising_when_qtwebenginecore_is_unimportable: OK")


def test_install_injects_extra_guard_js_before_the_polyfill_when_given():
    """🆕 v0.0.5b3: extra_guard_js=を渡すと、qwebchannel.jsとPySide6WebUSBPolyfillの
    間に3本目のスクリプトとして注入されること、その内容・注入ポイント・World・
    runsOnSubFramesの扱いが他の2本と同じであることを確認する。渡さない場合
    (=このファイルの他のテストすべて)は従来どおり2本のままであることは
    既存のtest_install_injects_exactly_two_scripts_with_correct_injection_point_and_world/
    test_install_does_not_run_scripts_on_subframesが引き続き保証する。"""
    from PySide6.QtWebEngineCore import QWebEngineScript
    _make_app()
    page = FakePage()
    guard_src = "window.__pysideWebUSBExtraGuard = function(req) { return req.origin === 'https://allowed.example'; };"
    install(page, settings_organization="pyside6-webusb-tests", settings_application="test_install",
            extra_guard_js=guard_src)
    names = [s.name() for s in page._scripts.inserted]
    assert names == ["PySide6WebUSBQWebChannelLib", "PySide6WebUSBExtraGuard", "PySide6WebUSBPolyfill"], names
    guard_script = page._scripts.inserted[1]
    assert guard_script.sourceCode() == guard_src
    assert guard_script.injectionPoint() == QWebEngineScript.InjectionPoint.DocumentCreation
    assert guard_script.worldId() == QWebEngineScript.ScriptWorldId.MainWorld
    # runsOnSubFramesは他の2本と同じ値(bridge._frame_trackerの配線可否)に揃っているはず。
    assert guard_script.runsOnSubFrames() == page._scripts.inserted[0].runsOnSubFrames()
    assert guard_script.runsOnSubFrames() == page._scripts.inserted[2].runsOnSubFrames()
    print("test_install_injects_extra_guard_js_before_the_polyfill_when_given: OK")


def test_install_forwards_locale_and_chooser_strings_to_the_bridge():
    """🆕 v0.0.5b3: install()のlocale=/chooser_strings=がWebUSBBridgeまで届き、
    実際にチューザー文言の解決へ反映されることを確認する(配線の確認であり、
    文言の中身自体はtest_i18n.py/test_chooser_dialog.pyが担う)。"""
    _make_app()
    page = FakePage()
    bridge = install(page, settings_organization="pyside6-webusb-tests", settings_application="test_install",
                      locale="zh")
    assert bridge is not None
    assert bridge._resolve_chooser_strings()["cancel"] == "取消"

    page2 = FakePage(url="https://b.example/")
    bridge2 = install(page2, settings_organization="pyside6-webusb-tests", settings_application="test_install",
                       chooser_strings={"cancel": "NOPE"})
    assert bridge2._resolve_chooser_strings()["cancel"] == "NOPE"
    # locale省略時の既定(日本語)から、cancel以外は変わっていないことも確認する。
    assert bridge2._resolve_chooser_strings()["connect"] == "接続"
    print("test_install_forwards_locale_and_chooser_strings_to_the_bridge: OK")


if __name__ == "__main__":
    class _FakeMonkeypatch:
        """pytestなしでも走らせられるよう、monkeypatch.setitem相当を素朴に実装したもの
        (test_bridge.pyの_FakeMonkeypatchはsetattr版、こちらはsys.modules用のsetitem版)。"""
        def __init__(self):
            self._restore = []

        def setitem(self, mapping, key, value):
            self._restore.append((mapping, key, key in mapping, mapping.get(key)))
            mapping[key] = value

        def undo(self):
            for mapping, key, had_key, old_value in reversed(self._restore):
                if had_key:
                    mapping[key] = old_value
                else:
                    mapping.pop(key, None)
            self._restore.clear()

    mp = _FakeMonkeypatch()
    test_install_returns_a_bridge_and_registers_the_web_channel()
    test_install_injects_exactly_two_scripts_with_correct_injection_point_and_world()
    test_install_does_not_run_scripts_on_subframes()
    test_install_is_scoped_to_the_pages_own_origin_not_a_shared_default()
    test_install_returns_none_instead_of_raising_when_qtwebenginecore_is_unimportable(mp)
    mp.undo()
    test_install_injects_extra_guard_js_before_the_polyfill_when_given()
    test_install_forwards_locale_and_chooser_strings_to_the_bridge()
    print("ALL INSTALL TESTS PASSED")
