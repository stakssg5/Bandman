#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, Any, List, Optional, Set


def iter_csv(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    yield obj
            except json.JSONDecodeError:
                continue


def detect_format(path: Path, forced: Optional[str]) -> str:
    if forced and forced != "auto":
        return forced.lower()
    ext = path.suffix.lower()
    if ext in {".csv"}:
        return "csv"
    if ext in {".jsonl", ".ndjson"}:
        return "jsonl"
    return "csv"


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Extract a unique list of login identifiers (e.g., username/email) "
            "from CSV or JSONL logs."
        )
    )
    parser.add_argument("--input", required=True, help="Path to CSV or JSONL file")
    parser.add_argument(
        "--format",
        choices=["csv", "jsonl", "auto"],
        default="auto",
        help="Input format (default: auto)",
    )
    parser.add_argument(
        "--fields",
        default="username,email,user,login,login_name,login_id",
        help=(
            "Comma-separated field names to scan for login identifiers. "
            "Order matters; first non-empty field found is used."
        ),
    )
    parser.add_argument(
        "--counts",
        action="store_true",
        help="Output counts per login, sorted by frequency",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Show only the top N results (0 = all)",
    )
    parser.add_argument(
        "--output",
        help="Optional output file. If .csv, writes 'login,count' CSV; otherwise text.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    fmt = detect_format(input_path, args.format)
    records = iter_csv(input_path) if fmt == "csv" else iter_jsonl(input_path)

    field_order: List[str] = [f.strip() for f in args.fields.split(",") if f.strip()]

    # Collect logins
    counter: Counter = Counter()
    seen: Set[str] = set()

    for rec in records:
        chosen_value: Optional[str] = None
        for field_name in field_order:
            if field_name in rec and rec[field_name] not in (None, ""):
                chosen_value = str(rec[field_name]).strip()
                break
        if not chosen_value:
            continue
        if args.counts:
            counter.update([chosen_value])
        else:
            seen.add(chosen_value)

    # Prepare output
    lines: List[str] = []
    if args.counts:
        items = counter.most_common()
        if args.top and args.top > 0:
            items = items[: args.top]
        if args.output and str(args.output).lower().endswith(".csv"):
            # Will handle CSV writing later below
            pass
        else:
            for login, cnt in items:
                lines.append(f"{login}\t{cnt}")
    else:
        items = sorted(seen)
        if args.top and args.top > 0:
            items = items[: args.top]
        lines = list(items)

    # Write output
    if args.output:
        out_path = Path(args.output)
        if out_path.suffix.lower() == ".csv":
            with out_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if args.counts:
                    writer.writerow(["login", "count"])
                    for login, cnt in (counter.most_common(args.top) if args.top else counter.most_common()):
                        writer.writerow([login, cnt])
                else:
                    writer.writerow(["login"])
                    for login in (lines if lines else []):
                        writer.writerow([login])
        else:
            with out_path.open("w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
    else:
        for line in lines:
            print(line)


if __name__ == "__main__":
    main()
