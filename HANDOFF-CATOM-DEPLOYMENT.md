# Catom Deployment Handoff

## 1. Project Overview

This workstream is about the `Catom` desktop app in the repo at `/Users/Naegele/dev/ryan-report`. The app is intended to let a client download Axon/CATOM reports and build the combined Ryan report through a desktop UI, with browser-based automation behind the scenes.

The immediate goals became:

- make the Catom desktop app reliable for client use
- support `Chrome`, `Chromium`, and `Comet`
- improve runtime visibility and error handling
- package the app cleanly for install on macOS
- ensure first-time setup works correctly for clients
- remove stale/cached config behavior from upgrades
- push changes to git so the user can test

A secondary goal was to create an SOP for using the CATOM software.

## 2. Earlier Context Recovered From Claude Conversation

A prior Claude Code conversation was located and read fully. The relevant Claude conversation ID is:

- `696be052-1d95-4056-8340-6948ec275f47`

That conversation established the earlier technical approach for Ryan report automation:

- work happened in `~/dev/ryan-report/`
- browser control moved to CDP attach against the user’s real browser session instead of launching a fresh isolated browser
- Axon/CATOM was found to be fragile as an SPA
- navigation often had to happen via JS clicks and iframe-aware interactions
- `Contents` tab reset before each report improved reliability
- the intended reports were:
  - `New RYAN`
  - `Order Master Report`
  - `audit info`
- the pipeline already existed:
  - `download_reports.py`
  - `build_ryan_report.py`
  - `run_pipeline.py`
- the desktop packaging direction was:
  - `pywebview`
  - setup wizard
  - browser autodetection
  - PyInstaller packaging

That earlier conversation matters because many of the current fixes were trying to preserve that workflow while making the packaged app client-safe.

## 3. Repo and Key Files

Repo root:

- `/Users/Naegele/dev/ryan-report`

Main files touched or relevant:

- `app/main.py`
- `app/build.py`
- `execution/download_reports.py`
- `execution/browser_config.json`
- `execution/browser_config.example.json`
- `app/ui/index.html`
- `orchestration/CATOM_SOP.md`

Build artifacts in the original output folder:

- `dist/Catom.app`
- `dist/Catom.pkg`
- `dist/Catom.zip`

Clean rebuild artifacts in alternate folder:

- `dist-clean/Catom.app`
- `dist-clean/Catom.pkg`

## 4. User-Visible Problems Being Solved

The user reported several concrete issues:

1. App timed out during pipeline execution with only a generic message:
   - `Pipeline timed out after 5 minutes`

2. The app needed to work with:
   - `Chrome`
   - `Chromium`
   - `Comet`

3. The app needed better runtime visibility instead of long silent waits.

4. The app was expected to show a first-time setup wizard after install, but instead launched with old values already filled in.

5. Even after uninstall/reinstall, the app still showed old CATOM settings, including stale login/browser values.

6. macOS packaging/install behavior was inconsistent:
   - `.app` and `.pkg` were being produced
   - `.dmg` creation kept failing
   - Installer/upgrade behavior was not reliably replacing the old bundle

7. Signing was desired for proper client distribution, but Developer ID signing was blocked.

## 5. Work Completed

### 5.1 SOP Creation

A CATOM SOP was created:

- `orchestration/CATOM_SOP.md`

This was created based on the recovered Claude conversation and current project context.

### 5.2 Runtime Error Handling and Visibility

Changes were made in `app/main.py`:

- subprocess output is streamed live into the UI instead of buffered until the end
- preflight validation was added for:
  - browser executable path
  - browser user data directory
  - Axon URL
  - username/password
  - download directory
  - historical Ryan CSV
  - enabled reports
- build-step input validation was added
- timeout budgeting was improved
- download timeout is now computed more realistically instead of a hard-coded 5-minute failure
- timeout errors now give clearer context

Result:

- the app should now show what it is doing in real time
- failures should be easier to localize

### 5.3 Browser Support Hardening

Changes were made in both `app/main.py` and `execution/download_reports.py`:

- explicit browser detection/support added for:
  - `Comet`
  - `Google Chrome`
  - `Chromium`
- browser handling was made Chromium-family oriented instead of implicitly Comet-only
- process/path validation was improved

Result:

- browser selection is no longer conceptually tied only to Comet
- Chrome and Chromium are intended supported paths

### 5.4 Packaging Improvements

Changes were made in `app/build.py`:

- build process creates:
  - `.app`
  - `.pkg`
  - `.zip`
- app bundle wrapping was added around PyInstaller output so there is a real `.app`
- build no longer depends on DMG succeeding
- DMG failure is treated as non-fatal
- support added for optional signing env vars:
  - `CATOM_CODESIGN_IDENTITY`
  - `CATOM_INSTALLER_IDENTITY`
- support added for alternate dist output via:
  - `CATOM_DIST_DIR`
- package now includes a `preinstall` script intended to remove an existing `/Applications/Catom.app` before install

Important packaging limitation:

- DMG creation still fails with:
  - `hdiutil: create failed - Device not configured`

### 5.5 First-Run / Config Isolation Work

This was the most important and most problematic area.

#### Intended design

The correct first-run behavior is:

- packaged app should use `browser_config.example.json` only as a template
- real user config should live in user space:
  - `~/Library/Application Support/Catom/browser_config.json` on macOS
- first-time wizard should show until user actually saves config
- bundled legacy config inside the app should never count as real user setup

#### Changes made

In `app/main.py`:

- config path logic was redirected to user profile storage:
  - `~/Library/Application Support/Catom/browser_config.json`
- `is_configured()` was changed so it only returns `True` if the real user config file exists and contains a username
- legacy bundled config cleanup logic was added to remove any old embedded `browser_config.json` at startup if present

In `app/build.py`:

- execution files are staged with `browser_config.json` excluded
- only `browser_config.example.json` should be bundled in the clean build

#### Verified clean behavior in build artifacts

The clean build in `dist-clean/Catom.app` was verified:

- no bundled `browser_config.json`
- bundled `browser_config.example.json` exists at:
  - `dist-clean/Catom.app/Contents/Resources/app/_internal/execution/browser_config.example.json`

The clean package in `dist-clean/Catom.pkg` was also verified to contain the clean app payload layout.

## 6. Root Cause Analysis

This was investigated extensively. The current best root-cause statement is:

### Root cause

The app originally stored live configuration inside the app bundle itself. Older installed builds had a legacy layout like:

- `/Applications/Catom.app/Contents/Resources/execution/browser_config.json`

That file contained real saved user values, including CATOM URL, username, browser path, etc.

Later builds changed the app structure and intended config handling, but macOS install/upgrade behavior did not produce a clean replacement of the old app bundle. As a result:

- old orphaned files inside the installed `.app` survived upgrade/install cycles
- the installed app still contained stale bundled config
- the UI showed old values as if setup had already happened
- uninstall/reinstall attempts were misleading because the installed bundle was not being replaced cleanly enough

This is why the user kept seeing the same old settings even after reinstalling.

### Evidence found

The installed app at `/Applications/Catom.app` was confirmed at one point to contain:

- `/Applications/Catom.app/Contents/Resources/execution/browser_config.json`

That file contained the stale CATOM values the user was seeing on screen.

The trashed older app copies also contained the same legacy bundled config.

The clean rebuilt bundle in `dist-clean` does not contain that file.

### Important implication

This was not just “Finder cache” or “user profile cache.” It was a real stale file surviving inside installed app bundles because of a bad legacy-to-new bundle upgrade path.

## 7. Current State Right Now

### Code state

The codebase now contains the intended fixes for the actual root cause:

- first-run depends only on real user config
- legacy bundled config is ignored/cleaned at runtime
- build excludes live `browser_config.json`
- package includes preinstall cleanup
- browser support and runtime visibility are improved

### Build state

A clean build exists in:

- `dist-clean/Catom.app`
- `dist-clean/Catom.pkg`

These were created specifically to route around the corrupted/locked old `dist` artifacts.

### Installed app state

There is still an installed app at:

- `/Applications/Catom.app`

There are also multiple old app copies in Trash:

- `/Users/Naegele/.Trash/Catom.app`
- `/Users/Naegele/.Trash/Catom 1.58.25 PM.app`
- `/Users/Naegele/.Trash/Catom 2.05.01 PM.app`

Finder visually showed duplicate icons at one point, but filesystem checks showed only one real installed app in `/Applications`; the rest were trashed copies / Finder indexing noise.

### Packaging/install state

This is the main unresolved operational issue:

- `/Applications/Catom.app` has been resistant to direct overwrite/delete from the current shell because of permissions and prior install state
- the old `dist/Catom.app` artifact is also root-owned / permission-locked and cannot be cleanly removed from the current shell
- therefore, `dist-clean` is currently the trustworthy output location, not the original `dist`

## 8. Git Status / Commits

Earlier commits already pushed to `main` include:

- `a443899` Improve Catom packaging and runtime visibility
- `cbe7b53` Fix Catom app bundle packaging
- `a155c15` Use per-user config for Catom first-run setup

There are additional uncommitted changes at the end of this thread, specifically in:

- `app/main.py`
- `app/build.py`

These latest changes include the strongest root-cause fix:

- `is_configured()` based on user config file only
- runtime cleanup of legacy bundled config
- alternate dist support
- package preinstall cleanup script

Those latest changes still need to be committed and pushed.

## 9. Signing / Certificate Status

The user wanted the app signed and ready for client use.

### What was attempted

- existing Developer ID certificates were checked in Keychain
- new CSR/key pairs were generated locally
- user reissued/imported cert material through Apple Developer / Keychain
- attempts were made to use `security`, `codesign`, and installer signing from Terminal

### Current result

Terminal still could not use a valid Developer ID identity.

Observed problems:

- `security find-identity -v -p codesigning` reported no valid usable identity in practice
- `codesign` could not use the expected Developer ID identity
- app builds are therefore ad hoc signed only
- pkg is not confirmed as proper Developer ID signed

### What this means

For internal/local testing:

- current builds are usable

For polished client distribution:

- proper Developer ID signing is still unfinished
- Gatekeeper-clean delivery is not yet complete

## 10. Important Sensitive Context

A stale bundled config file was found inside old app bundles that contained real login/config values. Those values should be treated as compromised internal project data and should not be preserved in documentation, screenshots, commits, or future package payloads.

The key takeaway is:

- old bundled `browser_config.json` files must never ship again
- any old copies in Trash or legacy installed bundles should be treated as contaminated artifacts

## 11. Main Outstanding Items

### Highest priority

1. Finish a clean installation path using the verified clean build in `dist-clean`
2. Confirm the installed app actually launches into the setup wizard
3. If needed, fully remove the existing `/Applications/Catom.app` using a method with sufficient privileges outside the current blocked shell path
4. Commit and push the latest root-cause fixes
5. Retest full first-run flow
6. Retest runtime logging
7. Retest with:
   - Chrome
   - Chromium
   - Comet

### Secondary priority

8. Resolve proper Developer ID signing for both app and installer
9. Rebuild final client-facing package after signing is fixed
10. Optionally clean Finder/Trash noise once the real install problem is resolved

## 12. Recommended Next Steps

This is the exact handoff sequence I would recommend.

### Step 1: Preserve current code changes

Commit and push the uncommitted changes in:

- `app/main.py`
- `app/build.py`

### Step 2: Remove the currently installed app with sufficient privileges

The blocking issue now is not the clean build; it is replacement of the stale installed app in `/Applications`.

Use a method that actually has the needed privileges and can fully remove:

- `/Applications/Catom.app`

Do not rely on overlaying over the old bundle.

### Step 3: Install the clean build

Install from:

- `dist-clean/Catom.pkg`

or, if package behavior is still suspect, directly place:

- `dist-clean/Catom.app`

into `/Applications` after the stale app is fully removed.

### Step 4: Verify first-run behavior

Expected behavior after clean install:

- no prefilled prior state
- setup wizard should appear
- user config file should not exist until saved:
  - `~/Library/Application Support/Catom/browser_config.json`

### Step 5: Verify browser support

Test setup flow and runtime flow with:

- Comet
- Google Chrome
- Chromium

### Step 6: Verify runtime behavior

Test:

- live log streaming
- download timeout visibility
- report download step
- build step
- build-only flow
- download-only flow

### Step 7: Finish signing

After functional verification:

- resolve Terminal-visible Developer ID identities
- sign app
- sign pkg
- rebuild final client installer

## 13. Key Technical Conclusions

These are the conclusions the next owner should treat as settled unless disproven by fresh evidence.

1. The stale setup issue was real and file-based, not user imagination.
2. The root cause is legacy bundled config surviving upgrade/install cycles.
3. The correct architecture is:
   - bundled example config only
   - real config in user profile
4. `is_configured()` must not rely on example/bundled config.
5. The app should defensively delete legacy bundled `browser_config.json` at startup.
6. The installer should delete an existing `/Applications/Catom.app` before installing the new one.
7. `dist-clean` is currently the trustworthy build output, not `dist`.
8. DMG creation is still broken but not a blocker for functional testing.
9. Proper Developer ID signing is still unresolved.

## 14. Risks / Caveats

- The installed `/Applications/Catom.app` may still be stale until explicitly removed with sufficient privileges.
- Finder visuals are noisy and should not be trusted over filesystem inspection.
- Old app copies in Trash still contain legacy bundled config and should not be reused.
- The original `dist/Catom.app` is permission/ownership contaminated and should not be trusted.
- Until signing is fixed, client distribution quality is incomplete.

## 15. Handoff Summary

The project is not blocked on mystery behavior anymore. The root cause has been identified: legacy bundled config inside old app bundles survives upgrades and makes the app look preconfigured. Code-level fixes have been added to prevent that permanently, and a clean build has been produced in `dist-clean`.

The remaining work is operational and release-focused:

- remove the stale installed app cleanly
- install the verified clean build
- confirm first-run wizard appears
- commit/push latest fixes
- resolve Developer ID signing
- produce final client-ready release

The most important artifacts for the next person are:

- clean app: `dist-clean/Catom.app`
- clean installer: `dist-clean/Catom.pkg`
- root-cause fix code: `app/main.py`
- installer cleanup logic: `app/build.py`
- SOP: `orchestration/CATOM_SOP.md`
