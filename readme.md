# Mail List Merge

Merges multiple mailing-list CSV files, normalizes names/addresses, removes invalid rows, deduplicates records, and writes a cleaned output.

## Install

```bash
pip install -r requirements.txt
```

## Run

Default run (reads `inputs/*.csv`):

```bash
python3 main.py
```

Run with explicit options:

```bash
python3 main.py \
  --input-glob "inputs/*.csv" \
  --output-file "output.csv" \
  --combined-file "combined.csv" \
  --dedupe-mode person
```

## CLI Options

- `--input-glob`
  - Glob pattern for input CSV files.
  - Default: `inputs/*.csv`
- `--output-file`
  - Path to cleaned, pre-dedupe output.
  - Default: `output.csv`
- `--combined-file`
  - Path to final deduped output.
  - Default: `combined.csv`
- `--dedupe-mode`
  - `person`: dedupe by `first_name + last_name + normalized address + zip` (fallback to normalized full name if name parts are missing).
  - `household`: dedupe by `last_name + normalized address + zip` (fallback to normalized full name if last name is missing).
  - Default: `person`

## Input Support

The script supports files with:

- `name` or `fullname`
- optional `first` / `last` (or common variants)
- `address`, optional `address2`
- `city`, `st` / `state`, `zip` / `zip5`

It also handles:

- non-UTF8 encodings (`utf-8-sig`, `cp1252`, `latin-1`)
- files with non-data preamble rows before headers
- continuation address lines

## Output Columns

Final output (`combined.csv` by default):

- `first_name`
- `last_name`
- `credentials`
- `name`
- `address`
- `address2`
- `city`
- `st`
- `zip`

## Counters Printed

Each run prints:

- record count for each input file
- total input records
- final output record count
- total records pruned
- records dropped for missing address/zip
- duplicate records removed
- records dropped for missing state

## Notes

- Empty/placeholder names, addresses, and ZIPs are removed.
- State is normalized to 2-letter code where possible.
