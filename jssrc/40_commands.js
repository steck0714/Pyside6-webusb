/* ==========================================================================
 * part 40 :: custom commands, self test, native-looking toString()
 * ========================================================================== */

/* ---- Function.prototype.toString masking ------------------------------------
 * Every function this polyfill creates reports "function name() { [native code] }".
 * Function.prototype.toString itself is wrapped in a Proxy so that it, too, prints as
 * native code, keeps its name/length and has no `prototype` property.
 * ------------------------------------------------------------------------- */
if (CONFIG.nativeLookalike) {
    var patchedToString = new Proxy(origFnToString, {
        apply: function (target, thisArg, argList) {
            if (isObjectLike(thisArg) && wmHas(nativeText, thisArg)) return wmGet(nativeText, thisArg);
            return reflectApply(target, thisArg, argList);
        }
    });
    wmSet(nativeText, patchedToString, nativeSource('toString'));
    defineProperty(Function.prototype, 'toString', {
        value: patchedToString, writable: true, enumerable: false, configurable: true
    });
}

/* ---- localisation of the console helper texts -------------------------------- */
var STRINGS = {
    en: {
        transferLimits: function (l) {
            return '[pyside6-webusb] Transfer size policy: transfers up to ' + l.hostSafetyHardLimit +
                ' bytes are allowed here. Real Chrome would reject anything over ' + l.chromeCompatibleWarnThreshold +
                ' bytes with DataError -- this implementation instead logs a console.warn() on that specific transfer ' +
                'and lets it proceed, since it is intentionally not a drop-in Chrome clone but a WebUSB-compatible ' +
                'implementation with its own, more permissive extensions. See the pyside6-webusb README/CHANGELOG (v0.0.4b2) for the full reasoning.';
        },
        help: '[pyside6-webusb] Available __pysideWebUSB commands: listGrantedDevices() - devices already granted to this origin; ' +
            "bridgeInfo() - this bridge's own version/backend/acceleration status; explainTransferLimits() - this implementation's " +
            'transfer size policy vs real Chrome; locale() - the language of this debug output; platform() - host OS / architecture / ' +
            'capability summary; transport() - how this page reaches Python (webchannel or websocket); version() - polyfill and ' +
            'bridge versions; diagnose() - environment report (libusb, permissions hints); selfTest() - checks that the WebUSB ' +
            'interfaces look and behave like a native browser.',
        selfTestDone: function (ok, total) { return '[pyside6-webusb] selfTest: ' + ok + '/' + total + ' checks passed.'; }
    },
    ja: {
        transferLimits: function (l) {
            return '[pyside6-webusb] 転送サイズの方針: ここでは ' + l.hostSafetyHardLimit + ' バイトまでの転送を許可しています。' +
                '実際のChromeなら ' + l.chromeCompatibleWarnThreshold + ' バイトを超えるとDataErrorで拒否しますが、この実装ではその転送に' +
                '対してconsole.warn()を出すだけで処理は継続します——これはChromeの完全な代替品を目指したものではなく、より寛容な独自拡張を持つ' +
                'WebUSB互換の実装だからです。詳しい理由はpyside6-webusbのREADME/CHANGELOG(v0.0.4b2)を参照してください。';
        },
        help: '[pyside6-webusb] __pysideWebUSBで使えるコマンド: listGrantedDevices() - このオリジンに既に許可済みのデバイス一覧 / ' +
            'bridgeInfo() - このブリッジ自身のバージョン・バックエンド・アクセラレーション状況 / explainTransferLimits() - この実装の' +
            '転送サイズ方針と実Chromeとの違い / locale() - このデバッグ出力の言語 / platform() - ホストOS・アーキテクチャ・機能の概要 / ' +
            'transport() - このページがPythonへ到達する方式(webchannelかwebsocket) / version() - ポリフィルとブリッジのバージョン / ' +
            'diagnose() - 環境レポート(libusb・権限のヒント) / selfTest() - WebUSBの各インターフェースがネイティブのブラウザと同じ見た目・' +
            '挙動かを確認します。',
        selfTestDone: function (ok, total) { return '[pyside6-webusb] selfTest: ' + total + ' 件中 ' + ok + ' 件が合格しました。'; }
    },
    zh: {
        transferLimits: function (l) {
            return '[pyside6-webusb] 传输大小策略: 此处允许最多 ' + l.hostSafetyHardLimit + ' 字节的传输。真正的 Chrome 会对超过 ' +
                l.chromeCompatibleWarnThreshold + ' 字节的传输以 DataError 拒绝,而本实现只会针对该次传输输出 console.warn() 并允许其继续——' +
                '因为本实现并非要成为 Chrome 的完全替代品,而是一个带有更宽松扩展的 WebUSB 兼容实现。完整原因请参阅 pyside6-webusb 的 README/CHANGELOG(v0.0.4b2)。';
        },
        help: '[pyside6-webusb] __pysideWebUSB 可用命令: listGrantedDevices() - 列出已授权给此来源的设备 / bridgeInfo() - 本桥接自身的版本/后端/加速状态 / ' +
            'explainTransferLimits() - 本实现的传输大小策略与真实 Chrome 的差异 / locale() - 此调试输出的语言 / platform() - 主机操作系统、架构与功能概要 / ' +
            'transport() - 此页面访问 Python 的方式(webchannel 或 websocket) / version() - polyfill 与桥接版本 / diagnose() - 环境报告(libusb、权限提示) / ' +
            'selfTest() - 检查 WebUSB 各接口的外观与行为是否与原生浏览器一致。',
        selfTestDone: function (ok, total) { return '[pyside6-webusb] selfTest: ' + total + ' 项中 ' + ok + ' 项通过。'; }
    }
};
function strings() { return STRINGS[CONFIG.locale] || STRINGS.en; }

/* ---- selfTest ----------------------------------------------------------------- */
function runSelfTest() {
    var checks = [];
    function check(name, fn) {
        var ok = false, detail = '';
        try { var r = fn(); ok = (r === true); if (!ok) detail = StringC(r); } catch (e) { detail = 'threw ' + (e && e.name) + ': ' + (e && e.message); }
        arrayPush(checks, { name: name, ok: ok, detail: detail });
    }
    var protoDesc = getOwnPropertyDescriptor(Navigator.prototype, 'usb');
    check('navigator.usb is a USB instance', function () { return nav.usb instanceof USB && nav.usb.constructor === USB; });
    check('Object.prototype.toString gives [object USB]', function () { return objectToString(nav.usb) === '[object USB]'; });
    check('navigator.usb is not an own property of navigator', function () { return !hasOwn(nav, 'usb'); });
    check('Navigator.prototype.usb is a getter-only accessor', function () {
        return !!protoDesc && typeof protoDesc.get === 'function' && protoDesc.set === undefined && protoDesc.enumerable === true;
    });
    check('delete navigator.usb does not remove it', function () {
        var before = nav.usb, r = (delete nav.usb);
        return r === true && nav.usb === before;
    });
    check('property lock matches the configured policy', function () { return !!protoDesc && protoDesc.configurable === !CONFIG.lockNavigatorUsb; });
    check('all WebUSB interface objects exist on window', function () {
        for (var i = 0; i < EXPORTED.length; i++) if (win[EXPORTED[i][0]] !== EXPORTED[i][1]) return EXPORTED[i][0] + ' missing or replaced';
        return true;
    });
    check('Symbol.toStringTag values are correct', function () {
        for (var i = 0; i < EXPORTED.length; i++) if (EXPORTED[i][1].prototype[symToStringTag] !== EXPORTED[i][0]) return EXPORTED[i][0];
        return true;
    });
    check('USB and USBDevice have illegal constructors', function () {
        try { new USB(); return 'USB constructible'; } catch (e) { if (!(e instanceof TypeErrorC) || e.message !== "Failed to construct 'USB': Illegal constructor") return e.message; }
        try { new USBDevice(); return 'USBDevice constructible'; } catch (e2) { if (!(e2 instanceof TypeErrorC) || e2.message !== "Failed to construct 'USBDevice': Illegal constructor") return e2.message; }
        try { USB(); return 'USB callable'; } catch (e3) { if (!(e3 instanceof TypeErrorC) || e3.message !== 'Illegal constructor') return e3.message; }
        return true;
    });
    check('methods have no prototype and are not constructors', function () {
        var m = nav.usb.getDevices;
        if (hasOwn(m, 'prototype')) return 'has prototype';
        try { new m(); return 'constructible'; } catch (e) { return e instanceof TypeErrorC; }
    });
    check('brand checks reject foreign receivers', function () {
        try { reflectApply(protoDesc.get, {}, []); return 'getter accepted {}'; } catch (e) { return e instanceof TypeErrorC && e.message === 'Illegal invocation'; }
    });
    if (CONFIG.nativeLookalike) {
        check('functions print as native code', function () {
            var f = Function.prototype.toString;
            return reflectApply(f, nav.usb.getDevices, []) === 'function getDevices() { [native code] }' &&
                   reflectApply(f, USB, []) === 'function USB() { [native code] }' &&
                   reflectApply(f, f, []) === 'function toString() { [native code] }';
        });
    }
    var okCount = 0;
    for (var i = 0; i < checks.length; i++) if (checks[i].ok) okCount++;
    return { ok: okCount === checks.length, passed: okCount, total: checks.length, checks: checks };
}

/* ---- command object ------------------------------------------------------------- */
function jsPlatformHint() {
    var uaData = nav.userAgentData;
    return { userAgent: StringC(nav.userAgent), platform: StringC(nav.platform || (uaData && uaData.platform) || '') };
}
var commands = {
    listGrantedDevices: function () {
        return promiseThen(nav.usb.getDevices(), function (devices) {
            var rows = [];
            for (var i = 0; i < devices.length; i++) {
                var d = devices[i];
                arrayPush(rows, {
                    vendorId: '0x' + d.vendorId.toString(16), productId: '0x' + d.productId.toString(16),
                    productName: d.productName, manufacturerName: d.manufacturerName,
                    serialNumber: d.serialNumber, opened: d.opened
                });
            }
            try { if (consoleRef && consoleRef.table) reflectApply(consoleRef.table, consoleRef, [rows]); } catch (e) { /* ignore */ }
            return rows;
        });
    },
    bridgeInfo: function () {
        return promiseThen(callJson('isAvailable', []), function (res) { logInfo('[pyside6-webusb] bridge info:', res); return res; });
    },
    explainTransferLimits: function () {
        return promiseThen(callJson('isAvailable', []), function (res) {
            var limits = (res && res.transferLimits) || {};
            logInfo(strings().transferLimits(limits));
            return limits;
        });
    },
    locale: function () { return CONFIG.locale; },
    help: function () { var msg = strings().help; logInfo(msg); return msg; },
    platform: function () {
        return promiseThen(callJson('isAvailable', []), function (res) {
            var out = { host: (res && res.platform) || null, capabilities: (res && res.capabilities) || null, page: jsPlatformHint() };
            logInfo('[pyside6-webusb] platform:', out);
            return out;
        });
    },
    transport: function () {
        return promiseThen(transport.ready, function (ready) { return { kind: transport.kind, ready: ready === true }; });
    },
    version: function () {
        return promiseThen(callJson('isAvailable', []), function (res) {
            return { polyfill: CONFIG.version, bridge: (res && res.bridgeVersion) || null };
        });
    },
    diagnose: function () {
        return promiseThen(callJson('getDiagnostics', []), function (res) { logInfo('[pyside6-webusb] diagnostics:', res); return res; });
    },
    selfTest: function () {
        var r = runSelfTest();
        try { if (consoleRef && consoleRef.table) reflectApply(consoleRef.table, consoleRef, [r.checks]); } catch (e) { /* ignore */ }
        logInfo(strings().selfTestDone(r.passed, r.total));
        return r;
    }
};
(function () {
    var names = ['listGrantedDevices', 'bridgeInfo', 'explainTransferLimits', 'locale', 'help', 'platform', 'transport', 'version', 'diagnose', 'selfTest'];
    for (var i = 0; i < names.length; i++) {
        var fn = commands[names[i]];
        defineProperty(fn, 'name', { value: names[i], configurable: true });
        if (CONFIG.nativeLookalike) maskFunction(fn, nativeSource(names[i]));
    }
})();
if (CONFIG.exposeCommands && !hasOwn(win, '__pysideWebUSB')) {
    /* non-enumerable: invisible to Object.keys(window) / for-in, still reachable by name from the console */
    defineProperty(win, '__pysideWebUSB', { value: commands, writable: true, enumerable: false, configurable: true });
}
