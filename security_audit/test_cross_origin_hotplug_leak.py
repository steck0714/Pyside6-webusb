# -*- coding: utf-8 -*-
"""クロスオリジン情報漏洩: ホットプラグ(接続/切断)イベントのブロードキャスト範囲。

bridge.py の _poll_hotplug() 自身のコメントが明記している既知の簡略化:
    「deviceConnected/deviceDisconnectedはQt Signalとしてページ内の全フレームへ
    ブロードキャストされる(Signal配信をフレーム単位に絞る仕組みは無い)。
    フレームごとに異なる許可状況で出し分けることは今のところできないため、
    トップレベルページの許可状況を基準にする」

このテストは、この簡略化の実際の影響(=トップレベルページが許可された
デバイスの接続/切断が、そのデバイスを一切許可されていない別オリジンの
埋め込みiframeにも配送されてしまう)を実際に動かして確認する。

deviceConnected/deviceDisconnectedはPySide6のSignal(str)であり、Qt側の
仕組み上、特定のフレーム(=特定のQWebChannel接続)だけを狙って配送する
API自体が無い。そのため、この所見は「1箇所を直せば直る」類のバグではなく、
設計上の既知のトレードオフとして README のセキュリティモデルに明記する
(現状は本体READMEに記載が無く、bridge.py内のコメントのみに存在する)
か、より根本的にはpolyfill.py側で受信時に自オリジンの許可デバイス一覧と
突き合わせて再フィルタする対策が必要になる。
"""
import json

from PySide6.QtCore import QCoreApplication

from _fixtures import FakeConfiguration, FakeDevice, make_bridge


def test_hotplug_gate_checks_top_level_origin_not_receiving_frame():
    """_poll_hotplug()が接続/切断を配送するかどうかの判定に使っているのは
    「トップレベルページのオリジン」であって、実際にイベントを受け取る
    (かもしれない)個々のフレームのオリジンではないことを、実際に
    _is_grantedへ渡された引数を記録して確認する。"""
    dev = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev])

    top_level_origin = "https://top-level-page.example"
    embedded_iframe_origin = "https://unrelated-ad-widget.example"  # top-levelとは無関係、無許可の第三者オリジン

    bridge._top_level_origin = lambda: top_level_origin
    granted_origin_calls = []

    def fake_is_granted(origin, vid, pid):
        granted_origin_calls.append(origin)
        return origin == top_level_origin  # トップレベルページだけが許可されている状況

    bridge._is_granted = fake_is_granted

    class FakeHotplugWatcher:
        def poll(self):
            return ({(0x2341, 0x8036)}, set())  # 1台が接続

    bridge._hotplug_watcher = FakeHotplugWatcher()
    bridge._pyusb = lambda: (type("C", (), {"find": staticmethod(lambda **kw: dev)})(), _FakeUtilForHotplug())

    received = []
    bridge.deviceConnected.connect(lambda info_json: received.append(json.loads(info_json)))

    bridge._poll_hotplug()
    QCoreApplication.processEvents()

    assert granted_origin_calls == [top_level_origin], (
        f"_is_grantedへ渡されたオリジンが {granted_origin_calls} だった。"
        "実際に受信しうる個々のフレーム(例: embedded_iframe_origin)の許可状況では"
        "なく、常にトップレベルページのオリジンだけを基準にしている。"
    )
    assert len(received) == 1, (
        "トップレベルページが許可済みのデバイスの接続イベントが発火しなかった"
        "(前提条件の確認に失敗)"
    )
    assert embedded_iframe_origin not in granted_origin_calls, (
        "この時点で無関係な第三者オリジン(embedded_iframe_origin)の許可状況は"
        "一度も個別確認されていない。にもかかわらず、deviceConnected Signalは"
        "ページ全体へブロードキャストされる(Qt Signalの性質上、特定のフレーム"
        "だけを狙って配送するAPIが無い)ため、このオリジンが仮に同じページに"
        "埋め込まれたiframeとしてリスナーを登録していれば、自身が一切許可されて"
        "いないベンダーID/プロダクトIDの接続/切断情報を受け取ってしまう。"
    )


class _FakeUtilForHotplug:
    def get_string(self, dev, index):
        return None


def test_frame_token_cache_eviction_fails_closed_under_flood():
    """FrameOriginTrackerのトークンキャッシュ上限(256)を大量のフレーム生成で
    溢れさせても、古いトークンが単に失効する(=以後そのトークンでの呼び出しは
    「オリジン不明」として拒否される)だけで、別オリジンへの成りすまし等の
    危険な方向には倒れないことを確認する回帰テスト。"""
    from pyside6_webusb.frame_origin import FrameOriginTracker

    class _FakeFrame:
        pass

    class _FakePage:
        def profile(self):
            return None

        def scripts(self):
            class _Scripts:
                def insert(self, *a, **kw):
                    pass
            return _Scripts()

    tracker = FrameOriginTracker.__new__(FrameOriginTracker)
    tracker._token_to_origin = {}
    tracker._MAX_TOTAL_TOKENS = FrameOriginTracker._MAX_TOTAL_TOKENS

    first_token = tracker._assign_token(_FakeFrame())
    for _ in range(FrameOriginTracker._MAX_TOTAL_TOKENS + 50):
        tracker._assign_token(_FakeFrame())

    assert len(tracker._token_to_origin) <= FrameOriginTracker._MAX_TOTAL_TOKENS, (
        "トークンキャッシュが上限を超えて際限なく増え続けている(DoS/メモリ膨張の懸念)"
    )
    assert tracker.origin_for_token(first_token) is None, (
        "上限を溢れさせた後も、最も古いトークン(first_token)がまだ有効なオリジンに"
        "解決できてしまっている(=キャッシュ追い出しが機能していない)"
    )
    print("test_frame_token_cache_eviction_fails_closed_under_flood: OK (fails closed)")
