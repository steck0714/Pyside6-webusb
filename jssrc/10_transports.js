/* ==========================================================================
 * part 10 :: transports
 *
 * A transport hides HOW the page reaches the Python bridge:
 *   - 'webchannel' : QtWebEngine (qt.webChannelTransport + qwebchannel.js).  The frame
 *                    token is pushed into the frame by Python (FrameOriginTracker).
 *   - 'websocket'  : QtWebView (Android WebView / WKWebView / WebView2 / ...) and any
 *                    embedder without QWebChannel.  The page talks to a loopback
 *                    QWebSocketServer.  The server derives the caller's origin from the
 *                    handshake `Origin` header, which page script cannot forge, so no
 *                    frame token is needed.
 *
 * Interface:  { kind, ready, callRaw(method, args) -> Promise<any>,
 *               send(method, args), onEvent(fn(type, infoJson)), frameToken() }
 * ========================================================================== */

var clearTimeoutFn = win.clearTimeout;
var wsSend = WebSocketC ? WebSocketC.prototype.send : null;
var wsClose = WebSocketC ? WebSocketC.prototype.close : null;

/* Replaced by install() with the inlined qwebchannel.js so that no QWebChannel/QObject
 * globals leak into the page (default: use a page-provided global, used by the tests). */
var QWC_LIB = /*QWC_LIB_BEGIN*/(typeof QWebChannel === 'function' ? QWebChannel : null)/*QWC_LIB_END*/;

function makeWebChannelTransport() {
    var qtObj = win.qt;
    if (!qtObj || !qtObj.webChannelTransport || typeof QWC_LIB !== 'function') return null;
    var handlers = [];
    function emit(type, json) {
        for (var i = 0; i < handlers.length; i++) {
            try { handlers[i](type, json); } catch (e) { /* a broken listener must not break the others */ }
        }
    }
    var bridgePromise = new PromiseC(function (resolve) {
        try {
            new QWC_LIB(qtObj.webChannelTransport, function (channel) {
                var b = (channel && channel.objects && channel.objects.pyUsbBridge) || null;
                if (b) {
                    try {
                        if (b.deviceConnected && b.deviceConnected.connect) {
                            b.deviceConnected.connect(function (j) { emit('connect', j); });
                        }
                        if (b.deviceDisconnected && b.deviceDisconnected.connect) {
                            b.deviceDisconnected.connect(function (j) { emit('disconnect', j); });
                        }
                    } catch (e) { /* signals are optional */ }
                }
                resolve(b);
            });
        } catch (e) { resolve(null); }
    });
    return {
        kind: 'webchannel',
        ready: promiseThen(bridgePromise, function (b) { return !!b; }),
        callRaw: function (method, args) {
            return promiseThen(bridgePromise, function (b) {
                if (!b || typeof b[method] !== 'function') throw new ErrorC('WebUSB bridge unavailable');
                return new PromiseC(function (resolve) {
                    var a = arraySlice(args, 0);
                    arrayPush(a, function (res) { resolve(res); });
                    reflectApply(b[method], b, a);
                });
            });
        },
        send: function (method, args) {
            promiseThen(bridgePromise, function (b) {
                if (b && typeof b[method] === 'function') reflectApply(b[method], b, arraySlice(args, 0));
            });
        },
        onEvent: function (fn) { arrayPush(handlers, fn); },
        frameToken: function () {
            var t = win.__pyUsbFrameToken;
            return typeof t === 'string' ? t : '';
        }
    };
}

function makeWebSocketTransport() {
    var cfg = CONFIG.ws;
    if (!cfg || !WebSocketC || !wsSend) return null;
    var url = 'ws://' + cfg.host + ':' + cfg.port + '/pyusb/' + cfg.secret;
    var sock = null, opening = null, state = 'closed', nextId = 1, everOpen = false, backoff = 1000, reconnects = 0;
    var pending = new MapC();
    var handlers = [];
    function emit(type, json) {
        for (var i = 0; i < handlers.length; i++) {
            try { handlers[i](type, json); } catch (e) { /* ignore */ }
        }
    }
    function unavailable() { return new ErrorC('WebUSB bridge unavailable'); }
    function failAll(err) {
        var old = pending;
        pending = new MapC();
        mapForEach(old, function (entry) { entry.reject(err); });
    }
    function scheduleReconnect() {
        /* Proactive reconnects exist only so that hotplug events keep flowing while the page is idle;
         * any API call reopens the socket on demand, so give up after a few attempts (no endless timers). */
        if (!everOpen || reconnects >= 6) return;
        reconnects++;
        var delay = backoff;
        backoff = backoff < 30000 ? backoff * 2 : 30000;
        reflectApply(setTimeoutFn, win, [function () {
            if (state === 'closed') promiseThen(open(), function () { /* ok */ }, function () { scheduleReconnect(); });
        }, delay]);
    }
    function open() {
        if (state === 'open') return promiseResolve(sock);
        if (opening) return opening;
        opening = new PromiseC(function (resolve, reject) {
            var s, done = false, timer = null;
            function fail() {
                if (done) return;
                done = true;
                if (timer !== null) reflectApply(clearTimeoutFn, win, [timer]);
                state = 'closed'; sock = null; opening = null;
                reject(unavailable());
            }
            try { s = new WebSocketC(url); } catch (e) { opening = null; reject(unavailable()); return; }
            state = 'connecting';
            timer = reflectApply(setTimeoutFn, win, [function () {
                if (!done) { try { reflectApply(wsClose, s, []); } catch (e) { /* ignore */ } fail(); }
            }, 8000]);
            s.onmessage = function (ev) {
                var msg;
                try { msg = jsonParse(ev.data); } catch (e) { return; }
                if (!msg || typeof msg !== 'object') return;
                if (msg.hello) {
                    if (!done) {
                        done = true;
                        reflectApply(clearTimeoutFn, win, [timer]);
                        state = 'open'; sock = s; opening = null; everOpen = true; backoff = 1000; reconnects = 0;
                        resolve(s);
                    }
                    return;
                }
                if (msg.ev) { emit(msg.ev, msg.d); return; }
                if (typeof msg.i === 'number') {
                    var entry = mapGet(pending, msg.i);
                    if (entry) {
                        mapDelete(pending, msg.i);
                        if (hasOwn(msg, 'e')) entry.reject(new ErrorC(StringC(msg.e)));
                        else entry.resolve(msg.r);
                    }
                }
            };
            s.onclose = function () {
                var wasOpen = (state === 'open');
                if (!done) { fail(); }
                state = 'closed'; sock = null; opening = null;
                failAll(unavailable());
                if (wasOpen) scheduleReconnect();
            };
            s.onerror = function () { /* onclose always follows */ };
        });
        return opening;
    }
    return {
        kind: 'websocket',
        ready: promiseThen(open(), function () { return true; }, function () { return false; }),
        callRaw: function (method, args) {
            return promiseThen(open(), function (s) {
                return new PromiseC(function (resolve, reject) {
                    var id = nextId++;
                    mapSet(pending, id, { resolve: resolve, reject: reject });
                    try { reflectApply(wsSend, s, [jsonStringify({ i: id, m: method, a: args })]); }
                    catch (e) { mapDelete(pending, id); reject(unavailable()); }
                });
            });
        },
        send: function (method, args) {
            promiseThen(open(), function (s) {
                try { reflectApply(wsSend, s, [jsonStringify({ m: method, a: args })]); } catch (e) { /* ignore */ }
            }, function () { /* ignore */ });
        },
        onEvent: function (fn) { arrayPush(handlers, fn); },
        frameToken: function () { return ''; }   /* the server binds the origin to the connection */
    };
}

var transport = (CONFIG.transport === 'websocket') ? makeWebSocketTransport() : makeWebChannelTransport();
if (!transport) return;
