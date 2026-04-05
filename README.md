# ryan-report

Local automation for building the Ryan moves report from Axon exports.

## Current Status

This repo packages the working implementation that exists today.

It can currently:

- read `Order Master Report ...csv`
- read `New RYAN ...csv`
- read a historical Ryan CSV ledger
- explode `Serial #`, `Serial #2`, `Serial #3`, `Serial #4` into separate Ryan rows
- append only orders not already present in the existing Ryan report
- learn serial-to-description mappings from historical Ryan output
- emit an unresolved serial queue for manual fixes

It also includes a browser-download runner for Axon so the source reports can be downloaded before the build step.

## DOE Structure

- `directives/`: immutable business rules, mappings, and guardrails
- `orchestration/`: runbooks, workflows, schedules, and packaging notes
- `execution/`: runnable code and wrappers
- `state/`: learned lookup tables and manual overrides
- `planning/`: PRD and PRP for the next implementation phase

## What Works Right Now

Inputs:

- `Order Master Report ...csv`
- `New RYAN ...csv`
- historical Ryan CSV such as `2026 RYAN MOVES.csv`

Outputs:

- fresh Ryan-format CSV
- append-ready Ryan-format CSV
- unresolved serial queue
- generated serial lookup table

## Exact Run Commands

Manual build only:

```bash
python3 execution/build_ryan_report.py \
  --input-dir "/Users/Naegele/Downloads" \
  --order-master "/Users/Naegele/Downloads/Order Master Report 2026-04-04 205709.csv" \
  --new-ryan "/Users/Naegele/Downloads/New RYAN 2026-04-04 205755.csv" \
  --historical-ryan "/Users/Naegele/Downloads/ryan-moves-and-tests/2026 RYAN MOVES.csv" \
  --output "/Users/Naegele/Downloads/generated-ryan-report-latest-new-only.csv" \
  --append-to "/Users/Naegele/Downloads/ryan-moves-and-tests/2026 RYAN MOVES.csv" \
  --append-output "/Users/Naegele/Downloads/append-ryan-report-latest.csv" \
  --only-new-orders
```

Manual end-to-end runner:

```bash
python3 execution/run_pipeline.py --skip-download
```

Shell wrapper:

```bash
./execution/run_pipeline.sh --skip-download
```

Windows wrapper:

```bat
execution\run_pipeline.bat --skip-download
```

Browser download runner (with profile‑lock fallback):

```bash
python3 execution/download_reports.py --config execution/browser_config.example.json
```

The downloader now attempts to use the configured Chromium/Comet profile. If the profile is already open and locked, it automatically creates a temporary copy of the profile and runs the automation against that copy, logging a short informational message. This makes the automation reliable even when the user has the browser open for other tasks.

## Current Known Gaps

- Brand-new secondary serials may have no known description.
- Those unresolved cases are written to `state/unresolved_serials.csv`.
- Additional junk placeholder variants may still appear in source exports and should be normalized as they are discovered.
- Live browser automation is implemented but still needs a stable dedicated automation profile or direct in-place tab control.

## Recommended Client Packaging

Current recommendation:

1. keep this repo as the core engine
2. package it as a cross-platform local runner
3. add a lightweight desktop UI
4. optionally add a Claude Desktop command/skill as a manual trigger

See:

- `orchestration/DOE_FRAMEWORK.md`
- `orchestration/WORKFLOW.md`
- `orchestration/CLIENT_DEPLOYMENT.md`
- `planning/PRD-next-phase.md`
- `planning/PRP-next-phase.md`
