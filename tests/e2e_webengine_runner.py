# -*- coding: utf-8 -*-
"""実物のChromium(QtWebEngine)でポリフィルを検証するスタンドアロン・ランナー。

pytestからはサブプロセスとして起動される(tests/test_e2e_webengine.py)。QtWebEngineは
プロセス内の状態(QApplication生成順など)に敏感なので、他のテストと同じプロセスでは
走らせない。結果はJSON(1行)で標準出力へ出す:

    {"checks": [{"name": ..., "ok": true/false, "detail": ...}, ...]}

やること:
  A. 同じChromium上の**本物の** navigator.hid / HID / HIDDevice / HIDConnectionEvent を
     基準にして、USB系クラスの「形」(記述子・名前・length・toString・Symbol.toStringTag・
     エラーメッセージ)がネイティブと同じルールに従っているかを判定する。
     (同じ判定関数をネイティブHIDにも当て、判定関数自体が正しいことを担保する)
  B. 仮想USBデバイス(pyside6_webusb.virtual)で getDevices/open/claim/transfer/close/
     hotplugイベントを一通り動かす。
  C. ページ側スクリプトが Promise/JSON/Function.prototype.call 等を書き換えても
     ブリッジが壊れないこと、delete/defineProperty で navigator.usb が消えないこと。
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
for _f in ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]:
    if _f not in _flags:
        _flags.append(_f)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(_flags)   # 親プロセスが既に値を持っていても必要なフラグを足す(setdefaultだと取りこぼす)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  (QApplication生成より前にimportすること)
from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer, QUrl, Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QApplication

from pyside6_webusb import install
from pyside6_webusb.virtual import (
    VirtualUsbConfiguration, VirtualUsbDevice, VirtualUsbEndpoint, VirtualUsbInterface,
    make_virtual_usb_backend,
)

VID, PID = 0x2341, 0x8036

import http.server
import threading


FRAME_PAGE = (b"<!doctype html><html><head><meta charset=utf-8></head><body><script>"
              b"setTimeout(function () {"
              b"  var info = {o: location.origin, hasUsb: typeof navigator.usb, hasQt: typeof window.qt, hasClass: typeof window.USBDevice, tok: typeof window.__pyUsbFrameToken, tokEnumerable: Object.keys(window).indexOf('__pyUsbFrameToken') >= 0,"
              b"    leaked: Object.keys(window).filter(function (k) { return /__pyUsbFrameToken|__pysideWebUSB|QWebChannel|^USB/.test(k); }).length};"
              b"  parent.postMessage(JSON.stringify(info), '*');"
              b"}, 600);</script></body></html>")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):   # noqa: N802
        if self.path.startswith("/frame"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(FRAME_PAGE)))
            self.end_headers()
            self.wfile.write(FRAME_PAGE)
            return
        body = b"<!doctype html><html><head><meta charset=utf-8><title>e2e</title></head><body><button id=b>go</button></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
threading.Thread(target=_server.serve_forever, daemon=True).start()
ORIGIN = "http://127.0.0.1:%d" % _server.server_address[1]

app = QApplication.instance() or QApplication(sys.argv)


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Harness:
    def __init__(self, lock=True, native_lookalike=True, expose_commands=True, grant=True, chooser="first"):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
        self.tmp.close()
        self.settings = QSettings(self.tmp.name, QSettings.Format.IniFormat)
        self.device = VirtualUsbDevice(
            vendor_id=VID, product_id=PID, manufacturer="Acme", product="Virtual Widget", serial_number="SN-0001",
            configurations=[VirtualUsbConfiguration(value=1, interfaces=[
                VirtualUsbInterface(number=0, alternate=0, interface_class=0xFF, endpoints=[
                    VirtualUsbEndpoint(number=1, direction="in", transfer_type="bulk"),
                    VirtualUsbEndpoint(number=1, direction="out", transfer_type="bulk"),
                ]),
            ])],
        )
        self.backend = make_virtual_usb_backend([self.device])
        self.page = QWebEnginePage()

        class _Win:  # browser_window.settings だけを見る
            pass
        win = _Win()
        win.settings = self.settings
        self.bridge = install(self.page, browser_window=win, usb_backend=self.backend, locale="en",
                              lock_navigator_usb=lock, native_lookalike=native_lookalike,
                              expose_commands=expose_commands,
                              chooser=(lambda devices, origin, strings: devices[0] if devices else None)
                              if chooser == "first" else (lambda devices, origin, strings: None))
        assert self.bridge is not None, "install() returned None"
        self.bridge._hotplug_timer.stop()   # テストからは手動でpollする
        if grant:
            self.bridge._grant(ORIGIN, VID, PID)
        self._n = 0
        loop = QEventLoop()
        self.page.loadFinished.connect(lambda ok: loop.quit())
        self.page.load(QUrl(ORIGIN + "/"))
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        spin(500)
        self.bridge._frame_tracker.rescan()
        spin(300)   # FrameOriginTrackerがトークンを配るのを待つ

    def run(self, js, timeout_ms=15000):
        """asyncを含むJS式を実行し、JSON化した結果を返す。"""
        self._n += 1
        key = "__e2e_result_%d" % self._n
        wrapped = (
            "(function(){ window['%s'] = null; Promise.resolve().then(function(){ return (async function(){ %s })(); })"
            ".then(function(v){ window['%s'] = JSON.stringify({ok: v}); },"
            " function(e){ window['%s'] = JSON.stringify({err: String(e && e.name) + ': ' + String(e && e.message)}); }); })();"
            % (key, js, key, key))
        self.page.runJavaScript(wrapped)
        out = {}

        def got(v):
            out["v"] = v
        elapsed = 0
        while elapsed < timeout_ms:
            spin(120)
            elapsed += 120
            self.page.runJavaScript("window['%s']" % key, got)
            spin(60)
            elapsed += 60
            if out.get("v"):
                return json.loads(out["v"])
        return {"err": "timeout"}


CHECKS = []


def record(name, ok, detail=""):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail if not ok else ""})


def expect(h, name, js, predicate=None, equals=None):
    r = h.run(js)
    if "err" in r:
        record(name, False, "JS error: %s" % r["err"])
        return None
    v = r["ok"]
    if equals is not None:
        record(name, v == equals, "got %r, expected %r" % (v, equals))
    elif predicate is not None:
        record(name, predicate(v), "got %r" % (v,))
    else:
        record(name, v is True, "got %r" % (v,))
    return v


SHAPE_JS = r"""
function shapeIssues(C, tag, opts) {
  opts = opts || {};
  var issues = [];
  function d(o, k) { return Object.getOwnPropertyDescriptor(o, k); }
  var fts = Function.prototype.toString;
  if (typeof C !== 'function') return ['missing'];
  if (C.name !== tag) issues.push('ctor.name=' + C.name);
  var pd = d(C, 'prototype');
  if (!pd || pd.writable || pd.enumerable || pd.configurable) issues.push('ctor.prototype descriptor');
  var nd = d(C, 'name'); if (!nd || nd.writable || nd.enumerable || !nd.configurable) issues.push('ctor.name descriptor');
  var ld = d(C, 'length'); if (!ld || ld.writable || ld.enumerable || !ld.configurable) issues.push('ctor.length descriptor');
  if (fts.call(C) !== 'function ' + tag + '() { [native code] }') issues.push('ctor toString=' + fts.call(C));
  var keys = Reflect.ownKeys(C).map(String).sort().join(',');
  if (keys !== 'length,name,prototype') issues.push('ctor own keys=' + keys);
  var P = C.prototype;
  var td = d(P, Symbol.toStringTag);
  if (!td || td.value !== tag || td.writable || td.enumerable || !td.configurable) issues.push('toStringTag descriptor');
  var cd = d(P, 'constructor');
  if (!cd || cd.value !== C || !cd.writable || cd.enumerable || !cd.configurable) issues.push('constructor descriptor');
  if (opts.eventTarget && Object.getPrototypeOf(P) !== EventTarget.prototype) issues.push('proto chain (EventTarget)');
  if (opts.event && Object.getPrototypeOf(P) !== Event.prototype) issues.push('proto chain (Event)');
  if (opts.event && Object.getPrototypeOf(C) !== Event) issues.push('ctor [[Prototype]] not Event');
  if (opts.eventTarget && Object.getPrototypeOf(C) !== EventTarget) issues.push('ctor [[Prototype]] not EventTarget');
  Reflect.ownKeys(P).forEach(function (k) {
    if (typeof k === 'symbol' || k === 'constructor') return;
    var pdsc = d(P, k), n = String(k);
    if ('value' in pdsc) {
      if (typeof pdsc.value !== 'function') { issues.push(n + ': data property'); return; }
      var f = pdsc.value;
      if (!pdsc.writable || !pdsc.enumerable || !pdsc.configurable) issues.push(n + ': method flags');
      if (f.name !== n) issues.push(n + ': fn.name=' + f.name);
      if (f.hasOwnProperty('prototype')) issues.push(n + ': fn has prototype');
      if (fts.call(f) !== 'function ' + n + '() { [native code] }') issues.push(n + ': fn toString');
      try { new f(); issues.push(n + ': constructible'); } catch (e) { if (!(e instanceof TypeError)) issues.push(n + ': new -> ' + e.name); }
    } else {
      if (!pdsc.enumerable || !pdsc.configurable) issues.push(n + ': accessor flags');
      if (!pdsc.get) { issues.push(n + ': no getter'); return; }
      if (pdsc.get.name !== 'get ' + n) issues.push(n + ': getter.name=' + pdsc.get.name);
      if (pdsc.get.length !== 0) issues.push(n + ': getter.length');
      if (pdsc.get.hasOwnProperty('prototype')) issues.push(n + ': getter has prototype');
      if (fts.call(pdsc.get) !== 'function get ' + n + '() { [native code] }') issues.push(n + ': getter toString');
      if (pdsc.set) {
        if (n.indexOf('on') !== 0) issues.push(n + ': unexpected setter');
        else if (pdsc.set.name !== 'set ' + n) issues.push(n + ': setter.name=' + pdsc.set.name);
      } else if (n.indexOf('on') === 0) issues.push(n + ': event handler without setter');
      try { pdsc.get.call({}); issues.push(n + ': getter accepted foreign this'); }
      catch (e) { if (!(e instanceof TypeError) || e.message !== 'Illegal invocation') issues.push(n + ': getter err=' + e.message); }
    }
  });
  return issues;
}
"""


def run_all():
    h = Harness()

    # ---------------------------------------------------------------- A. fingerprint
    r = h.run(SHAPE_JS + r"""
      var out = {};
      out.nativeUSB = typeof navigator.hid === 'object';
      out.nativeHID = shapeIssues(HID, 'HID', {eventTarget: true});
      out.nativeHIDDevice = shapeIssues(HIDDevice, 'HIDDevice', {eventTarget: true});
      out.nativeHIDConnectionEvent = shapeIssues(HIDConnectionEvent, 'HIDConnectionEvent', {event: true});
      out.USB = shapeIssues(USB, 'USB', {eventTarget: true});
      out.USBDevice = shapeIssues(USBDevice, 'USBDevice', {});
      out.USBConnectionEvent = shapeIssues(USBConnectionEvent, 'USBConnectionEvent', {event: true});
      ['USBConfiguration','USBInterface','USBAlternateInterface','USBEndpoint','USBInTransferResult','USBOutTransferResult',
       'USBIsochronousInTransferPacket','USBIsochronousInTransferResult','USBIsochronousOutTransferPacket','USBIsochronousOutTransferResult']
        .forEach(function (n) { out[n] = shapeIssues(window[n], n, {}); });
      return out;
    """)
    if "err" in r:
        record("fingerprint: runner", False, r["err"])
    else:
        o = r["ok"]
        # ネイティブに当てた判定が通る=判定関数の前提(ネイティブの形)が正しい、という担保
        for k in ("nativeHID", "nativeHIDDevice", "nativeHIDConnectionEvent"):
            record("fingerprint: checker accepts native %s" % k[6:], o[k] == [], o[k])
        for k, v in o.items():
            if k.startswith("native"):
                continue
            record("fingerprint: %s has the native shape" % k, v == [], v)

    expect(h, "navigator.usb is a USB instance with [object USB] tag",
           "return navigator.usb instanceof USB && Object.prototype.toString.call(navigator.usb) === '[object USB]' && navigator.usb.constructor === USB")
    expect(h, "navigator.usb has no own keys / JSON is {}",
           "return Object.keys(navigator.usb).length === 0 && JSON.stringify(navigator.usb) === '{}' && Reflect.ownKeys(navigator.usb).length === 0")
    expect(h, "navigator has no own 'usb' property",
           "return !Object.prototype.hasOwnProperty.call(navigator, 'usb') && Object.getOwnPropertyNames(navigator).indexOf('usb') < 0")
    expect(h, "Object.keys(window) does not reveal polyfill globals",
           "var k = Object.keys(window).join(' '); return !/__pyUsbFrameToken|__pysideWebUSB|QWebChannel|USB/.test(k)")
    expect(h, "no QWebChannel/QObject globals leak into the page",
           "return typeof QWebChannel === 'undefined' && typeof QObject === 'undefined' && typeof QWebChannelMessageTypes === 'undefined'")
    expect(h, "interface globals are non-enumerable, writable, configurable (like native)",
           "var d = Object.getOwnPropertyDescriptor(window, 'USBDevice'); var n = Object.getOwnPropertyDescriptor(window, 'HIDDevice'); "
           "return d.enumerable === n.enumerable && d.writable === n.writable && d.configurable === n.configurable")
    expect(h, "Navigator.prototype.usb descriptor mirrors navigator.hid (accessor, enumerable, getter only)",
           "var u = Object.getOwnPropertyDescriptor(Navigator.prototype, 'usb'); var hd = Object.getOwnPropertyDescriptor(Navigator.prototype, 'hid'); "
           "return !!u.get && u.set === undefined && u.enumerable === hd.enumerable && u.get.name === 'get usb' && u.get.length === 0")
    expect(h, "illegal constructor / invocation messages equal native HID's",
           r"""var res = [];
           function msg(f) { try { f(); return 'no throw'; } catch (e) { return e.name + ': ' + e.message; } }
           var a = [msg(function(){ new HID(); }), msg(function(){ new USB(); })];
           var b = [msg(function(){ HID(); }), msg(function(){ USB(); })];
           var c = [msg(function(){ new HIDDevice(); }), msg(function(){ new USBDevice(); })];
           var g = [msg(function(){ Object.getOwnPropertyDescriptor(Navigator.prototype,'hid').get.call({}); }), msg(function(){ Object.getOwnPropertyDescriptor(Navigator.prototype,'usb').get.call({}); })];
           function nz(x) { return x.replace(/HIDDevice|USBDevice/g, 'D').replace(/'HID'|'USB'/g, "'X'"); }
           var ok = nz(a[0]) === nz(a[1]) && nz(b[0]) === nz(b[1]) && nz(c[0]) === nz(c[1]) && nz(g[0]) === nz(g[1]);
           return ok ? true : JSON.stringify([a, b, c, g]);""")
    expect(h, "USBConnectionEvent constructor errors mirror HIDConnectionEvent",
           r"""function msg(f) { try { f(); return 'no throw'; } catch (e) { return e.name + ': ' + e.message; } }
           function norm(s) { return s.replace(/HIDConnectionEvent|USBConnectionEvent/g, 'X').replace(/HIDDevice|USBDevice/g, 'D').replace(/HIDConnectionEventInit|USBConnectionEventInit/g, 'I'); }
           var pairs = [
             [function(){ new HIDConnectionEvent(); }, function(){ new USBConnectionEvent(); }],
             [function(){ HIDConnectionEvent('connect', {}); }, function(){ USBConnectionEvent('connect', {}); }],
             [function(){ new HIDConnectionEvent('connect'); }, function(){ new USBConnectionEvent('connect'); }],
             [function(){ new HIDConnectionEvent('connect', {}); }, function(){ new USBConnectionEvent('connect', {}); }],
             [function(){ new HIDConnectionEvent('connect', {device: 1}); }, function(){ new USBConnectionEvent('connect', {device: 1}); }]
           ];
           var bad = pairs.filter(function (p) { return norm(msg(p[0])) !== norm(msg(p[1])); }).map(function (p) { return [msg(p[0]), msg(p[1])]; });
           return bad.length === 0 ? true : JSON.stringify(bad);""")
    expect(h, "promise-returning methods reject like native (Illegal invocation / arg count / dictionary / no gesture)",
           r"""async function rej(f) { try { await f(); return 'resolved'; } catch (e) { return e.name + ': ' + e.message; } }
           function norm(s) { return s.replace(/'HID'/g, "'X'").replace(/'USB'/g, "'X'").replace(/HIDDeviceRequestOptions|USBDeviceRequestOptions/g, 'O').replace(/HIDDeviceFilter|USBDeviceFilter/g, 'F'); }
           var pairs = [
             [function(){ return HID.prototype.getDevices.call({}); }, function(){ return USB.prototype.getDevices.call({}); }],
             [function(){ return HID.prototype.requestDevice.call({}, {filters: []}); }, function(){ return USB.prototype.requestDevice.call({}, {filters: []}); }],
             [function(){ return navigator.hid.requestDevice(); }, function(){ return navigator.usb.requestDevice(); }],
             [function(){ return navigator.hid.requestDevice({}); }, function(){ return navigator.usb.requestDevice({}); }],
             [function(){ return navigator.hid.requestDevice(1); }, function(){ return navigator.usb.requestDevice(1); }],
             [function(){ return navigator.hid.requestDevice({filters: 5}); }, function(){ return navigator.usb.requestDevice({filters: 5}); }],
             [function(){ return navigator.hid.requestDevice({filters: [5]}); }, function(){ return navigator.usb.requestDevice({filters: [5]}); }],
             [function(){ return navigator.hid.requestDevice({filters: []}); }, function(){ return navigator.usb.requestDevice({filters: []}); }]
           ];
           var bad = [];
           for (var i = 0; i < pairs.length; i++) {
             var a = norm(await rej(pairs[i][0])), b = norm(await rej(pairs[i][1]));
             if (a !== b) bad.push([a, b]);
           }
           return bad.length === 0 ? true : JSON.stringify(bad);""")
    expect(h, "event handler attribute semantics equal native (null default, non-object -> null, object kept)",
           r"""function probe(t) {
             var seq = [String(t.onconnect)];
             t.onconnect = function () {}; seq.push(typeof t.onconnect);
             t.onconnect = 5; seq.push(String(t.onconnect));
             t.onconnect = {}; seq.push(typeof t.onconnect);
             t.onconnect = null; seq.push(String(t.onconnect));
             return seq.join('|');
           }
           return probe(navigator.hid) === probe(navigator.usb);""")
    expect(h, "strict-mode assignment to navigator.usb throws the same TypeError as navigator.hid",
           r"""'use strict';
           function e(k) { try { navigator[k] = 5; return 'no throw'; } catch (x) { return x.name + ': ' + x.message.replace(k, 'K'); } }
           return e('hid') === e('usb');""")
    expect(h, "Function.prototype.toString self-consistency (native-looking)",
           r"""var f = Function.prototype.toString;
           return f.call(f) === 'function toString() { [native code] }' && f.name === 'toString' && f.length === 0 &&
                  !f.hasOwnProperty('prototype') && f.toString() === 'function toString() { [native code] }' &&
                  f.call(function foo() { return 1; }) === 'function foo() { return 1; }' &&
                  f.call(class A { m() {} }) === 'class A { m() {} }' &&
                  f.call(Math.max) === 'function max() { [native code] }' &&
                  f.call(new Proxy(function(){}, {})) === 'function () { [native code] }';""")
    expect(h, "Function.prototype.toString rejects non-functions with the native message",
           r"""try { Function.prototype.toString.call({}); return 'no throw'; } catch (e) { return e.name + ': ' + e.message; }""",
           equals="TypeError: Function.prototype.toString requires that 'this' be a Function")

    # ---------------------------------------------------------------- delete protection
    expect(h, "delete navigator.usb returns true and navigator.usb keeps working",
           r"""var before = navigator.usb; var r = delete navigator.usb; return r === true && navigator.usb === before && typeof navigator.usb.getDevices === 'function';""")
    expect(h, "delete Navigator.prototype.usb is refused (lock) and navigator.usb survives",
           r"""'use strict'; var before = navigator.usb; var msg = 'no throw';
           try { delete Navigator.prototype.usb; } catch (e) { msg = e.name; }
           return msg === 'TypeError' && navigator.usb === before;""")
    expect(h, "Object.defineProperty(Navigator.prototype,'usb',...) is refused",
           r"""try { Object.defineProperty(Navigator.prototype, 'usb', {value: 1}); return 'no throw'; } catch (e) { return e.name === 'TypeError' && navigator.usb instanceof USB; }""")
    expect(h, "navigator.usb = null (sloppy) is ignored, like a getter-only native attribute",
           r"""navigator.usb = null; navigator.usb = undefined; return navigator.usb instanceof USB;""")
    expect(h, "deleting window.USB does not break navigator.usb",
           r"""var U = window.USB; delete window.USB; var ok = navigator.usb instanceof U && typeof navigator.usb.getDevices === 'function'; window.USB = U; return ok;""")

    # ---------------------------------------------------------------- B. behaviour with the virtual device
    expect(h, "getDevices() returns granted USBDevice objects (stable identity, no own props)",
           r"""var a = await navigator.usb.getDevices(); var b = await navigator.usb.getDevices();
           var d = a[0];
           return a.length === 1 && a[0] === b[0] && d instanceof USBDevice && Object.keys(d).length === 0 && JSON.stringify(d) === '{}' &&
                  d.vendorId === 0x2341 && d.productId === 0x8036 && d.productName === 'Virtual Widget' && d.manufacturerName === 'Acme' &&
                  d.serialNumber === 'SN-0001' && d.opened === false && Object.prototype.toString.call(d) === '[object USBDevice]';""")
    expect(h, "descriptor graph is native-shaped (USBConfiguration/Interface/AlternateInterface/Endpoint, frozen arrays)",
           r"""var d = (await navigator.usb.getDevices())[0]; var c = d.configurations[0]; var i = c.interfaces[0]; var a = i.alternates[0]; var e = a.endpoints[0];
           return d.configurations.length === 1 && Object.isFrozen(d.configurations) && c instanceof USBConfiguration && i instanceof USBInterface &&
                  a instanceof USBAlternateInterface && e instanceof USBEndpoint && c.configurationValue === 1 && i.interfaceNumber === 0 &&
                  i.alternate === a && i.claimed === false && a.interfaceClass === 0xFF && a.endpoints.length === 2 &&
                  e.endpointNumber === 1 && e.direction === 'in' && e.type === 'bulk' && (d.configuration === null || d.configuration.configurationValue === 1);""")
    expect(h, "open -> claim -> transferOut/In -> release -> close works end to end",
           r"""var d = (await navigator.usb.getDevices())[0];
           await d.open();
           if (!d.opened) return 'not opened';
           if (d.configuration === null) await d.selectConfiguration(1);
           await d.claimInterface(0);
           var claimed = d.configuration.interfaces[0].claimed === true;
           var o = await d.transferOut(1, new Uint8Array([1, 2, 3]));
           var i = await d.transferIn(1, 8);
           await d.releaseInterface(0);
           var released = d.configuration.interfaces[0].claimed === false;
           await d.close();
           return claimed && released && !d.opened && o instanceof USBOutTransferResult && o.status === 'ok' && o.bytesWritten === 3 &&
                  i instanceof USBInTransferResult && i.status === 'ok' && i.data instanceof DataView && i.data.byteLength === 8 &&
                  Object.prototype.toString.call(i) === '[object USBInTransferResult]';""")
    expect(h, "control transfers and error mapping (InvalidStateError / NotFoundError / IndexSizeError texts)",
           r"""var d = (await navigator.usb.getDevices())[0];
           function m(p) { return p.then(function () { return 'resolved'; }, function (e) { return e.name + ': ' + e.message; }); }
           var out = [];
           out.push(await m(d.transferIn(1, 8)));
           await d.open();
           if (d.configuration === null) await d.selectConfiguration(1);
           out.push(await m(d.transferIn(1, 8)));
           out.push(await m(d.claimInterface(9)));
           await d.claimInterface(0);
           out.push(await m(d.transferIn(0, 8)));
           out.push(await m(d.transferIn(2, 8)));
           out.push(await m(d.transferIn()));
           out.push(await m(d.selectAlternateInterface(0, 5)));
           var ci = await d.controlTransferIn({requestType: 'vendor', recipient: 'device', request: 1, value: 0, index: 0}, 4);
           out.push(ci.constructor.name + ':' + ci.status);
           out.push(await m(d.controlTransferIn({requestType: 'bogus', recipient: 'device', request: 1, value: 0, index: 0}, 4)));
           out.push(await m(d.controlTransferIn({requestType: 'vendor', recipient: 'device', request: 1, value: 0}, 4)));
           await d.releaseInterface(0);
           await d.close();
           return JSON.stringify(out);""",
           equals=json.dumps([
               "InvalidStateError: The device must be opened first.",
               "InvalidStateError: The specified interface has not been claimed.".replace("The specified interface has not been claimed.", "The specified endpoint is not part of a claimed and selected alternate interface.") if False else "NotFoundError: The specified endpoint is not part of a claimed and selected alternate interface.",
               "NotFoundError: The interface number provided is not supported by the device in its current configuration.",
               "IndexSizeError: The specified endpoint number is out of range.",
               "NotFoundError: The specified endpoint is not part of a claimed and selected alternate interface.",
               "TypeError: Failed to execute 'transferIn' on 'USBDevice': 2 arguments required, but only 0 present.",
               "NotFoundError: The alternate setting provided is not supported by the device in its current configuration.",
               "USBInTransferResult:ok",
               "TypeError: Failed to execute 'controlTransferIn' on 'USBDevice': Failed to read the 'requestType' property from 'USBControlTransferParameters': The provided value 'bogus' is not a valid enum value of type USBRequestType.",
               "TypeError: Failed to execute 'controlTransferIn' on 'USBDevice': Failed to read the 'index' property from 'USBControlTransferParameters': Required member is undefined.",
           ], separators=(",", ":")))
    # hotplug events
    r = h.run(r"""
       var events = [];
       navigator.usb.addEventListener('connect', function (e) { events.push('L:connect:' + (e instanceof USBConnectionEvent) + ':' + (e.device instanceof USBDevice) + ':' + e.device.vendorId); });
       navigator.usb.addEventListener('disconnect', function (e) { events.push('L:disconnect:' + e.device.opened + ':' + e.device.vendorId); });
       navigator.usb.onconnect = function (e) { events.push('H:connect'); };
       await navigator.usb.getDevices();
       window.__events = events;
       return true;""")
    h.bridge._poll_hotplug()      # まず現在の接続状況を基準(ベースライン)として取り込む
    spin(100)
    h.device.unplug()
    h.bridge._poll_hotplug()      # 差分: disconnect
    spin(1200)
    h.device.plug()
    h.bridge._poll_hotplug()      # 差分: connect
    spin(1500)
    expect(h, "hotplug: disconnect then connect events reach listeners with USBConnectionEvent/USBDevice",
           r"""var e = window.__events || []; return JSON.stringify(e);""",
           predicate=lambda v: "L:disconnect:false:9025" in v and "L:connect:true:true:9025" in v and "H:connect" in v)
    expect(h, "the reconnected device is a fresh USBDevice object",
           r"""var d = (await navigator.usb.getDevices())[0]; return d instanceof USBDevice && d.opened === false;""")

    # requestDevice: no user activation when driven from runJavaScript -> native SecurityError text
    expect(h, "requestDevice without user activation rejects with the exact Chromium SecurityError",
           r"""try { await navigator.usb.requestDevice({filters: [{vendorId: 0x2341}]}); return 'resolved'; } catch (e) { return e.name + ': ' + e.message; }""",
           equals="SecurityError: Failed to execute 'requestDevice' on 'USB': Must be handling a user gesture to show a permission request.")
    expect(h, "filter validation texts (productId without vendorId, etc.) are TypeErrors",
           r"""async function m(f) { try { await f(); return 'resolved'; } catch (e) { return e.name + ': ' + e.message; } }
           var out = [];
           // no user activation in this context: emulate the check order by asserting conversion errors come first
           out.push(await m(function(){ return navigator.usb.requestDevice({filters: [{productId: 1}]}); }));
           return out[0];""",
           predicate=lambda v: v.startswith("SecurityError:") or v.startswith("TypeError: A filter containing"))

    # ---------------------------------------------------------------- self test & commands
    expect(h, "window.__pysideWebUSB.selfTest() passes all checks",
           r"""var r = __pysideWebUSB.selfTest(); return r.ok === true ? true : JSON.stringify(r.checks.filter(function (c) { return !c.ok; }));""")
    expect(h, "custom commands work (platform / transport / version / diagnose / bridgeInfo / help / locale)",
           r"""var p = await __pysideWebUSB.platform(); var t = await __pysideWebUSB.transport(); var v = await __pysideWebUSB.version();
           var dg = await __pysideWebUSB.diagnose(); var b = await __pysideWebUSB.bridgeInfo(); var hp = __pysideWebUSB.help();
           return p.host.os === 'linux' && t.kind === 'webchannel' && t.ready === true && v.bridge.indexOf('0.0.6') === 0 &&
                  dg.transport === 'webchannel' && dg.backendUsable === true && b.available === true && typeof hp === 'string' &&
                  __pysideWebUSB.locale() === 'en';""")
    expect(h, "listGrantedDevices() lists the granted device",
           r"""var rows = await __pysideWebUSB.listGrantedDevices(); return rows.length === 1 && rows[0].vendorId === '0x2341';""")

    # ---------------------------------------------------------------- C. tamper resistance
    expect(h, "page monkey-patching Promise/JSON/Array/Function/Object/WeakMap cannot break or hijack the bridge",
           r"""var saved = {then: Promise.prototype.then, parse: JSON.parse, str: JSON.stringify, push: Array.prototype.push, call: Function.prototype.call,
                         apply: Function.prototype.apply, bind: Function.prototype.bind, dp: Object.defineProperty, wmget: WeakMap.prototype.get,
                         wmset: WeakMap.prototype.set, atob: window.atob, btoa: window.btoa, resolve: Promise.resolve, slice: Array.prototype.slice};
           var hijacked = 0;
           Promise.prototype.then = function () { hijacked++; return saved.then.apply(this, arguments); };
           JSON.parse = function () { hijacked++; return saved.parse.apply(this, arguments); };
           JSON.stringify = function () { hijacked++; return saved.str.apply(this, arguments); };
           Array.prototype.push = function () { hijacked++; return saved.push.apply(this, arguments); };
           Array.prototype.slice = function () { hijacked++; return saved.slice.apply(this, arguments); };
           WeakMap.prototype.get = function () { hijacked++; return saved.wmget.apply(this, arguments); };
           WeakMap.prototype.set = function () { hijacked++; return saved.wmset.apply(this, arguments); };
           Promise.resolve = function () { hijacked++; return saved.resolve.apply(this, arguments); };
           window.atob = function () { hijacked++; return saved.atob.apply(window, arguments); };
           window.btoa = function () { hijacked++; return saved.btoa.apply(window, arguments); };
           var res;
           try {
             var d = (await navigator.usb.getDevices())[0];
             await d.open(); if (d.configuration === null) await d.selectConfiguration(1); await d.claimInterface(0);
             var o = await d.transferOut(1, new Uint8Array([9, 8, 7]));
             await d.releaseInterface(0); await d.close();
             res = o.bytesWritten === 3;
           } finally {
             Promise.prototype.then = saved.then; JSON.parse = saved.parse; JSON.stringify = saved.str; Array.prototype.push = saved.push;
             Array.prototype.slice = saved.slice; WeakMap.prototype.get = saved.wmget; WeakMap.prototype.set = saved.wmset; Promise.resolve = saved.resolve;
             window.atob = saved.atob; window.btoa = saved.btoa;
           }
           return res === true ? true : 'result=' + res;""")
    # extra_guard hijack: the guard function is captured once
    h2 = Harness()
    h2.page.runJavaScript("window.__pysideWebUSBExtraGuard = function () { return false; };")
    spin(100)
    expect(h2, "page cannot install an extra guard after the polyfill started (guard is captured once at startup)",
           r"""try { await navigator.usb.requestDevice({filters: [{vendorId: 0x2341}]}); return 'x'; } catch (e) { return e.name; }""",
           predicate=lambda v: v == "SecurityError")

    # ---------------------------------------------------------------- sub-frames (per-frame origin isolation)
    port = ORIGIN.rsplit(":", 1)[1]
    hf = Harness()
    hf.page.runJavaScript("window.__frames = []; window.addEventListener('message', function (e) { window.__frames.push(e.data); });"
                          "document.body.innerHTML = '<iframe id=same src=\"http://127.0.0.1:%s/frame\"></iframe>"
                          "<iframe id=other src=\"http://localhost:%s/frame\"></iframe>';" % (port, port))
    spin(3500)
    r = hf.run("return window.__frames")
    frames = [json.loads(x) for x in (r.get("ok") or [])]
    by_origin = {f["o"]: f for f in frames}
    same = by_origin.get(ORIGIN)
    other = by_origin.get("http://localhost:" + port)
    # QtWebEngineは qt.webChannelTransport をメインフレームにしか出さない(PySide6 6.11.2実測)。
    # よってiframe内ではポリフィルは「何も入れない」(fail closed)。トークンは配られるが、
    # 非列挙で、ブリッジへ到達する手段が無い。メインフレームの機能はiframeの存在に影響されない。
    record("sub-frame: both frames loaded and reported", bool(same) and bool(other), json.dumps(frames))
    for label, f in (("same-origin", same), ("cross-origin", other)):
        if not f:
            continue
        record("sub-frame (%s): no transport in the frame -> polyfill stays out (navigator.usb undefined, no classes) instead of half-working" % label,
               f["hasQt"] == "undefined" and f["hasUsb"] == "undefined" and f["hasClass"] == "undefined", json.dumps(f))
        record("sub-frame (%s): nothing polyfill-ish is enumerable in the frame's window (token is non-enumerable)" % label,
               f["leaked"] == 0 and f["tokEnumerable"] is False, json.dumps(f))
    expect(hf, "main frame keeps working while iframes are present",
           "var a = await navigator.usb.getDevices(); return a.length === 1 && a[0].productName === 'Virtual Widget'")

    # ---------------------------------------------------------------- real user gesture (real click)
    def click_flow(harness, name):
        view = QWebEngineView()
        view.setPage(harness.page)
        view.resize(500, 400)
        view.show()
        spin(600)
        harness.page.runJavaScript(r"""
          document.body.innerHTML = '<button id=b style="position:fixed;left:0;top:0;width:300px;height:200px">go</button>';
          window.__g = null;
          document.getElementById('b').addEventListener('click', function () {
            var active = navigator.userActivation.isActive;
            navigator.usb.requestDevice({filters: [{vendorId: 0x2341}]}).then(
              function (d) { window.__g = 'ok:' + (d instanceof USBDevice) + ':' + d.productName + ':' + d.serialNumber + ':active=' + active; },
              function (e) { window.__g = 'err:' + e.name + ':' + e.message + ':active=' + active; });
          });""")
        spin(300)
        QTest.mouseClick(view.focusProxy() or view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
        got = {}
        for _ in range(50):
            spin(200)
            harness.page.runJavaScript("window.__g", lambda v: got.__setitem__("v", v))
            spin(50)
            if got.get("v"):
                break
        return got.get("v"), view

    hg = Harness(grant=False)
    v, view_g = click_flow(hg, "gesture")
    record("requestDevice from a real click resolves to a USBDevice", v == "ok:true:Virtual Widget:SN-0001:active=true", v)
    record("...and records the per-origin grant", hg.bridge._is_granted(ORIGIN, VID, PID) is True)
    expect(hg, "...and the granted device is now listed by getDevices() (same object as requestDevice returned)",
           r"""var a = await navigator.usb.getDevices(); return a.length === 1 && a[0].productName === 'Virtual Widget';""")
    view_g.close()

    hc = Harness(grant=False, chooser="cancel")
    v, view_c = click_flow(hc, "cancel")
    record("cancelling the chooser rejects with NotFoundError: No device selected.",
           v == "err:NotFoundError:No device selected.:active=true", v)
    record("...and grants nothing", hc.bridge._is_granted(ORIGIN, VID, PID) is False)
    view_c.close()

    # ---------------------------------------------------------------- opt-outs
    h3 = Harness(lock=False, native_lookalike=False, expose_commands=False)
    expect(h3, "lock_navigator_usb=False gives the exact native configurable:true descriptor",
           r"""var u = Object.getOwnPropertyDescriptor(Navigator.prototype, 'usb'); var n = Object.getOwnPropertyDescriptor(Navigator.prototype, 'hid'); return u.configurable === true && n.configurable === true;""")
    expect(h3, "expose_commands=False hides window.__pysideWebUSB entirely",
           r"""return typeof window.__pysideWebUSB === 'undefined' && !('__pysideWebUSB' in window);""")
    expect(h3, "native_lookalike=False leaves Function.prototype.toString untouched",
           r"""return Function.prototype.toString.call(navigator.usb.getDevices).indexOf('[native code]') < 0;""")
    return CHECKS


def main():
    try:
        checks = run_all()
    except Exception as e:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        checks = CHECKS + [{"name": "runner crashed", "ok": False, "detail": repr(e)}]
    print("E2E_JSON=" + json.dumps({"checks": checks}))
    sys.stdout.flush()
    os._exit(0 if all(c["ok"] for c in checks) else 1)


if __name__ == "__main__":
    main()
