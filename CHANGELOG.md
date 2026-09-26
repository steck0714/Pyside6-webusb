# Changelog

All notable changes to this project are documented here.

## [0.0.5.post7]

Informally `v0.0.5b3` (source zip filename/GitHub release label); `0.0.5.post7` is the version
string this release actually ships under everywhere (`_version.py`, `pyproject.toml`, sdist,
wheel), continuing the `.post` line for the same PEP 440 ordering reason as every previous
`.post` release on this project.

### Added

- **Built-in multi-language support: `en` / `ja` / `zh` (Simplified Chinese), via a new
  `pyside6_webusb.i18n` module.** Previously the device chooser dialog's default strings were
  English-only, and `diagnostics.py`'s environment report was Japanese-only, with no supported
  way to switch either — `chooser_dialog.WebUsbDeviceChooserDialog` already accepted a `strings=`
  override dict, but nothing in the only real call path (`bridge.py`'s
  `_request_device_chooser_impl` → `WebUsbDeviceChooserDialog(...)`) ever passed one, so it was
  unreachable in practice. `install()` and `WebUSBBridge.__init__()` gain `locale=` (`"en"`/
  `"ja"`/`"zh"`/`"auto"` to follow the OS locale/omit for the previous Japanese-only behavior) and
  `chooser_strings=` (a partial-override dict, or one of the locale strings as a shortcut).
  `diagnostics.environment_report()`/`format_environment_report()` gain the same `locale=`
  parameter, and `python -m pyside6_webusb` gains `--lang`/`-l`. **Backward compatibility:**
  `DEFAULT_LOCALE = "ja"` is a fixed default, not OS-autodetection — every call site that used to
  take no locale argument keeps producing byte-for-byte the same Japanese text it always did
  (verified: all pre-existing tests, including the ones asserting literal Japanese substrings in
  `format_environment_report()`'s output, pass unmodified). `chooser_dialog.DEFAULT_STRINGS` is
  now sourced from `i18n.CHOOSER_STRINGS["en"]` (single source of truth) but keeps its name/shape
  for anyone already importing it directly. New: `tests/test_i18n.py` (locale
  resolution/fallback, key-set parity across all three locales), `tests/test_chooser_dialog.py`
  (this file had **no dedicated tests at all** before this release — now covers per-locale
  rendering, partial `strings=` overrides, and the Connect-button-disabled-until-selected safety
  behavior), plus additions to `tests/test_install.py`/`tests/test_diagnostics.py` and a new
  JS-level locale-agnostic check is not needed since locale only affects Python-rendered UI, not
  `WEBUSB_POLYFILL_JS` itself.
- **`extra_guard_js=` parameter on `install()`.** Lets a host application inject its own
  JavaScript that defines `window.__pysideWebUSBExtraGuard(({origin, filters,
  exclusionFilters}) => boolean)`; `navigator.usb.requestDevice()` now calls it (if defined)
  immediately after filter-shape validation and *before* ever reaching the bridge or opening the
  chooser dialog, rejecting with `SecurityError` when it returns exactly `false` (a thrown guard
  is treated as `false` — fail closed). Returning `true`/`undefined` changes nothing; this hook
  can only add restrictions on top of this package's own checks, never loosen them. Injected as
  its own `QWebEngineScript` (`"PySide6WebUSBExtraGuard"`), positioned between the
  QWebChannel-library script and the main polyfill script, only when `extra_guard_js` is given —
  `install()` still injects exactly its previous two scripts otherwise (existing
  `test_install_injects_exactly_two_scripts_with_correct_injection_point_and_world` passes
  unmodified). This closes a gap between what was previously discussed for this project (a
  domain-specific polyfill guard hook) and what the shipped code actually had — nothing like it
  existed anywhere in `0.0.5.post6`. New: `test_install_injects_extra_guard_js_before_the_polyfill_when_given`
  (Python side) and a `tests/test_polyfill.js` block covering the false/throw/true/undefined
  return-value matrix, the exact `{origin, filters, exclusionFilters}` shape passed to the guard,
  and that a rejecting guard means `requestDeviceChooser` never reaches the bridge at all.
- **`scripts/verify_test_suite.py`** — a standalone health-check script answering "do the test
  files themselves actually still work", not just "does `pytest` report green". It separately
  checks: the running environment (`diagnostics.environment_report()`), the full `pytest`
  suite, **every individual `tests/test_*.py` file run directly** (`python tests/test_X.py` —
  the exact class of check that would have caught the `tests/test_virtual.py` bug described
  under Fixed below, since `pytest` alone did not), the Node.js polyfill test, and the TypeScript
  type check — auto-skipping the Node/tsc checks when those tools aren't installed rather than
  failing on their absence, and auto-detecting module-level `pytest.importorskip`/`pytest.skip`
  usage (currently only `test_rust_accel.py`) to correctly treat pytest-only-by-design test files
  as an expected skip rather than a direct-execution failure. Supports `--save-report path.json`
  for CI. Verified against this exact repository (clean run: all 5 categories PASS) and against
  an intentionally-broken copy of `test_errors.py` (correctly reports `FAIL` and exits `1`, then
  reverts to clean/exit `0` once restored — i.e. the script's own pass/fail detection was
  round-tripped, not just assumed to work).
- **`.gitignore`**, shipped in the source zip for the first time. `MANIFEST.in` has referenced
  "(see .gitignore)" in a comment since early in this project's history, but the file itself was
  never actually included in a distributed zip — a dangling reference. Covers the standard
  Python/Rust (`native/*/target/`, matching the `0.0.4b0` changelog's own note that the project's
  real `.gitignore` excludes this) and Node ignores, this release's own generated
  `tests/_polyfill_extracted.js` and `verify_test_suite_report.json`, and editor/OS cruft.

### Fixed

- **🐛 `pyside6_webusb.virtual._version_to_bcd()` silently produced a nonsensical version from a
  negative integer instead of raising.** `post6`/`v0.0.5b2` already rejected malformed strings,
  `bool`, and other unsupported types with `ValueError` (see that release's own changelog entry),
  but a bare negative `int` — or a negative component inside a `tuple`/`list` (e.g.
  `(2, -1, 0)`) — slipped through untouched. Python's `&` behaves as infinite-precision two's
  complement, so `_version_to_bcd(-1)` computed `(-1 & 0xFF) << 8` = `0xFF00` ("255.0"): a
  plausible-looking but completely unintended version, silently. This is the exact same failure
  mode the `post6` fix was written to close (a typo silently building a wrong-but-valid-looking
  virtual device instead of raising) — it just wasn't checked for the negative case. Reproduced
  directly (confirmed `_version_to_bcd(-1) == 0xFF00` and `_version_to_bcd((2, -1, 0))` silently
  corrupting only the `minor` nibble, before fixing). Both the `int` path and the `tuple`/`list`
  path now raise `ValueError` for any negative value; `0` itself is still valid. New:
  `test_virtual_version_to_bcd_rejects_negative_integers` (also confirms `0` and `(0, 0, 0)`
  still work).
- **🐛 `tests/test_virtual.py` could not actually be run directly** (`python tests/test_virtual.py`)
  **from a clean checkout**, contrary to what this file's `post6` changelog entry claims
  ("confirmed... `test_virtual`... still runs cleanly that way"). Unlike every one of its seven
  sibling files in `tests/` (`test_bridge.py`, `test_diagnostics.py`, `test_errors.py`,
  `test_frame_origin.py`, `test_hardening.py`, `test_install.py`, `test_rust_accel.py`), this
  file was missing the `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
  "src"))` bootstrap line that lets a direct script run find the `src/`-layout package without it
  already being installed. Under `pytest` this was invisible, since `tests/conftest.py` does the
  equivalent `sys.path` setup for every test regardless — which is presumably how the `post6`
  verification missed it (the package was very likely already importable in whatever environment
  that check ran in). Reproduced directly against a clean environment with the package not
  installed (`ModuleNotFoundError: No module named 'pyside6_webusb'`) before fixing. The same
  edit also replaces this file's comment-only assumption that `QT_QPA_PLATFORM=offscreen` is
  already set with the same active fallback every sibling file actually executes, for the same
  reason. Found while building `scripts/verify_test_suite.py` above — exactly the class of gap
  that script now exists to catch automatically going forward.

### Security review (updated after the user shared their GitHub repo's actual alerts)

A pass was requested against CWE-275, CWE-20, CWE-362 (cited alongside advisory ID
`GHSA-chgr-c6px-7xpp`), CWE-125 (cited alongside `GHSA-36hh-v3qg-5jq4`), CVE-2018-6125,
CVE-2020-16033, CWE-451, CWE-393, CWE-359, and CWE-770. This was first checked against this
package's own source with no further context (see the superseded findings kept below for that
pass); the user then shared screenshots of their actual GitHub repository's Dependabot PR #2 and
CodeQL "Code scanning alerts" list, which identify what several of these actually are:

- **`GHSA-chgr-c6px-7xpp` (CWE-362) and `GHSA-36hh-v3qg-5jq4` (CWE-125) are PyO3's own
  RustSec advisories**, fixed upstream in PyO3 0.29.0 ("Missing `Sync` bound on
  `PyCFunction::new_closure` closures" and "Possible out of bounds read in
  `BoundTupleIterator::nth_back`/`BoundListIterator::nth_back`" per PyO3's own changelog,
  matching these two CWE categories exactly) — not findings against this project's own code, but
  against the `pyo3` dependency of `native/pyside6_webusb_accel/`, exactly as Dependabot PR #2
  ("Bump pyo3 from 0.27.2 to 0.29.0") proposes. **Fixed**: `Cargo.toml`'s pin changed from
  `pyo3 = "=0.27.2"` to `pyo3 = "=0.29.0"`, and `Cargo.lock` was regenerated (`cargo
  generate-lockfile`, resolved against the real crates.io registry — not hand-edited). **Not
  verified**: this sandbox's system `rustc` is `1.75.0` (Ubuntu 24.04's packaged version), and
  `pyo3-ffi 0.29.0` itself requires `rustc>=1.83` to *compile* (confirmed directly: `cargo check`
  fails on the version gate, independent of and before any actual code compilation). Dependency
  *resolution* succeeded and is trustworthy (real registry, real checksums); actual compilation
  was not attempted or verified. **Action needed on your side**: build/CI environments for
  `native/pyside6_webusb_accel/` need `rustc>=1.83` for this bump — please run `maturin develop`
  (or your usual build) once with a current Rust toolchain and confirm it still builds before
  relying on this; per this project's own established policy, a Rust-side change should not be
  trusted as working until it has actually been built.
- **CWE-275 ("Workflow does not contain permissions", 2 CodeQL alerts) is about
  `.github/workflows/restore-pypi.yml:8` and `.github/workflows/github-actions-publish-pypi.yml:26`
  having no `permissions:` block.** These files are not part of this zip/sdist (GitHub Actions
  workflow files live only in the git repository, never in a PyPI distribution) and were not
  available to check or edit directly — reconstructing a full CI workflow that handles PyPI
  publishing credentials from phone-screenshot fragments risked introducing a real mistake into a
  credentials-handling file, so that was deliberately not attempted. The fix itself is simple and
  is the same for both files, per GitHub's own guidance shown in the alert: add a `permissions:`
  block at the workflow root (applies to every job that doesn't set its own) or per-job, scoped to
  the minimum each workflow actually needs (`contents: read` covers a checkout-and-build step;
  `restore-pypi.yml` and `github-actions-publish-pypi.yml` both look like they only checkout,
  build, and upload to PyPI via a token, so `permissions: contents: read` at the workflow root is
  likely sufficient for both — add `id-token: write` only if either was switched to PyPI's
  Trusted Publishing/OIDC flow rather than a `TWINE_PASSWORD` secret). Share the actual two files
  (or grant a way to fetch them) to get this applied directly rather than described.
- **CWE-20 ("Incomplete URL substring sanitization", 3 CodeQL alerts, `py/incomplete-url-substring-sanitization`)
  is about `tests/test_frame_origin.py` lines 222, 223, and 332** — this file *is* in this
  distribution, so this one was checked and fixed directly. All three flagged lines were
  `"https://some.origin" in <a set of origin strings>` — exact-match **set membership**
  (`origins = set(tracker._token_to_origin.values())` immediately precedes each one), not a
  substring search against a URL string. This is the false-positive shape CodeQL's rule can't
  distinguish from the real OWASP-SSRF pattern it targets (`"trusted.com" in some_url_string`,
  bypassable via `"evil.com/trusted.com"`) — there is no such string here, and no attacker-supplied
  value is being substring-matched. Confirmed directly by reading the surrounding code (not
  assumed from the alert text). **Fixed**: rewritten as subset comparisons
  (`{"https://top.example", "https://ok.example"} <= origins`) that are semantically identical but
  no longer match the flagged textual pattern, so the scanner won't re-flag this exact code again;
  `tests/test_frame_origin.py`'s full suite (11 tests, pytest and direct-execution modes both)
  still passes unchanged.

<details>
<summary>Superseded findings from the first pass (kept for the record, before the screenshots above provided ground truth)</summary>

- CVE-2018-6125 and CVE-2020-16033 are not new findings for this project — both are already cited
  in this exact `CHANGELOG.md` (`0.0.4b3`) as the precedent for the alternate-setting
  class-confusion fix and the `sanitize_device_string()`/forced-`PlainText` chooser-dialog fix,
  respectively, and both mitigations are still in place and still covered by
  `security_audit/test_altsetting_class_confusion.py` and
  `security_audit/test_malicious_device_ui_and_descriptors.py`.
- CWE-451 (UI misrepresentation): the same forced-`PlainText` `QLabel` rendering in
  `chooser_dialog.py` automatically covers this release's new localized strings too (`unknown
  device`/`SN` labels flow through the same `_DeviceRowWidget` code path) — confirmed by reading
  the code path rather than assumed.
- CWE-20 (improper input validation): the `virtual.py` fix under **Fixed** above is itself in
  this category. Beyond that, no new gap was found in the existing filter/base64/options-size
  validation already documented across this file's history.
- CWE-362 (race conditions): no new gap found beyond the existing `_busy_handles`/`_chooser_active`
  reentrancy guards and the `post6` `destroyed`-signal fix already in this file.
- CWE-125 (out-of-bounds read): the Rust crate at `native/pyside6_webusb_accel/` contains **zero**
  `unsafe` blocks (checked directly: `grep -c unsafe src/lib.rs` → `0`), so classic OOB memory
  reads are structurally not possible there under safe Rust; this package's own Python code has
  no raw `ctypes`/`struct`/buffer indexing either. Could not be built/run in this environment (no
  Rust toolchain available), so this is a source-reading review only, not a compiled/tested one.
- CWE-393, CWE-359, CWE-770, CWE-275: each maps to mitigations already specifically documented
  elsewhere in this file (`closeDevice()`'s JSON-string return fix; per-frame origin isolation and
  the `window.__pysideWebUSB` debug-namespace disclosure boundary; the transfer-size/handle-count/
  token-count caps; the origin-scoped grant model and the deliberate non-`@Slot` exposure of
  host-only methods) — no new gap found in this pass.
- **`GHSA-chgr-c6px-7xpp` and `GHSA-36hh-v3qg-5jq4` could not be looked up or verified** — this
  environment has no access to an external advisory database, and neither ID corresponds to
  anything in this project's own history. Rather than guess what they refer to, both are reported
  here as unverified. If they concern this project specifically, please share the advisory
  contents (or enable a way to fetch them) and they can be checked properly.

</details>



Informally `v0.0.5b2` (source zip filename/GitHub release label); `0.0.5.post6` is the version
string this release actually ships under everywhere (`_version.py`, `pyproject.toml`, sdist,
wheel), continuing the `.post` line for the same PEP 440 ordering reason as every previous
`.post` release on this project.

### Fixed

- **`FrameOriginTracker` no longer keeps trying to touch a destroyed `QWebEnginePage`.**
  Observed on real hardware and logged in `checklog2.md` ("45. QWebEnginePage Lifetime
  Observation"): after a page was destroyed, the tracker's periodic re-scan timer kept firing
  every 2 seconds and kept hitting `libshiboken: Internal C++ object (...QWebEnginePage)
  already deleted` — caught and ignored (so it never crashed), but with no way for the tracker
  to actually learn the page was gone, it repeated indefinitely. The timer being parented to
  the page doesn't fully protect against this: a delayed re-scan queued via `QTimer.singleShot`
  from `navigationRequested` handling has no parent at all, so nothing guaranteed it wouldn't
  fire after the page was gone. `FrameOriginTracker` now connects to the page's own `destroyed`
  signal — which Qt guarantees fires for every `QObject`, however it's being torn down — and
  stops the periodic timer and short-circuits any further re-scan the instant it fires (verified
  the timer is still safely stoppable at that exact moment, empirically, before relying on it).
  Also added an explicit `disconnect()` method for proactively tearing a tracker down while its
  page is still alive (`checklog2.md`'s own test harness tried calling exactly this method
  before it existed — "44. Cleanup Testing"). New tests:
  `test_tracker_stops_reacting_after_page_is_destroyed` (uses `shiboken6.delete()` to
  deterministically trigger real C++ destruction rather than relying on Python GC timing) and
  `test_tracker_disconnect_stops_timer_and_further_rescans_while_page_still_alive`.
- **`controlTransferIn/Out` with `recipient: "endpoint"` no longer wrongly blocks a legitimate
  transfer to a currently-active, benign endpoint.** `0.0.5.post5` hardened this path to check
  whether *any* alternate setting sharing the target endpoint address declares a protected
  interface class (HID, etc.) — a real device can legally have alt 0 (benign, currently
  selected after `claimInterface()`) and alt 1 (HID, not selected) both declaring the same
  endpoint address, which is exactly the "alternate setting class confusion" shape this
  project's own `VULNERABILITY_REPORT.md` documents. The `post5` check ran *before* determining
  which alternate actually owns the endpoint in the device's current state, so it rejected the
  legitimate alt-0 transfer just because the unrelated, unselected alt-1 happened to share the
  address — reproduced directly against `post5`'s code before fixing. The check now first
  determines the endpoint's current owner the same way `_endpoint_available_or_error()` already
  does (prefer the alternate setting actually tracked as selected for that interface), and only
  then checks whether *that* owner is protected; if no currently-selected alternate owns the
  address at all, it falls back to flagging any protected candidate, preserving the original
  defense-in-depth intent for the case where a page is fishing for a protected alternate's
  endpoint by raw address without ever legitimately selecting it. Rewrote
  `test_control_transfer_endpoint_recipient_blocks_protected_alternate` (which had encoded the
  bug as expected behavior — it only ever tested the shared-address case and asserted it must
  always be rejected) into
  `test_control_transfer_endpoint_recipient_alt_aware_protected_class_handling`, covering both
  directions explicitly. `security_audit/test_altsetting_class_confusion.py`'s existing
  hidden-HID-endpoint test is unaffected (it already used a non-shared endpoint address, i.e.
  the case this fix must continue to block) and still passes.
- **`tests/test_virtual.py` can be run directly again (`python tests/test_virtual.py`).** Three
  test functions added in `post5` (`test_virtual_version_to_bcd_formats` and two others) were
  appended *after* the file's `if __name__ == "__main__":` block instead of before it, so
  running the file as a script hit a `NameError` the moment it reached the first of them —
  reproduced directly. `pytest`-based runs were unaffected (it discovers tests independently of
  file order), which is presumably why this went unnoticed. Moved the block back to the end of
  the file, its normal position, after every test definition.
- **`VirtualUsbDevice(usb_version=..., device_version=...)` no longer silently produces a wrong
  version for malformed input.** The string-parsing path silently dropped any dot-separated part
  that wasn't a plain digit string (`version.split(".") if p.isdigit()`), so a typo like
  `"2.1.x"` quietly became BCD `0x0000` (version "0.0.0") instead of raising — the kind of
  mistake a developer using this for repeatable test fixtures would want to know about
  immediately, not discover later as a confusingly-versioned virtual device. Also, per this
  project's own established convention elsewhere (`hardening.is_valid_usb_device_filter()`
  explicitly rejects `bool` for numeric filter fields, since `bool` is a subclass of `int` in
  Python), passing a bare `True`/`False` is now explicitly rejected rather than silently
  interpreted as `1`/`0`. `None` remains a deliberate, still-tested exception — it means
  "unspecified" and continues to resolve to `0x0000`. New test:
  `test_virtual_version_to_bcd_rejects_malformed_input`.
- **`VirtualUsbConfiguration(description=...)` / `VirtualUsbInterface(name=...)` now actually
  work.** Both parameters were accepted and stored, but never wired to anything — `iConfiguration`
  and `iInterface` were hardcoded to `0` regardless, so `hardening.build_device_descriptor()`'s
  string-descriptor resolution (the same code path `listDevices()`/`getDevices()` use) could
  never find a name for either one; the strings a caller passed in were silently discarded. This
  bug predates `post5` — it's been present in `virtual.py` since the module was introduced in
  `0.0.5a3` and had gone unnoticed since neither existing test nor the module's own examples
  happened to check the round-trip. `VirtualUsbDevice.__init__` now interns both strings into its
  own string table (the same one manufacturer/product/serial already use) once it knows which
  device its configurations and interfaces belong to. Caught while building this release's
  `from_descriptor()` feature (below), whose round-trip test would otherwise have silently lost
  every name. New test: `test_virtual_configuration_and_interface_names_are_actually_resolvable`.

### Added

- **`VirtualUsbDevice.from_descriptor()`: record a real device once, replay it without hardware
  forever.** Builds a virtual device directly from a device descriptor dict in the exact shape
  `hardening.build_device_descriptor()` produces — i.e. exactly what `listDevices()`/
  `getDevices()` already hand to JS (vendor/product IDs, manufacturer/product/serial strings,
  every configuration/interface/alternate-setting/endpoint). The natural workflow: plug the real
  device in once, call `listDevices()` (or the debug namespace's
  `listGrantedDevices()`/`bridgeInfo()`), save the JSON, and reuse it indefinitely afterward with
  no hardware attached — for CI, for a bug repro that needs a specific real device's exact
  descriptor shape, or just to avoid re-plugging a device every test run. Missing fields fall
  back to harmless defaults, so a hand-written or partially-captured descriptor works too;
  `on_bulk_read=`/`on_bulk_write=`/`on_control_transfer=` remain available on top for simulating
  the device's actual protocol rather than the default zero-filled echo (descriptors don't carry
  transfer contents, only shape). Verified with a full round trip: build a `VirtualUsbDevice` by
  hand, turn it into a descriptor with `build_device_descriptor()`, reconstruct a new device with
  `from_descriptor()`, turn *that* into a descriptor again, and assert the two descriptors are
  byte-for-byte identical — including the configuration/interface name fix above, without which
  this round trip would have silently dropped every name. New tests:
  `test_virtual_device_from_descriptor_round_trips_through_build_device_descriptor` (also opens,
  claims, and transfers on the replayed device through a real `WebUSBBridge` to confirm it isn't
  just descriptor-deep) and `test_virtual_device_from_descriptor_tolerates_missing_optional_fields`.
  See README "Record a real device once, replay it forever".

### Tests

- `tests/` + `security_audit/`: **211 passed, 2 skipped**, up from `0.0.5.post5`'s 205 passed/2
  skipped (+2 `FrameOriginTracker` lifecycle tests, +1 rewritten control-transfer test replacing
  the one that encoded the bug, +3 `virtual.py` tests: malformed-version rejection, name
  resolution, and the `from_descriptor` round trip, +1 `from_descriptor` missing-fields test —
  net +6 after the 1-for-1 rewrite). `node tests/test_polyfill.js` and
  `tsc --strict --noEmit` against both `types/*.ts` files: unaffected, still pass. Also
  confirmed every test file with a `python tests/test_X.py` direct-execution mode (`test_bridge`,
  `test_hardening`, `test_frame_origin`, `test_virtual`, after the fix above) still runs cleanly
  that way, not just under `pytest`.

### Documentation

- README `Status` line, `.d.ts` version-tracking header comment, and the three short
  `README.{en,ja,zh}.md` overview pages updated from `v0.0.5a2`/`0.0.5.post3` (stale since before
  even `post4`) to `v0.0.5b2`/`0.0.5.post6`; their `Experimental Alpha` label also updated to
  `Experimental Beta` to match the `bN` tag now in use.
- README: new "Record a real device once, replay it forever" subsection under virtual USB
  devices, documenting `from_descriptor()`.

### Project metadata

- Version: `0.0.5.post6` (informally `v0.0.5b2`).

## [0.0.5.post5]

Referred to informally as `v0.0.5b1` during development; `0.0.5.post5` is the version string
this release ships under under PEP 440 (`pyside6_webusb-0.0.5.post5-py3-none-any.whl` and
`pyside6_webusb-0.0.5.post5.tar.gz`).

### Security & Hardening
- **Endpoint-targeted control transfer alternate setting protection**:
  Hardened `_control_transfer_validation_error` for `recipient == "endpoint"`. In composite
  devices where multiple alternate settings define an endpoint or where an alternate setting
  belongs to a protected interface class (e.g. HID), control transfers to that endpoint are
  strictly rejected with `SecurityError`, preventing bypass of `claimInterface` protections.
- **Strict type & boundary validation for USB device filters**:
  `hardening.is_valid_usb_device_filter` and polyfill's `isValidUsbDeviceFilter` now enforce
  strict type checks and numerical ranges (`vendorId`/`productId` in 0..65535, `classCode`/
  `subclassCode`/`protocolCode` in 0..255, and `serialNumber` must be a string).
- **Hardened options and base64 payload boundaries**:
  `requestDeviceChooser` rejects options JSON payloads exceeding 64KB and non-dictionary
  options objects. `_b64decode_or_data_error` validates string type and rejects oversized
  base64 payloads immediately with `DataError`.

### Features & Usability
- **Serial number device disambiguation in chooser dialog and `openDevice`**:
  `openDevice` now supports targeting a specific device by serial number (overloaded `@Slot(int, int, str, str)`),
  and `WebUsbDeviceChooserDialog` displays `SN: <serial>` in row details to easily distinguish
  multiple connected devices sharing identical Vendor ID and Product ID.
- **Standard WebUSB interface exposure on `window`**:
  `window.USB`, `window.USBConnectionEvent`, and `window.USBDevice` (`OpenWebUSBDevice`)
  are now exposed on `window` if not already defined, matching standard browser behavior.
- **Enhanced `VirtualUsbDevice` & `VirtualUsbBackend`**:
  `VirtualUsbDevice` now supports version input as integer (including BCD), string (e.g. `"2.1.0"`),
  or tuple/list, and supports buffer-based IN control transfers (`bytearray`/`memoryview`).
  `VirtualUsbBackend.find` supports `custom_match` and keyword-based attribute filtering.

## [0.0.5.post4]

Continues the `.post` line for the same reason `0.0.5.post2`/`0.0.5.post3` did: this project's
`0.0.5aN`-style alpha naming would sort *before* any already-published `.post` release under
PEP 440 and would never be installed by default. Referred to informally as `v0.0.5a3` during
development (source zip filename); `0.0.5.post4` is the version string this release actually
ships under, everywhere (`_version.py`, `pyproject.toml`, sdist, wheel).

### Security

- **`selectAlternateInterface()` now rejects switching into a protected interface class.**
  Closes the residual half of `security_report/VULNERABILITY_REPORT.md` finding No.1.
  `claimInterface()` only ever validates alternate setting 0's interface class (by design --
  see its own docstring on why alt-0-only is the right tradeoff, unchanged by this release).
  That means a composite device with a benign alt 0 and a protected-class alt 1 (HID, Mass
  Storage, etc.) could legitimately be claimed. What was missing: nothing stopped a page from
  then calling `selectAlternateInterface()` to switch straight into that protected alt --
  `_endpoint_available_or_error()` correctly resolves endpoints against whatever alternate is
  *currently selected*, so once switched, transfers to the protected alt's endpoints succeeded
  normally. `selectAlternateInterface()` now runs the same `interface_class_for()` +
  `is_protected_interface_class()` check claimInterface() already ran, against the *target*
  alternate setting, before allowing the switch. New tests:
  `test_selectAlternateInterface_rejects_switch_to_protected_class_alternate` (confirms the
  switch itself is rejected, and that the HID endpoint stays unreachable afterward) and
  `test_selectAlternateInterface_rejects_nonexistent_alternate_setting` (a target alternate
  setting that doesn't exist at all is now `NotFoundError`, matching the spec's "finding the
  alternate index" algorithm, rather than whatever error pyusb/libusb happened to raise).

### Fixed

- **`UsbHotplugWatcher`'s first `poll()` no longer fires spurious `connect` events for
  devices that were already plugged in before it started watching.** Real browsers don't
  dispatch `connect` for already-attached devices -- they're just visible via `getDevices()`
  from the start. The previous implementation diffed the current device set against an empty
  baseline on its very first poll, so every already-attached, already-granted device fired a
  synthetic `connect` once the hotplug timer's first tick landed (on top of already appearing
  in the initial `getDevices()` result). The first poll now only records a baseline;
  connect/disconnect diffing behaves as before from the second poll onward.
  `test_hotplug_watcher_diff` updated to reflect the corrected behavior; new test
  `test_hotplug_watcher_first_poll_never_fires_spurious_connect_events`. Known limitation,
  unchanged: identity is still `(vendor_id, product_id)` only, so two physically distinct
  devices sharing the same IDs can't be told apart on unplug (see README).
- **`claimInterface()` on an already-claimed interface is now the spec-correct no-op.** The
  WebUSB spec's `claimInterface()` algorithm resolves immediately, without touching hardware or
  re-checking the protected-class list, when the interface is already claimed. The previous
  implementation had no such check and unconditionally reset the tracked "currently selected
  alternate setting" back to 0 on every call -- so claiming an interface, legitimately
  switching to a non-zero alternate via `selectAlternateInterface()`, and then redundantly
  re-claiming the same interface would silently desync the tracked alternate (reset to 0) from
  the device's real state (still on the switched-to alternate), which
  `_endpoint_available_or_error()` relies on being accurate. New test:
  `test_claimInterface_redundant_reclaim_is_a_noop_and_preserves_alternate_tracking`.
- **`claimInterface()`/`releaseInterface()` on a nonexistent interface number now return
  `NotFoundError`.** Previously, claiming a nonexistent interface fell through to
  `interface_class_for()` returning `None`, which `is_protected_interface_class()` treats as
  protected (a deliberate safe-side fallback for the *real* case it's meant for) -- so the
  actual error was a misleading `SecurityError: interface X is class 'Unknown'`, blaming a
  protected class for what was really a nonexistent interface. `releaseInterface()` on an
  interface that was never claimed is now also a no-op that skips the hardware call entirely,
  matching the spec, instead of always calling into pyusb regardless of claim state. New tests:
  `test_claimInterface_rejects_nonexistent_interface_with_NotFoundError`,
  `test_releaseInterface_of_unclaimed_interface_is_a_noop`,
  `test_releaseInterface_rejects_nonexistent_interface_with_NotFoundError`.
- **`openDevice()` on a device that isn't connected now reports `NotFoundError`.** The spec's
  `open()` algorithm calls this out by name for a device that's no longer attached to the
  system. The previous implementation returned an unprefixed string, which
  `polyfill.py`'s `throwFromResult()` doesn't recognize, so it silently fell back to its
  default `NetworkError` instead. New test:
  `test_openDevice_reports_missing_device_as_NotFoundError`.
- **`_b64decode()`'s non-canonical-base64 rejection now applies on the Rust-accelerated path
  too.** Previously documented as a known gap (see `0.0.5.post2`/`.post3`): the optional Rust
  extension's `decode_base64()` skipped the round-trip canonical-form check the pure-Python
  path always ran. This release's environment still has no Rust toolchain to build and verify
  the actual extension against, so instead of touching the Rust side blind, the round-trip
  check (re-encode via Python's own `base64.b64encode()` and compare) now always runs in
  Python regardless of which path decoded the bytes -- one extra re-encode's worth of cost,
  applies uniformly either way. New test:
  `test_b64decode_rust_path_also_rejects_non_canonical_base64`, which installs a fake
  `_rust_accel` that deliberately skips validation (mirroring the documented real gap) and
  confirms the Python-side check still catches it.
- **JS: `close()`/`selectConfiguration()`/`reset()` now reset per-interface `claimed` state.**
  All three reset `[[claimedInterface]]` to false for every interface per the spec (`close()`
  as if `releaseInterface()` had been called for each claimed interface; the other two
  explicitly). `bridge.py`'s server-side state was already correct; the JS-side
  `OpenWebUSBDevice` object's own `iface.claimed`/`iface.alternate` were never being reset, so
  e.g. claiming an interface, switching configurations, and switching back left the JS object
  believing an interface was still claimed when the server-side handle had actually reset --
  leading to real transfer failures once a page trusted the (stale) JS-side flag.
  `close()` additionally now nulls `_handle` and is a true no-op (sends nothing to the bridge)
  when called on a device that isn't open, per spec. `tests/test_polyfill.js` extended
  accordingly; the existing close()-forwarding regression test was adjusted since `_handle` is
  now legitimately `null` after a successful close (it used to compare against the device's
  live `_handle`, which no longer holds the value it's checking for after this fix).

### Added

- **`navigator.usb` is now a real `EventTarget`.** `navigator.usb instanceof EventTarget` was
  confirmed `false` in real DevTools despite `types/webusb-polyfill.d.ts` declaring
  `interface USB extends EventTarget` -- the runtime object was a plain object literal with its
  own hand-rolled `addEventListener`/`removeEventListener`, never actually inheriting from
  `EventTarget`. `navigator.usb` is now an instance of a `USB` class that genuinely extends the
  environment's native `EventTarget` (QtWebEngine's Chromium has one), and dispatched
  `connect`/`disconnect` events are instances of a `USBConnectionEvent` class that genuinely
  extends `Event`, carrying a real `.device` property. Native `EventTarget`/`Event` reject the
  ES5 "constructor-stealing" pattern (`Parent.call(this)`) used everywhere else in this
  file's otherwise-ES5 style -- they're real ES6 class constructors that require `new` --
  so this one piece uses `class ... extends`, guarded behind a `typeof EventTarget === 'function'`
  check with a full ES5 fallback (matching the old behavior, minus `instanceof EventTarget`) for
  any environment without a native `EventTarget`. Existing `addEventListener`/`on(connect|
  disconnect)` behavior is unchanged and covered by the existing tests; this is additive.
- **`pyside6_webusb.virtual`: hardware-free virtual USB devices.** New module providing
  `VirtualUsbDevice`/`VirtualUsbConfiguration`/`VirtualUsbInterface`/`VirtualUsbEndpoint` (duck
  types matching the same minimal `usb.core`/`usb.util` surface this project's own
  `FakeDevice`-style test fixtures already relied on) and `make_virtual_usb_backend()`, wired in
  through a new `WebUSBBridge(usb_backend=...)` constructor parameter. Lets `navigator.usb` be
  exercised end-to-end -- chooser, permissions, `claimInterface()`, transfers, hotplug -- with
  no real hardware attached, through the *same* `bridge.py`/`hardening.py` code path a real
  device uses, so every existing security check (protected interface classes, the blocklist,
  origin-scoped permissions) applies to a virtual device exactly as it would to real hardware;
  confirmed with a dedicated test that a HID-class virtual interface is rejected by
  `claimInterface()` the same way a real one would be. Transfers default to a zero-filled echo
  response; `on_bulk_read`/`on_bulk_write`/`on_control_transfer` callables let a device simulate
  a real protocol instead. Hotplug simulation (`VirtualUsbDevice.plug()`/`.unplug()`) is picked
  up by the real `UsbHotplugWatcher` polling loop with no changes to `bridge.py`'s hotplug code
  at all -- confirmed by driving a real `UsbHotplugWatcher` instance against a virtual backend
  in `test_virtual_device_plug_unplug_is_detected_by_hotplug_watcher`. New file
  `tests/test_virtual.py` (5 tests). See README "Testing hardware-free with virtual USB
  devices" for usage and known limitations (no isochronous timing simulation, no kernel-driver
  concept, `reset()` keeps the same descriptor configuration).

### Documentation

- **License consolidated into a single `LICENSE` file.** Previously split across the MIT text
  plus a short separate qwebchannel.js note; now one file covering (1) incorporated/derived
  material with full upstream license text reproduced inline (Chromium's BSD-3-Clause USB
  blocklist data, the W3C-derived WebIDL in `types/webusb-polyfill.d.ts`), (2) external runtime
  dependencies (Qt/PySide6, pyusb, libusb, PyO3, the Rust `base64` crate), and (3) reference-only
  projects consulted during development (adb_client, thegecko/webusb, node-usb) -- each with its
  license type now individually confirmed by reading that project's own `LICENSE` file directly,
  not assumed. Corrects two factual errors found while consolidating: the W3C license actually in
  effect is the **2015-05-13** version (`W3C-20150513`), not 2023 -- confirmed by reading
  WICG/webusb's own `LICENSE.md`, which points at the 2015 URL specifically; and the Chromium
  blocklist source link (both here and in README) pointed at
  `services/device/usb/usb_blocklist.cc`, which 404s -- the file actually lives at
  `chrome/browser/usb/usb_blocklist.cc` (`hardening.py`'s own inline comment already had this
  right; only README and the old license note had the stale path). `pyproject.toml`'s
  `license` field updated from the inaccurate bare `"MIT"` to the PEP 639 expression
  `"MIT AND BSD-3-Clause AND W3C-20150513"`, matching what's actually incorporated. Also softened
  an over-definite "`qwebchannel.js` is BSD-3-Clause" claim (in `polyfill.py`'s docstring and
  README) to match LICENSE §2.1's more careful wording -- the exact license depends on the
  Qt/PySide6 distribution actually linked at runtime, which this project doesn't audit.
- Corrected a stale `hardening.py` docstring that still said isochronous transfers were
  unsupported "in this implementation" -- true when that comment was written (before
  `0.0.4a0` added `isochronousTransferIn`/`Out`), not since. Reworded to past tense, pointing
  at the actual current limitation (per-packet fidelity, documented in `0.0.5.post3`'s
  "Investigated, not changed").
- `types/webusb-polyfill.d.ts`'s version-tracking header comment updated from `v0.0.4a0` to
  `v0.0.5a3`, noting the `EventTarget`/state-reset changes above.
- README: fixed the same stale Chromium blocklist link noted above; updated the `Status` line's
  version and isochronous wording (it now correctly says isochronous *is* implemented, with a
  linked, specific known limitation, rather than implying it's entirely unverified); added a
  "Testing hardware-free with virtual USB devices" section; added a hotplug bullet documenting
  both the first-poll fix and the (unchanged, pre-existing) VID/PID-identity limitation.

### Packaging

- **Added `MANIFEST.in`.** The sdist and this source zip's `src/` tree have always been
  byte-for-byte identical (verified again this release), but the *sdist* was missing
  `tests/`, `security_audit/`, `security_report/`, `types/`, `examples/`, and `CHANGELOG.md`
  entirely -- there was no `MANIFEST.in`, and `setuptools`' sdist defaults don't reach any of
  those directories. Anyone installing from sdist rather than this zip had no way to run the
  test suite described in README "Testing", and no access to the TypeScript definitions in
  `types/`. Now included.

### Tests

- `tests/` + `security_audit/`: **198 passed, 2 skipped**, up from `0.0.5.post3`'s 184
  passed/2 skipped: +9 new regression tests for the fixes above, +5 new tests in the new
  `tests/test_virtual.py` (198 = 184 + 9 + 5). `node tests/test_polyfill.js`: all cases pass,
  including the `EventTarget`/state-reset changes above.
  `tsc --strict --noEmit` against both `types/*.ts` files: still passes (no breaking change to
  the public type surface — `USB extends EventTarget` was already declared; the runtime now
  actually matches it).

### Project metadata

- Version: `0.0.5.post4` (informally `v0.0.5a3`).

## [0.0.5.post3]

Continues the `.post` line from `0.0.5.post2` for the same reason that release continued it
from `0.0.5.post1`: this project's own `0.0.5a1`-style alpha naming would sort *before* any
already-published `.post` release under PEP 440 and would never be installed by default.
Referred to informally as `v0.0.5a2` during development; `0.0.5.post3` is the version string
this release actually ships under, everywhere.

### Added

- **`pyside6-webusb-doctor --json` / `python -m pyside6_webusb --json`.** Prints
  `environment_report()`'s dict as JSON on stdout instead of `format_environment_report()`'s
  human-readable text — same exit-code meaning (non-zero on a real problem) as the existing
  text mode, which remains the default when `--json` isn't given. This project's own
  `__main__.py` docstring already documented a CI use case for the plain text mode
  ("このジョブのPySide6/libusbセットアップは壊れていないか"); `--json` extends that same use
  case to CI jobs that want to archive the report as a structured artifact or branch on
  specific `problems` entries programmatically, rather than pattern-matching the text output.
  `main(argv=None)` had accepted (but never read) an `argv` parameter since `0.0.5a0` — this is
  its first actual use. Confirmed necessary, not just tidy, by reading the actual
  `pyside6-webusb-doctor` script `pip install` generates: it calls `sys.exit(main())` with no
  arguments, so `main()` reading `sys.argv[1:]` itself (when `argv` isn't explicitly passed) is
  what makes a real `pyside6-webusb-doctor --json` invocation from a shell work at all, not only
  the explicit-`argv` form used in this project's own tests.

### Compatibility

- **`diagnostics.environment_report()`: `pyusb_backend_note`.** Set when `pyusb_backend`
  resolves to `"libusb0"` — pyusb's older backend, reached only as a fallback when its newer
  `libusb1` backend's shared library isn't found. Not a `problems` entry (`libusb0` is still a
  working backend), but this project's own `security_report/VULNERABILITY_REPORT.md`
  ("Environment note") already recorded that `pyusb 1.3.1`'s `libusb0.py` emits a
  `DeprecationWarning` under Python 3.14 about a `ctypes.Structure` `_pack_`/`_fields_` pattern
  scheduled to become an error in Python 3.19 — an upstream `pyusb` issue, confirmed by reading
  `usb/backend/libusb1.py`'s own source in the installed `pyusb 1.3.1` package, not just
  restating the earlier note secondhand. Re-checked whether the warning fires under this
  release's own Python (3.12.3): it does not, consistent with the original note being specific
  to 3.14+ rather than a regression introduced here. The note points at installing an OS-level
  `libusb1` shared library as the practical way to stop depending on the `libusb0` path at all.
  Wired into `format_environment_report()` the same way `frame_origin_isolation_note` is: an
  extra "参考:" line, only when the note is actually set.

### Investigated, not changed

- **Isochronous IN transfers' per-packet fidelity, revisited.** `security_report/
  VULNERABILITY_REPORT.md`'s "Noted but not scored" entry already flagged that a short
  `isochronousTransferIn()` result can leave later reconstructed packets silently truncated or
  empty while still reporting `status: "ok"`. Traced this to its root cause this time by reading
  the installed `pyusb 1.3.1`'s `usb/backend/libusb1.py` directly: libusb's own
  `_libusb_iso_packet_descriptor` struct *does* carry a per-packet `actual_length` (and status)
  for every packet in an isochronous transfer, but pyusb's public `iso_read()` only returns the
  *sum* of every packet's `actual_length` as one combined integer — the per-packet breakdown
  this project's code would need exists inside pyusb's C-level transfer struct, but never
  reaches pyusb's own Python API surface. Getting genuine per-packet fidelity would mean
  reaching past `iso_read()` into pyusb's private transfer-handling internals, which is exactly
  the kind of "riskier... rather than a rushed half-solution" change `0.0.4b2`'s isochronous
  entry already declined to make without real hardware to verify against, and this release has
  no more access to real isochronous hardware than that one did. Left as-is, with this concrete
  root cause now recorded in case a future release has real hardware to verify a fix against.

### Tests

- `tests/` + `security_audit/`: **184 passed, 2 skipped** in the environment this release ran
  in, up from `0.0.5.post2`'s 183 passed/1 skipped: +1 genuinely new test
  (`test_main_json_flag_prints_the_raw_report_as_json_with_the_same_exit_code`) plus one new
  test that itself skips in this particular environment
  (`test_environment_report_notes_libusb0_fallback_without_treating_it_as_a_problem`, added to
  cover `pyusb_backend_note` — skips here because this sandbox's `libusb0.get_backend()` fails
  too once `libusb1`'s is forced to fail, so the specific "`libusb1` absent, `libusb0` present"
  fallback this test targets can't be reproduced in this environment; the existing, similarly
  environment-dependent `test_rust_accel.py` skip is unrelated and unchanged). Also updated
  `test_main_returns_zero_when_clean_and_nonzero_when_problems` to pass `argv=[]` explicitly
  rather than relying on `main()`'s (now meaningful, not just accepted-and-ignored) default —
  otherwise this test would have started depending on whatever arguments the outer `pytest`
  invocation itself happened to receive. `node tests/test_polyfill.js` and
  `tsc --strict --noEmit` against both `types/*.ts` files: unaffected by this release (no
  changes to `polyfill.py`'s embedded JS or to `types/`), re-run anyway and still pass.

### Project metadata

- Version: `0.0.5.post3`.

## [0.0.5.post2]

Merge of two independent verification passes run in parallel against the same `0.0.5.post1`
starting point — one against a real **Python `3.15.0rc2`** / **`PySide6 6.12.0a1.dev1789538080`**
environment focused on this project's *test harness and Rust build*, the other against the same
pre-release wheels/source tree focused on this project's *shipped Python logic* — plus one
further, structural bug this merge itself found by actually re-running the combined result
rather than assuming two independently-green test runs stay green once spliced together. Nothing
under `src/pyside6_webusb/` needed any change to keep working on 3.15/6.12.0a1 beyond what's
listed below; both starting passes independently re-confirmed the `178 passed/1 skipped`
`0.0.5a0` baseline held before either touched anything.

**Version:** continuing the `.post` line from the already-published `0.0.5.post1` — `0.0.5a1`
would sort *before* `0.0.5.post1` under PEP 440 and would never be installed by default, the same
"labeled `0.0.5a0`, shipped `0.0.5.post1`" discrepancy this project's own `0.0.5a0` entry already
flagged in its own "Project metadata" below. Referred to informally as `v0.0.5a1` during
development (both merged sources' own `_version.py` said this, one of them explicitly "per
instruction"); `0.0.5.post2` is the one version string this release actually ships under,
everywhere, to avoid repeating that exact discrepancy a second time.

### Security

- **`_b64decode()` (`bridge.py`) now rejects non-canonical base64** — e.g. `"Zh=="`, which
  `base64.b64decode()` has always decoded leniently to the same bytes as the correct `"Zg=="`
  (RFC 4648 §3.5: non-zero padding bits). `data_b64` arguments to `controlTransferOut`/
  `bulkTransferOut`/`isochronousTransferOut` reach this function via `QWebChannel`, which exposes
  `WebUSBBridge` as a plain JS object — a frame that skips `WEBUSB_POLYFILL_JS` and calls these
  slots directly can pass any string it likes, not only what a real `btoa()`-based encoder would
  produce. On Python 3.15+, uses the native `canonical=True` parameter `base64.b64decode()`
  gained in that release — confirmed by reading `Lib/base64.py` and `Modules/binascii.c` directly
  in the `Python-3.15.0rc2` source tree, not just `Doc/whatsnew/3.15.rst`'s prose. On 3.9–3.14,
  falls back to a version-independent equivalent (decode leniently, then verify
  `b64encode(decoded) == original`), guarded by a narrow `except TypeError` in case
  `canonical=`'s exact shape changes before 3.15's final release. **Known gap, left as such
  rather than guessed at**: the optional Rust acceleration path
  (`native/pyside6_webusb_accel`'s `decode_base64`) does not get this check — no Rust toolchain
  was available in the environment this fix was written in (only a detached `.asc` signature for
  `rust-1.98.1`, not the toolchain itself), and this project's policy is not to ship a Rust-side
  "fix" that wasn't actually built and run. Anyone building the accelerated extension should
  apply the same check to `decode_base64` before relying on it for the same guarantee the
  pure-Python path now has.

### Fixed

- **`install()` could raise a raw `ImportError`/`ModuleNotFoundError` instead of the `None` its
  own docstring promises** ("QWebChannel自体が使えない環境では例外を送出せず None を返す").
  `from PySide6.QtWebChannel import QWebChannel` and
  `from PySide6.QtWebEngineCore import QWebEngineScript` sat *before* `install()`'s own
  `try`/`except Exception: return None`, not inside it — so if either import itself failed (as
  opposed to `QWebChannel(page)`/`registerObject()` failing at the following lines, which *were*
  already covered), the promised graceful-`None` path was never reached. Found while checking
  this package against the `PySide6 6.12.0a1` package split described under "Added" below. Moved
  both imports inside the existing `try` block; no behavior change for the already-covered
  failure modes. Covered by
  `test_install_returns_none_instead_of_raising_when_qtwebenginecore_is_unimportable`.
- **Malformed `data_b64` surfaced to JS as a generic `NetworkError` instead of the `DataError`
  real Chrome uses for malformed transfer data.** `controlTransferOut`/`bulkTransferOut`/
  `isochronousTransferOut` all called `_b64decode(data_b64)` directly; a `binascii.Error` from it
  fell through to each method's own generic `except Exception` handler, which has no
  `errors.py`-style prefix, so `polyfill.py`'s `throwFromResult()` couldn't match it to any
  `DOMException` and fell back to its default. A new `_b64decode_or_data_error()` wrapper
  (matching the existing `_control_transfer_validation_error()` early-return shape) is now used
  at all three call sites. Covered by
  `test_bulkTransferOut_reports_malformed_base64_as_DataError_not_generic_NetworkError`.
- **`node tests/test_polyfill.js` failed immediately with `TypeError: bridge.mintGestureToken is
  not a function`, and would still have failed on a later assertion (`connect`/`disconnect`
  event dispatch never firing) once that first error was fixed.** This Node-based harness's fake
  bridge object had never been updated for either of two bridge methods `0.0.4b3`'s security
  audit added — `mintGestureToken` (user-gesture verification) and `isGrantedToThisFrame` (the
  hotplug-leak fix) — so calling either from the real `polyfill.py` JS crashed the script
  outright, or threw inside a `try`/`catch` that silently swallowed the failure. Neither was
  caught by `pytest tests/ security_audit/` passing, since this is a separate Node process this
  project's own README already documents as a distinct step. Added both to the fake bridge;
  `requestDeviceChooser`'s mock signature also updated to accept the `gestureToken` parameter the
  real bridge now requires.
- **`tests/test_diagnostics.py::test_package_import_and_install_survive_pyside6_being_unavailable`
  hardcoded `"import_ok=0.0.5.post1"` as a literal**, which would have needed a manual edit on
  every future version bump — and, in one of this release's two starting points, did get one, to
  a second hardcoded literal (`"0.0.5a1"`) that this merge did not keep, for the same reason.
  Changed to compare against `pyside6_webusb.__version__` read dynamically from the outer test
  process, matching the pattern this same file's
  `test_environment_report_reflects_the_running_interpreter_and_is_clean` already used a few
  lines above it.
- **A structural bug this merge itself introduced was caught before shipping, not after.**
  Combining the two starting points' independent edits to `tests/test_bridge.py` briefly lost the
  `def test_bulk_transfer_rejects_out_of_range_endpoint_number():` line — the same "silently
  becomes an unlabeled tail of the previous test" failure mode this project's own `0.0.4b1`/
  `0.0.4b2`/`0.0.5a0` entries have each hit before, this time surfacing while splicing in this
  release's two new base64 tests immediately above it. Caught by actually running
  `pytest tests/test_bridge.py --collect-only` and checking the count against expectations before
  trusting the merge — the same practice this project always applies to a single change, applied
  here to the merge step itself — rather than assuming two independently-green test files stay
  green once spliced together. Restored; `tests/test_bridge.py`'s own
  `if __name__ == "__main__":` block (a second, pytest-independent way this file can be run) also
  gained calls for the two new tests it was still missing.

### Added

- **`diagnostics.environment_report()`: `qtwebengine_importable`.** Installed `PySide6 6.12.0a1`
  (2026-09 development build) `pyside6-addons`/`pyside6-webengine`/`pyside6-essentials` dev
  wheels into separate venvs and compared their contents directly (`unzip -l`):
  `QtWebEngineCore.abi3.so`/`QtWebEngineWidgets.abi3.so`, present inside `pyside6-addons` in
  every released version through `6.11.2`, have moved into a new, separate `pyside6-webengine`
  wheel — not yet published to PyPI under any released version as of this writing, so this
  package's `pyproject.toml` dependencies are deliberately **not** changed to require it yet.
  This field, and the accompanying `problems` entry naming `PySide6-WebEngine` specifically,
  exist so that failure is diagnosable rather than a bare `ModuleNotFoundError` with no further
  guidance if/when that split reaches a real release.
- **`diagnostics.environment_report()`: `frame_origin_isolation_available` /
  `frame_origin_isolation_note`.** Installed `PySide6-Essentials`/`Addons` `6.6.0`, `6.7.0`, and
  `6.8.0` into separate venvs to binary-search exactly which release first shipped
  `QWebEngineFrame` (absent in `6.6.0`/`6.7.0`; present from `6.8.0`) — the class
  `frame_origin.FrameOriginTracker` (`0.0.2b0`/`0.0.3`/`0.0.3a0`/`0.0.3b0`) depends on for
  cross-origin iframe spoofing protection. This project's declared floor is
  `PySide6-Addons>=6.5`, meaning `6.5`–`6.7` were, until now, silently falling back to the weaker
  pre-`0.0.2b0` `page.url()`-based origin model with no way for a host app to know.
  `frame_origin.py`'s `is_functional` docstring updated with the same concrete `6.8.0` figure.
  Both new fields got their own dedicated tests during this merge
  (`test_environment_report_detects_missing_qtwebengine`,
  `test_environment_report_reports_frame_origin_isolation_availability`) — the starting point
  that added the fields had also wired them into `format_environment_report()` and the README,
  but had not yet added direct unit tests for either one.
- **Optional Rust acceleration crate now builds an `abi3` wheel** (`pyo3`'s `abi3-py39` feature),
  fixing `maturin build` failing outright against Python 3.15 (`error: the configured Python
  version (3.15) is newer than PyO3's maximum supported version (3.14)` against the pinned
  `pyo3 =0.27.2`). Built with `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`; the resulting `cp39-abi3`
  wheel imports and round-trips correctly under `3.15.0rc2`. Independent of the 3.15 issue that
  surfaced it, this is a net improvement: one `abi3` build now covers this package's entire
  `requires-python = ">=3.9"` range instead of a separate version-specific build per Python minor
  version. See the README's new "Building against very new Python versions" section.

### Tests

- `tests/` + `security_audit/`: **183 passed, 1 skipped** in the environment this merge itself
  ran in (up from the `0.0.5a0` baseline's 178 passed/1 skipped by +5 genuinely new tests: the
  three from "Fixed"/"Added" above plus the two this merge itself wrote for the new diagnostics
  fields; the `def`-line restoration is a wash against this baseline since it only repairs a
  regression this merge's own splicing step introduced partway through, not a net-new test).
  The 1 skip is the same pre-existing, environment-dependent "Rust extension not built" skip in
  `test_rust_accel.py` (no Rust toolchain in this merge's own environment).
  One of the two starting points' own environments did have a working Rust toolchain and
  separately reported **188 passed, 0 skipped** there with the new `abi3` extension actually
  built — not independently reproduced by this merge, whose own environment had no toolchain
  either, consistent with the "Security" section's known Rust-side gap above. `node
  tests/test_polyfill.js`: all assertions pass with the fake-bridge fix above — but only once
  `tests/_polyfill_extracted.js` (the generated file this harness actually loads, per
  `extract_polyfill_js.py`'s own documented usage) is regenerated from the current
  `polyfill.py` first; the copy that arrived checked into this merge's own starting tree had
  drifted stale (predating the `mintGestureToken`/`isGrantedToThisFrame` codepaths it needed to
  exercise), which read as a fake-bridge-mock failure until re-running the extraction step
  confirmed the actual mismatch. Re-running `python tests/extract_polyfill_js.py` before
  `node tests/test_polyfill.js` is required after any change to `polyfill.py`, generated file
  or not.

### Project metadata

- Version: `0.0.5.post2`.
- This entry merges two independent verification passes that were run in parallel against the
  same `0.0.5.post1` starting point. Their changes were almost entirely non-overlapping by file:
  one touched only this project's test harness (`tests/test_polyfill.js`) and Rust build config
  (`native/pyside6_webusb_accel/Cargo.toml`); the other touched only `src/pyside6_webusb/`'s
  actual logic (`bridge.py`, `diagnostics.py`, `frame_origin.py`, `polyfill.py`) and its matching
  tests. `README.md` and `tests/test_diagnostics.py`'s version-literal assertion were the only
  two files both touched; both are reconciled above (taking the more general, non-hardcoded fix
  for the latter) rather than picked from one side arbitrarily.

## [0.0.5a0]

Feature release on top of `0.0.4b3`: one new host-app-facing capability
(`grant_device_for_origin()`), a new environment-diagnostics module + CLI, and three fixes found
while verifying this release in a real `Python 3.14.7` / `PySide6-Essentials`/`PySide6-Addons`
`6.11.2` environment — including one in this release's own new diagnostics feature, found by
actually installing the built wheel rather than trusting its unit tests alone (see "Fixed,"
below). Marked `a0` (alpha) rather than a plain patch bump since this adds behavior rather than
only fixing it — same reasoning as `0.0.1a0`/`0.0.2b0`/`0.0.3a0`/`0.0.3b0`/`0.0.4a0` before it.
The archive this release started from already had its version string bumped to a plain `0.0.5`
with no corresponding changelog entry; nothing beyond the two `0.0.4b3`-inherited items under
"Fixed" below (the `closeDevice()` gap and the test file's missing `def` line) was found to
differ from `0.0.4b3`'s documented end state, but this project has no record of what, if
anything, else `0.0.5` was meant to contain, and this entry does not claim to speak for it.

### Added

- **`WebUSBBridge.grant_device_for_origin(origin, vendor_id, product_id)`.** The management-only
  methods next to it (`list_granted_origins()`/`revoke_origin_grant()`/`revoke_all_for_origin()`)
  let a host app inspect and revoke grants, but nothing let it *create* one without routing
  through the chooser dialog — an asymmetry with no way to pre-authorize a device the way
  Chrome's enterprise
  [`WebUsbAllowDevicesForUrls`](https://chromeenterprise.google/policies/#WebUsbAllowDevicesForUrls)
  policy does, which kiosk/embedded deployments need (the set of allowed origins/devices is
  fixed by configuration, not decided by an end user clicking "Connect" in a dialog they may
  never even see). Shares `_grant()`/`_is_granted()` and the same `QSettings`-backed persistence
  as a grant obtained through the normal flow, so a pre-authorized device is indistinguishable
  from — and immediately visible to `listDevices()`/`navigator.usb.getDevices()` alongside — one
  granted the usual way, and can later be removed with the existing `revoke_origin_grant()`.
  Rejects blocklisted (known-security-key) devices for the same reason `openDevice()` does —
  arguably more important here, precisely *because* this path bypasses the user interaction that
  the chooser dialog would otherwise provide as a second layer. Deliberately **not** a `@Slot`,
  for the same reason `list_granted_origins()`/`revoke_origin_grant()`/`revoke_all_for_origin()`
  aren't (see `0.0.4b2`): `install()` injects the polyfill into `MainWorld`, so any `@Slot`
  on the bridge is reachable by *any* page opening its own `QWebChannel` connection directly,
  regardless of what `polyfill.py`'s own JS does or doesn't call — a method that hands out device
  access with no user gesture at all must never be one.
- **`pyside6_webusb.diagnostics`: `environment_report()` / `format_environment_report()`.** Most
  "`navigator.usb` isn't working" reports turn out to be an environment problem — old/missing
  PySide6, or `pyusb` installed without an OS-level `libusb` backend behind it — rather than a
  bug in this package's own logic, and there was previously no single place to check that
  (`isAvailable()` is JS/DevTools-facing and doesn't cover the Python-side environment at all).
  `environment_report()` returns a plain, JSON-safe dict (Python version/implementation,
  `PySide6`/`shiboken6`/Qt-runtime versions, `pyusb` version and which backend — `libusb1` vs
  `libusb0` — actually resolved, Rust-acceleration status, and a `problems` list);
  `format_environment_report()` renders the same as human-readable text. Deliberately has zero
  `PySide6`/`QtCore` import at module scope — a tool for diagnosing whether `PySide6` is
  reachable at all would be self-defeating if it could only run once `PySide6` already is.
  Missing Rust acceleration is reported but intentionally never added to `problems`: it's a
  fully-supported, optional fallback (see "Rust acceleration (optional)" in the README), not a
  broken state.
- **`python -m pyside6_webusb`** (new `__main__.py`) and, once installed, **`pyside6-webusb-doctor`**
  (new `[project.scripts]` entry point) both print `format_environment_report()`'s output and
  exit `1` if `problems` is non-empty, `0` otherwise — usable as a one-line CI/support-tooling
  sanity check (`python -m pyside6_webusb || echo "environment broken"`), not just interactively.
  `environment_report`/`format_environment_report` are also re-exported from the package's own
  `__init__.py`.

### Fixed

- **`import pyside6_webusb` itself failed with a raw `ModuleNotFoundError` in any environment
  missing `PySide6-Essentials`/`PySide6-Addons` — including the exact environment the new
  `environment_report()`/`python -m pyside6_webusb`/`pyside6-webusb-doctor` (see "Added," above)
  exist to help with.** `__init__.py` imported `bridge.py` (which imports `PySide6.QtCore`
  unconditionally at module scope) before `diagnostics.py`, so the package's own import chain
  hit the missing dependency and died before a caller could ever reach the diagnostic tooling —
  a self-defeating failure mode for a tool whose entire premise is "help figure out what's wrong
  with your `PySide6` install." Found the same way several other issues in this project's
  history have been: by actually installing the built wheel with `--no-deps` into a clean venv
  (deliberately *not* installing `PySide6`) and running `pyside6-webusb-doctor` against it,
  rather than trusting that the new feature worked because its own mocked unit tests passed —
  those tests (see "Tests," below) all ran in a process where `pyside6_webusb` and `PySide6`
  were already successfully imported earlier, so none of them actually exercised this exact
  failure path. `__init__.py` now imports `diagnostics` first and wraps the `PySide6`-dependent
  imports (`bridge`, `chooser_dialog`, `polyfill`) in a `try`/`except ImportError` that inspects
  `.name` to distinguish a genuinely-missing `PySide6`/`shiboken6` (degrade gracefully) from any
  other `ImportError` (a real bug in this package's own code, which must still surface loudly,
  not be misreported as "PySide6 is missing"). `install`/`WebUSBBridge`/`WebUsbDeviceChooserDialog`
  become a small stub that raises a clear `ImportError` — chained from the original — pointing at
  `python -m pyside6_webusb` when actually called, rather than either working partially or
  failing with a confusing `NoneType`/`AttributeError` later. **A second, subtler bug turned up
  fixing the first one**: the stub closure initially referenced the `except ImportError as _e`
  variable directly, which Python 3 automatically deletes at the end of the `except` block (to
  avoid the traceback keeping a reference cycle alive) — so calling the stub *later*, well after
  that block had already exited, raised `NameError: name '_e' is not defined` instead of the
  intended message. Fixed by copying the exception into an ordinarily-scoped variable before the
  closure captures it. Both bugs are covered by
  `test_package_import_and_install_survive_pyside6_being_unavailable`, which runs a real
  subprocess with `python -S` (site-packages excluded entirely, so `PySide6`/`pyusb` are
  genuinely absent rather than merely mocked) and checks both that `import pyside6_webusb`
  succeeds and that calling each stub actually raises the intended message rather than crashing
  differently.
- **`closeDevice()` could dispose a device out from under an in-progress chunked bulk transfer**
  — a gap the `0.0.4b` entry's docstring had explicitly named and deferred ("より完全な修正は
  将来のバージョンで検討する"). `bulkTransferIn()`/`bulkTransferOut()` yield to the Qt event
  loop (`processEvents()`) between sub-chunks of a large transfer so the UI thread doesn't
  freeze; transfer-vs-transfer reentrancy on the same handle during that window was already
  guarded via `_busy_handles`, but `closeDevice()` never checked the same marker, so a
  same-handle `close()` arriving in that window could `dispose_resources()` the device while a
  transfer loop still held a reference to it. `closeDevice()` now checks `_busy_handles` exactly
  like the transfer methods do and rejects with `InvalidStateError` instead, verified by
  reproducing the actual reentrant call via a monkeypatched `QCoreApplication.processEvents`
  (`test_closeDevice_rejects_close_while_handle_is_mid_chunked_transfer`) rather than reasoning
  about it in the abstract — the same technique the original `0.0.4b`
  transfer-vs-transfer reentrancy test already used, now reused for this second call path.
  `closeDevice()` had no dedicated tests at all before this release (a contributing reason the
  original always-returns-`None` bug that `0.0.4b3`'s security audit (finding No.4) caught went
  unnoticed as long as it did); it now has three (`test_closeDevice_returns_json_and_disposes_the_device`,
  `test_closeDevice_rejects_invalid_handle`, plus the reentrancy test above), and the test-only
  `FakeUsbUtil` fixture gained a real `dispose_resources()` (previously absent — meaning the
  production code's call to it was silently swallowed by the surrounding `try`/`except` in every
  existing test) so disposal can actually be asserted on rather than merely not-crash on.
- **A structural bug in `tests/test_bridge.py`, of the same shape `0.0.4b1` had already fixed
  once for a different test:** `test_bulk_transfer_reentrant_call_on_busy_handle_is_rejected`'s
  `def` line was missing, so its entire body (a valid, already-passing set of assertions) was
  silently executing as an unlabeled tail appended to the end of the preceding
  `test_bulk_transfer_round_trips_realistic_adb_wrte_message` — collected and run as part of
  that test, but never on its own, and absent from every test list and count. Caught the same
  way `0.0.4b1` caught the original instance: by actually running `pytest --collect-only` and
  checking the resulting count against expectations, not by assuming the file's structure
  matched its contents. Restored the missing `def` line; the test now collects and passes on its
  own (`tests/` collection count: 79 → 80).

### Tests

- `test_bridge.py`: the restored `test_bulk_transfer_reentrant_call_on_busy_handle_is_rejected`;
  `test_closeDevice_returns_json_and_disposes_the_device`,
  `test_closeDevice_rejects_invalid_handle`,
  `test_closeDevice_rejects_close_while_handle_is_mid_chunked_transfer`;
  `test_grant_device_for_origin_persists_without_chooser_and_is_symmetric_with_revoke`,
  `test_grant_device_for_origin_rejects_blocklisted_device`,
  `test_grant_device_for_origin_rejects_missing_origin`. Extended the existing
  `test_requestDeviceChooser_is_registered_as_qt_slot` regression test (it enumerates every
  method that must *not* be a JS-reachable `@Slot`) to also cover `grant_device_for_origin`.
- `tests/test_diagnostics.py` (new file, 9 tests): a clean-environment baseline against the
  actual installed `PySide6`/`shiboken6`/`pyusb` in the verification environment (not mocked),
  plus `sys.modules`-`None` injection (the standard "simulate an uninstalled package" pytest
  idiom) to exercise the missing-`PySide6`, missing-`pyusb`, and `pyusb`-without-a-`libusb`-
  backend paths, `format_environment_report()`'s two branches, and both exit codes of
  `python -m pyside6_webusb`'s `main()`. Two of this file's own first-draft assertions turned out
  to be wrong once actually run rather than merely reasoned about — `shiboken6` doesn't share
  `PySide6`'s `sys.modules` entry (it's an independent top-level package, not a submodule), and
  `PySide6.QtCore` specifically needed its own `sys.modules[...] = None` alongside `PySide6`'s
  own, since CPython's import machinery resolves an already-cached dotted submodule straight
  from `sys.modules` without re-checking whether its parent package was blocked — both fixed
  after the failure surfaced, not asserted away. The `__init__.py`-resilience regression test
  (`test_package_import_and_install_survive_pyside6_being_unavailable`, see "Fixed," above) went
  through the same kind of correction: a first draft used the same `sys.modules`-`None` trick,
  which triggered an unrelated crash from `shiboken6`'s own site-initialization signature-support
  hook reacting badly to an artificially-blocked-but-actually-installed `PySide6` — not a sign
  the underlying fix was wrong, but a sign the simulation was unrealistic. Rewritten to spawn a
  real subprocess with `python -S` (skips `site`/`.pth` processing entirely) and a `PYTHONPATH`
  containing only this package's own `src/`, so site-packages — `PySide6` included — is
  genuinely absent rather than merely patched around, matching the actual `--no-deps` install
  that first surfaced the bug.
- Full suite re-verified together after every change in this entry, not just at the end:
  `tests/` + `security_audit/` — **178 passed, 1 skipped** (163 + 15 new = 178; the 1 skip is the
  pre-existing, environment-dependent "Rust extension not built" skip in `test_rust_accel.py`,
  unrelated to this release).

### Project metadata

- Version: `0.0.5a0`.
- Verified environment for this entire entry: **Python `3.14.7`** (installed fresh via
  `uv python install`, not assumed to already be present — Ubuntu 24.04's system package manager
  only offers `3.12.x`), **`PySide6-Essentials`/`PySide6-Addons` `6.11.2`**, **`pyusb` `1.3.1`**
  (both confirmed as the actual current latest on PyPI at verification time, not just the
  versions asked for), with a real `libusb1` backend resolving successfully
  (`libusb-1.0-0` present). `QT_QPA_PLATFORM=offscreen`, no real display — the existing
  `conftest.py` already assumed exactly this kind of headless environment.
- Every file touched or added in this release was also successfully byte-compiled under Python
  `3.9.25` (this project's `requires-python` floor), installed fresh via `uv python install`
  rather than assumed — no accidental reliance on newer syntax.
- The Rust acceleration crate under `native/` is unmodified in this release and was not
  rebuilt or re-tested (no Rust toolchain available in the verification environment this time);
  `test_rust_accel.py`'s existing skip-when-unbuilt behavior is unaffected either way.
- `pyproject.toml`: `license = { text = "MIT" }` plus a `License :: OSI Approved :: MIT License`
  classifier replaced with the single SPDX-expression form (`license = "MIT"`, classifier
  dropped as redundant) and `build-system.requires` bumped to `setuptools>=77` to match —
  `python -m build` emitted explicit deprecation warnings for the old table form pointing at a
  2027-02-18 removal date, surfaced while building this release's own wheel/sdist rather than
  found by inspection.
- Built both `sdist` and `wheel` with `python -m build` (clean, no warnings, after the
  `pyproject.toml` fix above); both pass `twine check`. Installed the built wheel into a fresh
  venv (`uv pip install pyside6_webusb-0.0.5a0-py3-none-any.whl`, dependencies resolved from
  PyPI, not from this checkout) and confirmed `import pyside6_webusb`, `python -m
  pyside6_webusb`, and the installed `pyside6-webusb-doctor` console script all behave
  identically to the checkout under test. Separately installed the same wheel with `--no-deps`
  into another fresh venv to deliberately reproduce a `PySide6`-less install — this is the install
  that surfaced the first "Fixed" item above, and re-running it after the fix confirms
  `pyside6-webusb-doctor` now reports the missing dependency cleanly instead of crashing.

## [0.0.4b3]

An independent, external security audit against this codebase (two passes — the second at the
requester's explicit request for maximum strictness), reproduced end to end in a real
Python 3.14.4 / PySide6 6.11.2 environment before any fix landed, and re-verified the same way
after. See [`security_report/VULNERABILITY_REPORT.md`](security_report/VULNERABILITY_REPORT.md)
for the full writeup and [`security_audit/`](security_audit/) for the executable reproductions —
every one of them is designed to keep passing, unmodified, as long as the corresponding fix
stays in place. Final result: **83 audit tests, 83 passing** (up from 66/80 before this release);
the full existing `tests/` suite (161 tests) also still passes unmodified.

### Security

- **Alternate-setting class confusion let a page reach a protected interface class's endpoints
  without `claimInterface()` ever seeing that class (High).** `interface_class_for()` looked only
  at whichever alternate setting's descriptor came first for a given interface number, and
  `_endpoint_available_or_error()` searched a claimed interface's endpoints across *every*
  alternate setting rather than only the one actually selected. A composite device declaring
  alternate setting 0 of an interface as innocuous vendor-specific and alternate setting 1 of
  that same interface as HID could be claimed under alternate setting 0 (correctly allowed) and
  then have `bulkTransferIn()` — no `selectAlternateInterface()` call needed — read real data
  from the hidden HID alternate's endpoint. The same root cause reached the `class`- and
  `interface`-recipient branches of control-transfer validation, too. The same category of
  security boundary CVE-2018-6125 found Chrome itself missing. Every one of `claimInterface()`,
  `_endpoint_available_or_error()`, both affected control-transfer branches, and
  `selectAlternateInterface()` now agree on which alternate setting is actually selected for each
  claimed interface, and that tracked state is invalidated by `selectConfiguration()` and
  `resetDevice()` (a device may legitimately re-enumerate with different descriptors after a bus
  reset).
- **`requestDeviceChooser()` had no server-side check that it was called from a real user
  gesture, and no server-side validation of `filters`/`exclusionFilters` structure (Medium).**
  Both checks existed only in `polyfill.py`'s own JS — a page with a direct `QWebChannel`
  connection to the bridge (bypassing `polyfill.py` entirely) could pop the native chooser dialog
  at any time with zero user interaction, and a structurally invalid filter (e.g. `productId`
  without `vendorId`) widened the candidate list instead of matching nothing, the opposite of
  what the spec requires. `polyfill.py` now mints a short-lived, single-use token
  (`mintGestureToken()`) at the exact moment it confirms `navigator.userActivation.isActive`, and
  `requestDeviceChooser()` independently verifies both that token and every filter's structure
  before constructing the dialog. Documented limitation: PySide6/QtWebEngine has no public API
  for the Python side to independently observe a page's real DOM user-activation state, so this
  raises the bar substantially without being a perfect guarantee against a sufficiently
  determined scripted attacker that also mints its own token.
- **Device-supplied strings (manufacturer/product/serial/configuration/interface names) reached
  the chooser dialog and JSON descriptors with no sanitization at all (Medium).** These strings
  are entirely the connected device's own choice. A hostile device could embed control
  characters, Unicode bidirectional-override characters (the same trick used to disguise
  filenames — e.g. making `cod.exe` display as `exe.doc`), or HTML-like markup that Qt's default
  `QLabel` text format would render as rich text, visually spoofing the permission dialog itself
  — the same category of issue as CVE-2020-16033. All such strings now pass through
  `sanitize_device_string()` (strips control and bidi-override characters, caps length), and
  every `QLabel` in the chooser dialog is forced to `Qt.TextFormat.PlainText` regardless of
  content.
- **`closeDevice()` always returned `None` instead of a JSON string — on every call, not only
  invalid ones (Low).** Every code path fell off the end of the function with no explicit
  `return`. `JSON.parse(null)` throws on the JS side, so this broke error handling for legitimate
  callers too, not just the adversarial case the audit used to find it. While fixing this, a
  second, unrelated bug was found by inspection: its `@Slot` declaration didn't declare
  `result=str` at all (unlike every sibling method), meaning even a correct Python return value
  would never have been marshalled back to JS through a real `QWebChannel` connection — direct
  Python-call tests could never have caught this, since they bypass Qt's meta-object marshalling
  entirely.
- **Hotplug `connect`/`disconnect` events reached cross-origin frames that were never granted the
  device involved (Low/Informational).** `deviceConnected`/`deviceDisconnected` are plain Qt
  signals with no per-frame delivery mechanism, and whether one fires is decided from the
  top-level page's grants alone — so an embedded cross-origin iframe that had never itself been
  granted a device could still observe its vendorId/productId on connect/disconnect. Qt Signals
  can't be redesigned to deliver per-frame without a larger architecture change, but the
  *observable* behavior didn't need one: `polyfill.py` now re-verifies, via a new
  `isGrantedToThisFrame()` check scoped to its own frame's own origin, before ever dispatching a
  JS event or calling `onconnect`/`ondisconnect`.
- **`openDevice()` had no limit on simultaneous open handles per origin (Medium — easy to
  trigger despite modest per-call cost).** An ordinary page holding one legitimate grant could
  grow `WebUSBBridge`'s internal handle table without bound just by calling `device.open()` in a
  loop without ever closing them — no `QWebChannel` bypass needed. This consumes memory in the
  *host application's own process*, not the tab's renderer, so it isn't bounded by normal
  per-tab memory limits. Each origin is now capped at a generous number of concurrently open
  handles; opening past the cap releases that origin's oldest handle first rather than failing
  the new `open()` call.

## [0.0.4b2]

A cross-checked-against-real-Chrome-source pass, plus a real security fix, an F12/DevTools
debug surface, and a deliberate policy change around this implementation's own identity: rather
than being a drop-in Chrome clone, `pyside6-webusb` is explicitly a WebUSB-*compatible*
implementation that keeps some of its own, more permissive extensions where they don't
compromise safety. Every behavioral claim below was checked against Blink's actual source
(`third_party/blink/renderer/modules/webusb/usb_device.cc`, fetched from the `chromium/chromium`
GitHub mirror), not the abstract spec text alone or memory.

### Security

- **`listKnownDevices`/`forgetKnownDevice`/`forgetAllKnownDevices` were reachable from any web
  page, not just the host application.** These three manage data across *all* origins (the full
  known-device list; `forgetAllKnownDevices` is destructive) and were explicitly meant for a
  host app's own trusted settings UI — the exact same category of operation that
  `list_granted_origins`/`revoke_origin_grant`/`revoke_all_for_origin` in the same file already
  document as "deliberately not `@Slot`, since exposing this to the currently-displayed web page
  would be wrong." These three just never got the same treatment, seemingly predating that
  principle being established. Since `install()` injects the polyfill into `MainWorld` — the
  same JS execution context the page's own scripts run in, which is *required* for
  `navigator.usb` to be visible to the page at all — anything registered as a `@Slot` on the
  bridge object is reachable by any web page opening its own `QWebChannel` connection directly,
  regardless of whether `polyfill.py`'s own JS ever calls it (confirmed `polyfill.py` never did,
  for any of these three). Removed `@Slot` from all three; they're now plain Python methods,
  callable only by the host application's own code, matching the established pattern next to
  them. `tests/test_bridge.py::test_requestDeviceChooser_is_registered_as_qt_slot` now asserts
  all six management-only methods are absent from the Qt meta-object's slot list — confirmed
  this actually catches the regression by re-adding `@Slot` and watching the assertion fail with
  the exact expected message before restoring the fix.

### Fixed

- **`errors.py`'s own error prefixes (`IndexSizeError:`, `InvalidAccessError:`, `NotFoundError:`,
  and the new `DataError:`) weren't recognized by the JS-side dispatcher**, only
  `SecurityError:`/`InvalidStateError:` were. `bulkTransferIn`/`Out` have no client-side
  pre-check at all before calling the bridge, so this was a live, reachable bug: an
  out-of-range endpoint number (a check that's existed since early versions) produced a
  `DOMException` with `.name === 'NetworkError'` and the literal text `"IndexSizeError: ..."`
  still stuck in `.message`, instead of `.name === 'IndexSizeError'` with a clean message.
  Confirmed by deliberately reverting the fix and watching a new regression test fail with
  exactly that symptom, then confirming it passes with the fix restored. `KNOWN_ERROR_PREFIXES`
  now lists every prefix `errors.py` can actually produce, rather than requiring every call site
  to separately remember to pass a matching `defaultErrorName` (the approach that led to this
  gap in the first place).
- **`isochronousTransferOut` never checked that `data`'s length matched the sum of
  `packetLengths`.** Real Chrome rejects a mismatch with `DataError: "The data buffer size must
  match the total packet length."` (`kBufferSizeMismatch`, confirmed in Blink source). This
  implementation had no equivalent check at all — a page could send `data` shorter or longer
  than its declared `packetLengths` and the mismatched buffer would be passed straight to
  `backend.iso_write()` as-is. Added the same check, with Chrome's exact message text.
- Fixed a real structural bug in `tests/test_bridge.py` uncovered while updating these tests:
  `test_bulk_and_control_transfer_reject_absurdly_large_length`'s `def` line had gone missing
  (most likely lost in an earlier bulk find-and-replace pass in this project's history), leaving
  its entire body as unreachable-but-syntactically-valid code silently appended to the *previous*
  test function. It had never run as its own test — every one of its assertions had been
  executing (and passing) as an unlabeled tail end of
  `test_bulk_transfer_reentrant_call_on_busy_handle_is_rejected` instead, which is why this
  didn't show up as a missing test in any prior test count. Restored as its own function.

### Changed — Chrome-compatibility alignment

- **Both transfer size limits now match Blink's actual `kUsbTransferLengthLimit` (32 MiB)**
  as a *reference* value, not this project's own previous, ungrounded guesses (bulk was 64 MiB,
  isochronous was 16 MiB as of `0.0.4a0`/`0.0.4b0` — neither matched what real Chrome actually
  enforces). Also switched the DOMException type real Chrome uses for this specific rejection
  from `IndexSizeError` (this project's previous guess) to `DataError` (Blink's actual choice,
  confirmed from source) — `IndexSizeError` is kept for the genuinely-different "endpoint number
  out of range" case, which Blink's own `EnsureEndpointAvailable` does use `IndexSizeError` for.
- **This 32 MiB figure is no longer a hard rejection threshold in this implementation** — see
  the policy change below.

### Changed — deliberate policy: WebUSB-compatible, not a Chrome clone

This is the most substantive change in this release, so it gets its own section rather than
being folded into "Fixed" or "Changed" above.

Real Chrome's 32 MiB transfer limit (`kUsbTransferLengthLimit`) is Chrome's own operational
choice, not a WebUSB spec requirement — nothing in the spec text mandates it. This project is
built as a WebUSB-*compatible* implementation with room for its own extensions, not a
byte-for-byte Chrome clone, so as of this release: **a `transferIn`/`transferOut`/
`isochronousTransferIn`/`isochronousTransferOut` call exceeding 32 MiB is no longer rejected.**
It proceeds normally, up to a much larger, *unrelated* hard ceiling
(`HOST_SAFETY_MAX_TRANSFER_LENGTH`, 512 MiB) that exists purely so this implementation's own
host process can't be forced into an unbounded memory allocation by a pathological request —
that ceiling has nothing to do with Chrome-matching and is enforced regardless.

This is not silent, and it does not pretend to be Chrome: the response carries a `warning`
field (`chrome_transfer_limit_warning()`, `hardening.py`) that the polyfill forwards to
`console.warn()` — visible in DevTools (F12) on the exact transfer that exceeded the limit. The
message quotes Blink's real rejection text (`"The data buffer exceeded supported maximum size of
33554432 bytes"`) and then explicitly states that this is pyside6-webusb, not Chrome, and that
it does not enforce that limit — the point is to be transparent about the divergence, not to
mimic Chrome's identity or hide that anything unusual happened. `window.__pysideWebUSB.
explainTransferLimits()` (new, see below) gives the same explanation on demand. Verified: a
request at exactly 32 MiB carries no warning; one byte over does; both succeed either way
(`test_bulk_transfer_over_chrome_limit_warns_but_succeeds`, covering both `bulkTransferIn` and
`isochronousTransferIn`).

### Added

- **`window.__pysideWebUSB`**, an F12/DevTools Console debug namespace, injected alongside
  `navigator.usb`. Deliberately scoped to information that either (a) doesn't vary by origin at
  all (bridge version, Rust-acceleration status, transfer size limits) or (b) is exactly what
  the calling origin already sees via `navigator.usb.getDevices()`, just reformatted for
  `console.table()` — nothing here discloses anything a page couldn't already learn, and in
  particular nothing here repeats the mistake fixed in Security above.
  - `listGrantedDevices()` — the calling origin's already-granted devices, `console.table()`-
    formatted. Verified to return exactly as many rows as `navigator.usb.getDevices()` — no
    additional disclosure.
  - `bridgeInfo()` — version, `rustAccelerated`, and the transfer-limit values, sourced from a
    new `isAvailable()` response field (`bridgeVersion`/`rustAccelerated`/`transferLimits`) that
    didn't exist before this release; this information wasn't accessible from JS at all
    previously.
  - `explainTransferLimits()` — logs the same reasoning described in the policy section above,
    on demand rather than only reactively when a specific transfer happens to exceed it.
  - A single source of truth for the version string was needed for `bridgeInfo()` to read it
    without a circular import (`bridge.py` importing from `__init__.py`, which itself imports
    `bridge.py`) — added `_version.py`, now what both `__init__.py` and `bridge.py` read
    `__version__` from.
- Investigated (but did not implement) using Rust to work around this implementation's existing
  isochronous limitation (uniform packet lengths only — `_validate_packet_lengths` in
  `bridge.py`, unchanged since `0.0.2b0`). `libusb`'s C API does support per-packet lengths via
  its async submission API (`libusb_fill_iso_transfer`), so a Rust binding (`rusb`/
  `libusb1-sys`) could in principle expose it. Didn't proceed, for reasons recorded in
  `_validate_packet_lengths`'s own docstring rather than silently dropped: libusb's isochronous
  support is async-only (no synchronous "wait for completion" variant to wrap), and the real
  blocker — `pyusb` already holds this device open via its own `libusb` context/handle, and a
  second, independent handle from Rust can't safely coexist claiming the same interface on most
  platforms. Working around that would mean extracting `pyusb`'s internal raw
  `libusb_device_handle*` (an undocumented implementation detail liable to break on any `pyusb`
  update) and sharing it across the FFI boundary as a raw, Rust-ownership-untracked pointer —
  with no real USB hardware available anywhere to validate such code, the risk profile (a bug
  here isn't a logic error, it's a potential crash or, worse, sending a real device incorrect
  padded data because the surrounding software couldn't tell that "make it work" this way would
  give the device different bytes than intended) outweighed shipping it unverified. Left as a
  documented, deliberately-not-attempted path rather than a rushed half-solution.
- `tests/test_bridge.py::test_sustained_large_transfers_do_not_leak_state_or_corrupt_data`: 30
  consecutive ~300 KB `transferIn` calls (each exceeding `BULK_TRANSFER_CHUNK_SIZE`, so each
  exercises the `0.0.4b0` chunking path), 30 consecutive `transferOut` calls, then 50 alternating
  IN/OUT round trips resembling an ADB request/response pattern — each iteration uses distinct
  data (not the same buffer reused) so corruption on any single iteration, not just a systematic
  one, would be caught, and `_busy_handles`/`_open_devices` size is checked after every single
  iteration, not just at the end, to catch a leak that only shows up gradually.

### Project metadata

- Version bumped to `0.0.4b2`.
- Confirmed via the `chromium/chromium` GitHub mirror that `raw.githubusercontent.com` serves
  real, current Blink source (`usb_device.cc`, `usb.cc`) — used throughout this entry's fixes.
- **Fixed `pyproject.toml`'s `Homepage`/`Issues` URLs**, which pointed at
  `steck0714/Mock-webusb` — verified via `git ls-remote` that this and
  `steck0714/Pyside6-webusb` are two genuinely different repositories (different `HEAD` commits),
  not a rename/case variation of the same one. Fetching `Mock-webusb`'s actual `README.ja.md`
  confirmed it's the umbrella project's landing repo (multi-language READMEs, no `pyproject.toml`
  at all) linking out to this package's real repo (`Pyside6-webusb`) and its Firefox counterpart
  (`fox-webusb`) — not this package's own code repository. Now points `Homepage`/`Issues` at
  `Pyside6-webusb` (confirmed live, and already tracking this project — its `pyproject.toml`
  showed `version = "0.0.4b1"` at the time of this check) and added a separate
  `"Mock-APIs (parent project)"` URL entry for `Mock-webusb`. Mock-webusb's real README text is
  also what the "Why this exists" section's Chrome-compatible-not-identical framing is now quoted
  from directly, rather than paraphrased from a secondhand description.

## [0.0.4b1]

A cross-language quality/audit pass rather than new user-facing features: ran each language's
own static-analysis tooling over the whole codebase (`cargo clippy` for Rust, `ruff` for Python,
`eslint` for the embedded JS polyfill, `tsc` with flags stricter than `--strict` for the
TypeScript defs), fixed what was actually worth fixing, and used the Rust extension to further
optimize the large-transfer data path this whole `0.0.4a0`→`0.0.4b1` line of work has been
about. Every improvement below was verified, not just asserted — see the specific numbers.

### Fixed

- **A real correctness gap `cargo clippy --pedantic` caught**: `adb_pack_header()`'s
  `data.len() as u32` cast silently wraps for a payload over 4 GiB (`usize` on this platform
  can exceed `u32::MAX`; a plain `as` cast doesn't check). Unreachable through this project's own
  call sites today (`bridge.py` already caps requests at 64 MiB via `BULK_TRANSFER_MAX_LENGTH`),
  but the crate's public functions are usable standalone, and a silently-wrong `data_length`
  field is a worse failure mode than an explicit one. Switched to
  `u32::try_from(data.len()).unwrap_or(u32::MAX)` — saturates instead of wrapping to a small,
  misleadingly-plausible-looking wrong number. (The real ADB protocol's own `data_length` field
  is a `u32`, so a >4 GiB single message isn't representable in the wire format at all regardless
  of this implementation — this fix makes that limitation explicit instead of silently
  corrupting the field.) Added `#[must_use]` to every `logic`-module function that returns a
  value with no side effects, per `clippy::pedantic`'s suggestion, so misuse (computing a result
  and silently discarding it) is a compiler warning rather than a silent no-op.
- **Silent exception-swallowing in device enumeration** (`ruff`'s `S112` check, `hardening.py`):
  `build_configurations_tree()` and `_device_interface_class_tuples()` had bare
  `except Exception: continue` at the endpoint/interface/configuration level while walking a
  device's descriptors, with zero indication of *why* something was skipped. A device with one
  malformed descriptor at any level would just silently lose that endpoint/interface/configuration
  from what gets exposed to the page — "my device is plugged in but half its endpoints are
  missing and there's no way to tell why" is exactly the kind of hard-to-debug field issue this
  project's own established convention (`print(f"[pyside6-webusb] ...: 例外を無視: {e}")`,
  used throughout `bridge.py`) exists to avoid. Brought these three call sites in line with that
  convention — behavior is unchanged (still skips and continues exactly as before), only
  visibility is added.

### Added

- **Rust-accelerated transfer-response JSON construction**
  (`format_transfer_in_success_json`), used by `bulkTransferIn`/`controlTransferIn`'s success
  path. The old flow was three separate Python-level allocations for a large payload: join the
  read chunks into `bytes`, base64-encode into a new string, `json.dumps()` wrap into another new
  string. The new Rust function does the base64 encoding and the (narrowly-scoped, only for this
  known-safe fixed shape — see its doc comment for exactly why this isn't a general-purpose JSON
  builder) response-string construction in one pass with a pre-sized buffer. **Measured, not
  assumed**: for a 1 MB payload, `timeit`-measured at 200 iterations, the Rust path is
  **~2.9x faster** than the old approach (5.46ms → 1.85ms); the pure-Python fallback path (see
  below) measured statistically indistinguishable from the old approach once benchmark-harness
  overhead is controlled for (5.50ms → 5.54ms) — the speedup is specifically a Rust-availability
  benefit, not something that snuck in "for free" on the fallback path too. `bridge.py`'s
  `_format_transfer_success_json()` wrapper follows the same `HAVE_RUST_ACCEL`-gated fallback
  pattern as `_b64encode`/`_b64decode`, and — verified directly, not assumed — **produces
  byte-identical output on both paths** (`tests/test_rust_accel.py::
  test_bridge_format_transfer_success_json_wrapper_matches_rust_and_python_paths`), so which
  path is active is invisible on the wire.
- **All JSON responses are now compact** (`_json_dumps()`, `separators=(",", ":")`, applied
  to all 95 `json.dumps()` call sites in `bridge.py`, not just the large-transfer ones) instead
  of Python's default `, `/`: ` separators. `JSON.parse()` on the receiving end is whitespace-
  insensitive either way — this is a pure wire-size reduction (measured **8.2%** smaller for a
  small representative response; the *proportional* saving shrinks for large payloads since the
  savings are a fixed few bytes per message while the base64 payload dominates, but it's free
  and it applies to every response, not just transfers) — and it's also what made the Rust
  function's hand-built JSON and Python's `json.dumps()` output byte-identical in the first
  place (mismatched separators would have made the "identical on both paths" property above
  false).
- Cross-language static analysis now actually run, with results recorded here rather than
  assumed clean: `cargo clippy --all-targets -- -W clippy::all -W clippy::pedantic` (Rust,
  findings above + doc-comment backtick nits left as-is), `ruff check --select ALL` with a
  curated ignore list (Python; findings above + several accepted style preferences), `eslint`
  with a hand-written flat config against the *extracted* polyfill JS (not `polyfill.py`
  directly, since most of that file is the JS source as a Python string constant — a generic
  Python linter run on it would be almost pure noise): zero real errors, 8 warnings, all either
  the deliberate `x != null` idiom (checks "not null and not undefined" in one comparison — using
  `!==` here would need two separate checks, `!=` is the *more* correct choice, not a mistake)
  or intentionally-unused `catch (e)` bindings in isolated event-dispatch error handling. `tsc`
  with `--strict` plus `--noUncheckedIndexedAccess --exactOptionalPropertyTypes
  --noImplicitOverride --noPropertyAccessFromIndexSignature --noImplicitReturns
  --noFallthroughCasesInSwitch --forceConsistentCasingInFileNames` on top (stricter than any
  flag combination checked before this release): zero new errors on either `types/sample-usage.ts`
  or `types/negative-check.ts`.
- 5 new Rust unit tests (`format_transfer_in_success_json_*`, `cargo test`: 13 total, up from
  10) and 2 new Python tests (`test_rust_accel.py`: 10 total, up from 8) covering the new
  function and its parity with the pure-Python fallback path.

### Project metadata

- Version bumped to `0.0.4b1` (already the PEP 440-normalized form — no `a`/`b` suffix number
  to append this time, unlike the `0.0.4a`→`0.0.4a0` and `0.0.4b`→`0.0.4b0` normalizations in
  the previous two releases).
- `rust-clippy` installed via `apt` (Ubuntu 24.04's own package, alongside the `rustc`/`cargo`
  already in place from `0.0.4b0` — no `rustup` component system available in this environment,
  same network-allowlist constraint noted in the `0.0.4b0` entry).

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
