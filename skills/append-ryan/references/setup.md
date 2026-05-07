# Append-Ryan — operator notes

This file is a quick reference for the operator (the person installing or maintaining the append-ryan task). Claude reads this when the user asks troubleshooting questions or wants more detail about how a piece works.

## Pipeline overview

```
[Axon desktop app]               (unchanged — the user's existing tool)
      |
      |  daily download of New RYAN.csv + Order Master Report.csv (+ optional audit info.csv)
      v
~/Downloads/ryan-moves-and-tests/
      |
      |  scheduled task fires (default 7am daily)
      |  -> python3 run_daily_append.py
      |
      v
build_ryan_report.py
      |  reads New RYAN + Order Master Report + 2026 RYAN MOVES.xlsx (all year sheets)
      |  emits generated-ryan-report-new-only.csv (the new rows for this run)
      |
      v
append_to_xlsx.py
      |  finds latest section, carry-over fills its open template-padded rows
      |  overflows into new section(s) at 25 rows/section, page numbers auto-increment
      |  writes completion-summary.json describing every section that hit 25 rows this run
      |
      v
~/Downloads/2026 RYAN MOVES.xlsx   (updated)
~/Downloads/ryan-archive/<YYYY-MM-DD>/   (source CSVs + summary moved here on success)
      |
      |  task prompt reads completion-summary.json
      v
For each section that hit 25 rows:
   email MCP connector creates a DRAFT addressed to configured recipients,
   xlsx attached. The user reviews + clicks Send themselves.
```

## Files written by setup

- `~/Documents/Claude/Scheduled/append-ryan/SKILL.md` — the scheduled task's prompt (created by `mcp__scheduled-tasks__create_scheduled_task`).
- `~/Documents/Claude/Scheduled/append-ryan/scripts/{build_ryan_report,append_to_xlsx,run_daily_append}.py` — runtime scripts.
- `~/Documents/Claude/Scheduled/append-ryan/email-config.json` — recipient settings (only when email is enabled).

## Common issues

### "ERROR: Excel currently has '...' open ..."

Excel keeps a `~$<filename>.xlsx` lock file in the same directory while the workbook is open. If the lock file is present, `append_to_xlsx.py` refuses to write — otherwise it would corrupt the file. Fix: close the workbook in Excel. The next scheduled run picks up.

### "Nothing to do — required source files are missing."

The desktop app hasn't dropped a fresh `New RYAN*.csv` and `Order Master Report*.csv` into the source folder. Possible causes: the desktop app didn't run that day, Axon was down, network issue. The task is idempotent — once the files appear, the next run processes them.

### Sections aren't completing / no drafts

A section completes only when its row count reaches 25. If the latest section has 14 populated rows + 11 template-padded rows, today's run needs at least 11 fresh rows to complete it. Otherwise the section stays partial and tomorrow's run carries over.

If the user's daily volume is much less than 25 rows, drafts will fire less often than daily — that's expected behavior. Each draft corresponds to one printed page of the Ryan ledger.

### "No email MCP connector installed"

The task's draft step requires a Gmail / Outlook / similar MCP connector. Re-run the `append-ryan` skill, choose "update email settings," and let it walk through `mcp__mcp-registry__search_mcp_registry` + `mcp__mcp-registry__suggest_connectors` to install one. Then re-run the skill once to refresh email config.

### Schedule didn't fire

Cowork's scheduled tasks fire when Cowork is running. If the user's machine was off or Cowork was closed at the scheduled time, the task fires at the next launch of Cowork (one-time make-up run for cron tasks). Check the task's `lastRunAt` via `mcp__scheduled-tasks__list_scheduled_tasks`.

### Wrong page numbers

Page numbers come from existing sections in the workbook. The script uses the highest existing `PAGE: NN OF 2026` number it finds and increments. If the user manually pasted in a section with a much higher page number, the increment continues from there. Edit the page-footer cell directly in Excel if you need to reset.

## Manual / one-off invocation

The user can run the pipeline outside the schedule any time:

```
python3 ~/Documents/Claude/Scheduled/append-ryan/scripts/run_daily_append.py \
    --source-dir ~/Downloads/ryan-moves-and-tests \
    --xlsx ~/Downloads/"2026 RYAN MOVES.xlsx" \
    --archive-root ~/Downloads/ryan-archive
```

Add `--dry-run` to see what it would do without touching anything. Add `--no-archive` to leave the source files in place after a successful run (useful for re-testing).

## Resetting

To uninstall: delete the scheduled task in Cowork's Scheduled section, then `rm -rf ~/Documents/Claude/Scheduled/append-ryan`. The skill bundle itself can be removed from Cowork's plugin manager. The user's xlsx and archive folder are never deleted automatically.
