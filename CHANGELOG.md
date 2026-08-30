# Changelog

All notable changes to this project are documented here.

## [0.0.4b0]

Builds directly on `0.0.4a0`'s large-transfer work: extends it with Rust tooling, closes the
one significant gap that work left open (the UI-freeze risk it had explicitly flagged but not
yet fixed), and adds a realistic ADB-protocol-shaped integration test rather than only
arbitrary-blob transfer tests.

### Added

- **Optional Rust (PyO3) acceleration crate**,
  [`native/pyside6_webusb_accel/`](native/pyside6_webusb_accel/): a faster base64 codec for the
  large-transfer wire encoding, plus ADB wire-protocol message-framing helpers
  (`adb_pack_header`/`adb_unpack_header`/`adb_verify_header`/`adb_checksum`/
  `adb_command_name`) for building realistic WebADB-shaped test fixtures — not an ADB client or
  server, no auth/shell handling, just message framing. `bridge.py` tries to `import
  pyside6_webusb_accel` and falls back to the standard-library `base64` module if that import
  fails (`HAVE_RUST_ACCEL`); this package remains fully functional, tests and all, with no Rust
  toolchain present at all. See the README's new "Rust acceleration (optional)" section for the
  build steps and exactly which real reference implementation the ADB field layout/checksum
  behavior was confirmed against (a working, published open-source Rust ADB client, not
  memory — see the crate's own module doc for the specific files read). The crate separates a
  plain-Rust `logic` module (no PyO3 types) from a thin `#[pyfunction]` binding layer
  specifically so `cargo test` can run as ordinary Rust — `pyo3`'s `extension-module` feature
  deliberately doesn't link against `libpython`, which breaks a normal `cargo test` binary if
  `Python::with_gil` shows up directly inside `#[cfg(test)]`. 10 Rust-side unit tests
  (`cargo test`) plus `tests/test_rust_accel.py` (cross-validates against Python's own `base64`
  for sizes 0 to 600 KB, RFC 4648 test vectors, ADB header round-trips/tamper-detection,
  `pytest.importorskip`-guarded so the rest of the suite is unaffected if the crate isn't
  built).
- **`tests/test_bridge.py::test_bulk_transfer_round_trips_realistic_adb_wrte_message`**: sends a
  real ADB `WRTE`-message-shaped payload (24-byte header + 256 KB body, via a pure-Python
  reference implementation of the same framing so this test doesn't require the Rust crate to be
  built) through `bulkTransferOut` on one bridge/fake-device pair and `bulkTransferIn` on
  another, using the real Google USB vendor ID (`0x18D1`) associated with Android/ADB devices,
  and confirms every header field and the full payload survive byte-for-byte — including through
  the chunked-transfer path below, since the payload is well over `BULK_TRANSFER_CHUNK_SIZE`.
  Previous large-transfer tests all used arbitrary-content blobs; this checks the specific shape
  of data this whole line of work (`0.0.4a0`/`0.0.4b0`) is actually motivated by.

### Fixed

- **A large `transferIn`/`transferOut` could freeze the entire app's UI, not just delay the
  page.** `0.0.4a0`'s own changelog entry flagged this directly and accepted it as a tradeoff at
  the time ("no timeout at all risks freezing your app's UI thread... these bridge methods run
  synchronously on the Qt main thread") — scaling the timeout down to something bounded (120s
  worst case) made premature cutoffs less likely but did nothing about the freeze itself for any
  transfer that's slow *for a legitimate reason*, which is exactly the WebADB scenario (pushing
  a multi-hundred-KB file over a real USB link takes real time). Every `@Slot` in this bridge
  runs on the Qt main thread — the same thread painting the window and handling every other
  event — so one `pyusb` call blocking for, say, 10 seconds meant the whole app was unresponsive
  for 10 seconds, with no way to even repaint. Fixed by splitting any `transferIn`/`transferOut`
  over `BULK_TRANSFER_CHUNK_SIZE` (256 KiB) into sub-chunk `pyusb` calls
  (`_chunked_bulk_read`/`_chunked_bulk_write`), calling `QCoreApplication.processEvents()`
  between them. The sub-chunk loop preserves the exact completion semantics a single big call
  would have had: a read sub-chunk that comes back shorter than requested is treated as a short
  packet (USB's own "transfer complete" signal) and ends the loop there, rather than trying to
  keep filling the original requested length — matching what `libusb` itself does internally for
  one large call, just observable in smaller steps from the Python side instead of one opaque
  blocking call. This is a mitigation, not full asynchrony: the main thread still does the actual
  `pyusb` I/O for each sub-chunk, so throughput isn't changed and the UI can still visibly lag on
  a slow link — it's now able to repaint and process other events between sub-chunks rather than
  being fully wedged for the whole transfer. A true non-blocking implementation would need to
  move `pyusb` calls to a worker thread and make the affected `@Slot`s deliver their result
  asynchronously (`QWebChannel` does support this via a `QJSValue` callback parameter instead of
  `result=`, rather than the sync-return pattern every method here currently uses) — that's a
  larger, riskier architecture change than this release's scope; noted here as the natural next
  step rather than attempted under time pressure and shipped half-verified.
- **Reentrancy risk introduced by the fix above.** `processEvents()` can dispatch another
  incoming `QWebChannel` call while a chunked transfer is mid-flight — including, in principle,
  another `transferIn`/`transferOut` call for the *same* handle, which would mean two `pyusb`
  calls against the same device interleaving unpredictably. Guarded with a per-handle
  `_busy_handles` set: a `transferIn`/`transferOut` call for a handle that's already mid-transfer
  is rejected immediately with `InvalidStateError` (no `pyusb` call made at all) rather than
  risking interleaved I/O; transfers to *different* handles are unaffected, and the guard is
  released in a `finally` so it can't leak on an exception/stall/babble path.
  `test_bulk_transfer_reentrant_call_on_busy_handle_is_rejected` triggers this from inside a real
  monkeypatched `QCoreApplication.processEvents()` (a genuine reentrant call, not just a
  pre-set flag) to confirm the guard fires under the actual condition that produces it. Documented
  as a known, deliberately out-of-scope gap for this release: `closeDevice` doesn't check
  `_busy_handles` at all, so a same-handle `closeDevice` reentering during a chunked transfer
  could dispose the device out from under the in-progress transfer loop — the next sub-chunk call
  would then fail with a normal caught exception (not a crash or silent corruption), but it's not
  a clean success path either. Left as-is rather than extending the guard to every method that
  touches `_open_devices` under this release's time budget; see the `closeDevice` docstring.

### Project metadata

- Version bumped to `0.0.4b0` (`packaging.version.Version("0.0.4b")` normalizes to this
  automatically, confirmed the same way as the `0.0.4a0` bump).
- The Rust crate (`native/pyside6_webusb_accel/`) is versioned independently (`0.1.0`) since
  it's a genuinely separate, separately-buildable artifact rather than something released in
  lockstep with the Python package's own version.
- Verified with `rustc`/`cargo` `1.75.0` (Ubuntu 24.04's own `apt` package — `rustup`/
  `static.rust-lang.org` aren't reachable from this environment's network allowlist) and `pyo3`
  `0.27.2`, the newest `pyo3` release line whose MSRV (1.74, unchanged from `0.26.0`) is still
  satisfied by that compiler while also explicitly testing against the Python 3.14 final release
  — confirmed by reading `pyo3`'s own `CHANGELOG.md` rather than guessing a version number.
  `pyo3` `0.28`+ raises MSRV to 1.83, which this environment's `rustc` doesn't satisfy, hence the
  `=0.27.2` pin in `Cargo.toml` rather than an open-ended version requirement.
- `.gitignore` now excludes `native/*/target/` (Rust build output — `Cargo.toml`/`Cargo.lock`/
  `src/` are still tracked).

## [0.0.4a0]

Feature/hardening release on top of `0.0.4`: one previously-unimplemented piece of the
`USBTransferStatus` enum, a round of hardening specifically aimed at large-payload transfers
(WebADB — Android Debug Bridge over WebUSB — being the motivating example, though anything
moving substantial bulk data applies), and TypeScript type declarations. Marked `a0` (alpha)
rather than a plain patch bump since, unlike `0.0.4`, this adds behavior rather than only
fixing it — same reasoning as `0.0.1a0`/`0.0.2b0`/`0.0.3a0`/`0.0.3b0` before it.

### Added

- **`USBTransferStatus: 'babble'`.** The spec's `USBTransferStatus` enum has three values —
  `"ok"`, `"stall"`, `"babble"` — and only the first two were ever produced. Re-read the
  `controlTransferIn`/`transferIn`/`isochronousTransferIn` algorithms in the spec source
  specifically looking for the third: babble means the device responded with *more* data than
  the host requested, and is IN-direction-only (there's no OUT-direction equivalent — confirmed
  by checking all three occurrences in the spec text, all under `*In` methods). Detected from
  `pyusb`'s `LIBUSB_ERROR_OVERFLOW`, the same way stall is detected from `LIBUSB_ERROR_PIPE`:
  confirmed by constructing a real `usb.core.USBError` directly from
  `usb.backend.libusb1.LIBUSB_ERROR_OVERFLOW` and checking what it actually reports
  (`errno=75`, `"[Errno 75] Overflow"`) rather than assuming. `is_babble_error()` in
  `hardening.py` mirrors `is_stall_error()`'s existing shape. Wired into `bulkTransferIn`,
  `controlTransferIn`, and `isochronousTransferIn`. As with stall, this implementation can't
  recover partial data from an overflow via `pyusb`'s synchronous read API, so (like stall)
  `data` comes back empty — noted in the docstring rather than silently overclaimed.
  Cross-checked the full `USBDevice` WebIDL against what's implemented while in there: every
  other attribute/method (including `forget()`, which was already wired to
  `OpenWebUSBDevice.prototype.forget()` in the polyfill) was already present — babble was the
  one real gap.
- **TypeScript type declarations** (`types/webusb-polyfill.d.ts`) for the `navigator.usb`
  surface this polyfill installs — `declare global` ambient types, not a module, since that's
  how the polyfill actually attaches itself. Transcribed directly from the WebIDL blocks in the
  spec source (fetched fresh, not written from memory) rather than approximated. Checked with
  `tsc --strict`: a full-surface usage sample (device selection with filters/exclusionFilters,
  open/configure/claim/transfer/reset/close/forget, control and isochronous transfers, the
  `'babble'` status, connection events) compiles clean, and a separate `@ts-expect-error` file
  (wrong status string, wrong `clearHalt` direction, wrong filter field type) confirms invalid
  usage is actually rejected, not just nominally typed. Documented in a new README section,
  including that `@types/w3c-web-usb` is a reasonable alternative if you'd rather have the bare
  spec types without this project's framing.

### Changed — large-transfer hardening (WebADB and similar)

- **Wire encoding switched from hex to base64** between the JS polyfill and the Python bridge,
  for every transfer method (`bulkTransferIn`/`Out`, `controlTransferIn`/`Out`,
  `isochronousTransferIn`/`Out`). This is a pure internal-implementation-detail change — the
  public `transferIn`/`transferOut`/etc. surface still takes/returns plain
  `ArrayBuffer`/`DataView` exactly as before and as spec requires. Hex was a 2x size expansion
  per byte; base64 is ~1.33x, meaningfully smaller for the multi-hundred-KB-to-multi-MB payload
  sizes a WebADB-style client routinely moves through a single `transferIn`/`transferOut` call.
  **Found a real crash risk while implementing this, not just a size concern**: the standard
  `String.fromCharCode.apply(null, byteArray)` trick for building the base64 input string
  throws `RangeError: Maximum call stack size exceeded` once the array is large enough, because
  each byte becomes a separate function argument and JS engines cap how many of those a single
  call can take. Confirmed directly in Node (same V8 family as QtWebEngine's Chromium): fine at
  100 KB, throws by 300 KB — squarely inside normal WebADB payload territory, so shipping the
  naive version would have made large transfers *more* fragile than the hex implementation it
  was replacing. Fixed by chunking the array into `0x8000`-byte pieces before each
  `fromCharCode.apply()` call. Verified both the crash and the fix directly (temporarily
  reverted to the unchunked version, confirmed the new 500 KB round-trip test in
  `test_polyfill.js` fails with exactly that `RangeError`, then restored the fix and confirmed
  it passes) rather than trusting the fix by inspection alone.
- **Transfer timeouts now scale with payload size** (`scaled_transfer_timeout_ms()` in
  `hardening.py`) instead of a flat, hardcoded 5000ms, for `bulkTransferIn`/`Out`,
  `controlTransferIn`/`Out`, and `isochronousTransferIn`/`Out`. The spec doesn't expose a
  timeout concept to JS for any of these methods at all — a caller is entitled to expect a
  slow-but-legitimate transfer to simply take as long as it takes. But this implementation
  still has to give `pyusb` *some* finite value, and a flat 5s risked cutting off a real
  large-payload transfer on a slow link. The other extreme — no timeout, blocking indefinitely
  — isn't safe either: these are synchronous `@Slot` methods running on the Qt main thread, so
  a device that stops responding mid-transfer would freeze the whole app's UI, not just the one
  pending JS promise. Compromise: 5s minimum, scaling at a conservative assumed 100 KB/s, capped
  at 120s so a truly stuck device can't hang the UI forever either.
- **Requested transfer lengths are now capped** before a buffer is allocated for them: 64 MiB
  for `transferIn` (spec type is `unsigned long`, effectively ~4 GB, which a buggy/malicious
  page could otherwise use to force an enormous host-side allocation with one call), the spec's
  own 65535-byte `unsigned short` ceiling for `controlTransferIn` (enforced explicitly rather
  than left to whatever happens to occur further down the call chain), and 16 MiB total for
  `isochronousTransferIn`'s summed `packetLengths`. All three limits are this implementation's
  own defensive choice, not a spec requirement, and comfortably above realistic single-call
  WebADB-style payload sizes.

### Tests
- `test_hardening.py`: `test_is_babble_error`, `test_scaled_transfer_timeout_ms`.
- `test_bridge.py`: `test_bulk_and_control_transfer_in_report_babble_status`,
  `test_bulk_and_control_transfer_timeout_scales_with_length`,
  `test_bulk_and_control_transfer_reject_absurdly_large_length`,
  `test_isochronous_transfer_rejects_oversized_total_packet_lengths`,
  `test_bulk_transfer_large_payload_round_trip_via_base64` (300 KB, Python-side path).
  `FakeDevice.read()`/`write()`/`ctrl_transfer()` gained optional configurable exceptions
  (`read_exception`/`write_exception`/`ctrl_transfer_exception`, all `None` by default — no
  effect on any pre-existing test) so babble could actually be exercised end to end instead of
  only unit-tested in isolation.
- `test_polyfill.js`: a 500 KB payload round-tripped through `transferOut`→`transferIn` (chunked
  base64 encode/decode), confirmed byte-for-byte, with the chunking fix's necessity confirmed by
  temporarily reverting it (see above). Every hex literal in the fake bridge's canned responses
  and assertions was replaced with the precise base64 encoding of the same intended bytes
  (computed programmatically, not hand-converted) so the tests keep checking the same actual
  byte values, not just "some string."
- `types/webusb-polyfill.d.ts` checked with `tsc --strict` against both a positive usage sample
  and a negative `@ts-expect-error` sample (see "Added," above) — not part of the pytest/Node
  suites (no `typescript` dependency added to the package), but documented as a manual/CI-of-
  your-choice check in the README's Testing section.

### Project metadata
- Version: `0.0.4a0`. (Written as the full normalized form up front — `packaging.version
  .Version("0.0.4a")` parses fine and normalizes to `0.0.4a0` automatically, but this project's
  own convention has always been to write versions pre-normalized, so that's what's in
  `pyproject.toml`/`__init__.py`.)
- Same verified environment as `0.0.4`: Python `3.14.4`, `PySide6-Essentials`/`PySide6-Addons`
  `6.11.2`, `pyusb` `1.3.1`. Full suite (Python + `test_polyfill.js`) re-verified green after
  every change in this entry, not just at the end.

## [0.0.4]

A bug-fix and spec-compliance-audit release. Started from a user-reported symptom (the device
chooser dialog not appearing), confirmed the diagnosis, and used the same audit to look for
other gaps between this implementation and the spec / the real `pyusb`/PySide6 it sits on top
of. All five fixes below were verified against real installed sources or a real `QWebChannel`
round-trip, not assumed.

### Fixed

- **Chooser dialog silently losing its parent window (user-reported).**
  `requestDeviceChooser()` resolved the dialog's parent purely via
  `QApplication.activeWindow()`, ignoring `self.browser_window` even though `__init__()` /
  `install()` already threaded it all the way through to the bridge. `activeWindow()`'s value
  depends on the OS/window manager correctly propagating focus-activation state to Qt, which an
  async JS→Python `QWebChannel` call (arriving via a nested event loop, triggered from inside a
  `QWebEngineView`'s own native compositor surface) doesn't reliably keep in sync on every
  platform — when it returns `None`, the dialog opens as an independent, unparented top-level
  window, which can end up behind the browser window, on a different desktop/workspace, or
  otherwise easy to lose track of, even though it's technically open and modal the whole time.
  Added `_resolve_chooser_parent_window()`: prefers `browser_window` (only when it's actually a
  `QWidget` — see below), falls back to `activeWindow()`, then to the first visible top-level
  widget, in that order. Also added explicit `dlg.show()` / `raise_()` / `activateWindow()`
  before `exec()` as defense in depth. `examples/minimal_browser.py` and the README's
  `browser_window` documentation were both updated to demonstrate and describe this —
  `browser_window` was previously documented purely as a settings-storage duck-typed parameter
  (`.settings` attribute), so this is a backward-compatible broadening of what it's used for,
  not a new required argument or a breaking change to what could be passed there before.
  Covered by three new `test_bridge.py` cases:
  `test_resolve_chooser_parent_window_prefers_browser_window_widget`,
  `test_resolve_chooser_parent_window_ignores_non_widget_browser_window` (confirms passing the
  old-style non-`QWidget` settings-holder still works and doesn't get used as a parent), and
  `test_requestDeviceChooser_passes_browser_window_to_dialog_as_parent` (end-to-end through the
  real `requestDeviceChooser()` call path, not just the resolver in isolation).

- **`device.close()` never actually closed anything.** `closeDevice(handle_id,
  frame_token="")` has been `@Slot(int, str)` (2 required parameters) since `frame_token` was
  threaded through every origin-sensitive method in `0.0.3b0` — but the polyfill's `close()`,
  the one call site that doesn't go through the `callBridge()` helper (since it doesn't need a
  return value), was never updated to match, and still called `bridge.closeDevice(this._handle)`
  with a single argument. Confirmed with a real `QWebChannel` round-trip (a throwaway probe
  `QObject` with a `@Slot(int, str)` method, invoked from JS both with and without the second
  argument) that this isn't a "missing argument defaults to empty string" situation:
  **QWebChannel silently drops the call entirely** when the JS caller supplies fewer arguments
  than the registered slot signature requires — the Python method never runs at all, no
  exception, no console warning. So every `device.close()` call was a complete no-op: the
  `pyusb`/libusb device handle was never disposed, the entry in `_open_devices` was never
  removed, and the underlying device stayed exclusively claimed by the process for as long as
  the page/bridge lived. Fixed by passing `_frameToken()` as the second argument, matching
  every other bridge call site. `tests/test_polyfill.js` gained a dedicated case that opens a
  device, closes it, and asserts `closeDevice` was invoked with exactly `(handle, frame_token)`
  — confirmed this fails against the pre-fix code and passes against the fix before finalizing it.

- **Isochronous transfers passed the wrong value as the backend's interface-number
  parameter.** Read directly from the installed `pyusb`'s `usb/backend/libusb1.py`:
  `iso_read(self, dev_handle, ep, intf, buff, timeout)` / `iso_write(self, dev_handle, ep,
  intf, data, timeout)` — the third parameter is an interface number (this is also exactly what
  `Device.read()`/`write()`'s own internal dispatch passes, via `Context.setup_request()`'s
  `intf.bInterfaceNumber` — confirmed by reading that code path too). `isochronousTransferIn`/
  `Out` here were passing the raw endpoint number instead, discarding the real interface number
  that `_endpoint_available_or_error()` already computes and returns (previously captured as
  `_owner` and thrown away). Currently a no-op at runtime — the installed `pyusb` (`1.3.1`)'s
  `_IsoTransferHandler` accepts `intf` but never reads it, confirmed from source — but
  semantically wrong, reliant on that being true forever, and a landmine for any future `pyusb`
  release that starts using it. Fixed to pass the real interface number through in both
  directions. `test_isochronousTransfer_success_path_with_fake_backend` gained assertions on
  this; a new `test_isochronousTransfer_passes_interface_number_not_endpoint_number_as_intf`
  uses a deliberately-different interface number (`7`) and endpoint numbers (`3`/`4`) so the
  assertion can't accidentally pass just because both happened to be the same small integer.

- **`selectConfiguration()` didn't reset per-handle claimed-interface tracking.** The spec
  requires `[[claimedInterface]]` to be cleared for every interface on a successful
  configuration switch — a given interface *number* can mean something completely different
  under a different configuration. The implementation called `dev.set_configuration()` but left
  the handle's `claimed_interfaces` set untouched, so an interface number claimed under the old
  configuration stayed "claimed" (and therefore usable for transfers / `selectAlternateInterface
  ()`) under the new one, despite never actually being claimed there. `selectConfiguration()`
  had *no* test coverage at all before this version — `tests/test_bridge.py`'s `FakeDevice`
  didn't even implement `set_configuration()` — so this was found by reading the spec's
  algorithm against the implementation line by line, not from a symptom report.
  `FakeDevice.set_configuration()` / `get_active_configuration()` were extended in the test
  fakes (previously `get_active_configuration()` unconditionally returned the fixture's
  first/only configuration, since no existing test used more than one) so configuration
  switches can actually be exercised. New test:
  `test_selectConfiguration_resets_claimed_interfaces`.

- **`bulkTransferIn`/`Out` accepted isochronous endpoints.** The spec's `transferIn`/
  `transferOut` algorithm requires `InvalidAccessError` when the target endpoint's actual type
  isn't bulk or interrupt — this project already enforced the *reverse* direction
  (`isochronousTransferIn`/`Out` rejecting non-isochronous endpoints, since `0.0.2b0`), but not
  this one. `pyusb`'s `Device.read()`/`write()` auto-dispatches to the correct backend call
  (`bulk_read`/`intr_read`/`iso_read`, confirmed from `usb/core.py`'s `fn_map`) purely from the
  endpoint descriptor's declared type, so the transfer would actually go through and "succeed"
  against a real isochronous endpoint via the bulk-named methods — this only ever surfaced as a
  spec/permissions violation, never a runtime error, which is presumably why it went unnoticed.
  `_endpoint_available_or_error()`'s `required_type` parameter now accepts a tuple of allowed
  types (previously exactly one); `bulkTransferIn`/`Out` pass `("bulk", "interrupt")`. New test:
  `test_bulkTransferIn_and_Out_reject_isochronous_endpoint`.

### Verified against the spec / real sources — no change needed
Things this audit specifically checked and found already correct, recorded here rather than
silently passed over:
- `hardening.py`'s `KNOWN_SECURITY_KEY_BLOCKLIST` (43 entries) matches WICG's own
  `blocklist.txt` (fetched live from `github.com/WICG/webusb`, `main` branch) exactly — same 43
  entries both directions, and neither source currently has any `bcdDevice`-qualified entries
  (a form this implementation's blocklist can't represent, since it's vendor/product-ID only —
  worth re-checking on a future audit, but not a gap today). This cross-checks against a
  *different* canonical source than the `0.0.1a0` entry's comparison against Chromium's
  `usb_blocklist.cc`; both agree.
- `PROTECTED_INTERFACE_CLASSES` (`0x01, 0x03, 0x08, 0x09, 0x0B, 0x0E, 0x10, 0xE0`) matches the
  spec's "has a protected interface class" table exactly, entry for entry.
- Every `pyusb` `Device` method call site in `bridge.py` (`read`, `write`, `ctrl_transfer`,
  `set_interface_altsetting`, `set_configuration`, `get_active_configuration`, `reset`,
  `clear_halt`, `is_kernel_driver_active`, `detach_kernel_driver`) checked argument-by-argument
  against the actual installed `pyusb` source's method signatures — all correct.
- Every `@Slot`-decorated method's declared argument count checked against every JS call site
  that invokes it (whether via the `callBridge()` helper or a direct call) — `closeDevice`
  (Fixed, above) was the only mismatch found.
- `Configuration.__iter__` / `Interface.__iter__` (confirmed from the installed `usb/core.py`)
  yield one `Interface` object per alternate setting, not one per interface number — matches
  how `build_configurations_tree()` already grouped them by interface number.

### Project metadata
- Version bumped to `0.0.4`.
- Verified against Python `3.14.4` (the latest available; Ubuntu 24.04's system package manager
  only offers `3.12.x`, so this used `uv python install` to get a real up-to-date interpreter)
  and `PySide6-Essentials`/`PySide6-Addons` `6.11.2` (latest on PyPI as of this release — up
  from `6.11.1`, confirmed current as of the `0.0.3` entry). The full test suite (Python +
  `tests/test_polyfill.js`) passes unmodified on both. Also compiled every file touched in this
  release under Python `3.9.24` (the floor of `requires-python`) to confirm no accidental
  reliance on newer syntax snuck in.
- One pre-existing, unrelated `DeprecationWarning` observed under Python 3.14, from `pyusb`'s
  own `usb/backend/libusb0.py` (`ctypes.Structure` subclasses using `_pack_` without
  `_layout_`, which 3.14's `ctypes` now warns about ahead of a future Python version making it
  an error). This lives entirely inside `pyusb`, isn't triggered by anything this project's own
  code does, and isn't something this project can fix — noted here rather than silently ignored.

## [0.0.3b0]

Implemented the per-frame origin attribution design that `0.0.3`/`0.0.3a0` researched but
didn't ship. `navigator.usb` is available in iframes again (`setRunsOnSubFrames(True)`,
reverting the `0.0.2b0` lockdown) — but now backed by a real per-frame origin check instead of
the vulnerable page-wide one that made that lockdown necessary in the first place.

### Added

- **`frame_origin.py`** (new module) — `FrameOriginTracker`, which is what makes this safe to
  re-enable. Design: Python (not JS) walks the real frame tree via
  `QWebEnginePage.mainFrame()`/`QWebEngineFrame.children()`, mints an unguessable token
  (`secrets.token_urlsafe`) per frame, and pushes it into *that specific frame* via
  `QWebEngineFrame.runJavaScript()` — a different, cross-origin frame cannot read another
  frame's token without breaking the same-origin policy itself. `WEBUSB_POLYFILL_JS` reads its
  own `window.__pyUsbFrameToken` and sends it with every bridge call; `WebUSBBridge` resolves
  the caller's real origin by looking the token up, never by trusting anything JS claims about
  itself. Rescans are triggered by `QWebEnginePage.navigationRequested` (fires once per frame
  navigation, including subframes — confirmed in `0.0.3a0`), staggered a few times after each
  signal since the request arrives before the frame necessarily exists in the tree, plus a
  2-second periodic rescan as a backstop.

  Three things only showed up once this was tested against a **real** `QWebEnginePage` (not
  the fakes the rest of the test suite uses), which is exactly why that testing mattered:
    - `QWebEngineFrame.runJavaScript(code)` with a single argument raises *"not enough
      arguments"* — it requires a callback as a second argument, even one that does nothing.
    - `QWebEnginePage.setHtml(html, baseUrl=...)` does **not** make
      `QWebEngineFrame.url()` reflect `baseUrl` — it reports the content as a `data:` URL
      instead, which correctly (if confusingly, for testing) resolves to no origin at all.
      Real navigations (`page.load(QUrl(...))`) behave as expected; the integration test uses
      that instead.
    - `QWebEngineFrame` Python objects returned by `children()`/`mainFrame()` don't appear to
      be stable across calls — the same underlying iframe showed different `id()` values on
      successive rescans. The original design tried to track "does this frame already have a
      valid token" per frame identity to avoid re-issuing tokens; that check silently never
      matched, defeating its own purpose (harmlessly — it just re-issued tokens more than
      necessary). Removed that optimization rather than build something fragile on top of an
      identity assumption that doesn't hold; every rescan simply (re-)issues a fresh token for
      every frame it finds now, with a global cap (`_MAX_TOTAL_TOKENS`) on how many tokens are
      kept at once so this can't grow without bound.

- **`frame_token` parameter, threaded through every origin-sensitive `@Slot`** (`listDevices`,
  `requestDeviceChooser`, `openDevice`, `closeDevice`, `claimInterface`, `releaseInterface`,
  `selectConfiguration`, `selectAlternateInterface`, `resetDevice`, `clearHalt`,
  `bulkTransferIn`/`Out`, `controlTransferIn`/`Out`, `isochronousTransferIn`/`Out`,
  `forgetGrantedDevice` — 16 methods). Defaults to `""`, so every existing direct-Python test
  call site kept working unchanged (`WebUSBBridge._current_origin(frame_token="")` falls back
  to the pre-`0.0.3b0` `page.url()`-only behavior whenever `self._frame_tracker` is `None`,
  which is exactly the case for tests built via `make_bridge()` or any other use of this
  package without `install()`). `_get_open_device()` also takes `frame_token` now, since it's
  the shared choke point roughly a dozen of those methods funnel through to authorize reuse of
  an already-open handle — this is what makes the fix functionally complete rather than just
  "fails closed but broken": a handle opened by a subframe now stays usable by that *same*
  subframe for follow-up calls, not just at the moment it was opened.

  **The one rule this all depends on:** when `self._frame_tracker` is not `None`,
  `_current_origin()` resolves *exclusively* through the token — including for the main frame,
  which also gets an assigned token now like any other frame. There is no "empty token falls
  back to the top-level page" case once a tracker is wired, on purpose: allowing that would
  let a hostile subframe calling the raw `QWebChannel` object directly (bypassing the polyfill
  entirely) impersonate the top-level page just by omitting the token — reintroducing the exact
  `0.0.2b0` vulnerability this whole feature exists to close.

  Added a dedicated internal `_top_level_origin()` (always reads `page.url()` directly, no
  token involved) for the two places that were never about "which frame is calling" in the
  first place: `_on_page_navigated()` (detects the top-level page itself navigating, to drop
  stale handles) and the hotplug watcher's `deviceConnected`/`deviceDisconnected` filtering
  (these are `Signal`s broadcast to every frame on the page — there's no mechanism to target a
  `Signal` at one specific frame, so per-frame-scoped hotplug notifications are out of scope
  for now; they're filtered against the top-level page's grants, same as before).

- **Tests**: `tests/test_frame_origin.py` — eight fast tests against fakes (token issuance,
  nested-frame walking, opaque-URL rejection, the `is_functional` fallback, the total-token
  cap, exception resilience) plus one real-`QWebEnginePage` integration test (loads local HTML
  containing a cross-origin iframe, confirms the iframe gets a token that resolves to its own
  real origin, and that an empty or forged token resolves to nothing). `tests/test_bridge.py`
  gained two more: `test_frame_tracker_wired_denies_empty_and_forged_tokens` and
  `test_frame_tracker_wired_isolates_handles_between_different_frame_origins`, exercising the
  exact attack shape this feature closes without needing a real browser context for every run.

### Fixed
- `install()`'s two injected `QWebEngineScript`s now call `setRunsOnSubFrames(True)` again —
  but only when `FrameOriginTracker.wire()` actually managed to connect to
  `navigationRequested` (`tracker.is_functional`). On a PySide6/Qt version old enough not to
  have that signal, `install()` falls back to the `0.0.2b0` behavior
  (`setRunsOnSubFrames(False)`) automatically rather than silently running with no real
  per-frame protection.

### Project metadata
- Version bumped to `0.0.3b0`.

## [0.0.3a0]

Follow-up to `0.0.3`'s research question: does a per-frame navigation/load signal actually
exist? Also extracted the DOMException-prefix convention into its own module and added its own
test coverage.

### Researched further: `navigationRequested` is the per-frame signal that was missing

`0.0.3` confirmed `QWebEngineFrame` can enumerate frames and their real origins, but noted
`loadFinished`/`loadStarted` only fire once per page load, not once per frame — leaving "how do
we know when a new/navigating frame appears" unanswered. Dumped `QWebEnginePage`'s full signal
list via `QMetaObject` (rather than guessing from documentation) and found
`navigationRequested(QWebEngineNavigationRequest&)`, which carries `.url()` and
`.isMainFrame()`. Verified empirically against a real `QWebEnginePage` loading local HTML with
two iframes: it fired **three times** — once for the top-level page (`isMainFrame=True`) and
once for *each* iframe (`isMainFrame=False`), each with its own correct URL. This is exactly
the per-frame trigger `0.0.3` said didn't exist at the `QWebEnginePage` level.

This doesn't complete the design by itself. Correlating a `navigationRequested` event to the
specific `QWebEngineFrame` object needed for `runJavaScript()`-based token delivery still
requires re-walking `mainFrame()`/`children()` after the signal fires (the navigation request
arrives before the frame necessarily exists in the tree). More significantly, re-checking the
full design against `_get_open_device()` — the choke point roughly a dozen other `@Slot`
methods funnel through to authorize use of an already-open handle — showed that a token can't
be limited to just the three entry-point methods (`getDevices`, `requestDevice`, `open`) the
way `0.0.3` hoped: unless *every* handle-consuming call also resolves the real calling frame's
origin, a handle legitimately opened by a subframe would fail every subsequent operation
against the (unfixed) top-level-page-only origin check — safe, but non-functional, not a real
fix. Confirming this needs the token threaded through every handle-consuming method (not just
three) before it can be both correct and usable; not attempted in this version for the same
reason as `0.0.3` — it's a wide, security-sensitive change that deserves to land as its own
reviewable unit, not mixed in with this version's other fixes.

### Added
- **`errors.py`**: centralizes the `"SecurityError:"`/`"InvalidStateError:"`/`"NotFoundError:"`/
  `"InvalidAccessError:"`/`"IndexSizeError:"` prefix convention that `polyfill.py`'s
  `throwFromResult()` matches against. Previously these were hand-typed as raw f-strings in
  (at least) 10 places in `bridge.py` — functional, but a typo in any of them (e.g.
  `"SecurtyError:"`) wouldn't be a syntax error, just a silently-wrong `DOMException` name
  reaching JS, since `throwFromResult()` would fail to recognize the misspelled prefix and fall
  back to whatever generic default the caller specified. `bridge.py` now calls
  `security_error(msg)` etc. instead of constructing the string inline, including
  `_control_transfer_validation_error()`'s local `_err()` helper, which now delegates to the
  same functions rather than duplicating the prefix format. Added `tests/test_errors.py`.

### Project metadata
- Version bumped to `0.0.3a0`.

## [0.0.3]

Investigated whether per-frame origin attribution — the thing `0.0.2b0`'s `Security` entry
concluded "isn't currently possible through PySide6's public API" — is actually possible after
all, given a newer PySide6/Qt version. Also confirmed the currently-installed `pyusb` (1.3.1)
is the latest release on PyPI, so the isochronous-transfer limitations documented in `0.0.2`
aren't an artifact of using an outdated `pyusb`.

### Researched: per-frame origin attribution (not yet implemented)

**The earlier conclusion needs updating.** `QWebEngineFrame` — confirmed present in the
installed `PySide6` 6.11.1 (`from PySide6.QtWebEngineCore import QWebEngineFrame`) — did not
exist in older PySide6/Qt WebEngine releases, which is presumably why the `0.0.2b0` fix landed
on "disable subframes entirely" as the only safe option available at the time. Verified
empirically in this environment, against a real `QWebEnginePage` loading real HTML with an
iframe (not just reading documentation):

- `page.mainFrame()` returns a `QWebEngineFrame` for the top-level frame.
- `frame.children()` recursively returns child frames — a real iframe
  (`<iframe src="https://example.org/child.html" name="childframe">`) showed up correctly,
  with its own accurate `.url()` (`https://example.org/child.html`) and `.name()`
  (`childframe`), both read from Qt/Chromium's own frame-tracking (not from any
  JS-supplied value) via `page.mainFrame().children()`.
- `frame.runJavaScript(code, callback)` exists and accepts a per-frame target, though its
  exact reliability (e.g. against a frame with no content loaded) wasn't fully pinned down in
  this pass and needs more testing before depending on it.

This changes the picture, but **does not by itself solve the problem** — `QWebEnginePage`'s
`setWebChannel(channel, worldId=None)` (confirmed via its actual overload signature) is still
page-scoped, not frame-scoped, and there's still no signal or callback that tells Python
"this specific incoming `QWebChannel` call came from *this* frame." Enumerating frames answers
"what frames currently exist and what are their real origins" — it doesn't answer "which frame
just invoked `requestDeviceChooser()`."

**A viable design, sketched but not implemented:** have Python (not JS) mint an unguessable,
per-frame token, push it into that specific frame via `frame.runJavaScript()` (so only code
genuinely running in that frame ever sees its own token — a different frame can't read it
without breaking same-origin isolation itself), and have every bridge call include that token
as an actual parameter (not a separately-set piece of state, which would race across frames
issuing concurrent calls) so Python can look up the real origin the token was issued for. This
needs re-verifying tokens periodically (there's no per-iframe navigation signal at the
`QWebEnginePage` level — confirmed empirically: `loadFinished`/`loadStarted` only fired once
for a page containing an iframe, not once per frame — so detecting a frame's origin changing
out from under an issued token means polling `mainFrame()`/`children()` on a timer, similar to
the existing hotplug-device watcher).

**Why this isn't implemented yet:** doing it properly means adding a token parameter to every
transfer/permission `@Slot` (roughly 19 methods), the matching change to every `callBridge()`
call site in the polyfill, and re-validating the entire existing test suite against the new
signatures — a substantially larger and more security-sensitive change than the surgical fixes
in this and the previous few versions, and one that deserves dedicated review rather than
landing alongside unrelated work. Recorded here as a concrete, verified-feasible design so it
doesn't have to be re-researched from scratch, and so `setRunsOnSubFrames(False)` in `install()`
is understood as "safe default pending this work," not "believed impossible."

### Verified, no change needed
- `pyusb` 1.3.1 (currently installed) is the latest version on PyPI (checked via
  `pip index versions pyusb`) — the isochronous-transfer caveats from `0.0.2` (no public
  high-level API, uniform-packet-length-only backend) reflect `pyusb`'s actual current state,
  not an outdated dependency.

### Project metadata
- Version bumped to `0.0.3`.

## [0.0.2b0]

Continued the spec/Chrome-source comparison from `0.0.1a0`, this time pulling actual Chromium
source (Blink's `usb_device.cc`, fetched live from `github.com/chromium/chromium`) rather than
spec prose alone, plus a first attempt at isochronous transfer support.

### Security
- **🚨 Cross-origin iframes could access the top-level page's granted USB devices.**
  `install()` injected the WebUSB polyfill with `script.setRunsOnSubFrames(True)`, meaning it
  ran inside every iframe on a page, not just the top frame. `WebUSBBridge._current_origin()`
  determines the origin to check permissions against from `QWebEnginePage.url()` — which is
  *always* the top-level frame's URL; there's no way to determine which frame inside a page a
  given `QWebChannel` call actually came from through PySide6's public API. The combination
  meant a cross-origin iframe (a compromised ad, a malicious embed, anything the top-level page
  didn't fully trust) calling `navigator.usb.requestDevice()`/`getDevices()` had its request
  attributed to the *top-level page's* origin — not its own — giving it full access to every
  USB device the top-level page had ever been granted, a complete bypass of the origin
  isolation the rest of this codebase's permission model depends on. Since there's no
  currently-available way to correctly attribute a `QWebChannel` call to the specific frame
  that made it, the fix is to fail closed: `setRunsOnSubFrames(False)`, so `navigator.usb`
  simply isn't defined inside any iframe at all (a real capability loss relative to real
  Chrome, which does support properly-isolated WebUSB in cross-origin iframes — but a correct
  and safe default given what this codebase can actually verify). Found by reading `install()`
  end to end while looking for anything below `WebUSBBridge` itself that could affect the
  security model, rather than only the bridge's own methods.
  Added `tests/test_install.py` — there was **no test coverage of `install()` at all**
  before this, using real `QWebEngineScript`/`QWebChannel` objects against a lightweight fake
  page (no full `QWebEnginePage`/renderer needed). Confirmed
  `test_install_does_not_run_scripts_on_subframes` fails against a copy with
  `setRunsOnSubFrames(True)` restored.

### Fixed
- **`bulkTransferIn`/`bulkTransferOut`/`clearHalt` had no equivalent of Chrome's
  `USBDevice::EnsureEndpointAvailable()`.** Fetched and read Blink's actual
  `third_party/blink/renderer/modules/webusb/usb_device.cc`: `transferIn`/`transferOut`/
  `clearHalt` all unconditionally call this before touching the device, and it requires the
  target endpoint to belong to a **claimed** interface. This implementation had that check for
  `controlTransferIn`/`controlTransferOut` (added in `0.0.1a0`) but never extended it to plain
  bulk/interrupt transfers or `clearHalt` — so a page could skip `claimInterface()` (and the
  protected-class rejection that comes with it) entirely and still read/write a protected
  interface's bulk or interrupt endpoints directly. Added `_endpoint_available_or_error()`,
  shared by all three methods, plus the endpoint-number range check (`1`-`15`, matching
  Chrome's `IndexSizeError` for out-of-range numbers). Added
  `test_bulk_transfer_and_clearHalt_require_claimed_interface` and
  `test_bulk_transfer_rejects_out_of_range_endpoint_number`; confirmed both fail against a
  copy with the checks removed.
- **`open()` (JS) had no idempotency check.** Real Chrome's `USBDevice::open()` resolves
  immediately without doing anything if the device is already open. This implementation always
  called through to `openDevice()` regardless, which — since `openDevice()` mints a brand new
  handle every call — meant calling `open()` twice silently orphaned the first handle (and
  anything claimed on it) with no way to ever close it again, since `this._handle` gets
  overwritten by the second call. Added an early return when `this.opened` is already true.
  Extended the JS test's exact-call-sequence assertion (now also tracking `openDevice` calls,
  which the fake bridge previously didn't record) to confirm a second `open()` adds no new
  bridge call.
- **`selectAlternateInterface()` had no equivalent of Chrome's `EnsureInterfaceClaimed()`.**
  Confirmed from the same Blink source: it requires the target interface to already be
  claimed, rejecting with `InvalidStateError` otherwise. This implementation had no such
  check at all — a page could change a never-claimed (including protected-class) interface's
  alternate setting without ever calling `claimInterface()`. Added the check, matching
  Chrome's exact error message. Added `test_selectAlternateInterface_requires_claimed_interface`;
  confirmed it fails against a copy with the check removed.
- **`claimInterface()`/`releaseInterface()` had no equivalent of Chrome's
  `EnsureDeviceConfigured()`.** Also confirmed from Blink's source: both require a
  configuration to already be selected, before anything else. Without an explicit check, a
  device with no active configuration was *still* rejected by this implementation (since
  `interface_class_for()` already falls back to "protected" when it can't determine an active
  configuration — see the `0.0.1a0` entry above) but with a misleading `SecurityError:
  ...protected interface class` message instead of the real reason. Added an explicit check at
  the top of both methods with Chrome's exact wording
  (`InvalidStateError: "the device must have a configuration selected"`). Added
  `test_claimInterface_and_releaseInterface_require_configuration_selected`; confirmed it
  fails (with the old, misleading `SecurityError` message) against a copy with the check
  removed.

### Added
- **Isochronous transfer support (`isochronousTransferIn`/`isochronousTransferOut`), best
  effort.** These previously always returned `NotSupportedError`. `pyusb`'s public API
  (`usb.core.Device`) has no isochronous method — `read()`/`write()` are documented as
  bulk/interrupt only — but its `libusb1` backend does expose `iso_read()`/`iso_write()`
  (confirmed by inspecting the installed `pyusb` package directly). Reaching them requires
  `dev.backend` and the private `dev._ctx.handle`, which is a real departure from the
  public-API-only approach the rest of this codebase follows, and is the reason this is
  labeled best-effort rather than held to the same confidence bar as the rest of `0.0.1a0`.
  Two known, deliberate limitations:
    - `pyusb`'s `iso_read`/`iso_write` split one buffer into **uniform**-length packets
      (`libusb_get_max_iso_packet_size()`-derived, last packet takes the remainder); the
      spec's `packetLengths` allows a different length per packet. Non-uniform
      `packetLengths` are rejected with `NotSupportedError` rather than silently
      mis-transferred.
    - If `dev.backend`/`dev._ctx.handle` aren't available (non-`libusb1` backend, or a future
      `pyusb` version restructures these attributes), both methods fall back to
      `NotSupportedError` instead of raising.
    Added the endpoint-type check (`InvalidAccessError` for a non-isochronous endpoint,
    reusing `_endpoint_available_or_error()` with a new `required_type` parameter) and
    per-packet `status`/`data`/`bytesWritten` result shapes matching
    `USBIsochronousInTransferResult`/`USBIsochronousOutTransferResult`. Tested: parameter
    validation, the claimed/endpoint-type gates, and packet-splitting arithmetic against a
    fake backend (Python `test_isochronousTransfer_*`, JS `isochronousTransferIn/Out`
    fixture tests covering `NotFoundError`/`InvalidAccessError`/success). **Not tested: an
    actual isochronous transfer against real hardware** — there is no USB device available in
    this environment to verify against. Treat this specific feature as unverified until
    someone runs it against a real isochronous device (a USB audio or webcam interface is a
    good candidate) and reports back.

### Project metadata
- Version bumped to `0.0.2b0`.



A line-by-line audit against the actual WebUSB spec source (`WICG/webusb`'s `index.bs`,
fetched directly from GitHub rather than relying on recollection of the rendered page) and
the real `pyusb` API (installed and introspected, not assumed from memory), looking
specifically for spec-defined behavior this implementation didn't yet have, and for bugs the
existing test suite's blind spots could be hiding.

### Fixed
- **`bulkTransferIn()` was missing the IN direction bit.** The spec's
  `transferIn(endpointNumber, length)` algorithm computes
  `endpointAddress = endpointNumber | 0x80` before touching the device; this implementation
  passed `endpointNumber` straight through to `pyusb`'s `Device.read()`, whose `endpoint`
  parameter is documented (confirmed from the installed pyusb source) to require the full
  `bEndpointAddress`, not the bare number. In practice `device.transferIn(1, ...)` was
  targeting address `0x01` (endpoint 1 **OUT**) instead of `0x81` (endpoint 1 **IN**) — real
  IN transfers would have failed against essentially any actual device.
  `bulkTransferOut`/`transferOut` were unaffected (OUT is address `endpointNumber` unchanged,
  per the same spec algorithm). Added `test_bulkTransferIn_adds_the_in_direction_bit`, which
  opens a fake device and asserts the exact byte passed to the mocked `.read()`/`.write()`
  calls; confirmed it fails against the unfixed code (`assert 1 == 129`) before re-fixing.
- **`requestDeviceChooser()` had no reentrancy guard.** The chooser dialog is shown with
  `QDialog.exec()`, which runs a nested Qt event loop; a second call to
  `requestDeviceChooser()` arriving on the same `WebUSBBridge` instance while that nested loop
  is running (double-invocation from the page, a queued `QWebChannel` message serviced
  mid-loop, etc.) would reenter the method and could open a second chooser on top of the
  first. Added a `_chooser_active` guard — `requestDeviceChooser()` is now a thin wrapper with
  a `try`/`finally` around the actual implementation, which moved to
  `_request_device_chooser_impl` (deliberately **not** `@Slot`-decorated, and now covered by
  the existing `test_requestDeviceChooser_is_registered_as_qt_slot` so it can't silently
  become JS-reachable later). A reentrant call now gets an immediate `InvalidStateError`
  instead of a second dialog. Added `test_requestDeviceChooser_reentrancy_guard`, which
  reenters from inside the (fake) dialog's `exec()`; confirmed it fails against the unguarded
  code — it actually hits Python's recursion limit (`maximum recursion depth exceeded`), a
  fairly vivid demonstration of why the guard matters — before re-fixing.
  `polyfill.py`'s `requestDevice()` previously discarded `res.error` for any
  `cancelled: true` response and always reported a generic `NotFoundError('No device
  selected.')`; it now routes through `throwFromResult` (extended to recognize an
  `InvalidStateError:` prefix, alongside the existing `SecurityError:` one) so this new
  rejection reason — and any other real failure — is no longer indistinguishable from the user
  simply clicking Cancel.
- **`controlTransferIn`/`controlTransferOut` could bypass `claimInterface()`'s protected-class
  rejection entirely.** The spec runs a [control transfer validation
  algorithm](https://wicg.github.io/webusb/#control-transfer-validation-algorithm) before
  every control transfer — reject `requestType: 'class'` requests targeting a protected-class
  interface, reject `recipient: 'interface'`/`'endpoint'` requests targeting a protected-class
  interface, require the owning interface to actually be claimed for those two recipients, and
  restrict `requestType: 'standard'` to a handful of read-only requests — and this
  implementation ran none of it. In practice a page could skip `claimInterface()` altogether
  (which does reject protected classes like HID) and reach the same interface directly with
  `controlTransferOut({requestType: 'class', recipient: 'interface', index: <that interface
  number>, ...}, data)`, which went straight through to `pyusb.ctrl_transfer()` with no check
  at all. Added `_control_transfer_validation_error()`, called from both methods before
  touching the device, decoding `requestType`/`recipient` directly from the `bmRequestType`
  byte already being constructed (no new parameters needed from JS). Added three regression
  tests covering the class-request bypass, the interface-recipient claim requirement, and the
  standard-request restrictions; confirmed each fails against a copy with the two call sites
  removed.
- **`interface_class_for()`'s "not found" sentinel silently defeated the safety fallback it
  was meant to feed.** It returned `-1` for an interface number that doesn't exist on the
  device, documented as "let the caller fail safe (reject)" — but `is_protected_interface_class()`
  only falls back to "reject" when `int(...)` *raises* (`TypeError`/`ValueError`), and
  `int(-1)` doesn't raise; `-1 not in PROTECTED_INTERFACE_CLASSES` cleanly evaluates to
  `False`, i.e. "not protected." Reproduced directly at a Python prompt:
  `is_protected_interface_class(-1)` really does return `False`. `claimInterface()` uses
  exactly this pair of calls, so an interface number that doesn't match any real interface was
  being treated as safe to claim instead of rejected. Changed the sentinel to `None`, which
  `is_protected_interface_class()` already handles correctly through the same fallback
  (`int(None)` raises `TypeError`). Added `test_unknown_interface_number_treated_as_protected`;
  confirmed it fails against the `-1` version.
- **`interface_class_for()` (and the new endpoint-recipient check above) searched every
  configuration the device declares, not just the currently active one.** For the very common
  case of a single-configuration device this made no difference, but on a device with more
  than one configuration, an inactive configuration's interface could be found first and used
  for the protected-class/claimed check instead of the interface that's actually reachable
  right now. Both now call `pyusb`'s `get_active_configuration()` first and search only within
  it, falling back to "unknown → protected" (same as the previous fix) if the active
  configuration itself can't be determined. Added
  `test_interface_class_for_scoped_to_active_configuration`, using two configurations that
  deliberately disagree about interface 0's class so a wrong scope produces a wrong class;
  confirmed it fails against the unscoped search.

### Added
Missing pieces found by comparing the descriptor-building code against the spec's IDL and
algorithms — gaps, not bugs in existing behavior:
- **`PROTECTED_INTERFACE_CLASSES` was missing Hub (`0x09`).** The spec's own
  [protected interface classes](https://wicg.github.io/webusb/#h-protected-classes) table
  lists 8 classes; this implementation had 7 (Hub was the omission). `claimInterface()` would
  previously have allowed claiming a Hub-class interface. Added
  `test_hub_interface_flagged_protected`.
- **`USBConfiguration.configurationName`** and **`USBAlternateInterface.interfaceName`** —
  spec-defined attributes (the `iConfiguration`/`iInterface` string descriptors, confirmed
  present on `pyusb`'s `Configuration`/`Interface` objects from their actual source) that
  `build_configurations_tree()` never populated; the keys simply didn't exist in the returned
  descriptor. Both fall back to `None` when the device doesn't define the string (index `0`),
  matching how `manufacturerName`/`productName`/`serialNumber` already behave. Added
  `test_configuration_and_interface_names`.
- **Endpoints list no longer includes Control-Transfer-Type descriptors.** The spec's
  `USBAlternateInterface` construction steps explicitly skip descriptors whose `bmAttributes`
  indicates Control Transfer Type, noting "there shouldn't be any endpoint object belongs to
  Control Transfer Type" — and `USBEndpointType` doesn't even define a `"control"` value
  (only `"bulk"`/`"interrupt"`/`"isochronous"`). Real device descriptors essentially never
  trigger this in practice, but the implementation now matches the spec's own stated
  invariant instead of an implicit assumption. Added
  `test_control_type_endpoint_excluded_from_endpoints`.

Every item above (in both this section and the three new entries added to *Fixed*) was
verified to fail against a reverted copy of the code before being re-fixed, following the same
practice as the `0.0.0` entries below.

### Verified against the spec / real sources — no change needed
Things this audit specifically checked and found already correct, recorded here rather than
silently passed over:
- The known-security-key blocklist (43 entries) matches Chromium's actual `usb_blocklist.cc`
  byte-for-byte (fetched live from `github.com/chromium/chromium`).
- `device_matches_usb_filter()`'s classCode/subclassCode/protocolCode precedence — including
  the "any interface matches → match, independent of the device-level class" short-circuit —
  matches the spec's filter-matching algorithm step for step.
- `claimInterface()`/`releaseInterface()` on an already-claimed/already-released interface
  resolve successfully rather than erroring, per spec — confirmed this falls out of `pyusb`'s
  own `claim_interface()`/`release_interface()` being idempotent (read from the installed
  `pyusb` source), so no explicit guard was needed on top.
- `set_configuration()`'s parameter is the actual `bConfigurationValue`, not a 0-based index
  (confirmed from the installed `pyusb` source), matching how `selectConfiguration()` already
  called it.

### Project metadata
- Version bumped to `0.0.1a0` — this is pre-1.0, alpha-stage software, and the version number
  now says so explicitly rather than reading `0.0.0`.
- `pyproject.toml`'s `Homepage`/`Issues` URLs point at the actual repository,
  `https://github.com/steck0714/Mock-webusb`, instead of the `YOUR_USERNAME` placeholder.

## [0.0.0] — initial extraction

Initial standalone extraction of the WebUSB implementation from the `openweb` browser
project, generalized for use in any PySide6/QtWebEngine app.

### Core functionality
- `WebUSBBridge`: QWebChannel bridge backed by pyusb/libusb — full `navigator.usb` surface
  (`getDevices`, `requestDevice`, all `USBDevice` methods, bulk/control transfers with
  spec-accurate STALL handling, hotplug `connect`/`disconnect` events).
- `WEBUSB_POLYFILL_JS`: the JavaScript polyfill implementing `navigator.usb` against that
  bridge, including `options.filters`/`exclusionFilters` matching per the WICG spec
  algorithm (vendor/product ID, serial number, and the composite-device
  matches-via-any-interface classCode rule).
- `WebUsbDeviceChooserDialog`: native device picker, referenced against Chrome's actual
  chooser UX — always names the requesting origin, requires an explicit device selection
  before "Connect" is enabled (no auto-selecting the first row), and live-updates the list
  if a device is plugged in while the dialog is still open.
- Security hardening: the 7 WebUSB protected interface classes, a Chromium-blocklist-derived
  known-security-key blocklist, per-origin permission storage, and origin binding read
  independently from the page URL (never trusted from JS).
- `install(page)`: one-call integration — wires the bridge, loads `qwebchannel.js` from your
  Qt installation's built-in resources, and injects the polyfill script.

### Fixed before first use
An external code review (cross-checked against the actual source rather than taken at face
value) surfaced one real, confirmed bug and several other findings:
- **Fixed**: `bridge.py` was missing `import time` despite using `time.time()` in `_grant()`
  and `_record_device_usage()` — both call sites were wrapped in `try/except`, so the
  `NameError` was silently swallowed rather than crashing; the practical effect was that
  granted permissions and device-usage records silently failed to persist. Added a
  regression test that exercises these methods *without* mocking them (and verified the
  test actually catches the bug by reintroducing it and confirming the failure, before
  re-fixing it).
- **Fixed**: `revoke_origin_grant()`/`revoke_all_for_origin()` had no exception handling
  (inconsistent with the rest of the class, which never lets an exception escape).
- **Fixed**: error strings returned to JS could contain raw newlines/tabs from underlying
  pyusb/libusb exceptions; added `safe_error_str()` and applied it at all 19 call sites.
- **Hardened**: `_on_page_navigated()` now explicitly clears every open handle when the
  current origin can't be determined at all, rather than relying solely on a per-handle
  inequality check.
- **Fixed**: `@Slot(str, result=str)` was misattached to the private helper
  `_enumerate_filtered_devices()` instead of `requestDeviceChooser()` — the actual
  `navigator.usb.requestDevice()` implementation that `WEBUSB_POLYFILL_JS` calls via
  `callBridge('requestDeviceChooser', JSON.stringify(...))`. Confirmed against a real
  `staticMetaObject` (not just static reading) that `requestDeviceChooser` was completely
  absent from the registered Qt slots — QWebChannel could never have exposed it to JS — while
  the helper (whose real parameters are `usb_core`/`usb_util` module handles and
  `filters`/`exclusion_filters` lists, nothing resembling a `QString`) was registered instead.
  All existing tests call `requestDeviceChooser()` as a plain Python method, so none of them
  could catch this class of bug. Added `test_requestDeviceChooser_is_registered_as_qt_slot`,
  which asserts slot registration directly via `staticMetaObject`/`QMetaMethod`, and confirmed
  it fails against the broken version before re-fixing.
- Considered and deliberately **not** implemented: a lock around `_open_devices` (Qt's
  single-threaded event loop model means the claimed race condition doesn't apply here, and
  a mis-applied lock would be a worse bug than none) and USB handle-ID recycling (recycling
  IDs risks a *different*, worse bug — a stale JS reference resolving to the wrong device).
