/* ==========================================================================
 * part 20 :: WebIDL-style helpers
 * Error texts and check ORDER mirror Chromium's Blink (third_party/blink/renderer/
 * modules/webusb/*.cc, checked against the real sources).
 * ========================================================================== */

/* ---- native-lookalike registry (Function.prototype.toString masking) ------- */
var nativeText = new WeakMapC();
function nativeSource(name) { return 'function ' + name + '() { [native code] }'; }
function maskFunction(fn, text) { wmSet(nativeText, fn, text); return fn; }

/* ---- errors ---------------------------------------------------------------- */
function trimStack(err, skipFn) {
    if (captureStackTrace && typeof skipFn === 'function') {
        try { captureStackTrace(err, skipFn); } catch (e) { /* ignore */ }
    }
    return err;
}
function makeTypeError(msg, skipFn) { return trimStack(new TypeErrorC(msg), skipFn); }
function makeDOMException(msg, name, skipFn) { return trimStack(new DOMExceptionC(msg, name), skipFn); }
function failedExecute(iface, method, detail) { return "Failed to execute '" + method + "' on '" + iface + "': " + detail; }
function failedConstruct(iface, detail) { return "Failed to construct '" + iface + "': " + detail; }
function notEnoughArgs(required, present) {
    return required + ' argument' + (required === 1 ? '' : 's') + ' required, but only ' + present + ' present.';
}
var NEW_OPERATOR_MSG = "Please use the 'new' operator, this DOM object constructor cannot be called as a function.";

/* ---- WebIDL type conversions (no [EnforceRange]/[Clamp]: modulo semantics) ---- */
function isObjectLike(v) { var t = typeof v; return (t === 'object' && v !== null) || t === 'function'; }
function truncateToBits(num, bits) {
    if (num !== num || num === Infinity || num === -Infinity) return 0;
    var n = num < 0 ? -mathFloor(-num) : mathFloor(num);
    var m = mathPow(2, bits);
    n = n % m;
    if (n < 0) n += m;
    return n + 0;
}
/* Unary plus is WebIDL ToNumber: it throws V8's own TypeError for Symbol/BigInt. */
function cvtOctet(v) { return truncateToBits(+v, 8); }
function cvtUShort(v) { return truncateToBits(+v, 16); }
function cvtULong(v) { return truncateToBits(+v, 32); }
function cvtDOMString(v) { return '' + v; }   /* throws for Symbol, like ToString */
function cvtEnum(v, allowed, enumName) {
    var s = '' + v;
    if (arrayIndexOf(allowed, s) < 0) {
        throw new TypeErrorC("The provided value '" + s + "' is not a valid enum value of type " + enumName + '.');
    }
    return s;
}
function wrapMember(dictName, member, fn) {
    try { return fn(); } catch (e) {
        if (e && getPrototypeOf(e) === TypeErrorC.prototype) {
            throw new TypeErrorC("Failed to read the '" + member + "' property from '" + dictName + "': " + e.message);
        }
        throw e;
    }
}
function cvtSequence(value, elem) {
    if (!isObjectLike(value)) throw new TypeErrorC('The provided value cannot be converted to a sequence.');
    var method = value[symIterator];
    if (typeof method !== 'function') throw new TypeErrorC('The object must have a callable @@iterator property.');
    var it = reflectApply(method, value, []);
    if (!isObjectLike(it)) throw new TypeErrorC('The object must have a callable @@iterator property.');
    var next = it.next, out = [];
    for (;;) {
        var step = reflectApply(next, it, []);
        if (!isObjectLike(step)) throw new TypeErrorC('Iterator result ' + step + ' is not an object');
        if (step.done) break;
        arrayPush(out, elem(step.value));
    }
    return out;
}
/* members: [[name, converter, required], ...] in lexicographic order (WebIDL rule) */
function cvtDictionary(v, dictName, members, notObjectMsg) {
    if (!isObjectLike(v)) throw new TypeErrorC(notObjectMsg || ("The provided value is not of type '" + dictName + "'."));
    var out = {};
    for (var i = 0; i < members.length; i++) {
        var name = members[i][0], conv = members[i][1], required = members[i][2];
        var raw = v[name];
        if (raw === undefined) {
            if (required) throw new TypeErrorC("Failed to read the '" + name + "' property from '" + dictName + "': Required member is undefined.");
            continue;
        }
        out[name] = wrapMember(dictName, name, function () { return conv(raw); });
    }
    return out;
}
var FILTER_MEMBERS = [
    ['classCode', cvtOctet, false], ['productId', cvtUShort, false], ['protocolCode', cvtOctet, false],
    ['serialNumber', cvtDOMString, false], ['subclassCode', cvtOctet, false], ['vendorId', cvtUShort, false]
];
function cvtFilter(v) { return cvtDictionary(v, 'USBDeviceFilter', FILTER_MEMBERS); }
function cvtRequestOptions(v) {
    if (!isObjectLike(v)) throw new TypeErrorC("The provided value is not of type 'USBDeviceRequestOptions'.");
    var out = { filters: [], exclusionFilters: [] };
    var excl = v.exclusionFilters;
    if (excl !== undefined) {
        out.exclusionFilters = wrapMember('USBDeviceRequestOptions', 'exclusionFilters', function () { return cvtSequence(excl, cvtFilter); });
    }
    var filt = v.filters;
    if (filt === undefined) {
        throw new TypeErrorC("Failed to read the 'filters' property from 'USBDeviceRequestOptions': Required member is undefined.");
    }
    out.filters = wrapMember('USBDeviceRequestOptions', 'filters', function () { return cvtSequence(filt, cvtFilter); });
    return out;
}
var SETUP_MEMBERS = [
    ['index', cvtUShort, true],
    ['recipient', function (x) { return cvtEnum(x, ['device', 'interface', 'endpoint', 'other'], 'USBRecipient'); }, true],
    ['request', cvtOctet, true],
    ['requestType', function (x) { return cvtEnum(x, ['standard', 'class', 'vendor'], 'USBRequestType'); }, true],
    ['value', cvtUShort, true]
];
function cvtControlSetup(v) { return cvtDictionary(v, 'USBControlTransferParameters', SETUP_MEMBERS); }
function cvtDirection(v) { return cvtEnum(v, ['in', 'out'], 'USBDirection'); }
function cvtTransferStatus(v) { return cvtEnum(v, ['ok', 'stall', 'babble'], 'USBTransferStatus'); }

/* BufferSource ([PassAsSpan], non-shared) */
function isArrayBuffer(v) {
    if (!isObjectLike(v)) return false;
    try { abByteLength(v); return true; } catch (e) { return false; }
}
function cvtBufferSource(v) {
    if (!(abIsView(v) || isArrayBuffer(v))) {
        throw new TypeErrorC("The provided value is not of type '(ArrayBuffer or ArrayBufferView)'.");
    }
    return v;
}
function bufferSourceBytes(v) {
    if (abIsView(v)) return new U8(v.buffer, v.byteOffset, v.byteLength);
    return new U8(v);
}
function isDataView(v) { return isObjectLike(v) && abIsView(v) && objectToString(v) === '[object DataView]'; }

/* ---- base64 (bridge payload encoding) --------------------------------------- */
function bytesToBase64(view) {
    var arr = bufferSourceBytes(view), binary = '', chunk = 0x8000;
    for (var i = 0; i < arr.length; i += chunk) {
        binary += reflectApply(fromCharCode, StringC, u8Subarray(arr, i, i + chunk));
    }
    return reflectApply(btoaFn, win, [binary]);
}
function base64ToU8(b64) {
    var binary = reflectApply(atobFn, win, [b64 || '']);
    var bytes = new U8(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = charCodeAt(binary, i);
    return bytes;
}

/* ---- member factories -------------------------------------------------------
 * makeOperation:  a prototype method that is NOT a constructor and has no `prototype`
 *                 property (object-literal shorthand), the right name/length, a native
 *                 looking toString(), an "Illegal invocation" rejection on a wrong
 *                 receiver and synchronous errors turned into rejected promises.
 * makeGetter:     an accessor getter named "get <name>" with a brand check.
 * -------------------------------------------------------------------------- */
function makeOperation(brand, ifaceName, name, length, impl) {
    var op = ({ [name]() {
        var self = this, args = arguments;
        try {
            if (!brand(self)) throw makeTypeError(failedExecute(ifaceName, name, 'Illegal invocation'), op);
            return impl(self, args, op);
        } catch (e) {
            return promiseReject(e);
        }
    } })[name];
    defineProperty(op, 'length', { value: length, configurable: true });
    maskFunction(op, nativeSource(name));
    return { value: op, writable: true, enumerable: true, configurable: true };
}
function makeGetter(brand, name, read) {
    var holder = { get [name]() {
        if (!brand(this)) throw makeTypeError('Illegal invocation', getterFn);
        return read(this);
    } };
    var getterFn = getOwnPropertyDescriptor(holder, name).get;
    maskFunction(getterFn, nativeSource('get ' + name));
    return getterFn;
}
function makeAttribute(brand, name, read) {
    return { get: makeGetter(brand, name, read), set: undefined, enumerable: true, configurable: true };
}

/* Assemble an interface object the way WebIDL does. */
function assembleInterface(Ctor, tag, ctorParent, protoParent, members, order) {
    if (ctorParent) setPrototypeOf(Ctor, ctorParent);
    var proto = Ctor.prototype;
    if (protoParent) setPrototypeOf(proto, protoParent);
    delete proto.constructor;
    for (var i = 0; i < order.length; i++) {
        var n = order[i];
        if (n === 'constructor') {
            defineProperty(proto, 'constructor', { value: Ctor, writable: true, enumerable: false, configurable: true });
        } else {
            defineProperty(proto, n, members[n]);
        }
    }
    defineProperty(proto, symToStringTag, { value: tag, writable: false, enumerable: false, configurable: true });
    defineProperty(Ctor, 'prototype', { writable: false });
    maskFunction(Ctor, nativeSource(tag));
}
