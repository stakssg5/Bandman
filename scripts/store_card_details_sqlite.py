#!/usr/bin/env python3
"""
Store extracted payment card details from front/back text into SQLite.

- Merges front/back text (from --front-text/--front-file and --back-text/--back-file)
- Reuses the existing extract_card_info.extract_card_info() logic
- Creates the SQLite database/table if they do not exist
- Inserts a row with normalized fields and the full extraction JSON

Examples:
  python3 scripts/store_card_details_sqlite.py \
    --front-text "(Jane Doe) 4111 1111 1111 1111" \
    --back-text "12/29 CVV 123 ZIP 94105" \
    --db data/cards.db --pretty

Security note:
- By default, only masked PAN and last4 are stored. To store the full PAN
  in the database (not recommended), pass --store-full-pan explicitly.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Make repository root importable so we can import extract_card_info
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from extract_card_info import extract_card_info  # type: ignore
except Exception as e:  # pragma: no cover
    print(
        f"Error: failed to import extract_card_info from repo root: {e}",
        file=sys.stderr,
    )
    sys.exit(2)


@dataclass
class Inputs:
    front_text: str
    back_text: str
    source: Optional[str]


SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _read_text_arg_pair(text_arg: Optional[str], file_arg: Optional[str], label: str) -> str:
    if text_arg and file_arg:
        print(f"Error: provide either --{label}-text or --{label}-file, not both", file=sys.stderr)
        sys.exit(2)
    if text_arg:
        return text_arg
    if file_arg:
        try:
            return Path(file_arg).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"Error: file not found for --{label}-file: {file_arg}", file=sys.stderr)
            sys.exit(2)
    return ""


def _ensure_parent_dir(path: Path) -> None:
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def _ensure_table(conn: sqlite3.Connection, table: str) -> None:
    if not SAFE_TABLE_NAME.match(table):
        raise ValueError("Unsafe table name. Use alphanumerics and underscores only, not starting with a digit.")
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            source TEXT,
            front_text TEXT,
            back_text TEXT,
            cardholder_name TEXT,
            card_number_masked TEXT,
            card_number_full TEXT,
            card_last4 TEXT,
            expiry_date TEXT,
            cvv_cvc_present INTEGER NOT NULL,
            postal_address_present INTEGER NOT NULL,
            extraction_json TEXT NOT NULL
        )
        """
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_created_at ON {table}(created_at)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_last4 ON {table}(card_last4)")


def _masked_pan(pan: str) -> str:
    if not pan or len(pan) < 4:
        return pan
    return ("*" * (len(pan) - 4)) + pan[-4:]


def _to_bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def _insert_row(
    conn: sqlite3.Connection,
    table: str,
    source: Optional[str],
    front_text: str,
    back_text: str,
    extraction: Dict[str, Any],
    store_full_pan: bool,
) -> int:
    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    # Derive number fields from extraction
    extracted_number = extraction.get("card_number")

    # If the extractor returned a masked value, we need to derive last4 from it
    last4: Optional[str] = None
    card_number_masked: Optional[str] = None
    card_number_full: Optional[str] = None

    if extracted_number:
        # Heuristic: if contains a '*', treat as masked
        if "*" in extracted_number:
            card_number_masked = extracted_number
            last4 = extracted_number[-4:]
        else:
            # Treat as full; mask for storage and optionally store full
            last4 = extracted_number[-4:]
            card_number_masked = _masked_pan(extracted_number)
            if store_full_pan:
                card_number_full = extracted_number

    payload = {
        "created_at": now_iso,
        "source": source,
        "front_text": front_text,
        "back_text": back_text,
        "cardholder_name": extraction.get("cardholder_name"),
        "card_number_masked": card_number_masked,
        "card_number_full": card_number_full,
        "card_last4": last4,
        "expiry_date": extraction.get("expiry_date"),
        "cvv_cvc_present": _to_bool_int(extraction.get("cvv_cvc_present", False)),
        "postal_address_present": _to_bool_int(extraction.get("postal_address_present", False)),
        "extraction_json": json.dumps(extraction, separators=(",", ":")),
    }

    placeholders = ", ".join(":" + k for k in payload.keys())
    columns = ", ".join(payload.keys())
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    with conn:
        cur = conn.execute(sql, payload)
        return int(cur.lastrowid)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract card details from front/back text and store in SQLite",
    )
    # Inputs
    parser.add_argument("--front-text", type=str, help="Front-of-card text (e.g., OCR output)")
    parser.add_argument("--front-file", type=str, help="Path to file containing front-of-card text")
    parser.add_argument("--back-text", type=str, help="Back-of-card text (e.g., OCR output)")
    parser.add_argument("--back-file", type=str, help="Path to file containing back-of-card text")

    parser.add_argument("--source", type=str, help="Optional source identifier (filename, id, etc.)")

    # DB options
    parser.add_argument("--db", type=str, default="data/cards.db", help="Path to SQLite DB file (will be created)")
    parser.add_argument("--table", type=str, default="card_extractions", help="Table name to insert into")

    # Behavior
    parser.add_argument("--store-full-pan", action="store_true", help="Store full PAN in DB (not recommended)")
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print the inserted record metadata as JSON"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not write to DB; just print extraction JSON"
    )

    # Extraction behavior passthrough: whether to return full PAN from extractor
    parser.add_argument(
        "--extract-full-pan",
        action="store_true",
        help="Ask extractor for full PAN (still masked for storage unless --store-full-pan)",
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    front_text = _read_text_arg_pair(args.front_text, args.front_file, "front")
    back_text = _read_text_arg_pair(args.back_text, args.back_file, "back")

    if not front_text and not back_text:
        print("Error: provide at least one of front/back text or files", file=sys.stderr)
        sys.exit(2)

    merged = "\n".join([s for s in [front_text.strip(), back_text.strip()] if s])

    extraction = extract_card_info(merged, return_full_pan=bool(args.extract_full_pan))

    if args.dry_run:
        print(json.dumps(extraction, indent=2 if args.pretty else None))
        return

    db_path = Path(args.db)
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_table(conn, args.table)
        row_id = _insert_row(
            conn=conn,
            table=args.table,
            source=args.source,
            front_text=front_text,
            back_text=back_text,
            extraction=extraction,
            store_full_pan=bool(args.store_full_pan),
        )
    finally:
        conn.close()

    out = {
        "id": row_id,
        "db": str(db_path),
        "table": args.table,
    }
    if args.pretty:
        print(json.dumps(out, indent=2))
    else:
        print(json.dumps(out, separators=(",", ":")))


if __name__ == "__main__":
    main()
