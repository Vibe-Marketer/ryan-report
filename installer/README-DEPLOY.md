# Catom Deploy — Status & Cheat Sheet

## What's done (no action needed)

| Item | Status | Detail |
|---|---|---|
| R2 bucket | ✅ Created | `catom-updates` in account `e9319ad5ca87e4768e7a79f1339ec8c8` |
| Custom domain | ✅ Connected | `updates.aisimple.co` → `catom-updates` bucket (Cloudflare proxied, HTTPS) |
| GitHub Actions secrets | ✅ Set | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET` all pushed to `Vibe-Marketer/ryan-report` |
| Repo files | ✅ Committed-ready | `installer/Catom.nsi`, `app/__version__.py`, `app/updater.py`, `app/main.py` wiring, `index.html` banner, `.github/workflows/build.yml` |

R2 creds are shared with the callvault-assets bucket (account-scoped). If you ever want bucket-scoped isolation, generate a fresh token via Cloudflare dashboard → R2 → Manage R2 API Tokens.

## Verify the channel is live

```bash
curl -sI https://updates.aisimple.co/catom/latest.json
# Expected: HTTP/2 404 (bucket is empty until first release — that's correct)
```

When you publish your first GitHub Release, this URL will start returning HTTP 200 with the version JSON.

## How to ship a release

1. Bump `app/__version__.py` (e.g. `"1.0.0"` → `"1.0.1"`).
2. Commit.
3. Tag and push:
   ```bash
   git tag v1.0.1
   git push origin main && git push origin v1.0.1
   ```
4. On GitHub → Releases → Draft a new release → choose tag `v1.0.1` → write release notes (these become the banner text Eric sees) → Publish.
5. Wait ~10 min. CI builds the NSIS installer, attaches `Catom-Setup-v1.0.1.exe` to the GitHub Release, AND uploads it + a fresh `latest.json` to R2.
6. Eric's running Catom app polls `updates.aisimple.co` on next launch, sees the new version, banner appears.

## First-ever install for Eric

Download `Catom-Setup-v1.0.0.exe` from the GitHub Release assets (or grab it from R2). Drop it in a Drive folder, share with Eric. He double-clicks → setup wizard → installed. Last manual install he'll ever do.

## How auto-update flows at runtime

1. Catom launches → `app/updater.py` GETs `https://updates.aisimple.co/catom/latest.json` (~1s, async, fails silently if offline).
2. If `version` > `__version__`, the green banner appears in the UI.
3. User clicks **Update Now** → app downloads `Catom-Setup-vX.Y.Z.exe` to `%TEMP%\Catom-Update.exe`.
4. App launches `Catom-Setup-vX.Y.Z.exe /S` (silent install) detached + `os._exit(0)` so NSIS can replace files.
5. NSIS auto-uninstalls the prior version, installs the new one, and `.onInstSuccess` re-launches Catom.
6. Eric is on the new version ~30s after click. No prompts.

## Known gaps

- **No code signing.** SmartScreen warning on the very first install. One-time "More info → Run anyway." Optional to fix with $200/yr OV cert later.
- **Mac builds still run** in CI but have no auto-update path. Mac is for your personal dev use only.
- **Four output bugs** (move dates, multi-attachment serials, Orland Park origin, town-without-job-number) are not fixed by this work — they're separate bugs in `execution/build_ryan_report.py`. Ship installer + auto-update first, verify the channel, then fix bugs as `v1.0.2`+.

## Deferred to a future release

These were discussed but intentionally out of scope for v1.0.0. Coming back to them as `v1.1.0` or later, behind the auto-update channel so they ship transparently to Eric:

- **Headless browser + in-app 2FA prompt.** Today the Chrome window opens minimized off-screen and the user clicks nothing; the 2FA popup is handled inside the Catom UI. A true headless mode (no Chrome window at all) with a modal-style 2FA prompt would eliminate any chance of Eric clicking the wrong thing in Chrome. Defer until v1.0.0 install is verified in production for two reasons: (1) headless on Axon's SPA needs separate testing for rendering quirks, (2) the visible-minimized mode is the known-working path from the May 7 install.
- **Concurrent-login eviction.** Axon TMS sometimes pops a "You're logged in elsewhere — disconnect that session?" modal during automation if another tab/session is active. Today this can stall a run. Future fix: detect the modal, click Disconnect automatically, log a warning. Not blocking today since Eric is the sole automation user on the Catom Trucking Axon account.
