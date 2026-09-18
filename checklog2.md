# pyside6-webusb Check Log 2

## Comprehensive Validation Report

---

# 1. Purpose

This document records the practical validation work performed during the pyside6-webusb v5.1, v5.2, and v5.3 test series.

The purpose of the test series was to validate not only the existence of `navigator.usb`, but the complete browser-to-Python bridge path used by pyside6-webusb.

The validation covered:

- PySide6 / QtWebEngine initialization
- WebUSBBridge installation
- JavaScript execution
- JavaScript-to-Python result transport
- primitive JavaScript values
- structured JavaScript values
- JSON transport
- Promise settlement
- `navigator.usb`
- WebUSB method exposure
- WebUSB event handling
- WebUSB object identity
- private WebUSB diagnostic APIs
- bridge information
- transfer limits
- granted-device reporting
- URL/origin handling
- frame tracking
- multi-frame pages
- Python WebUSBBridge surface
- Rust acceleration status
- physical USB availability
- F12 / browser-side inspection
- cleanup and object lifetime

The test series also compared multiple harness revisions in order to distinguish implementation behavior from test-harness problems.

---

# 2. Test Scope

The validation was divided into several layers.

```text
Python test harness
        │
        ▼
PySide6
        │
        ▼
QtWebEngine / Chromium
        │
        ▼
JavaScript bridge
        │
        ▼
navigator.usb
        │
        ▼
pyside6-webusb WebUSB implementation
        │
        ▼
Python / PyUSB backend
        │
        ▼
Physical USB device
```

The F12 checks provided an additional observation point from the browser side:

```text
QtWebEngine page
        │
        ├── Python harness inspection
        │
        └── F12 / JavaScript inspection
                │
                ├── navigator.usb
                ├── WebUSB methods
                ├── WebUSB properties
                └── private bridge state
```

This separation was important because a failure in one layer does not necessarily indicate a failure in another layer.

---

# 3. Test Environment

## 3.1 v5.3 Environment

- OS: Windows 11
- Python: 3.15.0rc2
- PySide6: 6.12.0a1.dev1789537996
- Shiboken6: 6.12.0a1.dev1789537996
- Qt Runtime: 6.12.1
- QtWebEngine Chromium: 140.0.7339.225
- PyUSB: 1.3.1
- USB backend: libusb0
- pyside6-webusb: 0.0.5.post1

The v5.3 run therefore used a development PySide6 / Qt 6.12 environment.

---

# 4. Test Results Summary

## 4.1 v5.1

```text
PASS       38
NO DEVICE   6
FAIL        2
```

The major observations were:

- `getDevices()` / private API timeout behavior
- `bridgeInfo()` unavailable during part of transfer-policy testing
- cleanup warnings involving `QWebEnginePage` and `QWebEngineProfile`

---

## 4.2 v5.2

```text
PASS       25
NO DEVICE   1
FAIL       15
NOTE        1
```

The large number of failures was later determined to be strongly affected by a test-harness problem.

The JavaScript result was being handled as a string while Python-side code expected a dictionary-like object.

Observed error:

```text
AttributeError("'str' object has no attribute 'get'")
```

This caused failures to propagate into tests that depended on the incorrectly interpreted result.

A separate issue was also found in `FrameOriginTracker` construction.

---

## 4.3 v5.3

```text
PASS       57
NO DEVICE   5
FAIL        1
NOTE        1
```

Overall:

```text
PASS WITH FAILURES
```

The v5.3 result was substantially cleaner after the JavaScript result transport and tracker-construction issues were addressed.

---

# 5. Test Execution: QtWebEngine Initialization

The first stage was to establish a functioning QtWebEngine environment.

The following components were tested:

- Chromium
- `QWebEngineProfile`
- `QWebEnginePage`
- `QWebEngineView`

Results:

```text
Chromium             PASS
QWebEngineProfile    PASS
QWebEnginePage       PASS
QWebEngineView       PASS
```

A dedicated profile was used:

```text
pyside6_webusb_v53
```

The HTTPS test page:

```text
https://example.com
```

was successfully loaded.

Result:

```text
PASS
```

This established that the WebUSB tests were running inside a functioning QtWebEngine page.

---

# 6. Test Execution: WebUSBBridge Installation

The Python package was imported successfully.

Result:

```text
PASS
```

The WebUSB bridge was installed into the `QWebEnginePage`.

Result:

```text
PASS
```

The installation returned:

```text
WebUSBBridge
```

This established that the Python-side bridge could be attached to the QtWebEngine page.

---

# 7. Test Execution: JavaScript Result Transport

One of the most important findings of the test series was the behavior of JavaScript result transport.

The test harness checked several JavaScript value types.

## 7.1 Number

Test value:

```text
123
```

Observed Python-side value:

```text
123.0
```

Type:

```text
float
```

Result:

```text
PASS
```

---

## 7.2 String

Test value:

```text
hello
```

Observed Python-side value:

```text
'hello'
```

Type:

```text
str
```

Result:

```text
PASS
```

---

## 7.3 Boolean

Test value:

```text
true
```

Observed Python-side value:

```text
True
```

Result:

```text
PASS
```

---

## 7.4 Null

JavaScript:

```text
null
```

was returned through the QtWebEngine result mechanism.

The harness observed an empty-string-like representation on the Python side.

This was recorded as:

```text
PASS
```

The result demonstrates that JavaScript `null` does not necessarily arrive as a native Python `None` through this transport path.

---

## 7.5 Object

A raw JavaScript object was tested.

The result was returned as a string representation rather than automatically becoming the Python dictionary structure expected by the original harness.

This behavior became especially important in v5.2.

---

## 7.6 Array

A raw JavaScript array was also tested.

As with objects, structured JavaScript data did not automatically arrive as a Python-native list in the form expected by the original test harness.

---

# 8. v5.2 Structured-Result Failure

During v5.2, Python-side code attempted dictionary operations on returned JavaScript data.

The resulting exception was:

```text
AttributeError("'str' object has no attribute 'get'")
```

This was initially capable of making several apparently unrelated WebUSB tests fail.

The important conclusion was that the failure chain was:

```text
JavaScript object
        ↓
QtWebEngine result
        ↓
Python string
        ↓
Python code expects dict
        ↓
AttributeError
        ↓
later checks fail
```

Therefore the v5.2 failure count could not be interpreted as fifteen independent WebUSB implementation failures.

This was a test-harness / transport interpretation issue.

---

# 9. JSON Transport

The v5.3 harness changed the structured-data transport to explicit JSON serialization.

The JavaScript side used:

```text
JSON.stringify(...)
```

A test object was successfully transported as:

```text
{"ok":true,"value":789}
```

The Python side then parsed the JSON representation.

Result:

```text
PASS
```

This was a major improvement in the test methodology.

It established a clear boundary:

```text
JavaScript object
        ↓
JSON.stringify()
        ↓
string transport
        ↓
JSON parsing
        ↓
Python dictionary
```

This prevented the v5.2 `str.get()` failure from cascading into later tests.

---

# 10. Promise Settlement

Promise behavior was explicitly tested in v5.3.

## 10.1 Promise.resolve()

Test:

```text
Promise.resolve(123)
```

Result:

```text
PASS
```

Resolved value:

```text
123
```

---

## 10.2 Promise Microtask

A Promise resolved through a microtask was also tested.

Resolved value:

```text
456
```

Result:

```text
PASS
```

This established that the harness can wait for asynchronous JavaScript Promise completion.

This is particularly relevant because WebUSB methods such as:

```text
navigator.usb.getDevices()
navigator.usb.requestDevice()
```

use Promise-based APIs.

---

# 11. WebUSB Injection

After bridge installation, the page-side WebUSB object was inspected.

The v5.3 JavaScript environment reported:

```text
navigatorUsb: true
navigatorUsbType: "object"
```

Result:

```text
PASS
```

This established that the WebUSB surface was actually present in the page.

---

# 12. navigator.usb API Surface

The following functions were detected:

```text
getDevices              function
requestDevice           function
addEventListener        function
removeEventListener     function
```

The following properties were also available:

```text
onconnect
ondisconnect
```

The page was a secure context:

```text
secureContext: true
```

Result:

```text
PASS
```

---

# 13. navigator.usb Own Properties

The detected own property names were:

```text
onconnect
ondisconnect
getDevices
requestDevice
addEventListener
removeEventListener
```

This provided direct evidence of the public WebUSB surface exposed by the implementation.

---

# 14. WebUSB Object Identity

The implementation was also inspected for JavaScript object identity.

Observed:

```text
constructor: "Object"
```

and:

```text
navigator.usb instanceof EventTarget
→ false
```

This is an important compatibility observation.

The implementation exposes the required WebUSB surface, but the object does not reproduce the native browser WebUSB prototype identity exactly.

In particular:

```text
navigator.usb instanceof EventTarget
```

was not true in the pyside6-webusb v5.3 environment.

This is different from merely checking whether `addEventListener()` exists.

---

# 15. Private WebUSB API

The page exposed a private diagnostic API.

The following members were detected:

```text
listGrantedDevices
bridgeInfo
explainTransferLimits
```

All three were callable.

Result:

```text
PASS
```

This private API provides diagnostic information beyond the standard WebUSB surface.

---

# 16. bridgeInfo()

The bridge information returned:

```text
available: true
bridgeVersion: "0.0.5.post1"
rustAccelerated: false
```

Result:

```text
PASS
```

This established that the installed WebUSB bridge reported itself as available.

The reported bridge version matched the tested package:

```text
0.0.5.post1
```

---

# 17. Rust Acceleration

The bridge reported:

```text
rustAccelerated: false
```

The direct acceleration check returned:

```text
accelerated = None
version = None
```

Result:

```text
PASS
```

The test therefore did not demonstrate active Rust acceleration in this environment.

The tested configuration should be regarded as the non-Rust-accelerated path for this run.

---

# 18. getDevices()

The following call was tested:

```text
navigator.usb.getDevices()
```

Result:

```text
PASS
```

Returned device count:

```text
0
```

No physical USB device was connected during the test.

Therefore the result means:

```text
getDevices() executed successfully
AND
the current granted-device list was empty
```

The empty list was not treated as an implementation failure.

---

# 19. requestDevice()

Multiple filter configurations were tested.

## 19.1 Empty Filter Array

Test:

```text
navigator.usb.requestDevice({filters: []})
```

Observed:

```text
SecurityError:
Must be handling a user gesture to call navigator.usb.requestDevice().
```

Classification:

```text
NO DEVICE
```

The request reached the user-activation restriction before a physical device could be selected.

---

## 19.2 vendorId Filter

A request using a `vendorId` filter was tested.

The user-gesture restriction was observed.

Classification:

```text
NO DEVICE
```

---

## 19.3 vendorId + productId

A request using both:

```text
vendorId
productId
```

was tested.

The same user-gesture restriction prevented actual device selection.

Classification:

```text
NO DEVICE
```

---

## 19.4 classCode

A request using:

```text
classCode
```

was tested.

The same user-gesture restriction prevented physical device selection.

Classification:

```text
NO DEVICE
```

---

# 20. requestDevice() Without filters

The following case was tested:

```text
navigator.usb.requestDevice()
```

The implementation returned:

```text
TypeError:
required member filters is undefined.
```

Result:

```text
FAIL
```

This was the only v5.3 FAIL.

The failure is deterministic and does not depend on physical USB hardware.

It therefore differs from the `NO DEVICE` cases.

The observed behavior can be summarized as:

```text
filters omitted
        ↓
required WebUSB argument absent
        ↓
TypeError
```

The test harness currently records this as a FAIL because the test expected a different result.

---

# 21. User Gesture Enforcement

The requestDevice tests demonstrated that user activation is enforced.

Observed message:

```text
Must be handling a user gesture to call navigator.usb.requestDevice().
```

This is an important distinction from a bridge that simply exposes a callable function.

The implementation did not allow the test harness to open the chooser from an arbitrary non-user-gesture context.

Actual chooser testing therefore remained unavailable in this run.

---

# 22. USB Event Listener Tests

The following event listener operations were tested:

```text
connect listener
disconnect listener
```

Results:

```text
connect listener       PASS
disconnect listener    PASS
```

Observed event counts:

```text
connect       0
disconnect    0
```

Because no physical USB device was connected or disconnected, actual hardware event delivery was not tested.

The test confirms listener registration rather than physical hotplug behavior.

---

# 23. listGrantedDevices()

The private diagnostic API:

```text
listGrantedDevices()
```

returned:

```text
[]
```

Result:

```text
PASS
```

This is consistent with the absence of a physical USB device and corresponding granted device.

---

# 24. Transfer Limits

The bridge reported:

```text
chromeCompatibleWarnThreshold:
33554432

hostSafetyHardLimit:
536870912

controlTransferMaxLength:
65535
```

Equivalent values:

```text
32 MiB
512 MiB
65535 bytes
```

The transfer-policy test passed.

Result:

```text
PASS
```

These limits are exposed independently of physical USB hardware.

---

# 25. explainTransferLimits()

The private diagnostic API:

```text
explainTransferLimits()
```

returned the same transfer-limit information.

Result:

```text
PASS
```

This confirmed that transfer-policy information can be queried through the bridge's diagnostic interface.

---

# 26. URL-to-Origin Conversion

The origin handling code was tested with multiple URL types.

## HTTPS URL

Input:

```text
https://example.com/path/page.html
```

Output:

```text
https://example.com
```

Result:

```text
PASS
```

---

## HTTP URL With Port

Input:

```text
http://example.com:8080/test
```

Output:

```text
http://example.com:8080
```

Result:

```text
PASS
```

---

## about:blank

Input:

```text
about:blank
```

Output:

```text
None
```

Result:

```text
PASS
```

---

## data URL

Input:

```text
data:text/html,test
```

Output:

```text
None
```

Result:

```text
PASS
```

---

# 27. FrameOriginTracker

The v5.2 test exposed an incorrect constructor usage.

The tracker was instantiated without the required page argument.

The v5.3 test corrected this to:

```text
FrameOriginTracker(page)
```

Result:

```text
PASS
```

The tracker was then wired:

```text
wire()
→ PASS
```

A rescan was performed:

```text
rescan()
→ PASS
```

This established that the tracker can be initialized against the active `QWebEnginePage`.

---

# 28. Multi-frame Test

A multi-frame page was tested.

Observed:

```text
origin:
https://example.com

frameCount:
2
```

Both iframe URLs were:

```text
https://example.com/
```

Result:

```text
PASS
```

This confirmed that the frame/origin tracking path works with more than one frame in the tested environment.

---

# 29. Python WebUSBBridge Surface

The Python-side `WebUSBBridge` object was inspected.

Results:

```text
WebUSBBridge object      PASS
public API surface       PASS
```

Reported public member count:

```text
75
```

This confirmed that the Python-side bridge object is present and exposes a substantial API surface in the tested environment.

---

# 30. F12 / Browser-Side Validation

The project was also examined from the browser-side JavaScript environment through F12 / Developer Tools.

This was important because Python-side tests alone do not prove that the expected objects are actually exposed inside the page.

The F12 checks were based on the actual browser-side WebUSB inspection performed during the project validation.

These checks are recorded separately from the v5.3 Python harness counts.

---

# 31. F12: fox-webusb navigator.usb Inspection

The fox-webusb browser-side implementation was inspected through F12.

Observed:

```text
navigator.usb
→ [object USB]
```

The constructor was observed as:

```text
USB
```

The prototype exposed:

```text
getDevices
requestDevice
onconnect
ondisconnect
```

This demonstrated that the fox-webusb browser surface was directly observable from the page's JavaScript environment.

---

# 32. F12: fox-webusb getDevices()

The browser-side F12 test called:

```text
navigator.usb.getDevices()
```

Observed:

```text
[]
```

This was consistent with the absence of a granted/available physical USB device.

The Promise-based call itself completed successfully.

---

# 33. F12: fox-webusb requestDevice()

The browser-side F12 test also exercised:

```text
navigator.usb.requestDevice()
```

and the empty-filter form.

Without an appropriate user gesture, the observed error was:

```text
SecurityError:
requestDevice() must be called from a user gesture
```

This confirmed the user-activation requirement at the browser-side level as well.

---

# 34. F12: fox-webusb Event Handling

The F12 browser-side test checked the WebUSB event listener surface.

The event listener test passed.

The available event properties included:

```text
onconnect
ondisconnect
```

No physical device was connected, so this did not constitute a physical hotplug test.

---

# 35. F12: fox-webusb WebUSB Global Constructors

The fox-webusb F12/WPT-inspired inspection also checked standard WebUSB constructor globals.

The following were observed as undefined in the fox-webusb browser environment:

```text
USB
USBDevice
USBConfiguration
USBInterface
USBAlternateInterface
USBEndpoint
```

This was recorded as an implementation-surface observation.

It demonstrates that fox-webusb's exposed surface differs from the browser environment in which those standard WebUSB constructor globals are normally present.

---

# 36. F12: awawausb Comparison

The browser-side F12 checks also provided a comparison point with awawausb.

The awawausb environment reported:

```text
secureContext: true
navigator.usb: [object EventTarget]
```

The following constructor globals were present as functions:

```text
USB
USBDevice
USBConfiguration
USBInterface
USBAlternateInterface
USBEndpoint
```

A Promise-based WebUSB check also fulfilled successfully.

This comparison was useful for identifying surface-level differences between the implementations.

It was not used as a pass/fail criterion for pyside6-webusb.

---

# 37. F12: fox-webusb Injection Marker

An additional browser-side inspection found:

```text
globalThis.__foxWebusbInjected
```

The actual value was:

```text
true
```

Its property descriptor was observed as:

```text
value: true
writable: true
enumerable: true
configurable: true
```

This confirmed that the fox-webusb injection marker was present in the page and that its property descriptor was directly observable.

---

# 38. F12: fox-webusb Private Injection Surface

The F12 scan also observed:

```text
navigator.usb
```

and:

```text
USB.prototype.getDevices
USB.prototype.requestDevice
```

as functions in the fox-webusb environment.

The browser-side inspection therefore verified the presence of the injected WebUSB surface independently from the Python test harness.

---

# 39. Relationship Between F12 and pyside6-webusb

The F12 checks and the Python harness checks serve different purposes.

The Python harness verifies:

```text
Python
↓
PySide6
↓
QtWebEngine
↓
bridge
↓
JavaScript
```

The F12 inspection verifies the page-side result:

```text
QtWebEngine page
↓
JavaScript runtime
↓
navigator.usb
↓
WebUSB methods / properties
```

This distinction matters when diagnosing failures.

For example, a Python-side structured-result failure does not necessarily mean `navigator.usb` is broken.

Likewise, the presence of `navigator.usb` in F12 does not prove that physical USB transfers work.

---

# 40. v5.1 Findings

The v5.1 run established that the general bridge environment could be created and tested, but asynchronous and cleanup-related issues remained.

Observed problems included:

```text
getDevices()
private API
```

timeout behavior.

The transfer-policy test also depended on successful access to:

```text
bridgeInfo()
```

Cleanup generated warnings related to WebEngine object lifetime.

At this stage, several layers had not yet been cleanly separated.

---

# 41. v5.2 Findings

The v5.2 run initially appeared to have many failures.

The recorded result was:

```text
PASS       25
NO DEVICE   1
FAIL       15
NOTE        1
```

The most important discovery was:

```text
AttributeError("'str' object has no attribute 'get'")
```

This revealed that the harness was interpreting a JavaScript structured result as though it were already a Python dictionary.

This was a major test-harness issue.

The v5.2 failure count therefore contained cascading failures.

The tracker construction was also incorrect because the page argument was omitted.

---

# 42. v5.3 Corrections

The v5.3 test introduced two important corrections.

## Structured data

JavaScript structured data was explicitly serialized with:

```text
JSON.stringify()
```

and parsed in Python.

## Frame tracker

The tracker was constructed with:

```text
FrameOriginTracker(page)
```

These changes eliminated the major v5.2 cascading failures.

Promise settlement was also explicitly tested.

---

# 43. v5.3 Findings

The v5.3 run produced:

```text
PASS       57
NO DEVICE   5
FAIL        1
NOTE        1
```

The WebUSB surface was present.

The bridge reported:

```text
available: true
```

`getDevices()` executed successfully and returned an empty list.

The requestDevice tests reached the expected user-activation restriction when executed outside a user gesture.

The omitted-`filters` case produced a deterministic TypeError.

Frame/origin handling passed.

Multi-frame handling passed.

Private diagnostics passed.

Transfer-policy reporting passed.

The Python bridge surface passed.

Rust acceleration was not active.

Physical USB I/O remained untested.

---

# 44. Cleanup Testing

The cleanup path was tested after the WebUSB and frame tests.

Basic page/view/profile cleanup completed.

Result:

```text
PASS
```

However, the tracker cleanup exposed an API/lifecycle issue.

The harness attempted:

```text
tracker.disconnect()
```

but `FrameOriginTracker` does not provide a `.disconnect()` method.

This produced:

```text
AttributeError
```

Classification:

```text
NOTE
```

---

# 45. QWebEnginePage Lifetime Observation

After page deletion, a library log appeared:

```text
FrameOriginTracker.rescan:
mainFrame()取得失敗(無視):
libshiboken: Internal C++ object
(PySide6.QtWebEngineCore.QWebEnginePage) already deleted.
```

This demonstrates that a tracker rescan could still reach the page after the underlying C++ `QWebEnginePage` object had already been deleted.

The library ignored the condition, so it did not cause the overall v5.3 test to fail.

Nevertheless, it is a real lifecycle observation.

The relevant object relationship is:

```text
FrameOriginTracker
        │
        ▼
QWebEnginePage
        │
        ▼
Shiboken C++ object lifetime
```

The cleanup order should therefore be reviewed.

---

# 46. Important Distinction: FAIL vs NO DEVICE vs NOTE

The test series produced several categories of result.

## PASS

The tested operation completed as expected.

---

## NO DEVICE

The operation could not proceed to actual hardware behavior because no physical USB device was available or because the device chooser required user activation.

This is not equivalent to an implementation failure.

---

## FAIL

The observed result did not match what the particular harness test expected.

The v5.3 FAIL was:

```text
requestDevice()
filters omitted
→ TypeError
```

---

## NOTE

A non-fatal issue was observed.

The v5.3 NOTE concerned:

```text
FrameOriginTracker
```

cleanup/lifetime handling.

---

# 47. Hardware Testing Status

No physical USB device was connected during the v5.3 run.

Therefore the following could not be validated end-to-end:

```text
USB device chooser
permission grant
physical enumeration
USBDevice.open()
USBDevice.close()
claimInterface()
releaseInterface()
selectConfiguration()
selectAlternateInterface()
control transfers
bulk transfers
interrupt transfers
isochronous transfers
reset
physical connect events
physical disconnect events
hotplug
actual USB data integrity
```

These items remain unverified rather than failed.

---

# 48. What the Current Test Series Proves

The combined test series provides evidence for the following behavior in the tested environment:

```text
PySide6 / QtWebEngine
        ↓
WebUSBBridge installation
        ↓
JavaScript execution
        ↓
Promise settlement
        ↓
JSON structured-data transport
        ↓
navigator.usb
        ↓
WebUSB method surface
        ↓
event listener surface
        ↓
private diagnostics
        ↓
transfer policy
        ↓
frame/origin tracking
        ↓
multi-frame handling
        ↓
Python bridge surface
```

The browser-side F12 work additionally established that the injected WebUSB surfaces can be inspected directly from the JavaScript runtime.

---

# 49. What the Current Test Series Does Not Prove

The test series does not yet prove complete hardware-level WebUSB operation.

In particular, it does not establish that a real USB device can successfully complete:

```text
chooser
permission
open
claim
configuration
transfer
reset
close
```

or that physical hotplug events are delivered correctly.

Those require actual hardware.

---

# 50. Important Compatibility Findings

Several compatibility characteristics were explicitly observed.

## 50.1 navigator.usb exists

```text
true
```

---

## 50.2 navigator.usb is an object

```text
typeof navigator.usb
→ object
```

---

## 50.3 WebUSB methods exist

```text
getDevices
requestDevice
addEventListener
removeEventListener
```

are functions.

---

## 50.4 Event properties exist

```text
onconnect
ondisconnect
```

are exposed.

---

## 50.5 Native EventTarget identity is not reproduced exactly

```text
navigator.usb instanceof EventTarget
→ false
```

---

## 50.6 The bridge reports availability

```text
available: true
```

---

## 50.7 getDevices() works without hardware

```text
[]
```

was returned successfully.

---

## 50.8 requestDevice() enforces user activation

Observed:

```text
SecurityError:
Must be handling a user gesture to call navigator.usb.requestDevice().
```

---

## 50.9 Missing filters produces a deterministic TypeError

Observed:

```text
TypeError:
required member filters is undefined.
```

---

## 50.10 Transfer limits are exposed

```text
33554432
536870912
65535
```

were reported.

---

## 50.11 Frame/origin tracking works

URL-to-origin and multi-frame tests passed.

---

# 51. Harness Findings

The test series also produced important findings about the test harness itself.

## 51.1 JavaScript structured results must be serialized explicitly

The v5.2 failure demonstrated that structured JavaScript results should not be assumed to arrive as Python dictionaries.

The v5.3 JSON approach resolved this.

---

## 51.2 Promise completion must be handled explicitly

Promise settlement was therefore made an explicit test category.

---

## 51.3 FrameOriginTracker requires the page

The correct construction is:

```text
FrameOriginTracker(page)
```

---

## 51.4 Surface reporting has a cosmetic key mismatch

Some v5.3 individual detail fields displayed:

```text
None
```

despite the actual JSON result containing the expected values.

This was caused by a mismatch between the generated check-detail key and the actual JSON property name.

The underlying WebUSB values were present.

---

## 51.5 Tracker cleanup must be handled explicitly

The harness should not call a nonexistent:

```text
tracker.disconnect()
```

method.

Tracker activity should also be prevented from accessing a deleted `QWebEnginePage`.

---

# 52. Cross-Version Interpretation

The progression from v5.1 to v5.3 is significant.

## v5.1

The environment worked sufficiently to perform meaningful testing, but timeout and cleanup issues obscured some results.

---

## v5.2

The test harness exposed a structured JavaScript-result problem.

This produced cascading Python exceptions.

The apparent failure count was therefore larger than the number of independent implementation problems.

---

## v5.3

The structured-result path was corrected with explicit JSON serialization.

Promise handling was explicitly tested.

FrameOriginTracker construction was corrected.

The result became:

```text
57 PASS
5 NO DEVICE
1 FAIL
1 NOTE
```

The remaining failures and notes became much more localized and interpretable.

---

# 53. Final Test Matrix

| Area | v5.3 Result | Notes |
|---|---|---|
| Chromium | PASS | QtWebEngine initialized |
| QWebEngineProfile | PASS | Dedicated profile |
| QWebEnginePage | PASS | Page created |
| QWebEngineView | PASS | View created |
| WebUSBBridge import | PASS | Python package available |
| WebUSBBridge install | PASS | Installed into page |
| HTTPS page load | PASS | example.com |
| JS primitive transport | PASS | Number/string/boolean/etc. |
| JS structured transport | PASS | Explicit JSON |
| Promise.resolve | PASS | Resolved value received |
| Promise microtask | PASS | Resolved value received |
| navigator.usb | PASS | Object present |
| WebUSB methods | PASS | Required methods present |
| Event properties | PASS | onconnect/ondisconnect |
| EventTarget identity | Observation | `instanceof EventTarget` false |
| getDevices() | PASS | Empty list |
| requestDevice() | NO DEVICE | User gesture required |
| requestDevice() omitted filters | FAIL | TypeError |
| Event listener registration | PASS | No hardware events |
| bridgeInfo() | PASS | available=true |
| listGrantedDevices() | PASS | Empty list |
| explainTransferLimits() | PASS | Limits returned |
| Transfer policy | PASS | Limits enforced/reported |
| URL origin conversion | PASS | Multiple URL forms |
| FrameOriginTracker | PASS | Page supplied |
| Frame tracker wire | PASS | Wired |
| Frame tracker rescan | PASS | Rescan completed |
| Multi-frame | PASS | 2 frames |
| Python bridge surface | PASS | 75 public members |
| Rust acceleration | Not active | `false` |
| Physical USB | NO DEVICE | No hardware |
| Cleanup | PASS | Basic cleanup |
| Tracker cleanup | NOTE | Lifecycle issue |

---

# 54. F12 / Browser-Side Findings Matrix

| F12 Check | Observation |
|---|---|
| fox-webusb `navigator.usb` | `[object USB]` |
| fox-webusb constructor | `USB` |
| fox-webusb `getDevices()` | `[]` |
| fox-webusb `requestDevice()` | User-gesture SecurityError without activation |
| fox-webusb event listener test | PASS |
| fox-webusb `secureContext` | `true` |
| fox-webusb standard WebUSB constructors | Observed as undefined |
| awawausb `navigator.usb` | `[object EventTarget]` |
| awawausb WebUSB constructors | Present as functions |
| awawausb Promise check | Fulfilled |
| `__foxWebusbInjected` | `true` |
| injection marker descriptor | value/writable/enumerable/configurable all true |
| fox-webusb `USB.prototype.getDevices` | function |
| fox-webusb `USB.prototype.requestDevice` | function |

These F12 results are browser-side observations and are kept separate from the v5.3 Python harness result counts.

---

# 55. Remaining Issues

## 55.1 Physical USB validation

A real USB device is still required for end-to-end testing.

---

## 55.2 User gesture test path

A dedicated user-gesture-driven test is required if actual `requestDevice()` chooser behavior is to be tested.

---

## 55.3 requestDevice() argument compatibility

The omitted-`filters` behavior should be explicitly classified against the intended API compatibility requirements.

Current observed result:

```text
TypeError:
required member filters is undefined.
```

---

## 55.4 EventTarget compatibility

The current implementation reports:

```text
navigator.usb instanceof EventTarget
→ false
```

This should remain documented as a compatibility observation.

---

## 55.5 FrameOriginTracker lifecycle

The tracker/page destruction sequence should be reviewed.

In particular:

```text
FrameOriginTracker
```

should not continue to access:

```text
QWebEnginePage
```

after the page has been destroyed.

---

## 55.6 Harness surface-reporting bug

The check-detail property mapping should be corrected so that successful values are displayed rather than `None`.

---

# 56. Next Hardware Validation

The next major test stage should use an actual USB device.

The desired end-to-end sequence is:

```text
User gesture
      ↓
navigator.usb.requestDevice()
      ↓
Device chooser
      ↓
Permission
      ↓
USBDevice
      ↓
getDevices()
      ↓
open()
      ↓
selectConfiguration()
      ↓
claimInterface()
      ↓
transfer
      ↓
verify returned data
      ↓
releaseInterface()
      ↓
close()
```

Additional tests should cover:

```text
connect
disconnect
hotplug
reset
controlTransfer
bulkTransfer
interruptTransfer
isochronousTransfer
```

Only a physical device can validate these portions of the stack.

---

# 57. Final Assessment

The v5.3 test series provides a substantially clearer validation result than v5.1 and v5.2.

The most important discovery was not simply the increase from:

```text
25 PASS
```

to:

```text
57 PASS
```

The important discovery was the separation of the different failure classes.

The v5.2 results demonstrated that JavaScript structured-result transport was a major source of cascading harness failures.

The v5.3 JSON transport correction resolved that class of problem.

The v5.3 test then demonstrated successful operation of:

```text
PySide6
QtWebEngine
WebUSBBridge
JavaScript execution
JSON transport
Promise settlement
navigator.usb
WebUSB methods
WebUSB events
private diagnostic API
transfer-policy reporting
origin handling
FrameOriginTracker
multi-frame handling
Python bridge surface
```

The browser-side F12 work additionally demonstrated that WebUSB injection and the exposed browser-side objects can be inspected directly from the JavaScript environment.

At the same time, the test series identified several concrete limitations:

```text
navigator.usb instanceof EventTarget
→ false

requestDevice() without filters
→ TypeError

Rust acceleration
→ not active

physical USB
→ not tested

FrameOriginTracker cleanup
→ lifecycle issue
```

The five `NO DEVICE` results should not be interpreted as implementation failures because no physical USB device was connected and the requestDevice tests were also constrained by the browser's user-activation requirement.

The current result is therefore best described as:

```text
SUCCESSFUL API / BRIDGE-LEVEL VALIDATION
WITH ONE DETERMINISTIC TEST FAILURE,
ONE CLEANUP NOTE,
AND PHYSICAL USB FUNCTIONALITY STILL UNVERIFIED
```

---

# 58. Overall Conclusion

The check series successfully progressed from a partially diagnosable v5.1 environment through the problematic v5.2 harness revision to the substantially cleaner v5.3 validation.

The testing established that the pyside6-webusb bridge can be installed into a PySide6 / QtWebEngine page, expose `navigator.usb`, communicate between JavaScript and Python, handle Promise-based operations, expose diagnostic information, track origins and frames, and report transfer policy information.

The tests also established that the browser-side surface is observable through F12 and that the project contains detectable differences from native WebUSB implementations, including the `EventTarget` prototype relationship.

The remaining work is now concentrated rather than diffuse.

The next major unknown is no longer basic bridge initialization or JavaScript transport.

It is the behavior of the bridge when connected to an actual physical USB device.

Until that hardware test is performed, the validation should be considered an API/bridge-level validation rather than a complete end-to-end WebUSB hardware validation.