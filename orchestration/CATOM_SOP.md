# Catom SOP

## Purpose

This SOP explains how to use the Catom / Axon software to generate the files needed for the Ryan report workflow.

This is the practical operator version:

- log in
- pull the required reports
- run the Catom app
- review the output
- resolve any missing serials if needed

## When To Use This

Use this SOP any time you need to:

- pull a fresh Ryan-related export from Catom / Axon
- generate the updated Ryan moves report
- append new moves into the existing Ryan ledger

## Systems Used

- Catom / Axon web system
- Catom desktop app (`Catom.app` or `Catom.exe`)
- Existing Ryan ledger CSV

## Required Inputs

Before starting, make sure you have:

- your Catom / Axon subdomain
  - example: `catom`
- your Catom / Axon username
- your Catom / Axon password
- the current Ryan ledger CSV
  - example: `2026 RYAN MOVES.csv`

## Output From This Process

This process produces:

- downloaded Catom source reports
- a fresh generated Ryan report CSV
- an append-ready Ryan report CSV
- an unresolved serial file if manual cleanup is needed

## Standard Run Frequency

Use this process whenever a fresh Ryan report needs to be built.

Typical cadence:

- weekly
- end of billing cycle
- whenever Ryan asks for updated moves

## Procedure

### 1. Open The Catom App

Open the Catom desktop app.

On first setup, complete the wizard:

- choose your browser
- enter your company subdomain
  - example: `catom`
- enter your Axon username
- enter your Axon password
- choose the historical Ryan ledger CSV

Important:

- the app builds the full site URL automatically as `https://SUBDOMAIN.axoneta.io`
- the user should only enter the subdomain portion

### 2. Confirm Settings

In Settings, confirm:

- browser selection is correct
- login credentials are correct
- download folder is correct
- historical Ryan CSV path is correct

If anything changed, save settings before running.

### 3. Run The Full Workflow

From the main Run screen, click:

- `Run All`

This tells the app to:

1. connect to the configured browser
2. log into Catom / Axon if needed
3. download the required reports
4. build the updated Ryan report

### 4. Reports Pulled From Catom / Axon

The current workflow uses these Catom / Axon reports:

1. `New RYAN`
2. `Order Master Report`
3. `audit info`

Current note:

- `audit info` is downloaded by the automation flow
- it is optional for the main build logic today
- `New RYAN` and `Order Master Report` are the core required reports

### 5. Manual Report Paths In Catom / Axon

If you ever need to pull the reports manually inside the web app, use these paths.

#### New RYAN

Path:

- `Trucking`
- `Reporter Reports`
- `New RYAN`
- `Export`

Behavior:

- no filter fields required
- a `Working...` message may appear
- file downloads directly

#### Order Master Report

Path:

- `Trucking`
- `Order Master Report`
- `Export`

Expected preset filters:

- `Order End Date` = range
- `Bill To` = `Ryan, Inc.`
- `Voided On` = empty

Behavior:

- file downloads directly

#### audit info

Path:

- `Trucking`
- `Reporter Reports`
- `audit info`
- `Export`

Expected preset filter:

- `Order Date` > `02/01/2026`

Behavior:

- a `Working...` message may appear
- file downloads directly

## Success Criteria

The run is successful if:

- the app finishes without a fatal error
- the report files are downloaded
- a new Ryan output CSV is generated
- an append-ready CSV is generated

## Post-Run Review

After the run finishes:

1. review the generated output files
2. confirm the append-ready Ryan CSV was created
3. check whether `state/unresolved_serials.csv` was produced or updated

If unresolved serials exist:

1. open `state/unresolved_serials.csv`
2. identify the missing serial descriptions
3. add confirmed mappings to `state/serial_overrides.csv`
4. rerun the build

## Common Issues

### Login Fails

Check:

- subdomain is correct
- username is correct
- password is correct
- the full URL should be `https://SUBDOMAIN.axoneta.io`

### Browser Opens But Workflow Does Not Complete

Check:

- the correct browser is selected
- the browser profile is the one that has Catom access
- the app still has permission to use that browser profile

### Report Downloads But Build Fails

Check:

- historical Ryan CSV path is correct
- the chosen Ryan ledger file is the right one
- the downloaded source files exist in the configured download folder

### Output Has Missing Descriptions

This usually means serial mappings are incomplete.

Resolve by:

- reviewing `state/unresolved_serials.csv`
- adding confirmed mappings to `state/serial_overrides.csv`
- rerunning the workflow

## Manual Fallback

If automation is temporarily broken:

1. log into Catom / Axon manually
2. export `New RYAN`
3. export `Order Master Report`
4. export `audit info` if needed
5. place the files in the normal download folder
6. run the build-only mode in the Catom app

## Operator Notes

- Do not reload the Axon app unnecessarily during automation.
- If the Catom UI labels change slightly, validate the report names before assuming the automation is wrong.
- `RYAN TEST` may also appear in the Reporter Reports list, but `New RYAN` is the intended report for this workflow.

## Owner

This SOP should be updated whenever:

- Catom / Axon navigation changes
- required reports change
- the Catom desktop app flow changes
- Ryan report business rules change
