from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

TARGET_HEADER_ROW_1 = [
    "",
    "Truck",
    "",
    "By",
    "Date",
    "",
    "Hour",
    "Machine",
    "From",
    "To",
    "Order #",
    "",
    "",
    "",
    "",
    "",
]
TARGET_HEADER_ROW_2 = [
    "",
    "#",
    "PO#",
    "Whom",
    "Move",
    "Machine#",
    "Meter",
    "Description",
    "Job#  ",
    "Job#                          ",
    "",
    "",
    "",
    "",
    "",
    "",
]
SERIAL_COLUMNS = ["Serial #", "Serial #2", "Serial #3", "Serial #4"]
IGNORED_SERIAL_VALUES = {"", "0", "0.0", "00", "o", "na", "n/a", "none", "null"}
ORDER_MASTER_NAME = "Order Master Report"
NEW_RYAN_NAME = "New RYAN"


@dataclass
class OrderMasterRecord:
    order_number: str
    move_date: str
    origin: str
    destination: str
    driver_name: str


@dataclass
class GeneratedRow:
    po: str
    driver_initials: str
    move_date: str
    machine: str
    meter: str
    description: str
    origin: str
    destination: str
    order_number: str


def read_csv_rows(path: Path) -> list[list[str]]:
    # Handle xlsx files natively. Reads only the active sheet — for
    # multi-sheet historical workbooks, prefer read_historical_rows below.
    if path.suffix.lower() in (".xlsx", ".xls"):
        try:
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([_xlsx_cell_to_str(cell) for cell in row])
            wb.close()
            return rows
        except ImportError:
            raise RuntimeError(
                f"Cannot read {path.name}: openpyxl is required for xlsx files. "
                f"Install it with: pip install openpyxl"
            )
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return list(csv.reader(handle))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("csv", b"", 0, 1, f"Unable to decode CSV file: {path}")


def _xlsx_cell_to_str(cell) -> str:
    """Render an openpyxl cell value as a CSV-equivalent string.

    Datetimes are written as the same '%-d-%b' format the CSV pipeline emits
    (e.g. '6-Jan'), so dedup keys built off these strings line up with rows
    produced from CSV inputs.
    """
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        try:
            return cell.strftime("%-d-%b")
        except ValueError:
            # Windows: %-d not supported; %#d is the equivalent.
            return cell.strftime("%#d-%b")
    return str(cell)


def read_historical_rows(path: Path) -> list[list[str]]:
    """Load rows for the historical equipment lookup.

    For an .xlsx workbook, unions rows from every sheet whose name is a 4-digit
    year (e.g. '2016' through '2026'), so the serial -> description / meter
    lookup sees the full equipment history that drives `Ryan` description
    fill-in. Falls back to the single-sheet read_csv_rows for CSV inputs and
    for xlsx workbooks that have no year-named sheets.
    """
    if path.suffix.lower() not in (".xlsx", ".xls"):
        return read_csv_rows(path)

    try:
        from openpyxl import load_workbook
    except ImportError:
        raise RuntimeError(
            f"Cannot read {path.name}: openpyxl is required for xlsx files. "
            f"Install it with: pip install openpyxl"
        )

    wb = load_workbook(path, read_only=True, data_only=True)
    year_sheets = [name for name in wb.sheetnames if name.isdigit() and len(name) == 4]
    if not year_sheets:
        wb.close()
        return read_csv_rows(path)

    rows: list[list[str]] = []
    for name in year_sheets:
        ws = wb[name]
        for row in ws.iter_rows(values_only=True):
            rows.append([_xlsx_cell_to_str(cell) for cell in row])
    wb.close()
    return rows


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_serial(value: str) -> str:
    value = normalize_space(value)
    if not value:
        return ""
    if value.lower() in IGNORED_SERIAL_VALUES:
        return ""
    return value.replace("  ", " ")


def normalize_meter(value: str, default: str = "N/A") -> str:
    value = normalize_space(value)
    if not value or value.lower() in IGNORED_SERIAL_VALUES:
        return default
    return value


def format_move_date(value: str) -> str:
    value = normalize_space(value)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%-d-%b")
        except ValueError:
            continue
    return value


def derive_driver_initials(driver_name: str) -> str:
    driver_name = normalize_space(driver_name)
    if not driver_name:
        return ""
    if "," in driver_name:
        last, first = [normalize_space(part) for part in driver_name.split(",", 1)]
        return (first[:1] + last[:1]).upper()
    parts = driver_name.split(" ")
    if len(parts) >= 2:
        return (parts[0][:1] + parts[-1][:1]).upper()
    return driver_name[:2].upper()


def discover_latest_file(input_dir: Path, prefix: str) -> Path:
    matches = sorted(
        input_dir.glob(f"{prefix}*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not matches:
        raise FileNotFoundError(
            f"No file matching '{prefix}*.csv' found in {input_dir}"
        )
    return matches[0]


def parse_order_master(path: Path) -> dict[str, OrderMasterRecord]:
    rows = read_csv_rows(path)
    start_index = (
        next(i for i, row in enumerate(rows) if row and row[0] == "Order#") + 1
    )
    records = {}
    current = None
    for row in rows[start_index:]:
        padded = row + [""] * (10 - len(row))
        first = normalize_space(padded[0])
        location = normalize_space(padded[2])
        if first.isdigit():
            current = OrderMasterRecord(
                first,
                format_move_date(padded[1]),
                location,
                "",
                normalize_space(padded[4]),
            )
            records[first] = current
            continue
        if not current:
            continue
        if first:
            current = None
            continue
        if (
            not current.destination
            and location
            and location
            not in {
                "Freight Amount",
                "Other Charges",
                "Total Billed",
                "TotalBilled",
                "Total Payout",
                "Net Revenue",
            }
        ):
            current.destination = location
    return records


def normalize_location(value: str) -> str:
    """Stopgap From/To formatter.

    Customer wants `<job#>-<CITY>` (e.g. `2503.2-HOFFMAN ESTATES`). Until the
    Distribution PDF parser ships the asset->job# crosswalk, strip the trailing
    state code (`, IL` / `, WI`) and uppercase. So Axon's `"HOFFMAN ESTATES, IL"`
    becomes `"HOFFMAN ESTATES"` instead of being shipped to the customer with
    state codes that no other row has. The job# prefix gets added back when
    the Distribution PDF lookup lands.
    """
    s = normalize_space(value or "")
    if not s:
        return ""
    # Strip trailing ", ST" (2-letter state) — match real Axon output.
    s = re.sub(r",\s*[A-Z]{2}\s*$", "", s, flags=re.IGNORECASE)
    return s.upper()


def parse_historical_orders(path: Path) -> dict[str, tuple[str, str]]:
    """Build Order# -> (from_str, to_str) crosswalk from the historical xlsx.

    Reads every year-sheet and records the From/To values seen for each
    Order#. Used as the primary lookup for From/To formatting — when a
    repeat order shows up in Axon, we use the exact From/To string Eric
    has used historically (which already has the `<job#>-<CITY>` format).
    Falls back to normalize_location() for orders not seen historically.
    """
    crosswalk: dict[str, tuple[str, str]] = {}
    rows = read_historical_rows(path)
    for row in rows:
        padded = row + [""] * 11
        order = normalize_space(padded[10])
        if not order.isdigit():
            continue
        from_v = normalize_space(padded[8])
        to_v = normalize_space(padded[9])
        if from_v or to_v:
            crosswalk[order] = (from_v, to_v)
    return crosswalk


def parse_historical_ryan(path: Path) -> tuple[dict[str, dict[str, str]], Counter[str]]:
    rows = read_historical_rows(path)
    description_counts = defaultdict(Counter)
    meter_counts = defaultdict(Counter)
    for row in rows:
        padded = row + [""] * 11
        if not normalize_space(padded[0]).isdigit() or not normalize_space(padded[10]):
            continue
        serial = normalize_serial(padded[5])
        if not serial:
            continue
        desc = normalize_space(padded[7])
        meter = normalize_meter(padded[6])
        if desc:
            description_counts[serial][desc] += 1
        if meter:
            meter_counts[serial][meter] += 1
    lookup = {}
    for serial, counts in description_counts.items():
        lookup[serial] = {
            "description": counts.most_common(1)[0][0],
            "meter": meter_counts[serial].most_common(1)[0][0]
            if meter_counts[serial]
            else "N/A",
        }
    return lookup, Counter({s: sum(c.values()) for s, c in description_counts.items()})


def parse_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    rows = read_csv_rows(path)
    if not rows:
        return {}
    header = rows[0]
    overrides = {}
    for raw in rows[1:]:
        row = dict(zip(header, raw + [""] * (len(header) - len(raw))))
        serial = normalize_serial(row.get("serial", ""))
        if serial:
            overrides[serial] = {
                "description": normalize_space(row.get("description", "")),
                "meter": normalize_meter(row.get("meter", "N/A")),
            }
    return overrides


def build_serial_lookup(
    generated_seed: dict[str, dict[str, str]],
    historical: dict[str, dict[str, str]],
    overrides: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    lookup = {**generated_seed, **historical}
    lookup.update(overrides)
    return lookup


def parse_new_ryan(path: Path) -> list[dict[str, str]]:
    rows = read_csv_rows(path)
    if not rows:
        return []
    header = rows[0]
    return [
        dict(zip(header, row + [""] * (len(header) - len(row)))) for row in rows[1:]
    ]


def resolve_description(
    serial: str,
    serial_index: int,
    row: dict[str, str],
    lookup: dict[str, dict[str, str]],
) -> str:
    commodity = normalize_space(row.get("Order Commodity", ""))
    if serial_index == 0 and commodity:
        return commodity
    return lookup.get(serial, {}).get("description", "")


def resolve_meter(
    serial: str,
    serial_index: int,
    row: dict[str, str],
    lookup: dict[str, dict[str, str]],
) -> str:
    if serial_index == 0:
        return normalize_meter(row.get("Hour Meter", ""))
    return lookup.get(serial, {}).get("meter", "N/A") or "N/A"


def collect_generated_rows(
    new_rows: list[dict[str, str]],
    order_master: dict[str, OrderMasterRecord],
    serial_lookup: dict[str, dict[str, str]],
    order_crosswalk: dict[str, tuple[str, str]] | None = None,
) -> tuple[list[GeneratedRow], list[dict[str, str]]]:
    generated = []
    unresolved = []
    crosswalk = order_crosswalk or {}
    for row in new_rows:
        if normalize_space(row.get("Bill To Name", "")) != "Ryan, Inc.":
            continue
        order_number = normalize_space(row.get("Order#", ""))
        if not order_number:
            continue
        master = order_master.get(order_number)
        if not master:
            continue

        # From/To formatting: prefer the historical crosswalk (gives correct
        # <job#>-<CITY> for repeat orders); fall back to a state-stripped,
        # uppercase city for brand-new orders. Until the Distribution PDF
        # parser lands, this is the best we can do without manual entry.
        cw = crosswalk.get(order_number)
        if cw and (cw[0] or cw[1]):
            from_str, to_str = cw
        else:
            from_str = normalize_location(master.origin)
            to_str = normalize_location(master.destination)

        for index, column in enumerate(SERIAL_COLUMNS):
            serial = normalize_serial(row.get(column, ""))
            if not serial:
                continue
            description = resolve_description(serial, index, row, serial_lookup)
            meter = resolve_meter(serial, index, row, serial_lookup)
            if not description:
                unresolved.append(
                    {
                        "order_number": order_number,
                        "serial": serial,
                        "source_column": column,
                        "issue": "Missing description",
                        "suggested_description": "",
                    }
                )
                continue
            generated.append(
                GeneratedRow(
                    normalize_space(row.get("Customer PO#", "")),
                    derive_driver_initials(master.driver_name),
                    master.move_date,
                    serial,
                    meter,
                    description,
                    from_str,
                    to_str,
                    order_number,
                )
            )
    return generated, unresolved


def generated_row_key(row: GeneratedRow) -> tuple[str, str, str, str, str]:
    return (row.order_number, row.machine, row.move_date, row.origin, row.destination)


def parse_existing_target_rows(
    path: Path,
) -> tuple[list[list[str]], set[tuple[str, str, str, str, str]], set[str], int]:
    rows = read_csv_rows(path)
    preserved = []
    seen = set()
    seen_orders = set()
    max_line = 0
    for row in rows:
        preserved.append(row)
        padded = row + [""] * 11
        if normalize_space(padded[0]).isdigit():
            max_line = max(max_line, int(normalize_space(padded[0])))
            seen_orders.add(normalize_space(padded[10]))
            seen.add(
                (
                    normalize_space(padded[10]),
                    normalize_serial(padded[5]),
                    normalize_space(padded[4]),
                    normalize_space(padded[8]),
                    normalize_space(padded[9]),
                )
            )
    return preserved, seen, seen_orders, max_line


def filter_new_orders(
    generated_rows: list[GeneratedRow], append_to: Path
) -> tuple[list[GeneratedRow], int]:
    _, _, seen_orders, _ = parse_existing_target_rows(append_to)
    filtered = [row for row in generated_rows if row.order_number not in seen_orders]
    return filtered, len(generated_rows) - len(filtered)


def filter_unresolved_new_orders(
    unresolved: list[dict[str, str]], append_to: Path
) -> list[dict[str, str]]:
    _, _, seen_orders, _ = parse_existing_target_rows(append_to)
    return [row for row in unresolved if row.get("order_number", "") not in seen_orders]


def write_target_csv(path: Path, generated_rows: Iterable[GeneratedRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TARGET_HEADER_ROW_1)
        writer.writerow(TARGET_HEADER_ROW_2)
        for idx, row in enumerate(generated_rows, start=1):
            writer.writerow(
                [
                    idx,
                    row.driver_initials,
                    row.po,
                    "DR",
                    row.move_date,
                    row.machine,
                    row.meter,
                    row.description,
                    row.origin,
                    row.destination,
                    row.order_number,
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )


def write_append_csv(
    path: Path, append_to: Path, generated_rows: list[GeneratedRow]
) -> tuple[int, int]:
    preserved, seen, _, max_line = parse_existing_target_rows(append_to)
    skipped = 0
    new_rows = []
    for row in generated_rows:
        if generated_row_key(row) in seen:
            skipped += 1
            continue
        max_line += 1
        new_rows.append(
            [
                max_line,
                row.driver_initials,
                row.po,
                "DR",
                row.move_date,
                row.machine,
                row.meter,
                row.description,
                row.origin,
                row.destination,
                row.order_number,
                "",
                "",
                "",
                "",
                "",
            ]
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for row in preserved + new_rows:
            writer.writerow(row)
    return len(new_rows), skipped


def write_lookup_csv(
    path: Path, lookup: dict[str, dict[str, str]], frequencies: Counter[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["serial", "description", "meter", "historical_matches"])
        for serial in sorted(lookup):
            writer.writerow(
                [
                    serial,
                    lookup[serial].get("description", ""),
                    lookup[serial].get("meter", "N/A"),
                    frequencies.get(serial, 0),
                ]
            )


def write_unresolved_csv(path: Path, unresolved: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "order_number",
                "serial",
                "source_column",
                "issue",
                "suggested_description",
            ],
        )
        writer.writeheader()
        writer.writerows(unresolved)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a Ryan-format report from Axon exports."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--append-to")
    parser.add_argument("--append-output")
    parser.add_argument("--only-new-orders", action="store_true")
    parser.add_argument("--order-master")
    parser.add_argument("--new-ryan")
    parser.add_argument("--historical-ryan")
    parser.add_argument("--state-dir")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        state_dir = Path(__file__).resolve().parents[1] / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    order_master_path = (
        Path(args.order_master)
        if args.order_master
        else discover_latest_file(input_dir, ORDER_MASTER_NAME)
    )
    new_ryan_path = (
        Path(args.new_ryan)
        if args.new_ryan
        else discover_latest_file(input_dir, NEW_RYAN_NAME)
    )
    historical_path = (
        Path(args.historical_ryan)
        if args.historical_ryan
        else input_dir / "2026 RYAN MOVES.csv"
    )

    order_master = parse_order_master(order_master_path)
    new_rows = parse_new_ryan(new_ryan_path)
    historical_lookup, historical_freq = parse_historical_ryan(historical_path)
    order_crosswalk = parse_historical_orders(historical_path)
    serial_lookup = build_serial_lookup(
        parse_overrides(state_dir / "generated_serial_lookup.csv"),
        historical_lookup,
        parse_overrides(state_dir / "serial_overrides.csv"),
    )
    generated_rows, unresolved = collect_generated_rows(
        new_rows, order_master, serial_lookup, order_crosswalk
    )

    skipped_existing_orders = 0
    if args.append_to and args.only_new_orders:
        generated_rows, skipped_existing_orders = filter_new_orders(
            generated_rows, Path(args.append_to)
        )
        unresolved = filter_unresolved_new_orders(unresolved, Path(args.append_to))

    generated_rows.sort(key=lambda r: (r.move_date, r.order_number, r.machine))
    write_target_csv(Path(args.output), generated_rows)
    write_lookup_csv(
        state_dir / "generated_serial_lookup.csv", serial_lookup, historical_freq
    )
    write_unresolved_csv(state_dir / "unresolved_serials.csv", unresolved)

    print(f"Generated rows: {len(generated_rows)}")
    print(f"Unresolved rows: {len(unresolved)}")
    if skipped_existing_orders:
        print(f"Skipped rows from existing orders: {skipped_existing_orders}")

    if args.append_to and args.append_output:
        appended, skipped = write_append_csv(
            Path(args.append_output), Path(args.append_to), generated_rows
        )
        print(f"Appended rows: {appended}")
        print(f"Skipped existing rows: {skipped}")


if __name__ == "__main__":
    main()
