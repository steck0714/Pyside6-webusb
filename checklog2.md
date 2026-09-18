# pyside6-webusb Check Log 2

## Environment

- OS: Windows 11
- Python: 3.15.0rc2
- PySide6: 6.12.0a1.dev1789537996
- Shiboken6: 6.12.0a1.dev1789537996
- Qt Runtime: 6.12.1
- QtWebEngine Chromium: 140.0.7339.225
- PyUSB: 1.3.1
- USB Backend: libusb0
- pyside6-webusb: 0.0.5.post1

---

## Result Summary

| Result | Count |
|---|---:|
| PASS | 57 |
| NO DEVICE | 5 |
| FAIL | 1 |
| NOTE | 1 |
| Overall | **PASS WITH FAILURES** |

---

## 1. QWebEngine / Installation

- Chromium: PASS
- QWebEngineProfile: PASS
- QWebEnginePage: PASS
- QWebEngineView: PASS
- WebUSBBridge import: PASS
- `install(page)`: PASS
- `https://example.com` load: PASS

---

## 2. JavaScript Transport

### Raw JS

The following raw JavaScript values were tested:

- Number: PASS
- String: PASS
- Boolean: PASS
- Null: PASS
- Object: PASS
- Array: PASS

Raw objects and arrays are not directly returned as Python objects.
The harness uses explicit JSON transport for structured values.

### JSON Transport

Object transport using `JSON.stringify()`:

    {"ok":true,"value":789}

Result: PASS

---

## 3. Promise Settlement

- `Promise.resolve(123)`: PASS
- Promise microtask (`456`): PASS

Promise settlement and retrieval of resolved values were confirmed.

---

## 4. WebUSB Surface

The following WebUSB surface was detected:

    navigator.usb            true
    navigator.usb type       object
    getDevices               function
    requestDevice            function
    addEventListener         function
    removeEventListener      function
    constructor              Object
    instanceof EventTarget   false
    onconnect                true
    ondisconnect             true
    secureContext            true
    Qt type                  object
    transport type            object
    QWebChannel type         function
    private API              object

### Own Properties

    onconnect
    ondisconnect
    getDevices
    requestDevice
    addEventListener
    removeEventListener

### Private API

    listGrantedDevices
    bridgeInfo
    explainTransferLimits

The WebUSB surface is present and operational.

> Some individual harness detail fields display `None` because of a property-name mapping issue. The actual JSON result contains the expected values. This is not considered a WebUSB implementation failure.

---

## 5. getDevices()

    count = 0

Result: PASS

No physical USB device was connected, so an empty device list was expected.

---

## 6. requestDevice()

| Test | Result |
|---|---|
| `filters=[]` | NO DEVICE |
| filters omitted | **FAIL** |
| vendorId | NO DEVICE |
| vendorId + productId | NO DEVICE |
| classCode | NO DEVICE |

### User Gesture

For `requestDevice()` calls such as `filters=[]`, the following was observed:

    SecurityError:
    Must be handling a user gesture to call navigator.usb.requestDevice().

### filters omitted

When `filters` is omitted:

    TypeError:
    required member filters is undefined.

This FAIL concerns API input validation and is distinct from the absence of a physical USB device.

---

## 7. Events

- Connect listener registration: PASS
- Disconnect listener registration: PASS
- Connect count: 0
- Disconnect count: 0

No physical USB device was connected, so actual event dispatch was not observed.

---

## 8. Private Debug API

The following APIs were verified:

    bridgeInfo()
    listGrantedDevices()
    explainTransferLimits()

All: PASS

### bridgeInfo()

    available: true
    bridgeVersion: 0.0.5.post1
    rustAccelerated: false

### Transfer Limits

    chromeCompatibleWarnThreshold: 33554432
    hostSafetyHardLimit:           536870912
    controlTransferMaxLength:      65535

Transfer policy: PASS

---

## 9. Frame / Origin

### URL → Origin

    https://example.com/path/page.html
    → https://example.com

    http://example.com:8080/test
    → http://example.com:8080

    about:blank
    → None

    data:text/html,test
    → None

All tests: PASS

### FrameOriginTracker

- `FrameOriginTracker(page)`: PASS
- `wire()`: PASS
- `rescan()`: PASS

---

## 10. Multi-frame

    origin: https://example.com
    frameCount: 2
    iframe src: https://example.com/

Result: PASS

---

## 11. Python WebUSBBridge

- WebUSBBridge object: PASS
- Python API surface: PASS
- Public API count: 75

---

## 12. Rust Acceleration

    accelerated = None
    version = None

Result: PASS

Rust acceleration was not confirmed as enabled in this environment.

---

## 13. Physical USB

Result:

    NO DEVICE

Because no physical USB device was connected, the following were not tested:

- Device chooser
- Permission / grant
- `open()`
- `claimInterface()`
- Control transfers
- Bulk transfers
- Interrupt transfers
- Reset
- Hotplug

---

## 14. Cleanup

Basic Page / View / Profile cleanup: PASS

However, one NOTE occurred:

    AttributeError

`FrameOriginTracker` does not provide a `.disconnect()` method.

A second cleanup-related log appeared after page deletion:

    libshiboken: Internal C++ object
    (PySide6.QtWebEngineCore.QWebEnginePage) already deleted.

This indicates that a tracker rescan still attempted to access the deleted page.

Tracker lifecycle and cleanup ordering should be improved.

---

# 15. v5.1 → v5.2 → v5.3

## v5.1

    PASS 38
    NO DEVICE 6
    FAIL 2

Main issues:

- `getDevices()` / private API timeouts
- Transfer policy failure because `bridgeInfo` was unavailable
- Cleanup warning related to Profile / Page destruction order

---

## v5.2

    PASS 25
    NO DEVICE 1
    FAIL 15
    NOTE 1

Main issues:

- JavaScript results were returned as strings in cases where the harness expected objects
- `AttributeError("'str' object has no attribute 'get'")`
- `FrameOriginTracker` was instantiated without the required page argument
- These issues caused cascading failures across multiple tests

---

## v5.3

    PASS 57
    NO DEVICE 5
    FAIL 1
    NOTE 1

v5.3 addressed the major v5.2 issues by introducing:

- Explicit `JSON.stringify()` for JavaScript object transport
- Promise settlement testing
- Correct `FrameOriginTracker(page)` construction
- Re-validation of the WebUSB surface
- Re-validation of the private debug API

As a result, the cascading failures seen in v5.2 were largely eliminated.

---

# 16. Remaining Issues

## Harness

1. Decide how the omitted-`filters` `requestDevice()` case should be classified.
2. Fix the WebUSB surface check-detail property mapping.
3. Review the `FrameOriginTracker` lifecycle / cleanup API.
4. Ensure tracker callbacks / rescans are stopped before deleting the page.

## Physical USB

A physical USB device is required to additionally test:

- Device chooser
- Permission / grant
- Open / claim
- Control transfers
- Bulk / interrupt transfers
- Reset
- Connect / disconnect
- Hotplug

---

# 17. Conclusion

The v5.3 check confirmed the basic operation of the following components on PySide6 / QtWebEngine:

- WebUSB bridge surface
- JavaScript transport
- JSON transport
- Promise settlement
- `navigator.usb`
- `getDevices()`
- WebUSB event listeners
- Private debug API
- Transfer policy
- Frame / origin tracking
- Multi-frame handling
- Python WebUSBBridge surface

The remaining FAIL is:

    requestDevice()
    filters omitted
    → TypeError

This is different from the `NO DEVICE` results caused by the absence of a physical USB device.

A cleanup NOTE also remains around the `FrameOriginTracker` lifecycle.

Because no physical USB device was connected, this log does not verify actual USB I/O, device chooser behavior, permission granting, transfers, reset, or hotplug behavior.