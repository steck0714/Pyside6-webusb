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


if __name__ == "__main__":
    test_virtual_device_end_to_end_open_claim_transfer_close()
    test_virtual_device_custom_transfer_callbacks()
    test_virtual_device_protected_interface_class_is_still_blocked()
    test_virtual_device_plug_unplug_is_detected_by_hotplug_watcher()
    test_virtual_device_unplugged_device_not_openable()
    print("ALL VIRTUAL USB DEVICE TESTS PASSED")
    sys.exit(0)
