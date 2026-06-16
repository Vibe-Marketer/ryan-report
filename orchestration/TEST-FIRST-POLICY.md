# Catom Test-First Policy

**Standing rule: every Catom fix is built and tested on `naegele-pc` (Andrew's Windows PC) BEFORE a release is cut or the R2 update feed is restamped.**

## Why this rule exists

The bug class that broke the customer (ticket 2026-06-16, "Run Report does nothing")
only manifests on the **frozen Windows build, freshly installed via NSIS, on a real
Win11 box**:

- `webview.start()` with no pinned backend → pywebview silently falls back to MSHTML
  (IE11) when WebView2 is absent → the UI's modern JS dies → every button goes inert.
- `urllib` with no bundled CA store (certifi) → TLS verify fails → `URLError` → the
  in-app updater can never reach the feed.

**Dev/Mac self-checks pass while the Windows build is broken.** `py_compile`, linting,
and a `curl` against the live feed from the Mac all succeed because the Mac has a
system CA store and never runs the frozen MSHTML path. They are necessary but **not
sufficient**. The only real proof is a frozen-build install on Windows.

## Procedure (every fix)

1. Apply the fix; self-check on dev (`py_compile`, lint).
2. Build the Windows installer **without releasing**:
   - CI: `gh workflow run "Build Desktop App"` → download the `Catom-Setup` artifact
     (no GitHub release, no R2 restamp — customers are untouched), **or**
   - build on `naegele-pc` directly (`python app/build.py` + NSIS).
3. On `naegele-pc`: install the NSIS build, click **Run Report** →
   - confirm `[1/2] Downloading reports from Axon...` logs (Run handler alive), and
   - confirm the launch update check no longer logs `URLError`.
4. **Only after PASS:** cut a GitHub release tag → CI restamps R2 `latest.json` →
   customers auto-receive.

## Never

- Never restamp R2 `latest.json` from an untested build.
- Never treat a green dev/Mac check as release-ready for Windows clients.

## Customer recovery note

A customer already stuck on a broken build (e.g. 1.3.13 with the `URLError` updater)
**cannot auto-update** — their broken updater is the thing that's broken. They need a
**one-time manual install** of the fixed version (send the direct
`Catom-Setup-vX.Y.Z.exe` link). Auto-update only works from the fixed version forward.
