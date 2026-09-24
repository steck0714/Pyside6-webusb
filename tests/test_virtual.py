# -*- coding: utf-8 -*-
"""🆕 v0.0.5a3で追加した pyside6_webusb.virtual (実USBハードウェア不要の仮想
デバイス機能) のエンドツーエンドテスト。他のフィクスチャ(FakeDevice等)を
使わず、WebUSBBridge(usb_backend=...)という実際の公開APIをそのまま使って、
listDevices〜openDevice〜claimInterface〜bulk/制御転送〜closeDeviceの
一連の流れと、保護対象インターフェースクラスの判定が仮想デバイスにも
きちんと効くこと、抜き挿しシミュレーションが既存のホットプラグ検知
ロジックにそのまま乗ることを確認する。"""

import base64
import json
import sys

# QApplication([])のディスプレイ接続失敗はプロセスクラッシュになり得るため、
# 他のテストファイルと同じ作法でQT_QPA_PLATFORM=offscreenを前提とする
# (README/CIの実行手順を参照)。
from PySide6.QtWidgets import QApplication

from pyside6_webusb.bridge import WebUSBBridge
from pyside6_webusb.hardening import UsbHotplugWatcher
from pyside6_webusb.virtual import (
    VirtualUsbConfiguration,
    VirtualUsbDevice,
    VirtualUsbEndpoint,
    VirtualUsbInterface,
    make_virtual_usb_backend,
)

_app = QApplication.instance() or QApplication([])


def _make_widget_device(**overrides):
    kwargs = dict(
        vendor_id=0x2341, product_id=0x8036,
        manufacturer="Acme", product="Virtual Widget", serial_number="SN-0001",
        configurations=[
            VirtualUsbConfiguration(value=1, interfaces=[
                VirtualUsbInterface(number=0, alternate=0, interface_class=0xFF, endpoints=[
                    VirtualUsbEndpoint(number=1, direction="in", transfer_type="bulk"),
                    VirtualUsbEndpoint(number=1, direction="out", transfer_type="bulk"),
                ]),
            ]),
        ],
    )
    kwargs.update(overrides)
    return VirtualUsbDevice(**kwargs)


def test_virtual_device_end_to_end_open_claim_transfer_close():
    dev = _make_widget_device()
    backend = make_virtual_usb_backend([dev])
    bridge = WebUSBBridge(usb_backend=backend)
    bridge._is_granted = lambda *a, **kw: True
    bridge._current_origin = lambda *a, **kw: "https://example.test"

    listed = json.loads(bridge.listDevices())
    assert "error" not in listed, listed
    assert len(listed["devices"]) == 1
    d = listed["devices"][0]
    assert d["vendorId"] == 0x2341 and d["productId"] == 0x8036
    assert d["manufacturerName"] == "Acme" and d["productName"] == "Virtual Widget"
    assert d["serialNumber"] == "SN-0001"

    opened = json.loads(bridge.openDevice(0x2341, 0x8036))
    assert opened["success"] is True
    handle = opened["handle"]

    claimed = json.loads(bridge.claimInterface(handle, 0))
    assert claimed["success"] is True, claimed

    out_result = json.loads(bridge.bulkTransferOut(handle, 1, base64.b64encode(b"hello").decode("ascii")))
    assert out_result["success"] is True
    assert out_result["bytesWritten"] == 5

    in_result = json.loads(bridge.bulkTransferIn(handle, 1, 8))
    assert in_result["success"] is True
    assert base64.b64decode(in_result["data"]) == bytes(8)  # デフォルトはゼロ埋めのエコー応答

    released = json.loads(bridge.releaseInterface(handle, 0))
    assert released["success"] is True

    closed = json.loads(bridge.closeDevice(handle))
    assert closed["success"] is True
    print("test_virtual_device_end_to_end_open_claim_transfer_close: OK")


def test_virtual_device_custom_transfer_callbacks():
    """on_bulk_read/on_bulk_write/on_control_transferで応答ロジックを
    差し込めることを確認する(実プロトコルを模した固定シーケンスのシミュレーション用)。"""
    log = []

    def on_write(_dev, endpoint, data, _timeout):
        log.append(("write", endpoint, bytes(data)))
        return len(data)

    def on_read(_dev, endpoint, size_or_buffer, _timeout):
        log.append(("read", endpoint, size_or_buffer))
        return b"PONG!!!!"[:size_or_buffer if isinstance(size_or_buffer, int) else len(size_or_buffer)]

    def on_ctrl(_dev, bmRequestType, bRequest, wValue, wIndex, data_or_wLength, _timeout):
        log.append(("ctrl", bmRequestType, bRequest, wValue, wIndex))
        if bmRequestType & 0x80:
            return bytes([0xAB]) * data_or_wLength
        return len(bytes(data_or_wLength or b""))

    dev = _make_widget_device(on_bulk_read=on_read, on_bulk_write=on_write, on_control_transfer=on_ctrl)
    backend = make_virtual_usb_backend([dev])
    bridge = WebUSBBridge(usb_backend=backend)
    bridge._is_granted = lambda *a, **kw: True
    bridge._current_origin = lambda *a, **kw: "https://example.test"
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    json.loads(bridge.bulkTransferOut(handle, 1, base64.b64encode(b"PING").decode("ascii")))
    in_result = json.loads(bridge.bulkTransferIn(handle, 1, 8))
    assert base64.b64decode(in_result["data"]) == b"PONG!!!!"

    ctrl_in = json.loads(bridge.controlTransferIn(handle, 0xC0, 0x01, 0, 0, 4))
    assert base64.b64decode(ctrl_in["data"]) == bytes([0xAB] * 4)

    assert log[0] == ("write", 0x01, b"PING")
    assert log[1][:2] == ("read", 0x81)
    assert log[2][0] == "ctrl"
    print("test_virtual_device_custom_transfer_callbacks: OK")


def test_virtual_device_protected_interface_class_is_still_blocked():
    """🛡️ 仮想デバイスもbridge.py/hardening.pyの既存の保護対象インターフェース
    クラス判定をそのまま通ることを確認する(仮想デバイス機能の追加によって
    セキュリティモデルに抜け穴ができていないことの裏付け)。"""
    hid_dev = VirtualUsbDevice(
        vendor_id=0x1234, product_id=0x5678,
        configurations=[VirtualUsbConfiguration(value=1, interfaces=[
            VirtualUsbInterface(number=0, alternate=0, interface_class=0x03, endpoints=[
                VirtualUsbEndpoint(number=1, direction="in", transfer_type="interrupt"),
            ]),
        ])],
    )
    backend = make_virtual_usb_backend([hid_dev])
    bridge = WebUSBBridge(usb_backend=backend)
    bridge._is_granted = lambda *a, **kw: True
    bridge._current_origin = lambda *a, **kw: "https://example.test"
    handle = json.loads(bridge.openDevice(0x1234, 0x5678))["handle"]

    result = json.loads(bridge.claimInterface(handle, 0))
    assert result["success"] is False
    assert result["error"].startswith("SecurityError:"), result
    print("test_virtual_device_protected_interface_class_is_still_blocked: OK")


def test_virtual_device_plug_unplug_is_detected_by_hotplug_watcher():
    """plug()/unplug()による抜き挿しシミュレーションが、既存の
    UsbHotplugWatcher(実際にbridge.pyが使っているのと同じクラス)のポーリングで
    そのまま検知できることを確認する——bridge.py側の変更は一切不要。"""
    dev = _make_widget_device()
    backend, util_shim = make_virtual_usb_backend([dev])
    watcher = UsbHotplugWatcher(lambda: {(d.idVendor, d.idProduct) for d in backend.find(find_all=True)})

    connected, disconnected = watcher.poll()  # 初回は基準記録のみ
    assert connected == [] and disconnected == []

    dev.unplug()
    connected, disconnected = watcher.poll()
    assert connected == [] and disconnected == [(0x2341, 0x8036)]

    dev.plug()
    connected, disconnected = watcher.poll()
    assert connected == [(0x2341, 0x8036)] and disconnected == []
    print("test_virtual_device_plug_unplug_is_detected_by_hotplug_watcher: OK")


def test_virtual_device_unplugged_device_not_openable():
    dev = _make_widget_device()
    dev.unplug()
    backend = make_virtual_usb_backend([dev])
    bridge = WebUSBBridge(usb_backend=backend)
    bridge._is_granted = lambda *a, **kw: True
    bridge._current_origin = lambda *a, **kw: "https://example.test"

    result = json.loads(bridge.openDevice(0x2341, 0x8036))
    assert result["success"] is False
    assert result["error"].startswith("NotFoundError:"), result
    print("test_virtual_device_unplugged_device_not_openable: OK")


def test_virtual_version_to_bcd_formats():
    """_version_to_bcdがタプルだけでなく、文字列("2.1.0")や整数(0x0210, 2)も適切に変換できることを確認する。"""
    from pyside6_webusb.virtual import _version_to_bcd
    assert _version_to_bcd((2, 1, 0)) == 0x0210
    assert _version_to_bcd([1, 2, 3]) == 0x0123
    assert _version_to_bcd("2.1.0") == 0x0210
    assert _version_to_bcd("3.0") == 0x0300
    assert _version_to_bcd(0x0210) == 0x0210
    assert _version_to_bcd(2) == 0x0200
    assert _version_to_bcd(None) == 0x0000


def test_virtual_version_to_bcd_rejects_malformed_input():
    """🐛 バグ修正(v0.0.5b2): Noneは意図的な「指定なし」として0x0000のままだが、
    それ以外の解釈できない入力(数字でない部分を含む文字列、bool、
    未対応の型)は、黙って0.0.0扱いにするのではなくValueErrorを送出する
    べきことを確認する(タイプミスに気づかないまま誤ったバージョンの
    仮想デバイスが出来上がってしまうのを防ぐ)。"""
    from pyside6_webusb.virtual import _version_to_bcd
    import pytest as _pytest
    for bad in ("2.1.x", "not-a-version", "", True, False, {"major": 2}, 3.5):
        with _pytest.raises(ValueError):
            _version_to_bcd(bad)


def test_virtual_device_ctrl_transfer_with_buffer():
    """ctrl_transferでIN転送にbytearrayなどのバッファが渡された場合でも長さを正しく取得できることを確認する。"""
    dev = _make_widget_device()
    buf = bytearray(32)
    res = dev.ctrl_transfer(0x80, 0x06, 0x0100, 0, buf)
    assert len(res) == 32
    assert res == bytes(32)


def test_virtual_backend_find_custom_match_and_kwargs():
    """VirtualUsbBackend.find()がcustom_matchや追加の属性フィルタ(kwargs)に対応していることを確認する。"""
    dev1 = _make_widget_device(vendor_id=0x1234, product_id=0x0001, device_class=0xFF)
    dev2 = _make_widget_device(vendor_id=0x1234, product_id=0x0002, device_class=0x02)
    backend = make_virtual_usb_backend([dev1, dev2])[0]

    # kwargsフィルタ
    found = backend.find(bDeviceClass=0x02)
    assert found is dev2

    # custom_matchフィルタ
    matched = backend.find(find_all=True, custom_match=lambda d: d.idProduct == 0x0001)
    assert matched == [dev1]


def test_virtual_configuration_and_interface_names_are_actually_resolvable():
    """🐛 バグ修正(v0.0.5b2、実際に再現して確認): VirtualUsbConfiguration(description=...)
    とVirtualUsbInterface(name=...)は、渡した文字列をどこにも登録しないまま
    iConfiguration/iInterfaceを常に0に固定していたため、
    build_device_descriptor()のconfigurationName/interfaceName解決が常に
    Noneになり、指定したはずの名前が黙って消えていた(=死んでいたパラメータ)。
    実際にVirtualUsbUtilShim.get_string()で解決できることを直接確認する。"""
    from pyside6_webusb.virtual import VirtualUsbUtilShim
    iface = VirtualUsbInterface(number=0, alternate=0, interface_class=0xFF, name="Bulk Data Interface")
    cfg = VirtualUsbConfiguration(value=1, interfaces=[iface], description="Default Configuration")
    dev = VirtualUsbDevice(vendor_id=0x2341, product_id=0x8036, configurations=[cfg])
    util = VirtualUsbUtilShim()

    assert cfg.iConfiguration != 0, "iConfigurationが0のまま(=文字列が登録されていない)"
    assert iface.iInterface != 0, "iInterfaceが0のまま(=文字列が登録されていない)"
    assert util.get_string(dev, cfg.iConfiguration) == "Default Configuration"
    assert util.get_string(dev, iface.iInterface) == "Bulk Data Interface"


def test_virtual_device_from_descriptor_round_trips_through_build_device_descriptor():
    """🆕 v0.0.5b2の新機能: VirtualUsbDevice.from_descriptor()が、
    hardening.build_device_descriptor()の出力(listDevices()/getDevices()が
    JSへ返すのと全く同じ形)から仮想デバイスを正しく再構築できることを、
    「作る→記述子化する→そこから作り直す→もう一度記述子化する」という
    ラウンドトリップで確認する(実機を一度録って、後で実機無しに再生する
    という想定ワークフローそのもの)。"""
    from pyside6_webusb.hardening import build_device_descriptor
    from pyside6_webusb.virtual import VirtualUsbUtilShim

    util = VirtualUsbUtilShim()
    original = VirtualUsbDevice(
        vendor_id=0x2341, product_id=0x8036,
        manufacturer="Acme", product="Virtual Widget", serial_number="SN-0001",
        device_class=0xEF, device_subclass=0x02, device_protocol=0x01,
        usb_version=(2, 1, 0), device_version=(1, 5, 3),
        configurations=[
            VirtualUsbConfiguration(value=1, description="Default Configuration", interfaces=[
                VirtualUsbInterface(number=0, alternate=0, interface_class=0xFF, name="Bulk I/O", endpoints=[
                    VirtualUsbEndpoint(number=1, direction="in", transfer_type="bulk", max_packet_size=64),
                    VirtualUsbEndpoint(number=1, direction="out", transfer_type="bulk", max_packet_size=64),
                ]),
                VirtualUsbInterface(number=0, alternate=1, interface_class=0xFF, name="Bulk I/O (hi-speed)", endpoints=[
                    VirtualUsbEndpoint(number=1, direction="in", transfer_type="bulk", max_packet_size=512),
                ]),
            ]),
        ],
    )
    descriptor = build_device_descriptor(original, util)

    replayed = VirtualUsbDevice.from_descriptor(descriptor)
    replayed_descriptor = build_device_descriptor(replayed, VirtualUsbUtilShim())

    assert replayed_descriptor == descriptor, (
        "from_descriptor()経由で再構築したデバイスの記述子が元と一致しない:\n"
        f"original={descriptor!r}\nreplayed={replayed_descriptor!r}"
    )

    # 再生した仮想デバイスが実際にbridge経由でも普通に使えることも確認する
    # (記述子が一致するだけでなく、実際にopen/claim/転送まで動くことの裏付け)。
    backend = make_virtual_usb_backend([replayed])
    bridge = WebUSBBridge(usb_backend=backend)
    bridge._is_granted = lambda *a, **kw: True
    bridge._current_origin = lambda *a, **kw: "https://example.test"
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True
    transfer = json.loads(bridge.bulkTransferIn(handle, 1, 8))
    assert transfer["success"] is True


def test_virtual_device_from_descriptor_tolerates_missing_optional_fields():
    """🆕 v0.0.5b2: 手書きの/部分的にしか無い記述子(実際のlistDevices()出力の
    一部だけを保存したような場合)でも、欠けているフィールドは無害な既定値で
    補ってVirtualUsbDeviceを組み立てられることを確認する。"""
    minimal_descriptor = {"vendorId": 0x1234, "productId": 0x5678}
    dev = VirtualUsbDevice.from_descriptor(minimal_descriptor)
    assert dev.idVendor == 0x1234 and dev.idProduct == 0x5678
    backend = make_virtual_usb_backend([dev])[0]
    assert backend.find(idVendor=0x1234, idProduct=0x5678) is dev


# 🐛 バグ修正(v0.0.5b2): このif __name__ブロックは以前ファイル中盤(旧テスト5本の
# 直後)に置かれており、その後に追加された3本のテスト関数(test_virtual_version_to_bcd_formats
# 以降)がまだ定義される前に呼ばれる形になっていた。pytest経由の実行(このファイルの
# 主な使われ方)はテスト関数を発見して直接呼ぶだけなので影響が無く見過ごされていたが、
# README/CHANGELOGが明示的にサポートを謳う「python tests/test_virtual.py」という直接
# 実行方式では、そこに到達した時点でtest_virtual_version_to_bcd_formatsがまだ定義されて
# おらずNameErrorになっていた(実際に再現して確認済み)。以後の混乱を避けるため、
# 全てのテスト関数定義の後、ファイル末尾に置く通常の配置へ直す。
if __name__ == "__main__":
    test_virtual_device_end_to_end_open_claim_transfer_close()
    test_virtual_device_custom_transfer_callbacks()
    test_virtual_device_protected_interface_class_is_still_blocked()
    test_virtual_device_plug_unplug_is_detected_by_hotplug_watcher()
    test_virtual_device_unplugged_device_not_openable()
    test_virtual_version_to_bcd_formats()
    test_virtual_version_to_bcd_rejects_malformed_input()
    test_virtual_device_ctrl_transfer_with_buffer()
    test_virtual_backend_find_custom_match_and_kwargs()
    test_virtual_configuration_and_interface_names_are_actually_resolvable()
    test_virtual_device_from_descriptor_round_trips_through_build_device_descriptor()
    test_virtual_device_from_descriptor_tolerates_missing_optional_fields()
    print("ALL VIRTUAL USB DEVICE TESTS PASSED")
    sys.exit(0)
