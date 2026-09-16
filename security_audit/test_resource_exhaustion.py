# -*- coding: utf-8 -*-
"""リソース枯渇(DoS)系の脅威モデル: 「一度だけ正規に許可を得た、ごく普通の
ページ」が、polyfill.py(navigator.usb)を一切迂回せず、正規のAPIを
連打するだけでホストアプリケーション本体(=表示中のタブだけでなく、
埋め込んでいるデスクトップアプリのメインプロセスそのもの)のメモリを
無制限に消費させられないか。

このファイルのテストは、他のfindingと異なり「素のQWebChannel直叩き」も
「壊れたデバイス記述子」も一切必要としない -- ごく普通に1つのデバイスへの
許可を得た後、navigator.usb.requestDevice()で許可されたデバイスに対して
device.open()を呼び続けるだけの、ごく自然なJSコードで再現できる。
"""
import json

from _fixtures import FakeConfiguration, FakeDevice, make_bridge


def test_openDevice_has_no_cap_and_leaks_unbounded_handles_without_close():
    """許可済みの1台のデバイスに対してopenDevice()をclose無しで大量に呼んでも、
    _open_devices の増加に何の上限も無いことを確認する。実際のWebページ視点では
    これは 'navigator.usb.getDevices()で得たUSBDeviceに対しopen()をループで
    呼び続けるだけ' という、悪意の無いふりをした普通のJSコードで再現できる
    (polyfill.pyのJS検証を一切迂回する必要が無い)。"""
    dev = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev])
    bridge._is_granted = lambda origin, vid, pid: True  # 一度だけ正規に許可された状況を模す

    N = 5000
    for _ in range(N):
        result = json.loads(bridge.openDevice(0x2341, 0x8036, ""))
        assert result["success"] is True, result

    assert len(bridge._open_devices) < N, (
        f"closeDevice()を一度も呼ばずにopenDevice()を{N}回呼んだ結果、"
        f"_open_devices が {len(bridge._open_devices)} 件まで無制限に増え続けて"
        "しまった。1オリジンあたりの同時オープンハンドル数に上限が無いため、"
        "たった1台のデバイスに対する正規の許可さえ得られれば(=素のQWebChannel"
        "直叩きや壊れたデバイス記述子といった特殊なテクニックを一切使わずとも)、"
        "ごく普通のJSコード(device.open()をループで呼び続けるだけ)で"
        "_open_devices 辞書とその中身(pyusbのDeviceオブジェクトへの参照)を"
        "無制限に増やせてしまう。これは表示中のページ(レンダラプロセス)の"
        "メモリではなく、WebUSBBridgeが実際に存在するホストアプリケーション"
        "本体のプロセスのメモリを消費するため、通常のタブ単位のメモリ上限や"
        "レンダラプロセスの分離では守られない。"
    )
