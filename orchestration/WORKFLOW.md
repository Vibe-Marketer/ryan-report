# Workflow

## Weekly Flow

1. Download the latest `Order Master Report`.
2. Download the latest `New RYAN` report.
3. Keep the historical Ryan ledger CSV available.
4. Run the pipeline.
5. Review `state/unresolved_serials.csv`.
6. If needed, add serial mappings to `state/serial_overrides.csv`.
7. Re-run the pipeline.
8. Publish the append-ready Ryan report.

## Trigger Modes

- Manual: `python3 execution/run_pipeline.py --skip-download`
- Manual with shell wrapper: `./execution/run_pipeline.sh --skip-download`
- Manual with Windows wrapper: `execution\run_pipeline.bat --skip-download`
- Scheduled: OS-native scheduler or later desktop scheduler

## Current Recommended Inputs

- `New RYAN ...csv`
- `Order Master Report ...csv`
- historical Ryan CSV

## Current Recommended Output

- append-ready Ryan CSV against an existing Ryan ledger

## Notes

- `audit info` is optional and not currently required for the main build.
- Browser download automation is a helper, not the source of truth.
