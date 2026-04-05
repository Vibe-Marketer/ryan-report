# Directives

## Goal

Produce a Ryan-format CSV from Axon exports with the least manual work possible.

## Source Priority

1. `New RYAN ...csv`
   - source of `Order#`, `Customer PO#`, `Hour Meter`, `Order Commodity`, and `Serial #1-4`
2. `Order Master Report ...csv`
   - source of move date, origin, destination, and driver
3. Historical Ryan CSV
   - source of serial-to-description mappings for secondary serials
4. `state/serial_overrides.csv`
   - operator-maintained corrections for serials not discoverable elsewhere

## Field Mapping

- Ryan `PO#` = Axon `Customer PO#`
- Ryan `Machine#` = Axon `Serial #`, `Serial #2`, `Serial #3`, `Serial #4`
- Ryan `Meter`
  - primary serial uses Axon `Hour Meter`
  - secondary serials default to `N/A` unless an override says otherwise
- Ryan `Description`
  - primary serial uses Axon `Order Commodity`
  - secondary serials use historical Ryan lookup first, then manual overrides
- Ryan `Date of Move` = `Order Master Report -> End Date`
- Ryan `From` = first location line in Order Master block
- Ryan `To` = second location line in Order Master block
- Ryan `Whom` = `DR`
- Ryan `Truck #` = initials derived from the driver name in Order Master

## Guardrails

- Never use Axon `Unit #` for Ryan `Machine#`
- Treat `0`, blank, `NA`, and `N/A` as empty serials except where the literal value is part of the serial text
- If a secondary serial has no known description, emit it to `state/unresolved_serials.csv`
- Do not silently invent attachment descriptions

## Self-Annealing Rules

- Build a generated serial lookup from historical Ryan rows every run
- Apply `serial_overrides.csv` after generated lookup so operator corrections win
- Emit unresolved serials after every run so the lookup can improve over time
- Re-running after adding overrides should reduce unresolved rows without code changes
