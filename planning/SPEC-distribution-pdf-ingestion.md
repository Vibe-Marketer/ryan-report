# Distribution PDF Ingestion — Spec

Status: PROPOSED · Date: 2026-05-07

## Problem

Pipeline output writes From/To as `"PLEASANT PRAIRIE, WI"`. Customer wants `3416.2-PLEASANT PRAIRIE` (Job# + city). Job# is not in any Axon export the pipeline currently pulls. It IS in the **RIC EM Distribution Report by Area** PDF that Ryan emails to Eric whenever asset assignments change.

Goal: turn that PDF into a deterministic, low-touch source of truth for asset → current-job# mapping, with no Eric-side workflow change beyond saving the PDF to a folder.

## Why this beats the alternatives

| Approach | Coverage | Eric burden | Code complexity | Verdict |
|---|---|---|---|---|
| City → most-common job# fallback | ~50% (208 cities have multi-job ambiguity, including PLEASANT PRAIRIE with 9 active jobs in 2025) | none | low | rejected — silently wrong |
| New Axon report w/ Shipper/Consignee | unknown — may not exist | full IT-blocked install + new browser steps | high | deferred |
| Distribution PDF + folder watcher | ~93% on first pass; ~99% with two PDFs straddling moves | drag-drop into one folder | medium | **selected** |

## How Eric uses it

```
~/Downloads/ryan-distribution-reports/         ← Eric drops latest PDF here
   Equipment Distribution Report as of 04.13.26.pdf
   Equipment Distribution Report as of 04.20.26.pdf   (newer)
   archive/
       Equipment Distribution Report as of 04.06.26.pdf
       Equipment Distribution Report as of 03.30.26.pdf
       ...
```

- Eric drops the newest PDF into the root folder.
- Pipeline scans on every run; archives older PDFs into `archive/` automatically.
- No deletion — archived PDFs are needed for From-side lookup.
- Optional: Outlook/Apple-Mail rule that auto-saves attachments matching `Equipment Distribution Report*.pdf` to that folder. Eliminates the drag-drop step entirely.

## Data extraction

The PDF has two sections:

1. **Regional pages** (~80% of doc): one section per Job/Location, asset list below. Format:
   ```
   Job: 3416.2- Uline H4 - Corporate Office - Pleasant Prairie, WI
       87-15404   2024 John Deere 299D 86" GP Bkt   PXBUC84E02064
       ...
   ```
2. **Consolidated index** (last ~20%): two-column dense layout, every asset with its current job#.

Parser uses ONLY the regional pages (single-column, deterministic). Index pages are skipped — the regional view already maps every asset; the index is a printed-report convenience for humans.

Detection: index begins at the first line matching `^\s*\d+-\d+\s+\S.*\s\d{3,5}\.\d-\s+\d+-\d+\s+` (asset followed by mid-line `<job#>-` followed by another asset).

### Output of one parse pass

```python
{
    "as_of": "2026-04-13",
    "source_pdf": "Equipment Distribution Report as of 04.13.26.pdf",
    "asset_to_job": {
        "87-15404": {"job": "3416.2", "city": "PLEASANT PRAIRIE", "project": "Uline H4 - Corporate Office"},
        "44-3382":  {"job": "3516.2", "city": "PLEASANT PRAIRIE", "project": "Highland Estates"},
        ...
    },
    "asset_to_shop": {
        "34-7424":  "ROLAND MACHINERY-FRANKSVILLE",
        "87-6082":  "KEVIN'S MACHINE SHOP",
        ...
    },
}
```

Stored as `state/distribution_cache/<YYYY-MM-DD>.json` — one file per parsed PDF, keyed by the as-of date. Cheap, debuggable, idempotent.

## Resolution algorithm (for each Axon CSV row)

```
Inputs from Axon:
    asset_num, csv_from_city, csv_to_city, axon_order_num, move_date

Step 1 — pick PDFs that bracket move_date:
    after_pdf  = newest PDF with as_of >= move_date   (where asset is now)
    before_pdf = newest PDF with as_of <  move_date   (where asset was before)

Step 2 — resolve TO:
    a) If asset_num in after_pdf.asset_to_job → "<job>-<city>"
    b) Elif asset_num in after_pdf.asset_to_shop → "<shop_label>"
    c) Elif axon_order_num in historical_xlsx_crosswalk → use historical To
    d) Else → write row to state/unresolved_jobs.csv, emit "<UNRESOLVED>-<csv_to_city>"

Step 3 — resolve FROM:
    same chain, but use before_pdf instead of after_pdf

Step 4 — sanity check (warn, don't block):
    If after_pdf says asset is at job X city Y but csv_to_city ≠ Y:
        log "asset moved >1 time between PDFs" (yo-yo case)
        still emit X-Y (PDF wins — it's downstream of any intermediate moves)
```

### Edge cases handled

- **No PDFs yet** (first install): fall through to historical Order# crosswalk, then unresolved.
- **Only one PDF** (week 1 of operation): use it for both From and To. Everything will look like "stayed at same job". Improves automatically once a second PDF lands.
- **Asset not in any PDF**: typically a rental, sub, or one-off attachment. Goes to `unresolved_jobs.csv` with full context for Eric to fill once.
- **PDF older than all moves in this batch**: warn but proceed; emit unresolved for asset-not-in-pdf cases.
- **Yo-yo move within one PDF interval**: PDF wins (it's the downstream snapshot). Log a warning so Eric can spot-check.

## Files to add / modify

### New files

| Path | Purpose |
|---|---|
| `execution/parse_distribution_pdf.py` | Parses one PDF → produces JSON cache file |
| `execution/distribution_lookup.py` | Loads all cached JSONs, exposes `lookup_at(asset, date)` |
| `state/distribution_cache/` | Directory of dated `<YYYY-MM-DD>.json` files (gitignored) |
| `state/unresolved_jobs.csv` | Eric-edits-this list of (asset, suggested job#, city) |
| `tests/test_distribution_parser.py` | Unit tests against the 04.13.26 PDF as a fixture |

### Modified files

| File | Change |
|---|---|
| `execution/build_ryan_report.py` | `parse_order_master` and `parse_new_ryan` no longer write `csv_from_city` / `csv_to_city` directly — they call `distribution_lookup.format_from_to()` |
| `execution/run_daily_append.py` | Pre-flight: scan `~/Downloads/ryan-distribution-reports/`, parse new PDFs, archive old ones |
| `app/main.py` | New "Distribution PDFs folder" picker in setup wizard, mirrors the existing browser/historical-CSV picker |
| `app/ui/index.html` | Same — UI surface for the folder picker + "X PDFs loaded, latest as of YYYY-MM-DD" status badge |
| `execution/browser_config.example.json` | Add `"distribution_pdf_dir": ""` config key |

## Out of scope (for this spec)

- Pulling the Distribution Report directly from Axon. We don't know if it lives there; Ryan emails it. Stay with the email/folder pattern until that's proven.
- Auto-emailing Ryan to ask for a fresh PDF. Manual cadence is fine.
- OCR — the PDF is text-based (Crystal Reports), `pdftotext -layout` gets clean output.
- The Master Equipment Distribution List that's separate from this Distribution Report — that's a different file, different ingestion. Tracked as a separate phase.

## Coverage estimate

Tested against today's 33 broken pipeline rows using the single 04.13.26 PDF:

- 27/29 assets found in PDF (93%)
- 2 unresolved (rental tag `13-7379`, attachment number `96-179`) — go to `unresolved_jobs.csv`
- 0/27 PDF-locations matched the CSV destination city, because the PDF is 3 weeks older than the moves. This is expected and *correct* — it tells us we'd need the post-move PDF to confirm where assets went. With Eric's drop-on-change cadence, a fresh PDF will be available within 1–2 days of any move.

## Questions for Eric (not blockers — defaults shown)

1. How often does Ryan generate this PDF? (Daily? On-change? Weekly?) Default assumption: drops in your inbox 1–3× per week.
2. Email rule possible? Filter `from:ryan-equipment* attachment:Equipment Distribution*.pdf` → save to a Downloads sub-folder. Default: drag-drop is fine for v1.
3. Are rentals (e.g. `13-7379`) ever in the report, or only Ryan-owned equipment? Default: rentals never appear → they always go to unresolved → Eric assigns once per rental.

## Implementation order

1. **Phase 1** — `parse_distribution_pdf.py` + JSON cache + tests (1 file). [~2 hrs]
2. **Phase 2** — `distribution_lookup.py` + integration into `build_ryan_report.py`. [~2 hrs]
3. **Phase 3** — Folder watcher in `run_daily_append.py` + archive logic. [~1 hr]
4. **Phase 4** — UI surface in `app/main.py` + `index.html`. [~1 hr]
5. **Phase 5** — Test on Andrew's machine end-to-end with both 04.13 PDF and a fresh post-May PDF (Eric to send). [~30 min]

Total: ~6.5 hours of focused work. Phase 1 alone is shippable as a CLI utility for Eric to run today if the desktop app is blocked.
