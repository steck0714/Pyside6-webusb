# -*- coding: utf-8 -*-
"""WebUSBBridge.requestDeviceChooser()を、フェイクのpyusbデバイス・フェイクの
チューザーダイアログに差し替えた上で実際に呼び出して検証する統合テスト。
実USBデバイス・実GUI操作なしで、options.filters/exclusionFiltersによる
絞り込みと、選択後のリッチな記述子再構築を確認する。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ★ `pytest`経由ならconftest.pyが同じ処理を先に行うが、`python tests/test_bridge.py`と
# 直接実行した場合はconftest.pyが自動では読み込まれないため、ここでも同じ
# ヘッドレス環境向けオフスクリーン自動フォールバックを行う(理由はconftest.py参照。
# QApplication([])のディスプレイ接続失敗はPythonの例外ではなくプロセスクラッシュに
# なるため、try/exceptでは救えず、生成前に検知して回避する必要がある)。
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from pyside6_webusb.bridge import WebUSBBridge

_app = QApplication.instance() or QApplication([])


# --- test_hardening.py と同じ形のフェイクpyusbオブジェクト ---
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


class _FakeCtx:
    def __init__(self, handle):
        self.handle = handle


class _FakeIsoBackend:
    """usb.backend.libusb1._LibUSB の iso_read/iso_write を模したフェイク。
    実物の挙動(バッファをその場で埋める/書き込みバイト数を返す)を模倣する。"""

    def __init__(self):
        self.iso_read_calls = []
        self.iso_write_calls = []

    def iso_read(self, dev_handle, ep, intf, buff, timeout=None):
        self.iso_read_calls.append({"dev_handle": dev_handle, "ep": ep, "intf": intf, "len": len(buff), "timeout": timeout})
        for i in range(len(buff)):
            buff[i] = 0xEE
        return len(buff)

    def iso_write(self, dev_handle, ep, intf, buff, timeout=None):
        self.iso_write_calls.append({"dev_handle": dev_handle, "ep": ep, "intf": intf, "data": bytes(buff), "timeout": timeout})
        return len(buff)


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
        # 🛡️ isochronous転送(_iso_backend_or_error)向け。既定ではNoneのままにし、
        #    「backendが無い実機/バックエンド」を模す(既存の全テストはこれで
        #    isochronousを試みればNotSupportedErrorへ安全にフォールバックする)。
        #    isochronousの成功パスをテストしたい場合だけenable_fake_iso_backend()
        #    を呼ぶ。
        self.backend = None
        self._ctx = None

    def enable_fake_iso_backend(self):
        self.backend = _FakeIsoBackend()
        self._ctx = _FakeCtx(handle=f"handle-{self.idVendor:04x}:{self.idProduct:04x}")
        return self.backend

    def __iter__(self):
        return iter(self._configurations)

    def get_active_configuration(self):
        # 🛡️ 実pyusbのDevice.get_active_configuration()を模倣。set_configuration()で
        #    切り替えていればそれを、まだ一度も呼ばれていなければ先頭を返す。
        if not self._configurations:
            raise ValueError("no active configuration")
        return getattr(self, "_active_configuration", None) or self._configurations[0]

    def set_configuration(self, configuration=None):
        # 🛡️ selectConfiguration()のclaimed_interfacesリセット確認テスト向け。
        #    実pyusbのDevice.set_configuration()を模倣し、bConfigurationValueが
        #    一致するconfigurationをアクティブにする(0/Noneは「先頭を選ぶ」という
        #    実仕様の挙動をそのまま模す)。
        if configuration is None or configuration == 0:
            self._active_configuration = self._configurations[0]
            return
        for cfg in self._configurations:
            if cfg.bConfigurationValue == configuration:
                self._active_configuration = cfg
                return
        raise ValueError(f"Configuration {configuration} not found")

    def read(self, endpoint, length, timeout=None):
        # 🛡️ pyusb実物のDevice.read()を模倣: endpointはbEndpointAddress(方向ビット込み)
        #    を要求する。呼び出し時に実際に渡された値を記録しておき、
        #    bulkTransferIn()側でIN方向ビット(0x80)が正しく付与されているかを
        #    テストから検証できるようにする。
        self.last_read_call = {"endpoint": endpoint, "length": length, "timeout": timeout}
        if getattr(self, "read_exception", None) is not None:
            raise self.read_exception
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
        if isinstance(data_or_wLength, int):
            return bytes([0xCD]) * min(data_or_wLength, 4)  # IN: ダミーデータ
        return len(data_or_wLength) if data_or_wLength else 0  # OUT: 書き込みバイト数

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

    def get_string(self, dev, index):
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
    """実QDialogの代わり。SELECT_INDEXで「一覧の何番目を選んだか」を制御する
    (Noneなら「キャンセルした」を意味する)。"""
    class DialogCode:
        Accepted = 1
        Rejected = 0

    SELECT_INDEX = 0
    last_devices_info = None  # ダイアログへ実際に渡された(=絞り込み後の)一覧を記録しておく
    last_origin = None
    last_refresh_callback = None
    last_parent = None  # 🛡️ v0.0.4: 実際に渡されたparent(親ウィジェット)を記録しておく

    def __init__(self, devices_info, parent, strings=None, origin=None, refresh_callback=None):
        FakeChooserDialog.last_devices_info = devices_info
        FakeChooserDialog.last_origin = origin
        FakeChooserDialog.last_refresh_callback = refresh_callback
        FakeChooserDialog.last_parent = parent
        self.devices_info = devices_info
        idx = FakeChooserDialog.SELECT_INDEX
        self.selected_device = devices_info[idx] if (idx is not None and idx < len(devices_info)) else None

    def exec(self):
        return self.DialogCode.Accepted if self.selected_device is not None else self.DialogCode.Rejected

    # 実QDialog(=QWidgetのサブクラス)には常に存在するメソッド群。v0.0.4で
    # bridge.py側がダイアログを確実に前面へ出すためexec()の前に呼ぶようになった
    # ため、フェイクにも(no-opでよいので)用意しておく。
    def show(self):
        pass

    def raise_(self):
        pass

    def activateWindow(self):
        pass


def make_bridge(devices, browser_window=None):
    """QWebChannel配線なしで、pyusb部分だけをフェイクに差し替えたWebUSBBridgeを作る。"""
    bridge = WebUSBBridge(browser_window=browser_window)
    bridge._pyusb = lambda: (FakeUsbCore(devices), FakeUsbUtil())
    bridge._load_known_devices = lambda: []
    bridge._record_device_usage = lambda *a, **kw: None
    grants = []
    bridge._grant = lambda origin, vid, pid: grants.append((origin, vid, pid))
    bridge._current_origin = lambda *a, **kw: "https://example.test"
    bridge.__test_grants__ = grants
    return bridge


def test_filters_narrow_the_candidate_list(monkeypatch):
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    dev_b = FakeDevice(0x1234, 0x0002, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a, dev_b])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.SELECT_INDEX = 0
    result = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": [{"vendorId": 0x2341}]})))
    assert result["cancelled"] is False
    assert result["device"]["vendorId"] == 0x2341
    assert len(FakeChooserDialog.last_devices_info) == 1  # dev_bは候補から除外されているはず
    print("test_filters_narrow_the_candidate_list: OK")


def test_empty_filters_array_matches_nothing(monkeypatch):
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.SELECT_INDEX = 0
    # 仕様どおり filters: [] (空配列)は「一致するものなし」
    result = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": []})))
    assert result["cancelled"] is True
    print("test_empty_filters_array_matches_nothing: OK")


def test_exclusion_filters_remove_a_match(monkeypatch):
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.SELECT_INDEX = 0
    result = json.loads(bridge.requestDeviceChooser(json.dumps({
        "filters": [{}], "exclusionFilters": [{"vendorId": 0x2341}],
    })))
    assert result["cancelled"] is True
    print("test_exclusion_filters_remove_a_match: OK")


def test_selected_device_gets_rich_descriptor(monkeypatch):
    cfg = FakeConfiguration(1, [FakeInterface(0, 0, 0xFF, 0, 0, [])])
    dev_a = FakeDevice(0x2341, 0x8036, [cfg])
    bridge = make_bridge([dev_a])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.SELECT_INDEX = 0
    result = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": [{}]})))
    assert result["cancelled"] is False
    # チューザー一覧構築時は軽量記述子だが、選ばれた1台はgetDevices()と同じ
    # リッチな記述子(configurations付き)で返るはず
    assert len(result["device"]["configurations"]) == 1
    print("test_selected_device_gets_rich_descriptor: OK")


def test_grant_recorded_only_on_selection(monkeypatch):
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)

    FakeChooserDialog.SELECT_INDEX = None
    result = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": [{}]})))
    assert result["cancelled"] is True
    assert bridge.__test_grants__ == []

    FakeChooserDialog.SELECT_INDEX = 0
    result = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": [{}]})))
    assert result["cancelled"] is False
    assert bridge.__test_grants__ == [("https://example.test", 0x2341, 0x8036)]
    print("test_grant_recorded_only_on_selection: OK")


def test_settings_fallback_uses_constructor_organization_and_application():
    bridge = WebUSBBridge(settings_organization="Acme", settings_application="Widget")
    s = bridge._known_device_settings()
    assert s is not None
    assert s.organizationName() == "Acme"
    assert s.applicationName() == "Widget"
    print("test_settings_fallback_uses_constructor_organization_and_application: OK")


def test_origin_is_passed_to_the_dialog(monkeypatch):
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.SELECT_INDEX = 0
    bridge.requestDeviceChooser(json.dumps({"filters": [{}]}))
    assert FakeChooserDialog.last_origin == "https://example.test"
    print("test_origin_is_passed_to_the_dialog: OK")


def test_resolve_chooser_parent_window_prefers_browser_window_widget():
    """🛡️ バグ修正(v0.0.4, ユーザー報告): 旧実装はQApplication.activeWindow()だけで
    チューザーダイアログの親を決めており、コンストラクタ/install()経由で
    browser_windowを受け取り self.browser_window へ保存していたにもかかわらず、
    実際の親解決では一切参照していなかった(QWebEngineView経由の非同期コール
    バックではactiveWindow()がOS/ウィンドウマネージャのフォーカス伝播に依存して
    Noneになりやすく、結果としてダイアログが親を持たない独立ウィンドウとして
    開かれ、ブラウザ本体の裏に隠れる等の理由で「画面が出ない」ように見える、
    という実際の不具合報告があった)。browser_windowに実際のQWidgetを渡した
    場合、それが最優先で返ることを確認する。"""
    from PySide6.QtWidgets import QWidget
    window = QWidget()
    try:
        bridge = WebUSBBridge(browser_window=window)
        assert bridge._resolve_chooser_parent_window() is window
    finally:
        window.deleteLater()
    print("test_resolve_chooser_parent_window_prefers_browser_window_widget: OK")


def test_resolve_chooser_parent_window_ignores_non_widget_browser_window():
    """browser_windowは元々「.settingsを持つオブジェクトなら何でもよい」という
    ダックタイピングで文書化されており(READMEの設定永続化用途)、必ずしも
    QWidgetとは限らない。QWidgetではないbrowser_windowを渡した既存ユーザーの
    挙動を壊さないよう、その場合はbrowser_windowそのものではなく、
    (QApplication.activeWindow()や可視なトップレベルウィジェットへの)
    フォールバックへ正しく進むことを確認する。"""
    class SettingsHolder:
        class settings:
            pass

    holder = SettingsHolder()
    bridge = WebUSBBridge(browser_window=holder)
    resolved = bridge._resolve_chooser_parent_window()
    assert resolved is not holder
    print("test_resolve_chooser_parent_window_ignores_non_widget_browser_window: OK")


def test_requestDeviceChooser_passes_browser_window_to_dialog_as_parent(monkeypatch):
    """_resolve_chooser_parent_window()単体ではなく、requestDeviceChooser()の
    実際の呼び出し経路を通しても、ダイアログのparentへbrowser_windowが正しく
    渡っていることを確認する(=配線の最後の一箇所まで繋がっていることの
    統合テスト)。"""
    from PySide6.QtWidgets import QWidget
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    window = QWidget()
    try:
        bridge = make_bridge([dev_a], browser_window=window)
        monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
        FakeChooserDialog.SELECT_INDEX = 0
        result = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": [{}]})))
        assert result["cancelled"] is False, result
        assert FakeChooserDialog.last_parent is window
    finally:
        window.deleteLater()
    print("test_requestDeviceChooser_passes_browser_window_to_dialog_as_parent: OK")


def test_refresh_callback_reflects_newly_plugged_device(monkeypatch):
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.SELECT_INDEX = 0
    bridge.requestDeviceChooser(json.dumps({"filters": [{}]}))
    assert len(FakeChooserDialog.last_refresh_callback()) == 1

    # ダイアログを開いたまま新しいデバイスが挿された、という状況を模擬する
    dev_b = FakeDevice(0x1234, 0x0002, [FakeConfiguration(1, [])])
    bridge._pyusb = lambda: (FakeUsbCore([dev_a, dev_b]), FakeUsbUtil())
    refreshed = FakeChooserDialog.last_refresh_callback()
    assert len(refreshed) == 2
    print("test_refresh_callback_reflects_newly_plugged_device: OK")


def test_full_flow_persists_grant_and_usage_without_mocking_internals(monkeypatch, tmp_path=None):
    """_grant()/_record_device_usage()を(テストのために上書きせず)実際に動かして
    最後まで通す。この2つはtime.time()を使っており、以前 bridge.py に
    `import time` が無いまま出荷され、実行時にNameErrorで静かに失敗していた
    (呼び出し側がtry/exceptで包んでいたため、ダイアログの選択自体は成功する
    ように見えてしまい、許可・利用実績の永続化だけがこっそり失敗していた)。
    filters/exclusionFiltersのテストのようにこれらを丸ごとモックしていると
    この種の欠陥を検出できないため、実装をそのまま通す専用のテストを分けている。
    QSettingsは実システムの設定ストアを汚さないよう、一時ファイルのIniFormatへ
    明示的に切り替える。"""
    import tempfile
    from PySide6.QtCore import QSettings

    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = WebUSBBridge()  # _grant/_record_device_usageは上書きしない(実装をそのまま使う)
    bridge._pyusb = lambda: (FakeUsbCore([dev_a]), FakeUsbUtil())
    bridge._current_origin = lambda *a, **kw: "https://example.test"

    tmp_dir = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp(prefix="pyside6_webusb_test_")
    ini_path = os.path.join(tmp_dir, "settings.ini")
    real_settings = QSettings(ini_path, QSettings.Format.IniFormat)
    bridge._known_device_settings = lambda: real_settings

    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.SELECT_INDEX = 0
    raw = bridge.requestDeviceChooser(json.dumps({"filters": [{}]}))
    result = json.loads(raw)
    assert result["cancelled"] is False
    assert result["device"]["vendorId"] == 0x2341

    granted = bridge.list_granted_origins()
    assert granted.get("https://example.test"), "実際のQSettingsへ許可が永続化されているはず"
    entry = granted["https://example.test"][0]
    assert entry["vendorId"] == 0x2341 and entry["productId"] == 0x8036
    assert isinstance(entry.get("grantedAt"), (int, float)), "grantedAtにtime.time()の値が入っているはず"

    known = bridge._load_known_devices()
    assert any(d.get("vendorId") == 0x2341 for d in known), "利用実績(known devices)にも記録されているはず"
    print("test_full_flow_persists_grant_and_usage_without_mocking_internals: OK")


def test_bulkTransferIn_adds_the_in_direction_bit():
    """USBDevice.transferIn(endpointNumber, length) の実仕様(WebUSB spec, index.bs):
    'Let endpointAddress be endpointNumber | 0x80'。JSから渡ってくるendpointは
    方向ビットを含まない生のendpointNumberであり、pyusbのDevice.read()は
    bEndpointAddress(方向ビット込みの値)を要求する(pyusb公式ドキュメント
    'The endpoint parameter corresponds to the bEndpointAddress member' で確認済み)。
    旧実装はこの変換が抜けており、endpointNumber=1のIN転送がbEndpointAddress=0x01
    (同じ番号のOUT側)を叩きにいってしまい、実機相手には常に失敗していた。
    対照として、transferOut/bulkTransferOutは元々ビット無しのendpointNumberが
    そのまま正しいbEndpointAddressになる(OUT方向は0ビット)ため変換は不要であり、
    そちらは今回変更していないことも合わせて確認する。"""
    ep_in = FakeEndpoint(0x81, 0x02)   # endpoint 1, IN, bulk
    ep_out = FakeEndpoint(0x02, 0x02)  # endpoint 2, OUT, bulk
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_in, ep_out])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True  # このテストの対象はopenDeviceの許可ゲートではない

    open_result = json.loads(bridge.openDevice(0x2341, 0x8036))
    assert open_result["success"] is True
    handle = open_result["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    in_result = json.loads(bridge.bulkTransferIn(handle, 1, 4))
    assert in_result["success"] is True, in_result
    assert dev_a.last_read_call["endpoint"] == 0x81, (
        "endpointNumber=1のIN転送はbEndpointAddress=0x81(=1 | 0x80)をpyusbへ渡すべき"
        f"だが、実際には {dev_a.last_read_call['endpoint']:#x} だった"
    )

    out_result = json.loads(bridge.bulkTransferOut(handle, 2, "AQIDBA=="))
    assert out_result["success"] is True, out_result
    assert dev_a.last_write_call["endpoint"] == 2, (
        "OUT方向は方向ビットが無いのが正しいので、endpointNumberはそのまま2で渡るはず"
    )
    print("test_bulkTransferIn_adds_the_in_direction_bit: OK")


def test_control_transfer_class_request_to_protected_interface_is_blocked():
    """WebUSB仕様「check the validity of the control transfer parameters」:
    requestType=='class' のとき、setup.indexの下位8bitが指すインターフェースが
    保護対象クラスなら(recipientが何であっても)SecurityError。
    旧実装はこの検証が完全に欠落しており、claimInterface()自体は拒否するHIDの
    ようなインターフェースへも、requestType:'class' のcontrolTransferOut/Inを
    直接送るだけでclaimInterfaceの保護を丸ごとバイパスできてしまっていた
    (claimInterfaceを一度も呼ばずに)。ここではrecipientをあえて'device'にして、
    recipient側の(別の)claimチェックに頼らずclass側の検証単体で
    ブロックされることを確認する。"""
    hid_intf = FakeInterface(0, 0, 0x03, 0x01, 0x01, [FakeEndpoint(0x81, 0x03)])  # HID, 未claim
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [hid_intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]

    # bmRequestType = direction:out(0x00) | type:class(0x20) | recipient:device(0x00) = 0x20
    # indexの下位8bit=0 -> interface 0(HID)を指す
    result = json.loads(bridge.controlTransferOut(handle, 0x20, 0x09, 0, 0, ""))
    assert result["success"] is False
    assert result["error"].startswith("SecurityError:"), result
    assert not hasattr(dev_a, "ctrl_transfer_calls"), (
        "保護対象クラスへのclass要求は実機(pyusb)へ届く前にブロックされるべき"
    )
    print("test_control_transfer_class_request_to_protected_interface_is_blocked: OK")


def test_control_transfer_interface_recipient_requires_claim():
    """recipient=='interface' のとき、対象インターフェースがclaim済みでなければ
    (保護対象クラスでなくても)InvalidStateError。claim後は同じ呼び出しが
    通ることも合わせて確認する。"""
    vendor_intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [FakeEndpoint(0x81, 0x02)])  # vendor-specific
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [vendor_intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]

    # bmRequestType = out(0x00) | type:vendor(0x40) | recipient:interface(0x01) = 0x41
    not_claimed = json.loads(bridge.controlTransferOut(handle, 0x41, 0x01, 0, 0, ""))
    assert not_claimed["success"] is False
    assert not_claimed["error"].startswith("InvalidStateError:"), not_claimed
    assert not hasattr(dev_a, "ctrl_transfer_calls")

    claim_result = json.loads(bridge.claimInterface(handle, 0))
    assert claim_result["success"] is True

    claimed = json.loads(bridge.controlTransferOut(handle, 0x41, 0x01, 0, 0, ""))
    assert claimed["success"] is True, claimed
    print("test_control_transfer_interface_recipient_requires_claim: OK")


def test_control_transfer_standard_request_restrictions():
    """spec: requestType=='standard' は (1) controlTransferOut(direction=out)では
    常に拒否、(2) controlTransferInでもGET_STATUS/GET_DESCRIPTOR/
    GET_CONFIGURATION/GET_INTERFACE/SYNCH_FRAME以外は拒否、という制限がある。"""
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [FakeEndpoint(0x81, 0x02)])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]

    # bmRequestType = out(0x00) | type:standard(0x00) | recipient:device(0x00) = 0x00
    out_result = json.loads(bridge.controlTransferOut(handle, 0x00, 0x09, 0, 0, ""))  # SET_CONFIGURATION相当
    assert out_result["success"] is False
    assert out_result["error"].startswith("SecurityError:"), out_result

    # bmRequestType = in(0x80) | type:standard(0x00) | recipient:device(0x00) = 0x80、
    # だが許可リスト外のrequest(0x05 = SET_ADDRESS相当)
    bad_in = json.loads(bridge.controlTransferIn(handle, 0x80, 0x05, 0, 0, 8))
    assert bad_in["success"] is False
    assert bad_in["error"].startswith("SecurityError:"), bad_in

    # 許可リスト内(0x00 = GET_STATUS)なら通る
    good_in = json.loads(bridge.controlTransferIn(handle, 0x80, 0x00, 0, 0, 2))
    assert good_in["success"] is True, good_in
    print("test_control_transfer_standard_request_restrictions: OK")


def test_bulk_transfer_and_clearHalt_require_claimed_interface():
    """実Chrome(Blinkの USBDevice::EnsureEndpointAvailable(), 実際に取得して確認)は
    transferIn/transferOut/clearHaltの前に、対象endpointが「claim済みの
    interfaceに属している」ことを毎回検証する。旧実装はcontrolTransferIn/Outにしか
    この種の検証を入れておらず、bulkTransferIn/Out・clearHaltは対象デバイスが
    開いてさえいればclaimInterface()を一度も呼ばずに実機へ転送を投げられて
    しまっていた(保護対象クラスのインターフェースへも、controlTransferを介さず
    直接bulk/interruptで読み書きできてしまう抜け穴だった)。"""
    ep_in = FakeEndpoint(0x81, 0x02)
    ep_out = FakeEndpoint(0x02, 0x02)
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_in, ep_out])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]

    # claimInterface()を一度も呼んでいない状態
    in_before = json.loads(bridge.bulkTransferIn(handle, 1, 4))
    assert in_before["success"] is False
    assert in_before["error"].startswith("NotFoundError:"), in_before

    out_before = json.loads(bridge.bulkTransferOut(handle, 2, "AQ=="))
    assert out_before["success"] is False
    assert out_before["error"].startswith("NotFoundError:"), out_before

    halt_before = json.loads(bridge.clearHalt(handle, "in", 1))
    assert halt_before["success"] is False
    assert halt_before["error"].startswith("NotFoundError:"), halt_before

    assert not hasattr(dev_a, "last_read_call")
    assert not hasattr(dev_a, "last_write_call")

    # claimInterface()後は全て通る
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True
    assert json.loads(bridge.bulkTransferIn(handle, 1, 4))["success"] is True
    assert json.loads(bridge.bulkTransferOut(handle, 2, "AQ=="))["success"] is True
    assert json.loads(bridge.clearHalt(handle, "in", 1))["success"] is True
    print("test_bulk_transfer_and_clearHalt_require_claimed_interface: OK")


def test_bulk_and_control_transfer_in_report_babble_status():
    """🆕 v0.0.4a0: WebUSB仕様のUSBTransferStatusは{"ok","stall","babble"}の3値。
    babble(デバイスが要求より多くのデータを返した場合)は、stallと同じく
    Promiseのreject対象ではなくstatus:'babble'を伴う"成功"resolveとして
    返るべき。pyusbのLIBUSB_ERROR_OVERFLOW(errno=75)相当の例外をFakeDeviceに
    仕込んで確認する。"""
    ep_in = FakeEndpoint(0x81, 0x02)  # bulk IN
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_in])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    class FakeOverflowError(Exception):
        errno = 75
    dev_a.read_exception = FakeOverflowError("[Errno 75] Overflow")

    bulk_result = json.loads(bridge.bulkTransferIn(handle, 1, 4))
    assert bulk_result["success"] is True, bulk_result
    assert bulk_result["status"] == "babble", bulk_result

    dev_a.ctrl_transfer_exception = FakeOverflowError("[Errno 75] Overflow")
    ctrl_result = json.loads(bridge.controlTransferIn(handle, 0xA1, 1, 0, 0, 4))
    assert ctrl_result["success"] is True, ctrl_result
    assert ctrl_result["status"] == "babble", ctrl_result
    print("test_bulk_and_control_transfer_in_report_babble_status: OK")


def test_bulk_and_control_transfer_timeout_scales_with_length():
    """🆕 v0.0.4a0: 固定5秒だったtimeoutが、要求サイズに応じてスケールされ、
    実際にpyusbへ渡っていることを確認する(WebADB等の大容量ペイロードでも
    早期タイムアウトで打ち切られないようにするための修正)。"""
    from pyside6_webusb.hardening import scaled_transfer_timeout_ms
    ep_in = FakeEndpoint(0x81, 0x02)
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_in])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    big_length = 2_000_000  # 2MB相当のIN転送(WebADBのファイル転送規模を想定)
    assert json.loads(bridge.bulkTransferIn(handle, 1, big_length))["success"] is True
    assert dev_a.last_read_call["timeout"] == scaled_transfer_timeout_ms(big_length)
    assert dev_a.last_read_call["timeout"] > 5000, "旧来の固定5秒より長くなっているはず"

    assert json.loads(bridge.controlTransferIn(handle, 0xA1, 1, 0, 0, 60000))["success"] is True
    assert dev_a.ctrl_transfer_calls[-1]["timeout"] == scaled_transfer_timeout_ms(60000)
    print("test_bulk_and_control_transfer_timeout_scales_with_length: OK")


def test_bulk_and_control_transfer_reject_absurdly_large_length():
    """🆕 v0.0.4a0: 行儀の悪い/悪意あるページが天文学的なlengthを渡すだけで
    ホスト側に無制限のメモリ確保を強制できないよう、実務上の上限を設けた。
    (仕様上の型はbulk=unsigned long、control=unsigned shortだが、素直に
    信用してすぐさまその場でバッファを確保するのは安全ではない。)"""
    from pyside6_webusb.hardening import BULK_TRANSFER_MAX_LENGTH, CONTROL_TRANSFER_MAX_LENGTH
    ep_in = FakeEndpoint(0x81, 0x02)
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_in])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    too_big_bulk = json.loads(bridge.bulkTransferIn(handle, 1, BULK_TRANSFER_MAX_LENGTH + 1))
    assert too_big_bulk["success"] is False
    assert too_big_bulk["error"].startswith("IndexSizeError:"), too_big_bulk
    assert not hasattr(dev_a, "last_read_call"), "上限超過時はpyusbのread()すら呼ばれないべき"

    too_big_ctrl = json.loads(bridge.controlTransferIn(handle, 0xA1, 1, 0, 0, CONTROL_TRANSFER_MAX_LENGTH + 1))
    assert too_big_ctrl["success"] is False
    assert too_big_ctrl["error"].startswith("IndexSizeError:"), too_big_ctrl
    print("test_bulk_and_control_transfer_reject_absurdly_large_length: OK")


def test_isochronous_transfer_rejects_oversized_total_packet_lengths():
    """🆕 v0.0.4a0: isochronousTransferIn/Outにも、packetLengths合計に対する
    実務上の上限を追加した。"""
    from pyside6_webusb.hardening import ISOCHRONOUS_TRANSFER_MAX_TOTAL_LENGTH
    ep_iso_in = FakeEndpoint(0x83, 0x01)
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_iso_in])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    huge_packet = ISOCHRONOUS_TRANSFER_MAX_TOTAL_LENGTH // 2 + 1
    result = json.loads(bridge.isochronousTransferIn(handle, 3, json.dumps([huge_packet, huge_packet])))
    assert result["success"] is False
    assert result["error"].startswith("IndexSizeError:"), result
    print("test_isochronous_transfer_rejects_oversized_total_packet_lengths: OK")


def test_bulk_transfer_large_payload_round_trip_via_base64():
    """🆕 v0.0.4a0: hexからbase64への移行後も、WebADB規模(ここでは300KB)の
    ペイロードがブリッジを一往復しても欠落・破損しないことを、Python側の
    経路(base64.b64encode/decode)でも確認する(JS側の大容量往復は
    test_polyfill.jsで別途、チャンク分割の落とし穴込みで検証済み)。"""
    import base64
    ep_in = FakeEndpoint(0x81, 0x02)
    ep_out = FakeEndpoint(0x02, 0x02)
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_in, ep_out])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    payload = bytes((i * 7 + 3) % 256 for i in range(300_000))
    out_result = json.loads(bridge.bulkTransferOut(handle, 2, base64.b64encode(payload).decode("ascii")))
    assert out_result["success"] is True, out_result
    assert dev_a.last_write_call["data"] == payload, "300KBのペイロードが1バイトも欠落・破損せず届くはず"
    print("test_bulk_transfer_large_payload_round_trip_via_base64: OK")


def test_bulk_transfer_rejects_out_of_range_endpoint_number():
    """実Chromeは endpoint番号が 1-15 の範囲外(0または16以上)だと
    IndexSizeErrorで即座に拒否する(EnsureEndpointAvailable())。"""
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [FakeEndpoint(0x81, 0x02)])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    zero_result = json.loads(bridge.bulkTransferIn(handle, 0, 4))
    assert zero_result["success"] is False
    assert zero_result["error"].startswith("IndexSizeError:"), zero_result

    too_big_result = json.loads(bridge.bulkTransferIn(handle, 16, 4))
    assert too_big_result["success"] is False
    assert too_big_result["error"].startswith("IndexSizeError:"), too_big_result
    print("test_bulk_transfer_rejects_out_of_range_endpoint_number: OK")


def test_bulkTransferIn_and_Out_reject_isochronous_endpoint():
    """WebUSB仕様のtransferIn/transferOutアルゴリズムは、対象endpointのtypeが
    bulkでもinterruptでもなければInvalidAccessErrorを返すと定めている
    (isochronousTransferIn/Outが別メソッドとして独立して用意されているのは
    このため)。
    🛡️ バグ修正(v0.0.4): 旧実装はrequired_typeを指定しておらず、isochronous
    専用のendpointに対してもbulkTransferIn/Out経由でread()/write()できて
    しまっていた。pyusbのDevice.read()/write()自体はendpoint記述子から
    転送タイプを自動判別して実際に転送してしまうため、実機を使わないと
    気づきにくい抜け穴だった。"""
    ep_iso_in = FakeEndpoint(0x83, 0x01)   # endpoint 3, IN, isochronous
    ep_iso_out = FakeEndpoint(0x04, 0x01)  # endpoint 4, OUT, isochronous
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_iso_in, ep_iso_out])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    in_result = json.loads(bridge.bulkTransferIn(handle, 3, 4))
    assert in_result["success"] is False
    assert in_result["error"].startswith("InvalidAccessError:"), in_result
    assert not hasattr(dev_a, "last_read_call"), "isochronous endpointへは実機のread()すら呼ばれないべき"

    out_result = json.loads(bridge.bulkTransferOut(handle, 4, "AQ=="))
    assert out_result["success"] is False
    assert out_result["error"].startswith("InvalidAccessError:"), out_result
    assert not hasattr(dev_a, "last_write_call")
    print("test_bulkTransferIn_and_Out_reject_isochronous_endpoint: OK")


def test_isochronousTransfer_without_iso_backend_returns_not_supported():
    """pyusbの公開API(usb.core.Device)にはisochronous転送メソッドが無く、
    このブリッジはlibusb1バックエンドの内部API(iso_read/iso_write)へ
    dev._ctx.handle経由でアクセスするワークアラウンドに頼っている。
    それが利用できない環境(backend=None、非libusb1バックエンド等)では、
    例外を投げず、はっきりしたNotSupportedErrorへ安全にフォールバックする
    べきことを確認する。"""
    ep_iso_in = FakeEndpoint(0x83, 0x01)  # endpoint 3, IN, isochronous
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_iso_in])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])  # backend=None(既定)
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    result = json.loads(bridge.isochronousTransferIn(handle, 3, json.dumps([32, 32])))
    assert result["success"] is False
    assert result["error"].startswith("NotSupportedError:"), result
    print("test_isochronousTransfer_without_iso_backend_returns_not_supported: OK")


def test_isochronousTransfer_rejects_non_uniform_packet_lengths():
    """pyusbのiso_read/iso_writeは(libusb_get_max_iso_packet_size()から求めた)
    均一なパケット長でしかバッファを分割できないため、packetLengthsの要素が
    全て同じでない場合はNotSupportedErrorにする(誤った長さ・誤った分割で
    黙って実機へ投げるよりはるかに安全)。"""
    ep_iso_in = FakeEndpoint(0x83, 0x01)
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_iso_in])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    dev_a.enable_fake_iso_backend()
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    result = json.loads(bridge.isochronousTransferIn(handle, 3, json.dumps([16, 32])))
    assert result["success"] is False
    assert result["error"].startswith("NotSupportedError:"), result
    print("test_isochronousTransfer_rejects_non_uniform_packet_lengths: OK")


def test_isochronousTransfer_requires_claimed_isochronous_endpoint():
    """endpointが(1)claim済みインターフェースに属していない、または
    (2)見つかってもisochronousタイプでない場合は、実転送を試みる前に
    (NotFoundError/InvalidAccessErrorで)拒否する。"""
    ep_bulk = FakeEndpoint(0x81, 0x02)    # endpoint 1, IN, bulk(isochronousではない)
    ep_iso_in = FakeEndpoint(0x83, 0x01)  # endpoint 3, IN, isochronous
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_bulk, ep_iso_in])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    dev_a.enable_fake_iso_backend()
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]

    not_claimed = json.loads(bridge.isochronousTransferIn(handle, 3, json.dumps([32])))
    assert not_claimed["success"] is False
    assert not_claimed["error"].startswith("NotFoundError:"), not_claimed

    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    wrong_type = json.loads(bridge.isochronousTransferIn(handle, 1, json.dumps([32])))
    assert wrong_type["success"] is False
    assert wrong_type["error"].startswith("InvalidAccessError:"), wrong_type
    print("test_isochronousTransfer_requires_claimed_isochronous_endpoint: OK")


def test_isochronousTransfer_success_path_with_fake_backend():
    """フェイクのiso backendを使い、方向ビットの付与・パケット分割・戻り値の
    組み立てが正しく行われることを確認する。
    ⚠️ 実USBハードウェアが無いため、実機相手のisochronous転送そのものは
    このテストでは検証できていない(検証できているのはPython側のロジックのみ)。"""
    ep_iso_in = FakeEndpoint(0x83, 0x01)   # endpoint 3, IN
    ep_iso_out = FakeEndpoint(0x04, 0x01)  # endpoint 4, OUT
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [ep_iso_in, ep_iso_out])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    fake_backend = dev_a.enable_fake_iso_backend()
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True

    in_result = json.loads(bridge.isochronousTransferIn(handle, 3, json.dumps([4, 4])))
    assert in_result["success"] is True, in_result
    assert len(in_result["packets"]) == 2
    assert all(p["status"] == "ok" for p in in_result["packets"])
    assert fake_backend.iso_read_calls[-1]["ep"] == 0x83, "IN方向ビット(0x80)込みのアドレスで呼ぶべき"
    # 🛡️ バグ修正(v0.0.4)の回帰テスト: pyusb実ソース(libusb1.py)確認済みの
    # iso_read(dev_handle, ep, intf, buff, timeout)の第3引数intfには、
    # エンドポイント番号(3)ではなくインターフェース番号(0)が渡るべき。
    # 旧実装はここにendpoint番号をそのまま渡していた。
    assert fake_backend.iso_read_calls[-1]["intf"] == 0, \
        "第3引数にはエンドポイント番号(3)ではなくインターフェース番号(0)を渡すべき"

    out_result = json.loads(bridge.isochronousTransferOut(handle, 4, "AQIDBAUGBwg=", json.dumps([4, 4])))
    assert out_result["success"] is True, out_result
    assert len(out_result["packets"]) == 2
    assert fake_backend.iso_write_calls[-1]["ep"] == 4
    assert fake_backend.iso_write_calls[-1]["data"] == bytes.fromhex("0102030405060708")
    assert fake_backend.iso_write_calls[-1]["intf"] == 0, \
        "第3引数にはエンドポイント番号(4)ではなくインターフェース番号(0)を渡すべき"
    print("test_isochronousTransfer_success_path_with_fake_backend: OK")


def test_isochronousTransfer_passes_interface_number_not_endpoint_number_as_intf():
    """前のテストは偶然インターフェース番号が0のため、「常に0を渡す」ような
    誤実装でも通ってしまいかねない。ここではインターフェース番号(7)と
    エンドポイント番号(3/4)を明確に異ならせ、backendのintf引数に本当に
    インターフェース番号が渡っているかを曖昧さなく確認する。"""
    ep_iso_in = FakeEndpoint(0x83, 0x01)   # endpoint 3, IN
    ep_iso_out = FakeEndpoint(0x04, 0x01)  # endpoint 4, OUT
    intf = FakeInterface(7, 0, 0xFF, 0x00, 0x00, [ep_iso_in, ep_iso_out])  # interface number 7
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    fake_backend = dev_a.enable_fake_iso_backend()
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]
    assert json.loads(bridge.claimInterface(handle, 7))["success"] is True

    json.loads(bridge.isochronousTransferIn(handle, 3, json.dumps([4])))
    assert fake_backend.iso_read_calls[-1]["intf"] == 7, fake_backend.iso_read_calls[-1]

    json.loads(bridge.isochronousTransferOut(handle, 4, "AQIDBA==", json.dumps([4])))
    assert fake_backend.iso_write_calls[-1]["intf"] == 7, fake_backend.iso_write_calls[-1]
    print("test_isochronousTransfer_passes_interface_number_not_endpoint_number_as_intf: OK")


def test_selectAlternateInterface_requires_claimed_interface():
    """実Chrome(usb_device.ccのUSBDevice::selectAlternateInterface()を実際に
    取得して確認)は、これを呼ぶ前に対象interfaceがclaim済みであることを要求する
    (EnsureInterfaceClaimed()、未claimならInvalidStateError)。旧実装はこの
    確認が完全に欠落しており、claimInterface()を一度も呼ばずに任意の
    インターフェース番号のalternate settingを変更できてしまっていた。"""
    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [FakeEndpoint(0x81, 0x02)])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]

    not_claimed = json.loads(bridge.selectAlternateInterface(handle, 0, 1))
    assert not_claimed["success"] is False
    assert not_claimed["error"].startswith("InvalidStateError:"), not_claimed

    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True
    claimed = json.loads(bridge.selectAlternateInterface(handle, 0, 1))
    assert claimed["success"] is True, claimed
    print("test_selectAlternateInterface_requires_claimed_interface: OK")


def test_claimInterface_and_releaseInterface_require_configuration_selected():
    """実Chrome(usb_device.ccのUSBDevice::claimInterface()/releaseInterface()を
    実際に取得して確認)は、どちらもEnsureDeviceConfigured()相当のチェック
    (configurationが選択されていること)を先に行う。旧実装はこれが無く、
    configuration未選択時のclaimInterface()は(結果的には拒否されるものの)
    「保護対象クラス」という不正確な理由のエラーになっていた。"""
    dev_a = FakeDevice(0x2341, 0x8036, [])  # configurationを1つも持たない = get_active_configuration()が例外を送出
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]

    claim_result = json.loads(bridge.claimInterface(handle, 0))
    assert claim_result["success"] is False
    assert claim_result["error"].startswith("InvalidStateError:"), claim_result

    release_result = json.loads(bridge.releaseInterface(handle, 0))
    assert release_result["success"] is False
    assert release_result["error"].startswith("InvalidStateError:"), release_result
    print("test_claimInterface_and_releaseInterface_require_configuration_selected: OK")


def test_selectConfiguration_resets_claimed_interfaces():
    """WebUSB仕様(USBDevice.selectConfiguration()): 成功時に[[claimedInterface]]を
    全てfalseへリセットする(configurationが変われば、同じインターフェース番号でも
    中身が別物になりうるため)。
    🛡️ バグ修正(v0.0.4): 旧実装はdev.set_configuration()を呼ぶだけでclaimed_interfaces
    (状態追跡用のset)を一切リセットしていなかった。config1でinterface 0をclaimした後
    config2へ切り替えても「interface 0はclaim済み」という古い状態がそのまま残ってしまい、
    config2上のinterface 0は実際には一度もclaimしていないのに、selectAlternateInterface()
    等がそれを誤って許可し続けていた。selectConfiguration自体がこれまで一度も
    テストされていなかったため、あわせてFakeDeviceにも(未実装だった)
    set_configuration()を追加している。"""
    intf_cfg1 = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [FakeEndpoint(0x81, 0x02)])
    intf_cfg2 = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [FakeEndpoint(0x81, 0x02)])
    dev_a = FakeDevice(0x2341, 0x8036, [
        FakeConfiguration(1, [intf_cfg1]),
        FakeConfiguration(2, [intf_cfg2]),
    ])
    bridge = make_bridge([dev_a])
    bridge._is_granted = lambda *a, **kw: True
    handle = json.loads(bridge.openDevice(0x2341, 0x8036))["handle"]

    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True
    # config1のまま: claim済みなのでselectAlternateInterfaceは通る
    assert json.loads(bridge.selectAlternateInterface(handle, 0, 0))["success"] is True

    select_result = json.loads(bridge.selectConfiguration(handle, 2))
    assert select_result["success"] is True, select_result
    assert dev_a.get_active_configuration().bConfigurationValue == 2

    # config2切り替え後は、config1時代のclaimは引き継がれないはず
    still_claimed = json.loads(bridge.selectAlternateInterface(handle, 0, 0))
    assert still_claimed["success"] is False
    assert still_claimed["error"].startswith("InvalidStateError:"), still_claimed

    # config2側で改めてclaimすれば、もちろん通る
    assert json.loads(bridge.claimInterface(handle, 0))["success"] is True
    assert json.loads(bridge.selectAlternateInterface(handle, 0, 0))["success"] is True
    print("test_selectConfiguration_resets_claimed_interfaces: OK")


def test_requestDeviceChooser_reentrancy_guard(monkeypatch):
    """dlg.exec()は(実物のQtでは)ネストしたQtイベントループを回すため、その最中に
    同じWebUSBBridgeインスタンスへもう一度requestDeviceChooser()が呼ばれると、
    チューザーダイアログが二重に開いてしまう恐れがある。ここではFakeChooserDialog.exec()
    の中から(="ダイアログが開いている最中"に相当するタイミングで)
    bridge.requestDeviceChooser()を再帰的に呼び出し、内側の呼び出しが
    InvalidStateErrorで即座に弾かれ、外側の(正規の)呼び出しは通常どおり成功し、
    完了後はガードフラグが確実に解除されていることを確認する。"""
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    reentrant_raw = {}

    class ReentrantChooserDialog(FakeChooserDialog):
        def exec(self):
            reentrant_raw["result"] = bridge.requestDeviceChooser(json.dumps({"filters": [{}]}))
            return super().exec()

    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", ReentrantChooserDialog)
    ReentrantChooserDialog.SELECT_INDEX = 0
    outer = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": [{}]})))

    assert "result" in reentrant_raw, "exec()の中からの再入呼び出しが実行されていない"
    inner = json.loads(reentrant_raw["result"])
    assert inner["cancelled"] is True
    assert inner.get("error", "").startswith("InvalidStateError:"), (
        f"再入時はInvalidStateErrorで即座に弾かれるべきだが、実際には {inner!r}"
    )
    assert outer["cancelled"] is False, "外側の(正規の)呼び出しは通常どおり成功するはず"
    assert bridge._chooser_active is False, "呼び出し完了後はガードフラグが必ず解除されているべき"
    print("test_requestDeviceChooser_reentrancy_guard: OK")


def test_frame_tracker_wired_denies_empty_and_forged_tokens():
    """🛡️ 0.0.2b0で見つかった脆弱性(クロスオリジンiframeがトップレベルページに
    成りすませる)を、0.0.3bで実装したフレーム単位オリジン特定が実際に防いでいる
    ことを確認する核心的なテスト。_frame_trackerが配線されている(=install()経由の
    実運用を模した)状態で、
      - 正規のトークン(トラッカーが「本当にiframe自身のオリジン」だと知っている
        値)を渡した呼び出しは、そのiframe自身に許可されたデバイスだけを扱える
      - 空文字列や、でたらめな(=盗み見/偽造された)トークンを渡した呼び出しは、
        (素のQWebChannelオブジェクトを直接叩く敵対的なコードを想定したもの)
        トップレベルページへ成りすますことなく、常にオリジン不明として拒否される
    ことを確認する。"""
    class FakeFrameTracker:
        def __init__(self, mapping):
            self._mapping = mapping

        def origin_for_token(self, token):
            return self._mapping.get(token) if token else None

    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    del bridge._current_origin  # make_bridge()の固定値lambdaオーバーライドを解除し、本来のメソッド(_frame_trackerを見る)へ戻す
    top_level_origin = "https://top-level-page.example"
    iframe_origin = "https://cross-origin-iframe.example"
    iframe_token = "genuine-token-for-the-iframe"
    bridge._frame_tracker = FakeFrameTracker({iframe_token: iframe_origin})
    # このテストの対象はフレーム単位オリジン解決そのものなので、許可判定は
    # 「iframe自身のオリジンにだけ許可がある」という状況を素朴に模す。
    bridge._is_granted = lambda origin, vid, pid: origin == iframe_origin

    # 正規のトークンでは、iframe自身に許可されたデバイスを開ける。
    genuine = json.loads(bridge.openDevice(0x2341, 0x8036, iframe_token))
    assert genuine["success"] is True, genuine

    # 空トークン(=トークンを送らない)では、トップレベルページに成りすませない
    # (トップレベルページには実運用上page.url()経由のトークンがあるはずだが、
    # このテストのフェイクトラッカーはトップレベルページ用のトークンを一切
    # 知らないので、常にNoneに解決される=拒否される)。
    empty_token_attempt = json.loads(bridge.openDevice(0x2341, 0x8036, ""))
    assert empty_token_attempt["success"] is False
    assert "Permission denied" in empty_token_attempt["error"] or "denied" in empty_token_attempt["error"].lower()

    # でたらめな(=知り得ないはずの)トークンでも同様に拒否される。
    forged_attempt = json.loads(bridge.openDevice(0x2341, 0x8036, "totally-forged-token"))
    assert forged_attempt["success"] is False
    print("test_frame_tracker_wired_denies_empty_and_forged_tokens: OK")


def test_frame_tracker_wired_isolates_handles_between_different_frame_origins():
    """フレームトラッカー配線時、あるオリジン(トークンA)が開いたハンドルを、
    別のオリジン(トークンB)からは(handle_idの数値さえ分かっていても)使えない
    ことを確認する(_get_open_device()のorigin照合がframe_token経由でも
    正しく機能していることの確認)。"""
    class FakeFrameTracker:
        def __init__(self, mapping):
            self._mapping = mapping

        def origin_for_token(self, token):
            return self._mapping.get(token) if token else None

    intf = FakeInterface(0, 0, 0xFF, 0x00, 0x00, [FakeEndpoint(0x81, 0x02)])
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [intf])])
    bridge = make_bridge([dev_a])
    del bridge._current_origin  # make_bridge()の固定値lambdaオーバーライドを解除
    origin_a, token_a = "https://frame-a.example", "token-a"
    origin_b, token_b = "https://frame-b.example", "token-b"
    bridge._frame_tracker = FakeFrameTracker({token_a: origin_a, token_b: origin_b})
    bridge._is_granted = lambda origin, vid, pid: origin in (origin_a, origin_b)

    open_result = json.loads(bridge.openDevice(0x2341, 0x8036, token_a))
    assert open_result["success"] is True
    handle = open_result["handle"]

    # 同じhandle_idでも、別オリジン(token_b)からはclaimInterfaceできない。
    stolen_attempt = json.loads(bridge.claimInterface(handle, 0, token_b))
    assert stolen_attempt["success"] is False
    assert stolen_attempt["error"] == "Invalid device handle"

    # 発行元本人(token_a)なら問題なく使える。
    legit_attempt = json.loads(bridge.claimInterface(handle, 0, token_a))
    assert legit_attempt["success"] is True, legit_attempt
    print("test_frame_tracker_wired_isolates_handles_between_different_frame_origins: OK")


def test_requestDeviceChooser_is_registered_as_qt_slot():
    """QWebChannel's QMetaObjectPublisher only exposes methods that are registered
    as Qt Slots on staticMetaObject to the JS-side proxy object -- plain Python
    methods are invisible to it. Every test above calls
    bridge.requestDeviceChooser(...) directly from Python, so they all pass
    regardless of whether @Slot is present or attached to the right method,
    leaving a blind spot where "every test is green" while the method is
    actually unreachable from JS. (This is exactly what happened in practice:
    @Slot(str, result=str) had been misattached to the private helper
    _enumerate_filtered_devices instead of requestDeviceChooser.) This test
    closes that blind spot by inspecting the metaobject directly."""
    from PySide6.QtCore import QMetaMethod

    mo = WebUSBBridge.staticMetaObject
    slot_names = {
        bytes(mo.method(i).methodSignature()).decode().split("(", 1)[0]
        for i in range(mo.methodCount())
        if mo.method(i).methodType() == QMetaMethod.MethodType.Slot
    }
    assert "requestDeviceChooser" in slot_names, (
        "requestDeviceChooser is missing @Slot (or it was attached to the wrong "
        "method), so it can't be called from JS's navigator.usb.requestDevice() "
        "via QWebChannel"
    )
    # _enumerate_filtered_devices is a private helper whose real parameters are
    # usb_core/usb_util (pyusb modules) and filters/exclusion_filters (lists) --
    # none of which can be marshalled across a QWebChannel/JSON boundary, so it
    # must never be exposed to JS as a Slot.
    assert "_enumerate_filtered_devices" not in slot_names, (
        "_enumerate_filtered_devices must remain a private helper; it must not "
        "be registered as a @Slot exposed to JS via QWebChannel"
    )
    # _request_device_chooser_impl is the private implementation behind the
    # reentrancy-guarded requestDeviceChooser() wrapper; it must stay
    # unreachable from JS for the same reason.
    assert "_request_device_chooser_impl" not in slot_names, (
        "_request_device_chooser_impl must remain a private helper; exposing it "
        "as a @Slot would let JS bypass requestDeviceChooser()'s reentrancy guard"
    )
    # _control_transfer_validation_error enforces protected-class/claim checks for
    # controlTransferIn/Out; it must stay unreachable from JS so a page can't call
    # it directly with fabricated arguments to probe or bypass those checks.
    assert "_control_transfer_validation_error" not in slot_names, (
        "_control_transfer_validation_error must remain a private helper, not a "
        "JS-reachable @Slot"
    )
    assert "_endpoint_available_or_error" not in slot_names, (
        "_endpoint_available_or_error must remain a private helper, not a "
        "JS-reachable @Slot"
    )
    assert "_iso_backend_or_error" not in slot_names and "_validate_packet_lengths" not in slot_names, (
        "isochronous transfer helpers must remain private, not JS-reachable @Slots"
    )
    print("test_requestDeviceChooser_is_registered_as_qt_slot: OK")


if __name__ == "__main__":
    class _FakeMonkeypatch:
        """pytestなしでも走らせられるよう、monkeypatch.setattr相当を素朴に実装したもの。"""
        def setattr(self, target, value):
            module_path, attr = target.rsplit(".", 1)
            import importlib
            mod = importlib.import_module(module_path)
            setattr(mod, attr, value)

    mp = _FakeMonkeypatch()
    test_filters_narrow_the_candidate_list(mp)
    test_empty_filters_array_matches_nothing(mp)
    test_exclusion_filters_remove_a_match(mp)
    test_selected_device_gets_rich_descriptor(mp)
    test_grant_recorded_only_on_selection(mp)
    test_settings_fallback_uses_constructor_organization_and_application()
    test_origin_is_passed_to_the_dialog(mp)
    test_refresh_callback_reflects_newly_plugged_device(mp)
    test_full_flow_persists_grant_and_usage_without_mocking_internals(mp)
    test_bulkTransferIn_adds_the_in_direction_bit()
    test_control_transfer_class_request_to_protected_interface_is_blocked()
    test_control_transfer_interface_recipient_requires_claim()
    test_control_transfer_standard_request_restrictions()
    test_bulk_transfer_and_clearHalt_require_claimed_interface()
    test_bulk_transfer_rejects_out_of_range_endpoint_number()
    test_isochronousTransfer_without_iso_backend_returns_not_supported()
    test_isochronousTransfer_rejects_non_uniform_packet_lengths()
    test_isochronousTransfer_requires_claimed_isochronous_endpoint()
    test_isochronousTransfer_success_path_with_fake_backend()
    test_selectAlternateInterface_requires_claimed_interface()
    test_claimInterface_and_releaseInterface_require_configuration_selected()
    test_frame_tracker_wired_denies_empty_and_forged_tokens()
    test_frame_tracker_wired_isolates_handles_between_different_frame_origins()
    test_requestDeviceChooser_reentrancy_guard(mp)
    test_requestDeviceChooser_is_registered_as_qt_slot()
    print("ALL BRIDGE TESTS PASSED")
