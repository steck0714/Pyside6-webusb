/* ==========================================================================
 * part 35 :: installation
 *
 * navigator.usb lives as an ACCESSOR ON Navigator.prototype (never as an own property of
 * the navigator instance).  That is what a native WebIDL attribute looks like, and it is
 * what makes `delete navigator.usb` a harmless no-op that still returns true.
 * With CONFIG.lockNavigatorUsb (default) the prototype property is additionally made
 * non-configurable so `delete Navigator.prototype.usb` / defineProperty(...) cannot remove
 * or replace it either.
 * ========================================================================== */

var usbInstance = reflectConstruct(EventTargetC, [], USB);
wmSet(usbSlots, usbInstance, { onconnect: null, ondisconnect: null, registered: objectCreate(null) });

/* ---- hotplug events ----------------------------------------------------------
 * The bridge broadcasts only {vendorId, productId}.  Descriptor strings (serial number,
 * names) are fetched per frame through listDevices(), which is origin/grant checked, so a
 * frame that has no permission never learns anything beyond "some VID:PID changed".
 * ------------------------------------------------------------------------- */
function deviceKey(info, ordinal) {
    return info.vendorId + ':' + info.productId + ':' + (info.serialNumber || '') + '#' + (ordinal || 0);
}
function enumerateGranted() {
    return promiseThen(callJson('listDevices', [transport.frameToken()]), function (res) {
        var list = (res && arrayIsArray(res.devices)) ? res.devices : [], counts = {}, out = [];
        for (var i = 0; i < list.length; i++) {
            var info = normalizeInfo(list[i]);
            var base = info.vendorId + ':' + info.productId + ':' + (info.serialNumber || '');
            var ord = counts[base] || 0;
            counts[base] = ord + 1;
            arrayPush(out, { info: info, ordinal: ord, key: deviceKey(info, ord) });
        }
        return out;
    });
}
function dispatchUsbEvent(type, device) {
    var ev = new USBConnectionEvent(type, { device: device });
    try { reflectApply(etDispatchEvent, usbInstance, [ev]); } catch (e) { /* listeners never break the bridge */ }
}
function announceConnected(vid, pid) {
    return promiseThen(enumerateGranted(), function (rows) {
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            if (r.info.vendorId !== vid || r.info.productId !== pid || mapHas(deviceCache, r.key)) continue;
            dispatchUsbEvent('connect', getOrCreateDevice(r.info, r.ordinal));
        }
    });
}
function announceDisconnected(vid, pid) {
    return promiseThen(enumerateGranted(), function (rows) {
        var present = objectCreate(null), gone = [];
        for (var i = 0; i < rows.length; i++) present[rows[i].key] = true;
        mapForEach(deviceCache, function (dev, key) {
            var ds = wmGet(deviceSlots, dev);
            if (ds.info.vendorId === vid && ds.info.productId === pid && present[key] !== true) arrayPush(gone, [key, dev]);
        });
        if (!gone.length) {
            /* the page never enumerated this device: still tell it, with an already-disconnected object */
            var ghost = objectCreate(USBDevice.prototype);
            var gs = makeDeviceState(normalizeInfo({ vendorId: vid, productId: pid }), 'ghost:' + vid + ':' + pid);
            markDisconnected(gs);
            wmSet(deviceSlots, ghost, gs);
            arrayPush(gone, [null, ghost]);
        }
        for (var j = 0; j < gone.length; j++) {
            if (gone[j][0] !== null) mapDelete(deviceCache, gone[j][0]);
            markDisconnected(wmGet(deviceSlots, gone[j][1]));
            dispatchUsbEvent('disconnect', gone[j][1]);
        }
    });
}
var eventChain = promiseResolve(undefined);
transport.onEvent(function (type, json) {
    var raw;
    try { raw = jsonParse(json); } catch (e) { return; }
    if (!raw || typeof raw.vendorId !== 'number' || typeof raw.productId !== 'number') return;
    var vid = raw.vendorId, pid = raw.productId;
    eventChain = promiseThen(eventChain, function () {
        return promiseThen(callRawChecked('isGrantedToThisFrame', [vid, pid, transport.frameToken()]), function (granted) {
            if (granted !== true) return undefined;
            return (type === 'connect') ? announceConnected(vid, pid) : announceDisconnected(vid, pid);
        });
    });
    eventChain = promiseThen(eventChain, undefined, function () { /* keep the chain alive */ });
});

/* ---- install -------------------------------------------------------------------- */
var usbGetter = makeGetter(function (self) { return self === nav; }, 'usb', function () { return usbInstance; });
defineProperty(Navigator.prototype, 'usb', {
    get: usbGetter, set: undefined, enumerable: true, configurable: !CONFIG.lockNavigatorUsb
});

var EXPORTED = [
    ['USB', USB], ['USBConnectionEvent', USBConnectionEvent], ['USBDevice', USBDevice],
    ['USBInTransferResult', USBInTransferResult], ['USBOutTransferResult', USBOutTransferResult],
    ['USBIsochronousInTransferPacket', USBIsochronousInTransferPacket],
    ['USBIsochronousInTransferResult', USBIsochronousInTransferResult],
    ['USBIsochronousOutTransferPacket', USBIsochronousOutTransferPacket],
    ['USBIsochronousOutTransferResult', USBIsochronousOutTransferResult],
    ['USBConfiguration', USBConfiguration], ['USBInterface', USBInterface],
    ['USBAlternateInterface', USBAlternateInterface], ['USBEndpoint', USBEndpoint]
];
for (var gi = 0; gi < EXPORTED.length; gi++) {
    if (!hasOwn(win, EXPORTED[gi][0])) {
        defineProperty(win, EXPORTED[gi][0], { value: EXPORTED[gi][1], writable: true, enumerable: false, configurable: true });
    }
}
