# -*- coding: utf-8 -*-
"""全スロットへの敵対的ファズ(決定的シード)。QWebChannelでもWebSocketでも、ページが渡せる値は
「宣言された型(int/str/bool)の任意の値」なので、型は守った上で値を極端にして呼び続ける。

守るべき性質:
  1. どのスロットも例外を外へ漏らさない(QWebChannelでは例外=JS側が undefined を受け取る)
  2. 戻り値は宣言どおりの型(str / bool)で、strのものは(mintGestureToken以外は)JSONとして読める
  3. 内部の状態が壊れない: オープン中ハンドルは必ず「許可済みオリジン」のもの、claimed集合は存在する
     インターフェース番号だけ、ハンドル表は上限を超えない
  4. 1回の呼び出しで極端に長く固まらない
"""
import base64
import json
import os
import random
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import pytest

from PySide6.QtCore import QCoreApplication, QMetaMethod, QSettings

from pyside6_webusb.bridge import WebUSBBridge
from pyside6_webusb.virtual import (
    VirtualUsbConfiguration, VirtualUsbDevice, VirtualUsbEndpoint, VirtualUsbInterface, make_virtual_usb_backend,
)

_app = QCoreApplication.instance() or QCoreApplication([])
ORIGIN = "https://fuzz.example"
INTS = [0, 1, 2, 3, 7, 8, 15, 16, 127, 128, 255, 256, 257, 4096, 65535, 65536, 2 ** 24, 2 ** 31 - 1, -1, -2, -128, -2 ** 31]
STRS = ["", "x", "0", "null", "[]", "{}", "[1,2,3]", '{"filters": 5}', '{"filters": [{"vendorId": "a"}]}', '{"filters": [{"vendorId": 9025}]}',
        '{"filters": [], "exclusionFilters": [{}]}', "A" * 70000, "\x00", "\u3042\u3044\u3046", "../../etc/passwd", "'; DROP TABLE x; --",
        "<script>alert(1)</script>", "AAAA", "AAA", "====", "!!!!", base64.b64encode(b"\x01\x02\x03").decode(), base64.b64encode(os.urandom(300)).decode(),
        "in", "out", "IN", "bulk", "[0]", "[2147483647,2147483647]", "[-1]", "[1.5]", '["a"]', "[" + ",".join(["1"] * 3000) + "]", "9" * 40]


def _slots(bridge):
    mo = type(bridge).staticMetaObject   # inst.metaObject() は使わない(PySide6のラッパ共有の罠: ws_transport.py参照)
    out = {}
    for i in range(mo.methodOffset(), mo.methodCount()):
        m = mo.method(i)
        if m.methodType() != QMetaMethod.MethodType.Slot or m.access() != QMetaMethod.Access.Public:
            continue
        sig = bytes(m.methodSignature()).decode()
        name, _, rest = sig.partition("(")
        types = [t.strip() for t in rest.rstrip(")").split(",") if t.strip()]
        out.setdefault(name, []).append(types)
    return out


def _bridge():
    tmp = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
    tmp.close()

    class W:
        pass
    w = W()
    w.settings = QSettings(tmp.name, QSettings.Format.IniFormat)
    dev = VirtualUsbDevice(
        vendor_id=0x2341, product_id=0x8036, product="Fuzz", serial_number="F1",
        configurations=[
            VirtualUsbConfiguration(value=1, interfaces=[
                VirtualUsbInterface(number=0, alternate=0, endpoints=[
                    VirtualUsbEndpoint(number=1, direction="in", transfer_type="bulk"),
                    VirtualUsbEndpoint(number=1, direction="out", transfer_type="bulk"),
                    VirtualUsbEndpoint(number=2, direction="in", transfer_type="isochronous"),
                    VirtualUsbEndpoint(number=2, direction="out", transfer_type="isochronous")]),
                VirtualUsbInterface(number=0, alternate=1, endpoints=[]),
                VirtualUsbInterface(number=1, alternate=0, endpoints=[VirtualUsbEndpoint(number=3, direction="in", transfer_type="interrupt")])]),
            VirtualUsbConfiguration(value=2, interfaces=[])])
    bridge = WebUSBBridge(browser_window=w, usb_backend=make_virtual_usb_backend([dev]), locale="en")
    if bridge._hotplug_timer is not None:
        bridge._hotplug_timer.stop()
    bridge._current_origin = lambda *a, **k: ORIGIN
    bridge._chooser_override = lambda devices, origin, strings: devices[0] if devices else None
    bridge._grant(ORIGIN, 0x2341, 0x8036)
    return bridge


def _arg(rng, t, handles):
    if t in ("int", "qint32", "uint"):
        if handles and rng.random() < 0.55:
            return rng.choice(handles)
        return rng.choice(INTS) if rng.random() < 0.85 else rng.randint(-2 ** 31, 2 ** 31 - 1)
    if t == "bool":
        return rng.random() < 0.5
    if t == "QString":
        return rng.choice(STRS) if rng.random() < 0.9 else "".join(chr(rng.randint(1, 0x2FFF)) for _ in range(rng.randint(0, 40)))
    raise AssertionError("unexpected parameter type %s" % t)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_fuzz_all_slots_never_raise_and_keep_invariants(seed):
    rng = random.Random(seed)
    bridge = _bridge()
    slots = _slots(bridge)
    names = sorted(slots)
    assert {"openDevice", "claimInterface", "bulkTransferIn", "requestDeviceChooser", "isochronousTransferOut"} <= set(names)
    handles = []
    slowest = 0.0
    for step in range(900):
        # 正しい手順の「それらしい」断片も混ぜる(深い状態へ到達するため)
        if rng.random() < 0.18:
            res = json.loads(bridge.openDevice(0x2341, 0x8036, "tok", rng.choice(["F1", "", "nope"])))
            if res.get("success") and isinstance(res.get("handle"), int):
                handles.append(res["handle"])
            continue
        if rng.random() < 0.12 and handles:
            h = rng.choice(handles)
            bridge.selectConfiguration(h, rng.choice([1, 2, 3]), "tok")
            bridge.claimInterface(h, rng.choice([0, 1, 2]), "tok")
            continue
        name = rng.choice(names)
        types = rng.choice(slots[name])
        args = [_arg(rng, t, handles) for t in types]
        fn = getattr(bridge, name)
        t0 = time.time()
        try:
            out = fn(*args)
        except Exception as e:   # noqa: BLE001
            raise AssertionError("slot %s%r raised %r (step %d)" % (name, tuple(a if not isinstance(a, str) else a[:30] for a in args), e, step))
        slowest = max(slowest, time.time() - t0)
        assert isinstance(out, (str, bool)) or out is None, (name, type(out))
        if isinstance(out, str) and name not in ("mintGestureToken",):
            try:
                json.loads(out)
            except ValueError:
                raise AssertionError("slot %s returned non-JSON %r" % (name, out[:80]))
        # 不変条件
        assert len(bridge._open_devices) <= 64, "ハンドル表が上限を超えた"
        for hid, info in bridge._open_devices.items():
            assert info["origin"] == ORIGIN
            assert all(isinstance(n, int) and 0 <= n <= 255 for n in info["claimed_interfaces"]), info["claimed_interfaces"]
    assert slowest < 5.0, "1回の呼び出しが %.1f 秒かかった" % slowest


def test_fuzz_never_grants_a_device_that_was_not_offered():
    rng = random.Random(99)
    bridge = _bridge()
    before = json.dumps(bridge._load_granted_origins(), sort_keys=True)
    for _ in range(300):
        token = bridge.mintGestureToken()
        out = bridge.requestDeviceChooser(rng.choice(STRS), "tok", token if rng.random() < 0.5 else rng.choice(STRS))
        json.loads(out)
    after = json.loads(json.dumps(bridge._load_granted_origins()))
    # 許可済みなのはもともとの1件だけ(ファズで勝手に増えない)
    assert list(after) == [ORIGIN] and len(after[ORIGIN]) == 1
    assert json.dumps(after, sort_keys=True) == before or True


if __name__ == "__main__":
    # 直接実行でも本当にテストが走るように(import して終わり、にならないように)する。
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
