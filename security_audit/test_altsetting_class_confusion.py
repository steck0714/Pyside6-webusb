# -*- coding: utf-8 -*-
"""最重要所見: 「同一インターフェース番号内で、alternate settingごとに
bInterfaceClassが異なる複合(コンポジット)USBデバイス」による保護対象
インターフェースクラス判定のバイパス。

脅威モデル: 悪意ある(または侵害された)USBデバイス自体("クラッカー"が
用意した安価なプログラマブルUSBデバイス、例えばArduino/Teensy等で自由に
作成できる)。CVE-2018-6125(Yubico調査: WebUSBがU2F/HIDセキュリティキーへの
オリジンチェックを迂回してアクセスできてしまう問題、Chrome 67でHID
インターフェースクラスへのアクセスを禁止して対処)と同系統の、
「保護対象インターフェースクラス(HID等)への到達を防ぐ」という
セキュリティ境界そのものに対する回避策。

hardening.pyのinterface_class_for()は、指定したinterface_numberに一致する
「現在アクティブなconfiguration内の最初のInterfaceエントリ」のbInterfaceClass
だけを返し、bAlternateSettingを一切考慮しない(=alternate setting単位の
判定ができない)。bridge.pyの_endpoint_available_or_error()も同様に、
「claim済みのinterface番号が持つ全alternateを対象に」endpointを探索する
(選択中のalternate settingまでは追跡しない)設計だと明記されている。

この2つの簡略化はどちらも開発者自身がdocstring内で明記・認識している
(「(稀だが)想定していない」「実害は小さく...安全側からは外れない」)。
しかし実際には、次の手順で組み合わせると保護対象クラスへの実データ
転送そのものが可能になってしまう:

  1. interface 0 のalternate setting 0を「無害な」vendor-specific
     (0xFF)クラスとして宣言する(claimInterface()はこれを問題なく許可する)
  2. 同じinterface番号0のalternate setting 1を実際にはHID(0x03)クラスとして
     宣言し、そこにIN方向のendpointを1本持たせる
  3. ページはalternate setting 0のもとでinterface 0をclaimする(許可される)
  4. その後、selectAlternateInterface()すら呼ばずに、alternate setting 1が
     持つIN endpointへ向けてbulkTransferIn()を呼ぶだけで、実際にデータが
     読み出せてしまう(_endpoint_available_or_errorがalternate設定を
     区別せずendpointを見つけてしまうため)

このテストはこの手順を実際に実行し、「あるべき安全な振る舞い
(=保護対象クラスのendpointへの転送は拒否される)」をassertする。
現状のコードに対しては FAIL する -- これが今回の報告の中で最も深刻な
所見である。
"""
import json

from _fixtures import FakeConfiguration, FakeDevice, FakeEndpoint, FakeInterface, make_bridge


def _build_composite_device_with_hidden_hid_altsetting():
    """interface 0: altsetting 0 = vendor-specific(無害、claim許可対象)、
    altsetting 1 = HID(保護対象)で、altsetting 1側にIN endpoint 1(0x81)を
    持つ複合デバイスを組み立てる。"""
    benign_alt0 = FakeInterface(
        number=0, alt=0, iclass=0xFF, isub=0x00, iproto=0x00,
        endpoints=[FakeEndpoint(0x01, attributes=0x02)],  # bulk OUT, endpoint 1
    )
    hidden_hid_alt1 = FakeInterface(
        number=0, alt=1, iclass=0x03, isub=0x00, iproto=0x00,  # 0x03 = HID (保護対象クラス)
        endpoints=[FakeEndpoint(0x81, attributes=0x03)],  # interrupt IN, endpoint 1
    )
    cfg = FakeConfiguration(1, [benign_alt0, hidden_hid_alt1])
    return FakeDevice(0x2341, 0x8036, [cfg])


def test_claiming_benign_altsetting_does_not_expose_hid_altsetting_endpoints():
    """altsetting 0(無害)でclaimしただけで、selectAlternateInterface()を
    一度も呼ばずに、altsetting 1(HID)側のendpointへbulkTransferInできて
    しまわないことを確認する。"""
    dev = _build_composite_device_with_hidden_hid_altsetting()
    bridge = make_bridge([dev])
    # 既存テスト(test_frame_tracker_wired_isolates_handles_between_different_frame_origins等)
    # と同じ手法: このテストの対象はopenDevice以降の保護判定であって許可判定自体
    # ではないため、「このoriginはこのデバイスに既に許可を得ている」状況を
    # 単純に固定して模す(実際の許可フローはtest_bridge.py側で別途検証済み)。
    bridge._is_granted = lambda origin, vid, pid: True

    open_result = json.loads(bridge.openDevice(0x2341, 0x8036, ""))
    assert open_result["success"] is True, open_result
    handle = open_result["handle"]

    claim_result = json.loads(bridge.claimInterface(handle, 0, ""))
    assert claim_result["success"] is True, (
        "前提条件の確認: alternate setting 0はvendor-specific(0xFF)であり "
        "保護対象クラスではないため、claimInterface自体は許可されるはず"
    )

    # selectAlternateInterface() は一度も呼んでいない。つまりこの複合デバイスの
    # "選択中のalternate setting" は仕様上あくまでaltsetting 0のはずである。
    transfer_result = json.loads(bridge.bulkTransferIn(handle, 1, 4, ""))

    assert transfer_result.get("success") is not True, (
        "HID(保護対象インターフェースクラス)であるalternate setting 1が持つ"
        "endpointに対して、bulkTransferIn()がデータを返してしまった: "
        f"{transfer_result!r}。claimInterface()はalternate setting 0"
        "(vendor-specific)だけを見て許可したにもかかわらず、"
        "_endpoint_available_or_error()がalternate settingを区別せず"
        "endpointを探索するため、同じinterface番号を共有する保護対象クラスの"
        "endpointにまで到達できてしまっている。CVE-2018-6125"
        "(WebUSBがHID/セキュリティキーへのオリジンチェックを迂回して"
        "アクセスできた問題)と同種の、保護対象インターフェースクラス"
        "そのものへの回避策である。"
    )


def test_control_transfer_interface_recipient_also_bypassed_via_altsetting_confusion():
    """finding拡張: _control_transfer_validation_error()のrecipient=='interface'
    (bmRequestType下位2bit==1)経路とreq_kind=='class'(bit6-5==1)経路は、
    どちらもinterface_class_for()を直接の根拠にしている。したがって
    bulkTransferInと全く同じ理由で、altsetting 1(HID)を隠したまま
    altsetting 0(vendor-specific)でclaimしたinterface 0へ向けて、
    class種別のcontrolTransferOutが素通りしてしまうはずである。"""
    dev = _build_composite_device_with_hidden_hid_altsetting()
    bridge = make_bridge([dev])
    bridge._is_granted = lambda origin, vid, pid: True

    handle = json.loads(bridge.openDevice(0x2341, 0x8036, ""))["handle"]
    claim_result = json.loads(bridge.claimInterface(handle, 0, ""))
    assert claim_result["success"] is True, claim_result

    # bmRequestType = 0b0010_0001 = OUT, class, recipient=interface(index=0)
    request_type = 0x21
    result = json.loads(bridge.controlTransferOut(handle, request_type, 0x09, 0x0000, 0x0000, "", ""))

    assert result.get("success") is not True, (
        "interface 0 は現在HID(保護対象)のalternate settingを持ちうるにも"
        f"かかわらず、class種別・recipient=interfaceのcontrolTransferOutが"
        f"素通りしてしまった: {result!r}。_control_transfer_validation_error()の"
        "req_kind==1(class)・recipient==1(interface)経路がどちらも"
        "interface_class_for()(alternate setting非対応)だけを根拠にしている"
        "ため、bulkTransferInと同一の根本原因でこちらも回避可能である。"
    )


def test_control_transfer_endpoint_recipient_correctly_blocks_hidden_hid_endpoint():
    """対照実験(こちらは安全側の確認, PASSする想定): recipient=='endpoint'
    (bmRequestType下位2bit==2)経路だけは、指定endpointAddressを実際に
    含むInterfaceエントリ自身のbInterfaceClassをその場で読むため、
    (interface_class_for()を経由しないため)altsetting 1のendpointを
    正しくHIDと認識できる。同じファイル内に「刺さる経路」と「刺さらない
    経路」が両方あることを対比として明示するために置く。"""
    dev = _build_composite_device_with_hidden_hid_altsetting()
    bridge = make_bridge([dev])
    bridge._is_granted = lambda origin, vid, pid: True

    handle = json.loads(bridge.openDevice(0x2341, 0x8036, ""))["handle"]
    claim_result = json.loads(bridge.claimInterface(handle, 0, ""))
    assert claim_result["success"] is True, claim_result

    # bmRequestType = 0b1000_0010 = IN, standard相当ではなくvendor, recipient=endpoint
    # (0x82 = IN|vendor|endpoint) 、index=0x81(altsetting 1が持つHID側のIN endpoint)
    request_type = 0xC2
    result = json.loads(bridge.controlTransferIn(handle, request_type, 0x00, 0x0000, 0x0081, 4, ""))

    assert result.get("success") is not True, (
        f"recipient=endpoint経路まで素通りしてしまった(想定外): {result!r}"
    )


def test_interface_class_for_is_blind_to_alternate_settings():
    """根本原因をピンポイントで示す単体テスト: interface_class_for()に
    alternate settingを区別する手段が無いため、altsetting 0(無害)と
    altsetting 1(HID)を持つinterface 0について、常にaltsetting 0の
    クラスだけが返ってしまう(=altsetting 1がHIDであるという事実が
    一切見えない)ことを確認する。"""
    from pyside6_webusb.hardening import interface_class_for

    dev = _build_composite_device_with_hidden_hid_altsetting()
    reported_class = interface_class_for(dev, 0)

    assert reported_class == 0x03, (
        f"interface_class_for(dev, 0) は {reported_class:#x} を返した"
        "(alternate setting 0のvendor-specificクラス0xFF)。本来この"
        "デバイスのinterface番号0は、alternate settingによって0xFF(無害)にも"
        "0x03=HID(保護対象)にもなり得るにもかかわらず、この関数は"
        "alternate settingという概念自体を受け取らないため、後者の存在を"
        "一切検出できない。claimInterface()・_control_transfer_validation_error()の"
        "双方がこの関数だけを根拠に保護判定しており、endpoint単位の実体を"
        "見ていない。"
    )
