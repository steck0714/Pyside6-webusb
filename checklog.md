# pyside6-webusb v0.0.4b2 CHECKLOG

## Test Environment

- OS: Windows
- Python: 3.14
- PySide6: 6.11.1
- Web engine: PySide6 QtWebEngine
- Package: pyside6-webusb
- Tested version: 0.0.4b2
- Test method: QtWebEngine DevTools Console
- USB device available: No

---

# 1. Installation

## Package installation

The package was installed and tested in a local PySide6 + QtWebEngine environment.

Status: **PASS**

---

# 2. Python Import

The package was successfully imported.

Observed version:

```text
0.0.4b2
```

Status: **PASS**

---

# 3. navigator.usb Injection

## Test

```js
typeof navigator.usb
```

## Result

```text
object
```

Status: **PASS**

`navigator.usb` was successfully injected into the QtWebEngine JavaScript environment.

---

# 4. Core WebUSB API Availability

## getDevices

### Test

```js
typeof navigator.usb.getDevices
```

### Result

```text
function
```

Status: **PASS**

---

## requestDevice

### Test

```js
typeof navigator.usb.requestDevice
```

### Result

```text
function
```

Status: **PASS**

---

# 5. navigator.usb Object

## Test

```js
navigator.usb
```

## Observed properties

```text
onconnect
ondisconnect
getDevices
requestDevice
addEventListener
...
```

The object was successfully exposed as a JavaScript object containing WebUSB-style methods and event-related properties.

---

# 6. EventTarget Check

## Test

```js
navigator.usb instanceof EventTarget
```

## Result

```text
false
```

Status: **OBSERVED**

The exposed `navigator.usb` object is not currently an instance of the page's `EventTarget` according to this DevTools test.

---

# 7. getDevices()

## Test

```js
navigator.usb.getDevices()
```

## Result

```text
Promise
```

The Promise was later observed as fulfilled.

---

## Test

```js
navigator.usb.getDevices().then(console.log)
```

## Result

```text
[]
```

Status: **PASS**

No USB devices were currently granted to the page.

---

# 8. getDevices() Implementation Observation

## Test

```js
navigator.usb.getDevices
```

## Observed implementation structure

```js
function() {
    return callBridge('listDevices', _frameToken()).then(function(res) {
        return (res.devices || []).map(function(d) {
            return new OpenWebUSBDevice(d);
        });
    });
}
```

Observed bridge flow:

```text
navigator.usb.getDevices()
        |
        v
callBridge('listDevices', _frameToken())
        |
        v
Bridge
        |
        v
Device data
        |
        v
OpenWebUSBDevice objects
```

Status: **OBSERVED**

---

# 9. requestDevice() Required filters Validation

## Test

```js
navigator.usb.requestDevice()
```

## Result

```text
TypeError: Failed to execute 'requestDevice' on 'USB':
required member filters is undefined.
```

Status: **PASS**

The implementation rejects a call where the required `filters` member is missing.

---

# 10. Device Chooser Test

## Test

```js
navigator.usb.requestDevice({filters:[]})
```

## Result

```text
Promise
```

A native device chooser was displayed.

The device selection was cancelled.

The Promise rejected with:

```text
NotFoundError: No device selected.
```

Status: **PASS**

Observed flow:

```text
requestDevice({filters:[]})
        |
        v
Promise returned
        |
        v
Native device chooser
        |
        v
User cancelled selection
        |
        v
NotFoundError
```

---

# 11. Permission State After Cancellation

## Test

```js
navigator.usb.getDevices().then(console.log)
```

## Result

```text
[]
```

Status: **PASS**

No granted USB device appeared after cancelling the device chooser.

---

# 12. __pysideWebUSB Debug Namespace

## Test

```js
Object.getOwnPropertyNames(__pysideWebUSB)
```

## Result

```js
[
    "listGrantedDevices",
    "bridgeInfo",
    "explainTransferLimits"
]
```

Status: **PASS**

Exactly three public own properties were observed.

Current observed debug namespace:

```text
__pysideWebUSB
|
+-- listGrantedDevices()
|
+-- bridgeInfo()
|
+-- explainTransferLimits()
```

---

# 13. bridgeInfo()

## Test

```js
__pysideWebUSB.bridgeInfo()
```

## Result

The Promise fulfilled with:

```js
{
    available: true,
    bridgeVersion: "0.0.4b2",
    rustAccelerated: false,
    transferLimits: {
        chromeCompatibleWarnThreshold: 33554432,
        hostSafetyHardLimit: 536870912,
        controlTransferMaxLength: 65535
    }
}
```

Status: **PASS**

Observed information:

- Bridge available: `true`
- Bridge version: `0.0.4b2`
- Rust acceleration: `false`
- Chrome-compatible warning threshold: `33554432`
- Host safety hard limit: `536870912`
- Maximum control transfer length: `65535`

---

# 14. bridgeInfo() Implementation

## Test

```js
__pysideWebUSB.bridgeInfo.toString()
```

## Result

```js
function() {
    return callBridge('isAvailable').then(function(res) {
        if (typeof console !== 'undefined' && console.log) {
            console.log('[pyside6-webusb] bridge info:', res);
        }
        return res;
    });
}
```

Status: **OBSERVED**

Observed flow:

```text
__pysideWebUSB.bridgeInfo()
        |
        v
callBridge('isAvailable')
        |
        v
Bridge response
        |
        +--> console.log()
        |
        v
Promise result
```

The bridge information is obtained asynchronously through the bridge rather than being observed here as a hard-coded JavaScript result.

---

# 15. listGrantedDevices()

## Test

```js
__pysideWebUSB.listGrantedDevices()
```

## Result

```text
[]
```

The Promise fulfilled with an empty array.

Status: **PASS**

No USB devices were currently granted.

---

# 16. listGrantedDevices() Implementation

## Test

```js
__pysideWebUSB.listGrantedDevices.toString()
```

## Result

```js
function() {
    return navigator.usb.getDevices().then(function(devices) {
        var rows = devices.map(function(d) {
            return {
                vendorId: '0x' + d.vendorId.toString(16),
                productId: '0x' + d.productId.toString(16),
                productName: d.productName,
                manufacturerName: d.manufacturerName,
                serialNumber: d.serialNumber,
                opened: d.opened,
            };
        });
        if (typeof console !== 'undefined' && console.table) console.table(rows);
        return rows;
    });
}
```

Status: **OBSERVED**

Observed flow:

```text
__pysideWebUSB.listGrantedDevices()
        |
        v
navigator.usb.getDevices()
        |
        v
Granted USBDevice objects
        |
        v
Diagnostic rows
        |
        +--> console.table(rows)
        |
        v
Promise result
```

The diagnostic rows contain:

- `vendorId`
- `productId`
- `productName`
- `manufacturerName`
- `serialNumber`
- `opened`

This function uses the public `navigator.usb.getDevices()` API rather than an additional directly observed device-list bridge command.

---

# 17. explainTransferLimits()

## Test

```js
__pysideWebUSB.explainTransferLimits()
```

## Result

The Promise fulfilled successfully.

The console reported:

```text
[pyside6-webusb] Transfer size policy:
transfers up to 536870912 bytes are allowed here.

Real Chrome would reject anything over 33554432 bytes
with DataError.

This implementation instead logs a console warning and
allows the transfer to proceed.
```

The implementation also describes itself as a WebUSB-compatible implementation with more permissive extensions rather than an intentionally exact Chrome clone.

Status: **PASS**

---

# 18. explainTransferLimits() Implementation

## Test

```js
__pysideWebUSB.explainTransferLimits.toString()
```

## Observed implementation

```js
function() {
    return callBridge('isAvailable').then(function(res) {
        var limits = res.transferLimits || {};
        var msg = '[pyside6-webusb] Transfer size policy: transfers up to ' +
            limits.hostSafetyHardLimit + ' bytes are allowed here. Real Chrome ' +
            'would reject anything over ' + limits.chromeCompatibleWarnThreshold +
            ' bytes with DataError -- this implementation instead logs a ' +
            'console.warn() on that specific transfer and lets it proceed, since ' +
            'it is intentionally not a drop-in Chrome clone but a WebUSB-compatible ' +
            'implementation with its own, more permissive extensions. ' +
            'See the pyside6-webusb README/CHANGELOG (v0.0.4b2) for the full reasoning.';
        if (typeof console !== 'undefined' && console.log) console.log(msg);
        return limits;
    });
}
```

Status: **OBSERVED**

Observed flow:

```text
__pysideWebUSB.explainTransferLimits()
        |
        v
callBridge('isAvailable')
        |
        v
transferLimits
        |
        v
JavaScript builds a human-readable explanation
        |
        +--> console.log()
        |
        v
Promise result
```

The transfer-limit explanation is dynamically generated using values returned from the bridge.

---

# 19. Debug API Architecture

The three observed public debug functions have different roles.

```text
bridgeInfo()
    |
    +-- Bridge diagnostic
        |
        +-- callBridge('isAvailable')


listGrantedDevices()
    |
    +-- Public WebUSB API diagnostic wrapper
        |
        +-- navigator.usb.getDevices()
        |
        +-- diagnostic row formatting
        |
        +-- console.table()


explainTransferLimits()
    |
    +-- Bridge diagnostic
        |
        +-- callBridge('isAvailable')
        |
        +-- reads transferLimits
        |
        +-- builds human-readable explanation
```

---

# 20. Current Verification Summary

| Feature | Status |
|---|---|
| Package installation | PASS |
| Python import | PASS |
| Version 0.0.4b2 | PASS |
| navigator.usb injection | PASS |
| navigator.usb object | PASS |
| getDevices function | PASS |
| requestDevice function | PASS |
| getDevices Promise behavior | PASS |
| Empty granted-device list | PASS |
| requestDevice filters validation | PASS |
| Native device chooser | PASS |
| Cancellation handling | PASS |
| Permission state after cancellation | PASS |
| __pysideWebUSB namespace | PASS |
| bridgeInfo() | PASS |
| bridgeInfo() implementation inspection | OBSERVED |
| listGrantedDevices() | PASS |
| listGrantedDevices() implementation inspection | OBSERVED |
| explainTransferLimits() | PASS |
| explainTransferLimits() implementation inspection | OBSERVED |

---

# 21. Verified Relationships

The following relationships were directly observed during DevTools testing:

```text
navigator.usb.getDevices()
        |
        v
callBridge('listDevices', _frameToken())
```

```text
__pysideWebUSB.bridgeInfo()
        |
        v
callBridge('isAvailable')
```

```text
__pysideWebUSB.listGrantedDevices()
        |
        v
navigator.usb.getDevices()
```

```text
__pysideWebUSB.explainTransferLimits()
        |
        v
callBridge('isAvailable')
        |
        v
transferLimits
        |
        v
Human-readable policy explanation
```

---

# 22. Not Yet Verified

No physical USB device was available during this test session.

The following features therefore remain unverified:

- Selecting an actual USB device
- Persistent permission after selecting a device
- `USBDevice.open()`
- `USBDevice.close()`
- Configuration selection
- Interface claiming
- Interface releasing
- Alternate interface selection
- Endpoint transfer operations
- `transferIn()`
- `transferOut()`
- `controlTransferIn()`
- `controlTransferOut()`
- Transfer error handling
- Transfer status handling
- Large transfer behavior
- Warning behavior above the Chrome-compatible threshold
- Hard-limit behavior
- Isochronous transfers
- USB connect events
- USB disconnect events

---

# 23. Current Conclusion

The tested `pyside6-webusb` v0.0.4b2 build successfully exposed a functional WebUSB-style API inside a PySide6 + QtWebEngine environment.

The following were directly observed through DevTools:

```text
navigator.usb
        |
        +-- getDevices()
        |
        +-- requestDevice()
        |
        +-- asynchronous Promise behavior
        |
        +-- request validation
        |
        +-- native device chooser
        |
        +-- cancellation handling
```

The complete currently observed public `__pysideWebUSB` namespace was also tested:

```text
__pysideWebUSB
        |
        +-- bridgeInfo()
        |
        +-- listGrantedDevices()
        |
        +-- explainTransferLimits()
```

All three observed public debug functions were callable and their JavaScript implementations were inspectable through DevTools.

No actual USB device communication was tested in this session because no USB device was available.

Therefore, the current result verifies the API injection, bridge communication paths, chooser behavior, validation behavior, cancellation behavior, permission-list behavior, and observed debug interfaces, while actual USB device communication remains unverified.
