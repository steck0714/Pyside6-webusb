// tests/test_polyfill.js  (v0.0.6a: ポリフィルの作り直しに合わせて全面刷新)
//
// tests/extract_polyfill_js.py が書き出した
//   _polyfill_extracted.js   (既定設定のポリフィル)
//   _bridge_signatures.json  (Python側WebUSBBridgeの公開スロット署名)
// を、Nodeの`vm`で作った「ブラウザ風の独立レルム」にロードして検証する。
// 実物のChromiumでの検証は tests/e2e_webengine_runner.py / e2e_qtwebview_runner.py の役目で、
// ここは「Qtもブラウザも無い環境(CIの軽量ジョブ等)でも回る」層:
//   1. JS→Pythonの引数契約: JSが呼ぶ全スロットの引数の個数・型が、Python側の宣言と一致する
//   2. インターフェースの形(記述子/タグ/illegal constructor/ブランドチェック/[native code])
//   3. delete/lock/代入で navigator.usb が消えない
//   4. プロトコル(転送結果のデコード、チャンク分割の落とし穴、状態機械、エラー写像)
//   5. ホットプラグのイベント
//   6. 独自コマンド(__pysideWebUSB)
//   7. WebSocket転送層のクライアント実装(偽WebSocketで)
//   8. ページ側のビルトイン書き換え(改ざん)への耐性
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const POLYFILL = fs.readFileSync(path.join(__dirname, '_polyfill_extracted.js'), 'utf8');
const SIG_PATH = path.join(__dirname, '_bridge_signatures.json');
const SIGNATURES = fs.existsSync(SIG_PATH) ? JSON.parse(fs.readFileSync(SIG_PATH, 'utf8')) : null;
if (!SIGNATURES) console.log('WARN: _bridge_signatures.json not found -> argument contract checks are skipped');

let passed = 0;
const failures = [];
async function test(name, fn) {
    try { await fn(); passed++; console.log('ok   - ' + name); }
    catch (e) { failures.push(name); console.log('FAIL - ' + name + '\n       ' + (e && e.stack || e)); }
}

// ------------------------------------------------------------------ fake bridge
const DEVICE = {
    vendorId: 0x2341, productId: 0x8036, manufacturerName: 'Acme', productName: 'Widget', serialNumber: 'SN1',
    deviceClass: 0, deviceSubclass: 0, deviceProtocol: 0, usbVersionMajor: 2, usbVersionMinor: 0, usbVersionSubminor: 0,
    deviceVersionMajor: 1, deviceVersionMinor: 2, deviceVersionSubminor: 3,
    configurations: [
        { configurationValue: 1, configurationName: 'Main', interfaces: [{
            interfaceNumber: 0,
            // alternateSetting=1 を先頭に置く: 「配列の先頭を機械的に使う」誤実装を炙り出す
            alternates: [
                { alternateSetting: 1, interfaceClass: 0xFF, interfaceSubclass: 0, interfaceProtocol: 0, interfaceName: null, endpoints: [] },
                { alternateSetting: 0, interfaceClass: 0xFF, interfaceSubclass: 1, interfaceProtocol: 2, interfaceName: 'Iface', endpoints: [
                    { endpointNumber: 1, direction: 'in', type: 'bulk', packetSize: 64 },
                    { endpointNumber: 2, direction: 'out', type: 'bulk', packetSize: 64 },
                    { endpointNumber: 3, direction: 'in', type: 'isochronous', packetSize: 32 },
                    { endpointNumber: 4, direction: 'out', type: 'isochronous', packetSize: 32 },
                ] },
            ],
        }] },
        { configurationValue: 2, configurationName: null, interfaces: [] },
    ],
};

function typeOk(t, v) {
    if (t === 'int') return typeof v === 'number' && Number.isInteger(v);
    if (t === 'QString') return typeof v === 'string';
    if (t === 'bool') return typeof v === 'boolean';
    return false;
}

function makeBridge() {
    const st = {
        calls: [], contractErrors: [], devices: [DEVICE], warns: [],
        responses: {
            openDevice: { success: true, handle: 7 },
            selectConfiguration: { success: true }, claimInterface: { success: true }, releaseInterface: { success: true },
            selectAlternateInterface: { success: true }, resetDevice: { success: true }, clearHalt: { success: true },
            bulkTransferIn: { success: true, status: 'ok', data: 'AQID' },
            bulkTransferOut: { success: true, status: 'ok', bytesWritten: 3 },
            controlTransferIn: { success: true, status: 'ok', data: 'AA==' },
            controlTransferOut: { success: true, status: 'ok', bytesWritten: 1 },
            isochronousTransferIn: { success: true, packets: [{ status: 'ok', data: 'AQI=' }, { status: 'ok', data: 'AwQ=' }] },
            isochronousTransferOut: { success: true, packets: [{ status: 'ok', bytesWritten: 2 }, { status: 'ok', bytesWritten: 2 }] },
            forgetGrantedDevice: { success: true },
            closeDevice: { success: true },
            requestDeviceChooser: () => ({ device: st.devices[0] }),
        },
        granted: true,
        signals: { deviceConnected: [], deviceDisconnected: [] },
    };
    function validate(name, args) {
        if (!SIGNATURES) return;
        const overloads = SIGNATURES[name];
        if (!overloads) { st.contractErrors.push(name + ': not a public slot of WebUSBBridge'); return; }
        const ok = overloads.some(o => o.params.length === args.length && o.params.every((t, i) => typeOk(t, args[i])));
        if (!ok) st.contractErrors.push(name + '(' + args.map(a => typeof a === 'number' ? 'int' : typeof a).join(',') + ') matches no overload ' +
            JSON.stringify(overloads.map(o => o.params)));
    }
    function method(name, fixed) {
        return function () {
            const a = Array.prototype.slice.call(arguments);
            let cb = null;
            if (typeof a[a.length - 1] === 'function') cb = a.pop();
            validate(name, a);
            st.calls.push([name].concat(a));
            let r = st.responses[name];
            if (typeof r === 'function') r = r(a);
            const out = fixed !== undefined ? fixed(a) : JSON.stringify(r);
            if (cb) cb(out);
        };
    }
    st.bridge = {
        deviceConnected: { connect: (fn) => st.signals.deviceConnected.push(fn) },
        deviceDisconnected: { connect: (fn) => st.signals.deviceDisconnected.push(fn) },
        isAvailable: method('isAvailable', () => JSON.stringify({
            available: true, bridgeVersion: '0.0.6.post1-test', platform: { os: 'linux', machine: 'x86_64', python: '3.12' },
            capabilities: { bulkTransfer: 'supported' }, transport: 'webchannel',
            transferLimits: { chromeCompatibleWarnThreshold: 33554432, hostSafetyHardLimit: 536870912, controlTransferMaxLength: 65535 } })),
        getDiagnostics: method('getDiagnostics', () => JSON.stringify({ bridgeVersion: 'x', transport: 'webchannel', backendUsable: true })),
        listDevices: method('listDevices', () => JSON.stringify({ devices: st.devices })),
        mintGestureToken: method('mintGestureToken', () => 'fake-gesture-token'),
        isGrantedToThisFrame: method('isGrantedToThisFrame', () => st.granted),
    };
    ['openDevice', 'closeDevice', 'selectConfiguration', 'claimInterface', 'releaseInterface', 'selectAlternateInterface', 'resetDevice',
     'clearHalt', 'forgetGrantedDevice', 'bulkTransferIn', 'bulkTransferOut', 'controlTransferIn', 'controlTransferOut',
     'isochronousTransferIn', 'isochronousTransferOut', 'requestDeviceChooser'].forEach(n => { st.bridge[n] = method(n); });
    return st;
}

// ------------------------------------------------------------------ vm environment
function makeEnv(opts) {
    opts = opts || {};
    const st = makeBridge();
    const sandbox = {
        console: { warn: (m) => st.warns.push(String(m)), log() {}, debug() {}, table() {} },
        setTimeout, clearTimeout, atob: (s) => Buffer.from(s, 'base64').toString('binary'), btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
        EventTarget, Event, DOMException,
    };
    if (opts.webSocket) sandbox.WebSocket = opts.webSocket;
    else {
        sandbox.qt = { webChannelTransport: {} };
        sandbox.QWebChannel = function (transport, cb) { setTimeout(() => cb({ objects: { pyUsbBridge: st.bridge } }), 0); };
    }
    const ctx = vm.createContext(sandbox);
    vm.runInContext(`
        var window = globalThis;
        function Navigator() {}
        Object.defineProperty(Navigator.prototype, Symbol.toStringTag, {value: 'Navigator', configurable: true});
        Object.defineProperty(Navigator.prototype, 'userAgent', { get: function userAgent() { return 'test'; }, enumerable: true, configurable: true });
        var navigator = new Navigator();
        navigator.userActivation = { isActive: true };
        window.isSecureContext = ${opts.insecure ? 'false' : 'true'};
    `, ctx);
    let src = POLYFILL;
    if (opts.config) {
        src = src.replace(/\/\*CONFIG_BEGIN\*\/[\s\S]*?\/\*CONFIG_END\*\//, (m) => {
            const cur = JSON.parse(m.slice('/*CONFIG_BEGIN*/'.length, -'/*CONFIG_END*/'.length));
            return '/*CONFIG_BEGIN*/' + JSON.stringify(Object.assign(cur, opts.config)) + '/*CONFIG_END*/';
        });
    }
    st.ctx = ctx;
    st.run = (code) => vm.runInContext(code, ctx);
    st.load = () => vm.runInContext(src, ctx);
    if (!opts.deferLoad) st.load();
    return st;
}
const tick = (ms) => new Promise(r => setTimeout(r, ms || 15));
// vmレルム由来の配列/オブジェクトはdeepStrictEqualのプロトタイプ比較で別物扱いになるので、素のJSONへ写す
const plain = (x) => JSON.parse(JSON.stringify(x));
const settle = async (env) => { await tick(); return env; };

async function opened(env) {
    const d = (await env.run('navigator.usb.getDevices()'))[0];
    await d.open();
    return d;
}
const outcome = (env, js) => env.run(`(async function () { try { await (${js}); return 'resolved'; } catch (e) { return e.name + ': ' + e.message; } })()`);
const sync = (env, js) => env.run(`(function () { try { ${js}; return 'no throw'; } catch (e) { return e.name + ': ' + e.message; } })()`);
async function rejection(p) { try { await p; return 'resolved'; } catch (e) { return e.name + ': ' + e.message; } }

(async function main() {
    // ============================================================ 1. contract
    await test('contract: every slot the polyfill calls exists in the Python bridge with a matching arity and types', async () => {
        const env = await settle(makeEnv());
        const d = await opened(env);
        await d.selectConfiguration(2); await d.selectConfiguration(1);
        await d.claimInterface(0);
        await d.selectAlternateInterface(0, 1); await d.selectAlternateInterface(0, 0);
        await d.transferOut(2, new Uint8Array([1, 2, 3])); await d.transferIn(1, 8);
        await d.isochronousTransferIn(3, [2, 2]); await d.isochronousTransferOut(4, new Uint8Array([1, 2, 3, 4]), [2, 2]);
        await d.controlTransferIn({ requestType: 'vendor', recipient: 'device', request: 1, value: 2, index: 3 }, 4);
        await d.controlTransferOut({ requestType: 'class', recipient: 'interface', request: 1, value: 2, index: 0 }, new Uint8Array([9]));
        await d.clearHalt('in', 1);
        await d.releaseInterface(0);
        await d.reset();
        await d.close(); await tick();
        await d.open(); await d.forget();
        await env.run("navigator.usb.requestDevice({filters: [{vendorId: 0x2341}]})");
        await env.run('__pysideWebUSB.bridgeInfo()'); await env.run('__pysideWebUSB.diagnose()');
        assert.deepStrictEqual(env.contractErrors, []);
        const used = new Set(env.calls.map(c => c[0]));
        for (const m of ['listDevices', 'openDevice', 'closeDevice', 'selectConfiguration', 'claimInterface', 'releaseInterface', 'selectAlternateInterface',
                         'bulkTransferIn', 'bulkTransferOut', 'controlTransferIn', 'controlTransferOut', 'isochronousTransferIn', 'isochronousTransferOut',
                         'clearHalt', 'resetDevice', 'forgetGrantedDevice', 'requestDeviceChooser', 'mintGestureToken', 'getDiagnostics', 'isAvailable']) {
            assert.ok(used.has(m), m + ' was never exercised');
        }
    });

    await test('contract: openDevice passes (vid, pid, frameToken, serial) and the frame token is forwarded to every call', async () => {
        const env = await settle(makeEnv());
        env.run("Object.defineProperty(window, '__pyUsbFrameToken', {value: 'tok-123', configurable: true, writable: true, enumerable: false})");
        const d = await opened(env);
        await d.claimInterface(0); await d.transferOut(2, new Uint8Array([1]));
        const open = env.calls.find(c => c[0] === 'openDevice');
        assert.deepStrictEqual(open.slice(1), [0x2341, 0x8036, 'tok-123', 'SN1']);
        for (const c of env.calls) if (['claimInterface', 'bulkTransferOut'].includes(c[0])) assert.strictEqual(c[c.length - 1], 'tok-123');
    });

    // ============================================================ 2. shape
    await test('shape: navigator.usb is a USB instance, [object USB], no own keys, JSON is {}', async () => {
        const env = await settle(makeEnv());
        assert.strictEqual(env.run('navigator.usb instanceof USB'), true);
        assert.strictEqual(env.run('Object.prototype.toString.call(navigator.usb)'), '[object USB]');
        assert.strictEqual(env.run('Object.getOwnPropertyNames(navigator.usb).length + Object.keys(navigator.usb).length'), 0);
        assert.strictEqual(env.run('JSON.stringify(navigator.usb)'), '{}');
        assert.strictEqual(env.run("Object.prototype.hasOwnProperty.call(navigator, 'usb')"), false);
    });

    await test('shape: all 13 interfaces exist; tags, prototypes and descriptors follow the native rules', async () => {
        const env = await settle(makeEnv());
        const issues = env.run(`(function () {
            var names = ['USB','USBConnectionEvent','USBDevice','USBInTransferResult','USBOutTransferResult','USBIsochronousInTransferPacket',
                         'USBIsochronousInTransferResult','USBIsochronousOutTransferPacket','USBIsochronousOutTransferResult','USBConfiguration',
                         'USBInterface','USBAlternateInterface','USBEndpoint'];
            var bad = [], fts = Function.prototype.toString;
            names.forEach(function (n) {
                var C = window[n];
                if (typeof C !== 'function') { bad.push(n + ' missing'); return; }
                var d = Object.getOwnPropertyDescriptor(window, n);
                if (d.enumerable || !d.writable || !d.configurable) bad.push(n + ' global flags');
                if (Reflect.ownKeys(C).map(String).sort().join() !== 'length,name,prototype') bad.push(n + ' ctor keys');
                if (fts.call(C) !== 'function ' + n + '() { [native code] }') bad.push(n + ' toString');
                var pd = Object.getOwnPropertyDescriptor(C, 'prototype'); if (pd.writable || pd.enumerable || pd.configurable) bad.push(n + ' prototype flags');
                var td = Object.getOwnPropertyDescriptor(C.prototype, Symbol.toStringTag);
                if (!td || td.value !== n || td.writable || td.enumerable || !td.configurable) bad.push(n + ' tag');
                Reflect.ownKeys(C.prototype).forEach(function (k) {
                    if (typeof k === 'symbol' || k === 'constructor') return;
                    var p = Object.getOwnPropertyDescriptor(C.prototype, k);
                    if ('value' in p) {
                        if (!p.writable || !p.enumerable || !p.configurable || p.value.hasOwnProperty('prototype') || p.value.name !== k ||
                            fts.call(p.value) !== 'function ' + k + '() { [native code] }') bad.push(n + '.' + k + ' method');
                    } else {
                        if (!p.enumerable || !p.configurable || p.get.name !== 'get ' + k || p.get.length !== 0 || p.get.hasOwnProperty('prototype') ||
                            fts.call(p.get) !== 'function get ' + k + '() { [native code] }') bad.push(n + '.' + k + ' accessor');
                    }
                });
            });
            if (Object.getPrototypeOf(USB.prototype) !== EventTarget.prototype) bad.push('USB proto');
            if (Object.getPrototypeOf(USBConnectionEvent) !== Event) bad.push('event ctor proto');
            return JSON.stringify(bad);
        })()`);
        assert.strictEqual(issues, '[]');
    });

    await test('shape: illegal constructors, brand checks and argument errors use the Blink texts', async () => {
        const env = await settle(makeEnv());
        assert.strictEqual(sync(env, 'new USB()'), "TypeError: Failed to construct 'USB': Illegal constructor");
        assert.strictEqual(sync(env, 'USB()'), 'TypeError: Illegal constructor');
        assert.strictEqual(sync(env, 'new USBDevice()'), "TypeError: Failed to construct 'USBDevice': Illegal constructor");
        assert.strictEqual(sync(env, "Object.getOwnPropertyDescriptor(Navigator.prototype,'usb').get.call({})"), 'TypeError: Illegal invocation');
        assert.strictEqual(sync(env, "USBInTransferResult('ok')"),
            "TypeError: Failed to construct 'USBInTransferResult': Please use the 'new' operator, this DOM object constructor cannot be called as a function.");
        assert.strictEqual(sync(env, 'new USBConnectionEvent()'), "TypeError: Failed to construct 'USBConnectionEvent': 2 arguments required, but only 0 present.");
        assert.strictEqual(sync(env, "new USBConnectionEvent('connect', {device: 1})"),
            "TypeError: Failed to construct 'USBConnectionEvent': Failed to read the 'device' property from 'USBConnectionEventInit': Failed to convert value to 'USBDevice'.");
        assert.strictEqual(sync(env, "new USBInTransferResult('bogus')"),
            "TypeError: Failed to construct 'USBInTransferResult': The provided value 'bogus' is not a valid enum value of type USBTransferStatus.");
        assert.strictEqual(await outcome(env, 'USB.prototype.getDevices.call({})'), "TypeError: Failed to execute 'getDevices' on 'USB': Illegal invocation");
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice()'), "TypeError: Failed to execute 'requestDevice' on 'USB': 1 argument required, but only 0 present.");
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice({})'),
            "TypeError: Failed to execute 'requestDevice' on 'USB': Failed to read the 'filters' property from 'USBDeviceRequestOptions': Required member is undefined.");
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice(1)'),
            "TypeError: Failed to execute 'requestDevice' on 'USB': The provided value is not of type 'USBDeviceRequestOptions'.");
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice({filters: [{productId: 1}]})'), 'TypeError: A filter containing a productId must also contain a vendorId.');
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice({filters: [{subclassCode: 1}]})'), 'TypeError: A filter containing a subclassCode must also contain a classCode.');
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice({filters: [{classCode: 1, protocolCode: 1}]})'), 'TypeError: A filter containing a protocolCode must also contain a subclassCode.');
    });

    await test('shape: descriptor graph values, frozen/stable arrays, public constructors of the descriptor classes', async () => {
        const env = await settle(makeEnv());
        const d = (await env.run('navigator.usb.getDevices()'))[0];
        assert.strictEqual(d.productName, 'Widget');
        assert.strictEqual(d.deviceVersionSubminor, 3);
        assert.strictEqual(d.configurations.length, 2);
        assert.strictEqual(env.run('(d) => Object.isFrozen(d.configurations)')(d), true);
        assert.strictEqual(d.configurations, d.configurations, 'configurations must be the same array every time');
        const c = d.configurations[0], i = c.interfaces[0];
        assert.strictEqual(env.run('(c) => c instanceof USBConfiguration && c.interfaces[0] instanceof USBInterface && c.interfaces[0].alternates[0] instanceof USBAlternateInterface')(c), true);
        assert.strictEqual(c.configurationName, 'Main');
        assert.strictEqual(d.configurations[1].configurationName, null);
        assert.strictEqual(i.alternates[1].endpoints[0].packetSize, 64);
        // 公開コンストラクタ: 既存の記述子からの再構築と、存在しないものへのRangeError
        assert.strictEqual(env.run('(d) => new USBConfiguration(d, 1).configurationValue')(d), 1);
        assert.strictEqual(env.run('(c) => new USBInterface(c, 0).interfaceNumber')(c), 0);
        assert.strictEqual(env.run('(i) => new USBAlternateInterface(i, 0).interfaceSubclass')(i), 1);
        assert.strictEqual(env.run('(a) => new USBEndpoint(a, 1, "in").type')(i.alternates[1]), 'bulk');
        assert.strictEqual(env.run('(d) => { try { new USBConfiguration(d, 9); } catch (e) { return e.name; } }')(d), 'RangeError');
        assert.strictEqual(env.run('(d) => { try { new USBConfiguration({}, 1); } catch (e) { return e.name; } }')(d), 'TypeError');
    });

    await test('shape: alternate 0 is selected (not the first array entry); claimed/alternate track the device state', async () => {
        const env = await settle(makeEnv());
        const d = await opened(env);
        assert.strictEqual(d.configuration.configurationValue, 1);
        const i = d.configuration.interfaces[0];
        assert.strictEqual(i.alternate.alternateSetting, 0);
        assert.strictEqual(i.alternates.length, 2);
        assert.strictEqual(i.claimed, false);
        await d.claimInterface(0);
        assert.strictEqual(i.claimed, true);
        await d.selectAlternateInterface(0, 1);
        assert.strictEqual(i.alternate.alternateSetting, 1);
        assert.strictEqual(i.alternate.endpoints.length, 0);
        await d.selectAlternateInterface(0, 0);
        assert.strictEqual(i.alternate.endpoints.length, 4);
        await d.releaseInterface(0);
        assert.strictEqual(i.claimed, false);
        await d.selectConfiguration(2);
        assert.strictEqual(d.configuration.configurationValue, 2);
    });

    // ============================================================ 3. lock
    await test('lock: delete navigator.usb is a no-op that returns true; the instance keeps working', async () => {
        const env = await settle(makeEnv());
        assert.strictEqual(env.run('(function(){ var b = navigator.usb; var r = delete navigator.usb; return r === true && navigator.usb === b; })()'), true);
    });
    await test('lock: delete Navigator.prototype.usb / defineProperty are refused by default', async () => {
        const env = await settle(makeEnv());
        assert.strictEqual(env.run("(function(){ 'use strict'; try { delete Navigator.prototype.usb; return 'no throw'; } catch (e) { return e.name; } })()"), 'TypeError');
        assert.strictEqual(env.run("(function(){ try { Object.defineProperty(Navigator.prototype, 'usb', {value: 1}); return 'no throw'; } catch (e) { return e.name; } })()"), 'TypeError');
        assert.strictEqual(env.run('navigator.usb instanceof USB'), true);
        assert.strictEqual(env.run("Object.getOwnPropertyDescriptor(Navigator.prototype, 'usb').configurable"), false);
    });
    await test('lock: lockNavigatorUsb=false gives the native configurable:true descriptor and the self test adapts', async () => {
        const env = await settle(makeEnv({ config: { lockNavigatorUsb: false } }));
        assert.strictEqual(env.run("Object.getOwnPropertyDescriptor(Navigator.prototype, 'usb').configurable"), true);
        assert.strictEqual(env.run('__pysideWebUSB.selfTest().ok'), true);
    });
    await test('lock: assignment is ignored (sloppy) / TypeError (strict) like a getter-only native attribute; deleting window.USB does not break it', async () => {
        const env = await settle(makeEnv());
        assert.strictEqual(env.run('(function(){ navigator.usb = null; return navigator.usb instanceof USB; })()'), true);
        assert.strictEqual(env.run("(function(){ 'use strict'; try { navigator.usb = 5; return 'no throw'; } catch (e) { return e.name; } })()"), 'TypeError');
        assert.strictEqual(env.run('(function(){ var U = window.USB; delete window.USB; var ok = navigator.usb instanceof U; window.USB = U; return ok; })()'), true);
    });
    await test('guards: not installed in an insecure context, and never overrides an existing navigator.usb', async () => {
        const insecure = await settle(makeEnv({ insecure: true }));
        assert.strictEqual(insecure.run('typeof navigator.usb + typeof USB'), 'undefinedundefined');
        const env = makeEnv({ deferLoad: true });
        env.run("Object.defineProperty(Navigator.prototype, 'usb', {get: function () { return 'native'; }, configurable: true})");
        env.load(); await tick();
        assert.strictEqual(env.run('navigator.usb'), 'native');
        assert.strictEqual(env.run('typeof USBDevice'), 'undefined');
    });

    // ============================================================ 4. protocol
    await test('protocol: transfer results are real USBInTransferResult/USBOutTransferResult with a decoded DataView', async () => {
        const env = await settle(makeEnv());
        const d = await opened(env);
        await d.claimInterface(0);
        const r = await d.transferIn(1, 3);
        assert.strictEqual(env.run('(r) => r instanceof USBInTransferResult')(r), true);
        assert.strictEqual(r.status, 'ok');
        assert.deepStrictEqual(Array.from(new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength)), [1, 2, 3]);
        const o = await d.transferOut(2, new Uint8Array([1, 2, 3]));
        assert.strictEqual(o.bytesWritten, 3);
        assert.strictEqual(env.run('(r) => Object.prototype.toString.call(r)')(o), '[object USBOutTransferResult]');
    });
    await test('protocol: isochronous results are split into packets that share one buffer', async () => {
        const env = await settle(makeEnv());
        const d = await opened(env);
        await d.claimInterface(0);
        const r = await d.isochronousTransferIn(3, [2, 2]);
        assert.strictEqual(r.packets.length, 2);
        assert.deepStrictEqual(Array.from(new Uint8Array(r.data.buffer)), [1, 2, 3, 4]);
        assert.strictEqual(r.packets[1].data.byteOffset, 2);
        const o = await d.isochronousTransferOut(4, new Uint8Array([1, 2, 3, 4]), [2, 2]);
        assert.deepStrictEqual(Array.from(o.packets, p => p.bytesWritten), [2, 2]);
    });
    await test('protocol: large buffers and views survive base64 chunking (no argument-count blowup, no corruption)', async () => {
        const env = await settle(makeEnv());
        const d = await opened(env);
        await d.claimInterface(0);
        const big = new Uint8Array(300000); for (let i = 0; i < big.length; i++) big[i] = (i * 31 + 7) & 0xFF;
        await d.transferOut(2, big);
        const last = () => env.calls.filter(c => c[0] === 'bulkTransferOut').pop()[3];
        assert.ok(Buffer.from(last(), 'base64').equals(Buffer.from(big)));
        const backing = new Uint8Array([9, 9, 1, 2, 3, 9]);
        await d.transferOut(2, new DataView(backing.buffer, 2, 3));
        assert.strictEqual(last(), Buffer.from([1, 2, 3]).toString('base64'));
        await d.transferOut(2, backing.buffer);
        assert.strictEqual(Buffer.from(last(), 'base64').length, 6);
        await d.transferOut(2, new Uint16Array([0x0201, 0x0403]));
        assert.strictEqual(last(), Buffer.from([1, 2, 3, 4]).toString('base64'));
    });
    await test('protocol: state machine and error texts follow Blink', async () => {
        const env = await settle(makeEnv());
        const d = (await env.run('navigator.usb.getDevices()'))[0];
        assert.strictEqual(await rejection(d.transferIn(1, 8)), 'InvalidStateError: The device must be opened first.');
        await d.open();
        assert.strictEqual(await rejection(d.transferIn(1, 8)), 'NotFoundError: The specified endpoint is not part of a claimed and selected alternate interface.');
        assert.strictEqual(await rejection(d.claimInterface(9)), 'NotFoundError: The interface number provided is not supported by the device in its current configuration.');
        assert.strictEqual(await rejection(d.selectConfiguration(9)), 'NotFoundError: The configuration value provided is not supported by the device.');
        await d.claimInterface(0);
        assert.strictEqual(await rejection(d.transferIn(0, 8)), 'IndexSizeError: The specified endpoint number is out of range.');
        assert.strictEqual(await rejection(d.selectAlternateInterface(0, 7)), 'NotFoundError: The alternate setting provided is not supported by the device in its current configuration.');
        assert.strictEqual(await rejection(d.isochronousTransferIn(1, [1])), 'InvalidAccessError: The specified endpoint is not an isochronous endpoint.');
        assert.strictEqual(await rejection(d.isochronousTransferOut(4, new Uint8Array(3), [2, 2])), 'DataError: The data buffer size must match the total packet length.');
        assert.strictEqual(await rejection(d.isochronousTransferIn(3, [4294967295, 1])), 'DataError: The total packet length exceeded the maximum size.');
        assert.strictEqual(await rejection(d.controlTransferIn({ requestType: 'vendor', recipient: 'interface', request: 1, value: 0, index: 5 }, 4)),
            'NotFoundError: The interface number provided is not supported by the device in its current configuration.');
        assert.strictEqual(await rejection(d.controlTransferIn({ requestType: 'bogus', recipient: 'device', request: 1, value: 0, index: 0 }, 4)),
            "TypeError: Failed to execute 'controlTransferIn' on 'USBDevice': Failed to read the 'requestType' property from 'USBControlTransferParameters': The provided value 'bogus' is not a valid enum value of type USBRequestType.");
        assert.strictEqual(await rejection(d.controlTransferIn({ requestType: 'vendor', recipient: 'device', request: 1, value: 0 }, 4)),
            "TypeError: Failed to execute 'controlTransferIn' on 'USBDevice': Failed to read the 'index' property from 'USBControlTransferParameters': Required member is undefined.");
        await d.close();
        assert.strictEqual(d.opened, false);
        assert.strictEqual(await rejection(d.claimInterface(0)), 'InvalidStateError: The device must be opened first.');
    });
    await test('protocol: WebIDL integer conversion is modulo, like a native [no EnforceRange] parameter', async () => {
        const env = await settle(makeEnv());
        const d = await opened(env);
        await d.claimInterface(256);   // 256 -> octet 0 (interface 0)
        assert.deepStrictEqual(env.calls.filter(c => c[0] === 'claimInterface').pop().slice(1, 3), [7, 0]);
        assert.strictEqual(await rejection(d.claimInterface(NaN)), 'resolved');                 // NaN -> 0
        assert.strictEqual(await rejection(d.claimInterface(Symbol('x'))).then(s => s.split(':')[0]), 'TypeError');
    });
    await test('protocol: overlapping device-state changes are refused with InvalidStateError', async () => {
        const env = await settle(makeEnv());
        const d = (await env.run('navigator.usb.getDevices()'))[0];
        const p1 = d.open();
        assert.strictEqual(await rejection(d.selectConfiguration(2)), 'InvalidStateError: An operation that changes the device state is in progress.');
        await p1;
    });
    await test('protocol: bridge failures map to DOMException names; raw backend text never reaches the page', async () => {
        const env = await settle(makeEnv());
        const d = (await env.run('navigator.usb.getDevices()'))[0];
        env.responses.openDevice = { success: false, error: 'SecurityError: This device is not granted to this origin' };
        assert.strictEqual(await rejection(d.open()), 'SecurityError: This device is not granted to this origin');
        env.responses.openDevice = { success: false, error: 'usb.core.USBError: [Errno 13] Access denied (insufficient permissions) /dev/bus/usb/001/007' };
        const leaked = await rejection(d.open());
        assert.strictEqual(leaked, 'SecurityError: Access denied.');
        assert.ok(!/dev\/bus|Errno|usb\.core/.test(leaked));
        env.responses.openDevice = { success: true, handle: 7 };
        await d.open();
        await d.claimInterface(0);
        env.responses.bulkTransferIn = { success: false, error: 'Invalid device handle' };
        assert.strictEqual(await rejection(d.transferIn(1, 4)), 'InvalidStateError: The device must be opened first.');
        assert.strictEqual(d.opened, false, 'a stale handle must close the JS-side device');
    });
    await test('protocol: requestDevice returns the same USBDevice object as getDevices(); a cancelled chooser is NotFoundError: No device selected.', async () => {
        const env = await settle(makeEnv());
        const first = (await env.run('navigator.usb.getDevices()'))[0];
        const got = await env.run('navigator.usb.requestDevice({filters: [{vendorId: 0x2341}]})');
        assert.strictEqual(got, first);
        env.responses.requestDeviceChooser = () => ({ cancelled: true });
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice({filters: []})'), 'NotFoundError: No device selected.');
        const call = env.calls.filter(c => c[0] === 'requestDeviceChooser').pop();
        assert.strictEqual(call[3], 'fake-gesture-token');
        assert.deepStrictEqual(JSON.parse(call[1]), { filters: [], exclusionFilters: [] });
        env.responses.requestDeviceChooser = () => ({ cancelled: true, error: 'SecurityError: The calling frame has an opaque or unknown origin and cannot request a USB device.' });
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice({filters: []})'), 'SecurityError: The calling frame has an opaque or unknown origin and cannot request a USB device.');
    });
    await test('protocol: without transient user activation requestDevice rejects with the exact Chromium SecurityError and never reaches the bridge', async () => {
        const env = await settle(makeEnv());
        env.run('navigator.userActivation.isActive = false');
        assert.strictEqual(await outcome(env, 'navigator.usb.requestDevice({filters: []})'),
            "SecurityError: Failed to execute 'requestDevice' on 'USB': Must be handling a user gesture to show a permission request.");
        assert.strictEqual(env.calls.filter(c => c[0] === 'requestDeviceChooser' || c[0] === 'mintGestureToken').length, 0);
    });

    // ============================================================ 5. events
    await test('events: connect/disconnect are re-validated per frame and dispatched as USBConnectionEvent with USBDevice objects', async () => {
        const env = await settle(makeEnv());
        env.run("window.__ev = []; navigator.usb.addEventListener('connect', function (e) { __ev.push('c:' + (e instanceof USBConnectionEvent) + ':' + (e.device instanceof USBDevice)); });" +
                "navigator.usb.addEventListener('disconnect', function (e) { __ev.push('d:' + e.device.opened); }); navigator.usb.onconnect = function () { __ev.push('h'); };");
        const dev = await opened(env);
        env.devices = [];                                                        // 抜かれた
        env.signals.deviceDisconnected.forEach(fn => fn(JSON.stringify({ vendorId: 0x2341, productId: 0x8036 })));
        await tick(60);
        assert.strictEqual(dev.opened, false, 'a disconnected device is closed');
        env.devices = [DEVICE];                                                  // 挿し直された
        env.signals.deviceConnected.forEach(fn => fn(JSON.stringify({ vendorId: 0x2341, productId: 0x8036 })));
        await tick(60);
        assert.deepStrictEqual(plain(env.run('__ev')), ['d:false', 'c:true:true', 'h']);
        const fresh = (await env.run('navigator.usb.getDevices()'))[0];
        assert.notStrictEqual(fresh, dev, 'a re-plugged device is a new USBDevice object');
    });
    await test('events: a frame without a grant gets nothing; malformed payloads are ignored', async () => {
        const env = await settle(makeEnv());
        env.run("window.__n = 0; navigator.usb.addEventListener('connect', function () { __n++; });");
        env.granted = false;
        env.signals.deviceConnected.forEach(fn => fn(JSON.stringify({ vendorId: 0x2341, productId: 0x8036 })));
        env.signals.deviceConnected.forEach(fn => fn('not json'));
        env.signals.deviceConnected.forEach(fn => fn(JSON.stringify({ vendorId: 'x' })));
        await tick(60);
        assert.strictEqual(env.run('__n'), 0);
        assert.strictEqual(env.calls.filter(c => c[0] === 'listDevices').length, 0, 'no descriptor lookup for an ungranted frame');
    });
    await test('events: on* attribute semantics (null default, non-object -> null, replaced handler, this === navigator.usb)', async () => {
        const env = await settle(makeEnv());
        assert.strictEqual(env.run('navigator.usb.onconnect'), null);
        assert.strictEqual(env.run('(function(){ navigator.usb.onconnect = 5; return navigator.usb.onconnect; })()'), null);
        env.run("window.__t = []; navigator.usb.onconnect = function (e) { __t.push('first'); }; navigator.usb.onconnect = function (e) { __t.push(this === navigator.usb ? 'second' : 'wrong-this'); };");
        env.signals.deviceConnected.forEach(fn => fn(JSON.stringify({ vendorId: 0x2341, productId: 0x8036 })));
        await tick(60);
        assert.deepStrictEqual(plain(env.run('__t')), ['second']);
    });

    // ============================================================ 6. custom commands
    await test('commands: hidden from enumeration; platform/transport/version/listGrantedDevices/explainTransferLimits/selfTest/help/locale', async () => {
        const env = await settle(makeEnv());
        assert.strictEqual(env.run("Object.keys(window).indexOf('__pysideWebUSB')"), -1);
        assert.strictEqual(env.run('typeof __pysideWebUSB.selfTest'), 'function');
        const t = await env.run('__pysideWebUSB.transport()');
        assert.deepStrictEqual(JSON.parse(JSON.stringify(t)), { kind: 'webchannel', ready: true });
        assert.strictEqual((await env.run('__pysideWebUSB.platform()')).host.os, 'linux');
        assert.strictEqual((await env.run('__pysideWebUSB.version()')).bridge, '0.0.6.post1-test');
        assert.strictEqual((await env.run('__pysideWebUSB.listGrantedDevices()'))[0].vendorId, '0x2341');
        assert.strictEqual((await env.run('__pysideWebUSB.explainTransferLimits()')).hostSafetyHardLimit, 536870912);
        const st = env.run('__pysideWebUSB.selfTest()');
        assert.strictEqual(st.ok, true, JSON.stringify(st.checks.filter(c => !c.ok)));
        assert.strictEqual(env.run('__pysideWebUSB.locale()'), 'en');
        for (const loc of ['ja', 'zh']) {
            const e2 = await settle(makeEnv({ config: { locale: loc } }));
            assert.strictEqual(e2.run('__pysideWebUSB.locale()'), loc);
            assert.ok(/listGrantedDevices/.test(e2.run('__pysideWebUSB.help()')));
        }
    });
    await test('commands: exposeCommands=false hides the namespace; nativeLookalike=false leaves Function.prototype.toString alone', async () => {
        const a = await settle(makeEnv({ config: { exposeCommands: false } }));
        assert.strictEqual(a.run("'__pysideWebUSB' in window"), false);
        const b = await settle(makeEnv({ config: { nativeLookalike: false } }));
        assert.strictEqual(b.run("Function.prototype.toString.call(navigator.usb.getDevices).indexOf('[native code]') < 0"), true);
        assert.strictEqual(b.run('__pysideWebUSB.selfTest().ok'), true);
    });
    await test('native lookalike: Function.prototype.toString is masked coherently and still rejects non-functions', async () => {
        const env = await settle(makeEnv());
        assert.strictEqual(env.run('Function.prototype.toString.call(Function.prototype.toString)'), 'function toString() { [native code] }');
        assert.strictEqual(env.run('Function.prototype.toString.toString()'), 'function toString() { [native code] }');
        assert.strictEqual(env.run('Function.prototype.toString.call(function foo() { return 1; })'), 'function foo() { return 1; }');
        assert.strictEqual(env.run("(function(){ try { Function.prototype.toString.call({}); } catch (e) { return e.name + ': ' + e.message; } })()"),
            "TypeError: Function.prototype.toString requires that 'this' be a Function");
        assert.strictEqual(env.run("Function.prototype.toString.hasOwnProperty('prototype') + ':' + Function.prototype.toString.name + ':' + Function.prototype.toString.length"), 'false:toString:0');
    });

    // ============================================================ 7. websocket client
    class FakeWebSocket {
        constructor(url) { this.url = url; this.sent = []; FakeWebSocket.instances.push(this); if (FakeWebSocket.onCreate) FakeWebSocket.onCreate(this); }
        send(data) { this.sent.push(JSON.parse(data)); if (FakeWebSocket.onSend) FakeWebSocket.onSend(this, JSON.parse(data)); }
        close() { if (this.onclose) this.onclose({}); }
        _server(msg) { if (this.onmessage) this.onmessage({ data: JSON.stringify(msg) }); }
    }
    const resetWs = () => { FakeWebSocket.instances = []; FakeWebSocket.onSend = null; FakeWebSocket.onCreate = null; };
    const wsConfig = { transport: 'websocket', ws: { host: '127.0.0.1', port: 4242, secret: 'sekret' } };
    await test('websocket: connects to ws://host:port/pyusb/<secret>, waits for hello, correlates request/response ids', async () => {
        resetWs();
        FakeWebSocket.onSend = (sock, msg) => {
            if (msg.m === 'listDevices') sock._server({ i: msg.i, r: JSON.stringify({ devices: [DEVICE] }) });
            else if (msg.m === 'isAvailable') sock._server({ i: msg.i, r: JSON.stringify({ available: true, bridgeVersion: 'ws-test' }) });
        };
        const env = await settle(makeEnv({ webSocket: FakeWebSocket, config: wsConfig }));
        const sock = FakeWebSocket.instances[0];
        assert.strictEqual(sock.url, 'ws://127.0.0.1:4242/pyusb/sekret');
        const pending = env.run('navigator.usb.getDevices()');
        await tick(30);
        assert.strictEqual(sock.sent.length, 0, 'nothing may be sent before the server said hello');
        sock._server({ hello: 1 });
        assert.strictEqual((await pending).length, 1);
        assert.deepStrictEqual(sock.sent[0].a, ['']);      // フレームトークンは常に''(サーバーが接続にオリジンを結び付ける)
        assert.strictEqual((await env.run('__pysideWebUSB.version()')).bridge, 'ws-test');
        assert.strictEqual((await env.run('__pysideWebUSB.transport()')).kind, 'websocket');
    });
    await test('websocket: server errors reject; a dropped socket fails in-flight calls with NotSupportedError; garbage frames are ignored', async () => {
        resetWs();
        FakeWebSocket.onSend = (sock, msg) => { if (msg.m === 'listDevices') sock._server({ i: msg.i, e: 'unknown method' }); };
        const env = await settle(makeEnv({ webSocket: FakeWebSocket, config: wsConfig }));
        const sock = FakeWebSocket.instances[0];
        sock._server({ hello: 1 });
        sock.onmessage({ data: 'not json' }); sock.onmessage({ data: '[1]' }); sock._server({ i: 999, r: 'x' });
        assert.strictEqual(await outcome(env, 'navigator.usb.getDevices()').then(s => s.split(':')[0]), 'NotSupportedError');
        FakeWebSocket.onSend = () => {};
        const inflight = outcome(env, 'navigator.usb.getDevices()');
        await tick(30);
        FakeWebSocket.onCreate = (s) => setTimeout(() => s.close(), 0);      // 再接続の試みはすぐ閉じる
        sock.close();
        assert.strictEqual((await inflight).split(':')[0], 'NotSupportedError');
    });
    await test('websocket: an unreachable server leaves navigator.usb in place and calls reject cleanly', async () => {
        resetWs();
        FakeWebSocket.onCreate = (s) => setTimeout(() => s.close(), 0);
        const env = await settle(makeEnv({ webSocket: FakeWebSocket, config: wsConfig }));
        assert.strictEqual((await outcome(env, 'navigator.usb.getDevices()')).split(':')[0], 'NotSupportedError');
        assert.strictEqual(env.run('navigator.usb instanceof USB'), true);
        resetWs();
    });
    await test('websocket: hotplug events pushed by the server are dispatched (after the per-frame grant check)', async () => {
        resetWs();
        FakeWebSocket.onSend = (sock, msg) => {
            if (msg.m === 'listDevices') sock._server({ i: msg.i, r: JSON.stringify({ devices: [DEVICE] }) });
            if (msg.m === 'isGrantedToThisFrame') sock._server({ i: msg.i, r: true });
        };
        const env = await settle(makeEnv({ webSocket: FakeWebSocket, config: wsConfig }));
        const sock = FakeWebSocket.instances[0]; sock._server({ hello: 1 });
        env.run("window.__c = 0; navigator.usb.addEventListener('connect', function (e) { __c += e.device.vendorId; });");
        sock._server({ ev: 'connect', d: JSON.stringify({ vendorId: 0x2341, productId: 0x8036 }) });
        await tick(80);
        assert.strictEqual(env.run('__c'), 0x2341);
    });

    // ============================================================ 8. tamper resistance
    await test('tamper: monkey-patching builtins after load cannot break or hijack the polyfill', async () => {
        const env = await settle(makeEnv());
        const boom = "function () { __hijacked++; throw new Error('hijacked'); }";
        env.run(`window.__hijacked = 0;
            var _then = Promise.prototype.then, _rApply = Reflect.apply;
            window.__thenCalls = 0;   // Node自身のawaitも(別レルムのPromiseに対して)thenを呼ぶので、これは参考値でアサートしない
            Promise.prototype.then = function () { __thenCalls++; return _rApply(_then, this, arguments); };
            JSON.parse = ${boom}; JSON.stringify = ${boom};
            var __boom = ${boom};
            var __arr = ['push','slice','indexOf','concat','map','filter','join','sort'], __str = ['charCodeAt','indexOf','slice','trim','split','replace'];
            for (var __i = 0; __i < __arr.length; __i++) Array.prototype[__arr[__i]] = __boom;
            for (var __j = 0; __j < __str.length; __j++) String.prototype[__str[__j]] = __boom;
            var __objs = ['defineProperty','create','freeze','getPrototypeOf','setPrototypeOf','getOwnPropertyDescriptor'];
            WeakMap.prototype.get = ${boom}; WeakMap.prototype.set = ${boom}; WeakMap.prototype.has = ${boom};
            Map.prototype.get = ${boom}; Map.prototype.set = ${boom}; Map.prototype.has = ${boom}; Map.prototype.delete = ${boom}; Map.prototype.forEach = ${boom};
            Promise.resolve = ${boom}; Promise.reject = ${boom};
            Function.prototype.call = ${boom}; Function.prototype.apply = ${boom}; Function.prototype.bind = ${boom};
            for (var __k = 0; __k < __objs.length; __k++) Object[__objs[__k]] = __boom;
            Object.prototype.hasOwnProperty = ${boom}; Array.prototype.forEach = ${boom};
            Reflect.apply = ${boom}; Reflect.construct = ${boom};
            String.fromCharCode = ${boom}; Uint8Array.prototype.subarray = ${boom}; Uint8Array.prototype.set = ${boom};
            Math.floor = ${boom}; Math.pow = ${boom};
            atob = ${boom}; btoa = ${boom}; Event = ${boom};`);
        const d = (await env.run('navigator.usb.getDevices()'))[0];
        await d.open(); await d.claimInterface(0);
        const r = await d.transferOut(2, new Uint8Array([1, 2, 3]));
        assert.strictEqual(r.bytesWritten, 3);
        const i = await d.transferIn(1, 3);
        assert.strictEqual(i.data.byteLength, 3);
        await d.controlTransferOut({ requestType: 'vendor', recipient: 'device', request: 1, value: 0, index: 0 }, new Uint8Array([1]));
        await d.releaseInterface(0); await d.close();
        env.run('navigator.usb.onconnect = function () {}');
        assert.strictEqual(env.run('__hijacked'), 0, 'the polyfill must only use intrinsics captured at startup');
    });
    await test('tamper: an extra guard defined by the page AFTER startup is ignored; one defined before startup is honoured (and captured once)', async () => {
        const late = await settle(makeEnv());
        late.run('window.__pysideWebUSBExtraGuard = function () { return false; }');
        assert.ok(await late.run('navigator.usb.requestDevice({filters: []})'), 'a late guard must not veto anything');
        const early = makeEnv({ deferLoad: true });
        early.run('window.__pysideWebUSBExtraGuard = function (r) { window.__seen = r.origin; return false; }');
        early.load(); await tick();
        early.run('window.__pysideWebUSBExtraGuard = function () { return true; }');   // 後から差し替えても効かない
        assert.strictEqual((await outcome(early, 'navigator.usb.requestDevice({filters: [{vendorId: 1}]})')).split(':')[0], 'SecurityError');
        assert.strictEqual(early.calls.filter(c => c[0] === 'requestDeviceChooser').length, 0);
    });
    await test('tamper: nothing internal leaks - no own properties on devices/results/configurations, and the polyfill adds only the WebUSB classes and the hidden command object to window', async () => {
        const env = makeEnv({ deferLoad: true });
        const before = new Set(env.run('Object.getOwnPropertyNames(window)'));
        env.load(); await tick();
        const after = env.run('Object.getOwnPropertyNames(window)');
        const added = plain(after.filter(k => !before.has(k)).sort());
        assert.deepStrictEqual(added, ['USB', 'USBAlternateInterface', 'USBConfiguration', 'USBConnectionEvent', 'USBDevice', 'USBEndpoint',
            'USBInTransferResult', 'USBInterface', 'USBIsochronousInTransferPacket', 'USBIsochronousInTransferResult', 'USBIsochronousOutTransferPacket',
            'USBIsochronousOutTransferResult', 'USBOutTransferResult', '__pysideWebUSB']);
        const d = await opened(env);
        await d.claimInterface(0);
        const r = await d.transferIn(1, 3);
        const ownKeys = env.run('(o) => Object.getOwnPropertyNames(o).length + Object.getOwnPropertySymbols(o).length');
        assert.strictEqual(ownKeys(d), 0);
        assert.strictEqual(ownKeys(r), 0);
        assert.strictEqual(ownKeys(d.configuration), 0);
        assert.strictEqual(ownKeys(d.configuration.interfaces[0].alternate.endpoints[0]), 0);
        // (テスト用サンドボックスが自前で持つQWebChannelモックは除外する)
        assert.strictEqual(env.run('Object.keys(window).filter(function (k) { return /usb|Frame/i.test(k); }).length'), 0);
    });

    console.log('\n' + passed + ' passed, ' + failures.length + ' failed');
    if (failures.length) { console.log('failed: ' + failures.join(' | ')); process.exit(1); }
    process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
