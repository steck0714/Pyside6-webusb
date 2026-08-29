# pyside6-webusb

**Status:** `0.0.4a0` — early beta, working and tested (see [CHANGELOG.md](CHANGELOG.md)),
but young. Treat pre-1.0 the way you'd treat any early-stage library. Isochronous transfer
support in particular has not been verified against real hardware — see CHANGELOG.

A [WebUSB API](https://wicg.github.io/webusb/) implementation for **PySide6 / QtWebEngine**
apps.

QtWebEngine (the Chromium build PySide6 ships) does not implement `navigator.usb` — Chromium
itself only ships WebUSB in the full Chrome/Chromium *browser* shell, not in the embeddable
`WebEngine` component. If you're building a PySide6 app with a `QWebEngineView` and the page
you're loading expects `navigator.usb` to exist (device-configuration tools, firmware
flashers, hardware dashboards, etc.), it silently won't. This package fills that gap:

- A **Python bridge** (`WebUSBBridge`) that talks to real hardware via
  [pyusb](https://github.com/pyusb/pyusb)/libusb, exposed to the page over `QWebChannel`.
- A **JavaScript polyfill** that makes `navigator.usb` behave like the real thing — same
  classes, same method names, same `DOMException` names, same permission model.
- A native **device chooser dialog** and **per-origin permission store**, so pages only ever
  see the one device the user explicitly picks — never a raw list of everything plugged in.

```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from pyside6_webusb import install

view = QWebEngineView()
install(view.page())      # <- that's the entire integration
view.load("https://your-site.example")
```

## Why this exists / provenance

This was extracted and generalized from the WebUSB implementation inside
[`openweb`](.), a PySide6-based custom browser, where it went through a security audit and
several rounds of hardening (protected device classes, a known-security-key blocklist,
per-origin permission storage, and a line-by-line comparison against the
[WICG WebUSB spec](https://wicg.github.io/webusb/) and Chromium's blocklist source). This
package is that same, already-tested implementation, with the browser-specific bits removed
so it can be dropped into any PySide6 app.

## Installation

```bash
pip install pyside6-webusb
```

(or, from a clone of this repo: `pip install -e .`). Requires `PySide6-Essentials`,
`PySide6-Addons` (for `QtWebEngine`/`QtWebChannel`) and `pyusb`, which are pulled in
automatically. On Linux you'll also need `libusb-1.0` installed at the OS level (`apt install
libusb-1.0-0` or equivalent) — pyusb links against it.

## API

### `install(page, browser_window=None, settings_organization="pyside6-webusb", settings_application="WebUSBBridge", qwebchannel_js=None) -> WebUSBBridge | None`

The only function most apps need. Wires up `navigator.usb` on the given `QWebEnginePage`.

- **page**: the `QWebEnginePage` (or `view.page()`) to install onto.
- **browser_window**: optional, but recommended if your `QWebEnginePage` lives inside a
  `QMainWindow`/`QWidget` — pass that window (e.g. `install(view.page(), browser_window=self)`
  from inside your window's `__init__`). It's used for two independent things:
  1. **Parenting the device-chooser dialog**, if `browser_window` is an actual `QWidget`.
     Without this, the dialog falls back to `QApplication.activeWindow()`, which some
     platforms/window managers don't keep reliably in sync with an async JS→Python call (the
     dialog still works, but can end up without a parent and easy to lose behind other
     windows — see the `0.0.4` CHANGELOG entry for the reported symptom and full fallback
     chain: `browser_window` → `activeWindow()` → any visible top-level widget → none).
  2. **Settings storage**: if it (or a non-widget object you pass instead) has a `.settings`
     attribute (a `QSettings` instance), permission grants are stored there instead of a
     package-local `QSettings`. This half of the contract predates 1. and doesn't require a
     `QWidget` — a plain settings-holder object is still fine here, it just won't be used for
     dialog parenting.
- **settings_organization / settings_application**: identify the fallback `QSettings` store
  used when `browser_window` isn't given, or doesn't have a `.settings` attribute. Set these
  to your own app's identity so permission data lands in *your* app's settings file, not a
  generic one.
- **qwebchannel_js**: almost never needed — by default `install()` reads `qwebchannel.js`
  straight out of your Qt installation's built-in resources
  (`:/qtwebchannel/qwebchannel.js`, the same mechanism Qt's own C++ examples use). Pass this
  explicitly only if that lookup fails in your environment.
- **Returns** the created `WebUSBBridge` (handy for tests / introspection), or `None` if
  `QWebChannel` itself isn't available in your Qt install — WebUSB just won't work on that
  page, but your app won't crash.

Call `install()` once per page (e.g. in whatever function creates your `QWebEngineView` /
`QWebEnginePage`).

### Lower-level pieces

If you need more control than `install()` gives you, the pieces it wires together are all
public: `pyside6_webusb.bridge.WebUSBBridge`, `pyside6_webusb.polyfill.WEBUSB_POLYFILL_JS`,
`pyside6_webusb.chooser_dialog.WebUsbDeviceChooserDialog`, and the pure-logic helpers in
`pyside6_webusb.hardening` (filter matching, blocklist checks, descriptor building — all
independent of Qt, so you can unit test against them without a display).

## Security model

- **`navigator.usb` works inside iframes again, safely.** `0.0.2b0` disabled it entirely
  after finding that a cross-origin iframe could impersonate the top-level page's origin (no
  way existed to tell which frame a `QWebChannel` call came from). `0.0.3b0` implements real
  per-frame origin attribution instead of just re-enabling the old, vulnerable check — see
  [`frame_origin.py`](src/pyside6_webusb/frame_origin.py) and the `0.0.3b0` CHANGELOG entry
  for the full design and what it took to verify against a real `QWebEnginePage`. On a
  PySide6/Qt version too old to have the signal this depends on
  (`QWebEnginePage.navigationRequested`), it automatically falls back to the old
  main-frame-only behavior rather than running with a broken security boundary.
- **The site never sees your device list.** `getDevices()` only ever returns devices a
  *user* has explicitly picked for that *origin* before. `requestDevice()` always shows a
  native chooser dialog; there is no way for a page to silently enumerate or connect to
  hardware.
- **Origin binding is enforced by Qt, not by the page's word for it.** The bridge reads the
  current origin from `QWebEnginePage.url()` — a page can't claim to be a different origin to
  read another site's granted devices.
- **8 protected interface classes are blocked from `claimInterface()`**, matching WebUSB's
  own [protected classes](https://wicg.github.io/webusb/#h-protected-classes) list: Audio,
  HID, Mass Storage, Hub, Smart Card, Video, Audio/Video, and Wireless Controller. This is the
  same restriction real browsers apply so that WebUSB can't be used to drive your keyboard,
  webcam, external drive, or USB hub out from under the OS.
- **That protection can't be bypassed through `controlTransferIn`/`controlTransferOut`, or
  through plain `transferIn`/`transferOut`/`clearHalt`/`selectAlternateInterface` either.**
  `claimInterface()` rejecting a protected class is meaningless if a page can just send a raw
  transfer (or change the alternate setting) at the same interface instead — so, per the
  spec's own [control transfer validation
  algorithm](https://wicg.github.io/webusb/#control-transfer-validation-algorithm) and real
  Chrome's `USBDevice::EnsureEndpointAvailable()`/`EnsureInterfaceClaimed()` (confirmed by
  reading Blink's actual source), every transfer method and `selectAlternateInterface()`
  require their target interface to actually be claimed, in addition to `requestType: 'class'`
  control requests being checked against the protected-class list regardless of recipient.
- **Known security keys are blocklisted by vendor/product ID**, mirroring Chromium's
  [usb_blocklist.cc](https://chromium.googlesource.com/chromium/src/+/main/services/device/usb/usb_blocklist.cc) —
  these devices don't even appear in the chooser dialog.
- **`requestDevice()` guards against reentrancy.** The chooser dialog runs a nested Qt event
  loop (`QDialog.exec()`); a second call arriving while one is already open for the same page
  (rapid re-invocation, a queued `QWebChannel` message serviced mid-loop, etc.) is rejected
  immediately with `InvalidStateError` instead of opening a second dialog on top of the first.
- **`requestDevice()` requires a real user gesture** (`navigator.userActivation`) and
  validates `options.filters`/`exclusionFilters` per spec before anything reaches the chooser.
- Every `WebUSBBridge` method is wrapped so a Python-side exception can never escape across
  the Qt meta-object boundary and crash your app — failures always come back to JS as a
  rejected promise instead.

None of this is a substitute for judgment about what you expose to what pages — it's the same
baseline model real browsers use, reproduced faithfully.

## Spec compliance notes

This aims to be a faithful `navigator.usb` reproduction, not just "good enough." Specifically
implemented per the [spec text](https://wicg.github.io/webusb/):

- Full `USBDevice`/`USBConfiguration`/`USBInterface`/`USBAlternateInterface`/`USBEndpoint`
  object graph, built from real descriptors (not guessed), including `USBConfiguration
  .configurationName` and `USBAlternateInterface.interfaceName` (read from the device's own
  `iConfiguration`/`iInterface` string descriptors when defined).
- `options.filters` **and** `options.exclusionFilters` matching, including the
  classCode-matches-via-any-interface rule (composite devices that report `0xFF` at the
  device level but a real class per-interface) — not just vendor/product ID.
- `transferIn(endpointNumber, length)` correctly targets the *IN* address for that endpoint
  number (`endpointNumber | 0x80`) rather than the raw number, matching both the spec's own
  algorithm and what the underlying `pyusb`/libusb call actually requires.
- `endpoints` lists never include Control-Transfer-Type descriptors, per the spec's note that
  no `USBEndpoint` object should ever represent one.
- `USBTransferStatus: 'stall'` and `'babble'` are both surfaced as *successful* resolutions
  (per spec — this is how real USB protocols signal recoverable errors), not rejected promises.
  Detected from libusb's `LIBUSB_ERROR_PIPE` (stall) and `LIBUSB_ERROR_OVERFLOW` (babble) via
  `pyusb`, on every IN-direction transfer method (`transferIn`, `controlTransferIn`,
  `isochronousTransferIn` — babble is specifically an IN-direction condition, per spec).
- `USBInterface.alternate` correctly resolves to the alternate setting numbered `0`, not
  whichever one happens to be first in the descriptor.
- `.configuration` reflects the device's *actual* active configuration
  (`get_active_configuration()`), not always the first one in the list.
- Correct `DOMException` names: `SecurityError` only for protected-class/blocklist rejections,
  `InvalidStateError` for a `requestDevice()` call made while a chooser is already open (or an
  unclaimed interface for control transfers), `InvalidAccessError` for an endpoint whose actual
  transfer type doesn't match the method used on it (isochronous endpoints via
  `transferIn`/`Out`, or non-isochronous endpoints via `isochronousTransferIn`/`Out`),
  `IndexSizeError` for an out-of-range endpoint
  number, `NetworkError` for other transfer/claim failures, `NotFoundError` when the user
  cancels the chooser (or an endpoint/interface can't be found or isn't claimed),
  `TypeError` for malformed filters or `packetLengths`, `NotSupportedError` when this
  environment can't actually perform an isochronous transfer (see below).
- `selectConfiguration()` resets which interfaces are considered "claimed" on success, per
  spec — claiming interface `2` under one configuration doesn't leave interface `2` treated as
  claimed after switching to a different configuration that happens to reuse that number.

Known, deliberate simplifications (things a from-scratch from-the-spec implementation would
add, that didn't seem worth the complexity here):

- **Isochronous transfers (`isochronousTransferIn`/`Out`) are implemented, but best-effort and
  unverified against real hardware.** `pyusb`'s public API has no isochronous method, so this
  reaches `libusb1`'s backend directly through a private `pyusb` attribute
  (`dev._ctx.handle`) — a real exception to the public-API-only approach used everywhere else
  in this codebase. It also only supports **uniform** packet lengths (`pyusb`'s backend can't
  express per-packet lengths that differ), and falls back to `NotSupportedError` if the
  backend/handle aren't available at all. See `CHANGELOG.md`'s `0.0.2b0` entry for the full
  reasoning. If you have an actual isochronous device (USB audio, a webcam's isochronous
  video endpoint, etc.), trying it and reporting back would materially increase confidence in
  this feature.
- **The full per-method `DOMException` matrix isn't 100% reproduced** — e.g. calling a method
  on an unopened device reports `NetworkError` rather than the spec's more specific
  `InvalidStateError` in every case. The names that matter for the common
  claim/deny-then-retry flow (`SecurityError` vs `NetworkError`) are correct.
- **No Permissions-Policy `usb-unrestricted` bypass** (the mechanism Isolated Web Apps can use
  to skip the protected-class/blocklist checks). This is deliberate — a general-purpose
  library shouldn't ship an easy way to disable its own hardening.

## Large transfers (WebADB and similar)

WebUSB is commonly used to drive protocols that move substantial amounts of data over bulk
endpoints — [WebADB](https://github.com/yume-chan/ya-webadb)-style Android Debug Bridge
clients being the best-known example, easily moving hundreds of KB to a few MB per
`transferIn`/`transferOut` call (file pushes, `logcat` streams, etc.). As of `0.0.4a0` this is
a first-class concern rather than an afterthought:

- **Wire encoding is base64, not hex**, between the JS polyfill and the Python bridge (an
  internal implementation detail — `transferIn`/`transferOut` still take/return plain
  `ArrayBuffer`/`DataView` per spec either way). Hex was a 2x size expansion; base64 is ~1.33x.
  The JS-side encoder chunks the input (`0x8000` bytes at a time) before handing it to
  `String.fromCharCode.apply()` — calling that unchunked on a large `Uint8Array` throws
  `RangeError: Maximum call stack size exceeded` once you're in WebADB-sized-payload territory
  (confirmed directly in Node: still fine at 100 KB, throws by 300 KB), so this isn't optional.
- **Transfer timeouts scale with payload size** instead of a flat 5 seconds, for
  `transferIn`/`Out` and `controlTransferIn`/`Out`. The spec doesn't expose a timeout concept
  to JS at all for these methods (callers are entitled to expect a slow-but-legitimate transfer
  to just take as long as it takes), but this implementation still has to hand `pyusb` some
  finite value — a flat 5s could cut off a real large-payload transfer on a slow link, while no
  timeout at all risks freezing your app's UI thread if a device stops responding mid-transfer
  (these bridge methods run synchronously on the Qt main thread). The compromise: 5s minimum,
  scaling at a conservative 100 KB/s, capped at 120s.
- **Requested lengths are capped** before this implementation allocates a buffer for them —
  64 MiB for `transferIn`, the spec's own 65535-byte `unsigned short` ceiling for
  `controlTransferIn`, 16 MiB total for `isochronousTransferIn`'s summed `packetLengths`. These
  are this implementation's own defensive limits (not spec requirements) against a
  buggy/malicious page forcing an unbounded host-side allocation with a single call; all three
  are comfortably above realistic single-call payload sizes for WebADB-style usage.

## TypeScript

[`types/webusb-polyfill.d.ts`](types/webusb-polyfill.d.ts) provides ambient
(`declare global`) type declarations for the `navigator.usb` surface this polyfill installs,
transcribed directly from the [WebIDL in the spec source](https://github.com/WICG/webusb/blob/main/index.bs)
rather than written from memory. Since this is a PyPI package rather than an npm one, there's
no `node_modules` resolution to hook into — copy the file into your own TypeScript project
(e.g. `src/types/`) and make sure it's covered by your `tsconfig.json`'s `include`.
[`types/sample-usage.ts`](types/sample-usage.ts) exercises the full surface (device selection,
open/configure/claim, control/bulk/isochronous transfers including a WebADB-sized 300 KB
`transferOut` and the `'babble'` status, connection events) and compiles clean under
`tsc --strict`; [`types/negative-check.ts`](types/negative-check.ts) uses `@ts-expect-error` to
confirm invalid usage (a made-up `USBTransferStatus`, a bad `clearHalt` direction, a
non-`number` `vendorId`) is actually rejected, not just nominally typed — both are real files in
this repo, not just a claim, and both are checked as part of this project's own test run (see
Testing below).

If you'd rather use the plain spec types without any polyfill-specific framing, DefinitelyTyped's
[`@types/w3c-web-usb`](https://www.npmjs.com/package/@types/w3c-web-usb) covers the same surface
generically.

## Testing

On a headless machine (CI, a server without a display, this package's own dev sandbox), set
`QT_QPA_PLATFORM=offscreen` before running anything that imports `PySide6.QtWidgets` —
without it, creating a `QApplication` aborts the process outright rather than raising a
catchable exception. `test_bridge.py` needs a `QApplication` (constructing a `WebUSBBridge`/
`WebUsbDeviceChooserDialog` requires one); `test_hardening.py` and `test_polyfill.js` don't.

```bash
pip install -e ".[dev]"
export QT_QPA_PLATFORM=offscreen   # only needed on a headless machine
python tests/test_hardening.py     # or: pytest tests/test_hardening.py
python tests/test_bridge.py        # or: pytest tests/test_bridge.py
python tests/test_frame_origin.py  # or: pytest tests/test_frame_origin.py
python tests/test_install.py       # or: pytest tests/test_install.py
python tests/test_errors.py        # or: pytest tests/test_errors.py
python tests/extract_polyfill_js.py && node tests/test_polyfill.js
```

To check the TypeScript definitions compile and actually constrain usage (not shipped as an
automated `pytest`/Node test, since it needs a separate `typescript` install — see the
TypeScript section above):

```bash
npm install -g typescript   # or any local install
cd types
tsc --strict --noEmit --lib es2020,dom webusb-polyfill.d.ts sample-usage.ts    # should exit 0
tsc --strict --noEmit --lib es2020,dom webusb-polyfill.d.ts negative-check.ts  # should also exit 0
```

`test_hardening.py`, `test_bridge.py`, and `test_errors.py` run without any GUI or real USB
hardware (fake pyusb-shaped objects stand in for both). `test_polyfill.js` runs the actual
polyfill JS in Node with a mocked `QWebChannel` bridge. `test_install.py` and most of
`test_frame_origin.py` use a lightweight fake page (no real browser engine needed); one test in
`test_frame_origin.py` does spin up a real `QWebEnginePage` (with `--no-sandbox`, since this
sandbox runs as root) to load actual HTML with a cross-origin iframe and confirm it gets
correctly attributed its own origin — that one test alone takes several seconds due to
Chromium startup, which is why it's the only one of its kind rather than a whole suite of them.

All of the above was additionally verified against a **real** `QWebEngineView` + real
`pyusb`/libusb during development (not just mocks) — loading a page, confirming
`navigator.usb`/`navigator.usb.getDevices` exist in its JS context, round-tripping an actual
`getDevices()` call through the real `QWebChannel` bridge end to end, and (as of `0.0.3b0`)
loading a page containing a cross-origin iframe and confirming the iframe gets a distinct,
correctly-attributed origin token separate from the main frame's. The one thing that still
isn't covered by automated tests is the native device-chooser dialog itself (it's a modal
`QDialog` — exercising it needs a real display and a human, or a UI-automation layer neither
this environment nor CI typically has). If you're integrating this into a project with headed
test infrastructure, that's the one gap worth closing.

### What's *not* verified yet: real-world site compatibility

Everything above tests this codebase's own logic (against fakes, or a bare page confirming
the API surface exists). It does **not** answer the actually-important question: does a real,
unmodified site written against Chrome's WebUSB — an Arduino/micro:bit/DFU flashing tool, a
device manufacturer's config page, one of the official WebUSB samples — actually work when
loaded through this bridge against real hardware. That needs a real device, a real display,
and a human clicking through the chooser dialog, none of which this sandboxed environment (or
most CI) has. `examples/compatibility_test.html` is a page you can load through
`examples/minimal_browser.py` (or your own app with `install()` wired up) against a real
device to walk through `requestDevice()` → `open()` → `selectConfiguration()` →
`claimInterface()` → transfers → `forget()`, plus watching connect/disconnect fire on a real
unplug/replug, with pass/fail shown inline. It's a tool for *you* to run this verification, not
a substitute for having run it — treat real-site compatibility as genuinely unverified until
someone does.

## Example

See [`examples/minimal_browser.py`](examples/minimal_browser.py) — a ~60-line runnable app
with an address bar and a self-contained demo page (no external site required) that calls
`getDevices()`/`requestDevice()` and shows the results.

```bash
python examples/minimal_browser.py
```

Point its address bar at `examples/compatibility_test.html` (or a real WebUSB site) with a
device plugged in to manually verify end-to-end compatibility — see the section above.

## License

MIT — see [LICENSE](LICENSE). `qwebchannel.js` is loaded at runtime from your own Qt
installation (BSD-3-Clause, © The Qt Company) and is not redistributed in this repository.
