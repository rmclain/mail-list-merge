import argparse
import csv
import glob
import re
from pathlib import Path

import pandas as pd
import pgeocode

TARGET_COLUMNS = ["first_name", "last_name", "credentials", "name", "address", "address2", "city", "st", "zip"]
COLUMN_ALIASES = {
    "name": ["name", "fullname"],
    "first": ["first", "firstname", "first_name"],
    "last": ["last", "lastname", "last_name", "surname"],
    "address": ["address"],
    "address2": ["address2"],
    "city": ["city"],
    "st": ["st", "state"],
    "zip": ["zip", "zip5"],
}
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

ABBREVIATIONS = {
    r"\b(street|st)\b": "st",
    r"\b(avenue|ave)\b": "ave",
    r"\b(road|rd)\b": "rd",
    r"\b(drive|dr)\b": "dr",
    r"\b(court|ct)\b": "ct",
    r"\b(boulevard|blvd)\b": "blvd",
    r"\b(lane|ln)\b": "ln",
    r"\b(place|pl)\b": "pl",
    r"\b(terrace|ter)\b": "ter",
    r"\b(parkway|pkwy)\b": "pkwy",
    r"\b(circle|cir)\b": "cir",
    r"\b(apartment|apt|suite|ste|unit)\b": "unit",
}

MISSING_TOKENS = {"", "na", "n/a", "none", "null", "unknown", "nan", "-", "--"}
NAME_DROP_TOKENS = {
    "mr",
    "mrs",
    "ms",
    "miss",
    "dr",
    "prof",
    "md",
    "do",
    "phd",
    "dds",
    "dmd",
    "pa",
    "np",
    "dnp",
    "aprn",
    "rn",
    "esq",
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
}

NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
NAME_PREFIXES = {"mr", "mrs", "ms", "miss", "dr", "prof"}
NAME_CREDENTIALS = {
    "md",
    "do",
    "phd",
    "dds",
    "dmd",
    "pa",
    "np",
    "dnp",
    "aprn",
    "rn",
    "esq",
    "facs",
    "mph",
    "mba",
}

STATE_ABBR = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def read_rows_with_fallback(path: str):
    last_error = None
    for encoding in ENCODINGS:
        try:
            with open(path, "r", encoding=encoding, newline="") as f:
                return list(csv.reader(f)), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise UnicodeDecodeError(
        "utf-8",
        b"",
        0,
        1,
        f"Unable to decode {path} with supported encodings: {ENCODINGS}. Last error: {last_error}",
    )


def find_header_index(rows):
    for i, row in enumerate(rows):
        normalized = {normalize_header(cell) for cell in row if cell and cell.strip()}
        if {"name", "address"}.issubset(normalized) or {"fullname", "address", "city"}.issubset(normalized):
            return i
    return None


def rows_to_dataframe(rows, header_idx: int) -> pd.DataFrame:
    header = rows[header_idx]
    width = len(header)
    data = [r[:width] + [""] * max(0, width - len(r)) for r in rows[header_idx + 1 :]]
    df = pd.DataFrame(data, columns=header).fillna("")
    # Drop fully empty rows early.
    df = df[(df.astype(str).apply(lambda col: col.str.strip())).ne("").any(axis=1)]
    return df


def first_matching_column(columns, aliases):
    normalized_to_original = {normalize_header(c): c for c in columns}
    for alias in aliases:
        candidate = normalized_to_original.get(normalize_header(alias))
        if candidate:
            return candidate
    return None


def standardize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {c: "" for c in ["name", "first", "last", "address", "address2", "city", "st", "zip"]}, index=df.index
    )
    for target, aliases in COLUMN_ALIASES.items():
        if target in out.columns:
            source = first_matching_column(df.columns, aliases)
            if source:
                out[target] = df[source].astype(str)

    first_col = first_matching_column(df.columns, COLUMN_ALIASES["first"])
    last_col = first_matching_column(df.columns, COLUMN_ALIASES["last"])
    if first_col and last_col:
        merged = (df[first_col].astype(str).str.strip() + " " + df[last_col].astype(str).str.strip()).str.strip()
        out["name"] = out["name"].mask(out["name"].str.strip() == "", merged)

    out = out.apply(lambda col: col.str.strip())

    # Handle occasional continuation lines that contain only extra address text.
    continuation_mask = (
        out["name"].eq("")
        & out["city"].eq("")
        & out["st"].eq("")
        & out["zip"].eq("")
        & out["address"].ne("")
    )
    for idx in out.index[continuation_mask]:
        prev_idx = idx - 1
        if prev_idx in out.index:
            extra = out.at[idx, "address"]
            if extra:
                current = out.at[prev_idx, "address2"]
                out.at[prev_idx, "address2"] = f"{current} {extra}".strip()

    out = out[~continuation_mask].copy()
    return out


def is_missing_text(value: str) -> bool:
    token = str(value or "").strip().lower()
    return token in MISSING_TOKENS


def normalize_name(name: str) -> str:
    if not name:
        return ""
    text = str(name).strip()
    if is_missing_text(text):
        return ""
    # Normalize "Last, First" style to improve parsing consistency.
    if "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) >= 2:
            text = f"{parts[1]} {parts[0]}"

    text = re.sub(r"[^a-zA-Z0-9' -]", " ", text.lower())
    tokens = [t for t in re.split(r"\s+", text) if t]
    tokens = [t for t in tokens if t not in NAME_DROP_TOKENS]
    return " ".join(tokens)


def normalize_name_display(name: str) -> str:
    key = normalize_name(name)
    return " ".join(part.capitalize() for part in key.split())


def smart_title(text: str) -> str:
    if not text:
        return ""
    return " ".join(part[:1].upper() + part[1:].lower() for part in text.split())


def split_name_parts(name: str) -> tuple[str, str, str]:
    text = str(name or "").strip()
    if is_missing_text(text):
        return "", "", ""

    lowered = re.sub(r"[^a-zA-Z0-9,' -]", " ", text.lower())
    lowered = re.sub(r"\s+", " ", lowered).strip()

    def tokenize(segment: str) -> list[str]:
        return [t.strip(".") for t in re.split(r"\s+", segment) if t.strip(".")]

    def extract_credentials(tokens: list[str]) -> tuple[list[str], list[str]]:
        creds = [t for t in tokens if t in NAME_CREDENTIALS]
        keep = [t for t in tokens if t not in NAME_CREDENTIALS]
        return keep, creds

    first_name = ""
    last_name = ""
    all_credentials: list[str] = []

    if "," in lowered:
        parts = [p.strip() for p in lowered.split(",") if p.strip()]
        last_tokens = tokenize(parts[0]) if parts else []
        first_tokens = tokenize(parts[1]) if len(parts) > 1 else []

        last_tokens, creds_last = extract_credentials(last_tokens)
        first_tokens, creds_first = extract_credentials(first_tokens)
        all_credentials.extend(creds_last + creds_first)

        first_tokens = [t for t in first_tokens if t not in NAME_PREFIXES and t not in NAME_SUFFIXES]
        last_tokens = [t for t in last_tokens if t not in NAME_PREFIXES and t not in NAME_SUFFIXES]
        first_name = " ".join(first_tokens)
        last_name = " ".join(last_tokens)
    else:
        tokens = tokenize(lowered)
        tokens, creds = extract_credentials(tokens)
        all_credentials.extend(creds)
        tokens = [t for t in tokens if t not in NAME_PREFIXES and t not in NAME_SUFFIXES]
        if len(tokens) == 1:
            first_name = tokens[0]
            last_name = ""
        elif len(tokens) >= 2:
            first_name = tokens[0]
            last_name = tokens[-1]

    first_name = smart_title(first_name)
    last_name = smart_title(last_name)
    credentials_text = ",".join(sorted(set(c.upper() for c in all_credentials)))
    return first_name, last_name, credentials_text


def normalize_address(address: str, address2: str = "") -> str:
    left = str(address or "").strip()
    right = str(address2 or "").strip()
    text = f"{left} {right}".strip()
    if not text or is_missing_text(text):
        return ""
    cleaned = text.lower()
    for pattern, replacement in ABBREVIATIONS.items():
        cleaned = re.sub(pattern, replacement, cleaned)
    cleaned = cleaned.replace("#", " unit ")
    cleaned = re.sub(r"[^a-z0-9 ]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_address_display(address: str) -> str:
    text = str(address or "").strip()
    if is_missing_text(text):
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.title()


def format_zip(zip_code: str) -> str:
    if not zip_code:
        return ""
    zip_code = str(zip_code).split(".")[0]
    zip_code = re.sub(r"-.*", "", zip_code)
    digits = re.sub(r"\D", "", zip_code)
    if not digits:
        return ""
    return digits.zfill(5)[:5]


def normalize_state(value: str) -> str:
    if not value:
        return ""
    state = value.strip().lower()
    if len(state) == 2 and state.isalpha():
        return state.upper()
    return STATE_ABBR.get(state, value.strip().upper())


def combine_csv_files(input_files, output_file, combined_file, dedupe_mode="person"):
    if not input_files:
        raise FileNotFoundError("No CSV files found in the inputs directory.")

    dataframes = []
    input_counts: list[tuple[str, int, str]] = []
    for file in input_files:
        rows, encoding = read_rows_with_fallback(file)
        header_idx = find_header_index(rows)
        if header_idx is None:
            raise ValueError(f"Could not find a recognizable header row in: {file}")
        raw_df = rows_to_dataframe(rows, header_idx)
        normalized_df = standardize_dataframe(raw_df)
        dataframes.append(normalized_df)
        input_counts.append((Path(file).name, len(normalized_df), encoding))
        print(f"Loaded {Path(file).name} using {encoding} ({len(normalized_df)} rows)")

    combined_df = pd.concat(dataframes, ignore_index=True)

    total_records = len(combined_df)

    combined_df["zip"] = combined_df["zip"].map(format_zip)
    combined_df["name_key"] = combined_df["name"].map(normalize_name)
    name_parts = combined_df["name"].map(split_name_parts)
    combined_df["first_name"] = combined_df["first"].where(
        combined_df["first"].str.strip() != "", name_parts.map(lambda x: x[0])
    )
    combined_df["last_name"] = combined_df["last"].where(
        combined_df["last"].str.strip() != "", name_parts.map(lambda x: x[1])
    )
    combined_df["credentials"] = name_parts.map(lambda x: x[2])
    combined_df["first_name_key"] = combined_df["first_name"].str.lower().str.strip()
    combined_df["last_name_key"] = combined_df["last_name"].str.lower().str.strip()
    combined_df["address_key"] = combined_df.apply(
        lambda row: normalize_address(row["address"], row["address2"]), axis=1
    )

    records_before_dropna = len(combined_df)
    combined_df = combined_df[
        (combined_df["address_key"] != "")
        & (combined_df["zip"] != "")
        & (combined_df["name_key"] != "")
    ].copy()
    records_dropped_due_to_na = records_before_dropna - len(combined_df)

    output_cols = ["first_name", "last_name", "credentials", "name", "address", "address2", "city", "st", "zip"]
    combined_df[output_cols].to_csv(output_file, index=False)

    if dedupe_mode == "household":
        has_last = combined_df["last_name_key"] != ""
        with_last = combined_df[has_last].drop_duplicates(
            subset=["last_name_key", "address_key", "zip"]
        )
        without_last = combined_df[~has_last].drop_duplicates(
            subset=["name_key", "address_key", "zip"]
        )
        combined_df = pd.concat([with_last, without_last], ignore_index=True)
    else:
        has_parts = (combined_df["first_name_key"] != "") & (combined_df["last_name_key"] != "")
        with_parts = combined_df[has_parts].drop_duplicates(
            subset=["first_name_key", "last_name_key", "address_key", "zip"]
        )
        without_parts = combined_df[~has_parts].drop_duplicates(
            subset=["name_key", "address_key", "zip"]
        )
        combined_df = pd.concat([with_parts, without_parts], ignore_index=True)

    records_after_duplicates = len(combined_df)
    duplicates_removed = total_records - records_dropped_due_to_na - records_after_duplicates

    combined_df.sort_values(by="zip", inplace=True)

    nomi = pgeocode.Nominatim("us")
    unique_zips = combined_df["zip"].dropna().unique()
    zip_map = {}
    for z in unique_zips:
        location = nomi.query_postal_code(z)
        if location is not None and pd.notna(location.state_code):
            zip_map[z] = (str(location.place_name), str(location.state_code))
        else:
            zip_map[z] = ("", "")

    city_state_df = pd.DataFrame(
        combined_df["zip"].map(zip_map).tolist(),
        index=combined_df.index,
        columns=["city_from_zip", "st_from_zip"],
    )
    combined_df = pd.concat([combined_df, city_state_df], axis=1)

    combined_df["city"] = combined_df["city_from_zip"].where(combined_df["city"].str.strip() == "", combined_df["city"])
    combined_df["st"] = combined_df["st_from_zip"].where(combined_df["st"].str.strip() == "", combined_df["st"])
    combined_df["st"] = combined_df["st"].map(normalize_state)

    records_before_state_drop = len(combined_df)
    combined_df = combined_df[combined_df["st"].str.strip() != ""].copy()
    records_dropped_due_to_no_state = records_before_state_drop - len(combined_df)

    combined_df["first_name"] = combined_df["first_name"].str.title()
    combined_df["last_name"] = combined_df["last_name"].str.title()
    combined_df["name"] = (
        combined_df["first_name"].str.strip() + " " + combined_df["last_name"].str.strip()
    ).str.strip()
    combined_df["address"] = combined_df["address"].map(normalize_address_display)
    combined_df["address2"] = combined_df["address2"].map(normalize_address_display)
    combined_df["city"] = combined_df["city"].str.title()
    combined_df["st"] = combined_df["st"].str.upper()
    combined_df["credentials"] = combined_df["credentials"].str.upper()

    combined_df = combined_df[TARGET_COLUMNS].reset_index(drop=True)
    combined_df.to_csv(combined_file, index=False)
    final_output_records = len(combined_df)
    total_pruned = total_records - final_output_records

    print("\nInput File Counts:")
    for name, count, encoding in input_counts:
        print(f"- {name}: {count} records ({encoding})")
    print(f"Total input records: {total_records}")
    print(f"Final output records ({combined_file}): {final_output_records}")
    print(f"Total records pruned: {total_pruned}")
    print(f"Dedupe mode: {dedupe_mode}")
    print(f"Total records before removing duplicates: {total_records}")
    print(f"Total records after removing duplicates: {final_output_records}")
    print(f"Number of duplicate records removed: {duplicates_removed}")
    print(f"Number of records dropped due to missing address or zip: {records_dropped_due_to_na}")
    print(f"Number of records dropped due to missing state: {records_dropped_due_to_no_state}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Merge and normalize mailing-list CSV files."
    )
    parser.add_argument(
        "--input-glob",
        default="inputs/*.csv",
        help="Glob pattern for input CSV files (default: inputs/*.csv).",
    )
    parser.add_argument(
        "--output-file",
        default="output.csv",
        help="Path for cleaned pre-dedupe output (default: output.csv).",
    )
    parser.add_argument(
        "--combined-file",
        default="combined.csv",
        help="Path for final deduped output (default: combined.csv).",
    )
    parser.add_argument(
        "--dedupe-mode",
        default="person",
        choices=["person", "household"],
        help="person=first+last+address+zip, household=last+address+zip (default: person).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    input_files = glob.glob(args.input_glob)
    combine_csv_files(input_files, args.output_file, args.combined_file, dedupe_mode=args.dedupe_mode)
