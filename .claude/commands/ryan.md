Run the Ryan report pipeline. Usage: /ryan [all|download|build]

- **all** (default): Download reports from Axon + build the combined report
- **download**: Only download the 3 reports from Axon (New RYAN, Order Master, audit info)
- **build**: Only build the report from CSVs already in the downloads folder (skip browser)

Based on the argument "$ARGUMENTS" (default to "all" if empty), run the appropriate command:

- **all**: `python3 execution/run_pipeline.py --config execution/browser_config.json`
- **download**: `python3 execution/download_reports.py --config execution/browser_config.json`
- **build**: `python3 execution/run_pipeline.py --config execution/browser_config.json --skip-download`

After completion, list the output files in `~/Downloads/ryan-moves-and-tests/` with sizes and timestamps.

If any step fails, diagnose the error and suggest a fix. Common issues:
- Browser not running with CDP → the script will relaunch it automatically
- Login expired → the script handles re-login
- CSV files missing → suggest running `/ryan download` first
