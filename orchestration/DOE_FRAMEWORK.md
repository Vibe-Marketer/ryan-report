# DOE Framework

## Directives

The directives layer defines immutable truth:

- exact source priority
- exact field mappings
- exact guardrails
- exact self-annealing rules

Primary file:

- `directives/DIRECTIVES.md`

## Orchestration

The orchestration layer defines:

- the weekly operator workflow
- the trigger modes
- packaging guidance
- client deployment guidance
- scheduling guidance

Primary files:

- `orchestration/WORKFLOW.md`
- `orchestration/CLIENT_DEPLOYMENT.md`

## Execution

The execution layer contains the working code:

- `execution/build_ryan_report.py`
- `execution/download_reports.py`
- `execution/run_pipeline.py`
- `execution/run_pipeline.sh`
- `execution/run_pipeline.bat`

## State

The state layer stores learned and human-corrected knowledge:

- `state/generated_serial_lookup.csv`
- `state/serial_overrides.csv`
- `state/unresolved_serials.csv`

## Why This DOE Shape Works

- business rules are explicit and reviewable
- execution is isolated from operator workflow
- state improves over time without code changes
- next-step productization can reuse the same layers in a desktop app or Claude trigger
