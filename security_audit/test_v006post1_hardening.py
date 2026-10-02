# -*- coding: utf-8 -*-
"""0.0.6.post1 (開発名 v0.0.6a) で見つけて直した問題の回帰テスト(security_audit No.9〜No.12)。

No.9   内部メソッド/QObject由来スロットがQWebChannel経由で任意のページから呼べた
       (_on_page_navigated で他オリジンのデバイスハンドルを破棄、deleteLater()でブリッジごと破棄)
No.10  オリジンを特定できないフレーム(about:blank/data:/file:/sandbox iframe)でもチューザーが開き、
       許可が記録されないまま完全な記述子が呼び出し元へ返った
No.11  ホットプラグ通知(全フレームへブロードキャスト)に製品名・シリアル番号まで載っていた
No.12  差し替え可能チューザー: 提示していないデバイスを返す/例外を投げるチューザーへの耐性

実機のQtWebEngine上でNo.9が再現することは、修正前のコードに対して確認済み
(CHANGELOG 0.0.6.post1 / security_report 参照)。ここではQt単体で判定できる形に落としている。
"""
import json

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QTimer, QUrl, Signal

from _fixtures import FakeConfiguration, FakeDevice, make_bridge
from pyside6_webusb.bridge import WebUSBBridge


class _FakePage(QObject):
    urlChanged = Signal(QUrl)

    def url(self):
        return QUrl("https://page.example/")


def _spin(ms=0):
    """イベントループを1周回す(DeferredDeleteはループが回っている間にしか配送されない)。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# PySide6の罠(実測): 親付きQObjectに inst.metaObject() を呼ぶと、返るQMetaObjectのラッパ
# (型と共有されている)がそのインスタンスの子になり、親がC++側で破棄された瞬間に
# `Cls.staticMetaObject` まで "already deleted" になって、後続のテストを壊す。
# インスタンス側のメタオブジェクト(=動的スロットが載る方)を調べる必要があるこのファイルの
# テストでは、親とブリッジをプロセス終了まで保持してこれを避ける。
_KEEP_ALIVE = []


def _slot_names(obj):
    from PySide6.QtCore import QMetaMethod
    _KEEP_ALIVE.append(obj)
    mo = obj.metaObject()
    names = []
    for i in range(mo.methodCount()):
        m = mo.method(i)
        if m.methodType() == QMetaMethod.MethodType.Slot and m.access() == QMetaMethod.Access.Public:
            names.append(bytes(m.methodSignature()).decode().split("(")[0])
    return names


# ---------------------------------------------------------------- No.9
def test_no9_internal_methods_are_not_exposed_as_slots():
    """QWebChannelは登録オブジェクトのメタオブジェクト上の公開スロットを全てJSへ出す。
    _on_page_navigated/_poll_hotplug等がそこに載っていてはいけない。"""
    page = _FakePage()
    _KEEP_ALIVE.append(page)
    bridge = WebUSBBridge(parent=page, locale="en")
    names = set(_slot_names(bridge))
    assert not [n for n in names if n.startswith("_")], sorted(n for n in names if n.startswith("_"))
    for forbidden in ("_on_page_navigated", "_poll_hotplug", "dispose", "event", "add_hotplug_listener",
                      "remove_hotplug_listener", "set_top_level_url_provider", "notify_navigated"):
        assert forbidden not in names, forbidden


def test_no9_signal_connections_do_not_add_dynamic_slots():
    """PySide6は、QObject自身のバウンドメソッドをSignalへつなぐと動的スロットとしてメタオブジェクトへ
    登録する(これがNo.9の原因)。弱参照つきの素の関数でつなげば、メタオブジェクトは静的なまま。"""
    plain = WebUSBBridge(locale="en")                           # 親なし: Signal接続(urlChanged)が無い
    baseline = plain.metaObject().methodCount()
    page = _FakePage()
    bridge = WebUSBBridge(parent=page, locale="en")             # 親あり: urlChanged/タイマーが接続される
    _KEEP_ALIVE.extend([plain, page, bridge])
    assert bridge.metaObject().methodCount() == baseline
    page.urlChanged.emit(QUrl("https://other.example/"))       # 接続自体は生きている(例外なく届く)
    QCoreApplication.processEvents()


def test_no9_page_cannot_destroy_the_bridge_with_deleteLater():
    bridge = WebUSBBridge(locale="en")
    bridge.deleteLater()                                        # QWebChannel経由でJSが呼べるQObjectのスロット
    _spin()
    assert shiboken6.isValid(bridge), "ページからのdeleteLater()でブリッジが破棄されてはいけない"
    bridge.deleteLater()
    _spin(20)
    assert shiboken6.isValid(bridge), "何度呼ばれても同じ"
    # ホストは dispose() で正規に破棄できる
    bridge.dispose()
    _spin(20)
    assert not shiboken6.isValid(bridge)


def test_no9_navigation_handler_still_fires_from_the_real_signal():
    """スロットから外したあとも、ページ遷移でオリジン変化時にオープン中ハンドルが閉じられる機能は生きている。"""
    page = _FakePage()
    bridge = WebUSBBridge(parent=page, locale="en")
    bridge._open_devices[5] = {"device": None, "origin": "https://old.example", "claimed_interfaces": set()}
    bridge._open_devices[6] = {"device": None, "origin": "https://page.example", "claimed_interfaces": set()}
    page.urlChanged.emit(QUrl("https://page.example/next"))
    QCoreApplication.processEvents()
    assert 5 not in bridge._open_devices, "別オリジンのハンドルは遷移で破棄される"
    assert 6 in bridge._open_devices, "現在のオリジンのハンドルは残る"


# ---------------------------------------------------------------- No.10
def _chooser_probe(origin, picked=None, raises=False):
    dev = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev])
    bridge._current_origin = lambda *a, **kw: origin
    calls = []

    def chooser(devices, org, strings):
        calls.append((list(devices), org))
        if raises:
            raise ValueError("boom")
        return picked(devices) if callable(picked) else picked
    bridge._chooser_override = chooser
    token = bridge.mintGestureToken()
    out = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": [{"vendorId": 0x2341}]}), "tok", token))
    return bridge, calls, out


@pytest.mark.parametrize("origin", [None, ""])
def test_no10_opaque_origin_never_reaches_the_chooser_and_gets_no_descriptor(origin):
    bridge, calls, out = _chooser_probe(origin, picked=lambda d: d[0])
    assert calls == [], "オリジン不明のフレームのためにUIを出してはいけない"
    assert out.get("cancelled") is True
    assert out["error"].startswith("SecurityError:")
    assert "device" not in out, "記述子を返してはいけない"
    assert bridge.__test_grants__ == []


def test_no10_positive_control_known_origin_reaches_the_chooser_and_is_granted():
    bridge, calls, out = _chooser_probe("https://app.example", picked=lambda d: d[0])
    assert len(calls) == 1 and calls[0][1] == "https://app.example"
    assert out["device"]["vendorId"] == 0x2341
    assert bridge.__test_grants__ == [("https://app.example", 0x2341, 0x8036)]


# ---------------------------------------------------------------- No.12
def test_no12_custom_chooser_cannot_grant_a_device_that_was_not_offered():
    forged = {"vendorId": 0x1234, "productId": 0x5678, "serialNumber": None}
    bridge, calls, out = _chooser_probe("https://app.example", picked=forged)
    assert out.get("cancelled") is True and "device" not in out
    assert bridge.__test_grants__ == []


def test_no12_chooser_exception_is_contained_and_not_leaked():
    bridge, calls, out = _chooser_probe("https://app.example", raises=True)
    assert out == {"cancelled": True, "error": "Dialog error"}
    assert "boom" not in json.dumps(out)
    assert bridge.__test_grants__ == []


def test_no12_chooser_returning_none_is_a_plain_cancel():
    bridge, calls, out = _chooser_probe("https://app.example", picked=None)
    assert out.get("cancelled") is True and not out.get("error")


# ---------------------------------------------------------------- No.11
def test_no11_hotplug_broadcast_carries_only_vid_pid():
    dev = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev])
    bridge._top_level_origin = lambda: "https://top.example"
    bridge._is_granted = lambda origin, vid, pid: True

    class Watcher:
        def poll(self):
            return ({(0x2341, 0x8036)}, {(0x1111, 0x2222)})
    bridge._hotplug_watcher = Watcher()
    got = {"connect": [], "disconnect": []}
    bridge.deviceConnected.connect(lambda s: got["connect"].append(json.loads(s)))
    bridge.deviceDisconnected.connect(lambda s: got["disconnect"].append(json.loads(s)))
    bridge._poll_hotplug()
    QCoreApplication.processEvents()
    assert got["connect"] == [{"vendorId": 0x2341, "productId": 0x8036}]
    assert got["disconnect"] == [{"vendorId": 0x1111, "productId": 0x2222}]


def test_no11_hotplug_listeners_get_events_even_without_a_granted_top_level_origin():
    """WebSocket転送層は接続(=オリジン)ごとに許可を判定する。リスナーへはVID/PIDだけが渡る。"""
    dev = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev])
    bridge._transport_kind = "websocket"
    bridge._hotplug_watcher = type("W", (), {"poll": lambda self: ({(1, 2)}, set())})()
    seen = []
    bridge.add_hotplug_listener(lambda kind, vid, pid: seen.append((kind, vid, pid)))
    bridge._poll_hotplug()
    assert seen == [("connect", 1, 2)]


def test_get_diagnostics_contains_no_paths_or_raw_errors():
    bridge = make_bridge([])
    info = json.loads(bridge.getDiagnostics())
    text = json.dumps(info)
    assert info["transport"] == "webchannel"
    assert info["platform"]["os"] and "hints" in info
    for needle in ("/home/", "/usr/", "C:\\", "Traceback", "site-packages"):
        assert needle not in text


if __name__ == "__main__":
    # 直接実行でも本当にテストが走るように(import して終わり、にならないように)する。
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
