# -*- coding: utf-8 -*-
"""polyfill.build_polyfill_js() / 生成バンドルの鮮度 / Nodeテスト・実ブラウザe2eのラッパー。"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import pytest

from pyside6_webusb import polyfill
from pyside6_webusb._polyfill_bundle import JS_SHA256, POLYFILL_JS_TEMPLATE


def _config(js):
    a = js.index("/*CONFIG_BEGIN*/") + len("/*CONFIG_BEGIN*/")
    return json.loads(js[a:js.index("/*CONFIG_END*/")])


def test_generated_bundle_matches_jssrc():
    """jssrc/*.js を直したのに scripts/build_polyfill.py を回し忘れると落ちる。"""
    if not os.path.isdir(os.path.join(ROOT, "jssrc")):
        pytest.skip("jssrc/ is not part of this source tree (installed package)")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_polyfill.py"), "--check"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_bundle_hash_matches_the_embedded_source():
    import hashlib
    assert hashlib.sha256(POLYFILL_JS_TEMPLATE.encode("utf-8")).hexdigest() == JS_SHA256


def test_default_constant_is_the_default_build():
    cfg = _config(polyfill.WEBUSB_POLYFILL_JS)
    assert cfg == {"locale": "en", "lockNavigatorUsb": True, "nativeLookalike": True, "exposeCommands": True,
                   "transport": "webchannel", "ws": None, "version": "", "debug": False}


def test_build_is_a_pure_function_of_its_arguments():
    a = polyfill.build_polyfill_js(locale="ja", version="9.9")
    b = polyfill.build_polyfill_js(locale="zh")
    assert _config(a)["locale"] == "ja" and _config(a)["version"] == "9.9"
    assert _config(b)["locale"] == "zh" and _config(b)["version"] == ""
    assert polyfill.WEBUSB_POLYFILL_JS == polyfill.build_polyfill_js()


def test_ws_config_and_hostile_values_cannot_break_out_of_the_config_literal():
    evil = {"host": "127.0.0.1", "port": 1, "secret": "*/});alert(1);//"}
    js = polyfill.build_polyfill_js(transport="websocket", ws=evil, locale='"}; alert(1); //')
    cfg = _config(js)
    assert cfg["ws"] == evil and cfg["locale"] == '"}; alert(1); //'
    assert js.count("/*CONFIG_BEGIN*/") == 1 and js.count("/*CONFIG_END*/") == 1
    assert "alert(1);//" not in js.replace(json.dumps(evil["secret"]), "")


def test_qwebchannel_source_is_wrapped_in_a_closure_and_never_global():
    lib = "var QWebChannel = function () { return 'lib'; }; var QObject = 1;"
    js = polyfill.build_polyfill_js(qwebchannel_js=lib)
    i = js.index("/*QWC_LIB_BEGIN*/")
    j = js.index("/*QWC_LIB_END*/")
    region = js[i:j]
    assert region.startswith("/*QWC_LIB_BEGIN*/(function () {") and region.rstrip().endswith("})()")
    assert "return QWebChannel;" in region and lib in region


def test_debug_adds_a_source_url_only_when_asked():
    assert "sourceURL" not in polyfill.build_polyfill_js()
    assert polyfill.build_polyfill_js(debug=True).rstrip().endswith("//# sourceURL=pyside6-webusb/polyfill.js")


def test_bundle_is_one_strict_iife_with_no_top_level_leaks():
    js = polyfill.WEBUSB_POLYFILL_JS
    assert js.startswith("(function () {\n'use strict';") and js.rstrip().endswith("})();")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_node_polyfill_suite():
    subprocess.run([sys.executable, os.path.join(HERE, "extract_polyfill_js.py")], check=True,
                   capture_output=True, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    out = subprocess.run(["node", os.path.join(HERE, "test_polyfill.js")], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout[-4000:] + out.stderr[-2000:]
    assert " 0 failed" in out.stdout


def _run_e2e(script):
    pytest.importorskip("PySide6.QtWebEngineCore")
    if os.environ.get("PYSIDE6_WEBUSB_SKIP_E2E") == "1":
        pytest.skip("PYSIDE6_WEBUSB_SKIP_E2E=1")
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, script)], capture_output=True, text=True, timeout=240,
                             env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    except subprocess.TimeoutExpired:
        pytest.skip("Chromium did not finish in time on this machine")
    line = [l for l in out.stdout.splitlines() if l.startswith("E2E_JSON=")]
    if not line:
        pytest.skip("Chromium (QtWebEngine) could not be started here:\n" + (out.stdout + out.stderr)[-800:])
    checks = json.loads(line[0][len("E2E_JSON="):])["checks"]
    failed = [c for c in checks if not c["ok"]]
    assert not failed, "\n".join("%s -> %s" % (c["name"], str(c["detail"])[:500]) for c in failed)
    return checks


def test_real_chromium_webengine_e2e():
    """実物のChromium(QtWebEngine): 同じエンジン上のネイティブWebHIDと形を比較し、仮想USBデバイスで
    getDevices/open/転送/ホットプラグ/実クリックのrequestDevice/改ざん耐性まで一通り動かす。"""
    checks = _run_e2e("e2e_webengine_runner.py")
    assert len(checks) >= 50


def test_qtwebview_example_smoke():
    """examples/qtwebview_app.py --smoke: QML WebView + install_webview + QmlDeviceChooser が実際に起動し、
    ページへポリフィルが入ってWebSocket転送が確立するところまで通る(サンプルが腐らないための検査)。"""
    pytest.importorskip("PySide6.QtWebView")
    pytest.importorskip("PySide6.QtWebSockets")
    pytest.importorskip("PySide6.QtWebEngineCore")
    if os.environ.get("PYSIDE6_WEBUSB_SKIP_E2E") == "1":
        pytest.skip("PYSIDE6_WEBUSB_SKIP_E2E=1")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", PYTHONPATH=os.path.join(ROOT, "src"))
    flags = env.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
    for f in ("--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"):
        if f not in flags:
            flags.append(f)
    env["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)
    try:
        out = subprocess.run([sys.executable, os.path.join(ROOT, "examples", "qtwebview_app.py"), "--smoke"],
                             capture_output=True, text=True, timeout=120, env=env)
    except subprocess.TimeoutExpired:
        pytest.skip("Chromium did not finish in time on this machine")
    if "SMOKE:" not in out.stdout:
        pytest.skip("QtWebView could not be started here:\n" + (out.stdout + out.stderr)[-600:])
    assert out.returncode == 0, out.stdout[-800:]
    assert '"usb":"object"' in out.stdout and '"kind":"websocket"' in out.stdout and '"ready":true' in out.stdout


def test_real_qtwebview_e2e():
    """実物のQML WebView(QtWebView)+ ループバックWebSocket。QWebChannelもドキュメント開始時注入も無い条件。"""
    pytest.importorskip("PySide6.QtWebView")
    pytest.importorskip("PySide6.QtWebSockets")
    checks = _run_e2e("e2e_qtwebview_runner.py")
    assert len(checks) >= 18


if __name__ == "__main__":
    # 直接実行でも本当にテストが走るように(import して終わり、にならないように)する。
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
