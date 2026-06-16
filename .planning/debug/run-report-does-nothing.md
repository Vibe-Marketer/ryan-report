---
slug: run-report-does-nothing
status: awaiting_human_verify
trigger: "Customer (Eric Villa, CATOM-WKS01) submitted a support ticket: clicking Run Report does nothing. Suspected related to long-running auto-update / receive-updates issues. Check tickets, see what was received and why it failed."
created: 2026-06-16
updated: 2026-06-16
---

## Resolution

root_cause: |
  ONE shared root across both failures: the frozen PyInstaller Windows build
  trusted the host OS for two things it must self-supply.

  Failure A (Run does nothing): pywebview renders the HTML UI via the WebView2
  (EdgeChromium) backend. webview.start() was called with no gui=, so when the
  customer's machine lost a usable WebView2 runtime (right when they switched
  from the hand-copied portable build on OneDrive\Desktop to the NSIS per-user
  install in %LOCALAPPDATA%\Programs\Catom on 2026-06-12), pywebview silently
  fell back to MSHTML (IE11/Trident). The UI's button handlers (runPipeline,
  init) are ES2017 `async function`s; MSHTML cannot parse async/await, so the
  ENTIRE <script> failed, window.pywebview.api was never wired, and every
  button — including Run Report — was dead. The page still rendered as static
  HTML and the Python-side launch update check still logged, which is exactly
  the observed "click Run, nothing happens, no pipeline log lines, but [UPDATE]
  lines present" signature.

  Failure B (URLError on update check): updater.py (and the distribution-PDF
  fetch + Claude troubleshoot call) used urllib with the DEFAULT ssl context.
  certifi was never bundled and PyInstaller collected no CA certs, so the frozen
  build had no CA trust store -> TLS verification failed -> SSLCertVerificationError
  surfaced as urllib URLError. The feed verified fine from the dev machine
  because it has certifi/system CAs.

  v2.0.0 was a version-string-only release (git diff v1.3.13..v2.0.0 touches
  ONLY __version__.py) and fixes NEITHER failure.

fix: |
  Make the frozen build self-sufficient + fail loud instead of silent.
  B: Added a certifi-backed ssl_context() + _urlopen() helper in updater.py and
     routed every HTTPS call (update check, installer download, distribution PDF,
     Claude API) through it. Added certifi to requirements.txt; build.py now
     --hidden-import certifi and --collect-data certifi so certifi.where()
     resolves inside the bundle.
  A: main.py now pins gui="edgechromium" on Windows so pywebview can NEVER
     silently degrade to MSHTML, plus a WebView2 runtime preflight
     (_webview2_runtime_present via registry) that, if the runtime is missing,
     writes an actionable [FATAL] log line and shows a native MessageBox telling
     the user/IT to install the Edge WebView2 Evergreen Runtime — instead of
     opening a dead-button window.
  Bumped __version__ to 2.0.1 (real release so the fix can ship; 2.0.0 was a
  no-op).

verification: |
  - py_compile clean on updater.py, main.py, build.py, __version__.py.
  - New ssl_context() returns a CERT_REQUIRED context backed by certifi;
    _urlopen() verified the LIVE feed (HTTP 200, version 2.0.0) on this machine —
    the exact TLS path that was throwing URLError now succeeds.
  - Cross-platform safety confirmed: _webview2_runtime_present() returns True
    off-Windows, _show_native_error is a no-op off-Windows, gui= only set on
    Windows. Mac/dev runs unaffected.
  - REMAINING (needs the human / a real Windows build): rebuild the frozen
    Windows app, install via NSIS on a WebView2-equipped Win11 box, confirm
    Run Report logs [1/2] Downloading... again AND the update check no longer
    URLErrors. If Catom Trucking does corporate TLS interception (not just a
    missing CA store), certifi alone may be insufficient — see blind_spots.

files_changed:
  - app/updater.py: added ssl_context() + _urlopen() (certifi-backed); routed both urlopen calls through it
  - app/main.py: routed distribution-PDF + Claude-API urlopen through updater._urlopen; added WebView2 preflight (_webview2_runtime_present, _show_native_error) and pinned gui='edgechromium' on Windows
  - app/build.py: --hidden-import certifi + --collect-data certifi
  - app/requirements.txt: added certifi>=2024.2.2
  - app/__version__.py: 2.0.0 -> 2.0.1

# Debug Session: Run Report does nothing (Catom desktop app)

## Symptoms

- **Expected:** Clicking "Run Report" in Catom kicks off the Axon download + Ryan-report build pipeline (first log line `[1/2] Downloading reports from Axon...`).
- **Actual:** "When I go to click Run Report, it is not doing anything." On the complaint day the app logs ZERO pipeline activity.
- **Error messages:** `[UPDATE] check failed (running 1.3.13): URLError` repeated on every launch since 2026-06-12.
- **Timeline:** Pipeline worked fine 2026-05-07 / 05-18 / 05-20 (on 1.3.13-era builds). Update-check URLErrors begin 2026-06-12. Ticket filed 2026-06-16.
- **Reproduction:** Customer launches Catom v1.3.13 on Windows 11, clicks Run Report — nothing happens.

## Evidence (from R2 ticket bundle)

Ticket: `feedback/2026-06-16_145434_CATOM-WKS01_f90efd.zip` (pulled via `tools/catom-tickets.py get latest`, unzipped to `~/Downloads/catom-tickets/2026-06-16_145434_CATOM-WKS01_f90efd/`).

- timestamp: 2026-06-16T14:54:34Z | machine: CATOM-WKS01 (EricVilla) | platform: Windows-11-10.0.26200 | **app version: 1.3.13** (latest release is **2.0.0**)
- `catom.log.tail` on 2026-06-16: every launch = `[UPDATE] check failed (running 1.3.13): URLError` (x2–3) then `=== Catom exiting cleanly ===`. **No `[1/2] Downloading reports...` line anywhere on the complaint day** — the Run handler never produced output.
- Contrast: working runs (05-07, 05-18, 05-20) all logged `[1/2] Downloading reports from Axon...` immediately on Run.
- Update feed `https://updates.aisimple.co/catom/latest.json` is **LIVE and healthy from the dev machine** (HTTP 200, serves `{"version":"2.0.0", url: Catom-Setup-v2.0.0.exe}`, last-modified 2026-06-11). DNS resolves (Cloudflare 172.64.80.1). → URLError is **client-side**, not a dead endpoint.

## Two intertwined failures

### Failure A — Run Report does nothing (PRIMARY, customer's complaint)
Clicking Run writes no log line at all. Hypotheses:
1. UI/JS regression in v1.3.13 `app/ui/index.html` — Run click handler dead (precedent: commit `e718359 fix: remove duplicate TOTAL_STEPS const that broke entire UI`).
2. Launch-time auto-update check (added v1.3.5) throws URLError and its unhandled exception blocks/breaks the UI thread so Run becomes inert.
3. Silent exception in the Run handler before the first log write.

### Failure B — Can't receive updates (delivery channel; why the fix can't reach them)
`updater.py` request throws URLError on the customer's machine though the feed is live. Hypotheses:
1. Frozen PyInstaller build missing CA bundle (certifi not bundled) → urllib SSL verify fails, surfaced as URLError. Most likely.
2. Corporate proxy/firewall on Catom Trucking network blocking the request.
3. v1.3.13 `updater.py` request code defect (wrong scheme/host/timeout/headers).

## Current Focus

status: fixing — root cause confirmed for BOTH failures.

reasoning_checkpoint:
  hypothesis: "Both failures share ONE root: the frozen Windows build trusts the host OS for two things it must self-supply. (A) The Run button is inert because pywebview's WebView2 (EdgeChromium) backend is unavailable on the customer's now-NSIS-installed machine, so pywebview silently falls back to MSHTML/IE11, which cannot parse the ES2017 `async function` script block — ZERO JS runs, every onclick is dead, but the Python-side launch update check still logs. (B) urllib in the PyInstaller bundle has no CA trust store (certifi never bundled), so TLS verification of https://updates.aisimple.co fails -> URLError. v2.0.0 fixes NEITHER (it is a version-string-only release)."
  confirming_evidence:
    - "git diff v1.3.13..HEAD shows ONLY app/__version__.py changed (1.3.13 -> 2.0.0). main.py, updater.py, index.html, build.py are BYTE-IDENTICAL. v2.0.0 cannot fix anything behavioral."
    - "Log argv proves an install-location change exactly at the breakpoint: working runs (05-07..05-20) ran from 'OneDrive\\Desktop\\Catom\\Catom.exe' (hand-copied portable); broken runs (06-12+) run from 'AppData\\Local\\Programs\\Catom\\Catom.exe' = the NSIS InstallDir (Catom.nsi line 52). The app was reinstalled via NSIS right before it broke."
    - "On broken days the log shows the Python-side '[UPDATE] check failed: URLError' (fired from main.py _post_load_hooks->check_async, no JS needed) but ZERO pipeline lines. _run()'s FIRST action logs '[1/2] Downloading...' (or a validation [ERROR]); none appear => run_pipeline was never invoked from JS => the window.pywebview.api bridge / JS never executed."
    - "index.html uses async/await throughout (runPipeline, init are `async function`). HANDOFF-WINDOWS-BUILD.md line 150 states pywebview falls back to MSHTML when WebView2 runtime is absent. MSHTML=IE11 Trident has no async/await => the entire <script> fails to parse => all handlers dead while static HTML still renders."
    - "updater.py check_for_update() uses urllib.request.urlopen with the default SSL context and no cafile/certifi. 'certifi' appears nowhere in v1.3.13 except an unrelated code-signing note. build.py bundles webview/playwright/openpyxl/pdfplumber as hidden imports but never collects certifi or CA certs. Frozen Python on Windows has no CA store => SSLCertVerificationError surfaced as urllib URLError. Feed works from dev because the dev box has certifi/system CAs."
  falsification_test: "If on a machine WITH WebView2 runtime present the Run button worked on the identical NSIS build, that would confirm the WebView2/MSHTML mechanism for A. If pinning urllib to certifi.where() made the update check succeed on the frozen build behind the same network, that confirms B is CA-store (not proxy). Conversely, if Run still failed with WebView2 present and JS executing, A is NOT the backend fallback."
  fix_rationale: "Address the shared root: make the frozen build self-sufficient. (B) Bundle certifi and point urllib at it (ssl context with certifi CA bundle) so TLS verifies regardless of host CA store — directly removes the URLError. (A) Force pywebview to the EdgeChromium backend (gui='edgechromium') and fail loudly with an actionable message if WebView2 runtime is missing, AND remove the hard dependency on ES2017-only behavior so a fallback engine still surfaces an error instead of silently dying. Ship as a real new release so the customer can receive the fix once B unblocks the channel."
  blind_spots: "Cannot run the Windows frozen build here to observe WebView2 fallback live — inference is from log argv + HANDOFF doc + code, not a reproduced MSHTML session. A corporate proxy doing TLS interception (not just a missing CA store) would ALSO cause URLError; certifi alone may be necessary-but-insufficient if Catom Trucking inspects TLS. The exact reason WebView2 became unavailable on 06-12 (IT policy / Edge update / per-user vs portable runtime context) is not directly observed."

## Evidence Log

- 2026-06-16: Pulled ticket bundle from R2. Confirmed customer on 1.3.13, Run produces no log output, update check URLErrors since 06-12, feed live from dev machine.
- 2026-06-16: git diff v1.3.13..HEAD touches ONLY app/__version__.py. main.py/updater.py/index.html/build.py byte-identical between v1.3.13 and v2.0.0 (verified per-file with `git diff --quiet`). => v2.0.0 is a no-op release; pushing it fixes neither A nor B.
- 2026-06-16: Log argv reveals install-path change at the failure boundary. Working: `OneDrive\Desktop\Catom\Catom.exe` (portable). Broken (06-12+): `AppData\Local\Programs\Catom\Catom.exe` = NSIS `InstallDir "$LOCALAPPDATA\Programs\Catom"` (Catom.nsi:52). 06-11 transitional run from `AppData\Local\Catom` (older build, no update check). Customer reinstalled via NSIS-built Catom-Setup right before the break.
- 2026-06-16: Broken-day logs show only `[UPDATE] check failed: URLError` (Python-side, main.py:_post_load_hooks->updater.check_async) then `=== Catom exiting cleanly ===`. No `[1/2] Downloading...`, no validation `[ERROR]`. _run() (main.py:783) logs `[1/2]` as its first pipeline action => run_pipeline never fired from JS => the JS bridge / handler never ran.
- 2026-06-16: index.html Run button = inline `onclick="runPipeline('all')"` (line 451). runPipeline + init are `async function`s calling `window.pywebview.api.*`. webview.start() in main.py:1408 passes NO `gui=` => pywebview auto-selects backend. HANDOFF-WINDOWS-BUILD.md:150 documents the MSHTML fallback when WebView2 runtime is absent. MSHTML=IE11 cannot parse async/await => whole script dies, static HTML renders, all buttons inert. Matches "click does nothing, no log."
- 2026-06-16: updater.py check_for_update() (and download_installer, _ensure_distribution_pdf, troubleshoot) build urllib requests with the DEFAULT ssl context, no certifi/cafile. `certifi` absent from entire v1.3.13 source (except unrelated code-signing HANDOFF note). build.py hidden-imports list has no certifi and no CA-cert collection. Frozen Windows Python => empty CA store => TLS verify fails => urllib URLError. Dev machine has certifi/system CAs, so the feed works there.

## Eliminated

- Update endpoint down — ELIMINATED: feed returns HTTP 200 with v2.0.0 from dev machine; DNS resolves; client-side error.
- "v2.0.0 already fixes A and/or B" — ELIMINATED: v1.3.13..HEAD diff is the version string only; all behavioral files byte-identical. Shipping v2.0.0 as-is would not help the customer.
- Dead JS click handler as a code regression in index.html (e718359-style) — ELIMINATED for the customer's failure: the handler wiring (onclick=runPipeline) is intact and unchanged from the builds that worked. The handler is dead at RUNTIME due to the backend (MSHTML can't run the async script), not due to a source regression.
- Launch-time update check blocking/breaking the UI thread — ELIMINATED: the update check runs on a daemon thread via updater.check_async (non-blocking) and its URLError is caught; it cannot make the Run handler inert. It is a symptom of the SAME root (no CA store), not the cause of A.
