/* ==========================================================================
 * pyside6-webusb polyfill :: part 00 :: prelude
 *
 * scripts/build_polyfill.py concatenates the parts 00..40 inside ONE strict-mode
 * IIFE and emits src/pyside6_webusb/_polyfill_bundle.py.  Every `return;` in these
 * parts therefore means "do nothing on this page".
 *
 * Design goals (v0.0.6a):
 *   - navigator.usb is an accessor on Navigator.prototype, exactly like a native
 *     WebIDL attribute, so `delete navigator.usb` cannot remove it (it is not an
 *     own property of the navigator instance) and, by default, the prototype
 *     property itself is non-configurable.
 *   - All WebUSB interfaces (USB, USBDevice, USBConfiguration, ... , USBConnectionEvent)
 *     have the same shape a native Chromium build gives them: descriptors,
 *     Symbol.toStringTag, illegal-constructor errors, brand checks, toString().
 *   - Everything the polyfill needs is captured up-front (pristine intrinsics), so
 *     page scripts that monkey-patch Promise/JSON/Function.prototype.call/... later
 *     cannot hijack or break the bridge.
 * ========================================================================== */

var CONFIG = /*CONFIG_BEGIN*/{"locale":"en","lockNavigatorUsb":true,"nativeLookalike":true,"exposeCommands":true,"transport":"webchannel","ws":null,"version":"","debug":false}/*CONFIG_END*/;

var win = window;
var nav = win.navigator;

/* Do nothing outside a secure context (USB is [SecureContext]) and never override an
 * existing implementation (a native one, or our own from an earlier injection). */
if (typeof win.isSecureContext !== 'undefined' && !win.isSecureContext) return;
if (typeof Navigator !== 'function' || !(nav instanceof Navigator)) return;
if ('usb' in nav) return;
if (typeof EventTarget !== 'function' || typeof Event !== 'function' ||
    typeof Promise !== 'function' || typeof WeakMap !== 'function' ||
    typeof Reflect !== 'object' || typeof DOMException !== 'function') return;

/* ---- pristine intrinsics ------------------------------------------------- */
var uncurryThis = Function.prototype.bind.bind(Function.prototype.call);
var ObjectC = Object;
var defineProperty = ObjectC.defineProperty;
var getOwnPropertyDescriptor = ObjectC.getOwnPropertyDescriptor;
var getPrototypeOf = ObjectC.getPrototypeOf;
var setPrototypeOf = ObjectC.setPrototypeOf;
var objectCreate = ObjectC.create;
var objectFreeze = ObjectC.freeze;
var reflectApply = Reflect.apply;
var reflectConstruct = Reflect.construct;
var hasOwn = uncurryThis(ObjectC.prototype.hasOwnProperty);
var objectToString = uncurryThis(ObjectC.prototype.toString);
var arrayPush = uncurryThis(Array.prototype.push);
var arraySlice = uncurryThis(Array.prototype.slice);
var arrayIndexOf = uncurryThis(Array.prototype.indexOf);
var arrayIsArray = Array.isArray;
var WeakMapC = WeakMap;
var MapC = Map;
var PromiseC = Promise;
var wmGet = uncurryThis(WeakMapC.prototype.get);
var wmSet = uncurryThis(WeakMapC.prototype.set);
var wmHas = uncurryThis(WeakMapC.prototype.has);
var mapGet = uncurryThis(MapC.prototype.get);
var mapSet = uncurryThis(MapC.prototype.set);
var mapHas = uncurryThis(MapC.prototype.has);
var mapDelete = uncurryThis(MapC.prototype.delete);
var mapForEach = uncurryThis(MapC.prototype.forEach);
var promiseThen = uncurryThis(PromiseC.prototype.then);
var promiseResolveFn = PromiseC.resolve;
var promiseRejectFn = PromiseC.reject;
function promiseResolve(v) { return reflectApply(promiseResolveFn, PromiseC, [v]); }
function promiseReject(e) { return reflectApply(promiseRejectFn, PromiseC, [e]); }
var jsonParse = JSON.parse;
var jsonStringify = JSON.stringify;
var StringC = String;
var fromCharCode = String.fromCharCode;
var stringIndexOf = uncurryThis(String.prototype.indexOf);
var stringSlice = uncurryThis(String.prototype.slice);
var charCodeAt = uncurryThis(String.prototype.charCodeAt);
var mathFloor = Math.floor;
var mathPow = Math.pow;
var U8 = Uint8Array;
var DV = DataView;
var AB = ArrayBuffer;
var abIsView = AB.isView;
var abByteLength = uncurryThis(getOwnPropertyDescriptor(AB.prototype, 'byteLength').get);
var u8Subarray = uncurryThis(U8.prototype.subarray);
var u8Set = uncurryThis(U8.prototype.set);
var TypeErrorC = TypeError;
var RangeErrorC = RangeError;
var DOMExceptionC = DOMException;
var ErrorC = Error;
var EventC = Event;
var EventTargetC = EventTarget;
var etAddEventListener = EventTargetC.prototype.addEventListener;
var etDispatchEvent = EventTargetC.prototype.dispatchEvent;
var symToStringTag = Symbol.toStringTag;
var symIterator = Symbol.iterator;
var origFnToString = Function.prototype.toString;
var captureStackTrace = (typeof ErrorC.captureStackTrace === 'function') ? ErrorC.captureStackTrace : null;
var consoleRef = win.console;
var atobFn = win.atob;
var btoaFn = win.btoa;
var setTimeoutFn = win.setTimeout;
var WebSocketC = win.WebSocket;

function logWarn(msg) {
    try { if (consoleRef && consoleRef.warn) reflectApply(consoleRef.warn, consoleRef, [msg]); } catch (e) { /* ignore */ }
}
function logDebug(msg) {
    try { if (consoleRef && consoleRef.debug) reflectApply(consoleRef.debug, consoleRef, ['[pyside6-webusb] ' + msg]); } catch (e) { /* ignore */ }
}
function logInfo() {
    try { if (consoleRef && consoleRef.log) reflectApply(consoleRef.log, consoleRef, arraySlice(arguments, 0)); } catch (e) { /* ignore */ }
}
