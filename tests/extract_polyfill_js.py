# -*- coding: utf-8 -*-
"""tests/test_polyfill.js が読み込む素の .js ファイルと、Python側ブリッジの
スロット署名表(JSON)を書き出す。

Node.js側からPythonの文字列定数を直接importすることはできないため、テスト実行前に
このスクリプトで一度書き出す。

    python tests/extract_polyfill_js.py && node tests/test_polyfill.js

書き出すもの:
  _polyfill_extracted.js   既定設定のポリフィル(WEBUSB_POLYFILL_JS)
  _bridge_signatures.json  WebUSBBridgeの公開スロット {名前: [{"params": [型...], "returns": "型"}, ...]}
                           (オーバーロードごとに1要素。QWebChannelはJS側の引数の個数で選ぶ)
                           (JS→Pythonの引数の並び・個数が食い違っていないかをNode側の
                            フェイクブリッジが機械的に検証するための「契約」)
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from pyside6_webusb.polyfill import WEBUSB_POLYFILL_JS


def bridge_signatures():
    from PySide6.QtCore import QMetaMethod
    from pyside6_webusb.bridge import WebUSBBridge
    mo = WebUSBBridge.staticMetaObject
    table = {}
    for i in range(mo.methodOffset(), mo.methodCount()):
        m = mo.method(i)
        if m.methodType() != QMetaMethod.MethodType.Slot or m.access() != QMetaMethod.Access.Public:
            continue
        sig = bytes(m.methodSignature()).decode("ascii")
        name, _, rest = sig.partition("(")
        params = [p.strip() for p in rest.rstrip(")").split(",") if p.strip()]
        tn = m.typeName()
        tn = tn.decode("ascii") if isinstance(tn, (bytes, bytearray)) else str(tn)
        table.setdefault(name, []).append({"params": params, "returns": tn or "void"})
    return table


def main():
    js_path = os.path.join(HERE, "_polyfill_extracted.js")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(WEBUSB_POLYFILL_JS)
    print("wrote %d bytes to %s" % (len(WEBUSB_POLYFILL_JS), js_path))
    sig_path = os.path.join(HERE, "_bridge_signatures.json")
    table = bridge_signatures()
    with open(sig_path, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=1, sort_keys=True)
    print("wrote %d slot signatures to %s" % (len(table), sig_path))


if __name__ == "__main__":
    main()
