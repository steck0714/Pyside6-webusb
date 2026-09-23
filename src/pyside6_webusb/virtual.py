# -*- coding: utf-8 -*-
"""
🆕 v0.0.5a3で追加: 仮想(ハードウェア不要)USBデバイスのサポート。

実機のUSBデバイスを1台も挿さなくても navigator.usb の動作を試したり、
CIで自動テストしたりしたい開発者向けに、pyusbの usb.core.Device /
usb.util が持つ最小限のインターフェースをduck-typingで満たす「仮想デバイス」を
提供する。security_audit/_fixtures.py や tests/test_bridge.py の
FakeDevice/FakeUsbUtil系のテスト用フィクスチャと全く同じ形をしているため、
bridge.py/hardening.pyの既存ロジック(保護対象インターフェースクラス判定・
現在選択中のalternate settingに基づくエンドポイント検証・セキュリティキー
ブロックリスト等)は一切変更することなくそのまま仮想デバイスにも適用される。

使い方::

    from pyside6_webusb import WebUSBBridge
    from pyside6_webusb.virtual import (
        VirtualUsbDevice, VirtualUsbConfiguration,
        VirtualUsbInterface, VirtualUsbEndpoint,
        make_virtual_usb_backend,
    )

    dev = VirtualUsbDevice(
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
    backend = make_virtual_usb_backend([dev])
    bridge = WebUSBBridge(usb_backend=backend)   # これで実機無しにnavigator.usbが動く
    channel.registerObject("pyUsbBridge", bridge)

    # 抜き挿しのシミュレーション。既存のホットプラグ監視(UsbHotplugWatcher)が
    # そのままポーリングで拾うので、bridge.py側に追加の変更は不要。
    backend[0].unplug()   # 抜く
    backend[0].plug()     # 挿し直す

制約(v0.0.5a3時点、README「Known limitations」にも記載):
    - bulk/interrupt/制御転送はデフォルトでは要求バイト数ぶんの0x00を返す
      だけの素朴な模擬応答になる。VirtualUsbDevice(..., on_control_transfer=,
      on_bulk_read=, on_bulk_write=)にcallableを渡せば、デバイスごとに
      好きな応答ロジック(実プロトコルを模した固定シーケンス等)を差し込める。
    - isochronous転送のタイミング(帯域・周期)そのものはシミュレートしない
      (呼び出しはbulk/interrupt同様に素朴に処理する)。
    - kernel driverの概念が無いため is_kernel_driver_active() は常にFalse。
    - reset()は記述子構成をそのまま維持する(実機のようには再列挙しない。
      WebUSB仕様自身、reset後にどのconfigurationが有効かは未規定
      (Issue #36)としており、これは仕様違反ではない)。
"""

import threading
import time


# usb.util の ENDPOINT_* / ENDPOINT_TYPE_* 定数(pyusb実物と同じ値)。
ENDPOINT_IN = 0x80
ENDPOINT_OUT = 0x00
ENDPOINT_TYPE_CTRL = 0
ENDPOINT_TYPE_ISO = 1
ENDPOINT_TYPE_BULK = 2
ENDPOINT_TYPE_INTR = 3

_TRANSFER_TYPE_TO_BMATTRIBUTES = {
    "control": ENDPOINT_TYPE_CTRL,
    "isochronous": ENDPOINT_TYPE_ISO,
    "bulk": ENDPOINT_TYPE_BULK,
    "interrupt": ENDPOINT_TYPE_INTR,
}


class VirtualUsbEndpoint:
    """pyusbの usb.core.Endpoint に相当する最小限の記述子。"""

    def __init__(self, number, direction="in", transfer_type="bulk", max_packet_size=64):
        if direction not in ("in", "out"):
            raise ValueError("direction must be 'in' or 'out'")
        if transfer_type not in _TRANSFER_TYPE_TO_BMATTRIBUTES:
            raise ValueError(f"unknown transfer_type: {transfer_type!r}")
        self.direction = direction
        self.transfer_type = transfer_type
        self.bEndpointAddress = (number & 0x0F) | (ENDPOINT_IN if direction == "in" else ENDPOINT_OUT)
        self.bmAttributes = _TRANSFER_TYPE_TO_BMATTRIBUTES[transfer_type]
        self.wMaxPacketSize = max_packet_size
        self.bInterval = 0


class VirtualUsbInterface:
    """pyusbの usb.core.Interface に相当する最小限の記述子(1個 = 1つのalternate setting)。"""

    def __init__(self, number, alternate=0, interface_class=0xFF, interface_subclass=0x00,
                 interface_protocol=0x00, endpoints=(), name=None):
        self.bInterfaceNumber = number
        self.bAlternateSetting = alternate
        self.bInterfaceClass = interface_class
        self.bInterfaceSubClass = interface_subclass
        self.bInterfaceProtocol = interface_protocol
        self.iInterface = 0
        self._name = name
        self._endpoints = list(endpoints)

    @property
    def bNumEndpoints(self):
        return len(self._endpoints)

    def __iter__(self):
        return iter(self._endpoints)


class VirtualUsbConfiguration:
    """pyusbの usb.core.Configuration に相当する最小限の記述子。
    `interfaces` には各interfaceの各alternate settingごとに1個ずつ
    VirtualUsbInterfaceを並べる(pyusb/本ライブラリの扱いと同じ——
    「interface番号」単位でグルーピングされてはいない)。"""

    def __init__(self, value=1, interfaces=(), description=None, self_powered=False, remote_wakeup=False,
                 max_power_ma=100):
        self.bConfigurationValue = value
        self.iConfiguration = 0
        self.bmAttributes = 0x80 | (0x40 if self_powered else 0) | (0x20 if remote_wakeup else 0)
        self.bMaxPower = max(0, int(max_power_ma) // 2)
        self._interfaces = list(interfaces)

    @property
    def bNumInterfaces(self):
        return len({intf.bInterfaceNumber for intf in self._interfaces})

    def __iter__(self):
        return iter(self._interfaces)


class VirtualUsbDevice:
    """pyusbの usb.core.Device に相当する最小限のduck-typedデバイス。
    実USBハードウェアに触れることなく、bridge.py/hardening.pyの既存ロジックを
    そのまま通す(security_audit/_fixtures.pyのFakeDeviceと同じ設計方針)。"""

    def __init__(self, vendor_id, product_id, configurations=(), manufacturer=None, product=None,
                 serial_number=None, device_class=0x00, device_subclass=0x00, device_protocol=0x00,
                 usb_version=(2, 0, 0), device_version=(1, 0, 0),
                 on_control_transfer=None, on_bulk_read=None, on_bulk_write=None):
        self.idVendor = vendor_id
        self.idProduct = product_id
        self.bDeviceClass = device_class
        self.bDeviceSubClass = device_subclass
        self.bDeviceProtocol = device_protocol
        self.bcdUSB = _version_to_bcd(usb_version)
        self.bcdDevice = _version_to_bcd(device_version)
        # 文字列記述子はindex(0以外の整数)で表現し、get_string()側で解決する。
        # get_string()はどんな整数indexでも解決できるよう、実際の文字列は
        # このオブジェクト自身にプライベートな辞書として持たせておく。
        self._strings = {}
        self.iManufacturer = self._intern_string(manufacturer)
        self.iProduct = self._intern_string(product)
        self.iSerialNumber = self._intern_string(serial_number)
        self._configurations = list(configurations) or [VirtualUsbConfiguration(value=1, interfaces=[])]
        self._active_configuration_value = self._configurations[0].bConfigurationValue
        self._plugged = True
        self._claimed_interfaces = set()
        self.on_control_transfer = on_control_transfer
        self.on_bulk_read = on_bulk_read
        self.on_bulk_write = on_bulk_write
        self._backend_ref = None  # make_virtual_usb_backend()が挿し戻す

    def _intern_string(self, value):
        if not value:
            return 0
        index = len(self._strings) + 1
        self._strings[index] = str(value)
        return index

    # ---- usb.util.get_string(dev, index) から呼ばれる ----
    def _resolve_string(self, index):
        return self._strings.get(index)

    # ---- 抜き挿しシミュレーション ----
    @property
    def is_plugged(self):
        return self._plugged

    def plug(self):
        """このデバイスを「挿す」。既存のUsbHotplugWatcherのポーリングが
        自然に検知し、許可済みオリジンにはconnectイベントが届く。"""
        self._plugged = True

    def unplug(self):
        """このデバイスを「抜く」。挿し直すまで find() から見えなくなる。"""
        self._plugged = False
        self._claimed_interfaces.clear()

    # ---- usb.core.Device が実際に持つAPI ----
    def get_active_configuration(self):
        for cfg in self._configurations:
            if cfg.bConfigurationValue == self._active_configuration_value:
                return cfg
        raise Exception("virtual device has no active configuration")

    def set_configuration(self, configuration=None):
        if configuration is None:
            target = self._configurations[0].bConfigurationValue
        elif hasattr(configuration, "bConfigurationValue"):
            target = configuration.bConfigurationValue
        else:
            target = configuration
        if not any(c.bConfigurationValue == target for c in self._configurations):
            raise Exception(f"virtual device has no configuration {target!r}")
        self._active_configuration_value = target
        self._claimed_interfaces.clear()

    def is_kernel_driver_active(self, interface):
        return False  # 仮想デバイスにkernel driverの概念は無い

    def detach_kernel_driver(self, interface):
        pass

    def attach_kernel_driver(self, interface):
        pass

    def set_interface_altsetting(self, interface=None, alternate_setting=None):
        cfg = self.get_active_configuration()
        if not any(intf.bInterfaceNumber == interface and intf.bAlternateSetting == alternate_setting
                    for intf in cfg):
            raise Exception(
                f"virtual device has no interface {interface} alternate setting {alternate_setting}"
            )

    def clear_halt(self, ep):
        pass

    def reset(self):
        # 🆕 v0.0.5a3の制約(README/このファイルのdocstring参照): 記述子構成は
        # 維持したまま、claim状態だけを実機のreset()相当にクリアする。
        self._claimed_interfaces.clear()

    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None):
        if self.on_control_transfer is not None:
            return self.on_control_transfer(
                self, bmRequestType, bRequest, wValue, wIndex, data_or_wLength, timeout
            )
        is_device_to_host = bool(bmRequestType & 0x80)
        if is_device_to_host:
            length = data_or_wLength if isinstance(data_or_wLength, int) else 0
            return bytes(length)
        data = bytes(data_or_wLength or b"")
        return len(data)

    def read(self, endpoint, size_or_buffer, timeout=None):
        if self.on_bulk_read is not None:
            return self.on_bulk_read(self, endpoint, size_or_buffer, timeout)
        length = size_or_buffer if isinstance(size_or_buffer, int) else len(size_or_buffer)
        return bytes(length)

    def write(self, endpoint, data, timeout=None):
        if self.on_bulk_write is not None:
            return self.on_bulk_write(self, endpoint, data, timeout)
        return len(bytes(data))

    def __iter__(self):
        return iter(self._configurations)


def _version_to_bcd(version_tuple):
    major, minor, sub = (list(version_tuple) + [0, 0, 0])[:3]
    return ((major & 0xFF) << 8) | ((minor & 0xF) << 4) | (sub & 0xF)


class VirtualUsbBackend:
    """usb.core モジュールに相当する最小限のduck-typedオブジェクト
    (WebUSBBridge(usb_backend=(backend, util_shim)) のタプル前半に渡す)。
    UsbHotplugWatcherが使う `find(find_all=True)` によるポーリングと、
    実際にfindで得られるデバイス一覧の両方をこの1つのオブジェクトが提供するため、
    抜き挿しシミュレーション(VirtualUsbDevice.plug()/unplug())は
    bridge.py側に一切変更を加えずそのまま動く。"""

    def __init__(self, devices=()):
        self._devices = list(devices)
        for dev in self._devices:
            dev._backend_ref = self

    def __len__(self):
        return len(self._devices)

    def __getitem__(self, index):
        return self._devices[index]

    def __iter__(self):
        return iter(self._devices)

    def add(self, device):
        device._backend_ref = self
        self._devices.append(device)

    def find(self, idVendor=None, idProduct=None, find_all=False, **_kwargs):
        matches = [
            d for d in self._devices
            if d.is_plugged
            and (idVendor is None or d.idVendor == idVendor)
            and (idProduct is None or d.idProduct == idProduct)
        ]
        if find_all:
            return matches
        return matches[0] if matches else None


class VirtualUsbUtilShim:
    """usb.util モジュールに相当する最小限のduck-typedオブジェクト
    (WebUSBBridge(usb_backend=(backend, util_shim)) のタプル後半に渡す)。"""

    ENDPOINT_IN = ENDPOINT_IN
    ENDPOINT_OUT = ENDPOINT_OUT
    ENDPOINT_TYPE_CTRL = ENDPOINT_TYPE_CTRL
    ENDPOINT_TYPE_ISO = ENDPOINT_TYPE_ISO
    ENDPOINT_TYPE_BULK = ENDPOINT_TYPE_BULK
    ENDPOINT_TYPE_INTR = ENDPOINT_TYPE_INTR

    def get_string(self, dev, index):
        value = dev._resolve_string(index)
        if value is None:
            raise Exception(f"virtual device has no string descriptor at index {index}")
        return value

    def endpoint_direction(self, address):
        return ENDPOINT_IN if (address & 0x80) else ENDPOINT_OUT

    def endpoint_type(self, bmAttributes):
        return bmAttributes & 0x03

    def dispose_resources(self, dev):
        pass  # 実機のようなOSハンドルは持たないので何もしなくてよい

    def claim_interface(self, dev, interface):
        dev._claimed_interfaces.add(interface)

    def release_interface(self, dev, interface):
        dev._claimed_interfaces.discard(interface)


def make_virtual_usb_backend(devices=()):
    """VirtualUsbDeviceのリストから `WebUSBBridge(usb_backend=...)` へそのまま
    渡せる `(usb_core相当, usb_util相当)` のタプルを組み立てる。戻り値の
    タプル前半(VirtualUsbBackend)はリストのように扱えるので、
    `backend[0].unplug()` のように後から個々のデバイスを操作できる。"""
    return VirtualUsbBackend(devices), VirtualUsbUtilShim()
