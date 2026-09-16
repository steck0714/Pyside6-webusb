# -*- coding: utf-8 -*-
"""脅威モデル: 「素のQWebChannel接続を自前で開き、polyfill.py(navigator.usb)を
経由せずWebUSBBridgeの@Slotを直接叩く敵対的スクリプト」。

これはこのプロジェクト自身がCHANGELOG(v0.0.4b2, Security)で明記している
既知の脅威モデルであり、実際に3つの管理系メソッド(listKnownDevices等)を
@Slotから外す形で一度対処されている:
    「install()はポリフィルをMainWorldへ注入する -- ページ自身のスクリプトが
    動くのと同じJS実行コンテキストであり、これによって初めてページから
    navigator.usbが見える。つまりbridgeオブジェクト上のどの@Slotも、
    polyfill.py自身のJSが実際にそれを呼んでいるかどうかに関わらず、
    独自にQWebChannel接続を開いた任意のページから到達可能である。」

このファイルは、その脅威モデルを requestDeviceChooser() 自体(=対処当時
@Slotのままにせざるを得なかった、まさにその入口)に対して当てはめ、
polyfill.pyのJS側だけで行われているチェック(ユーザー操作要求・
filtersの構造検証)が、Python側で独立して再検証されていないことを
実際に動かして確認する。

このファイルのテストは「あるべき安全な振る舞い」を assert する形で書いて
ある。現状のコードに対しては FAIL する(=これが今回報告する脆弱性その
ものであることを示す)。bridge.py側に対応する検証を追加すれば、コードを
変更することなくこれらのテストは PASS に変わる設計にしてある。
"""
import inspect
import json
import os

import pytest

from pyside6_webusb.bridge import WebUSBBridge
from _fixtures import FakeChooserDialog, FakeConfiguration, FakeDevice, make_bridge

_BRIDGE_SRC_PATH = os.path.join(os.path.dirname(__file__), "..", "src", "pyside6_webusb", "bridge.py")
with open(_BRIDGE_SRC_PATH, "r", encoding="utf-8") as _f:
    _BRIDGE_SOURCE = _f.read()


def test_requestDeviceChooser_signature_has_no_gesture_evidence_parameter():
    """navigator.usb.requestDevice()の『ユーザー操作(user gesture)が必要』という
    要件(README記載のセキュリティモデルの一部)を、Pythonのbridge層が原理的に
    検証できるようになっているか。requestDeviceChooser()のシグネチャに、呼び出しが
    本物のユーザー操作から来たことを示す情報(トークン/フラグ等)を渡す引数が
    無ければ、Python側では検証しようがない=検証は行われていないことになる。"""
    sig = inspect.signature(WebUSBBridge.requestDeviceChooser)
    param_names = set(sig.parameters.keys())
    gesture_related = {p for p in param_names if "gesture" in p.lower() or "activation" in p.lower() or "trusted" in p.lower()}
    assert gesture_related, (
        "requestDeviceChooser(self, options_json, frame_token='') にはユーザー操作の"
        "証跡を受け取る引数が存在しない(実際のシグネチャ: {})。"
        "navigator.userActivation.isActive の確認はpolyfill.py のJS側だけで"
        "行われており(該当箇所: 'Must be handling a user gesture to call "
        "navigator.usb.requestDevice()')、素のQWebChannel接続からこのSlotを"
        "直接呼ぶ敵対的スクリプトに対しては何の効力も持たない。".format(sig)
    )


def test_requestDeviceChooser_opens_chooser_without_any_gesture_evidence(monkeypatch):
    """百聞は一見に如かず: 実際にrequestDeviceChooser()を『ユーザー操作を一切示せない
    直接呼び出し』としてコールし、それでもチューザーダイアログの構築まで到達して
    しまう(=呼び出しが拒否されない)ことを確認する。"""
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.instantiated_count = 0
    FakeChooserDialog.SELECT_INDEX = 0

    # navigator.usb.requestDevice() のJSラッパーを一切経由せず、素のQWebChannel
    # スロットを直接叩く敵対的スクリプトを模した呼び出し。「ユーザー操作の証跡」を
    # 渡す方法自体が存在しない(前のテストで確認済み)。
    result = json.loads(bridge.requestDeviceChooser(json.dumps({"filters": [{}]})))

    assert FakeChooserDialog.instantiated_count == 0, (
        "本来であれば、ユーザー操作を伴わない直接呼び出しはSecurityError相当で"
        "サーバー側(Python)で拒否され、ネイティブのUSBデバイス選択ダイアログは"
        "一度も構築されないべきである。しかし実際には毎回ダイアログが構築されて"
        "しまっている(instantiated_count={}回)。この結果、敵対的スクリプトは"
        "任意のタイミング(例: ページ読み込み直後、他の操作に紛れさせて等)で"
        "ネイティブダイアログをポップアップさせることができ、"
        "『本物のクリックからしか呼べない』というREADME記載のセキュリティ特性を"
        "実質的に無効化できる(ダイアログの意図しない表示によるソーシャル"
        "エンジニアリング・スプーフィングの一種。CVE-2020-16033"
        "『WebUSBにおけるセキュリティUIのスプーフィングを許す不適切な実装』と"
        "同系統のリスク)。".format(FakeChooserDialog.instantiated_count)
    )


def test_spec_invalid_filter_missing_vendorid_is_rejected_serverside():
    """WebUSB仕様上、productIdだけを指定しvendorIdを伴わないfilterはTypeErrorに
    なるべき『無効なfilter』である(polyfill.py内のisValidUsbDeviceFilter相当の
    JSチェックが対象とするケース)。hardening.pyにはPython版の
    is_valid_usb_device_filter()が実装されているにもかかわらず、bridge.pyからは
    一度もimport/呼び出しされていない(=Python側では検証されない)ことを、
    ソースコードそのものから確認する。"""
    assert "is_valid_usb_device_filter" in _BRIDGE_SOURCE, (
        "hardening.is_valid_usb_device_filter() はbridge.py側で一度も参照されて"
        "いない。つまり『vendorId無しのproductId指定はTypeError』という仕様上の"
        "構造検証は、polyfill.pyのJS側だけで行われている。素のQWebChannel接続"
        "経由でrequestDeviceChooserを直接叩けば、この検証は素通りする。"
    )


def test_malformed_filter_does_not_silently_widen_the_candidate_list(monkeypatch):
    """↑の構造検証欠如を実際の挙動として確認する: vendorId無し・productIdのみの
    filter(仕様上はTypeErrorになるべき無効なfilter)を直接送ると、
    本来ベンダーが異なる(=正規のfilterでは絶対に一致し得ない)2台の候補が
    どちらも一覧に混ざってしまう。"""
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    dev_b = FakeDevice(0x9999, 0x8036, [FakeConfiguration(1, [])])  # 別ベンダーだが同じproductId
    bridge = make_bridge([dev_a, dev_b])
    monkeypatch.setattr("pyside6_webusb.bridge.WebUsbDeviceChooserDialog", FakeChooserDialog)
    FakeChooserDialog.SELECT_INDEX = None  # 一覧の中身だけ見る(選択はしない)

    bridge.requestDeviceChooser(json.dumps({"filters": [{"productId": 0x8036}]}))

    candidate_count = len(FakeChooserDialog.last_devices_info or [])
    assert candidate_count < 2, (
        "vendorId無しのproductId指定filter(仕様上は構造的に無効)が、本来"
        f"ベンダーが異なる2台を両方とも候補にしてしまっている(候補数: "
        f"{candidate_count})。is_valid_usb_device_filter()による構造検証が"
        "サーバー側で行われていれば、この無効なfilterはそもそも候補ゼロ"
        "(filters: [] と同様の『一致するものなし』)になるはずである。"
    )


# --- 全@Slotへの敵対的引数フラッディング ---
# tests/test_bridge.py の test_requestDeviceChooser_is_registered_as_qt_slot と
# 同じQMetaMethod手法で、実際にQWebChannel経由でJSから到達可能な@Slot一覧を
# 動的に洗い出す。「JSの正規呼び出し(=polyfill.pyが送るはずの型)」を前提に
# せず、素のQWebChannel接続から送られうる極端な値(負数・巨大整数)を直接
# ぶつけて、bridge.pyのクラスdocstringが謳う『例外は絶対にJSへ漏らさず、
# 常に妥当なJSON文字列を返す』という設計不変条件が実際に保たれているかを検証する。
NUMERIC_ADVERSARIAL_VALUES = [-1, 0, 2**31, 2**53, 2**63, -(2**31)]

HANDLE_CONSUMING_METHODS_AND_ARGS = {
    # method_name: 位置引数の個数(frame_tokenより前)
    "closeDevice": 1,
    "claimInterface": 2,
    "releaseInterface": 2,
    "selectConfiguration": 2,
    "selectAlternateInterface": 3,
    "resetDevice": 1,
    "clearHalt": 3,
    "bulkTransferIn": 3,
    "bulkTransferOut": 3,
    "controlTransferIn": 6,
    "controlTransferOut": 6,
}


def _reachable_slot_names():
    from PySide6.QtCore import QMetaMethod
    mo = WebUSBBridge.staticMetaObject
    return {
        bytes(mo.method(i).methodSignature()).decode().split("(", 1)[0]
        for i in range(mo.methodCount())
        if mo.method(i).methodType() == QMetaMethod.MethodType.Slot
    }


def test_all_handle_consuming_methods_are_actually_reachable_via_qwebchannel():
    """このファイルの他のテストが対象にしている全メソッドが、本当に
    QWebChannel経由でJSから到達可能な@Slotであることを先に確認しておく
    (=フェイクを叩いているだけで実際の攻撃面を取り違えていないことの保証)。"""
    reachable = _reachable_slot_names()
    missing = [m for m in HANDLE_CONSUMING_METHODS_AND_ARGS if m not in reachable]
    assert not missing, f"以下は@Slotとして到達不能(想定外、テスト対象の見直しが必要): {missing}"


@pytest.mark.parametrize("method_name", sorted(HANDLE_CONSUMING_METHODS_AND_ARGS.keys()))
@pytest.mark.parametrize("adversarial_value", NUMERIC_ADVERSARIAL_VALUES)
def test_handle_consuming_slots_never_raise_on_adversarial_numeric_args(method_name, adversarial_value):
    """正規のJS(polyfill.py)なら絶対に送らない極端な数値(負数・2**63等)を
    素のQWebChannel直叩きとして送っても、Pythonの未捕捉例外としてプロセスへ
    漏れることなく、常に文字列(JSON)を返すという設計不変条件を検証する。"""
    dev_a = FakeDevice(0x2341, 0x8036, [FakeConfiguration(1, [])])
    bridge = make_bridge([dev_a])
    method = getattr(bridge, method_name)
    n_args = HANDLE_CONSUMING_METHODS_AND_ARGS[method_name]
    args = [adversarial_value] * n_args
    try:
        result = method(*args, "")
    except Exception as e:  # pragma: no cover - このexceptに来ること自体が不具合
        pytest.fail(
            f"{method_name}({args!r}, '') が未捕捉の {type(e).__name__} を送出した: {e!r}。"
            "bridge.pyのクラスdocstringが謳う『例外は絶対にJSへ漏らさない』という"
            "設計不変条件に反する(JS側から見るとQWebChannel呼び出しが失敗扱いに"
            "なりうる=フェイルセーフ設計の破れ)。"
        )
    assert isinstance(result, str)
    parsed = json.loads(result)  # 妥当なJSONであること自体も確認
    assert isinstance(parsed, dict)
