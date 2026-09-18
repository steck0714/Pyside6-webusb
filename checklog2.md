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

```json
{"ok":true,"value":789}
