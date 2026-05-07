---
name: append-ryan
description: Install or reconfigure a daily scheduled task that ingests fresh Axon trucking exports (New RYAN, Order Master Report, optional audit info) and appends new equipment-move rows into the canonical 2026 RYAN MOVES.xlsx workbook. Carries over into the latest section's empty template-padded rows first, overflows into new sections wrapping at 25 rows each, and creates a draft email (never auto-sent, recipients configurable) with the workbook attached every time a section hits 25 rows. Triggers when the user mentions installing, scheduling, reconfiguring, or fixing the append-ryan task, the daily Ryan report append, the Ryan moves automation, or any routine maintaining a printable Ryan equipment-moves ledger from Axon downloads — even without the word "skill." Also use it for updating email recipients, schedule time, or source paths, or running the append manually.
---

# Append-Ryan — installation skill

This skill installs and configures a daily recurring task that ingests fresh Axon exports, appends new equipment-move rows to the canonical `2026 RYAN MOVES.xlsx` workbook, and drafts a review email each time a printable section hits 25 rows.

When the user invokes this skill, treat each invocation as a setup or reconfigure conversation. Be efficient: confirm what they want, ask only what you need (using AskUserQuestion for non-trivial choices), default to sensible values, and confirm before writing anything to disk.

## What the automation does (high level)

Each day at the chosen time:

1. The scheduled task scans the user's source folder (default `~/Downloads/ryan-moves-and-tests/`) for the latest `New RYAN*.csv` and `Order Master Report*.csv` (and optionally `audit info*.csv`) — the three reports the user's existing Axon desktop app downloads.
2. If both required files are present, it runs `build_ryan_report.py` against them, using the canonical `2026 RYAN MOVES.xlsx` as the historical equipment-list source. The build script unions every year sheet (2016 through 2026) so the serial → description / meter lookup sees the user's full equipment history.
3. It runs `append_to_xlsx.py` with carry-over filling:
    - First fills the latest section's open template-padded rows (lines that exist with a number in column A but no order # in column K).
    - When that section hits 25 rows, the section is "complete."
    - Overflow rows roll into a new section (page number auto-increments), with up to 25 data lines and template-padded trailing rows so tomorrow's run can carry over.
4. For every section that hit 25 rows during this run, the task drafts an email (never auto-sent) to the configured recipients with the workbook attached, body referencing the page number and date, so the user can review and send.
5. Source files are moved into a dated archive subfolder (default `~/Downloads/ryan-archive/<YYYY-MM-DD>/`) along with the run summary JSON. The xlsx is left in place.

The user's existing Axon desktop app keeps doing its thing — this skill only handles what happens after the source CSVs hit the source folder.

## Installation workflow

### Step 1: Confirm intent

If the user's prompt was vague ("install the append-ryan thing"), confirm it's a first-time setup. If they're reconfiguring (different schedule, different recipients, etc.), ask which parts to change so you don't redo settled choices.

### Step 2: Locate this skill's bundled scripts

This skill ships three runtime scripts in its own `scripts/` subfolder. Find this skill's installed path — it appears in the system prompt's `<available_skills>` list under `<location>` for `name: append-ryan`. Read that location once at the start of the workflow so you can copy scripts in step 4.

### Step 3: Gather configuration

Use AskUserQuestion (or short clarifying questions) to confirm:

- Source folder — where the desktop app drops fresh Axon CSVs. Default: `~/Downloads/ryan-moves-and-tests`. If the folder doesn't exist, offer to create it.
- Canonical xlsx path — the workbook to append into. Default: `~/Downloads/2026 RYAN MOVES.xlsx`. If not present, surface the error before proceeding.
- Archive root — where processed source files are moved. Default: `~/Downloads/ryan-archive`. Each daily run creates a dated subfolder underneath.
- Schedule time — when the daily run fires, in the user's local timezone. Default: 7:00 AM (cron `0 7 * * *`).
- Email setup (after the four above) — ask whether the user wants the draft-email-on-section-complete feature. If yes, collect:
    - From email — the address the draft should send from. (Has to match an account the user has connected via a Gmail / Outlook / similar MCP connector.)
    - To email — the primary recipient.
    - CC (optional, comma-separated).
    - Subject prefix (optional, default: `Ryan Equipment Moves`).

If the user signals they're fine with defaults, don't drag them through every option.

If the user wants email but doesn't have a Gmail / Outlook MCP connector installed, run `mcp__mcp-registry__search_mcp_registry` with terms like `["gmail", "outlook", "google workspace", "email", "mail"]` and `mcp__mcp-registry__suggest_connectors` to walk them through installing one. They can re-run this skill afterwards to finish email setup.

### Step 4: Install the scripts

The recurring task needs the runtime scripts at a stable path. Use `~/Documents/Claude/Scheduled/append-ryan/scripts/` (alongside where Cowork stores the scheduled task's `SKILL.md`).

Use bash to:

1. Create the destination: `mkdir -p ~/Documents/Claude/Scheduled/append-ryan/scripts`
2. Copy the three scripts from this skill's bundled `scripts/` directory there, overwriting any older versions (the bundled versions are source of truth).
3. Verify all three scripts (`build_ryan_report.py`, `append_to_xlsx.py`, `run_daily_append.py`) landed and report the destination path back.

Note: in Cowork's sandbox, paths translate. The user-facing `~/Documents` is the host path; from the sandbox, it appears under `/sessions/<session-id>/mnt/Documents`. Translate as needed when invoking bash.

### Step 5: Save email config (if email is enabled)

Write the email config to `~/Documents/Claude/Scheduled/append-ryan/email-config.json`. Keep it minimal:

```json
{
    "enabled": true,
    "from_email": "...",
    "to_email": "...",
    "cc": "",
    "subject_prefix": "Ryan Equipment Moves"
}
```

If email is disabled, write `{"enabled": false}` so the runtime task knows to skip the draft step. Use file-permission `0600` if your tools support it — these are the user's emails.

### Step 6: Register the scheduled task

Call `mcp__scheduled-tasks__create_scheduled_task` with:

- `taskId`: `append-ryan`
- `description`: a short one-liner like `Daily 7am: append new Axon downloads to 2026 RYAN MOVES.xlsx, archive sources, draft email when sections hit 25 rows.` (Use the actual time the user picked.)
- `cronExpression`: the 5-field cron from step 3.
- `prompt`: the runtime prompt template below, with the user's chosen paths and email settings substituted in.

If a task with that ID already exists, the tool updates it — the right behavior for reconfigure flows.

#### Runtime prompt template

Substitute `{source_dir}`, `{xlsx_path}`, `{archive_root}`, `{email_enabled}` (boolean), `{email_config_path}` with the user's chosen values. Keep the wording — it's been tuned for autonomous unattended runs.

```
Run the daily Ryan Report append. This is a scheduled background task — work autonomously, don't ask the user clarifying questions. If something fails, report it clearly so the user sees it.

Pipeline:

1. Locate the runtime script. It lives at the host path
   ~/Documents/Claude/Scheduled/append-ryan/scripts/run_daily_append.py
   For mcp__workspace__bash you need the sandbox-mapped path. Construct it
   from your session by checking which /sessions/<id>/mnt/Documents path
   you have access to, then append /Claude/Scheduled/append-ryan/scripts/run_daily_append.py.

2. Run the script with these arguments:
     python3 <sandbox-mapped run_daily_append.py> \
         --source-dir "{source_dir}" \
         --xlsx "{xlsx_path}" \
         --archive-root "{archive_root}"

3. Read the script's stdout. Possible outcomes:
   - "Nothing to do — required source files are missing." → No fresh
     downloads. Normal on days the desktop app didn't run. Report briefly
     and stop.
   - "ERROR: Excel currently has '...' open ..." → The xlsx is locked
     because Excel has it open. Surface this clearly; user closes Excel,
     next run picks up.
   - Build or append failure (non-zero exit, error in stdout) → Surface the
     full error message.
   - Successful run → stdout includes "Appended: N  Skipped (duplicates):
     M  Carry-over filled: ...  New sections: ...  Completed sections this
     run: K". Also look for ">> SECTIONS_COMPLETED_THIS_RUN: K  page
     numbers: [...]" if K > 0.

4. If the run was successful, summarize for the user: how many rows were
   appended, how many sections were completed (by page number), where the
   source files were archived to.

5. EMAIL DRAFT step (only if email is enabled = {email_enabled}):

   If sections were completed this run AND email is enabled:

   a. The append script archived the run summary into the dated archive
      folder: {archive_root}/<today>/completion-summary.json. Read it via
      the file tools or bash. The summary's `completed_sections` array
      lists each completed section's page_number, completion_type, and
      rows_added_this_run.

   b. Read the email config from {email_config_path} to get from_email,
      to_email, cc, and subject_prefix.

   c. For each completed section, create ONE email draft (never auto-send)
      using whichever email MCP connector is installed on this machine.
      Common candidates:
        - mcp__gmail__create_draft (or mcp__gmail__draft_message)
        - mcp__outlook__create_draft (or mcp__outlook__create_message)
        - any tool whose name contains "create_draft" or "compose"
      Use the connector's create-draft tool. Subject:
        "{subject_prefix} — Page NN ready for review (YYYY-MM-DD)"
      Body (plain text):
        "Page NN of 2026 RYAN MOVES is ready for review.

         {rows_added_this_run} new rows were appended on YYYY-MM-DD,
         completing the section. The full workbook is attached for review.

         — append-ryan automation"
      Attachment: {xlsx_path} (the canonical xlsx — full workbook).
      From: {from_email}.  To: {to_email}.  CC: {cc} (omit if empty).

      If no email MCP connector is available, log clearly that the draft
      could not be created because no email connector is installed, and
      tell the user how to fix it (install Gmail or Outlook MCP via the
      mcp-registry, then re-run the skill to update settings). DO NOT use
      computer-use or other tools to send email — drafts only, via a
      connector.

   d. Tell the user that drafts have been created and where to review them.

6. On a successful run with no completed sections, just report the row count
   summary. No draft is needed.

Important guardrails:
- Never auto-send an email. Always create as a draft for the user to review.
- If Excel has the xlsx open (~$ lock file present), the script refuses to
  write — surface that clearly. Don't try to work around it.
- Don't move or modify files outside the source folder, the canonical xlsx,
  the archive folder, and the email config file.
- If the script exits non-zero, source files are intentionally left in
  place so they can be reprocessed on the next run — don't try to clean up
  or retry within this same run.
```

### Step 7: Confirm to the user

Tell the user:

- The task is scheduled (mention the time and cron expression).
- The next run will fire at the next matching local time.
- They can use Cowork's "Run now" button on the task to do a one-off pre-approval run.
- If email is enabled: drafts are saved to their connected email account's drafts folder; they review and send manually.
- They can re-invoke this skill anytime to update paths, schedule time, or recipients.

### Optional: dry-run verification

If the user wants reassurance the wiring is correct, run the script once with `--dry-run` from the chat (not the scheduled task) using the same arguments. The script reports what it would do without touching anything.

## Reference files

- `references/setup.md` — Detailed setup instructions for the user, troubleshooting common issues (Excel lock, missing source files, schedule time mismatch, email connector issues).
- `scripts/build_ryan_report.py` — Existing build pipeline. Reads New RYAN + Order Master Report + historical xlsx; produces the new-only CSV.
- `scripts/append_to_xlsx.py` — Carry-over append. Fills open template slots first, overflows into new sections at 25-rows-per-section, writes a JSON run summary describing exactly what happened.
- `scripts/run_daily_append.py` — Wrapper that ties build + append together, archives source files + run summary, surfaces SECTIONS_COMPLETED_THIS_RUN markers.

## What this skill does NOT do

- It does not download reports from Axon. The user's existing desktop app handles that — bundled browser, 2FA, OS-native scheduling.
- It does not modify the user's existing app or its credentials.
- It does not auto-send any email. Drafts only — the user reviews and sends.
- It does not delete files. Source files are moved to the archive folder; archives are never auto-purged.

If the user asks for any of the above, say so plainly and offer the closest available alternative.
