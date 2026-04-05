# PRP: Next Phase Execution Plan

## Objective

Productize the current Ryan report automation into a cross-platform local runner with optional desktop UI and Claude trigger.

## Phase 1: Harden Current Engine

1. Normalize junk serial placeholders like `o`, `00`, and similar values.
2. Add stronger serial normalization for space vs dash variants.
3. Improve append logic and reporting around skipped orders.
4. Add structured logs.

## Phase 2: Configurable Local Runner

1. Package Python app with PyInstaller.
2. Add persistent config file handling.
3. Add explicit paths for:
   - download directory
   - Ryan ledger path
   - browser executable
   - browser profile
4. Add first-run setup flow.

## Phase 3: Desktop UI

1. Build a small Tauri or Electron shell.
2. Add buttons:
   - Download Reports
   - Build Ryan Report
   - Run Full Pipeline
   - Open Unresolved Queue
3. Add status surface:
   - last run time
   - rows appended
   - unresolved count

## Phase 4: Scheduling

1. macOS scheduler integration
2. Windows Task Scheduler integration
3. UI controls for schedule frequency and run window

## Phase 5: Claude Trigger

1. Add a Claude/Desktop command or skill wrapper.
2. The command should call the packaged local runner.
3. Claude should act as an operator UX layer, not the sole runtime.

## Open Questions

1. Should the desktop app manage its own browser profile?
2. Should unresolved serial corrections live only in CSV or also in a small SQLite DB?
3. Should the append target remain CSV or optionally become XLSX?

## Immediate Next Tasks

1. filter junk placeholder serials
2. add stable browser automation profile strategy
3. package the engine
4. build minimal UI shell
