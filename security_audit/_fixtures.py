# -*- coding: utf-8 -*-
"""security_audit/ 内の各テストファイルが共有するフェイクオブジェクト群。

基本形(FakeEndpoint/FakeInterface/FakeConfiguration/FakeDevice/FakeUsbUtil/
FakeUsbCore/FakeChooserDialog/make_bridge)は tests/test_bridge.py のものと
意図的に同一の形にしてある(bridge.py/hardening.pyが実際に期待するpyusbの
インターフェースはそちらで既に検証済みのため、food for thought:形を変えると
「本物の脆弱性」ではなく「フィクスチャの作り間違い」でテストが落ちる/通る
リスクが生まれる)。

このファイル固有の追加分は、攻撃者(=悪意あるページ、または悪意あるUSB
デバイス=「クラッカー」)が送り込みうる、値そのものが敵対的なケースを
組み立てるためのヘルパー。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtWidgets import QApplication

from pyside6_webusb.bridge import WebUSBBridge

_app = QApplication.instance() or QApplication([])


# --- tests/test_bridge.py と同形の基本フェイク ---

class FakeEndpoint:
    def __init__(self, address, attributes, max_packet=64):
        self.bEndpointAddress = address
        self.bmAttributes = attributes
        self.wMaxPacketSize = max_packet


class FakeInterface:
    def __init__(self, number, alt, iclass, isub, iproto, endpoints):
        self.bInterfaceNumber = number
        self.bAlternateSetting = alt
        self.bInterfaceClass = iclass
        self.bInterfaceSubClass = isub
        self.bInterfaceProtocol = iproto
        self._endpoints = endpoints

    def __iter__(self):
        return iter(self._endpoints)


class FakeConfiguration:
    def __init__(self, value, interfaces):
        self.bConfigurationValue = value
        self._interfaces = interfaces

    def __iter__(self):
        return iter(self._interfaces)


class FakeDevice:
    def __init__(self, idVendor, idProduct, configurations,
                 deviceClass=0, deviceSubClass=0, deviceProtocol=0,
                 bcdUSB=0x0200, bcdDevice=0x0100,
                 iManufacturer=1, iProduct=2, iSerialNumber=3):
        self.idVendor = idVendor
        self.idProduct = idProduct
        self._configurations = configurations
        self.bDeviceClass = deviceClass
        self.bDeviceSubClass = deviceSubClass
        self.bDeviceProtocol = deviceProtocol
        self.bcdUSB = bcdUSB
        self.bcdDevice = bcdDevice
        self.iManufacturer = iManufacturer
        self.iProduct = iProduct
        self.iSerialNumber = iSerialNumber
        self.backend = None
        self._ctx = None

    def __iter__(self):
        # 敵対的デバイス向け: configurationsが呼び出し可能なら、それを呼んで
        # 例外を発生させられるようにする(「列挙の途中で壊れたデバイス」を模す)
        if callable(self._configurations):
            return iter(self._configurations())
        return iter(self._configurations)

    def get_active_configuration(self):
        if not self._configurations:
            raise ValueError("no active configuration")
        cfgs = self._configurations() if callable(self._configurations) else self._configurations
        return getattr(self, "_active_configuration", None) or cfgs[0]

    def set_configuration(self, configuration=None):
        cfgs = self._configurations() if callable(self._configurations) else self._configurations
        if configuration is None or configuration == 0:
            self._active_configuration = cfgs[0]
            return
        for cfg in cfgs:
            if cfg.bConfigurationValue == configuration:
                self._active_configuration = cfg
                return
        raise ValueError(f"Configuration {configuration} not found")

    def read(self, endpoint, length, timeout=None):
        self.last_read_call = {"endpoint": endpoint, "length": length, "timeout": timeout}
        if not hasattr(self, "read_calls"):
            self.read_calls = []
        self.read_calls.append(dict(self.last_read_call))
        if getattr(self, "read_exception", None) is not None:
            raise self.read_exception
        # short_read_bytes: デバイスが要求より少ないバイト数しか返さない状況
        # (短パケット/デバイス側の都合)を模す。CVE-2026-5276型
        # (「不十分なポリシー適用によりプロセスメモリの一部を漏洩」)の
        # Python版アナロジー確認用: 実際に受け取ったバイト数だけが返る
        # (=使い回しバッファの余剰/未初期化領域が混ざらない)ことを検証する。
        short = getattr(self, "short_read_bytes", None)
        if short is not None:
            return bytes(short)
        return bytes([0xAB]) * min(length, 4)

    def write(self, endpoint, data, timeout=None):
        self.last_write_call = {"endpoint": endpoint, "data": bytes(data), "timeout": timeout}
        if getattr(self, "write_exception", None) is not None:
            raise self.write_exception
        return len(data)

    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None):
        self.ctrl_transfer_calls = getattr(self, "ctrl_transfer_calls", [])
        self.ctrl_transfer_calls.append({
            "bmRequestType": bmRequestType, "bRequest": bRequest,
            "wValue": wValue, "wIndex": wIndex, "data_or_wLength": data_or_wLength, "timeout": timeout,
        })
        if getattr(self, "ctrl_transfer_exception", None) is not None:
            raise self.ctrl_transfer_exception
        short = getattr(self, "short_read_bytes", None)
        if isinstance(data_or_wLength, int):
            if short is not None:
                return bytes(short)
            return bytes([0xCD]) * min(data_or_wLength, 4)
        return len(data_or_wLength) if data_or_wLength else 0

    def is_kernel_driver_active(self, interface_number):
        return False

    def detach_kernel_driver(self, interface_number):
        pass

    def clear_halt(self, endpoint):
        self.last_clear_halt_call = {"endpoint": endpoint}

    def set_interface_altsetting(self, interface=None, alternate_setting=None):
        self.last_set_interface_altsetting_call = {"interface": interface, "alternate_setting": alternate_setting}


class FakeUsbUtil:
    ENDPOINT_IN = 0x80
    ENDPOINT_OUT = 0x00
    ENDPOINT_TYPE_CTRL = 0
    ENDPOINT_TYPE_ISO = 1
    ENDPOINT_TYPE_BULK = 2
    ENDPOINT_TYPE_INTR = 3

    STRINGS = {1: "Acme Corp", 2: "Acme Widget", 3: "SN-0001"}

    def __init__(self, strings=None, string_exception=None):
        if strings is not None:
            self.STRINGS = strings
        self.string_exception = string_exception

    def get_string(self, dev, index):
        if self.string_exception is not None:
            raise self.string_exception
        return self.STRINGS.get(index)

    def endpoint_direction(self, address):
        return self.ENDPOINT_IN if (address & 0x80) else self.ENDPOINT_OUT

    def endpoint_type(self, attributes):
        return attributes & 0x03

    def claim_interface(self, dev, interface):
        dev.claimed_by_util = getattr(dev, "claimed_by_util", set())
        dev.claimed_by_util.add(interface)

    def release_interface(self, dev, interface):
        dev.claimed_by_util = getattr(dev, "claimed_by_util", set())
        dev.claimed_by_util.discard(interface)


class FakeUsbCore:
    def __init__(self, devices):
        self._devices = devices

    def find(self, find_all=False, idVendor=None, idProduct=None, **kw):
        if find_all:
            return list(self._devices)
        for d in self._devices:
            if (idVendor is None or d.idVendor == idVendor) and (idProduct is None or d.idProduct == idProduct):
                return d
        return None


class FakeChooserDialog:
    """実QDialogの代わり。tests/test_bridge.pyのFakeChooserDialogと同形。"""
    class DialogCode:
        Accepted = 1
        Rejected = 0

    SELECT_INDEX = 0
    last_devices_info = None
    last_origin = None
    last_refresh_callback = None
    last_parent = None
    instantiated_count = 0  # security_audit独自: 何回コンストラクトされたかを数える

    def __init__(self, devices_info, parent, strings=None, origin=None, refresh_callback=None):
        FakeChooserDialog.last_devices_info = devices_info
        FakeChooserDialog.last_origin = origin
        FakeChooserDialog.last_refresh_callback = refresh_callback
        FakeChooserDialog.last_parent = parent
        FakeChooserDialog.instantiated_count += 1
        self.devices_info = devices_info
        idx = FakeChooserDialog.SELECT_INDEX
        self.selected_device = devices_info[idx] if (idx is not None and idx < len(devices_info)) else None

    def exec(self):
        return self.DialogCode.Accepted if self.selected_device is not None else self.DialogCode.Rejected

    def show(self):
        pass

    def raise_(self):
        pass

    def activateWindow(self):
        pass


def make_bridge(devices, usb_util=None, browser_window=None):
    """QWebChannel配線なしで、pyusb部分だけをフェイクに差し替えたWebUSBBridgeを作る。
    tests/test_bridge.pyのmake_bridge()と同じ役割。usb_utilを渡すと、敵対的な
    文字列記述子(製品名など)を返すFakeUsbUtilに差し替えられる。"""
    bridge = WebUSBBridge(browser_window=browser_window)
    bridge._pyusb = lambda: (FakeUsbCore(devices), usb_util or FakeUsbUtil())
    bridge._load_known_devices = lambda: []
    bridge._record_device_usage = lambda *a, **kw: None
    grants = []
    bridge._grant = lambda origin, vid, pid: grants.append((origin, vid, pid))
    bridge._current_origin = lambda *a, **kw: "https://example.test"
    bridge.__test_grants__ = grants
    return bridge
