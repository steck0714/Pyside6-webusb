/* ==========================================================================
 * part 30 :: WebUSB object model
 * ========================================================================== */

var stringTrim = uncurryThis(String.prototype.trim);

var K_OPEN_REQUIRED = 'The device must be opened first.';
var K_DISCONNECTED = 'The device was disconnected.';
var K_DEVICE_CHANGING = 'An operation that changes the device state is in progress.';
var K_IFACE_CHANGING = 'An operation that changes interface state is in progress.';
var K_IFACE_NOT_FOUND = 'The interface number provided is not supported by the device in its current configuration.';
var K_ALT_NOT_FOUND = 'The alternate setting provided is not supported by the device in its current configuration.';
var K_NO_CONFIG = 'The device must have a configuration selected.';
var K_IFACE_NOT_CLAIMED = 'The specified interface has not been claimed.';
var K_EP_RANGE = 'The specified endpoint number is out of range.';
var K_EP_NOT_AVAILABLE = 'The specified endpoint is not part of a claimed and selected alternate interface.';
var K_PACKETS_TOO_BIG = 'The total packet length exceeded the maximum size.';
var K_BUFFER_MISMATCH = 'The data buffer size must match the total packet length.';

var usbSlots = new WeakMapC(), deviceSlots = new WeakMapC(), configSlots = new WeakMapC(),
    ifaceSlots = new WeakMapC(), altSlots = new WeakMapC(), endpointSlots = new WeakMapC(),
    eventSlots = new WeakMapC(), inResultSlots = new WeakMapC(), outResultSlots = new WeakMapC(),
    isoInPacketSlots = new WeakMapC(), isoInResultSlots = new WeakMapC(),
    isoOutPacketSlots = new WeakMapC(), isoOutResultSlots = new WeakMapC();

function ctorGuard(iface, skip, newTarget, given, required) {
    if (!newTarget) throw makeTypeError(failedConstruct(iface, NEW_OPERATOR_MSG), skip);
    if (given < required) throw makeTypeError(failedConstruct(iface, notEnoughArgs(required, given)), skip);
}
function ctorConvert(iface, fn, skip) {
    try { return fn(); } catch (e) {
        if (e && getPrototypeOf(e) === TypeErrorC.prototype) throw makeTypeError(failedConstruct(iface, e.message), skip);
        throw e;
    }
}
function convertArg(iface, method, fn, skip) {
    try { return fn(); } catch (e) {
        if (e && getPrototypeOf(e) === TypeErrorC.prototype) throw makeTypeError(failedExecute(iface, method, e.message), skip);
        throw e;
    }
}
function needArgs(args, n, iface, method, skip) {
    if (args.length < n) throw makeTypeError(failedExecute(iface, method, notEnoughArgs(n, args.length)), skip);
}
function freezeCopy(arr) { return objectFreeze(arraySlice(arr, 0)); }

/* ---- descriptor info normalisation (data comes from the trusted bridge) ------ */
function toInt(v) { return (typeof v === 'number' && v === v) ? v : 0; }
function toStrOrNull(v) { return (typeof v === 'string') ? v : null; }
function normalizeEndpoint(e) {
    e = e || {};
    return {
        endpointNumber: toInt(e.endpointNumber),
        direction: e.direction === 'out' ? 'out' : 'in',
        type: (e.type === 'interrupt' || e.type === 'isochronous') ? e.type : 'bulk',
        packetSize: toInt(e.packetSize)
    };
}
function normalizeAlternate(a) {
    a = a || {};
    var eps = [], src = arrayIsArray(a.endpoints) ? a.endpoints : [];
    for (var i = 0; i < src.length; i++) arrayPush(eps, normalizeEndpoint(src[i]));
    return {
        alternateSetting: toInt(a.alternateSetting), interfaceClass: toInt(a.interfaceClass),
        interfaceSubclass: toInt(a.interfaceSubclass), interfaceProtocol: toInt(a.interfaceProtocol),
        interfaceName: toStrOrNull(a.interfaceName), endpoints: eps
    };
}
function normalizeInterface(f) {
    f = f || {};
    var alts = [], src = arrayIsArray(f.alternates) ? f.alternates : [];
    for (var i = 0; i < src.length; i++) arrayPush(alts, normalizeAlternate(src[i]));
    if (!alts.length) arrayPush(alts, normalizeAlternate({ alternateSetting: 0 }));
    return { interfaceNumber: toInt(f.interfaceNumber), alternates: alts };
}
function normalizeConfiguration(c) {
    c = c || {};
    var ifs = [], src = arrayIsArray(c.interfaces) ? c.interfaces : [];
    for (var i = 0; i < src.length; i++) arrayPush(ifs, normalizeInterface(src[i]));
    return { configurationValue: toInt(c.configurationValue), configurationName: toStrOrNull(c.configurationName), interfaces: ifs };
}
function normalizeInfo(raw) {
    raw = raw || {};
    var cfgs = [], src = arrayIsArray(raw.configurations) ? raw.configurations : [];
    for (var i = 0; i < src.length; i++) arrayPush(cfgs, normalizeConfiguration(src[i]));
    return {
        vendorId: toInt(raw.vendorId), productId: toInt(raw.productId),
        productName: toStrOrNull(raw.productName), manufacturerName: toStrOrNull(raw.manufacturerName),
        serialNumber: toStrOrNull(raw.serialNumber),
        deviceClass: toInt(raw.deviceClass), deviceSubclass: toInt(raw.deviceSubclass), deviceProtocol: toInt(raw.deviceProtocol),
        usbVersionMajor: toInt(raw.usbVersionMajor), usbVersionMinor: toInt(raw.usbVersionMinor), usbVersionSubminor: toInt(raw.usbVersionSubminor),
        deviceVersionMajor: toInt(raw.deviceVersionMajor), deviceVersionMinor: toInt(raw.deviceVersionMinor), deviceVersionSubminor: toInt(raw.deviceVersionSubminor),
        configurations: cfgs,
        activeConfigurationValue: (typeof raw.activeConfigurationValue === 'number') ? raw.activeConfigurationValue : null
    };
}
function findConfigIndex(info, value) {
    for (var i = 0; i < info.configurations.length; i++) if (info.configurations[i].configurationValue === value) return i;
    return -1;
}

/* ---- per-device mutable state ----------------------------------------------- */
function makeDeviceState(info, key) {
    var ds = {
        info: info, key: key, handle: null, opened: false, disconnected: false,
        activeConfigIndex: -1, claimed: objectCreate(null), alt: objectCreate(null),
        changing: false, ifaceChanging: objectCreate(null), configs: null
    };
    var idx = -1;
    if (info.activeConfigurationValue !== null) idx = findConfigIndex(info, info.activeConfigurationValue);
    if (idx < 0 && info.configurations.length) idx = 0;   /* legacy: assume the first configuration */
    ds.activeConfigIndex = idx;
    return ds;
}
function resetInterfaceState(ds) {
    ds.claimed = objectCreate(null); ds.alt = objectCreate(null); ds.ifaceChanging = objectCreate(null);
}
function markClosed(ds) { ds.opened = false; ds.handle = null; ds.changing = false; resetInterfaceState(ds); }
function markDisconnected(ds) { ds.disconnected = true; markClosed(ds); }
function findInterfaceIndex(ds, number) {
    if (ds.activeConfigIndex < 0) return -1;
    var ifs = ds.info.configurations[ds.activeConfigIndex].interfaces;
    for (var i = 0; i < ifs.length; i++) if (ifs[i].interfaceNumber === number) return i;
    return -1;
}
function selectedAlternateIndex(iface, setting) {
    /* A freshly claimed interface is in alternate setting 0 (USB spec), which is not necessarily
     * the first entry of the descriptor list; fall back to the first entry only if there is none. */
    var want = (setting === undefined) ? 0 : setting;
    for (var i = 0; i < iface.alternates.length; i++) if (iface.alternates[i].alternateSetting === want) return i;
    return 0;
}
function anyInterfaceChanging(ds) {
    for (var k in ds.ifaceChanging) if (ds.ifaceChanging[k] === true) return true;
    return false;
}
function ensureNoDeviceChange(ds) {
    if (ds.disconnected) throw makeDOMException(K_DISCONNECTED, 'NotFoundError');
    if (ds.changing) throw makeDOMException(K_DEVICE_CHANGING, 'InvalidStateError');
}
function ensureNoDeviceOrInterfaceChange(ds) {
    ensureNoDeviceChange(ds);
    if (anyInterfaceChanging(ds)) throw makeDOMException(K_IFACE_CHANGING, 'InvalidStateError');
}
function ensureConfigured(ds) {
    ensureNoDeviceChange(ds);
    if (!ds.opened) throw makeDOMException(K_OPEN_REQUIRED, 'InvalidStateError');
    if (ds.activeConfigIndex < 0) throw makeDOMException(K_NO_CONFIG, 'InvalidStateError');
}
function ensureInterfaceClaimed(ds, number) {
    ensureConfigured(ds);
    var idx = findInterfaceIndex(ds, number);
    if (idx < 0) throw makeDOMException(K_IFACE_NOT_FOUND, 'NotFoundError');
    if (ds.ifaceChanging[number] === true) throw makeDOMException(K_IFACE_CHANGING, 'InvalidStateError');
    if (ds.claimed[number] !== true) throw makeDOMException(K_IFACE_NOT_CLAIMED, 'InvalidStateError');
    return idx;
}
/* endpoints of every claimed interface's currently selected alternate */
function availableEndpoint(ds, inTransfer, number) {
    if (ds.activeConfigIndex < 0) return null;
    var ifs = ds.info.configurations[ds.activeConfigIndex].interfaces;
    for (var i = 0; i < ifs.length; i++) {
        var iface = ifs[i];
        if (ds.claimed[iface.interfaceNumber] !== true || ds.ifaceChanging[iface.interfaceNumber] === true) continue;
        var alt = iface.alternates[selectedAlternateIndex(iface, ds.alt[iface.interfaceNumber])];
        for (var j = 0; j < alt.endpoints.length; j++) {
            var e = alt.endpoints[j];
            if (e.endpointNumber === number && (e.direction === 'in') === inTransfer) return e;
        }
    }
    return null;
}
function ensureEndpointAvailable(ds, inTransfer, number) {
    ensureConfigured(ds);
    if (number === 0 || number >= 16) throw makeDOMException(K_EP_RANGE, 'IndexSizeError');
    var ep = availableEndpoint(ds, inTransfer, number);
    if (!ep) throw makeDOMException(K_EP_NOT_AVAILABLE, 'NotFoundError');
    return ep;
}

/* ---- bridge helpers ---------------------------------------------------------- */
var KNOWN_ERROR_NAMES = ['SecurityError', 'InvalidStateError', 'NotFoundError', 'InvalidAccessError', 'IndexSizeError',
                         'DataError', 'NotSupportedError', 'NetworkError', 'AbortError', 'TimeoutError'];
function transportError(err) {
    /* connection level failures become the DOMException a native browser uses for "no such service" */
    if (err && getPrototypeOf(err) === ErrorC.prototype) {
        return new DOMExceptionC('The implementation did not support the requested type of object or operation.', 'NotSupportedError');
    }
    return err;
}
function callRawChecked(method, args) {
    return promiseThen(transport.callRaw(method, args), undefined, function (err) { throw transportError(err); });
}
function callJson(method, args) {
    return promiseThen(callRawChecked(method, args), function (res) {
        if (typeof res === 'string') {
            try { return jsonParse(res); } catch (e) { return { success: false, error: 'invalid bridge response' }; }
        }
        return res;
    });
}
function throwBridge(ds, res, defaultName, nativeMessage) {
    var msg = (res && typeof res.error === 'string') ? res.error : '';
    if (msg === 'Invalid device handle' && ds) {
        markClosed(ds);
        throw makeDOMException(K_OPEN_REQUIRED, 'InvalidStateError');
    }
    if (stringIndexOf(msg, 'TypeError:') === 0) throw new TypeErrorC(stringTrim(stringSlice(msg, 10)));
    for (var i = 0; i < KNOWN_ERROR_NAMES.length; i++) {
        var p = KNOWN_ERROR_NAMES[i] + ':';
        if (stringIndexOf(msg, p) === 0) throw new DOMExceptionC(stringTrim(stringSlice(msg, p.length)), KNOWN_ERROR_NAMES[i]);
    }
    if (msg) logDebug(msg);   /* raw backend text is kept out of the page-visible error */
    throw new DOMExceptionC(nativeMessage, defaultName);
}
function checkOk(ds, res, defaultName, nativeMessage) {
    if (!res || res.success !== true) throwBridge(ds, res, defaultName, nativeMessage);
}
function warnIfNeeded(res) { if (res && typeof res.warning === 'string') logWarn(res.warning); }
function withDeviceChange(ds, promise, onOk) {
    ds.changing = true;
    return promiseThen(promise, function (v) { ds.changing = false; return onOk(v); },
                                function (e) { ds.changing = false; throw e; });
}
function withInterfaceChange(ds, number, promise, onOk) {
    ds.ifaceChanging[number] = true;
    return promiseThen(promise, function (v) { delete ds.ifaceChanging[number]; return onOk(v); },
                                function (e) { delete ds.ifaceChanging[number]; throw e; });
}
function statusOf(res) { return res && res.status === 'stall' ? 'stall' : (res && res.status === 'babble' ? 'babble' : 'ok'); }

/* ==========================================================================
 * transfer result interfaces (public constructors, like Chromium)
 * ========================================================================== */
function USBInTransferResult(status, data = undefined) {
    ctorGuard('USBInTransferResult', USBInTransferResult, new.target, arguments.length, 1);
    var st = ctorConvert('USBInTransferResult', function () { return cvtTransferStatus(status); }, USBInTransferResult);
    var dv = null;
    if (data !== undefined && data !== null) {
        if (!isDataView(data)) throw makeTypeError(failedConstruct('USBInTransferResult', "parameter 2 is not of type 'DataView'."), USBInTransferResult);
        dv = data;
    }
    var self = objectCreate(new.target.prototype);
    wmSet(inResultSlots, self, { status: st, data: dv });
    return self;
}
function USBOutTransferResult(status, bytesWritten = 0) {
    ctorGuard('USBOutTransferResult', USBOutTransferResult, new.target, arguments.length, 1);
    var st = ctorConvert('USBOutTransferResult', function () { return cvtTransferStatus(status); }, USBOutTransferResult);
    var n = ctorConvert('USBOutTransferResult', function () { return cvtULong(bytesWritten); }, USBOutTransferResult);
    var self = objectCreate(new.target.prototype);
    wmSet(outResultSlots, self, { status: st, bytesWritten: n });
    return self;
}
function USBIsochronousInTransferPacket(status, data = undefined) {
    ctorGuard('USBIsochronousInTransferPacket', USBIsochronousInTransferPacket, new.target, arguments.length, 1);
    var st = ctorConvert('USBIsochronousInTransferPacket', function () { return cvtTransferStatus(status); }, USBIsochronousInTransferPacket);
    var dv = null;
    if (data !== undefined && data !== null) {
        if (!isDataView(data)) throw makeTypeError(failedConstruct('USBIsochronousInTransferPacket', "parameter 2 is not of type 'DataView'."), USBIsochronousInTransferPacket);
        dv = data;
    }
    var self = objectCreate(new.target.prototype);
    wmSet(isoInPacketSlots, self, { status: st, data: dv });
    return self;
}
function USBIsochronousInTransferResult(packets, data = undefined) {
    ctorGuard('USBIsochronousInTransferResult', USBIsochronousInTransferResult, new.target, arguments.length, 1);
    var list = ctorConvert('USBIsochronousInTransferResult', function () {
        return cvtSequence(packets, function (p) {
            if (!wmHas(isoInPacketSlots, p)) throw new TypeErrorC("The provided value is not of type 'USBIsochronousInTransferPacket'.");
            return p;
        });
    }, USBIsochronousInTransferResult);
    var dv = null;
    if (data !== undefined && data !== null) {
        if (!isDataView(data)) throw makeTypeError(failedConstruct('USBIsochronousInTransferResult', "parameter 2 is not of type 'DataView'."), USBIsochronousInTransferResult);
        dv = data;
    }
    var self = objectCreate(new.target.prototype);
    wmSet(isoInResultSlots, self, { packets: objectFreeze(list), data: dv });
    return self;
}
function USBIsochronousOutTransferPacket(status, bytesWritten = 0) {
    ctorGuard('USBIsochronousOutTransferPacket', USBIsochronousOutTransferPacket, new.target, arguments.length, 1);
    var st = ctorConvert('USBIsochronousOutTransferPacket', function () { return cvtTransferStatus(status); }, USBIsochronousOutTransferPacket);
    var n = ctorConvert('USBIsochronousOutTransferPacket', function () { return cvtULong(bytesWritten); }, USBIsochronousOutTransferPacket);
    var self = objectCreate(new.target.prototype);
    wmSet(isoOutPacketSlots, self, { status: st, bytesWritten: n });
    return self;
}
function USBIsochronousOutTransferResult(packets) {
    ctorGuard('USBIsochronousOutTransferResult', USBIsochronousOutTransferResult, new.target, arguments.length, 1);
    var list = ctorConvert('USBIsochronousOutTransferResult', function () {
        return cvtSequence(packets, function (p) {
            if (!wmHas(isoOutPacketSlots, p)) throw new TypeErrorC("The provided value is not of type 'USBIsochronousOutTransferPacket'.");
            return p;
        });
    }, USBIsochronousOutTransferResult);
    var self = objectCreate(new.target.prototype);
    wmSet(isoOutResultSlots, self, { packets: objectFreeze(list) });
    return self;
}
function slotGetter(map, key) { return function (self) { return wmGet(map, self)[key]; }; }
function brandOf(map) { return function (v) { return wmHas(map, v); }; }
function attrs(map, names) {
    var m = {}, brand = brandOf(map);
    for (var i = 0; i < names.length; i++) m[names[i]] = makeAttribute(brand, names[i], slotGetter(map, names[i]));
    return m;
}
function simpleInterface(Ctor, tag, map, names) {
    var m = attrs(map, names);
    assembleInterface(Ctor, tag, null, null, m, names.concat(['constructor']));
}
simpleInterface(USBInTransferResult, 'USBInTransferResult', inResultSlots, ['data', 'status']);
simpleInterface(USBOutTransferResult, 'USBOutTransferResult', outResultSlots, ['bytesWritten', 'status']);
simpleInterface(USBIsochronousInTransferPacket, 'USBIsochronousInTransferPacket', isoInPacketSlots, ['status', 'data']);
simpleInterface(USBIsochronousInTransferResult, 'USBIsochronousInTransferResult', isoInResultSlots, ['data', 'packets']);
simpleInterface(USBIsochronousOutTransferPacket, 'USBIsochronousOutTransferPacket', isoOutPacketSlots, ['bytesWritten', 'status']);
simpleInterface(USBIsochronousOutTransferResult, 'USBIsochronousOutTransferResult', isoOutResultSlots, ['packets']);

/* ==========================================================================
 * descriptor graph: USBConfiguration > USBInterface > USBAlternateInterface > USBEndpoint
 * ========================================================================== */
function isClaimed(ds, cfgIndex, number) { return ds.claimed[number] === true && ds.activeConfigIndex === cfgIndex; }

function buildEndpoint(ds, c, f, a, e, proto) {
    var obj = objectCreate(proto || USBEndpoint.prototype);
    wmSet(endpointSlots, obj, { ds: ds, c: c, f: f, a: a, e: e, node: ds.info.configurations[c].interfaces[f].alternates[a].endpoints[e] });
    return obj;
}
function buildAlternate(ds, c, f, a, proto) {
    var obj = objectCreate(proto || USBAlternateInterface.prototype);
    var node = ds.info.configurations[c].interfaces[f].alternates[a];
    var eps = [];
    for (var i = 0; i < node.endpoints.length; i++) arrayPush(eps, buildEndpoint(ds, c, f, a, i));
    wmSet(altSlots, obj, { ds: ds, c: c, f: f, a: a, node: node, endpoints: objectFreeze(eps) });
    return obj;
}
function buildInterface(ds, c, f, proto) {
    var obj = objectCreate(proto || USBInterface.prototype);
    var node = ds.info.configurations[c].interfaces[f];
    var alts = [];
    for (var i = 0; i < node.alternates.length; i++) arrayPush(alts, buildAlternate(ds, c, f, i));
    wmSet(ifaceSlots, obj, { ds: ds, c: c, f: f, node: node, alternates: objectFreeze(alts) });
    return obj;
}
function buildConfiguration(ds, c, proto) {
    var obj = objectCreate(proto || USBConfiguration.prototype);
    var node = ds.info.configurations[c];
    var ifs = [];
    for (var i = 0; i < node.interfaces.length; i++) arrayPush(ifs, buildInterface(ds, c, i));
    wmSet(configSlots, obj, { ds: ds, c: c, node: node, interfaces: objectFreeze(ifs) });
    return obj;
}
function getConfigs(ds) {
    if (ds.configs === null) {
        var arr = [];
        for (var i = 0; i < ds.info.configurations.length; i++) arrayPush(arr, buildConfiguration(ds, i));
        ds.configs = objectFreeze(arr);
    }
    return ds.configs;
}

function USBConfiguration(device, configurationValue) {
    ctorGuard('USBConfiguration', USBConfiguration, new.target, arguments.length, 2);
    var ds = wmGet(deviceSlots, device);
    if (!ds) throw makeTypeError(failedConstruct('USBConfiguration', "parameter 1 is not of type 'USBDevice'."), USBConfiguration);
    var value = ctorConvert('USBConfiguration', function () { return cvtOctet(configurationValue); }, USBConfiguration);
    var idx = findConfigIndex(ds.info, value);
    if (idx < 0) throw new RangeErrorC(failedConstruct('USBConfiguration', 'Invalid configuration value.'));
    return buildConfiguration(ds, idx, new.target.prototype);
}
function USBInterface(configuration, interfaceNumber) {
    ctorGuard('USBInterface', USBInterface, new.target, arguments.length, 2);
    var cs = wmGet(configSlots, configuration);
    if (!cs) throw makeTypeError(failedConstruct('USBInterface', "parameter 1 is not of type 'USBConfiguration'."), USBInterface);
    var number = ctorConvert('USBInterface', function () { return cvtOctet(interfaceNumber); }, USBInterface);
    var ifs = cs.node.interfaces;
    for (var i = 0; i < ifs.length; i++) {
        if (ifs[i].interfaceNumber === number) return buildInterface(cs.ds, cs.c, i, new.target.prototype);
    }
    throw new RangeErrorC(failedConstruct('USBInterface', 'Invalid interface index.'));
}
function USBAlternateInterface(deviceInterface, alternateSetting) {
    ctorGuard('USBAlternateInterface', USBAlternateInterface, new.target, arguments.length, 2);
    var fs = wmGet(ifaceSlots, deviceInterface);
    if (!fs) throw makeTypeError(failedConstruct('USBAlternateInterface', "parameter 1 is not of type 'USBInterface'."), USBAlternateInterface);
    var setting = ctorConvert('USBAlternateInterface', function () { return cvtOctet(alternateSetting); }, USBAlternateInterface);
    var alts = fs.node.alternates;
    for (var i = 0; i < alts.length; i++) {
        if (alts[i].alternateSetting === setting) return buildAlternate(fs.ds, fs.c, fs.f, i, new.target.prototype);
    }
    throw new RangeErrorC(failedConstruct('USBAlternateInterface', 'Invalid alternate setting.'));
}
function USBEndpoint(alternate, endpointNumber, direction) {
    ctorGuard('USBEndpoint', USBEndpoint, new.target, arguments.length, 3);
    var as = wmGet(altSlots, alternate);
    if (!as) throw makeTypeError(failedConstruct('USBEndpoint', "parameter 1 is not of type 'USBAlternateInterface'."), USBEndpoint);
    var number = ctorConvert('USBEndpoint', function () { return cvtOctet(endpointNumber); }, USBEndpoint);
    var dir = ctorConvert('USBEndpoint', function () { return cvtDirection(direction); }, USBEndpoint);
    var eps = as.node.endpoints;
    for (var i = 0; i < eps.length; i++) {
        if (eps[i].endpointNumber === number && eps[i].direction === dir) return buildEndpoint(as.ds, as.c, as.f, as.a, i, new.target.prototype);
    }
    throw new RangeErrorC(failedConstruct('USBEndpoint', 'No such endpoint exists in the given alternate interface.'));
}

(function () {
    var bCfg = brandOf(configSlots), bIf = brandOf(ifaceSlots), bAlt = brandOf(altSlots), bEp = brandOf(endpointSlots);
    assembleInterface(USBConfiguration, 'USBConfiguration', null, null, {
        configurationValue: makeAttribute(bCfg, 'configurationValue', function (s) { return wmGet(configSlots, s).node.configurationValue; }),
        configurationName: makeAttribute(bCfg, 'configurationName', function (s) { return wmGet(configSlots, s).node.configurationName; }),
        interfaces: makeAttribute(bCfg, 'interfaces', function (s) { return wmGet(configSlots, s).interfaces; })
    }, ['configurationValue', 'configurationName', 'interfaces', 'constructor']);
    assembleInterface(USBInterface, 'USBInterface', null, null, {
        interfaceNumber: makeAttribute(bIf, 'interfaceNumber', function (s) { return wmGet(ifaceSlots, s).node.interfaceNumber; }),
        alternate: makeAttribute(bIf, 'alternate', function (s) {
            var fs = wmGet(ifaceSlots, s);
            var setting = isClaimed(fs.ds, fs.c, fs.node.interfaceNumber) ? fs.ds.alt[fs.node.interfaceNumber] : undefined;
            return fs.alternates[selectedAlternateIndex(fs.node, setting)];
        }),
        alternates: makeAttribute(bIf, 'alternates', function (s) { return wmGet(ifaceSlots, s).alternates; }),
        claimed: makeAttribute(bIf, 'claimed', function (s) { var fs = wmGet(ifaceSlots, s); return isClaimed(fs.ds, fs.c, fs.node.interfaceNumber); })
    }, ['interfaceNumber', 'alternate', 'alternates', 'claimed', 'constructor']);
    assembleInterface(USBAlternateInterface, 'USBAlternateInterface', null, null, {
        alternateSetting: makeAttribute(bAlt, 'alternateSetting', function (s) { return wmGet(altSlots, s).node.alternateSetting; }),
        interfaceClass: makeAttribute(bAlt, 'interfaceClass', function (s) { return wmGet(altSlots, s).node.interfaceClass; }),
        interfaceSubclass: makeAttribute(bAlt, 'interfaceSubclass', function (s) { return wmGet(altSlots, s).node.interfaceSubclass; }),
        interfaceProtocol: makeAttribute(bAlt, 'interfaceProtocol', function (s) { return wmGet(altSlots, s).node.interfaceProtocol; }),
        interfaceName: makeAttribute(bAlt, 'interfaceName', function (s) { return wmGet(altSlots, s).node.interfaceName; }),
        endpoints: makeAttribute(bAlt, 'endpoints', function (s) { return wmGet(altSlots, s).endpoints; })
    }, ['alternateSetting', 'interfaceClass', 'interfaceSubclass', 'interfaceProtocol', 'interfaceName', 'endpoints', 'constructor']);
    assembleInterface(USBEndpoint, 'USBEndpoint', null, null, {
        endpointNumber: makeAttribute(bEp, 'endpointNumber', function (s) { return wmGet(endpointSlots, s).node.endpointNumber; }),
        direction: makeAttribute(bEp, 'direction', function (s) { return wmGet(endpointSlots, s).node.direction; }),
        type: makeAttribute(bEp, 'type', function (s) { return wmGet(endpointSlots, s).node.type; }),
        packetSize: makeAttribute(bEp, 'packetSize', function (s) { return wmGet(endpointSlots, s).node.packetSize; })
    }, ['endpointNumber', 'direction', 'type', 'packetSize', 'constructor']);
})();

/* ==========================================================================
 * USBDevice
 * ========================================================================== */
function USBDevice() { throw makeTypeError(new.target ? failedConstruct('USBDevice', 'Illegal constructor') : 'Illegal constructor', USBDevice); }

var isDevice = brandOf(deviceSlots);
function devState(self) { return wmGet(deviceSlots, self); }

function opOpen(self) {
    var ds = devState(self);
    ensureNoDeviceChange(ds);
    if (ds.opened) return promiseResolve(undefined);
    return withDeviceChange(ds, callJson('openDevice', [ds.info.vendorId, ds.info.productId, transport.frameToken(), ds.info.serialNumber || '']), function (res) {
        checkOk(ds, res, 'SecurityError', 'Access denied.');
        ds.handle = res.handle; ds.opened = true;
    });
}
function opClose(self) {
    var ds = devState(self);
    ensureNoDeviceChange(ds);
    if (!ds.opened) return promiseResolve(undefined);
    var handle = ds.handle;
    markClosed(ds);
    transport.send('closeDevice', [handle, transport.frameToken()]);
    return promiseResolve(undefined);
}
function opForget(self) {
    var ds = devState(self);
    if (ds.opened && ds.handle !== null) transport.send('closeDevice', [ds.handle, transport.frameToken()]);
    markClosed(ds);
    mapDelete(deviceCache, ds.key);
    return promiseThen(callJson('forgetGrantedDevice', [ds.info.vendorId, ds.info.productId, transport.frameToken()]), function () { return undefined; });
}
function opSelectConfiguration(self, args, op) {
    var ds = devState(self);
    needArgs(args, 1, 'USBDevice', 'selectConfiguration', op);
    var value = convertArg('USBDevice', 'selectConfiguration', function () { return cvtOctet(args[0]); }, op);
    ensureNoDeviceOrInterfaceChange(ds);
    if (!ds.opened) throw makeDOMException(K_OPEN_REQUIRED, 'InvalidStateError');
    var idx = findConfigIndex(ds.info, value);
    if (idx < 0) throw makeDOMException('The configuration value provided is not supported by the device.', 'NotFoundError');
    if (ds.activeConfigIndex === idx) return promiseResolve(undefined);
    return withDeviceChange(ds, callJson('selectConfiguration', [ds.handle, value, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'Unable to set device configuration.');
        ds.activeConfigIndex = idx; resetInterfaceState(ds);
    });
}
function opClaimInterface(self, args, op) {
    var ds = devState(self);
    needArgs(args, 1, 'USBDevice', 'claimInterface', op);
    var n = convertArg('USBDevice', 'claimInterface', function () { return cvtOctet(args[0]); }, op);
    ensureConfigured(ds);
    if (findInterfaceIndex(ds, n) < 0) throw makeDOMException(K_IFACE_NOT_FOUND, 'NotFoundError');
    if (ds.ifaceChanging[n] === true) throw makeDOMException(K_IFACE_CHANGING, 'InvalidStateError');
    if (ds.claimed[n] === true) return promiseResolve(undefined);
    return withInterfaceChange(ds, n, callJson('claimInterface', [ds.handle, n, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'Unable to claim interface.');
        ds.claimed[n] = true; delete ds.alt[n];
    });
}
function opReleaseInterface(self, args, op) {
    var ds = devState(self);
    needArgs(args, 1, 'USBDevice', 'releaseInterface', op);
    var n = convertArg('USBDevice', 'releaseInterface', function () { return cvtOctet(args[0]); }, op);
    ensureConfigured(ds);
    if (findInterfaceIndex(ds, n) < 0) throw makeDOMException(K_IFACE_NOT_FOUND, 'NotFoundError');
    if (ds.ifaceChanging[n] === true) throw makeDOMException(K_IFACE_CHANGING, 'InvalidStateError');
    if (ds.claimed[n] !== true) return promiseResolve(undefined);
    return withInterfaceChange(ds, n, callJson('releaseInterface', [ds.handle, n, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'Unable to release interface.');
        delete ds.claimed[n]; delete ds.alt[n];
    });
}
function opSelectAlternateInterface(self, args, op) {
    var ds = devState(self);
    needArgs(args, 2, 'USBDevice', 'selectAlternateInterface', op);
    var n = convertArg('USBDevice', 'selectAlternateInterface', function () { return cvtOctet(args[0]); }, op);
    var a = convertArg('USBDevice', 'selectAlternateInterface', function () { return cvtOctet(args[1]); }, op);
    var fi = ensureInterfaceClaimed(ds, n);
    var iface = ds.info.configurations[ds.activeConfigIndex].interfaces[fi];
    var found = false;
    for (var i = 0; i < iface.alternates.length; i++) if (iface.alternates[i].alternateSetting === a) found = true;
    if (!found) throw makeDOMException(K_ALT_NOT_FOUND, 'NotFoundError');
    return withInterfaceChange(ds, n, callJson('selectAlternateInterface', [ds.handle, n, a, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'Unable to set device interface.');
        ds.alt[n] = a;
    });
}
function ensureControlAllowed(ds, setup) {
    if (setup.recipient === 'interface') ensureInterfaceClaimed(ds, setup.index & 0xff);
    else if (setup.recipient === 'endpoint') ensureEndpointAvailable(ds, (setup.index & 0x80) !== 0, setup.index & 0x0f);
}
function requestTypeByte(setup, dirIn) {
    return (setup.requestType === 'standard' ? 0x00 : setup.requestType === 'class' ? 0x20 : 0x40) |
           (setup.recipient === 'interface' ? 0x01 : setup.recipient === 'endpoint' ? 0x02 : setup.recipient === 'other' ? 0x03 : 0x00) |
           (dirIn ? 0x80 : 0x00);
}
function opControlTransferIn(self, args, op) {
    var ds = devState(self);
    needArgs(args, 2, 'USBDevice', 'controlTransferIn', op);
    var setup = convertArg('USBDevice', 'controlTransferIn', function () { return cvtControlSetup(args[0]); }, op);
    var length = convertArg('USBDevice', 'controlTransferIn', function () { return cvtUShort(args[1]); }, op);
    ensureNoDeviceOrInterfaceChange(ds);
    if (!ds.opened) throw makeDOMException(K_OPEN_REQUIRED, 'InvalidStateError');
    ensureControlAllowed(ds, setup);
    return promiseThen(callJson('controlTransferIn', [ds.handle, requestTypeByte(setup, true), setup.request, setup.value, setup.index, length, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'A transfer error has occurred.');
        var bytes = base64ToU8(res.data || '');
        return new USBInTransferResult(statusOf(res), new DV(bytes.buffer));
    });
}
function opControlTransferOut(self, args, op) {
    var ds = devState(self);
    needArgs(args, 1, 'USBDevice', 'controlTransferOut', op);
    var setup = convertArg('USBDevice', 'controlTransferOut', function () { return cvtControlSetup(args[0]); }, op);
    var data = null;
    if (args.length > 1 && args[1] !== undefined) data = convertArg('USBDevice', 'controlTransferOut', function () { return cvtBufferSource(args[1]); }, op);
    ensureNoDeviceOrInterfaceChange(ds);
    if (!ds.opened) throw makeDOMException(K_OPEN_REQUIRED, 'InvalidStateError');
    ensureControlAllowed(ds, setup);
    var b64 = data ? bytesToBase64(data) : '';
    return promiseThen(callJson('controlTransferOut', [ds.handle, requestTypeByte(setup, false), setup.request, setup.value, setup.index, b64, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'A transfer error has occurred.');
        return new USBOutTransferResult(statusOf(res), toInt(res.bytesWritten));
    });
}
function opClearHalt(self, args, op) {
    var ds = devState(self);
    needArgs(args, 2, 'USBDevice', 'clearHalt', op);
    var dir = convertArg('USBDevice', 'clearHalt', function () { return cvtDirection(args[0]); }, op);
    var n = convertArg('USBDevice', 'clearHalt', function () { return cvtOctet(args[1]); }, op);
    ensureEndpointAvailable(ds, dir === 'in', n);
    return promiseThen(callJson('clearHalt', [ds.handle, dir, n, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'Unable to clear endpoint.');
    });
}
function opTransferIn(self, args, op) {
    var ds = devState(self);
    needArgs(args, 2, 'USBDevice', 'transferIn', op);
    var n = convertArg('USBDevice', 'transferIn', function () { return cvtOctet(args[0]); }, op);
    var length = convertArg('USBDevice', 'transferIn', function () { return cvtULong(args[1]); }, op);
    ensureEndpointAvailable(ds, true, n);
    return promiseThen(callJson('bulkTransferIn', [ds.handle, n, length, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'A transfer error has occurred.');
        warnIfNeeded(res);
        var bytes = base64ToU8(res.data || '');
        return new USBInTransferResult(statusOf(res), new DV(bytes.buffer));
    });
}
function opTransferOut(self, args, op) {
    var ds = devState(self);
    needArgs(args, 2, 'USBDevice', 'transferOut', op);
    var n = convertArg('USBDevice', 'transferOut', function () { return cvtOctet(args[0]); }, op);
    var data = convertArg('USBDevice', 'transferOut', function () { return cvtBufferSource(args[1]); }, op);
    ensureEndpointAvailable(ds, false, n);
    var b64 = bytesToBase64(data);
    return promiseThen(callJson('bulkTransferOut', [ds.handle, n, b64, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'A transfer error has occurred.');
        warnIfNeeded(res);
        return new USBOutTransferResult(statusOf(res), toInt(res.bytesWritten));
    });
}
function totalPacketLength(lengths) {
    var total = 0;
    for (var i = 0; i < lengths.length; i++) {
        if (4294967295 - total < lengths[i]) return -1;
        total += lengths[i];
    }
    return total;
}
function opIsochronousTransferIn(self, args, op) {
    var ds = devState(self);
    needArgs(args, 2, 'USBDevice', 'isochronousTransferIn', op);
    var n = convertArg('USBDevice', 'isochronousTransferIn', function () { return cvtOctet(args[0]); }, op);
    var lengths = convertArg('USBDevice', 'isochronousTransferIn', function () { return cvtSequence(args[1], cvtULong); }, op);
    var ep = ensureEndpointAvailable(ds, true, n);
    if (totalPacketLength(lengths) < 0) throw makeDOMException(K_PACKETS_TOO_BIG, 'DataError');
    if (ep.type !== 'isochronous') throw makeDOMException('The specified endpoint is not an isochronous endpoint.', 'InvalidAccessError');
    return promiseThen(callJson('isochronousTransferIn', [ds.handle, n, jsonStringify(lengths), transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'A transfer error has occurred.');
        warnIfNeeded(res);
        var list = arrayIsArray(res.packets) ? res.packets : [];
        var chunks = [], total = 0, i;
        for (i = 0; i < list.length; i++) { var b = base64ToU8(list[i] && list[i].data || ''); arrayPush(chunks, b); total += b.length; }
        var combined = new U8(total), offset = 0, packets = [];
        for (i = 0; i < chunks.length; i++) {
            u8Set(combined, chunks[i], offset);
            arrayPush(packets, new USBIsochronousInTransferPacket(statusOf(list[i]), new DV(combined.buffer, offset, chunks[i].length)));
            offset += chunks[i].length;
        }
        return new USBIsochronousInTransferResult(packets, new DV(combined.buffer));
    });
}
function opIsochronousTransferOut(self, args, op) {
    var ds = devState(self);
    needArgs(args, 3, 'USBDevice', 'isochronousTransferOut', op);
    var n = convertArg('USBDevice', 'isochronousTransferOut', function () { return cvtOctet(args[0]); }, op);
    var data = convertArg('USBDevice', 'isochronousTransferOut', function () { return cvtBufferSource(args[1]); }, op);
    var lengths = convertArg('USBDevice', 'isochronousTransferOut', function () { return cvtSequence(args[2], cvtULong); }, op);
    var ep = ensureEndpointAvailable(ds, false, n);
    var total = totalPacketLength(lengths);
    if (total < 0) throw makeDOMException(K_PACKETS_TOO_BIG, 'DataError');
    if (total !== bufferSourceBytes(data).length) throw makeDOMException(K_BUFFER_MISMATCH, 'DataError');
    if (ep.type !== 'isochronous') throw makeDOMException('The specified endpoint is not an isochronous endpoint.', 'InvalidAccessError');
    var b64 = bytesToBase64(data);
    return promiseThen(callJson('isochronousTransferOut', [ds.handle, n, b64, jsonStringify(lengths), transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'A transfer error has occurred.');
        warnIfNeeded(res);
        var list = arrayIsArray(res.packets) ? res.packets : [], packets = [];
        for (var i = 0; i < list.length; i++) arrayPush(packets, new USBIsochronousOutTransferPacket(statusOf(list[i]), toInt(list[i] && list[i].bytesWritten)));
        return new USBIsochronousOutTransferResult(packets);
    });
}
function opReset(self) {
    var ds = devState(self);
    ensureNoDeviceOrInterfaceChange(ds);
    if (!ds.opened) throw makeDOMException(K_OPEN_REQUIRED, 'InvalidStateError');
    return withDeviceChange(ds, callJson('resetDevice', [ds.handle, transport.frameToken()]), function (res) {
        checkOk(ds, res, 'NetworkError', 'Unable to reset the device.');
        resetInterfaceState(ds);
    });
}

(function () {
    var m = {};
    function attr(name, read) { m[name] = makeAttribute(isDevice, name, function (s) { return read(devState(s)); }); }
    var infoAttrs = ['usbVersionMajor', 'usbVersionMinor', 'usbVersionSubminor', 'deviceClass', 'deviceSubclass', 'deviceProtocol',
                     'vendorId', 'productId', 'deviceVersionMajor', 'deviceVersionMinor', 'deviceVersionSubminor',
                     'manufacturerName', 'productName', 'serialNumber'];
    infoAttrs.forEach(function (name) { attr(name, function (ds) { return ds.info[name]; }); });
    attr('configuration', function (ds) { return ds.activeConfigIndex >= 0 ? getConfigs(ds)[ds.activeConfigIndex] : null; });
    attr('configurations', function (ds) { return getConfigs(ds); });
    attr('opened', function (ds) { return ds.opened; });
    var ops = [
        ['open', 0, opOpen], ['close', 0, opClose], ['forget', 0, opForget],
        ['selectConfiguration', 1, opSelectConfiguration], ['claimInterface', 1, opClaimInterface],
        ['releaseInterface', 1, opReleaseInterface], ['selectAlternateInterface', 2, opSelectAlternateInterface],
        ['controlTransferIn', 2, opControlTransferIn], ['controlTransferOut', 1, opControlTransferOut],
        ['clearHalt', 2, opClearHalt], ['transferIn', 2, opTransferIn], ['transferOut', 2, opTransferOut],
        ['isochronousTransferIn', 2, opIsochronousTransferIn], ['isochronousTransferOut', 3, opIsochronousTransferOut],
        ['reset', 0, opReset]
    ];
    var opNames = [];
    ops.forEach(function (o) { m[o[0]] = makeOperation(isDevice, 'USBDevice', o[0], o[1], o[2]); arrayPush(opNames, o[0]); });
    opNames.sort();   /* Blink installs operations in alphabetical order */
    assembleInterface(USBDevice, 'USBDevice', null, null, m, infoAttrs.concat(['configuration', 'configurations', 'opened'], opNames, ['constructor']));
})();

/* ==========================================================================
 * USBConnectionEvent
 * ========================================================================== */
function USBConnectionEvent(type, eventInitDict) {
    ctorGuard('USBConnectionEvent', USBConnectionEvent, new.target, arguments.length, 2);
    var t = ctorConvert('USBConnectionEvent', function () { return cvtDOMString(type); }, USBConnectionEvent);
    if (!isObjectLike(eventInitDict)) {
        throw makeTypeError(failedConstruct('USBConnectionEvent', "The provided value is not of type 'USBConnectionEventInit'."), USBConnectionEvent);
    }
    var init = { bubbles: !!eventInitDict.bubbles, cancelable: !!eventInitDict.cancelable, composed: !!eventInitDict.composed };
    var dev = eventInitDict.device;
    if (dev === undefined) {
        throw makeTypeError(failedConstruct('USBConnectionEvent', "Failed to read the 'device' property from 'USBConnectionEventInit': Required member is undefined."), USBConnectionEvent);
    }
    if (!isDevice(dev)) {
        throw makeTypeError(failedConstruct('USBConnectionEvent', "Failed to read the 'device' property from 'USBConnectionEventInit': Failed to convert value to 'USBDevice'."), USBConnectionEvent);
    }
    var ev = reflectConstruct(EventC, [t, init], new.target);
    wmSet(eventSlots, ev, { device: dev });
    return ev;
}
assembleInterface(USBConnectionEvent, 'USBConnectionEvent', EventC, EventC.prototype, {
    device: makeAttribute(brandOf(eventSlots), 'device', function (s) { return wmGet(eventSlots, s).device; })
}, ['device', 'constructor']);

/* ==========================================================================
 * USB (navigator.usb)
 * ========================================================================== */
function USB() { throw makeTypeError(new.target ? failedConstruct('USB', 'Illegal constructor') : 'Illegal constructor', USB); }
var isUSB = brandOf(usbSlots);
var deviceCache = new MapC();

function getOrCreateDevice(info, ordinal) {
    var key = info.vendorId + ':' + info.productId + ':' + (info.serialNumber || '') + '#' + (ordinal || 0);
    var existing = mapGet(deviceCache, key);
    if (existing) return existing;
    var dev = objectCreate(USBDevice.prototype);
    wmSet(deviceSlots, dev, makeDeviceState(info, key));
    mapSet(deviceCache, key, dev);
    return dev;
}
function findCachedDevice(info) {
    return mapGet(deviceCache, info.vendorId + ':' + info.productId + ':' + (info.serialNumber || '') + '#0');
}

function handlerAttribute(type) {
    var name = 'on' + type;
    var getter = makeGetter(isUSB, name, function (self) { return wmGet(usbSlots, self)[name]; });
    var holder = { set [name](value) {
        if (!isUSB(this)) throw makeTypeError('Illegal invocation', setterFn);
        var s = wmGet(usbSlots, this), self = this;
        var v = isObjectLike(value) ? value : null;
        s[name] = v;
        if (v !== null && !s.registered[type]) {
            s.registered[type] = true;
            reflectApply(etAddEventListener, self, [type, function (ev) {
                var h = s[name];
                if (typeof h === 'function') reflectApply(h, self, [ev]);
            }]);
        }
    } };
    var setterFn = getOwnPropertyDescriptor(holder, name).set;
    maskFunction(setterFn, nativeSource('set ' + name));
    return { get: getter, set: setterFn, enumerable: true, configurable: true };
}

function opGetDevices() {
    return promiseThen(callJson('listDevices', [transport.frameToken()]), function (res) {
        var out = [], counts = {}, list = (res && arrayIsArray(res.devices)) ? res.devices : [];
        for (var i = 0; i < list.length; i++) {
            var info = normalizeInfo(list[i]);
            var base = info.vendorId + ':' + info.productId + ':' + (info.serialNumber || '');
            var ord = counts[base] || 0;
            counts[base] = ord + 1;
            arrayPush(out, getOrCreateDevice(info, ord));
        }
        return out;
    });
}

var ExtraGuardRef = win.__pysideWebUSBExtraGuard;   /* captured once: the page cannot swap it out later */
function runExtraGuard(filters, exclusionFilters) {
    if (typeof ExtraGuardRef !== 'function') return true;
    try {
        return reflectApply(ExtraGuardRef, win, [{
            origin: (win.location && win.location.origin) ? win.location.origin : '',
            filters: filters, exclusionFilters: exclusionFilters
        }]) !== false;
    } catch (e) { return false; }
}

function opRequestDevice(self, args, op) {
    needArgs(args, 1, 'USB', 'requestDevice', op);
    var options = convertArg('USB', 'requestDevice', function () { return cvtRequestOptions(args[0]); }, op);
    var ua = nav.userActivation;
    if (ua && ua.isActive === false) {
        throw makeDOMException(failedExecute('USB', 'requestDevice', 'Must be handling a user gesture to show a permission request.'), 'SecurityError');
    }
    var all = [], k;
    for (k = 0; k < options.filters.length; k++) arrayPush(all, options.filters[k]);
    for (k = 0; k < options.exclusionFilters.length; k++) arrayPush(all, options.exclusionFilters[k]);
    for (var i = 0; i < all.length; i++) {
        var f = all[i];
        if (hasOwn(f, 'productId') && !hasOwn(f, 'vendorId')) throw new TypeErrorC('A filter containing a productId must also contain a vendorId.');
        if (hasOwn(f, 'subclassCode') && !hasOwn(f, 'classCode')) throw new TypeErrorC('A filter containing a subclassCode must also contain a classCode.');
        if (hasOwn(f, 'protocolCode') && !hasOwn(f, 'subclassCode')) throw new TypeErrorC('A filter containing a protocolCode must also contain a subclassCode.');
    }
    if (!runExtraGuard(options.filters, options.exclusionFilters)) {
        throw makeDOMException("Rejected by this page's configured WebUSB guard (extra_guard_js).", 'SecurityError');
    }
    var payload = jsonStringify({ filters: options.filters, exclusionFilters: options.exclusionFilters });
    var chosen = promiseThen(callRawChecked('mintGestureToken', []), function (gesture) {
        return callJson('requestDeviceChooser', [payload, transport.frameToken(), (typeof gesture === 'string') ? gesture : '']);
    });
    return promiseThen(chosen, function (res) {
        if (res && res.cancelled) {
            if (res.error) throwBridge(null, res, 'NotFoundError', 'No device selected.');
            throw new DOMExceptionC('No device selected.', 'NotFoundError');
        }
        if (!res || !res.device) throw new DOMExceptionC('No device selected.', 'NotFoundError');
        var info = normalizeInfo(res.device);
        return findCachedDevice(info) || getOrCreateDevice(info, 0);
    });
}

(function () {
    assembleInterface(USB, 'USB', EventTargetC, EventTargetC.prototype, {
        onconnect: handlerAttribute('connect'),
        ondisconnect: handlerAttribute('disconnect'),
        getDevices: makeOperation(isUSB, 'USB', 'getDevices', 0, opGetDevices),
        requestDevice: makeOperation(isUSB, 'USB', 'requestDevice', 1, opRequestDevice)
    }, ['onconnect', 'ondisconnect', 'getDevices', 'constructor', 'requestDevice']);
})();
